# 백엔드 무료 호스팅 가이드

전부 무료 티어로 구성합니다. 신용카드 없이 시작할 수 있습니다.

| 구성 요소 | 서비스 | 무료 조건 |
| --- | --- | --- |
| PostgreSQL | [Neon](https://neon.tech) | 0.5GB 저장, 월 100 compute-hour, 영구 무료, 카드 불필요 |
| API 서버 | [Render](https://render.com) Web Service | 512MB RAM, 15분 미사용 시 슬립(재기동 30~60초) |
| 크롤러 | GitHub Actions | 공개 저장소는 표준 러너 무료, 16GB RAM |

크롤러를 서버가 아닌 GitHub Actions 에서 돌리는 이유는 다음과 같습니다.
뉴스 파이프라인이 Playwright(Chromium)와 torch·transformers(KoBERT 감성분석)를
쓰는데, 이 조합은 512MB 무료 인스턴스에서 동작하지 않습니다. 반면 크롤링은
상시 서비스가 아니라 주기적 배치라 Actions 러너에 잘 맞습니다.

---

## 1. Neon PostgreSQL

1. [neon.tech](https://neon.tech) 가입 → 프로젝트 생성 (리전은 `AWS ap-southeast-1` 권장)
2. Connection Details 에서 host / database / user / password 확인
3. 스키마는 서버가 최초 기동할 때 `core/graph_storage.py` 가 자동 생성하고,
   `data/assembly_members_complete.json` 을 자동으로 임포트합니다. 수동 작업은 없습니다.

Neon 은 SSL 을 요구합니다. 코드 수정 없이 `PGSSLMODE=require` 환경변수로 처리합니다
(libpq 가 직접 읽습니다).

## 2. Render API 서버

저장소에 `render.yaml` 블루프린트가 있습니다.

1. Render 대시보드 → **New → Blueprint** → 이 저장소 선택
2. 아래 환경변수를 Neon 값으로 채웁니다.

| 변수 | 값 |
| --- | --- |
| `POSTGRES_HOST` | Neon 호스트 (`ep-...aws.neon.tech`) |
| `POSTGRES_USER` | Neon 사용자 |
| `POSTGRES_PASSWORD` | Neon 비밀번호 |
| `POSTGRES_DB` | Neon 데이터베이스명 |

`POSTGRES_PORT`(5432)와 `PGSSLMODE`(require)는 블루프린트에 이미 들어 있습니다.

3. 배포 후 `https://<서비스명>.onrender.com/health` 로 확인합니다.

### 프론트엔드 연결

Vercel(`korea-politician`) → Settings → Environment Variables 에 추가한 뒤 **재배포**합니다.
Vite 환경변수는 런타임이 아니라 빌드 타임에 번들에 박히므로 재배포가 반드시 필요합니다.

```
VITE_API_BASE_URL = https://<서비스명>.onrender.com/api
```

백엔드는 CORS 가 `allow_origins=["*"]` 로 열려 있어 별도 설정이 필요 없습니다.

## 3. 크롤러 (GitHub Actions)

`.github/workflows/crawl.yml` 이 매일 04:00 KST 에 실행되고, Actions 탭에서 수동
실행(`workflow_dispatch`)도 가능합니다.

저장소 → Settings → Secrets and variables → Actions 에 다음을 등록합니다.

```
POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
```

`backend/scripts/run_news_sns.py` 는 `while True` 데몬이라 스케줄 실행에 맞지 않습니다.
워크플로는 동일한 두 파이프라인(`news_crawler_pipeline.py`, `sns_crawler_pipeline.py`)을
1회씩 직접 호출합니다.

---

## 로컬에서 이미지 확인

빌드 컨텍스트는 `backend/` 가 아니라 **저장소 루트**입니다. 회원 데이터(`data/`)와
사진(`img/`)이 `backend/` 바깥에 있어서, docker-compose 는 이를 바인드 마운트로
넣어주지만 호스팅 환경에는 마운트가 없기 때문입니다. 루트 `Dockerfile` 이 두
경로를 이미지에 함께 담습니다.

```bash
docker build -t korea-politician-api .
docker run -p 5000:5000 \
  -e POSTGRES_HOST=... -e POSTGRES_USER=... -e POSTGRES_PASSWORD=... \
  -e POSTGRES_DB=... -e PGSSLMODE=require \
  korea-politician-api
```

## 무료 티어에서 알아둘 점

- **첫 요청이 느립니다.** Render 무료 인스턴스는 15분 미사용 시 내려가고, 다음 요청에서
  30~60초 걸려 다시 뜹니다. Neon 도 scale-to-zero 라 여기에 0.3~0.5초가 더 붙습니다.
- **Neon 월 100 compute-hour** 는 상시 연결을 유지하면 약 4일이면 소진됩니다.
  scale-to-zero 가 동작하도록 유휴 시 연결을 놓아두는 편이 좋습니다.
- **Render 무료 Postgres 는 90일 후 만료**됩니다. 그래서 DB 를 Neon 으로 분리했습니다.
- 슬립이 곤란해지면 Render Starter(월 $7) 또는 Fly.io 유료로 올리는 것이 가장 간단합니다.

## 의존성 구조

| 파일 | 용도 |
| --- | --- |
| `backend/requirements-api.txt` | API 서버 런타임 (fastapi, uvicorn, psycopg2, Pillow) |
| `backend/requirements-crawler.txt` | 크롤러 (playwright, torch, transformers, newspaper3k 등) |
| `backend/requirements.txt` | 로컬 전체 개발용 |

`requirements.txt` 에 있던 `turingdb` 는 PyPI 에 존재하지 않아 `pip install` 이 통째로
실패하고 있었습니다. 주석 처리했고, 실제로는 `scripts/turingdb_importer.py` 에서만
쓰입니다. API 서버와 크롤러는 `core/graph_storage.py` 를 통해 PostgreSQL 을 사용합니다.
크롤러가 쓰는데 누락돼 있던 `python-dotenv` 도 추가했습니다.
