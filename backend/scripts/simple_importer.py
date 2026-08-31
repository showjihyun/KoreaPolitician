"""
간단한 그래프 데이터 임포터
인메모리 그래프 저장소 사용
"""

import json
import os
import re
from core.graph_storage import graph_storage


# 노드에 함께 담을 프로필 필드. 화면의 프로필 팝업이 이 값들을 쓴다.
PROFILE_FIELDS = (
    "hjNm", "engNm", "bthDate", "telNo", "eMail",
    "homepage", "linkUrl", "staff", "secretary", "secretary2",
)


def profile_fields(member: dict) -> dict:
    """의원 원본 레코드에서 프로필 필드만 뽑는다. 없는 값은 빈 문자열."""
    out = {key: (member.get(key) or "") for key in PROFILE_FIELDS}
    careers = member.get("careers") or []
    if isinstance(careers, str):
        careers = [careers]
    # 경력은 최근 8개만. 노드 properties 가 지나치게 커지면 그래프 응답이 무거워진다.
    out["careers"] = [str(c) for c in careers][:8]
    return out


async def sync_member_profiles(json_file: str) -> int:
    """이미 적재된 의원 노드에 프로필 필드를 채워 넣는다.

    프로필 필드는 원본 JSON 에 계속 있었지만 노드에 담기지 않았다. 최초
    임포트는 노드가 하나도 없을 때만 도므로, 이미 데이터가 있는 DB 는
    재임포트 없이 이 경로로 보강한다. 값이 이미 같으면 아무 것도 하지 않는다.
    """
    if not os.path.exists(json_file):
        return 0

    with open(json_file, "r", encoding="utf-8") as f:
        records = json.load(f)
    by_name = {m.get("name"): m for m in records if m.get("name")}

    pending = []
    for node in graph_storage.find_nodes("Member"):
        source = by_name.get(node["properties"].get("name"))
        if not source:
            continue
        fields = profile_fields(source)
        if all(node["properties"].get(k) == v for k, v in fields.items()):
            continue
        merged = {**node["properties"], **fields}
        pending.append((node["id"], node["labels"], merged))

    if pending:
        await graph_storage.add_nodes_bulk(pending)
    return len(pending)


