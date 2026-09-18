"""화면에 나가는 날짜가 한국시간인지 본다.

2026-09-17 21:51 UTC 에 돈 회차는 한국시간으로 09-18 새벽 회차다. 그런데
기준일이 UTC 로 찍혀 2026-09-17 로 남았고, 화면의 "최근 7일" 범위도 하루
뒤처져 보였다. 한국 국회를 보는 화면이라 날짜는 한국시간이어야 한다.

    pytest backend/tests/test_service_time.py -v
"""

from datetime import datetime, timedelta, timezone

from core import service_time
from core.service_time import KST, kst_stamp, service_date, to_kst


# --- 변환 -------------------------------------------------------------------

def test_naive_timestamp_is_read_as_utc():
    """DB 의 TIMESTAMP 열에는 시간대가 없다. UTC 로 보고 옮긴다."""
    assert kst_stamp(datetime(2026, 9, 17, 21, 51, 0)) == "2026-09-18 06:51:00"


def test_aware_timestamp_is_converted():
    aware = datetime(2026, 9, 17, 21, 51, tzinfo=timezone.utc)
    assert kst_stamp(aware, "%Y-%m-%d %H:%M") == "2026-09-18 06:51"


def test_already_kst_stays_put():
    value = datetime(2026, 9, 18, 6, 51, tzinfo=KST)
    assert kst_stamp(value, "%Y-%m-%d %H:%M") == "2026-09-18 06:51"


def test_midnight_boundary():
    """15:00 UTC 가 한국시간 자정이다. 이 경계에서 날짜가 넘어간다."""
    assert kst_stamp(datetime(2026, 9, 17, 14, 59), "%Y-%m-%d") == "2026-09-17"
    assert kst_stamp(datetime(2026, 9, 17, 15, 0), "%Y-%m-%d") == "2026-09-18"


def test_missing_value_stays_missing():
    """/api/periods 는 값이 없으면 null 을 그대로 내보낸다."""
    assert kst_stamp(None) is None


def test_offset_is_fixed():
    """한국은 1988년 이후 서머타임이 없다. 계절과 무관하게 +9 다."""
    for month in (1, 7):
        moment = datetime(2026, month, 15, 3, 0, tzinfo=timezone.utc)
        assert to_kst(moment).utcoffset() == timedelta(hours=9)


# --- 기준일 -----------------------------------------------------------------

def test_service_date_follows_kst(monkeypatch):
    """새벽에 도는 회차는 UTC 로는 전날이지만 한국시간으로는 그날이다."""
    monkeypatch.setattr(service_time, "now_kst",
                        lambda: datetime(2026, 9, 18, 6, 51, tzinfo=KST))
    assert service_date() == "20260918"
    assert service_date("%Y-%m-%d") == "2026-09-18"


def test_pipeline_stamps_kst_base_date(monkeypatch, tmp_path):
    """수집 단계가 회차의 기준일을 한국시간으로 적는다."""
    import pytest

    pytest.importorskip("torch", reason="파이프라인 임포트에 필요")
    from crawlers import news_crawler_pipeline as pipe

    monkeypatch.setattr(pipe, "service_date", lambda *a: "20260918")
    monkeypatch.setattr(pipe, "collect_news", lambda deadline=None: [
        {"title": "기사", "url": "https://example.com/1", "press": "테스트", "date": ""}])
    out = tmp_path / "articles.json"

    from types import SimpleNamespace
    assert pipe.cli_collect(SimpleNamespace(out=out)) == 0

    import json
    assert json.loads(out.read_text(encoding="utf-8"))["base_date"] == "20260918"
