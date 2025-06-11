from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import os
from neo4j_importer import Neo4jImporter
import logging

logging.basicConfig(level=logging.INFO)

app = FastAPI()
importer = None

@app.get('/api/graph/{member_name}')
def graph(member_name: str, depth: int = Query(2, ge=1, le=5)):
    global importer
    if importer is None:
        importer = Neo4jImporter(
            uri=os.environ.get('NEO4J_URI', 'bolt://localhost:7687'),
            user=os.environ.get('NEO4J_USER', 'neo4j'),
            password=os.environ.get('NEO4J_PASSWORD', 'patrol-alpine-thomas-nepal-deposit-3273')
        )
    # 부분 일치 검색 지원
    with importer.driver.session() as session:
        result = session.run(
            "MATCH (m:Member) WHERE m.name CONTAINS $name RETURN m.id as id LIMIT 1",
            name=member_name
        )
        record = result.single()
        if not record or not record["id"]:
            logging.info(f"No member found for search: {member_name}")
            return JSONResponse(content={"nodes": [], "relationships": [], "message": f"'{member_name}'에 대한 검색 결과가 없습니다."})
        member_id = record["id"]
    data = importer.get_member_relationships(member_id, max_depth=depth)
    return JSONResponse(content=data)

@app.get('/api/graph/all')
def graph_all(limit: int = 200):
    global importer
    if importer is None:
        importer = Neo4jImporter(
            uri=os.environ.get('NEO4J_URI', 'bolt://localhost:7687'),
            user=os.environ.get('NEO4J_USER', 'neo4j'),
            password=os.environ.get('NEO4J_PASSWORD', 'patrol-alpine-thomas-nepal-deposit-3273')
        )
    data = importer.get_all_politician_graph(limit=limit)
    return JSONResponse(content=data)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "fastapi_server:app",
        host="0.0.0.0",
        port=5000,
        reload=True
    )

# FastAPI 실행은 아래 명령어로 실행하세요:
# uvicorn backend.fastapi_server:app --reload --host 0.0.0.0 --port 5000 