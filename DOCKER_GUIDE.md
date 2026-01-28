# Docker 실행 가이드

## 사전 요구사항

- Docker Desktop 설치 (Windows/Mac)
- Docker Compose 설치 (Linux)

## 빠른 시작

### Windows

```cmd
docker-start.bat
```

### Linux/Mac

```bash
chmod +x docker-start.sh
./docker-start.sh
```

### 수동 실행

```bash
# 모든 서비스 시작
docker-compose up -d

# 로그 확인
docker-compose logs -f

# 특정 서비스 로그만 확인
docker-compose logs -f backend
docker-compose logs -f turingdb
```

## 서비스 구성

### 1. TuringDB (포트 6666)
- 고성능 그래프 데이터베이스
- REST API: http://localhost:6666

### 2. Backend API (포트 5000)
- FastAPI 서버
- API 문서: http://localhost:5000/docs
- 엔드포인트:
  - GET /api/search/{member_name}
  - GET /api/graph/{member_name}?depth=2
  - GET /api/graph/all?limit=200
  - GET /api/stats

## 데이터 임포트

### 방법 1: 컨테이너 내부에서 실행

```bash
# 전체 데이터 임포트
docker-compose exec backend python turingdb_importer.py --import-all --json assembly_members_complete.json

# 의원 노드만 임포트
docker-compose exec backend python turingdb_importer.py --import-members --json assembly_members_complete.json
```

### 방법 2: 로컬에서 실행 (TuringDB가 Docker에서 실행 중일 때)

```bash
cd backend
pip install -r requirements.txt
python turingdb_importer.py --import-all --json ../assembly_members_complete.json
```

## Docker 명령어

### 서비스 관리

```bash
# 서비스 시작
docker-compose up -d

# 서비스 중지
docker-compose down

# 서비스 재시작
docker-compose restart

# 특정 서비스만 재시작
docker-compose restart backend

# 서비스 상태 확인
docker-compose ps

# 로그 확인
docker-compose logs -f backend
```

### 컨테이너 접속

```bash
# Backend 컨테이너 접속
docker-compose exec backend bash

# TuringDB 컨테이너 접속 (있는 경우)
docker-compose exec turingdb sh
```

### 데이터 볼륨 관리

```bash
# 볼륨 목록 확인
docker volume ls

# 볼륨 삭제 (주의: 데이터가 삭제됩니다!)
docker-compose down -v

# 특정 볼륨만 삭제
docker volume rm koreapolitician_turingdb_data
```

### 이미지 재빌드

```bash
# Backend 이미지 재빌드
docker-compose build backend

# 캐시 없이 재빌드
docker-compose build --no-cache backend

# 재빌드 후 시작
docker-compose up -d --build
```

## 개발 모드

개발 중에는 코드 변경 시 자동으로 재시작됩니다:

```bash
# --reload 옵션으로 실행 (docker-compose.yml에 이미 설정됨)
docker-compose up -d backend
```

백엔드 코드를 수정하면 자동으로 서버가 재시작됩니다.

## 환경 변수

`backend/.env` 파일에서 설정:

```env
TURINGDB_HOST=http://turingdb:6666
TURINGDB_GRAPH=korea_politician
```

Docker Compose에서는 `docker-compose.yml`의 environment 섹션에서 오버라이드됩니다.

## API 테스트

### curl 사용

```bash
# 의원 검색
curl http://localhost:5000/api/search/이재명

# 의원 관계 그래프
curl http://localhost:5000/api/graph/이재명?depth=2

# 전체 그래프
curl http://localhost:5000/api/graph/all?limit=100

# 통계
curl http://localhost:5000/api/stats
```

### 브라우저에서

- API 문서: http://localhost:5000/docs
- ReDoc: http://localhost:5000/redoc

## 문제 해결

### 포트 충돌

포트가 이미 사용 중인 경우 `docker-compose.yml`에서 포트 변경:

```yaml
services:
  backend:
    ports:
      - "5001:5000"  # 5001로 변경
  
  turingdb:
    ports:
      - "6667:6666"  # 6667로 변경
```

### 컨테이너가 시작되지 않음

```bash
# 로그 확인
docker-compose logs backend

# 컨테이너 상태 확인
docker-compose ps

# 컨테이너 재시작
docker-compose restart backend
```

### TuringDB 연결 실패

```bash
# TuringDB 상태 확인
docker-compose logs turingdb

# TuringDB 헬스체크
curl http://localhost:6666/health

# 네트워크 확인
docker network ls
docker network inspect koreapolitician_default
```

### 데이터가 사라짐

볼륨을 삭제하지 않도록 주의:

```bash
# 서비스만 중지 (볼륨 유지)
docker-compose down

# 볼륨까지 삭제 (주의!)
docker-compose down -v
```

### 이미지 빌드 실패

```bash
# 캐시 없이 재빌드
docker-compose build --no-cache backend

# Docker 빌드 로그 확인
docker-compose build backend --progress=plain
```

## 프로덕션 배포

프로덕션 환경에서는:

1. `docker-compose.yml`에서 `--reload` 옵션 제거
2. 환경 변수를 `.env` 파일로 분리
3. 볼륨 백업 설정
4. 리버스 프록시 (Nginx) 추가
5. HTTPS 설정

```yaml
# docker-compose.prod.yml
services:
  backend:
    command: uvicorn turingdb_server:app --host 0.0.0.0 --port 5000 --workers 4
    restart: always
```

## 모니터링

```bash
# 리소스 사용량 확인
docker stats

# 특정 컨테이너만 확인
docker stats korea-politician-backend korea-politician-turingdb
```

## 백업 및 복원

### 데이터 백업

```bash
# TuringDB 데이터 백업
docker run --rm -v koreapolitician_turingdb_data:/data -v $(pwd):/backup alpine tar czf /backup/turingdb-backup.tar.gz -C /data .
```

### 데이터 복원

```bash
# TuringDB 데이터 복원
docker run --rm -v koreapolitician_turingdb_data:/data -v $(pwd):/backup alpine tar xzf /backup/turingdb-backup.tar.gz -C /data
```

## 추가 리소스

- [Docker 공식 문서](https://docs.docker.com/)
- [Docker Compose 문서](https://docs.docker.com/compose/)
- [TuringDB 문서](https://docs.turingdb.ai/)
