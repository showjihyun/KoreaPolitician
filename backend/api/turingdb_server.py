from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from core.graph_storage import graph_storage
from core.db_config import db_config_from_env, env
from scripts.simple_importer import SimpleImporter
from core.image_manager import image_manager
import logging
from collections import deque
import datetime
from pydantic import BaseModel
from contextlib import asynccontextmanager


logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """기동 시 DB 커넥션 풀을 열고 데이터를 적재하며, 종료 시 풀을 닫는다."""
    # 빈 문자열 환경변수(미등록 시크릿)를 미설정으로 처리한다.
    await graph_storage.init_db(db_config_from_env())

    json_file = "data/assembly_members_complete.json"
    # 노드가 없으면 JSON 에서 최초 임포트
    if os.path.exists(json_file) and (await graph_storage.get_statistics())["total_nodes"] == 0:
        logging.info("Loading data on startup...")
        importer = SimpleImporter()
        # 노드/엣지를 모아 한 트랜잭션으로 저장한다. 건별 왕복이면 원격 DB
        # 기준으로 기동에만 수십 초가 걸려 헬스체크를 넘긴다.
        async with graph_storage.batch():
            await importer.import_data(json_file)
        logging.info("Data loaded successfully!")

    yield

    # 종료 시 커넥션 풀 반납
    await graph_storage.close()


app = FastAPI(lifespan=lifespan)

# Activity Log Queue (In-Memory, Ring Buffer)
activity_logs = deque(maxlen=50)

async def log_activity(action: str, details: str):
    await graph_storage.add_log(action, details)
    # Still keep in memory for very fast live updates if needed, 
    # but the API will primarily fetch from DB now.
    log = {
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
        "action": action,
        "details": details
    }
    activity_logs.appendleft(log)

class EdgeRequest(BaseModel):
    source: str
    target: str
    type: str
    properties: dict = {}

# CORS 설정
# allow_origins=["*"] 와 allow_credentials=True 를 함께 쓰면 스펙상 무효이며,
# Starlette 는 요청 Origin 을 그대로 반영해 사실상 모든 출처에 인증 포함
# 요청을 허용한다. 이 API 는 쿠키를 쓰지 않으므로 credentials 를 끈다.
# 배포 시 CORS_ALLOW_ORIGINS 로 출처를 좁힐 수 있다(쉼표 구분).
_origins_raw = env("CORS_ALLOW_ORIGINS")
_allow_origins = [o.strip() for o in _origins_raw.split(",")] if _origins_raw else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# 쓰기 엔드포인트 보호용 토큰. 설정하지 않으면 쓰기를 막는다.
# 공개 URL 에 무인증 write 를 열어두면 누구나 DB 를 채울 수 있다.
API_WRITE_TOKEN = env("API_WRITE_TOKEN")


def require_write_token(x_api_key: str = Header(default=None)):
    """쓰기 요청 인증. 토큰 미설정 시 엔드포인트 자체를 비활성화한다."""
    if not API_WRITE_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="쓰기 기능이 비활성화되어 있습니다. API_WRITE_TOKEN 을 설정하세요.",
        )
    if x_api_key != API_WRITE_TOKEN:
        raise HTTPException(status_code=401, detail="유효하지 않은 API 키입니다.")

