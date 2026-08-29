"""비동기 DB 계층 회귀 테스트.

psycopg3 AsyncConnectionPool 전환(커넥션 누수 수정 포함)이 계속 유효한지
확인한다. 특히 다음 회귀를 잡는 것이 목적이다.

  - 커넥션 누수: 예전 구현은 메서드마다 psycopg2.connect() 로 새 커넥션을 열고
    close() 를 하지 않아, 노드를 저장할 때마다 커넥션이 하나씩 쌓였다.
  - await 누락: DB 메서드가 코루틴이므로 await 를 빠뜨리면 조용히 실패한다.
  - Windows 이벤트 루프: psycopg3 는 ProactorEventLoop 에서 동작하지 않는다.
  - Jsonb 어댑터: psycopg3 는 타입에 엄격해 JSONB 컬럼에 str 을 넣으면 실패한다.
  - Supavisor 호환: 트랜잭션 풀러는 prepared statement 를 지원하지 않는다.

실제 PostgreSQL 이 필요하다. 접속할 수 없으면 전부 건너뛴다.
개발자의 실제 데이터를 건드리지 않도록 전용 테스트 DB 를 따로 만든다.

일회용 DB 로 실행하는 예:

    docker run -d --name kp-test-pg -e POSTGRES_PASSWORD=testpw \\
        -p 55432:5432 postgres:15-alpine

    POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432 POSTGRES_PASSWORD=testpw \\
        PYTHONPATH=backend python backend/tests/test_async_db.py

pytest 로도 실행된다:

    POSTGRES_HOST=... PYTHONPATH=backend pytest backend/tests/test_async_db.py -v
"""

import os
import threading

import psycopg

from core.graph_storage import GraphStorage, close_sync, run_sync

try:
    import pytest
except ImportError:                                   # pytest 없이 단독 실행하는 경우
    pytest = None


# 테스트 전용 DB. 운영/개발 DB 를 건드리지 않기 위해 분리한다.
TEST_DB = os.environ.get("POSTGRES_TEST_DB", "korea_politician_test")

TABLES = (
    "turing_nodes", "turing_edges", "turing_logs",
    "politician_sns_hotness", "politician_hotness_summary", "system_settings",
)


def _server_config():
    return {
        "host": os.environ.get("POSTGRES_HOST", "localhost"),
        "port": int(os.environ.get("POSTGRES_PORT", 5432)),
        "user": os.environ.get("POSTGRES_USER", "postgres"),
        "password": os.environ.get("POSTGRES_PASSWORD", "1234"),
        "dbname": os.environ.get("POSTGRES_DB", "postgres"),
    }


def _make_test_db():
    """테스트 전용 DB 를 만들고 그 접속 설정을 돌려준다."""
    admin = _server_config()
    with psycopg.connect(connect_timeout=5, autocommit=True, **admin) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{TEST_DB}"')
    cfg = dict(admin)
    cfg["dbname"] = TEST_DB
    return cfg


try:
    CFG = _make_test_db()
    UNAVAILABLE = None
except Exception as exc:                              # noqa: BLE001
    CFG = None
    UNAVAILABLE = f"PostgreSQL 에 접속할 수 없습니다: {exc}"


def _skip():
    """DB 가 없으면 True 를 돌려주고(pytest 에서는 skip 처리) 테스트를 건너뛴다."""
    if UNAVAILABLE is None:
        return False
    if pytest is not None:
        pytest.skip(UNAVAILABLE)
    print(f"  SKIP  {UNAVAILABLE}")
    return True


def _reset():
    """테이블을 지워 깨끗한 상태에서 시작한다."""
    with psycopg.connect(**CFG) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {', '.join(TABLES)} CASCADE")
        conn.commit()


def _server_connection_count():
    """서버가 보고 있는 테스트 DB 커넥션 수(자기 자신 제외)."""
    with psycopg.connect(**CFG) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (CFG["dbname"],),
            )
            return cur.fetchone()[0]


# --------------------------------------------------------------------------- #


