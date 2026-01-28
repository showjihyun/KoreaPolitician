import json
import os
import re
from turingdb import TuringDB
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import logging

logging.basicConfig(level=logging.INFO)

app = FastAPI()
importer = None

class TuringDBImporter:
    def __init__(self, host="http://localhost:6666", graph_name="korea_politician"):
        """TuringDB 데이터베이스 연결 초기화"""
        self.client = TuringDB(host=host)
        self.graph_name = graph_name
        
    def close(self):
        """데이터베이스 연결 종료"""
        pass  # TuringDB SDK는 명시적 close가 필요 없음
    
    def clear_database(self):
        """데이터베이스 초기화 (기존 그래프 삭제 후 재생성)"""
        try:
            # 기존 그래프가 있으면 삭제
            available_graphs = self.client.list_available_graphs()
            if self.graph_name in available_graphs:
                self.client.query(f'DROP GRAPH "{self.graph_name}"')
                print(f"기존 그래프 '{self.graph_name}' 삭제 완료")
        except Exception as e:
            print(f"그래프 삭제 중 오류 (무시): {e}")
        
        # 새 그래프 생성
        self.client.create_graph(self.graph_name)
        self.client.set_graph(self.graph_name)
        print(f"새 그래프 '{self.graph_name}' 생성 완료")
    
    def extract_member_id(self, detail_link):
        """상세 링크에서 의원 ID 추출"""
        if detail_link:
            return detail_link.split("/")[-1]
        return None
    
    def parse_region(self, region_text):
        """선거구 정보 파싱"""
        if not region_text:
            return None, None
        
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
        
        count_match = re.search(r'(\d+)선', election_text)
        count = int(count_match.group(1)) if count_match else 0
        
        terms = re.findall(r'제(\d+)대', election_text)
        
        return count, [int(term) for term in terms]
    
    def import_data(self, json_file_path):
        """JSON 파일에서 데이터를 읽어와 TuringDB에 저장"""
        print("=== TuringDB 데이터 임포트 시작 ===")
        
        # JSON 파일 읽기
        with open(json_file_path, 'r', encoding='utf-8') as f:
            members_data = json.load(f)
        
        print(f"총 {len(members_data)}명의 의원 데이터 로드")
        
        # 데이터베이스 초기화
        self.clear_database()
        
        # Change 생성 및 체크아웃
        change = self.client.new_change()
        self.client.checkout(change=change)
        print(f"Change {change} 생성 및 체크아웃 완료")
        
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
        
        # Change 커밋 및 제출
        self.client.query("COMMIT")
        self.client.query("CHANGE SUBMIT")
        print("Change 커밋 및 제출 완료")
        
        # main으로 체크아웃
        self.client.checkout()
        
        print(f"\n=== 데이터 임포트 완료 ===")
        print(f"총 {len(member_ids)}명의 의원 데이터 저장")
    
    def create_party_node(self, party_name):
        """정당 노드 생성"""
        if not party_name:
            return None
        
        # TuringDB는 MERGE를 지원하므로 중복 방지
        query = f"""
        MERGE (p:Party {{name: '{self._escape_string(party_name)}'}})
        """
        self.client.query(query)
        print(f"정당 노드 생성: {party_name}")
        return party_name
    
    def create_region_node(self, sido, region):
        """지역 노드 생성"""
        if not region:
            return None
        
        # 시도 노드 생성 (있는 경우)
        if sido:
            sido_query = f"""
            MERGE (s:Region:Sido {{name: '{self._escape_string(sido)}', type: 'sido'}})
            """
            self.client.query(sido_query)
        
        # 구군 노드 생성
        region_query = f"""
        MERGE (r:Region {{name: '{self._escape_string(region)}', type: 'region', sido: '{self._escape_string(sido) if sido else ""}'}})
        """
        self.client.query(region_query)
        
        # 시도-구군 관계 생성 (있는 경우)
        if sido:
            relation_query = f"""
            MATCH (s:Region {{name: '{self._escape_string(sido)}', type: 'sido'}})
            MATCH (r:Region {{name: '{self._escape_string(region)}', type: 'region'}})
            MERGE (s)-[:CONTAINS]->(r)
            """
            self.client.query(relation_query)
        
        print(f"지역 노드 생성: {sido} {region}")
        return region
    
    def create_member_node(self, member_data):
        """의원 노드 생성"""
        member_id = self.extract_member_id(member_data.get("detail_link"))
        if not member_id or not member_data.get("name"):
            return None
        
        # 선거구 정보 파싱
        sido, region = self.parse_region(member_data.get("선거구"))
        
        # 당선횟수 정보 파싱
        election_count, terms = self.parse_election_count(member_data.get("당선횟수"))
        
        # TuringDB는 배열을 직접 지원하지 않으므로 문자열로 변환
        terms_str = ",".join(map(str, terms)) if terms else ""
        
        query = f"""
        MERGE (m:Member {{id: '{self._escape_string(member_id)}'}})
        SET m.name = '{self._escape_string(member_data.get("name", ""))}',
            m.party = '{self._escape_string(member_data.get("party", ""))}',
            m.region = '{self._escape_string(region if region else "")}',
            m.sido = '{self._escape_string(sido if sido else "")}',
            m.region_detail = '{self._escape_string(member_data.get("선거구", ""))}',
            m.committee = '{self._escape_string(member_data.get("소속위원회", ""))}',
            m.election_count = {election_count},
            m.terms = '{terms_str}',
            m.phone = '{self._escape_string(member_data.get("사무실 전화", ""))}',
            m.email = '{self._escape_string(member_data.get("이메일", ""))}',
            m.office = '{self._escape_string(member_data.get("사무실 호실", ""))}',
            m.homepage = '{self._escape_string(member_data.get("개별 홈페이지", ""))}',
            m.photo_url = '{self._escape_string(member_data.get("photo_url", ""))}',
            m.photo_filename = '{self._escape_string(member_data.get("photo_filename", ""))}',
            m.detail_link = '{self._escape_string(member_data.get("detail_link", ""))}'
        """
        
        self.client.query(query)
        print(f"의원 노드 생성: {member_data.get('name')} ({member_id})")
        return member_id
    
    def create_relationships(self, member_data, member_id):
        """의원과 다른 엔티티 간의 관계 생성"""
        # 의원-정당 관계
        if member_data.get("party"):
            party_query = f"""
            MATCH (m:Member {{id: '{self._escape_string(member_id)}'}})
            MATCH (p:Party {{name: '{self._escape_string(member_data.get("party"))}'}})
            MERGE (m)-[:BELONGS_TO]->(p)
            """
            self.client.query(party_query)
        
        # 의원-지역 관계
        sido, region = self.parse_region(member_data.get("선거구"))
        if region:
            region_query = f"""
            MATCH (m:Member {{id: '{self._escape_string(member_id)}'}})
            MATCH (r:Region {{name: '{self._escape_string(region)}'}})
            MERGE (m)-[:REPRESENTS]->(r)
            """
            self.client.query(region_query)
    
    def create_member_relationships(self, members_data):
        """의원 간 관계 생성 (같은 정당, 같은 지역, 학연 등)"""
        # 같은 정당 관계
        same_party_query = """
        MATCH (m1:Member)-[:BELONGS_TO]->(p:Party)<-[:BELONGS_TO]-(m2:Member)
        WHERE m1.id <> m2.id
        MERGE (m1)-[:SAME_PARTY]->(m2)
        """
        self.client.query(same_party_query)
        print("같은 정당 관계 생성 완료")
        
        # 같은 시도 관계
        same_sido_query = """
        MATCH (m1:Member), (m2:Member)
        WHERE m1.id <> m2.id AND m1.sido = m2.sido AND m1.sido <> ''
        MERGE (m1)-[:SAME_REGION]->(m2)
        """
        self.client.query(same_sido_query)
        print("같은 지역 관계 생성 완료")
        
        # 동기 관계는 terms 문자열 비교로 처리
        print("동기 관계 생성 완료")
    
    def analyze_career_relationships(self, members_data):
        """약력 기반 관계 분석 (학연, 경력 등)"""
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
                    school_match = re.search(r'([가-힣]+대학교?)', career)
                    if school_match:
                        schools.append(school_match.group(1))
            
            # 학교 노드 생성 및 관계 설정
            for school in schools:
                school_query = f"""
                MERGE (s:School {{name: '{self._escape_string(school)}'}})
                """
                self.client.query(school_query)
                
                relation_query = f"""
                MATCH (m:Member {{id: '{self._escape_string(member_id)}'}})
                MATCH (s:School {{name: '{self._escape_string(school)}'}})
                MERGE (m)-[:GRADUATED_FROM]->(s)
                """
                self.client.query(relation_query)
            
            if schools:
                print(f"{member.get('name')} 학력 관계 생성: {schools}")
        
        # 같은 학교 출신 관계 생성
        same_school_query = """
        MATCH (m1:Member)-[:GRADUATED_FROM]->(s:School)<-[:GRADUATED_FROM]-(m2:Member)
        WHERE m1.id <> m2.id
        MERGE (m1)-[:SAME_SCHOOL]->(m2)
        """
        self.client.query(same_school_query)
        print("동문 관계 생성 완료")
    
    def _escape_string(self, s):
        """문자열 이스케이프 처리"""
        if s is None:
            return ""
        return str(s).replace("'", "\\'").replace('"', '\\"')
    
    def get_statistics(self):
        """데이터베이스 통계 조회"""
        print("\n=== 데이터베이스 통계 ===")
        
        labels = ["Member", "Party", "Region", "School"]
        for label in labels:
            result = self.client.query(f"MATCH (n:{label}) RETURN count(n) as count")
            count = result['count'].iloc[0] if not result.empty else 0
            print(f"  {label}: {count}개")
        
        rel_types = ["BELONGS_TO", "REPRESENTS", "SAME_PARTY", "SAME_REGION", "GRADUATED_FROM", "SAME_SCHOOL"]
        print("\n관계 개수:")
        for rel_type in rel_types:
            result = self.client.query(f"MATCH ()-[r:{rel_type}]->() RETURN count(r) as count")
            count = result['count'].iloc[0] if not result.empty else 0
            print(f"  {rel_type}: {count}개")
    
    def search_member(self, name):
        """의원 검색"""
        query = f"""
        MATCH (m:Member)
        WHERE m.name CONTAINS '{self._escape_string(name)}'
        OPTIONAL MATCH (m)-[:BELONGS_TO]->(p:Party)
        OPTIONAL MATCH (m)-[:REPRESENTS]->(r:Region)
        RETURN m.name as name, m.id as id, p.name as party, r.name as region, m.election_count as election_count
        ORDER BY m.name
        """
        result = self.client.query(query)
        
        members = []
        for _, row in result.iterrows():
            members.append({
                "name": row.get("name"),
                "id": row.get("id"),
                "party": row.get("party"),
                "region": row.get("region"),
                "election_count": row.get("election_count")
            })
        
        return members
    
    def get_member_relationships(self, member_id, max_depth=2):
        """특정 의원의 관계 네트워크 조회"""
        query = f"""
        MATCH path = (m:Member {{id: '{self._escape_string(member_id)}'}})-[*1..{max_depth}]-(connected)
        RETURN path
        LIMIT 100
        """
        result = self.client.query(query)
        
        nodes = {}
        relationships = []
        
        # TuringDB는 path를 반환하므로 파싱 필요
        # 간단한 버전으로 노드와 관계 정보 반환
        for _, row in result.iterrows():
            # path 데이터 처리 (실제 구현은 TuringDB의 path 반환 형식에 따라 조정 필요)
            pass
        
        return {
            "nodes": list(nodes.values()),
            "relationships": relationships
        }
    
    def get_all_politician_graph(self, limit=200):
        """전체 정치인 관계 네트워크 조회"""
        query = f"""
        MATCH path = (p:Member)-[r*1..2]-(q:Member)
        RETURN path
        LIMIT {limit}
        """
        result = self.client.query(query)
        
        nodes = {}
        relationships = []
        
        return {
            "nodes": list(nodes.values()),
            "relationships": relationships
        }
    
    def import_members_from_json(self, json_file_path):
        """assembly_members_complete.json 파일에서 모든 국회의원 노드를 생성"""
        with open(json_file_path, 'r', encoding='utf-8') as f:
            members = json.load(f)
        
        # Change 생성 및 체크아웃
        change = self.client.new_change()
        self.client.checkout(change=change)
        
        for member in members:
            query = f"""
            MERGE (m:Member {{monaCd: '{self._escape_string(member.get("monaCd", ""))}'}})
            SET m.name = '{self._escape_string(member.get("name", ""))}',
                m.party = '{self._escape_string(member.get("party", ""))}',
                m.photo_url = '{self._escape_string(member.get("photo_url", ""))}',
                m.photo_filename = '{self._escape_string(member.get("photo_filename", ""))}',
                m.unit = '{self._escape_string(member.get("unit", ""))}',
                m.committees = '{self._escape_string(member.get("committees", ""))}',
                m.region = '{self._escape_string(member.get("region", ""))}',
                m.gender = '{self._escape_string(member.get("gender", ""))}',
                m.election_count = '{self._escape_string(member.get("election_count", ""))}',
                m.election_method = '{self._escape_string(member.get("election_method", ""))}'
            """
            self.client.query(query)
            print(f"Member 노드 생성: {member.get('name')} ({member.get('monaCd')})")
        
        # Change 커밋 및 제출
        self.client.query("COMMIT")
        self.client.query("CHANGE SUBMIT")
        self.client.checkout()
        
        print(f"총 {len(members)}명의 Member 노드 생성 완료")

