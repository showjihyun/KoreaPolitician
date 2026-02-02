# Neo4j에서 TuringDB로 마이그레이션 가이드

## 개요
이 프로젝트는 Neo4j에서 TuringDB로 마이그레이션되었습니다. TuringDB는 Neo4j보다 200배 빠른 고성능 컬럼 기반 그래프 데이터베이스입니다.

## 주요 변경사항

### 1. 데이터베이스 변경
- **이전**: Neo4j (bolt://localhost:7687)
- **현재**: TuringDB (http://localhost:6666)

### 2. 새로운 파일
- `backend/turingdb_importer.py` - TuringDB 데이터 임포터
- `backend/turingdb_server.py` - TuringDB용 FastAPI 서버

### 3. 설정 파일 업데이트
- `backend/.env` - TuringDB 설정 추가
- `backend/requirements.txt` - turingdb 패키지 추가
- `docker-compose.yml` - TuringDB 컨테이너 추가

## 설치 및 실행

### 1. TuringDB 설치

#### 방법 1: pip 설치 (권장)
```bash
pip install turingdb
```

#### 방법 2: Docker 사용
```bash
cd KoreaPolitician
docker-compose up -d turingdb
```

### 2. Python 패키지 설치
```bash
cd backend
pip install -r requirements.txt
```

### 3. 데이터 임포트

#### 전체 데이터 임포트 (노드 + 관계)
```bash
cd backend
python turingdb_importer.py --import-all --json ../assembly_members_complete.json
```

#### 의원 노드만 임포트
```bash
cd backend
python turingdb_importer.py --import-members --json ../assembly_members_complete.json
```

### 4. FastAPI 서버 실행
```bash
cd backend
python turingdb_server.py
```

또는

```bash
cd backend
uvicorn turingdb_server:app --reload --host 0.0.0.0 --port 5000
```

## API 엔드포인트

### 1. 의원 검색
```
GET /api/search/{member_name}
```

### 2. 의원 관계 그래프
```
GET /api/graph/{member_name}?depth=2
```

### 3. 전체 정치인 그래프
```
GET /api/graph/all?limit=200
```

### 4. 통계 정보
```
GET /api/stats
```

## TuringDB 주요 특징

### 1. 성능
- Neo4j 대비 200배 빠른 멀티홉 쿼리
- 컬럼 기반 아키텍처로 분석 워크로드 최적화
- 제로 락킹 동시성 제어

### 2. 버전 관리
- Git과 유사한 버전 관리 시스템
- Change 기반 작업 (branch와 유사)
- Commit 및 Submit으로 변경사항 저장

### 3. 쿼리 언어
- OpenCypher 기반 (Neo4j와 유사)
- 대부분의 Cypher 쿼리 호환

## 마이그레이션 체크리스트

- [x] TuringDB 임포터 작성
- [x] FastAPI 서버 TuringDB 연동
- [x] Docker Compose 설정 업데이트
- [x] 환경 변수 설정 업데이트
- [x] requirements.txt 업데이트
- [ ] 프론트엔드 API 엔드포인트 확인
- [ ] 데이터 임포트 테스트
- [ ] 성능 벤치마크

## 기존 Neo4j 사용 (선택사항)

기존 Neo4j를 계속 사용하려면:

```bash
docker-compose --profile legacy up -d neo4j
```

그리고 기존 `fastapi_server.py` 또는 `neo4j_importer.py`를 사용하세요.

## 문제 해결

### TuringDB 연결 실패
1. TuringDB가 실행 중인지 확인: `docker ps` 또는 `turingdb` 프로세스 확인
2. 포트 6666이 사용 가능한지 확인
3. 환경 변수 `TURINGDB_HOST` 확인

### 데이터 임포트 실패
1. JSON 파일 경로 확인
2. TuringDB 그래프가 생성되었는지 확인
3. 로그 메시지 확인

## 참고 자료

- [TuringDB 공식 문서](https://docs.turingdb.ai/)
- [TuringDB GitHub](https://github.com/turing-db/turingdb)
- [TuringDB Python SDK](https://turingdb.mintlify.app/pythonsdk/reference)
- [TuringDB 예제](https://github.com/turing-db/turingdb-examples)
