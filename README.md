# KoreaPolitician - 한국 정치인 관계 분석 프로젝트

React + TypeScript + WebGL 기반 고성능 그래프 시각화 시스템

## 🚀 빠른 시작 (개발 환경)

### 1. 개발 환경 실행

```bash
# Windows
start-dev.bat

# Linux/Mac
chmod +x start-dev.sh
./start-dev.sh
```

이 스크립트는 자동으로:
1. Docker 컨테이너 시작 (Backend + TuringDB)
2. Frontend 개발 서버 시작 (Vite)

### 2. 서비스 확인

- **Frontend**: http://localhost:3100 (Vite 개발 서버)
- **Backend API**: http://localhost:5000
- **API 문서**: http://localhost:5000/docs
- **TuringDB**: http://localhost:6666

### 3. 개발 환경 종료

```bash
# Windows
stop-dev.bat

# Linux/Mac
docker-compose down
```

### 4. 수동 실행 (선택사항)

Backend + TuringDB만 Docker로 실행:
```bash
docker-compose up -d
```

Frontend는 별도로 실행:
```bash
cd frontend
npm install
npm run dev
```

## 📋 주요 기능

- **3D 그래프 시각화**: WebGL 기반 인터랙티브 3D 그래프
- **줌 컨트롤**: 전체 보기, 줌 인/아웃, 자동 정렬
- **실시간 검색**: 의원 이름으로 즉시 검색
- **관계 분석**: 정당, 지역, 학교 등 다양한 관계 시각화
- **통계 대시보드**: 실시간 데이터 통계
- **반응형 디자인**: 모바일/태블릿/데스크톱 지원

## 🏗️ 아키텍처

```
┌─────────────────┐
│   Frontend      │
│ React+TypeScript│
│   Port: 80      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Backend API    │
│   (FastAPI)     │
│   Port: 5000    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   TuringDB      │
│ (Graph Database)│
│   Port: 6666    │
└─────────────────┘
```

## 🛠️ 기술 스택

### Frontend
- **React 18** - UI 라이브러리
- **TypeScript** - 타입 안전성
- **Vite** - 빌드 도구
- **React Force Graph 3D** - WebGL 기반 3D 그래프
- **Three.js** - 3D 렌더링
- **TanStack Query** - 서버 상태 관리
- **Axios** - HTTP 클라이언트
- **Zustand** - 클라이언트 상태 관리

### Backend
- **Python 3.12**
- **FastAPI** - 고성능 웹 프레임워크
- **Pandas** - 데이터 처리
- **Uvicorn** - ASGI 서버

### Database
- **인메모리 그래프 저장소** - 고속 그래프 쿼리
- **TuringDB** - 레거시 지원 (선택사항)

### DevOps
- **Docker** - 컨테이너화
- **Docker Compose** - 멀티 컨테이너 관리
- **Nginx** - 프론트엔드 서빙 및 리버스 프록시

## 📁 프로젝트 구조

```
KoreaPolitician/
├── frontend/                   # React 프론트엔드
│   ├── src/
│   │   ├── components/        # React 컴포넌트
│   │   │   ├── Header.tsx
│   │   │   ├── SearchBar.tsx
│   │   │   ├── GraphVisualization.tsx
│   │   │   ├── MemberList.tsx
│   │   │   └── Statistics.tsx
│   │   ├── api/              # API 클라이언트
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── Dockerfile
│   ├── nginx.conf
│   └── package.json
├── backend/                   # FastAPI 백엔드
│   ├── turingdb_server.py    # FastAPI 서버
│   ├── simple_importer.py    # 데이터 임포터
│   ├── graph_storage.py      # 그래프 저장소
│   ├── requirements.txt
│   └── Dockerfile
├── turingdb/                  # TuringDB 컨테이너
│   └── Dockerfile
├── docker-compose.yml
└── README.md
```

## 🔌 API 엔드포인트

### 의원 검색
```bash
GET /api/search/{member_name}
```

### 의원 관계 그래프
```bash
GET /api/graph/{member_name}?depth=2
```

### 전체 정치인 그래프
```bash
GET /api/graph/all?limit=200
```

### 통계 정보
```bash
GET /api/stats
```

## 📊 데이터 모델

### 노드 타입
- **Member**: 국회의원 (300명)
- **Party**: 정당 (8개)
- **Region**: 지역

### 관계 타입
- **BELONGS_TO**: 의원 → 정당
- **REPRESENTS**: 의원 → 지역
- **SAME_PARTY**: 의원 ↔ 의원 (같은 정당)
- **SAME_REGION**: 의원 ↔ 의원 (같은 지역)

## 🐳 Docker 명령어

### 서비스 관리
```bash
# 전체 시작
docker-compose up -d

# 프론트엔드만 재빌드
docker-compose up -d --build frontend

# 백엔드만 재시작
docker-compose restart backend

# 로그 확인
docker-compose logs -f frontend
docker-compose logs -f backend

# 중지
docker-compose down
```

## 🔧 로컬 개발

### Frontend 개발

```bash
cd frontend
npm install
npm run dev
```

Frontend는 http://localhost:3000 에서 실행됩니다.

### Backend 개발

```bash
cd backend
pip install -r requirements.txt
python turingdb_server.py
```

Backend는 http://localhost:5000 에서 실행됩니다.

## 🎨 주요 기능 설명

### 3D 그래프 시각화
- WebGL 기반 고성능 렌더링
- 마우스/터치로 회전, 줌, 팬 가능
- 정당별 색상 구분
- 관계 유형별 엣지 색상

### 검색 기능
- 실시간 자동완성
- 부분 일치 검색
- 검색 결과 하이라이트

### 통계 대시보드
- 실시간 노드/엣지 수
- 정당별 의원 수
- 관계 유형별 통계

## 📈 성능

- **초기 로딩**: < 2초
- **그래프 렌더링**: 60 FPS
- **검색 응답**: < 100ms
- **데이터 로드**: 300명 의원 < 1초

## 🔍 문제 해결

### 포트 충돌
```yaml
# docker-compose.yml에서 포트 변경
ports:
  - "8080:80"  # Frontend
  - "5001:5000"  # Backend
```

### 프론트엔드 빌드 실패
```bash
cd frontend
rm -rf node_modules
npm install
npm run build
```

### 백엔드 데이터 로드 실패
```bash
docker-compose exec backend python simple_importer.py --json assembly_members_complete.json
```

## 📚 추가 문서

- [Docker 가이드](DOCKER_GUIDE.md)
- [TuringDB 가이드](README_TURINGDB.md)
- [마이그레이션 가이드](MIGRATION_GUIDE.md)

## 🤝 기여

이슈나 개선 사항이 있으면 GitHub Issues에 등록해주세요.

## 📄 라이선스

이 프로젝트는 MIT 라이선스를 따릅니다.

## 🔗 참고 자료

- [React 문서](https://react.dev/)
- [TypeScript 문서](https://www.typescriptlang.org/)
- [FastAPI 문서](https://fastapi.tiangolo.com/)
- [React Force Graph](https://github.com/vasturiano/react-force-graph)
- [Three.js 문서](https://threejs.org/)
