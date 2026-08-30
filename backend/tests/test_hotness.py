"""뉴스 기반 화제성 산출 회귀 테스트.

화제성은 원래 X·유튜브·인스타그램으로 채울 계획이었으나 전자 둘은
비로그인 수집이 막혔고 유튜브도 불안정해, 뉴스 언급을 1차 신호로 쓴다.
아래가 깨지면 화제성 테이블이 다시 비거나 잘못된 점수가 들어간다.

    POSTGRES_HOST=... PYTHONPATH=backend pytest backend/tests/test_hotness.py -v
"""

import os

import psycopg

from core.hotness import (NEWS_MENTION_BASE_SCORE, PLATFORM_NEWS, _focus_weight,
                          ensure_news_schema, rebuild_from_news, update_summary)

try:
    import pytest
except ImportError:
    pytest = None

TEST_DB = os.environ.get("POSTGRES_TEST_DB", "korea_politician_test")


def _server_config():
    return {
        "host": os.environ.get("POSTGRES_HOST", "localhost"),
        "port": int(os.environ.get("POSTGRES_PORT", 5432)),
        "user": os.environ.get("POSTGRES_USER", "postgres"),
        "password": os.environ.get("POSTGRES_PASSWORD", "1234"),
        "dbname": os.environ.get("POSTGRES_DB", "postgres"),
    }


def _make_test_db():
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
except Exception as exc:                                       # noqa: BLE001
    CFG = None
    UNAVAILABLE = f"PostgreSQL 에 접속할 수 없습니다: {exc}"


def _skip():
    if UNAVAILABLE is None:
        return False
    if pytest is not None:
        pytest.skip(UNAVAILABLE)
    print(f"  SKIP  {UNAVAILABLE}")
    return True


def _prepare(articles):
    """테스트 DB 를 초기화하고 news_sentiment 에 기사를 넣는다."""
    # core.hotness 는 환경변수로 풀을 만든다. 테스트 DB 를 보게 한다.
    os.environ["POSTGRES_DB"] = CFG["dbname"]
    from core.db_config import close_sync_pool
    close_sync_pool()  # 이전 테스트가 만든 풀은 다른 DB 를 볼 수 있다

    from core.graph_storage import GraphStorage, close_sync, run_sync
    storage = GraphStorage()
    run_sync(storage.init_db(CFG))          # 그래프/화제성 스키마
    run_sync(storage.close())
    close_sync()
    ensure_news_schema()                    # news_sentiment 스키마

    with psycopg.connect(**CFG) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE public.news_sentiment, public.politician_sns_hotness, "
                        "public.politician_hotness_summary")
            cur.executemany(
                """INSERT INTO public.news_sentiment
                   (title, url, press, date, politicians, sentiment_label,
                    sentiment_score, content, base_date)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                articles)
        conn.commit()


def test_focus_weight_penalises_name_lists():
    """여러 의원을 나열한 기사는 개인당 주목도가 낮아야 한다."""
    assert _focus_weight(1) == 1.0
    assert _focus_weight(4) == 0.5
    assert _focus_weight(1) > _focus_weight(2) > _focus_weight(10)
    # 선형이 아니라 제곱근이라 나열 기사가 0 에 수렴하지는 않는다
    assert _focus_weight(10) > 0.3


def test_records_one_row_per_member_per_article():
    if _skip():
        return
    _prepare([
        ("단독 기사", "http://x/1", "한겨레", "2026-08-31", "김민석",
         "NEGATIVE", 0.8, "본문", "20260831"),
        ("개각 기사", "http://x/2", "연합", "2026-08-31", "김민석,장동혁,용혜인",
         "NEUTRAL", 0.1, "본문", "20260831"),
    ])
    n = rebuild_from_news("20260831")
    assert n == 4, f"의원-기사 쌍 4건이어야 하는데 {n}"

    with psycopg.connect(**CFG) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM public.politician_sns_hotness "
                        "WHERE platform = %s", (PLATFORM_NEWS,))
            assert cur.fetchone()[0] == 4
            # 단독 기사가 나열 기사보다 점수가 높아야 한다
            cur.execute("""SELECT hot_score FROM public.politician_sns_hotness
                           WHERE member_name='김민석' ORDER BY hot_score DESC""")
            scores = [r[0] for r in cur.fetchall()]
            assert len(scores) == 2, scores
            assert scores[0] == NEWS_MENTION_BASE_SCORE, scores
            assert scores[1] < scores[0], scores


def test_rerun_is_idempotent():
    """같은 날 다시 돌려도 행이 늘지 않아야 한다 (upsert)."""
    if _skip():
        return
    _prepare([
        ("기사", "http://x/1", "한겨레", "2026-08-31", "김민석,장동혁",
         "NEGATIVE", 0.7, "본문", "20260831"),
    ])
    rebuild_from_news("20260831")
    rebuild_from_news("20260831")
    with psycopg.connect(**CFG) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM public.politician_sns_hotness")
            assert cur.fetchone()[0] == 2, "재실행으로 행이 늘었다"


def test_summary_reflects_mentions():
    """언급이 많은 의원의 요약 점수가 더 높아야 한다."""
    if _skip():
        return
    _prepare([
        ("기사1", "http://x/1", "한겨레", "2026-08-31", "김민석", "NEG", 0.8, "본문", "20260831"),
        ("기사2", "http://x/2", "연합", "2026-08-31", "김민석", "NEG", 0.8, "본문", "20260831"),
        ("기사3", "http://x/3", "중앙", "2026-08-31", "장동혁", "NEG", 0.8, "본문", "20260831"),
    ])
    rebuild_from_news("20260831")

    with psycopg.connect(**CFG) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT member_name, current_hot_score, top_platform
                           FROM public.politician_hotness_summary
                           ORDER BY current_hot_score DESC""")
            rows = cur.fetchall()
    assert rows, "요약이 비어 있다"
    assert rows[0][0] == "김민석", rows
    assert rows[0][1] > rows[-1][1], rows
    assert rows[0][2] == PLATFORM_NEWS, rows


def test_no_articles_is_safe():
    """해당 날짜에 기사가 없어도 예외 없이 0 을 돌려줘야 한다."""
    if _skip():
        return
    _prepare([])
    assert rebuild_from_news("20991231") == 0


def test_update_summary_on_unknown_member_does_not_raise():
    if _skip():
        return
    _prepare([])
    update_summary("존재하지않는의원")   # 예외가 나면 크롤러가 죽는다


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = []
    for fn in tests:
        try:
            fn()
        except Exception as exc:                               # noqa: BLE001
            failed.append(fn.__name__)
            print(f"  FAIL  {fn.__name__}: {exc}")
        else:
            print(f"  OK    {fn.__name__}")
    print()
    if failed:
        raise SystemExit(f"{len(failed)}개 실패")
    print(f"{len(tests)}개 테스트 통과")
