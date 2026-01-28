from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from graph_storage import graph_storage
from simple_importer import SimpleImporter
from image_manager import image_manager
import logging

logging.basicConfig(level=logging.INFO)

app = FastAPI()

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
    json_file = "assembly_members_complete.json"
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

@app.get('/api/stats')
def stats():
    """통계 정보"""
    stats = graph_storage.get_statistics()
    return JSONResponse(content=stats)

@app.get('/api/images/{filename}')
def serve_image(filename: str, thumbnail: bool = False):
    """이미지 서빙"""
    return image_manager.serve_image(filename, thumbnail=thumbnail)

@app.get('/api/images')
def list_images():
    """이미지 목록"""
    images = image_manager.get_all_images()
    return JSONResponse(content={"images": images})

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
