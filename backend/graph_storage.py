"""
간단한 인메모리 그래프 저장소
TuringDB 대신 사용할 수 있는 경량 그래프 데이터베이스
"""

import json
from typing import Dict, List, Any, Optional
from collections import defaultdict
import psycopg2
import json
import logging

logger = logging.getLogger(__name__)


class GraphStorage:
    def __init__(self):
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: List[Dict[str, Any]] = []
        self.node_index: Dict[str, List[str]] = defaultdict(list)  # label -> node_ids
        self.db_config = None

    def init_db(self, db_config):
        """DB 초기화 및 로드"""
        self.db_config = db_config
        self.create_tables()
        self.load_from_db()

    def create_tables(self):
        """테이블 생성"""
        if not self.db_config: return
        try:
            with psycopg2.connect(**self.db_config) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS turing_nodes (
                            id TEXT PRIMARY KEY,
                            labels TEXT[],
                            properties JSONB
                        );
                        CREATE TABLE IF NOT EXISTS turing_edges (
                            source_id TEXT,
                            target_id TEXT,
                            type TEXT,
                            properties JSONB,
                            PRIMARY KEY (source_id, target_id, type)
                        );
                        CREATE TABLE IF NOT EXISTS turing_logs (
                            id SERIAL PRIMARY KEY,
                            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            action TEXT,
                            details TEXT
                        );
                    """)
                conn.commit()
            logger.info("TuringDB persistence tables ready.")
        except Exception as e:
            logger.error(f"Failed to init tables: {e}")

    def load_from_db(self):
        """DB에서 데이터 로드"""
        if not self.db_config: return
        try:
            with psycopg2.connect(**self.db_config) as conn:
                with conn.cursor() as cur:
                    # Load Nodes
                    cur.execute("SELECT id, labels, properties FROM turing_nodes")
                    rows = cur.fetchall()
                    for r in rows:
                        self.nodes[r[0]] = {"id": r[0], "labels": r[1], "properties": r[2]}
                        for label in r[1]:
                            self.node_index[label].append(r[0])
                    logger.info(f"Loaded {len(self.nodes)} nodes from DB.")

                    # Load Edges
                    cur.execute("SELECT source_id, target_id, type, properties FROM turing_edges")
                    rows = cur.fetchall()
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

    def _persist_node(self, node_id, labels, properties):
        if not self.db_config: return
        try:
            with psycopg2.connect(**self.db_config) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO turing_nodes (id, labels, properties)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (id) DO UPDATE 
                        SET labels = EXCLUDED.labels, properties = EXCLUDED.properties
                    """, (node_id, labels, json.dumps(properties)))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to persist node {node_id}: {e}")

    def _persist_edge(self, from_id, to_id, rel_type, properties):
        if not self.db_config: return
        try:
            with psycopg2.connect(**self.db_config) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO turing_edges (source_id, target_id, type, properties)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (source_id, target_id, type) DO UPDATE 
                        SET properties = EXCLUDED.properties
                    """, (from_id, to_id, rel_type, json.dumps(properties)))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to persist edge: {e}")

    def add_log(self, action: str, details: str):
        """활동 로그 추가 및 저장"""
        if not self.db_config: return
        try:
            with psycopg2.connect(**self.db_config) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO turing_logs (action, details)
                        VALUES (%s, %s)
                    """, (action, details))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to add log: {e}")

    def get_logs(self, limit: int = 100, search: str = None) -> List[Dict[str, Any]]:
        """로그 조회 (검색 지원)"""
        if not self.db_config: return []
        try:
            with psycopg2.connect(**self.db_config) as conn:
                with conn.cursor() as cur:
                    query = "SELECT id, timestamp, action, details FROM turing_logs"
                    params = []
                    if search:
                        query += " WHERE details ILIKE %s OR action ILIKE %s"
                        params = [f"%{search}%", f"%{search}%"]
                    
                    query += " ORDER BY id DESC LIMIT %s"
                    params.append(limit)
                    
                    cur.execute(query, tuple(params))
                    rows = cur.fetchall()
                    return [{
                        "id": r[0],
                        "timestamp": r[1].strftime("%Y-%m-%d %H:%M:%S"),
                        "action": r[2],
                        "details": r[3]
                    } for r in rows]
        except Exception as e:
            logger.error(f"Failed to get logs: {e}")
            return []
        
    def add_node(self, node_id: str, labels: List[str], properties: Dict[str, Any]):
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
        
        self._persist_node(node_id, labels, properties)
    
    def add_edge(self, from_id: str, to_id: str, rel_type: str, properties: Dict[str, Any] = None):
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
            
        self._persist_edge(from_id, to_id, rel_type, edge["properties"])
    
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
    
    def get_statistics(self) -> Dict[str, Any]:
        """통계 정보"""
        stats = {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
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

    def get_intelligence(self) -> Dict[str, Any]:
        """정기적인 인사이트 리포트를 위한 인텔리전스 데이터 산출"""
        if not self.nodes: return {
            "top_influencers": [],
            "top_conflicts": [],
            "recent_events": [],
            "stats": self.get_statistics()
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
        recent_logs = self.get_logs(limit=10)

        return {
            "top_influencers": influencer_data,
            "top_conflicts": conflict_data,
            "recent_events": recent_logs,
            "stats": self.get_statistics()
        }
    
    def clear(self):
        """모든 데이터 삭제"""
        self.nodes.clear()
        self.edges.clear()
        self.node_index.clear()


# 전역 그래프 저장소
graph_storage = GraphStorage()
