from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from core.graph_storage import graph_storage
from scripts.simple_importer import SimpleImporter
from core.image_manager import image_manager
import logging
from collections import deque
import datetime
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)

app = FastAPI()

# Activity Log Queue (In-Memory, Ring Buffer)
activity_logs = deque(maxlen=50)

def log_activity(action: str, details: str):
    graph_storage.add_log(action, details)
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 서빙
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# 서버 시작 시 데이터 로드
@app.on_event("startup")
async def startup_event():
    """서버 시작 시 데이터 로드"""
    # DB Init
    db_config = {
        'host': os.environ.get('POSTGRES_HOST', 'localhost'),
        'port': int(os.environ.get('POSTGRES_PORT', 5432)),
        'user': os.environ.get('POSTGRES_USER', 'postgres'),
        'password': os.environ.get('POSTGRES_PASSWORD', '1234'),
        'dbname': os.environ.get('POSTGRES_DB', 'postgres'),
    }
    graph_storage.init_db(db_config)

    json_file = "data/assembly_members_complete.json"
    # Check if nodes exist, if not import from JSON
    if os.path.exists(json_file) and graph_storage.get_statistics()["total_nodes"] == 0:
        logging.info("Loading data on startup...")
        importer = SimpleImporter()
        importer.import_data(json_file)
        logging.info("Data loaded successfully!")

@app.get('/api/graph/all')
def graph_all(limit: int = 200):
    """전체 정치인 관계 그래프 조회"""
    members = graph_storage.find_nodes("Member")
    
    # 제한된 수의 노드만 반환
    limited_members = members[:min(limit, len(members))]
    
    nodes = []
    relationships = []
    node_ids = set()
    
    for member in limited_members:
        # 이미지 URL 추가
        name = member["properties"].get("name")
        if name:
            member["properties"]["image_url"] = f"/api/images/{name}.jpg"
            member["properties"]["thumbnail_url"] = f"/api/images/{name}.jpg?thumbnail=true"
        
        nodes.append(member)
        node_ids.add(member["id"])
        
        # 각 의원의 관계 추가
        rels = graph_storage.get_relationships(member["id"], direction="out")
        for rel in rels[:10]:  # 각 의원당 최대 10개 관계
            relationships.append(rel["edge"])
            if rel["node"] and rel["node"]["id"] not in node_ids:
                # 연결된 노드에도 이미지 URL 추가
                if rel["node"].get("labels") and "Member" in rel["node"]["labels"]:
                    rel_name = rel["node"]["properties"].get("name")
                    if rel_name:
                        rel["node"]["properties"]["image_url"] = f"/api/images/{rel_name}.jpg"
                        rel["node"]["properties"]["thumbnail_url"] = f"/api/images/{rel_name}.jpg?thumbnail=true"
                nodes.append(rel["node"])
                node_ids.add(rel["node"]["id"])
    
    return JSONResponse(content={
        "nodes": nodes,
        "relationships": relationships
    })

@app.get('/api/graph/{member_name}')
def graph(member_name: str, depth: int = Query(2, ge=1, le=5)):
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
    
    # 이미지 URL 추가
    for node in data["nodes"]:
        if node.get("labels") and "Member" in node["labels"]:
            name = node["properties"].get("name")
            if name:
                node["properties"]["image_url"] = f"/api/images/{name}.jpg"
                node["properties"]["thumbnail_url"] = f"/api/images/{name}.jpg?thumbnail=true"
    
    return JSONResponse(content=data)

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
def add_edge(req: EdgeRequest):
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

    edge = graph_storage.add_edge(src_id, tgt_id, req.type, req.properties)
    
    # Log Activity
    log_activity("New Relation", f"{req.source} -> {req.target} ({req.type})")
    
    return JSONResponse(content={"message": "Edge added", "edge": edge})

@app.get('/api/stats')
def stats():
    """통계 정보"""
    stats = graph_storage.get_statistics()
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
def get_activity_logs(limit: int = 50, history: bool = False, search: str = None):
    """활동 로그 조회 (기본값: 최근 50개)"""
    if history:
        # DB에서 히스토리 조회
        logs = graph_storage.get_logs(limit=limit if limit <= 200 else 200, search=search)
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
def get_intelligence():
    """상업용 인사이트 조회를 위한 지능형 분석 데이터 제공"""
    data = graph_storage.get_intelligence()
    return JSONResponse(content=data)

@app.get('/health')
def health():
    """헬스체크"""
    return JSONResponse(content={"status": "healthy"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "turingdb_server:app",
        host="0.0.0.0",
        port=5000,
        reload=True
    )
