# 백엔드 무료 호스팅 가이드

전부 무료 티어로 구성합니다. 신용카드 없이 시작할 수 있습니다.

| 구성 요소 | 서비스 | 무료 조건 |
| --- | --- | --- |
| PostgreSQL | [Supabase](https://supabase.com) | 500MB DB, 1GB 스토리지, API 요청 무제한, 프로젝트 2개 |
| API 서버 | [Render](https://render.com) Web Service | 월 750 instance-hour, 15분 미사용 시 슬립(재기동 약 1분). **웹 서비스 자체는 만료 없음** |
| 크롤러 | GitHub Actions | 공개 저장소는 표준 러너 무료, 16GB RAM |

크롤러를 서버가 아닌 GitHub Actions 에서 돌리는 이유는 다음과 같습니다.
뉴스 파이프라인이 Playwright(Chromium)와 torch·transformers(KoBERT 감성분석)를
쓰는데, 이 조합은 512MB 무료 인스턴스에서 동작하지 않습니다. 반면 크롤링은
상시 서비스가 아니라 주기적 배치라 Actions 러너에 잘 맞습니다.

> Supabase 무료 프로젝트는 **7일간 DB 활동이 없으면 일시정지**되고 수동으로
> 재개해야 합니다. 이 저장소는 크롤러 워크플로가 매일 DB에 쓰기 때문에
> 해당 상태에 도달하지 않습니다. 워크플로를 끄면 이 보호가 사라집니다.

---

## 1. Supabase PostgreSQL

1. [supabase.com](https://supabase.com) 가입 → New project (리전은 `Northeast Asia (Seoul)` 권장)
2. Project Settings → Database 에서 접속 정보 확인
3. 스키마는 서버가 최초 기동할 때 `core/graph_storage.py` 가 자동 생성하고,
   `data/assembly_members_complete.json` 을 자동으로 임포트합니다. 수동 작업은 없습니다.

### 포트는 6543 (Supavisor 트랜잭션 풀러)

직결 포트 5432 가 아니라 **6543** 을 쓰십시오. 무료 플랜은 직결 커넥션 수가
적고, 애플리케이션은 요청마다 풀에서 커넥션을 빌려 쓰기 때문에 풀러 경유가
맞습니다. 트랜잭션 풀러는 prepared statement 를 지원하지 않으므로
`graph_storage.py` 가 `prepare_threshold=None` 으로 이를 비활성화합니다.

SSL 은 `PGSSLMODE=require` 환경변수로 처리합니다(libpq 가 직접 읽습니다).

## 2. Render API 서버

저장소에 `render.yaml` 블루프린트가 있습니다.

1. Render 대시보드 → **New → Blueprint** → 이 저장소 선택
2. 아래 환경변수를 Supabase 값으로 채웁니다.

| 변수 | 값 |
| --- | --- |
| `POSTGRES_HOST` | `aws-0-....pooler.supabase.com` |
| `POSTGRES_USER` | `postgres.<project-ref>` |
| `POSTGRES_PASSWORD` | 프로젝트 DB 비밀번호 |
| `POSTGRES_DB` | `postgres` |

`POSTGRES_PORT`(6543), `PGSSLMODE`(require), `DB_POOL_MAX_SIZE`(5)는
블루프린트에 이미 들어 있습니다.

`API_WRITE_TOKEN` 은 Render 가 자동 생성합니다(`generateValue: true`). 생성된
값을 확인해 GitHub Actions 시크릿에도 같은 값을 등록해야 크롤러가 관계를
저장할 수 있습니다.

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `API_WRITE_TOKEN` | (자동 생성) | `POST /api/edge` 인증 토큰. **없으면 쓰기가 503 으로 막힙니다.** |
| `CORS_ALLOW_ORIGINS` | 전체 허용 | 쉼표 구분 출처 목록. 프론트 도메인만 남기는 것을 권장합니다. |
| `DB_POOL_MAX_SIZE` | 5 | 커넥션 풀 최대 크기 |
| `SNS_RETENTION_DAYS` | 90 | 이 기간이 지난 SNS 원본 행을 크롤러가 삭제합니다 |

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
API_BASE_URL      # 예: https://korea-politician-api.onrender.com
API_WRITE_TOKEN   # Render 의 값과 동일해야 함
```

> 시크릿을 등록하지 않으면 GitHub Actions 는 해당 환경변수를 "없음"이 아니라
> **빈 문자열**로 주입합니다. `core/db_config.py` 가 빈 값을 미설정으로
> 처리하지만, 접속 정보가 비면 결국 로컬 기본값으로 붙으려다 실패하므로
> 위 목록은 전부 등록해야 합니다.

`API_BASE_URL` 이 필요한 이유는, 뉴스 파이프라인의 `save_to_turingdb()` 가 탐지한
관계를 API 의 `/api/edge` 로 POST 하기 때문입니다. 값이 없으면 `localhost:5000`
으로 붙어 러너에서 실패합니다.

`backend/scripts/run_news_sns.py` 는 `while True` 데몬이라 스케줄 실행에 맞지 않습니다.
워크플로는 동일한 두 파이프라인(`news_crawler_pipeline.py`, `sns_crawler_pipeline.py`)을
1회씩 직접 호출합니다.

---

## DB 접근 구조

드라이버는 **psycopg3** 이고, API 서버의 DB 접근은 전부 async 입니다.

- `core/graph_storage.py` 가 `AsyncConnectionPool` 을 하나 유지합니다.
  풀은 FastAPI `lifespan` 에서 열리고 종료 시 닫힙니다.
- DB 를 만지는 저장소 메서드(`add_node`, `add_edge`, `get_logs`, `get_setting`,
  `get_statistics`, `get_intelligence` 등)는 모두 코루틴이며, 커넥션은
  `async with pool.connection()` 으로 빌려 블록을 벗어날 때 커밋(예외 시 롤백)
  후 반드시 반납됩니다.
- 인메모리 그래프만 읽는 메서드(`find_nodes`, `get_relationships`, `get_path`,
  `get_node`)는 DB 를 거치지 않으므로 동기 그대로입니다.

### 크롤러가 동기인 이유

크롤러는 Playwright **sync API** 를 씁니다. sync API 는 실행 중인 asyncio 루프
안에서 호출할 수 없어서, 크롤러를 async 로 만들려면 Playwright 호출 전체를
async API 로 재작성해야 합니다. 대신 `graph_storage.run_sync()` 브리지를 통해
같은 비동기 풀을 사용합니다. 이 브리지는 전용 스레드에서 이벤트 루프를 하나
돌리고 `run_coroutine_threadsafe` 로 작업을 넘기므로, 크롤러가
`ThreadPoolExecutor` 로 동시에 호출해도 안전합니다. 종료 시에는
`close_sync()`(또는 `atexit`)로 풀과 루프를 정리합니다.

### 회귀 테스트

`backend/tests/test_async_db.py` 가 위 구조를 지킨다. 커넥션 누수, await 누락,
Jsonb 어댑터, 스레드 브리지, 라우트 동작을 실제 PostgreSQL 로 확인한다.

```bash
docker run -d --name kp-test-pg -e POSTGRES_PASSWORD=testpw -p 55432:5432 postgres:15-alpine
pip install -r backend/requirements-api.txt -r backend/requirements-dev.txt

POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432 POSTGRES_PASSWORD=testpw   PYTHONPATH=backend pytest backend/tests/test_async_db.py -v
```

`korea_politician_test` DB 를 따로 만들어 쓰므로 개발용 데이터는 건드리지
않는다. PostgreSQL 에 접속할 수 없으면 전부 skip 된다.

## 의존성 구조

| 파일 | 용도 |
| --- | --- |
| `backend/requirements-api.txt` | API 서버 런타임 (fastapi, uvicorn, psycopg3, Pillow) |
| `backend/requirements-crawler.txt` | 크롤러 (playwright, torch, transformers, newspaper3k 등) |
| `backend/requirements.txt` | 로컬 전체 개발용 |
| `backend/requirements-dev.txt` | 테스트용 (pytest, httpx) |

## 무료 티어에서 알아둘 점

- **첫 요청이 느립니다.** Render 무료 인스턴스는 15분 미사용 시 내려가고, 다음 요청에서
  30~60초 걸려 다시 뜹니다.
- **Supabase 는 7일 무활동 시 일시정지**됩니다. 크롤러 워크플로가 매일 돌면
  발생하지 않습니다.
- **백업이 없습니다.** 무료 플랜에는 자동 백업이 포함되지 않습니다.
- 슬립이 곤란해지면 Render Starter(월 $7) 로 올리는 것이 가장 간단합니다.