def test_schema_is_created():
    """init_db 가 필요한 테이블을 전부 만든다."""
    if _skip():
        return
    _reset()
    storage = GraphStorage()
    try:
        run_sync(storage.init_db(CFG))
        rows = run_sync(storage.fetch_all(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
        created = {r[0] for r in rows}
        missing = set(TABLES) - created
        assert not missing, f"생성되지 않은 테이블: {sorted(missing)}"
    finally:
        run_sync(storage.close())


def test_jsonb_and_array_roundtrip():
    """properties(JSONB) 와 labels(TEXT[]) 가 파이썬 값으로 왕복한다.

    psycopg3 는 타입에 엄격해서 JSONB 컬럼에 json.dumps() 결과(str)를 넣으면
    실패한다. Jsonb 어댑터를 계속 쓰고 있는지 확인하는 회귀 테스트다.
    """
    if _skip():
        return
    _reset()
    storage = GraphStorage()
    try:
        run_sync(storage.init_db(CFG))
        run_sync(storage.add_node("n1", ["Member"], {"name": "테스트의원", "score": 99}))
        run_sync(storage.add_node("n2", ["Member"], {"name": "홍길동"}))
        run_sync(storage.add_edge("n1", "n2", "POSITIVE_SENTIMENT", {"weight": 0.5}))

        rows = run_sync(storage.fetch_all(
            "SELECT labels, properties FROM turing_nodes WHERE id = 'n1'"))
        labels, props = rows[0]
        assert labels == ["Member"], f"TEXT[] 왕복 실패: {labels!r}"
        assert isinstance(props, dict), f"JSONB 가 dict 로 오지 않음: {type(props)}"
        assert props["name"] == "테스트의원" and props["score"] == 99

        rows = run_sync(storage.fetch_all(
            "SELECT properties FROM turing_edges WHERE source_id = 'n1'"))
        assert rows[0][0]["weight"] == 0.5
    finally:
        run_sync(storage.close())


def test_upsert_does_not_duplicate():
    """같은 id 로 다시 저장하면 행이 늘지 않고 갱신된다 (ON CONFLICT)."""
    if _skip():
        return
    _reset()
    storage = GraphStorage()
    try:
        run_sync(storage.init_db(CFG))
        run_sync(storage.add_node("n1", ["Member"], {"party": "이전"}))
        run_sync(storage.add_node("n1", ["Member"], {"party": "변경"}))
        rows = run_sync(storage.fetch_all("SELECT count(*), max(properties->>'party') "
                                          "FROM turing_nodes WHERE id = 'n1'"))
        count, party = rows[0]
        assert count == 1, f"upsert 인데 행이 {count}개"
        assert party == "변경"
    finally:
        run_sync(storage.close())


def test_logs_and_settings():
    """로그 기록/검색과 설정 저장/조회가 동작한다."""
    if _skip():
        return
    _reset()
    storage = GraphStorage()
    try:
        run_sync(storage.init_db(CFG))
        run_sync(storage.add_log("테스트동작", "상세 내용"))

        logs = run_sync(storage.get_logs(limit=10))
        assert any(l["action"] == "테스트동작" for l in logs)

        found = run_sync(storage.get_logs(limit=10, search="상세"))
        assert len(found) >= 1, "ILIKE 검색이 결과를 못 찾음"

        run_sync(storage.set_setting("last_data_update", "2026-08-29"))
        assert run_sync(storage.get_setting("last_data_update")) == "2026-08-29"
        assert run_sync(storage.get_setting("없는키", "기본값")) == "기본값"
    finally:
        run_sync(storage.close())


def test_pool_does_not_leak_connections():
    """반복 호출해도 커넥션이 쌓이지 않는다.

    이 저장소의 핵심 회귀 테스트다. 예전 구현은 메서드마다 새 커넥션을 열고
    닫지 않아서, 아래 루프만으로도 서버 쪽 커넥션이 수십 개로 늘었다.
    """
    if _skip():
        return
    _reset()
    baseline = _server_connection_count()

    storage = GraphStorage()
    try:
        run_sync(storage.init_db(CFG))
        for i in range(60):
            run_sync(storage.add_node(f"n{i}", ["Member"], {"name": f"의원{i}"}))
            run_sync(storage.add_edge(f"n{i}", "n0", "SNS_INTERACTION", {"i": i}))
            run_sync(storage.get_setting("last_data_update", "-"))

        during = _server_connection_count()
        # 풀이 유지하는 커넥션만 있어야 한다. max_size 기본값은 5.
        pool_max = int(os.environ.get("DB_POOL_MAX_SIZE", "5"))
        assert during <= baseline + pool_max, (
            f"커넥션이 과도하게 열림: 기준 {baseline} -> {during} "
            f"(풀 최대 {pool_max})"
        )
    finally:
        run_sync(storage.close())

    after = _server_connection_count()
    assert after <= baseline, f"close() 후에도 커넥션이 남음: {baseline} -> {after}"


def test_sync_bridge_is_thread_safe():
    """run_sync 를 여러 스레드에서 동시에 호출해도 안전하다.

    크롤러는 Playwright sync API 때문에 async 로 만들 수 없고, ThreadPoolExecutor
    로 병렬 실행된다. 브리지는 전용 스레드의 이벤트 루프에 작업을 넘기므로
    동시 호출이 가능해야 한다.
    """
    if _skip():
        return
    _reset()
    baseline = _server_connection_count()

    storage = GraphStorage()
    run_sync(storage.init_db(CFG))
    run_sync(storage.add_node("hub", ["Member"], {"name": "허브"}))

    errors = []

    def worker(i):
        try:
            run_sync(storage.add_edge("hub", f"t{i}", f"SNS_INTERACTION_{i}", {"i": i}))
        except Exception as exc:                       # noqa: BLE001
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"동시 호출 중 오류: {errors[:3]}"

    rows = run_sync(storage.fetch_all(
        "SELECT count(*) FROM turing_edges WHERE type LIKE 'SNS_INTERACTION%%'"))
    assert rows[0][0] == 16, f"커밋된 엣지가 {rows[0][0]}/16"

    # 전역 싱글턴이 아닌 인스턴스를 썼으므로 명시적으로 넘겨서 닫는다.
    close_sync(storage)
    after = _server_connection_count()
    assert after <= baseline, f"close_sync() 후에도 커넥션이 남음: {baseline} -> {after}"


def test_api_routes():
    """FastAPI 라우트가 lifespan 포함해 동작한다.

    라우트에서 await 를 빠뜨리면 코루틴이 그대로 직렬화되며 깨지므로,
    응답 본문까지 확인한다.
    """
    if _skip():
        return
    if pytest is not None:
        pytest.importorskip("httpx", reason="TestClient 에 httpx 가 필요합니다")
    else:
        try:
            import httpx                               # noqa: F401
        except ImportError:
            print("  SKIP  httpx 가 없어 API 라우트 테스트를 건너뜁니다")
            return

    from fastapi.testclient import TestClient

    _reset()
    # 서버 lifespan 은 환경변수로 접속 정보를 읽는다. 테스트 DB 로 향하게 한다.
    saved = os.environ.get("POSTGRES_DB")
    os.environ["POSTGRES_DB"] = CFG["dbname"]
    try:
        import api.turingdb_server as server

        baseline = _server_connection_count()
        with TestClient(server.app) as client:
            for path, key in [
                ("/health", "status"),
                ("/api/graph/all?limit=10", "nodes"),
                ("/api/stats", "total_nodes"),
                ("/api/sns/trends?limit=3", "trends"),
                ("/api/activity_logs?history=true", "logs"),
                ("/api/intelligence", "top_influencers"),
            ]:
                res = client.get(path)
                assert res.status_code == 200, f"{path} -> {res.status_code}"
                assert key in res.json(), f"{path} 응답에 '{key}' 없음: {res.text[:120]}"

        after = _server_connection_count()
        assert after <= baseline, f"lifespan 종료 후 커넥션이 남음: {baseline} -> {after}"
    finally:
        if saved is None:
            os.environ.pop("POSTGRES_DB", None)
        else:
            os.environ["POSTGRES_DB"] = saved


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = []
    for fn in tests:
        try:
            fn()
        except Exception as exc:                       # noqa: BLE001
            failed.append((fn.__name__, exc))
            print(f"  FAIL  {fn.__name__}: {exc}")
        else:
            print(f"  OK    {fn.__name__}")
    print()
    if failed:
        raise SystemExit(f"{len(failed)}개 실패")
    print(f"{len(tests)}개 테스트 통과")