# 정적 파일 서빙
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get('/api/graph/all')
async def graph_all(limit: int = Query(350, ge=1, le=1000)):
    """전체 정치인 관계 그래프 조회"""
    members = graph_storage.find_nodes("Member")
    
    # 제한된 수의 노드만 반환
    limited_members = members[:min(limit, len(members))]
    
    nodes = []
    relationships = []
    node_ids = set()
    
    # Fetch hotness scores for these members
    hotness_map = {}
    try:
        async with graph_storage.connection() as conn:
            async with conn.cursor() as cur:
                # 화제성은 뉴스와 유튜브를 합친 값이다. 총점만 주면 화면에서
                # "종합" 이라는 사실이 드러나지 않으므로 플랫폼별 소계도 함께 준다.
                await cur.execute("""
                    SELECT s.member_name, s.current_hot_score, s.top_platform,
                           COALESCE(SUM(h.hot_score) FILTER (WHERE h.platform = 'News'), 0),
                           COALESCE(SUM(h.hot_score) FILTER (WHERE h.platform = 'YouTube'), 0)
                    FROM public.politician_hotness_summary s
                    LEFT JOIN public.politician_sns_hotness h
                           ON h.member_name = s.member_name
                          AND h.collected_at > NOW() - INTERVAL '1 day'
                    GROUP BY s.member_name, s.current_hot_score, s.top_platform
                """)
                for r in await cur.fetchall():
                    hotness_map[r[0]] = {
                        "score": r[1], "platform": r[2],
                        "news": float(r[3] or 0), "youtube": float(r[4] or 0),
                    }
    except Exception as e:
        logging.warning(f"hotness summary 조회 실패: {e}")

    for member in limited_members:
        # 이미지 URL 및 화제성 점수 추가
        name = member["properties"].get("name")
        member_id = member["id"]
        
        if name:
            member["properties"]["image_url"] = f"/api/images/{name}.jpg"
            member["properties"]["thumbnail_url"] = f"/api/images/{name}.jpg?thumbnail=true"
            # SNS 화제성 점수 통합
            hot_info = hotness_map.get(name, {"score": 0, "platform": None, "news": 0, "youtube": 0})
            member["properties"]["hot_score"] = hot_info["score"]
            member["properties"]["hot_platform"] = hot_info["platform"]
            member["properties"]["hot_news"] = hot_info.get("news", 0)
            member["properties"]["hot_youtube"] = hot_info.get("youtube", 0)
        
        if member_id not in node_ids:
            nodes.append(member)
            node_ids.add(member_id)
        
        # 각 의원의 관계 추가.
        # 응답 크기를 위해 의원당 10개로 자르는데, 순서대로 자르면 호불호
        # 관계가 소속/지역/SNS 언급에 밀려 잘려 나간다. 이 화면의 핵심은
        # 호불호이므로 감정 관계를 먼저 담는다.
        rels = graph_storage.get_relationships(member_id, direction="out")
        rels.sort(key=lambda r: 0 if r["edge"]["type"].endswith("_SENTIMENT") else 1)
        for rel in rels[:10]:  # 각 의원당 최대 10개 관계
            relationships.append(rel["edge"])
            if rel["node"] and rel["node"]["id"] not in node_ids:
                # 연결된 노드에도 이미지 및 화제성 점수 추가
                if rel["node"].get("labels") and "Member" in rel["node"]["labels"]:
                    rel_name = rel["node"]["properties"].get("name")
                    if rel_name:
                        rel["node"]["properties"]["image_url"] = f"/api/images/{rel_name}.jpg"
                        rel["node"]["properties"]["thumbnail_url"] = f"/api/images/{rel_name}.jpg?thumbnail=true"
                        hot_info = hotness_map.get(rel_name, {"score": 0, "platform": None, "news": 0, "youtube": 0})
                        rel["node"]["properties"]["hot_score"] = hot_info["score"]
                        rel["node"]["properties"]["hot_platform"] = hot_info["platform"]
                        rel["node"]["properties"]["hot_news"] = hot_info.get("news", 0)
                        rel["node"]["properties"]["hot_youtube"] = hot_info.get("youtube", 0)
                nodes.append(rel["node"])
                node_ids.add(rel["node"]["id"])
    
    return JSONResponse(content={
        "nodes": nodes,
        "relationships": relationships
    })

@app.get('/api/graph/{member_name}')
async def graph(member_name: str, depth: int = Query(2, ge=1, le=5)):
    """특정 의원의 관계 그래프 조회"""
    # 의원 검색
    members = graph_storage.find_nodes("Member", {"name": f"CONTAINS:{member_name}"})
    
    if not members:
        logging.info(f"No member found for search: {member_name}")
        return JSONResponse(content={
            "nodes": [], 
            "relationships": [], 
            "message": f"'{member_name}'에 대한 검색 결과가 없습니다."
        })
    
    member_id = members[0]["id"]
    data = graph_storage.get_path(member_id, max_depth=depth)
    
    # Fetch hotness scores for these members
    hotness_map = {}
    try:
        async with graph_storage.connection() as conn:
            async with conn.cursor() as cur:
                # 화제성은 뉴스와 유튜브를 합친 값이다. 총점만 주면 화면에서
                # "종합" 이라는 사실이 드러나지 않으므로 플랫폼별 소계도 함께 준다.
                await cur.execute("""
                    SELECT s.member_name, s.current_hot_score, s.top_platform,
                           COALESCE(SUM(h.hot_score) FILTER (WHERE h.platform = 'News'), 0),
                           COALESCE(SUM(h.hot_score) FILTER (WHERE h.platform = 'YouTube'), 0)
                    FROM public.politician_hotness_summary s
                    LEFT JOIN public.politician_sns_hotness h
                           ON h.member_name = s.member_name
                          AND h.collected_at > NOW() - INTERVAL '1 day'
                    GROUP BY s.member_name, s.current_hot_score, s.top_platform
                """)
                for r in await cur.fetchall():
                    hotness_map[r[0]] = {
                        "score": r[1], "platform": r[2],
                        "news": float(r[3] or 0), "youtube": float(r[4] or 0),
                    }
    except Exception as e:
        logging.warning(f"hotness summary 조회 실패: {e}")

    # 이미지 URL 및 화제성 점수 추가
    for node in data["nodes"]:
        if node.get("labels") and "Member" in node["labels"]:
            name = node["properties"].get("name")
            if name:
                node["properties"]["image_url"] = f"/api/images/{name}.jpg"
                node["properties"]["thumbnail_url"] = f"/api/images/{name}.jpg?thumbnail=true"
                hot_info = hotness_map.get(name, {"score": 0, "platform": None, "news": 0, "youtube": 0})
                node["properties"]["hot_score"] = hot_info["score"]
                node["properties"]["hot_platform"] = hot_info["platform"]
                node["properties"]["hot_news"] = hot_info.get("news", 0)
                node["properties"]["hot_youtube"] = hot_info.get("youtube", 0)
    
    return JSONResponse(content=data)

