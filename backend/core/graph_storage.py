"""
간단한 인메모리 그래프 저장소
TuringDB 대신 사용할 수 있는 경량 그래프 데이터베이스

DB 접근은 psycopg3 의 비동기 커넥션 풀을 사용한다. 이전 구현은 메서드를
호출할 때마다 psycopg2.connect() 로 새 커넥션을 열고 close() 하지 않아,
노드 하나를 저장할 때마다 커넥션이 하나씩 늘어났다. 지금은 모든 DB 메서드가
async 이며 풀에서 커넥션을 빌린 뒤 컨텍스트 매니저 종료 시 반드시 반납한다.
"""

import asyncio
import json
import logging
import os
import sys
import threading
from typing import Dict, List, Any, Optional
from collections import defaultdict

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    # psycopg3 의 비동기 구현은 Windows 기본 ProactorEventLoop 를 지원하지 않는다.
    #   "Psycopg cannot use the 'ProactorEventLoop' to run in async mode"
    # 배포 대상인 Linux 는 SelectorEventLoop 가 기본이라 영향이 없고,
    # 이 설정은 Windows 로컬 개발/크롤러 실행에서만 적용된다.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class GraphStorage:
    def __init__(self):
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: List[Dict[str, Any]] = []
        self.node_index: Dict[str, List[str]] = defaultdict(list)  # label -> node_ids
        self.db_config = None
        self._pool: Optional[AsyncConnectionPool] = None

    async def init_db(self, db_config):
        """DB 초기화 및 로드"""
        self.db_config = db_config
        await self._ensure_pool()
        await self.create_tables()
        await self.load_from_db()

    async def _ensure_pool(self):
        """비동기 커넥션 풀 준비 (최초 1회)"""
        if self._pool is not None or not self.db_config:
            return
        self._pool = AsyncConnectionPool(
            make_conninfo(**self.db_config),
            min_size=1,
            max_size=int(os.environ.get("DB_POOL_MAX_SIZE", "5")),
            open=False,
            # Supabase Supavisor(6543) 같은 트랜잭션 풀러는 prepared statement 를
            # 지원하지 않으므로 비활성화한다.
            kwargs={"prepare_threshold": None},
        )
        await self._pool.open(wait=True, timeout=30)
        logger.info("DB connection pool opened.")

    async def close(self):
        """커넥션 풀 종료. 애플리케이션 shutdown 에서 호출한다."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("DB connection pool closed.")

    def connection(self):
        """풀에서 커넥션을 빌리는 비동기 컨텍스트 매니저.
        블록을 벗어나면 커밋(예외 시 롤백) 후 풀로 반드시 반납된다."""
        if not self._pool:
            raise RuntimeError("DB pool is not initialized. call init_db() first.")
        return self._pool.connection()

    async def fetch_all(self, query: str, params: tuple = ()) -> List[tuple]:
        """임의 SELECT 를 같은 풀로 실행한다. API 라우트가 직접 커넥션을
        열지 않도록 하기 위한 헬퍼."""
        if not self._pool:
            return []
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                return await cur.fetchall()

    async def create_tables(self):
        """테이블 생성"""
        if not self._pool: return
        try:
            async with self._pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS turing_nodes (
                            id TEXT PRIMARY KEY,
                            labels TEXT[],
                            properties JSONB
                        );
                        CREATE TABLE IF NOT EXISTS turing_edges (
                            source_id TEXT,
                            target_id TEXT,
                            type TEXT,
                            properties JSONB, -- Includes score, social_impact_score, impact_factors, etc.
                            PRIMARY KEY (source_id, target_id, type)
                        );
                        CREATE TABLE IF NOT EXISTS turing_logs (
                            id SERIAL PRIMARY KEY,
                            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            action TEXT,
                            details TEXT
                        );
                        CREATE TABLE IF NOT EXISTS public.politician_sns_hotness (
                            id SERIAL PRIMARY KEY,
                            member_name TEXT,
                            platform TEXT,
                            author_type TEXT,
                            post_id TEXT,
                            content_preview TEXT,
                            engagement_data JSONB,
                            hot_score FLOAT,
                            sentiment_score FLOAT,
                            collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE (member_name, platform, post_id)
                        );
                        CREATE TABLE IF NOT EXISTS public.politician_hotness_summary (
                            member_name TEXT PRIMARY KEY,
                            current_hot_score FLOAT,
                            cumulative_hot_score FLOAT DEFAULT 0,
                            top_platform TEXT,
                            daily_change FLOAT DEFAULT 0,
                            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                        CREATE TABLE IF NOT EXISTS system_settings (
                            key TEXT PRIMARY KEY,
                            value TEXT,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                        -- 초기 데이터 설정
                        INSERT INTO system_settings (key, value) VALUES ('last_data_update', CURRENT_DATE::TEXT)
                        ON CONFLICT (key) DO NOTHING;
                    """)
            logger.info("TuringDB persistence tables ready.")
        except Exception as e:
            logger.error(f"Failed to init tables: {e}")

    async def load_from_db(self):
        """DB에서 데이터 로드"""
        if not self._pool: return
        try:
            async with self._pool.connection() as conn:
                async with conn.cursor() as cur:
                    # Load Nodes
                    await cur.execute("SELECT id, labels, properties FROM turing_nodes")
                    rows = await cur.fetchall()
                    for r in rows:
                        self.nodes[r[0]] = {"id": r[0], "labels": r[1], "properties": r[2]}
                        for label in r[1]:
                            if r[0] not in self.node_index[label]:
                                self.node_index[label].append(r[0])
                    logger.info(f"Loaded {len(self.nodes)} nodes from DB.")

                    # Load Edges
                    await cur.execute("SELECT source_id, target_id, type, properties FROM turing_edges")
                    rows = await cur.fetchall()
                    for r in rows:
                        self.edges.append({
                            "from": r[0],
                            "to": r[1],
                            "type": r[2],
                            "properties": r[3]
                        })
                    logger.info(f"Loaded {len(self.edges)} edges from DB.")
        except Exception as e:
            logger.error(f"Failed to load from DB: {e}")

    async def _persist_node(self, node_id, labels, properties):
        if not self._pool: return
        try:
            async with self._pool.connection() as conn:
                await conn.execute("""
                        INSERT INTO turing_nodes (id, labels, properties)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (id) DO UPDATE 
                        SET labels = EXCLUDED.labels, properties = EXCLUDED.properties
                    """, (node_id, labels, Jsonb(properties)))
        except Exception as e:
            logger.error(f"Failed to persist node {node_id}: {e}")

    async def _persist_edge(self, from_id, to_id, rel_type, properties):
        if not self._pool: return
        try:
            async with self._pool.connection() as conn:
                await conn.execute("""
                        INSERT INTO turing_edges (source_id, target_id, type, properties)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (source_id, target_id, type) DO UPDATE 
                        SET properties = EXCLUDED.properties
                    """, (from_id, to_id, rel_type, Jsonb(properties)))
        except Exception as e:
            logger.error(f"Failed to persist edge: {e}")

    async def add_log(self, action: str, details: str):
        """활동 로그 추가 및 저장"""
        if not self._pool: return
        try:
            async with self._pool.connection() as conn:
                await conn.execute("""
                        INSERT INTO turing_logs (action, details)
                        VALUES (%s, %s)
                    """, (action, details))
        except Exception as e:
            logger.error(f"Failed to add log: {e}")

    async def get_logs(self, limit: int = 100, search: str = None) -> List[Dict[str, Any]]:
        """로그 조회 (검색 지원)"""
        if not self._pool: return []
        try:
            async with self._pool.connection() as conn:
                async with conn.cursor() as cur:
                    query = "SELECT id, timestamp, action, details FROM turing_logs"
                    params = []
                    if search:
                        query += " WHERE details ILIKE %s OR action ILIKE %s"
                        params = [f"%{search}%", f"%{search}%"]
                    
                    query += " ORDER BY id DESC LIMIT %s"
                    params.append(limit)
                    
                    await cur.execute(query, tuple(params))
                    rows = await cur.fetchall()
                    return [{
                        "id": r[0],
                        "timestamp": r[1].strftime("%Y-%m-%d %H:%M:%S"),
                        "action": r[2],
                        "details": r[3]
                    } for r in rows]
        except Exception as e:
            logger.error(f"Failed to get logs: {e}")
            return []
        
    async def add_node(self, node_id: str, labels: List[str], properties: Dict[str, Any]):
        """노드 추가"""
        self.nodes[node_id] = {
            "id": node_id,
            "labels": labels,
            "properties": properties
        }
        
        # 인덱스 업데이트
        for label in labels:
            if node_id not in self.node_index[label]:
                self.node_index[label].append(node_id)
        
        await self._persist_node(node_id, labels, properties)
    
    async def add_edge(self, from_id: str, to_id: str, rel_type: str, properties: Dict[str, Any] = None):
        """엣지 추가"""
        edge = {
            "from": from_id,
            "to": to_id,
            "type": rel_type,
            "properties": properties or {}
        }
        
        # Check if edge already exists to update it? 
        # For simplicity, append to list (in-memory) but persist with upsert logic
        # Ideally we should dedup in memory too.
        existing = next((e for e in self.edges if e["from"] == from_id and e["to"] == to_id and e["type"] == rel_type), None)
        if existing:
            # Update properties
            existing["properties"].update(properties or {})
        else:
            self.edges.append(edge)
            
        await self._persist_edge(from_id, to_id, rel_type, edge["properties"])
    
    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """노드 조회"""
        return self.nodes.get(node_id)
    
    def find_nodes(self, label: str, properties: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """노드 검색"""
        node_ids = self.node_index.get(label, [])
        results = []
        
        for node_id in node_ids:
            node = self.nodes[node_id]
            
            # 속성 필터링
            if properties:
                match = True
                for key, value in properties.items():
                    node_value = node["properties"].get(key)
                    
                    # CONTAINS 연산 지원
                    if isinstance(value, str) and value.startswith("CONTAINS:"):
                        search_term = value.replace("CONTAINS:", "")
                        if not (node_value and search_term in str(node_value)):
                            match = False
                            break
                    elif node_value != value:
                        match = False
                        break
                
                if match:
                    results.append(node)
            else:
                results.append(node)
        
        return results
    
    def get_relationships(self, node_id: str, direction: str = "both", rel_type: str = None) -> List[Dict[str, Any]]:
        """노드의 관계 조회"""
        results = []
        
        for edge in self.edges:
            if rel_type and edge["type"] != rel_type:
                continue
            
            if direction in ["out", "both"] and edge["from"] == node_id:
                results.append({
                    "edge": edge,
                    "node": self.nodes.get(edge["to"])
                })
            
            if direction in ["in", "both"] and edge["to"] == node_id:
                results.append({
                    "edge": edge,
                    "node": self.nodes.get(edge["from"])
                })
        
        return results
    
    def get_path(self, start_id: str, max_depth: int = 2) -> Dict[str, Any]:
        """경로 탐색 (BFS)"""
        visited = set()
        queue = [(start_id, 0)]
        nodes = {}
        edges = []
        
        while queue:
            current_id, depth = queue.pop(0)
            
            if current_id in visited or depth > max_depth:
                continue
            
            visited.add(current_id)
            
            # 노드 추가
            if current_id in self.nodes:
                nodes[current_id] = self.nodes[current_id]
            
            # 관계 탐색
            if depth < max_depth:
                for rel in self.get_relationships(current_id, direction="both"):
                    edge = rel["edge"]
                    next_node = rel["node"]
                    
                    if next_node:
                        next_id = next_node["id"]
                        
                        # 엣지 추가
                        if edge not in edges:
                            edges.append(edge)
                        
                        # 큐에 추가
                        if next_id not in visited:
                            queue.append((next_id, depth + 1))
        
        return {
            "nodes": list(nodes.values()),
            "relationships": edges
        }
    
    async def get_setting(self, key: str, default: Any = None) -> Any:
        """시스템 설정 조회"""
        if not self._pool: return default
        try:
            async with self._pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT value FROM system_settings WHERE key = %s", (key,))
                    row = await cur.fetchone()
                    return row[0] if row else default
        except Exception as e:
            logger.error(f"Failed to get setting {key}: {e}")
            return default

    async def set_setting(self, key: str, value: str):
        """시스템 설정 저장"""
        if not self._pool: return
        try:
            async with self._pool.connection() as conn:
                await conn.execute("""
                        INSERT INTO system_settings (key, value, updated_at) 
                        VALUES (%s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                    """, (key, value))
        except Exception as e:
            logger.error(f"Failed to set setting {key}: {e}")

    async def get_statistics(self) -> Dict[str, Any]:
        """통계 정보"""
        stats = {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "last_updated": await self.get_setting("last_data_update", "2026-02-02"),
            "nodes_by_label": {},
            "edges_by_type": defaultdict(int)
        }
        
        # 라벨별 노드 수
        for label, node_ids in self.node_index.items():
            stats["nodes_by_label"][label] = len(node_ids)
        
        # 타입별 엣지 수
        for edge in self.edges:
            stats["edges_by_type"][edge["type"]] += 1
        
        stats["edges_by_type"] = dict(stats["edges_by_type"])
        
        return stats

    async def get_intelligence(self) -> Dict[str, Any]:
        """정기적인 인사이트 리포트를 위한 인텔리전스 데이터 산출"""
        if not self.nodes: return {
            "top_influencers": [],
            "top_conflicts": [],
            "recent_events": [],
            "stats": await self.get_statistics()
        }
        
        # 1. 탑 영향력 정치인 (Outgoing social_impact_score 합계 기준)
        node_impact = {}
        for edge in self.edges:
            src = edge["from"]
            score = edge["properties"].get("social_impact_score", 0.1)
            weight = 2.0 if "SENTIMENT" in edge["type"] else 1.0
            node_impact[src] = node_impact.get(src, 0) + (score * weight)
        
        top_influencer_ids = sorted(node_impact.items(), key=lambda x: x[1], reverse=True)[:5]
        influencer_data = []
        for nid, score in top_influencer_ids:
            node = self.nodes.get(nid)
            if node:
                influencer_data.append({
                    "id": nid,
                    "name": node["properties"].get("name"),
                    "party": node["properties"].get("party"),
                    "score": round(score, 2),
                    "image_url": f"/api/images/{node['properties'].get('name')}.jpg"
                })

        # 2. 갈등 지수 (Negative Sentiment 강도 기준)
        conflicts = [e for e in self.edges if e["type"] == "NEGATIVE_SENTIMENT"]
        top_conflicts = sorted(conflicts, key=lambda x: x["properties"].get("score", 0), reverse=True)[:5]
        conflict_data = []
        for e in top_conflicts:
            src_node = self.nodes.get(e["from"])
            tgt_node = self.nodes.get(e["to"])
            if src_node and tgt_node:
                conflict_data.append({
                    "source": src_node["properties"].get("name"),
                    "target": tgt_node["properties"].get("name"),
                    "score": e["properties"].get("score", 0),
                    "reason": e["properties"].get("reason", "갈등 양상 감지")
                })

        # 3. 최근 주요 사건
        recent_logs = await self.get_logs(limit=10)

        return {
            "top_influencers": influencer_data,
            "top_conflicts": conflict_data,
            "recent_events": recent_logs,
            "stats": await self.get_statistics()
        }
    
    def clear(self):
        """모든 데이터 삭제"""
        self.nodes.clear()
        self.edges.clear()
        self.node_index.clear()


# 전역 그래프 저장소
graph_storage = GraphStorage()


# --- 동기 배치 스크립트용 브리지 -------------------------------------------
# 크롤러는 Playwright 의 sync API 를 사용한다. sync API 는 실행 중인 asyncio
# 루프 안에서 호출할 수 없으므로 크롤러 자체를 async 로 만들 수 없다. 한편
# 비동기 커넥션 풀은 생성된 이벤트 루프에 묶여 있어서, asyncio.run() 을 매번
# 호출하면 새 루프가 생겨 풀이 깨진다.
#
# 그래서 전용 스레드에서 이벤트 루프를 하나 계속 돌리고, 동기 코드에서는
# run_coroutine_threadsafe 로 작업을 넘긴다. 크롤러가 ThreadPoolExecutor 로
# 여러 스레드에서 동시에 호출해도 안전하며, 호출하는 스레드에는 실행 중인
# 루프가 없으므로 Playwright sync API 와도 충돌하지 않는다.
_sync_loop: Optional[asyncio.AbstractEventLoop] = None
_sync_thread: Optional[threading.Thread] = None
_sync_lock = threading.Lock()


def _ensure_sync_loop() -> asyncio.AbstractEventLoop:
    global _sync_loop, _sync_thread
    with _sync_lock:
        if _sync_loop is not None and not _sync_loop.is_closed():
            return _sync_loop
        _sync_loop = asyncio.new_event_loop()
        _sync_thread = threading.Thread(
            target=_sync_loop.run_forever,
            name="graph-storage-loop",
            daemon=True,
        )
        _sync_thread.start()
        return _sync_loop


def run_sync(coro):
    """동기 코드에서 async 저장소 메서드를 실행한다. 스레드 안전."""
    loop = _ensure_sync_loop()
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


def close_sync(storage: Optional["GraphStorage"] = None):
    """run_sync 로 열린 커넥션 풀과 전용 루프를 정리한다.
    배치 스크립트 종료 시 finally 에서 호출할 것.

    storage 를 생략하면 전역 graph_storage 를 닫는다. 별도 인스턴스를
    run_sync 로 썼다면 그 인스턴스를 넘겨야 풀이 닫힌다. 루프를 멈추기 전에
    풀을 닫아야 백그라운드 태스크가 남지 않는다."""
    global _sync_loop, _sync_thread
    with _sync_lock:
        loop, thread = _sync_loop, _sync_thread
        _sync_loop, _sync_thread = None, None
    if loop is None or loop.is_closed():
        return
    target = storage if storage is not None else graph_storage
    try:
        asyncio.run_coroutine_threadsafe(target.close(), loop).result(timeout=30)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=10)
        loop.close()
