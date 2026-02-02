# KoreaPolitician with TuringDB

한국 정치인 관계 분석 프로젝트 - TuringDB 버전

## TuringDB란?

TuringDB는 고성능 인메모리 컬럼 기반 그래프 데이터베이스로, 분석 및 읽기 집약적 워크로드에 최적화되어 있습니다.

### 주요 장점
- **초고속 성능**: Neo4j 대비 200배 빠른 멀티홉 쿼리
- **버전 관리**: Git과 유사한 그래프 버전 관리 시스템
- **제로 락킹**: 동시성 제어를 위한 제로 락킹 아키텍처
- **스냅샷 격리**: 일관된 읽기 보장

## 빠른 시작

### 1. TuringDB 설치 및 실행

```bash
# pip로 설치
pip install turingdb

# TuringDB 실행 (인터랙티브 모드)
turingdb

# 또는 백그라운드 데몬으로 실행
turingdb --daemon
```

또는 Docker 사용:

```bash
docker-compose up -d turingdb
```

### 2. 의존성 설치

```bash
cd backend
pip install -r requirements.txt
```

### 3. 데이터 임포트

```bash
cd backend

# 전체 데이터 임포트 (노드 + 관계)
python turingdb_importer.py --import-all --json ../assembly_members_complete.json

# 통계 확인
python -c "from turingdb_importer import TuringDBImporter; i = TuringDBImporter(); i.get_statistics()"
```

### 4. API 서버 실행

```bash
cd backend
python turingdb_server.py
```

서버가 http://localhost:5000 에서 실행됩니다.

## API 사용 예제

### 의원 검색
```bash
curl http://localhost:5000/api/search/이재명
```

### 의원 관계 그래프 조회
```bash
curl http://localhost:5000/api/graph/이재명?depth=2
```

### 전체 정치인 그래프
```bash
curl http://localhost:5000/api/graph/all?limit=100
```

## TuringDB 쿼리 예제

### Python SDK 사용

```python
from turingdb import TuringDB

# 클라이언트 생성
client = TuringDB(host="http://localhost:6666")

# 그래프 설정
client.set_graph("korea_politician")

# 의원 검색
result = client.query("""
    MATCH (m:Member {name: '이재명'})
    RETURN m.name, m.party, m.region
""")
print(result)

# 같은 정당 의원 찾기
result = client.query("""
    MATCH (m:Member {name: '이재명'})-[:BELONGS_TO]->(p:Party)<-[:BELONGS_TO]-(other:Member)
    RETURN other.name, other.region
    LIMIT 10
""")
print(result)

# 동문 관계 찾기
result = client.query("""
    MATCH (m:Member {name: '이재명'})-[:GRADUATED_FROM]->(s:School)<-[:GRADUATED_FROM]-(other:Member)
    RETURN other.name, s.name as school
""")
print(result)
```

### 복잡한 관계 분석

```python
# 2단계 관계 분석 (친구의 친구)
result = client.query("""
    MATCH path = (m:Member {name: '이재명'})-[*1..2]-(connected:Member)
    RETURN DISTINCT connected.name, connected.party
    LIMIT 20
""")

# 정당별 의원 수
result = client.query("""
    MATCH (m:Member)-[:BELONGS_TO]->(p:Party)
    RETURN p.name, count(m) as member_count
    ORDER BY member_count DESC
""")

# 지역별 의원 수
result = client.query("""
    MATCH (m:Member)-[:REPRESENTS]->(r:Region)
    RETURN r.name, count(m) as member_count
    ORDER BY member_count DESC
""")
```

## 성능 비교

### Neo4j vs TuringDB

| 쿼리 유형 | Neo4j | TuringDB | 속도 향상 |
|----------|-------|----------|----------|
| 1-hop 쿼리 | 1390ms | 12ms | 115배 |
| 2-hop 쿼리 | 1420ms | 11ms | 129배 |
| 4-hop 쿼리 | 1568ms | 14ms | 112배 |
| 7-hop 쿼리 | 51,264ms | 172ms | 298배 |
| 8-hop 쿼리 | 98,183ms | 476ms | 206배 |

## 프로젝트 구조

```
KoreaPolitician/
├── backend/
│   ├── turingdb_importer.py    # TuringDB 데이터 임포터
│   ├── turingdb_server.py      # FastAPI 서버 (TuringDB)
│   ├── neo4j_importer.py       # Neo4j 임포터 (레거시)
│   ├── fastapi_server.py       # FastAPI 서버 (Neo4j, 레거시)
│   ├── requirements.txt        # Python 패키지
│   └── .env                    # 환경 변수
├── frontend/                   # 프론트엔드 (추후 개발)
├── docker-compose.yml          # Docker 설정
├── assembly_members_complete.json  # 의원 데이터
├── MIGRATION_GUIDE.md          # 마이그레이션 가이드
└── README_TURINGDB.md          # 이 파일
```

## 데이터 모델

### 노드 타입
- **Member**: 국회의원
  - 속성: id, name, party, region, sido, election_count, terms, phone, email, etc.
- **Party**: 정당
  - 속성: name
- **Region**: 지역 (시도, 구군)
  - 속성: name, type, sido
- **School**: 학교
  - 속성: name

### 관계 타입
- **BELONGS_TO**: 의원 → 정당
- **REPRESENTS**: 의원 → 지역
- **SAME_PARTY**: 의원 ↔ 의원 (같은 정당)
- **SAME_REGION**: 의원 ↔ 의원 (같은 지역)
- **SAME_TERM**: 의원 ↔ 의원 (같은 대수)
- **GRADUATED_FROM**: 의원 → 학교
- **SAME_SCHOOL**: 의원 ↔ 의원 (동문)
- **CONTAINS**: 시도 → 구군

## 문제 해결

### TuringDB가 시작되지 않음
```bash
# 포트 확인
netstat -ano | findstr :6666

# TuringDB 재시작
turingdb --daemon
```

### 데이터 임포트 오류
```bash
# 그래프 삭제 후 재생성
python -c "from turingdb import TuringDB; c = TuringDB(); c.query('DROP GRAPH \"korea_politician\"')"

# 다시 임포트
python turingdb_importer.py --import-all --json ../assembly_members_complete.json
```

### API 서버 오류
```bash
# 로그 확인
python turingdb_server.py

# 환경 변수 확인
echo %TURINGDB_HOST%
echo %TURINGDB_GRAPH%
```

## 추가 리소스

- [TuringDB 공식 문서](https://docs.turingdb.ai/)
- [TuringDB GitHub](https://github.com/turing-db/turingdb)
- [TuringDB Python SDK 레퍼런스](https://turingdb.mintlify.app/pythonsdk/reference)
- [TuringDB 예제 노트북](https://github.com/turing-db/turingdb-examples)

## 라이선스

TuringDB Community Edition은 BSL 라이선스를 따릅니다.

## 기여

문제가 발생하거나 개선 사항이 있으면 이슈를 등록해주세요.