@app.get('/api/sns/hot_posts/{member_name}')
async def sns_hot_posts(member_name: str, limit: int = Query(5, ge=1, le=100)):
    """특정 의원의 화제가 된 SNS 포스트 수집"""
    try:
        async with graph_storage.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT platform, author_type, content_preview, engagement_data, hot_score, collected_at 
                    FROM public.politician_sns_hotness
                    WHERE member_name = %s
                    ORDER BY hot_score DESC, collected_at DESC
                    LIMIT %s
                """, (member_name, limit))
                rows = await cur.fetchall()
                results = [{
                    "platform": r[0],
                    "author_type": r[1],
                    "content": r[2],
                    "engagement": r[3],
                    "hot_score": r[4],
                    "date": r[5].strftime("%Y-%m-%d %H:%M:%S")
                } for r in rows]
                return JSONResponse(content={"posts": results})
    except Exception as e:
        return JSONResponse(content={"error": str(e), "posts": []}, status_code=500)

@app.get('/api/sns/trends')
async def sns_trends(limit: int = Query(20, ge=1, le=200)):
    """전체 의원 중 가장 화제가 되는 SNS 포스트 수집"""
    try:
        async with graph_storage.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT member_name, platform, author_type, content_preview, engagement_data, hot_score, collected_at 
                    FROM public.politician_sns_hotness
                    ORDER BY hot_score DESC, collected_at DESC
                    LIMIT %s
                """, (limit,))
                rows = await cur.fetchall()
                results = [{
                    "member_name": r[0],
                    "platform": r[1],
                    "author_type": r[2],
                    "content": r[3],
                    "engagement": r[4],
                    "hot_score": r[5],
                    "date": r[6].strftime("%Y-%m-%d %H:%M:%S")
                } for r in rows]
                return JSONResponse(content={"trends": results})
    except Exception as e:
        return JSONResponse(content={"error": str(e), "trends": []}, status_code=500)

@app.get('/api/search/{member_name}')
def search(member_name: str):
    """의원 검색"""
    members = graph_storage.find_nodes("Member", {"name": f"CONTAINS:{member_name}"})
    
    results = []
    for member in members:
        props = member["properties"]
        name = props.get("name")
        results.append({
            "name": name,
            "id": props.get("id"),
            "party": props.get("party"),
            "region": props.get("region"),
            "election_count": props.get("election_count"),
            "image_url": f"/api/images/{name}.jpg" if name else None,
            "thumbnail_url": f"/api/images/{name}.jpg?thumbnail=true" if name else None,
        })
    
    return JSONResponse(content={"members": results})

@app.post('/api/edge')
async def add_edge(req: EdgeRequest, _auth: None = Depends(require_write_token)):
    """관계 추가"""
    # Find source and target nodes by name
    src_nodes = graph_storage.find_nodes("Member", {"name": f"CONTAINS:{req.source}"})
    tgt_nodes = graph_storage.find_nodes("Member", {"name": f"CONTAINS:{req.target}"})

    if not src_nodes:
        return JSONResponse(content={"message": f"Source member '{req.source}' not found"}, status_code=404)
    if not tgt_nodes:
        return JSONResponse(content={"message": f"Target member '{req.target}' not found"}, status_code=404)

    src_id = src_nodes[0]["id"]
    tgt_id = tgt_nodes[0]["id"]

    try:
        edge = await graph_storage.add_edge(src_id, tgt_id, req.type, req.properties)
    except Exception as e:
        # 저장 실패를 200 으로 돌려주면 크롤러가 성공한 줄 안다.
        logging.exception("엣지 저장 실패")
        return JSONResponse(content={"message": f"엣지 저장 실패: {e}"}, status_code=500)
    
    # Log Activity
    await log_activity("New Relation", f"{req.source} -> {req.target} ({req.type})")
    
    return JSONResponse(content={"message": "Edge added", "edge": edge})

