"""뉴스 파이프라인의 시간 예산 회귀 테스트.

2026-09-04 부터 09-09 까지 여섯 회차가 전부 GitHub Actions 90분 한도에
걸려 취소됐다. 기사 저장은 기사마다 하지만 엣지 집계와 화제성 산출은
분석 루프가 끝난 뒤 한 번 도는 구조라, 루프 도중에 죽으면 그날 수집분이
화면에 한 건도 반영되지 않는다. API 의 last_updated 가 2026-09-03 에
멈춰 있던 이유가 이것이다.

여기서 지키려는 것은 속도가 아니라 **마무리 도달**이다. 예산을 넘겨도
집계와 화제성이 반드시 실행돼야 한다.

    pytest backend/tests/test_news_time_budget.py -v
"""

import time

import pytest

pytest.importorskip("torch", reason="파이프라인 임포트에 필요")

from crawlers import news_crawler_pipeline as pipe


#: 가짜 기사 한 건의 비용과 개수. 워커 8개이므로 전부 처리하려면
#: ARTICLES / 8 * COST = 1.25초가 걸린다. 예산을 그보다 짧게 줘야
#: 초과 상황이 만들어진다.
ARTICLES = 40
ARTICLE_COST = 0.25
SHORT_BUDGET = 0.4


@pytest.fixture
def fast_budget(monkeypatch):
    """예산을 짧게 줄여 초과 상황을 만든다."""
    monkeypatch.setattr(pipe, "NEWS_TIME_BUDGET_SEC", SHORT_BUDGET)
    monkeypatch.setattr(pipe, "NEWS_COLLECT_BUDGET_SEC", SHORT_BUDGET)


@pytest.fixture
def stub_pipeline(monkeypatch):
    """수집·저장·집계를 전부 가짜로 바꾼 뒤 호출 기록을 돌려준다."""
    calls = {"analyzed": [], "edges": [], "hotness": 0}

    articles = [
        {"title": f"기사 {i}", "url": f"https://example.com/{i}",
         "press": "테스트", "date": "2026-09-10"}
        for i in range(ARTICLES)
    ]

    monkeypatch.setattr(pipe, "POLITICIANS", ["가나다", "라마바"])
    monkeypatch.setattr(pipe, "crawl_naver_section", lambda sid1, **kw: [])
    monkeypatch.setattr(pipe, "collect_all_sources_for_name",
                        lambda name, deadline=None: articles)

    def fake_process(art, db_config, seen_titles, seen_contents, deadline=None):
        if deadline is not None and time.time() > deadline:
            return None
        time.sleep(ARTICLE_COST)  # 기사 한 건의 비용을 흉내낸다
        calls["analyzed"].append(art["url"])
        return art["title"], [f"pair::{art['url']}"]

    def fake_push(pairs):
        calls["edges"].extend(pairs)
        return len(pairs), len(pairs)

    def fake_hotness(base_date):
        calls["hotness"] += 1
        return 1

    monkeypatch.setattr(pipe, "process_article", fake_process)
    monkeypatch.setattr(pipe, "push_aggregated_edges", fake_push)
    monkeypatch.setattr(pipe, "rebuild_from_news", fake_hotness)
    monkeypatch.setattr(pipe, "wake_api", lambda *a, **kw: True)
    return calls


def test_budget_overrun_still_reaches_aggregation(fast_budget, stub_pipeline):
    """예산을 넘겨도 집계와 화제성은 반드시 돈다.

    이게 이번 장애의 핵심이다. 예전 코드는 러너가 프로세스를 죽였고,
    그러면 아래 두 단계가 통째로 실행되지 않았다.
    """
    saved = pipe.run_pipeline(db_config=None)

    assert saved > 0, "예산을 넘겨도 그때까지 분석한 기사는 저장돼야 한다"
    assert stub_pipeline["edges"], "엣지 집계가 실행되지 않았다"
    assert stub_pipeline["hotness"] == 1, "화제성 산출이 실행되지 않았다"


def test_budget_overrun_drops_remaining_articles(fast_budget, stub_pipeline):
    """예산을 넘기면 남은 기사는 다음 회차로 넘긴다."""
    pipe.run_pipeline(db_config=None)

    analyzed = len(stub_pipeline["analyzed"])
    assert analyzed < ARTICLES, f"예산을 넘겼는데도 {analyzed}건을 전부 처리했다"


def test_full_budget_processes_everything(monkeypatch, stub_pipeline):
    """예산이 넉넉하면 예전과 똑같이 전부 처리한다."""
    monkeypatch.setattr(pipe, "NEWS_TIME_BUDGET_SEC", 600)
    monkeypatch.setattr(pipe, "NEWS_COLLECT_BUDGET_SEC", 600)

    saved = pipe.run_pipeline(db_config=None)

    assert saved == ARTICLES
    assert len(stub_pipeline["edges"]) == ARTICLES
    assert stub_pipeline["hotness"] == 1


def test_process_article_respects_deadline():
    """워커가 이미 집어간 기사도 예산을 넘겼으면 손대지 않는다."""
    art = {"title": "지난 기사", "url": "https://example.com/late"}
    result = pipe.process_article(art, None, set(), set(), deadline=time.time() - 1)
    assert result is None


def test_collect_respects_deadline():
    """수집 예산을 넘긴 뒤 등록된 검색은 브라우저를 띄우지 않는다."""
    assert pipe.collect_all_sources_for_name("홍길동", deadline=time.time() - 1) == []
