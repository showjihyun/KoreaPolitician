"""관계 근거 로그의 DB 왕복 회귀 테스트.

순수 함수는 test_relation_evidence.py 가 본다. 여기서는 적재와 조회,
그리고 같은 기사를 다시 넣어도 표본이 부풀지 않는지를 확인한다. 표본이
부풀면 신뢰도가 실제보다 높게 나온다.

    POSTGRES_HOST=... PYTHONPATH=backend pytest backend/tests/test_relation_evidence_db.py -v
"""

import os

import psycopg

try:
    import pytest
except ImportError:  # pragma: no cover
    pytest = None

from core import db_config, relation_evidence as ev

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
            if not cur.fetchone():
                cur.execute(f'CREATE DATABASE "{TEST_DB}"')


def setup_module(module):
    try:
        _make_test_db()
    except Exception as exc:  # pragma: no cover
        if pytest:
            pytest.skip(f"테스트용 Postgres 를 쓸 수 없습니다: {exc}",
                        allow_module_level=True)
        raise

    os.environ["POSTGRES_DB"] = TEST_DB
    db_config.close_sync_pool()
    ev.ensure_schema()
    with db_config.get_sync_pool().connection() as conn:
        conn.execute("TRUNCATE public.edge_observations")


def teardown_module(module):
    db_config.close_sync_pool()


def _row(url, press, polarity=-1, score=0.9, body="본문", title=None):
    return {
        "entity_a": "이을순", "entity_b": "김갑동",   # 일부러 역순으로 넣는다
        "polarity": polarity, "score": score, "focus_weight": 1.0,
        "press": press, "url": url, "title": title or f"{press} 기사",
        "article_date": "20260902", "simhash": ev.simhash(body),
        "evidence": "근거 문장",
    }


def test_round_trip_keeps_every_article():
    """엣지 덮어쓰기와 달리, 기사마다 근거가 남아야 한다."""
    ev.record_observations([
        _row("https://example.com/a", "조선일보", body="보수지 취재 " * 20),
        _row("https://example.com/b", "한겨레", body="진보지 취재 " * 20),
    ])
    key = ev.pair_key("김갑동", "이을순")
    loaded = ev.load_observations([key])[key]
    assert len(loaded) == 2
    assert {o["press"] for o in loaded} == {"조선일보", "한겨레"}


def test_pair_key_is_canonical_regardless_of_input_order():
    """넣을 때 순서가 뒤집혀도 같은 쌍으로 모여야 한다."""
    key = ev.pair_key("김갑동", "이을순")
    loaded = ev.load_observations([key])[key]
    assert loaded, "역순으로 넣은 관측이 정렬된 키로 조회돼야 한다"
    assert all(o["entity_a"] == "김갑동" and o["entity_b"] == "이을순" for o in loaded)


def test_recrawling_the_same_article_does_not_inflate_the_sample():
    """재수집으로 표본이 늘면 신뢰도가 실제보다 높아진다."""
    key = ev.pair_key("김갑동", "이을순")
    before = len(ev.load_observations([key])[key])

    for _ in range(3):
        ev.record_observations([
            _row("https://example.com/a", "조선일보", body="보수지 취재 " * 20),
        ])

    after = ev.load_observations([key])[key]
    assert len(after) == before


def test_aggregate_pairs_reads_from_the_log():
    key = ev.pair_key("김갑동", "이을순")
    edges = ev.aggregate_pairs([key])
    assert key in edges
    props = edges[key]["properties"]
    assert edges[key]["type"] == ev.NEGATIVE
    assert props["n_observations"] == 2
    assert props["n_clusters"] == 2               # 서로 다른 취재
    assert props["camp_coverage"] > 1 / 3         # 보수 + 진보
    assert props["provenance"] == "aggregate"


def test_all_pair_keys_lists_the_pair():
    assert ev.pair_key("김갑동", "이을순") in ev.all_pair_keys()


def test_publish_edges_posts_one_request_per_pair(monkeypatch):
    """반영은 기사마다가 아니라 쌍마다 한 번이어야 한다.

    예전에는 기사 하나가 관계 하나를 POST 했다. 지금은 근거를 모두 모아
    집계한 뒤 쌍당 한 번만 보낸다. 소급 이관 스크립트도 같은 함수를 쓴다.
    """
    key = ev.pair_key("김갑동", "이을순")
    sent = []

    class _Response:
        status_code = 200
        text = ""

    def _fake_post(url, json=None, headers=None, timeout=None):
        sent.append({"url": url, "payload": json, "headers": headers or {}})
        return _Response()

    import requests
    monkeypatch.setattr(requests, "post", _fake_post)
    monkeypatch.setenv("API_BASE_URL", "https://example.test")
    monkeypatch.setenv("API_WRITE_TOKEN", "tok")

    saved, total = ev.publish_edges([key, key])          # 중복을 줘도 한 번
    assert (saved, total) == (1, 1)
    assert len(sent) == 1, "쌍 하나에 요청이 여러 번 나갔다"

    request = sent[0]
    assert request["url"] == "https://example.test/api/edge"
    assert request["headers"].get("X-API-Key") == "tok"

    payload = request["payload"]
    assert [payload["source"], payload["target"]] == ["김갑동", "이을순"]
    assert payload["type"] in (ev.POSITIVE, ev.NEGATIVE)
    # 화면과 감사가 읽는 값이 실려 나가야 한다.
    for field in ("camp_coverage", "display_weight", "confidence",
                  "n_clusters", "provenance"):
        assert field in payload["properties"], field


def test_publish_edges_with_no_pairs_is_a_no_op(monkeypatch):
    import requests

    def _explode(*args, **kwargs):
        raise AssertionError("보낼 것이 없는데 요청이 나갔다")

    monkeypatch.setattr(requests, "post", _explode)
    assert ev.publish_edges([]) == (0, 0)
    assert ev.publish_edges([None, ""]) == (0, 0)


def test_uncollected_cosponsorship_is_not_reported_as_zero():
    """'확인한 적 없음' 과 '함께 발의한 적 없음' 은 다른 진술이다.

    둘을 같이 0 으로 돌려주면 감사 화면에서 협력한 적 없는 사이처럼
    보인다. 국회 API 키가 없어 수집을 못 하는 동안 특히 중요하다.
    """
    from core import cosponsorship as cs

    cs.ensure_schema()
    with db_config.get_sync_pool().connection() as conn:
        conn.execute("TRUNCATE public.assembly_bills")
        conn.execute("TRUNCATE public.cosponsorship")

    assert cs.is_populated() is False
    assert cs.bills_between("김갑동", "이을순") is None

    cs.save_bills([{"bill_id": "B1", "rst_proposer": "김갑동",
                    "publ_proposer": "이을순", "propose_dt": "20260901", "age": "22"}])
    cs.rebuild_pairs(["김갑동", "이을순", "박병수"], age="22")

    assert cs.bills_between("김갑동", "이을순") == 1
    # 수집은 됐고 함께 발의한 적만 없는 경우는 0 이다.
    assert cs.bills_between("김갑동", "박병수") == 0
