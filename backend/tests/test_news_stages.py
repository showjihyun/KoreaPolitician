"""뉴스 파이프라인을 러너 여러 대로 나눠 돌리는 단계 실행의 회귀 테스트.

2026-09-15, 09-16 두 회차는 러너 한 대(vCPU 4개)에서 90분 예산에 걸려
300건 중 215건, 176건만 분석했다. 그래서 수집 한 번 -> 분석 여러 대 ->
마무리 한 번으로 나눴다. 여기서 지키려는 것은 세 가지다.

  1. 기사가 러너 사이에 빠지거나 겹치지 않는다.
  2. 러너 사이에 오가는 파일만으로 다음 단계가 돈다.
  3. 분석 러너 하나가 죽어도 마무리는 돌고, 그 러너가 저장한 근거도 집계된다.

    pytest backend/tests/test_news_stages.py -v
"""

import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

pytest.importorskip("torch", reason="파이프라인 임포트에 필요")

from crawlers import news_crawler_pipeline as pipe


def _articles(n, prefix="기사"):
    return [{"title": f"{prefix} {i}", "url": f"https://example.com/{prefix}/{i}",
             "press": "테스트", "date": "2026-09-17"} for i in range(n)]


# --- 샤드 나누기 -------------------------------------------------------------

def test_shards_cover_every_article_exactly_once():
    articles = _articles(301)
    shards = [pipe.select_shard(articles, i, 4) for i in range(4)]

    urls = [a["url"] for shard in shards for a in shard]
    assert sorted(urls) == sorted(a["url"] for a in articles), "빠지거나 겹친 기사가 있다"
    assert max(map(len, shards)) - min(map(len, shards)) <= 1, "한 러너에 몰렸다"


def test_same_list_splits_the_same_way():
    """러너마다 같은 파일을 받아 제 몫을 고른다. 매번 같게 갈려야 한다."""
    articles = _articles(50)
    assert pipe.select_shard(articles, 2, 3) == pipe.select_shard(list(articles), 2, 3)


@pytest.mark.parametrize("shard, shards", [(4, 4), (-1, 4), (0, 0)])
def test_invalid_shard_is_rejected(shard, shards):
    with pytest.raises(ValueError):
        pipe.select_shard(_articles(3), shard, shards)


# --- 수집 -------------------------------------------------------------------

def test_collect_drops_same_title_from_different_urls(monkeypatch):
    """제목이 같은 기사는 나누기 전에 걸러야 두 러너가 따로 분석하지 않는다."""
    same = [{"title": "같은 제목", "url": "https://a.example/1", "press": "가", "date": ""},
            {"title": "같은 제목", "url": "https://b.example/2", "press": "나", "date": ""},
            {"title": "다른 제목", "url": "https://c.example/3", "press": "다", "date": ""}]
    monkeypatch.setattr(pipe, "POLITICIANS", ["가나다"])
    monkeypatch.setattr(pipe, "crawl_naver_section", lambda sid1, **kw: [])
    monkeypatch.setattr(pipe, "collect_all_sources_for_name", lambda name, deadline=None: same)

    kept = pipe.collect_news()

    assert [a["url"] for a in kept] == ["https://a.example/1", "https://c.example/3"]


# --- 단계 사이의 파일 ---------------------------------------------------------

@pytest.fixture
def staged(monkeypatch, tmp_path):
    """DB·API·브라우저·모델을 전부 가짜로 바꾼 단계 실행 환경."""
    calls = {"processed": [], "published": [], "hotness": [], "since": []}
    articles = _articles(10)

    monkeypatch.setattr(pipe, "POLITICIANS", ["가나다"])
    monkeypatch.setattr(pipe, "crawl_naver_section", lambda sid1, **kw: [])
    monkeypatch.setattr(pipe, "collect_all_sources_for_name",
                        lambda name, deadline=None: articles)
    monkeypatch.setattr(pipe, "ensure_news_schema", lambda: None)
    monkeypatch.setattr(pipe.relation_evidence, "ensure_schema", lambda: None)
    monkeypatch.setattr(pipe, "wake_api", lambda *a, **kw: True)

    def fake_process(art, db_config, seen_titles, seen_contents, deadline=None):
        calls["processed"].append((art["url"], art.get("base_date")))
        return art["title"], [f"쌍|{art['url'].rsplit('/', 1)[1]}"]

    def fake_publish(pairs):
        calls["published"].append(sorted(pairs))
        return len(pairs), len(pairs)

    def fake_since(since, source="news"):
        calls["since"].append(since)
        return ["쌍|db에서만"]

    monkeypatch.setattr(pipe, "process_article", fake_process)
    monkeypatch.setattr(pipe, "push_aggregated_edges", fake_publish)
    monkeypatch.setattr(pipe, "rebuild_from_news", lambda d: calls["hotness"].append(d) or 1)
    monkeypatch.setattr(pipe.relation_evidence, "pair_keys_observed_since", fake_since)

    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    return SimpleNamespace(calls=calls, dir=tmp_path, output=output)


def _outputs(path):
    return dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines())


