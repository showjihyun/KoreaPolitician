from py2neo import Graph, Node, Relationship
import pandas as pd

# Neo4j 접속 정보
NEO4J_URL = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "patrol-alpine-thomas-nepal-deposit-3273"  # Docker 실행 시 NEO4J_AUTH=neo4j/test 기준

# CSV 파일 읽기
df = pd.read_csv("politicians.csv", encoding="utf-8")

# Neo4j 연결
graph = Graph(NEO4J_URL, auth=(NEO4J_USER, NEO4J_PASSWORD))

# 인물 노드 생성
for _, row in df.iterrows():
    person = Node(
        "Person",
        name=row["name"],
        wiki_url=row["wiki_url"],
        birth_place=row.get("출생지", ""),
        party=row.get("소속", "")
    )
    graph.merge(person, "Person", "name")  # name 기준 중복 방지

    # 배우자 관계
    spouse = row.get("배우자", "")
    if spouse:
        spouse_node = Node("Person", name=spouse)
        graph.merge(spouse_node, "Person", "name")
        graph.merge(Relationship(person, "SPOUSE", spouse_node))

    # 가족 관계
    family = row.get("가족", "")
    if family:
        for fam in family.split(","):
            fam = fam.strip()
            if fam:
                fam_node = Node("Person", name=fam)
                graph.merge(fam_node, "Person", "name")
                graph.merge(Relationship(person, "FAMILY", fam_node))

print("Neo4j 데이터 INSERT 완료!") 