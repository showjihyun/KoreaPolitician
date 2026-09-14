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


# --- 이미 시작한 기사 ------------------------------------------------------
#
# 위의 예산 검사는 기사를 "집어들 때" 만 본다. 2026-09-13 회차는 그 틈으로
# 죽었다. 기사 300건이 전부 워커에 들어간 뒤 예산이 끝났고, cancel() 은 아직
# 시작하지 않은 것만 취소하므로 "남은 기사 0건" 을 찍고는, 기사 한 건을
# 붙잡고 있는 워커를 열 분 동안 기다리다 러너에게 죽었다. 집계와 화제성은
# 실행되지 않았다(스텝 110분 한도 초과, 런 34783162544).

LONG_ARTICLE_COST = 5.0


@pytest.fixture
def stub_pipeline_with_stragglers(monkeypatch):
    """일부 기사가 아주 느린 상황. 나머지는 제때 끝난다."""
    calls = {"analyzed": [], "edges": [], "hotness": 0}

    articles = [
        {"title": f"기사 {i}", "url": f"https://example.com/{i}",
         "press": "테스트", "date": "2026-09-13"}
        for i in range(ARTICLES)
    ]

    monkeypatch.setattr(pipe, "POLITICIANS", ["가나다", "라마바"])
    monkeypatch.setattr(pipe, "crawl_naver_section", lambda sid1, **kw: [])
    monkeypatch.setattr(pipe, "collect_all_sources_for_name",
                        lambda name, deadline=None: articles)

    def fake_process(art, db_config, seen_titles, seen_contents, deadline=None):
        if deadline is not None and time.time() > deadline:
            return None
        # 다섯 건에 한 번은 예산을 훌쩍 넘겨 도는 기사다.
        slow = int(art["url"].rsplit("/", 1)[1]) % 5 == 0
        time.sleep(LONG_ARTICLE_COST if slow else 0.02)
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


def test_straggler_does_not_hold_the_run(monkeypatch, stub_pipeline_with_stragglers):
    """느린 기사를 기다리다 마무리를 놓치지 않는다.

    예산 1초 + 유예 1초를 줬다. 느린 기사는 건당 5초다. 끝까지 기다리면
    최소 5초가 걸리고, 회차에서는 그게 10분이었다.
    """
    monkeypatch.setattr(pipe, "NEWS_TIME_BUDGET_SEC", 1.0)
    monkeypatch.setattr(pipe, "NEWS_COLLECT_BUDGET_SEC", 1.0)
    monkeypatch.setattr(pipe, "NEWS_FINISH_GRACE_SEC", 1.0)

    began = time.time()
    pipe.run_pipeline(db_config=None)
    elapsed = time.time() - began

    assert elapsed < LONG_ARTICLE_COST, (
        f"느린 기사가 끝날 때까지 기다렸다({elapsed:.1f}초). "
        "예산 + 유예 안에 마무리로 넘어가야 한다")
    assert stub_pipeline_with_stragglers["hotness"] == 1, "화제성 산출이 실행되지 않았다"
    assert stub_pipeline_with_stragglers["edges"], (
        "유예 안에 끝난 기사의 관계는 집계에 들어가야 한다")


# --- 기사 한 건의 비용 ------------------------------------------------------

def test_pair_candidates_caps_names_by_mention_count():
    """나열 기사는 많이 언급된 이름만 쌍으로 본다.

    이름은 서로의 앞부분이 되지 않는 것으로 고른다. '의원1' 은 '의원15' 의
    앞부분이라 count() 가 부풀려진다. 이 저장소가 김윤/김윤덕으로 겪은 것과
    같은 함정이다(core/name_matcher.py).
    """
    names = [f"김{syllable}" for syllable in "가나다라마바사아자차카타파하거너더러머버"]
    # 뒤쪽 이름을 더 많이 언급한 본문.
    content = " ".join(names) + " " + " ".join(names[15:] * 5)

    kept = pipe.pair_candidates(names, content, limit=5)

    assert len(kept) == 5
    assert set(kept) == set(names[15:]), "많이 언급된 이름이 남아야 한다"
    assert kept == [n for n in names if n in set(kept)], "기사에 나온 순서를 지켜야 한다"


def test_pair_candidates_keeps_small_articles_untouched():
    names = ["김민석", "정청래", "나경원"]
    assert pipe.pair_candidates(names, "김민석 정청래 나경원") == names


def test_pair_loop_stops_at_deadline(monkeypatch):
    """예산을 넘기면 기사 하나의 쌍 루프에서도 빠져나온다.

    쌍 하나가 몇 초씩 걸리는 기사가 있다. 쌍 사이에서 시계를 보지 않으면
    기사 한 건이 남은 예산을 다 먹는다.
    """
    names = [f"의원{i}" for i in range(8)]          # 28쌍
    content = "본문. " * 100
    seen = []

    class SlowAnalyzer:
        def analyze_pair(self, text, a, b, candidates=None):
            seen.append((a, b))
            time.sleep(0.05)
            return None

    monkeypatch.setattr(pipe, "analyzer", SlowAnalyzer())
    monkeypatch.setattr(pipe, "get_article_text", lambda url: content)
    monkeypatch.setattr(pipe, "extract_politicians", lambda text, pols: names)
    monkeypatch.setattr(pipe, "save_to_postgresql", lambda arts, cfg: None)
    monkeypatch.setattr(pipe, "save_observations", lambda art: [])

    art = {"title": "의원 여덟 명이 나오는 기사", "url": "https://example.com/many"}
    pipe.process_article(art, None, set(), set(), deadline=time.time() + 0.2)

    assert len(seen) < 28, f"예산을 넘겼는데 {len(seen)}쌍을 끝까지 돌았다"
    assert art["relationships"] == [], "판정한 쌍이 없으면 빈 목록이어야 한다"


def test_capped_names_limit_the_pairs(monkeypatch):
    """이름이 많은 기사는 상한만큼만 쌍을 만든다."""
    names = [f"의원{i}" for i in range(20)]          # 원래라면 190쌍
    seen = []

    class CountingAnalyzer:
        def analyze_pair(self, text, a, b, candidates=None):
            seen.append((a, b))
            # 이름 확인용 후보는 기사에 나온 전체가 넘어와야 한다.
            assert candidates == names
            return None

    monkeypatch.setattr(pipe, "RELATION_MAX_NAMES_PER_ARTICLE", 6)
    monkeypatch.setattr(pipe, "analyzer", CountingAnalyzer())
    monkeypatch.setattr(pipe, "get_article_text", lambda url: "본문. " * 100)
    monkeypatch.setattr(pipe, "extract_politicians", lambda text, pols: names)
    monkeypatch.setattr(pipe, "save_to_postgresql", lambda arts, cfg: None)
    monkeypatch.setattr(pipe, "save_observations", lambda art: [])

    art = {"title": "나열 기사", "url": "https://example.com/roundup"}
    pipe.process_article(art, None, set(), set())

    assert len(seen) == 15, f"6개 이름이면 15쌍인데 {len(seen)}쌍을 돌았다"


def test_collect_respects_deadline():
    """수집 예산을 넘긴 뒤 등록된 검색은 브라우저를 띄우지 않는다."""
    assert pipe.collect_all_sources_for_name("홍길동", deadline=time.time() - 1) == []