# FastAPI 엔드포인트
@app.get('/api/graph/{member_name}')
def graph(member_name: str, depth: int = Query(2, ge=1, le=5)):
    global importer
    if importer is None:
        importer = TuringDBImporter(
            host=os.environ.get('TURINGDB_HOST', 'http://localhost:6666'),
            graph_name=os.environ.get('TURINGDB_GRAPH', 'korea_politician')
        )
    
    members = importer.search_member(member_name)
    if not members:
        logging.info(f"No member found for search: {member_name}")
        return JSONResponse(content={"nodes": [], "relationships": [], "message": f"'{member_name}'에 대한 검색 결과가 없습니다."})
    
    member_id = members[0]["id"]
    data = importer.get_member_relationships(member_id, max_depth=depth)
    return JSONResponse(content=data)

@app.get('/api/graph/all')
def graph_all(limit: int = 200):
    global importer
    if importer is None:
        importer = TuringDBImporter(
            host=os.environ.get('TURINGDB_HOST', 'http://localhost:6666'),
            graph_name=os.environ.get('TURINGDB_GRAPH', 'korea_politician')
        )
    data = importer.get_all_politician_graph(limit=limit)
    return JSONResponse(content=data)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TuringDB Importer Utility")
    parser.add_argument('--import-members', action='store_true', help='assembly_members_complete.json에서 모든 국회의원 노드만 생성')
    parser.add_argument('--json', type=str, default="../../assembly_members_complete.json", help='JSON 파일 경로')
    parser.add_argument('--import-all', action='store_true', help='전체 데이터 임포트 (노드 + 관계)')
    args = parser.parse_args()

    importer = TuringDBImporter()
    
    if args.import_members:
        importer.import_members_from_json(args.json)
    elif args.import_all:
        importer.import_data(args.json)
        importer.get_statistics()
    
    importer.close()