@app.get('/api/stats')
async def stats():
    """통계 정보"""
    stats = await graph_storage.get_statistics()
    return JSONResponse(content=stats)

@app.get('/api/images/{filename}')
def serve_image(filename: str, thumbnail: bool = False):
    """이미지 서빙"""
    return image_manager.serve_image(filename, thumbnail=thumbnail)

@app.get('/api/dcp/context')
def dcp_context(subject: str, target: str):
    """
    DCP 알고리즘을 위한 문맥(동료 및 그들의 타겟에 대한 태도) 조회
    - 논문 정의에 따라 '동료(Ally)'는 동일 정당 소석 또는 우호 관계인 인물임.
    """
    # 1. Find Subject node
    sub_nodes = graph_storage.find_nodes("Member", {"name": f"CONTAINS:{subject}"})
    if not sub_nodes:
        return JSONResponse(content={"allies_context": []})
    
    sub_node = sub_nodes[0]
    sub_id = sub_node["id"]
    sub_party = sub_node["properties"].get("party")
    
    # 2. Find Allies
    allies = set()
    
    # Strategy A: Outgoing Positive Sentiment
    rels_out = graph_storage.get_relationships(sub_id, direction="out")
    for r in rels_out:
        if r["edge"]["type"] == "POSITIVE_SENTIMENT":
             if r["node"]: allies.add(r["node"]["id"])

    # Strategy B: Same Party (Paper's 'Organizational Resonance')
    if sub_party:
        party_members = graph_storage.find_nodes("Member", {"party": sub_party})
        for pm in party_members:
            if pm["id"] != sub_id:
                allies.add(pm["id"])
    
    # 3. For each Ally, check relation to Target
    tgt_nodes = graph_storage.find_nodes("Member", {"name": f"CONTAINS:{target}"})
    if not tgt_nodes:
        return JSONResponse(content={"allies_context": []})
    tgt_id = tgt_nodes[0]["id"]
    
    context_data = []
    
    for ally_id in allies:
        # Fetch relationships from Ally to Target
        ally_rels = graph_storage.get_relationships(ally_id, direction="out")
        for ar in ally_rels:
            if ar["node"]["id"] == tgt_id:
                # Found relation Ally -> Target
                edge = ar["edge"]
                if edge["type"] in ["POSITIVE_SENTIMENT", "NEGATIVE_SENTIMENT"]:
                    weight = edge["properties"].get("score", 0.5)
                    count = edge["properties"].get("count", 1)
                    
                    # Heuristic: weight boosted by count (frequency of attack/support)
                    effective_weight = weight * (1 + (0.05 * count)) 
                    
                    context_data.append({
                        "ally": ar["node"]["properties"].get("name"),
                        "relation": edge["type"],
                        "weight": effective_weight
                    })
                    
    return JSONResponse(content={"allies_context": context_data})

@app.get('/api/activity_logs')
async def get_activity_logs(limit: int = Query(50, ge=1, le=200),
                            history: bool = False, search: str = None):
    """활동 로그 조회 (기본값: 최근 50개)"""
    if history:
        # DB에서 히스토리 조회
        logs = await graph_storage.get_logs(limit=limit if limit <= 200 else 200, search=search)
        return JSONResponse(content={"logs": logs})
    
    # In-memory 필터링 (간단 검색)
    res_logs = list(activity_logs)
    if search:
        res_logs = [log for log in res_logs if search in log["details"] or search in log["action"]]
        
    return JSONResponse(content={"logs": res_logs[:limit]})

@app.get('/api/images')
def list_images():
    """이미지 목록"""
    images = image_manager.get_all_images()
    return JSONResponse(content={"images": images})

@app.get('/api/intelligence')
async def get_intelligence():
    """상업용 인사이트 조회를 위한 지능형 분석 데이터 제공"""
    data = await graph_storage.get_intelligence()
    return JSONResponse(content=data)

@app.get('/health')
async def health():
    """헬스체크.

    예전에는 DB 를 보지 않고 항상 healthy 를 반환해서, DB 가 끊겨도
    Render 헬스체크를 통과한 채 빈 그래프를 200 으로 서빙했다.
    """
    db_ok = await graph_storage.ping()
    body = {
        "status": "healthy" if db_ok else "degraded",
        "database": "up" if db_ok else "down",
        "nodes": len(graph_storage.nodes),
    }
    return JSONResponse(content=body, status_code=200 if db_ok else 503)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "turingdb_server:app",
        host="0.0.0.0",
        port=5000,
        reload=True
    )
