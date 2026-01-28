# Frontend 로컬 실행 설정

## 변경 사항

Frontend를 Docker 컨테이너에서 로컬 개발 서버로 변경했습니다.

### 이전 구성
```
┌─────────────────────────────────────┐
│  Docker Compose                     │
│  ├─ TuringDB (Port 6666)           │
│  ├─ Backend (Port 5000)            │
│  └─ Frontend (Port 3100) ← Docker  │
└─────────────────────────────────────┘
```

### 현재 구성
```
┌─────────────────────────────────────┐
│  Docker Compose                     │
│  ├─ TuringDB (Port 6666)           │
│  └─ Backend (Port 5000)            │
└─────────────────────────────────────┘

┌─────────────────────────────────────┐
│  Local Development                  │
│  └─ Frontend (Port 3100) ← Vite    │
└─────────────────────────────────────┘
```

## 장점

### 1. 빠른 개발 속도
- **HMR (Hot Module Replacement)**: 코드 변경 시 즉시 반영
- **빠른 빌드**: Docker 이미지 빌드 불필요
- **즉각적인 피드백**: 저장 즉시 브라우저 업데이트

### 2. 편리한 디버깅
- **Chrome DevTools**: 직접 디버깅 가능
- **Source Maps**: 원본 코드 확인 가능
- **React DevTools**: 컴포넌트 트리 검사

### 3. 유연한 개발 환경
- **포트 변경 용이**: vite.config.ts에서 간단히 변경
- **환경 변수 관리**: .env 파일로 쉽게 관리
- **의존성 업데이트**: npm install로 즉시 적용

## 실행 방법

### 자동 실행 (권장)

#### Windows
```bash
start-dev.bat
```

#### Linux/Mac
```bash
chmod +x start-dev.sh
./start-dev.sh
```

### 수동 실행

#### 1. Backend + TuringDB 시작
```bash
docker-compose up -d
```

#### 2. Frontend 시작
```bash
cd frontend
npm install  # 최초 1회만
npm run dev
```

## 서비스 접속

| 서비스 | URL | 설명 |
|--------|-----|------|
| Frontend | http://localhost:3100 | React 개발 서버 (Vite) |
| Backend | http://localhost:5000 | FastAPI 서버 |
| API Docs | http://localhost:5000/docs | Swagger UI |
| TuringDB | http://localhost:6666 | TuringDB REST API |

## 개발 워크플로우

### 1. 코드 수정
```bash
# Frontend 코드 수정
frontend/src/components/GraphVisualization.tsx
```

### 2. 자동 반영
- 파일 저장 시 Vite가 자동으로 변경사항 감지
- 브라우저가 자동으로 새로고침 (HMR)
- 콘솔에서 실시간 로그 확인

### 3. 빌드 테스트
```bash
cd frontend
npm run build
```

### 4. 타입 체크
```bash
cd frontend
npm run type-check
```

## 환경 설정

### vite.config.ts
```typescript
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3100,  // Frontend 포트
    proxy: {
      '/api': {
        target: 'http://localhost:5000',  // Backend URL
        changeOrigin: true,
      },
    },
  },
})
```

### .env (Frontend)
```env
VITE_API_URL=http://localhost:5000
```

## 종료 방법

### Frontend 종료
- 터미널에서 `Ctrl + C`

### Backend + TuringDB 종료
```bash
# Windows
stop-dev.bat

# Linux/Mac
docker-compose down
```

## 문제 해결

### 포트 3100이 이미 사용 중
```bash
# 포트 사용 프로세스 확인 (Windows)
netstat -ano | findstr :3100

# 포트 변경
# vite.config.ts에서 port: 3100을 다른 포트로 변경
```

### npm 의존성 오류
```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
```

### API 연결 실패
```bash
# Backend 상태 확인
docker-compose ps

# Backend 로그 확인
docker-compose logs backend

# Backend 재시작
docker-compose restart backend
```

### HMR이 작동하지 않음
```bash
# Vite 서버 재시작
# 터미널에서 Ctrl + C 후
npm run dev
```

## 성능 비교

| 항목 | Docker | Local Dev |
|------|--------|-----------|
| 초기 시작 | ~30초 | ~3초 |
| 코드 변경 반영 | ~10초 | <1초 |
| 빌드 시간 | ~60초 | ~20초 |
| 메모리 사용 | ~500MB | ~200MB |

## 배포 시

Production 환경에서는 여전히 Docker를 사용할 수 있습니다:

```bash
# Frontend를 Docker로 빌드 (선택사항)
docker build -t korea-politician-frontend ./frontend

# 또는 정적 파일로 빌드
cd frontend
npm run build
# dist/ 폴더를 웹 서버에 배포
```

## 추가 정보

- **개발 환경 가이드**: [DEV_SETUP.md](./DEV_SETUP.md)
- **줌 컨트롤 가이드**: [ZOOM_CONTROL_GUIDE.md](./ZOOM_CONTROL_GUIDE.md)
- **그래프 구조 가이드**: [GRAPH_STRUCTURE.md](./GRAPH_STRUCTURE.md)
- **기능 가이드**: [FEATURES_GUIDE.md](./FEATURES_GUIDE.md)