class SimpleImporter:
    def __init__(self):
        self.storage = graph_storage
        
    def extract_member_id(self, member_data):
        """의원 ID 추출"""
        # monaCd 사용
        return member_data.get("monaCd") or member_data.get("name", "unknown")
    
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
    
    async def import_data(self, json_file_path):
        """JSON 파일에서 데이터를 읽어와 그래프에 저장"""
        print("=== 데이터 임포트 시작 ===")
        
        # JSON 파일 읽기
        with open(json_file_path, 'r', encoding='utf-8') as f:
            members_data = json.load(f)
        
        print(f"총 {len(members_data)}명의 의원 데이터 로드")
        
        # 데이터베이스 초기화
        self.storage.clear()
        
        # 1단계: 정당 노드 생성
        print("\n1단계: 정당 노드 생성")
        parties = set()
        for member in members_data:
            if member.get("party"):
                parties.add(member.get("party"))
        
        for party in parties:
            await self.storage.add_node(
                f"party_{party}",
                ["Party"],
                {"name": party}
            )
            print(f"정당 노드 생성: {party}")
        
        # 2단계: 지역 노드 생성
        print("\n2단계: 지역 노드 생성")
        regions = set()
        for member in members_data:
            sido, region = self.parse_region(member.get("선거구"))
            if region:
                regions.add((sido, region))
        
        for sido, region in regions:
            if sido:
                await self.storage.add_node(
                    f"sido_{sido}",
                    ["Region", "Sido"],
                    {"name": sido, "type": "sido"}
                )
            
            await self.storage.add_node(
                f"region_{region}",
                ["Region"],
                {"name": region, "type": "region", "sido": sido or ""}
            )
            
            if sido:
                await self.storage.add_edge(
                    f"sido_{sido}",
                    f"region_{region}",
                    "CONTAINS"
                )
            
            print(f"지역 노드 생성: {sido} {region}")
        
        # 3단계: 의원 노드 생성
        print("\n3단계: 의원 노드 생성")
        member_ids = []
        for member in members_data:
            member_id = self.extract_member_id(member)
            if not member_id or not member.get("name"):
                continue
            
            sido, region = self.parse_region(member.get("region"))
            election_count = member.get("election_count", "")
            
            await self.storage.add_node(
                f"member_{member_id}",
                ["Member"],
                {
                    "id": member_id,
                    "name": member.get("name", ""),
                    "party": member.get("party", ""),
                    "region": region or member.get("region", ""),
                    "sido": sido or "",
                    "region_detail": member.get("region", ""),
                    "committee": member.get("committees", ""),
                    "election_count": election_count,
                    "unit": member.get("unit", ""),
                    "gender": member.get("gender", ""),
                    "election_method": member.get("election_method", ""),
                    "photo_url": member.get("photo_url", ""),
                    "photo_filename": member.get("photo_filename", ""),
                    "monaCd": member.get("monaCd", ""),
                    # 프로필 상세. 원본 JSON 에는 있는데 그동안 노드에 담기지
                    # 않아 화면에서 쓸 수 없었다.
                    **profile_fields(member),
                }
            )
            
            member_ids.append(member_id)
            print(f"의원 노드 생성: {member.get('name')} ({member_id})")
        
        # 4단계: 기본 관계 생성
        print("\n4단계: 기본 관계 생성")
        for member in members_data:
            member_id = self.extract_member_id(member)
            if not member_id:
                continue
            
            # 의원-정당 관계
            if member.get("party"):
                await self.storage.add_edge(
                    f"member_{member_id}",
                    f"party_{member.get('party')}",
                    "BELONGS_TO"
                )
            
            # 의원-지역 관계
            sido, region = self.parse_region(member.get("region"))
            if region:
                await self.storage.add_edge(
                    f"member_{member_id}",
                    f"region_{region}",
                    "REPRESENTS"
                )
        
        # 5단계: 의원 간 관계 생성
        print("\n5단계: 의원 간 관계 생성")
        await self.create_member_relationships(members_data)
        
        # 6단계: 약력 기반 관계 분석
        print("\n6단계: 약력 기반 관계 분석")
        self.analyze_career_relationships(members_data)
        
        print(f"\n=== 데이터 임포트 완료 ===")
        print(f"총 {len(member_ids)}명의 의원 데이터 저장")
        
        # 통계 출력
        await self.get_statistics()
    
    async def create_member_relationships(self, members_data):
        """의원 간 관계 생성 (불필요한 대규모 엣지 생성 억제)"""
        # 기존의 모든 조합 SAME_PARTY/SAME_REGION 생성은 엣지 폭증의 원인이므로 주석 처리
        # 대신 국회의원 노드와 정당 노드 간의 BELONGS_TO 관계로 연결성을 유지함
        print("SAME_PARTY 및 SAME_REGION 엣지 폭증 방지를 위해 개별 생성 스킵")
        
        # 샘플 감정 관계 생성 (향후 실제 데이터 연동 가능)
        # 특정 의원들 간의 대표적인 관계 예시
        sentiment_samples = [
            ("이재명", "나경원", "NEGATIVE_SENTIMENT", 85, "여야 대치 주역"),
            ("박지원", "안철수", "NEGATIVE_SENTIMENT", 70, "정치적 입장 차이"),
            ("이재명", "정청래", "POSITIVE_SENTIMENT", 90, "당내 긴밀한 관계"),
            ("나경원", "안철수", "POSITIVE_SENTIMENT", 60, "여권 내 중진 협력"),
            ("권성동", "이재명", "NEGATIVE_SENTIMENT", 95, "강력한 정치적 라이벌"),
        ]
        
        for p1_name, p2_name, rel_type, score, desc in sentiment_samples:
            # 이름으로 노드 찾기
            p1_nodes = self.storage.find_nodes("Member", {"name": f"CONTAINS:{p1_name}"})
            p2_nodes = self.storage.find_nodes("Member", {"name": f"CONTAINS:{p2_name}"})
            
            if p1_nodes and p2_nodes:
                await self.storage.add_edge(
                    p1_nodes[0]["id"], 
                    p2_nodes[0]["id"], 
                    rel_type, 
                    {"score": score, "count": 1, "description": desc}
                )
                print(f"샘플 감정 관계 생성: {p1_name} --[{rel_type}]--> {p2_name}")
    
    def analyze_career_relationships(self, members_data):
        """약력 기반 관계 분석"""
        # 현재 JSON에는 약력 정보가 없으므로 스킵
        print("약력 정보가 없어 학력 관계 생성 스킵")
    
    async def get_statistics(self):
        """통계 정보 출력"""
        stats = await self.storage.get_statistics()
        
        print("\n=== 데이터베이스 통계 ===")
        print(f"총 노드 수: {stats['total_nodes']}")
        print(f"총 엣지 수: {stats['total_edges']}")
        
        print("\n노드 개수:")
        for label, count in stats['nodes_by_label'].items():
            print(f"  {label}: {count}개")
        
        print("\n관계 개수:")
        for rel_type, count in stats['edges_by_type'].items():
            print(f"  {rel_type}: {count}개")


if __name__ == "__main__":
    import argparse
    import asyncio
    import os
    from dotenv import load_dotenv
    
    # .env 파일 로드
    load_dotenv()
    
    parser = argparse.ArgumentParser(description="Simple Graph Importer")
    parser.add_argument('--json', type=str, default="data/assembly_members_complete.json", help='JSON 파일 경로')
    args = parser.parse_args()
    
    # DB 초기화
    db_config = {
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': int(os.getenv('POSTGRES_PORT', 5432)),
        'user': os.getenv('POSTGRES_USER', 'postgres'),
        'password': os.getenv('POSTGRES_PASSWORD', '1234'),
        'dbname': os.getenv('POSTGRES_DB', 'postgres'),
    }
    
    print(f"Connecting to DB at {db_config['host']}:{db_config['port']}...")

    async def _main():
        await graph_storage.init_db(db_config)
        try:
            importer = SimpleImporter()
            await importer.import_data(args.json)
        finally:
            await graph_storage.close()

    asyncio.run(_main())