def test_stages_hand_off_through_files(staged):
    articles_json = staged.dir / "articles.json"
    assert pipe.cli_collect(SimpleNamespace(out=articles_json)) == 0

    out = _outputs(staged.output)
    payload = json.loads(articles_json.read_text(encoding="utf-8"))
    assert len(payload["articles"]) == 10 and out["articles"] == "10"
    assert out["base_date"] == payload["base_date"]

    for shard in range(3):
        code = pipe.cli_analyze(SimpleNamespace(articles=articles_json, shard=shard, shards=3,
                                                out=staged.dir / "pairs" / f"pairs-{shard}.json"))
        assert code == 0

    assert len(staged.calls["processed"]) == 10, "기사가 러너 사이에서 빠지거나 겹쳤다"
    assert {d for _, d in staged.calls["processed"]} == {payload["base_date"]}, (
        "기사마다 날짜를 새로 찍으면 자정을 넘긴 회차에서 화제성과 갈라진다")

    code = pipe.cli_finish(SimpleNamespace(pairs_dir=staged.dir / "pairs", shards=3,
                                           base_date=out["base_date"], since=out["since"]))
    assert code == 0
    published = staged.calls["published"][0]
    assert len([p for p in published if p != "쌍|db에서만"]) == 10
    assert staged.calls["hotness"] == [payload["base_date"]]


def test_finish_recovers_pairs_of_a_dead_runner(staged):
    """분석 러너 하나가 결과 파일을 못 남겨도 마무리는 돌고, DB 에서 쌍을 되찾는다."""
    pairs_dir = staged.dir / "pairs"
    pairs_dir.mkdir()
    (pairs_dir / "pairs-0.json").write_text(json.dumps(
        {"shard": 0, "shards": 2, "base_date": "20260917", "saved": 1, "pairs": ["쌍|넘겨받음"]},
        ensure_ascii=False), encoding="utf-8")
    since = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)

    pipe.cli_finish(SimpleNamespace(pairs_dir=pairs_dir, shards=2, base_date=None,
                                    since=since.isoformat()))

    assert staged.calls["published"] == [["쌍|db에서만", "쌍|넘겨받음"]]
    assert staged.calls["hotness"] == ["20260917"], "날짜를 남은 결과 파일에서 가져와야 한다"
    assert staged.calls["since"][0] < since, "러너와 DB 시계 차이만큼 여유를 둬야 한다"


def test_finish_runs_even_when_every_runner_died(staged):
    pipe.cli_finish(SimpleNamespace(pairs_dir=staged.dir / "없음", shards=4,
                                    base_date="20260917", since=None))
    assert staged.calls["hotness"] == ["20260917"], "화제성은 기사만으로도 산출돼야 한다"


def test_collect_fails_loudly_on_zero_articles(staged, monkeypatch):
    """조용한 0 은 예외보다 나쁘다. 수집 0건이면 잡이 실패로 보여야 한다."""
    monkeypatch.setattr(pipe, "collect_all_sources_for_name", lambda name, deadline=None: [])
    assert pipe.cli_collect(SimpleNamespace(out=staged.dir / "articles.json")) == 1


def test_analyze_respects_its_own_budget(staged, monkeypatch):
    """분석 러너는 수집 시간과 무관하게 자기 예산을 처음부터 잰다."""
    articles_json = staged.dir / "articles.json"
    pipe.cli_collect(SimpleNamespace(out=articles_json))
    seen = []
    monkeypatch.setattr(pipe, "analyze_articles",
                        lambda arts, cfg, deadline, base_date=None: seen.append(deadline) or (0, []))
    monkeypatch.setattr(pipe, "NEWS_TIME_BUDGET_SEC", 600)

    before = time.time()
    pipe.cli_analyze(SimpleNamespace(articles=articles_json, shard=0, shards=1,
                                     out=staged.dir / "pairs-0.json"))

    assert before + 590 <= seen[0] <= time.time() + 600


# --- 모델 -------------------------------------------------------------------

def test_model_failure_is_reported_once_and_articles_still_save(monkeypatch):
    """모델을 못 띄우면 관계만 빠지고 기사는 저장된다. 매 기사 다시 받지 않는다."""
    attempts = []

    class Broken:
        def __init__(self):
            attempts.append(1)
            raise OSError("허깅페이스에서 모델을 받지 못함")

    monkeypatch.setattr(pipe, "AffectiveAnalyzer", Broken)
    monkeypatch.setattr(pipe, "analyzer", None)
    monkeypatch.setattr(pipe, "_analyzer_failed", False)
    monkeypatch.setattr(pipe, "get_article_text", lambda url: "본문. " * 100)
    monkeypatch.setattr(pipe, "extract_politicians", lambda text, pols: ["김민석", "정청래"])
    saved = []
    monkeypatch.setattr(pipe, "save_to_postgresql", lambda arts, cfg: saved.extend(arts))
    monkeypatch.setattr(pipe, "save_observations", lambda art: [])

    for i in range(3):
        art = {"title": f"기사 {i}", "url": f"https://example.com/{i}"}
        assert pipe.process_article(art, None, set(), set()) is not None

    assert len(saved) == 3, "모델이 없어도 기사는 저장돼야 화제성이 나온다"
    assert len(attempts) == 1, f"모델 받기를 {len(attempts)}번 시도했다"
    assert all(not a.get("relationships") for a in saved)


def test_importing_the_pipeline_does_not_load_the_model():
    """SNS 파이프라인은 의원 이름만 쓰려고 이 모듈을 임포트한다."""
    import importlib
    import sys

    fresh = importlib.reload(sys.modules["crawlers.news_crawler_pipeline"])
    assert fresh.analyzer is None
