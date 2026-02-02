# 개발 환경 설정 가이드

## 개요

KoreaPolitician 프로젝트는 다음과 같이 구성됩니다:
- **Backend + TuringDB**: Docker 컨테이너로 실행
- **Frontend**: 로컬 개발 서버(Vite)로 실행

이 구성은 Frontend 개발 시 빠른 HMR(Hot Module Replacement)과 디버깅을 가능하게 합니다.

## 시스템 요구사항

### 필수 소프트웨어
- **Docker Desktop**: 최신 버전
- **Node.js**: v18 이상
- **npm**: v9 이상
- **Git**: 최신 버전

### 권장 사양
- RAM: 8GB 이상
- 디스크 공간: 10GB 이상
- OS: Windows 10/11, macOS, Linux

## 설치 및 실행

### 1. 저장소 클론

```bash
git clone <repository-url>
cd KoreaPolitician
```

### 2. Frontend 의존성 설치

```bash
cd frontend
npm install
cd ..
```

### 3. 개발 환경 시작

#### Windows
```bash
start-dev.bat
```

#### Linux/Mac
```bash
chmod +x start-dev.sh
./start-dev.sh
```

### 4. 서비스 접속

- **Frontend**: http://localhost:3100
- **Backend API**: http://localhost:5000
- **API 문서**: http://localhost:5000/docs
- **TuringDB**: http://localhost:6666

## 개발 워크플로우

### Frontend 개발

1. **코드 수정**
   - `frontend/src/` 디렉토리에서 코드 수정
   - Vite가 자동으로 변경사항 감지 및 HMR 적용

2. **빌드 테스트**
   ```bash
   cd frontend
   npm run build
   ```

3. **타입 체크**
   ```bash
   cd frontend
   npm run type-check
   ```

### Backend 개발

1. **코드 수정**
   - `backend/` 디렉토리에서 코드 수정
   - Docker 볼륨 마운트로 자동 반영 (uvicorn --reload)

2. **컨테이너 재시작**
   ```bash
   docker-compose restart backend
   ```

3. **로그 확인**
   ```bash
   docker-compose logs -f backend
   ```

### TuringDB 관리

1. **데이터 재로드**
   ```bash
   docker-compose exec backend python simple_importer.py --json assembly_members_complete.json
   ```

2. **데이터베이스 초기화**
   ```bash
   docker-compose down -v
   docker-compose up -d
   ```

## 포트 구성

| 서비스 | 포트 | 설명 |
|--------|------|------|
| Frontend | 3100 | Vite 개발 서버 |
| Backend | 5000 | FastAPI 서버 |
| TuringDB | 6666 | TuringDB REST API |

## 환경 변수

### Frontend (.env)
```env
VITE_API_URL=http://localhost:5000
```

### Backend (.env)
```env
TURINGDB_HOST=http://turingdb:6666
TURINGDB_GRAPH=korea_politician
PYTHONUNBUFFERED=1
```

## 문제 해결

### Frontend가 시작되지 않음

**증상**: `npm run dev` 실행 시 오류

**해결**:
```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
npm run dev
```

### Backend API 연결 실패

**증상**: Frontend에서 API 호출 실패

**해결**:
1. Backend 컨테이너 상태 확인
   ```bash
   docker-compose ps
   ```

2. Backend 로그 확인
   ```bash
   docker-compose logs backend
   ```

3. Backend 재시작
   ```bash
   docker-compose restart backend
   ```

### 포트 충돌

**증상**: "Port already in use" 오류

**해결**:
1. 사용 중인 프로세스 확인 (Windows)
   ```bash
   netstat -ano | findstr :3100
   netstat -ano | findstr :5000
   ```

2. 프로세스 종료 또는 포트 변경
   - Frontend: `frontend/vite.config.ts`에서 포트 변경
   - Backend: `docker-compose.yml`에서 포트 매핑 변경

### Docker 컨테이너 오류

**증상**: 컨테이너가 시작되지 않음

**해결**:
1. 모든 컨테이너 중지 및 제거
   ```bash
   docker-compose down -v
   ```

2. 이미지 재빌드
   ```bash
   docker-compose build --no-cache
   docker-compose up -d
   ```

## 개발 도구

### 추천 VS Code 확장

- **ESLint**: JavaScript/TypeScript 린팅
- **Prettier**: 코드 포맷팅
- **Volar**: Vue/React 지원
- **Docker**: Docker 관리
- **Thunder Client**: API 테스트

### 디버깅

#### Frontend 디버깅
1. Chrome DevTools 사용
2. React Developer Tools 설치
3. VS Code에서 디버깅:
   ```json
   {
     "type": "chrome",
     "request": "launch",
     "name": "Launch Chrome",
     "url": "http://localhost:3100",
     "webRoot": "${workspaceFolder}/frontend/src"
   }
   ```

#### Backend 디버깅
1. FastAPI 자동 문서: http://localhost:5000/docs
2. Docker 로그:
   ```bash
   docker-compose logs -f backend
   ```

## 성능 최적화

### Frontend
- **코드 분할**: React.lazy() 사용
- **이미지 최적화**: WebP 포맷 사용
- **번들 크기 분석**:
  ```bash
  npm run build
  npm run analyze
  ```

### Backend
- **캐싱**: Redis 추가 고려
- **데이터베이스 인덱싱**: TuringDB 인덱스 최적화
- **비동기 처리**: FastAPI async/await 활용

## 배포

### Production 빌드

1. Frontend 빌드
   ```bash
   cd frontend
   npm run build
   ```

2. Docker 이미지 빌드
   ```bash
   docker-compose -f docker-compose.prod.yml build
   ```

3. 배포
   ```bash
   docker-compose -f docker-compose.prod.yml up -d
   ```

## 추가 리소스

- [Vite 문서](https://vitejs.dev/)
- [React 문서](https://react.dev/)
- [FastAPI 문서](https://fastapi.tiangolo.com/)
- [Docker 문서](https://docs.docker.com/)
- [TuringDB 문서](./README_TURINGDB.md)

## 기여 가이드

1. Feature 브랜치 생성
2. 코드 수정 및 테스트
3. Commit 메시지 규칙 준수
4. Pull Request 생성

## 라이선스

이 프로젝트는 MIT 라이선스를 따릅니다.
