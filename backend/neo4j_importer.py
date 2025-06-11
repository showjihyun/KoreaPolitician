import json
import os
from neo4j import GraphDatabase
import re
from urllib.parse import urlparse

# === FastAPI API 추가 ===
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
importer = None
app = FastAPI()

class Neo4jImporter:
    def __init__(self, uri="bolt://localhost:7687", user="neo4j", password="patrol-alpine-thomas-nepal-deposit-3273"):
        """Neo4j 데이터베이스 연결 초기화"""
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        
    def close(self):
        """데이터베이스 연결 종료"""
        self.driver.close()
    
    def clear_database(self):
        """데이터베이스 초기화 (기존 데이터 삭제)"""
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
            print("데이터베이스 초기화 완료")
    
    def create_constraints(self):
        """인덱스 및 제약조건 생성"""
        with self.driver.session() as session:
            # 의원 ID 유니크 제약조건
            try:
                session.run("CREATE CONSTRAINT member_id_unique IF NOT EXISTS FOR (m:Member) REQUIRE m.id IS UNIQUE")
                print("Member ID 유니크 제약조건 생성")
            except:
                print("Member ID 제약조건 이미 존재")
            
            # 정당 이름 유니크 제약조건
            try:
                session.run("CREATE CONSTRAINT party_name_unique IF NOT EXISTS FOR (p:Party) REQUIRE p.name IS UNIQUE")
                print("Party name 유니크 제약조건 생성")
            except:
                print("Party name 제약조건 이미 존재")
            
            # 지역 이름 유니크 제약조건
            try:
                session.run("CREATE CONSTRAINT region_name_unique IF NOT EXISTS FOR (r:Region) REQUIRE r.name IS UNIQUE")
                print("Region name 유니크 제약조건 생성")
            except:
                print("Region name 제약조건 이미 존재")
    
    def extract_member_id(self, detail_link):
        """상세 링크에서 의원 ID 추출"""
        if detail_link:
            return detail_link.split("/")[-1]
        return None
    
    def parse_region(self, region_text):
        """선거구 정보 파싱"""
        if not region_text:
            return None, None
        
        # "서울 영등포구을" -> 시도: "서울", 구군: "영등포구을"
        # "경기 화성시을" -> 시도: "경기", 구군: "화성시을"
        # "비례대표" -> 시도: None, 구군: "비례대표"
        
        if "비례대표" in region_text:
            return None, "비례대표"
        
        parts = region_text.split(" ", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        else:
            return None, region_text
    
    def parse_election_count(self, election_text):
        """당선횟수 정보 파싱"""
        if not election_text:
            return 0, []
        
        # "5선(제17대, 제18대, 제19대, 제21대, 제22대)" 형태에서 숫자와 대수 추출
        count_match = re.search(r'(\d+)선', election_text)
        count = int(count_match.group(1)) if count_match else 0
        
        # 대수 정보 추출
        terms = re.findall(r'제(\d+)대', election_text)
        
        return count, [int(term) for term in terms]
    
    def create_member_node(self, member_data):
        """의원 노드 생성"""
        member_id = self.extract_member_id(member_data.get("detail_link"))
        if not member_id or not member_data.get("name"):
            return None
        
        # 선거구 정보 파싱
        sido, region = self.parse_region(member_data.get("선거구"))
        
        # 당선횟수 정보 파싱
        election_count, terms = self.parse_election_count(member_data.get("당선횟수"))
        
        with self.driver.session() as session:
            query = """
            MERGE (m:Member {id: $member_id})
            SET m.name = $name,
                m.party = $party,
                m.region = $region,
                m.sido = $sido,
                m.region_detail = $region_detail,
                m.committee = $committee,
                m.election_count = $election_count,
                m.terms = $terms,
                m.phone = $phone,
                m.email = $email,
                m.office = $office,
                m.homepage = $homepage,
                m.photo_url = $photo_url,
                m.photo_filename = $photo_filename,
                m.detail_link = $detail_link
            RETURN m
            """
            
            result = session.run(query, 
                member_id=member_id,
                name=member_data.get("name", ""),
                party=member_data.get("party", ""),
                region=region,
                sido=sido,
                region_detail=member_data.get("선거구", ""),
                committee=member_data.get("소속위원회", ""),
                election_count=election_count,
                terms=terms,
                phone=member_data.get("사무실 전화", ""),
                email=member_data.get("이메일", ""),
                office=member_data.get("사무실 호실", ""),
                homepage=member_data.get("개별 홈페이지", ""),
                photo_url=member_data.get("photo_url", ""),
                photo_filename=member_data.get("photo_filename", ""),
                detail_link=member_data.get("detail_link", "")
            )
            
            print(f"의원 노드 생성: {member_data.get('name')} ({member_id})")
            return member_id
    
    def create_party_node(self, party_name):
        """정당 노드 생성"""
        if not party_name:
            return None
        
        with self.driver.session() as session:
            query = """
            MERGE (p:Party {name: $party_name})
            RETURN p
            """
            session.run(query, party_name=party_name)
            print(f"정당 노드 생성: {party_name}")
            return party_name
    
    def create_region_node(self, sido, region):
        """지역 노드 생성"""
        if not region:
            return None
        
        with self.driver.session() as session:
            # 시도 노드 생성 (있는 경우)
            if sido:
                sido_query = """
                MERGE (s:Region:Sido {name: $sido, type: 'sido'})
                RETURN s
                """
                session.run(sido_query, sido=sido)
            
            # 구군 노드 생성
            region_query = """
            MERGE (r:Region {name: $region, type: 'region'})
            SET r.sido = $sido
            RETURN r
            """
            session.run(region_query, region=region, sido=sido)
            
            # 시도-구군 관계 생성 (있는 경우)
            if sido:
                relation_query = """
                MATCH (s:Region {name: $sido, type: 'sido'})
                MATCH (r:Region {name: $region, type: 'region'})
                MERGE (s)-[:CONTAINS]->(r)
                """
                session.run(relation_query, sido=sido, region=region)
            
            print(f"지역 노드 생성: {sido} {region}")
            return region
    
    def create_relationships(self, member_data, member_id):
        """의원과 다른 엔티티 간의 관계 생성"""
        with self.driver.session() as session:
            # 의원-정당 관계
            if member_data.get("party"):
                party_query = """
                MATCH (m:Member {id: $member_id})
                MATCH (p:Party {name: $party_name})
                MERGE (m)-[:BELONGS_TO]->(p)
                """
                session.run(party_query, member_id=member_id, party_name=member_data.get("party"))
            
            # 의원-지역 관계
            sido, region = self.parse_region(member_data.get("선거구"))
            if region:
                region_query = """
                MATCH (m:Member {id: $member_id})
                MATCH (r:Region {name: $region})
                MERGE (m)-[:REPRESENTS]->(r)
                """
                session.run(region_query, member_id=member_id, region=region)
    
    def create_member_relationships(self, members_data):
        """의원 간 관계 생성 (같은 정당, 같은 지역, 학연 등)"""
        with self.driver.session() as session:
            # 같은 정당 관계
            same_party_query = """
            MATCH (m1:Member)-[:BELONGS_TO]->(p:Party)<-[:BELONGS_TO]-(m2:Member)
            WHERE m1.id <> m2.id
            MERGE (m1)-[:SAME_PARTY]->(m2)
            """
            session.run(same_party_query)
            print("같은 정당 관계 생성 완료")
            
            # 같은 시도 관계
            same_sido_query = """
            MATCH (m1:Member)-[:REPRESENTS]->(r1:Region)-[:CONTAINS*0..1]-(r2:Region)<-[:REPRESENTS]-(m2:Member)
            WHERE m1.id <> m2.id AND m1.sido = m2.sido AND m1.sido IS NOT NULL
            MERGE (m1)-[:SAME_REGION]->(m2)
            """
            session.run(same_sido_query)
            print("같은 지역 관계 생성 완료")
            
            # 동기 관계 (같은 대수에 당선)
            same_term_query = """
            MATCH (m1:Member), (m2:Member)
            WHERE m1.id <> m2.id 
            AND any(term IN m1.terms WHERE term IN m2.terms)
            MERGE (m1)-[:SAME_TERM]->(m2)
            """
            session.run(same_term_query)
            print("동기 관계 생성 완료")
    
    def analyze_career_relationships(self, members_data):
        """약력 기반 관계 분석 (학연, 경력 등)"""
        with self.driver.session() as session:
            for member in members_data:
                if not member.get("name") or not member.get("약력"):
                    continue
                
                member_id = self.extract_member_id(member.get("detail_link"))
                if not member_id:
                    continue
                
                careers = member.get("약력", [])
                
                # 학교 정보 추출
                schools = []
                for career in careers:
                    if "대학교" in career or "대학" in career:
                        # "서울대학교 법학과 졸업" -> "서울대학교"
                        school_match = re.search(r'([가-힣]+대학교?)', career)
                        if school_match:
                            schools.append(school_match.group(1))
                
                # 학교 노드 생성 및 관계 설정
                for school in schools:
                    school_query = """
                    MERGE (s:School {name: $school_name})
                    """
                    session.run(school_query, school_name=school)
                    
                    relation_query = """
                    MATCH (m:Member {id: $member_id})
                    MATCH (s:School {name: $school_name})
                    MERGE (m)-[:GRADUATED_FROM]->(s)
                    """
                    session.run(relation_query, member_id=member_id, school_name=school)
                
                print(f"{member.get('name')} 학력 관계 생성: {schools}")
            
            # 같은 학교 출신 관계 생성
            same_school_query = """
            MATCH (m1:Member)-[:GRADUATED_FROM]->(s:School)<-[:GRADUATED_FROM]-(m2:Member)
            WHERE m1.id <> m2.id
            MERGE (m1)-[:SAME_SCHOOL]->(m2)
            """
            session.run(same_school_query)
            print("동문 관계 생성 완료")
    
    def import_data(self, json_file_path):
        """JSON 파일에서 데이터를 읽어와 Neo4j에 저장"""
        print("=== Neo4j 데이터 임포트 시작 ===")
        
        # JSON 파일 읽기
        with open(json_file_path, 'r', encoding='utf-8') as f:
            members_data = json.load(f)
        
        print(f"총 {len(members_data)}명의 의원 데이터 로드")
        
        # 데이터베이스 초기화 및 제약조건 생성
        self.clear_database()
        self.create_constraints()
        
        # 1단계: 정당 노드 생성
        print("\n1단계: 정당 노드 생성")
        parties = set()
        for member in members_data:
            if member.get("party"):
                parties.add(member.get("party"))
        
        for party in parties:
            self.create_party_node(party)
        
        # 2단계: 지역 노드 생성
        print("\n2단계: 지역 노드 생성")
        regions = set()
        for member in members_data:
            sido, region = self.parse_region(member.get("선거구"))
            if region:
                regions.add((sido, region))
        
        for sido, region in regions:
            self.create_region_node(sido, region)
        
        # 3단계: 의원 노드 생성
        print("\n3단계: 의원 노드 생성")
        member_ids = []
        for member in members_data:
            member_id = self.create_member_node(member)
            if member_id:
                member_ids.append(member_id)
        
        # 4단계: 기본 관계 생성
        print("\n4단계: 기본 관계 생성")
        for member in members_data:
            member_id = self.extract_member_id(member.get("detail_link"))
            if member_id:
                self.create_relationships(member, member_id)
        
        # 5단계: 의원 간 관계 생성
        print("\n5단계: 의원 간 관계 생성")
        self.create_member_relationships(members_data)
        
        # 6단계: 약력 기반 관계 분석
        print("\n6단계: 약력 기반 관계 분석")
        self.analyze_career_relationships(members_data)
        
        print(f"\n=== 데이터 임포트 완료 ===")
        print(f"총 {len(member_ids)}명의 의원 데이터 저장")
    
    def get_statistics(self):
        """데이터베이스 통계 조회"""
        with self.driver.session() as session:
            # 노드 개수
            node_counts = {}
            labels = ["Member", "Party", "Region", "School"]
            
            for label in labels:
                result = session.run(f"MATCH (n:{label}) RETURN count(n) as count")
                node_counts[label] = result.single()["count"]
            
            # 관계 개수
            relationship_counts = {}
            rel_types = ["BELONGS_TO", "REPRESENTS", "SAME_PARTY", "SAME_REGION", "SAME_TERM", "GRADUATED_FROM", "SAME_SCHOOL"]
            
            for rel_type in rel_types:
                result = session.run(f"MATCH ()-[r:{rel_type}]->() RETURN count(r) as count")
                relationship_counts[rel_type] = result.single()["count"]
            
            print("\n=== 데이터베이스 통계 ===")
            print("노드 개수:")
            for label, count in node_counts.items():
                print(f"  {label}: {count}개")
            
            print("\n관계 개수:")
            for rel_type, count in relationship_counts.items():
                print(f"  {rel_type}: {count}개")
    
    def search_member(self, name):
        """의원 검색"""
        with self.driver.session() as session:
            query = """
            MATCH (m:Member)
            WHERE m.name CONTAINS $name
            OPTIONAL MATCH (m)-[:BELONGS_TO]->(p:Party)
            OPTIONAL MATCH (m)-[:REPRESENTS]->(r:Region)
            RETURN m.name as name, m.id as id, p.name as party, r.name as region, m.election_count as election_count
            ORDER BY m.name
            """
            result = session.run(query, name=name)
            
            members = []
            for record in result:
                members.append({
                    "name": record["name"],
                    "id": record["id"],
                    "party": record["party"],
                    "region": record["region"],
                    "election_count": record["election_count"]
                })
            
            return members
    
    def get_member_relationships(self, member_id, max_depth=2):
        """특정 의원의 관계 네트워크 조회"""
        with self.driver.session() as session:
            query = f"""
            MATCH path = (m:Member {{id: $member_id}})-[*1..{max_depth}]-(connected)
            WHERE connected:Member OR connected:Party OR connected:Region OR connected:School
            RETURN path
            LIMIT 100
            """
            result = session.run(query, member_id=member_id)
            nodes = {}
            relationships = []
            for record in result:
                path = record["path"]
                for node in path.nodes:
                    node_id = node.element_id
                    if node_id not in nodes:
                        labels = list(node.labels)
                        properties = dict(node)
                        nodes[node_id] = {
                            "id": node_id,
                            "labels": labels,
                            "properties": properties
                        }
                for rel in path.relationships:
                    relationships.append({
                        "start": rel.start_node.element_id,
                        "end": rel.end_node.element_id,
                        "type": rel.type,
                        "properties": dict(rel)
                    })
            return {
                "nodes": list(nodes.values()),
                "relationships": relationships
            }

    def get_all_politician_graph(self, limit=200):
        """전체 정치인 관계 네트워크 조회 (긍정/부정 등 모든 관계 포함)"""
        with self.driver.session() as session:
            query = f"""
            MATCH path = (p:Member)-[r*1..2]-(q:Member)
            RETURN path
            LIMIT {limit}
            """
            result = session.run(query)
            nodes = {}
            relationships = []
            for record in result:
                path = record["path"]
                for node in path.nodes:
                    node_id = node.element_id
                    if node_id not in nodes:
                        labels = list(node.labels)
                        properties = dict(node)
                        nodes[node_id] = {
                            "id": node_id,
                            "labels": labels,
                            "properties": properties
                        }
                for rel in path.relationships:
                    relationships.append({
                        "start": rel.start_node.element_id,
                        "end": rel.end_node.element_id,
                        "type": rel.type,
                        "properties": dict(rel)
                    })
            return {
                "nodes": list(nodes.values()),
                "relationships": relationships
            }

    def import_members_from_json(self, json_file_path):
        """assembly_members_complete.json 파일에서 모든 국회의원 노드를 생성 (관계 없이 노드와 속성만)"""
        with open(json_file_path, 'r', encoding='utf-8') as f:
            members = json.load(f)
        with self.driver.session() as session:
            for member in members:
                # Neo4j Member 노드 생성 (monaCd 또는 name+party 조합으로 유니크)
                query = """
                MERGE (m:Member {monaCd: $monaCd})
                SET m.name = $name,
                    m.party = $party,
                    m.photo_url = $photo_url,
                    m.photo_filename = $photo_filename,
                    m.unit = $unit,
                    m.committees = $committees,
                    m.region = $region,
                    m.gender = $gender,
                    m.election_count = $election_count,
                    m.election_method = $election_method
                """
                session.run(query,
                    monaCd=member.get("monaCd", ""),
                    name=member.get("name", ""),
                    party=member.get("party", ""),
                    photo_url=member.get("photo_url", ""),
                    photo_filename=member.get("photo_filename", ""),
                    unit=member.get("unit", ""),
                    committees=member.get("committees", ""),
                    region=member.get("region", ""),
                    gender=member.get("gender", ""),
                    election_count=member.get("election_count", ""),
                    election_method=member.get("election_method", "")
                )
                print(f"Member 노드 생성: {member.get('name')} ({member.get('monaCd')})")
        print(f"총 {len(members)}명의 Member 노드 생성 완료")

@app.get('/api/graph/{member_name}')
def graph(member_name: str, depth: int = Query(2, ge=1, le=5)):
    global importer
    if importer is None:
        importer = Neo4jImporter(
            uri=os.environ.get('NEO4J_URI', 'bolt://localhost:7687'),
            user=os.environ.get('NEO4J_USER', 'neo4j'),
            password=os.environ.get('NEO4J_PASSWORD', 'patrol-alpine-thomas-nepal-deposit-3273')
        )
    # 이름으로 id 찾기
    with importer.driver.session() as session:
        result = session.run(
            "MATCH (m:Member) WHERE m.name CONTAINS $name RETURN m.id as id, m.name as name LIMIT 1",
            name=member_name
        )
        record = result.single()
        if not record or not record["id"]:
            return JSONResponse(content={"nodes": [], "relationships": []})
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

# FastAPI 실행은 아래 명령어로 실행하세요:
# uvicorn backend.neo4j_importer:app --reload --host 0.0.0.0 --port 5000 

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Neo4j Importer Utility")
    parser.add_argument('--import-members', action='store_true', help='assembly_members_complete.json에서 모든 국회의원 노드만 생성')
    parser.add_argument('--json', type=str, default="../../assembly_members_complete.json", help='JSON 파일 경로')
    args = parser.parse_args()

    if args.import_members:
        importer = Neo4jImporter()
        importer.import_members_from_json(args.json)
        importer.close() 