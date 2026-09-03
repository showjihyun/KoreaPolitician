"""관계 근거 집계 회귀 테스트.

여기가 깨지면 호불호 엣지의 의미가 바뀐다. DB 없이 도는 순수 함수만
검사한다.

    PYTHONPATH=backend pytest backend/tests/test_relation_evidence.py -v
"""

from datetime import datetime, timedelta, timezone

import pytest

from core import relation_evidence as ev
from core.media_outlets import camp_of, cluster_camp

NOW = datetime(2026, 9, 2, tzinfo=timezone.utc)


def _obs(entity_a="김갑동", entity_b="이을순", polarity=-1, score=0.9,
         press="조선일보", url=None, days_ago=0, text=None, title=None,
         focus=1.0, evidence="근거 문장", holder=None, target=None,
         evidence_type=None, hedged=False, stance_weight=1.0):
    """관측 한 건. 기본은 오늘 조선일보가 쓴 갈등 기사.

    제목은 기본적으로 관측마다 다르게 둔다. 제목이 같으면 클러스터링이
    본문과 무관하게 하나로 묶기 때문이다(전재 기사 대응 규칙). 제목이
    같아야 하는 경우는 시험에서 명시적으로 넘긴다.
    """
    day = (NOW - timedelta(days=days_ago)).date()
    body = text or f"{press} 고유 기사 본문 {days_ago} {score} " * 12
    return {
        "entity_a": entity_a,
        "entity_b": entity_b,
        "polarity": polarity,
        "score": score,
        "focus_weight": focus,
        "press": press,
        "url": url or f"https://example.com/{press}/{days_ago}/{score}/{polarity}",
        "title": title or f"{press} {days_ago} {score} {polarity} 기사",
        "article_date": day.isoformat(),
        "simhash": ev.simhash(body),
        "evidence": evidence,
        "holder": holder,
        "target": target,
        "evidence_type": evidence_type,
        "hedged": hedged,
        "stance_weight": stance_weight,
    }


# --- 쌍 키 ------------------------------------------------------------------

def test_pair_key_is_order_independent():
    """엣지 방향은 이름 정렬의 부산물이라 지금은 의미가 없다."""
    assert ev.pair_key("이재명", "한동훈") == ev.pair_key("한동훈", "이재명")
    a, b = ev.split_pair_key(ev.pair_key("한동훈", "이재명"))
    assert (a, b) == ("이재명", "한동훈")


# --- SimHash ----------------------------------------------------------------

def test_simhash_matches_near_duplicates():
    """전재 기사는 꼬리 문구만 다르다. 같은 사건으로 잡혀야 한다."""
    wire = "여야는 2일 국회 본회의에서 예산안 처리를 두고 정면으로 충돌했다. " * 6
    copy_a = wire + " 저작권자 (c) 연합뉴스, 무단 전재-재배포 금지"
    copy_b = wire + " 기자 홍길동 hong@example.com"
    assert ev.hamming(ev.simhash(copy_a), ev.simhash(copy_b)) <= ev.NEAR_DUPLICATE_DISTANCE


def test_simhash_separates_different_articles():
    """서로 다른 취재는 갈라져야 교차 검증이 의미를 갖는다."""
    one = "여야는 예산안 처리를 두고 본회의에서 충돌했다. " * 6
    two = "국정감사 증인 채택을 놓고 상임위가 파행을 빚었다. " * 6
    assert ev.hamming(ev.simhash(one), ev.simhash(two)) > ev.NEAR_DUPLICATE_DISTANCE


def test_simhash_fits_bigint():
    text = "가나다라마바사아자차카타파하 " * 50
    assert 0 <= ev.simhash(text) < (1 << ev.SIMHASH_BITS)


# --- 날짜 -------------------------------------------------------------------

def test_parse_date_handles_collector_formats():
    """섹션 크롤러는 20260902, 검색·해외 소스는 2026-09-02 를 준다."""
    assert ev.parse_date("20260902").isoformat() == "2026-09-02"
    assert ev.parse_date("2026-09-02").isoformat() == "2026-09-02"
    assert ev.parse_date("2026.09.02.").isoformat() == "2026-09-02"
    assert ev.parse_date("2026-09-02 14:33:00").isoformat() == "2026-09-02"
    assert ev.parse_date("어제") is None


# --- 클러스터링 -------------------------------------------------------------

def test_syndicated_copies_count_as_one_event():
    """통신사 전재 20건은 편집 판단 한 번이다."""
    wire = "여야가 예산안을 두고 충돌했다. " * 10
    copies = [
        _obs(press=p, url=f"https://example.com/{p}", text=wire)
        for p in ("연합뉴스", "조선일보", "한겨레", "중앙일보", "경향신문")
    ]
    clusters = ev.assign_clusters(copies, today=NOW.date())
    assert len(clusters) == 1


def test_independent_reports_stay_separate():
    conservative = _obs(press="조선일보",
                        text="야당 대표가 여당을 겨냥해 날을 세웠다. " * 8)
    progressive = _obs(press="한겨레",
                       text="국정감사 증인 채택을 놓고 상임위가 파행을 빚었다. " * 8)
    clusters = ev.assign_clusters([conservative, progressive], today=NOW.date())
    assert len(clusters) == 2


def test_same_title_joins_even_if_body_differs():
    """전재는 제목을 그대로 두고 본문만 잘라 싣는 경우가 흔하다."""
    full = _obs(press="연합뉴스", title="같은 제목", text="본문 전체 " * 40)
    trimmed = _obs(press="세계일보", title="같은 제목", text="완전히 다른 요약 " * 5,
                   url="https://example.com/trimmed")
    clusters = ev.assign_clusters([full, trimmed], today=NOW.date())
    assert len(clusters) == 1


def test_far_apart_dates_are_different_events():
    old = _obs(days_ago=30, text="같은 본문 " * 20)
    new = _obs(days_ago=0, text="같은 본문 " * 20, url="https://example.com/new")
    clusters = ev.assign_clusters([old, new], today=NOW.date())
    assert len(clusters) == 2


# --- 진영 -------------------------------------------------------------------

def test_camp_mapping():
    assert camp_of("조선일보") == "보수"
    assert camp_of("한겨레") == "진보"
    assert camp_of("연합뉴스") == "중도"
    assert camp_of("들어본 적 없는 매체") == "중도"


def test_cluster_spanning_camps_is_treated_as_wire():
    """여러 진영에 같은 원문이 실렸다면 그것은 통신사 한 곳의 판단이다."""
    assert cluster_camp(["조선일보", "한겨레"]) == "중도"
    assert cluster_camp(["조선일보", "중앙일보"]) == "보수"


# --- 집계 -------------------------------------------------------------------

def test_no_observations_yields_nothing():
    assert ev.aggregate([], now=NOW) is None


def test_single_camp_edge_is_marked_low_confidence():
    """한 진영만 쓴 갈등은 사건이 아니라 공격 선택일 수 있다."""
    observations = [_obs(press="조선일보"), _obs(press="중앙일보")]
    edge = ev.aggregate(observations, now=NOW)
    props = edge["properties"]

    assert edge["type"] == ev.NEGATIVE
    assert props["n_clusters"] == 2
    assert props["camp_coverage"] < 2 / 3          # 화면에서 점선
    assert props["camps_agree"]["보수"] == 2
    assert props["camps_agree"]["진보"] == 0
    assert props["confidence"] <= ev.CAMP_RELIABILITY


def test_cross_camp_beats_single_camp_at_equal_volume():
    """같은 기사 수라면 진영이 갈릴수록 신뢰가 높아야 한다."""
    single = [_obs(press="조선일보"), _obs(press="동아일보")]
    crossed = [_obs(press="조선일보"), _obs(press="한겨레")]
    low = ev.aggregate(single, now=NOW)["properties"]
    high = ev.aggregate(crossed, now=NOW)["properties"]

    assert high["confidence"] > low["confidence"]
    assert high["camp_coverage"] > low["camp_coverage"]
    assert high["display_weight"] > low["display_weight"]


#: 서로 다른 취재를 흉내 낸 본문들. 색인만 바꾼 문장은 SimHash 가 같은
#: 사건으로 묶어 버리므로(그게 맞는 동작이다) 실제로 다른 문장을 쓴다.
_DISTINCT_BODIES = [
    "예산결산특별위원회가 증액 심사를 두고 정회를 반복했다. " * 8,
    "법제사법위원회 전체회의에서 인사청문 보고서 채택이 무산됐다. " * 8,
    "국정감사 증인 명단을 두고 여야 간사가 협상 결렬을 선언했다. " * 8,
    "본회의 필리버스터가 자정을 넘겨 이어졌고 표결이 미뤄졌다. " * 8,
    "당대표 회동이 취소되면서 민생법안 처리 일정이 흔들렸다. " * 8,
    "상임위원장 배분 협상이 원점으로 돌아갔다는 발표가 나왔다. " * 8,
    "특검법 재의요구권 행사를 두고 정면 대치가 이어졌다. " * 8,
    "여론조사 공표 금지 기간을 앞두고 공방이 격화됐다. " * 8,
    "지역구 예산 삭감 명단이 공개되며 반발이 확산됐다. " * 8,
    "공직자 재산 신고 누락 의혹이 제기돼 해명 요구가 나왔다. " * 8,
    "국회 윤리특별위원회 제소 방침이 알려지며 파장이 일었다. " * 8,
    "교섭단체 대표연설 순서를 놓고 의사일정 합의가 지연됐다. " * 8,
]


def test_single_camp_confidence_is_capped_by_volume():
    """한 진영이 아무리 많이 써도 교차 검증 없이는 상한을 못 넘는다."""
    many = [
        _obs(press="조선일보", url=f"https://example.com/{i}",
             text=body, title=f"조선일보 {i}번째 기사")
        for i, body in enumerate(_DISTINCT_BODIES)
    ]
    props = ev.aggregate(many, now=NOW)["properties"]
    assert props["n_clusters"] == len(_DISTINCT_BODIES)
    assert props["confidence"] <= ev.CAMP_RELIABILITY


def test_syndication_does_not_fake_cross_camp_coverage():
    """전재 기사로 진영 커버리지가 채워지면 교차 검증이 무의미해진다."""
    wire = "여야가 충돌했다. " * 20
    observations = [
        _obs(press=p, url=f"https://example.com/{p}", text=wire)
        for p in ("연합뉴스", "조선일보", "한겨레", "경향신문", "중앙일보")
    ]
    props = ev.aggregate(observations, now=NOW)["properties"]

    assert props["n_observations"] == 5
    assert props["n_clusters"] == 1                 # 사건 하나
    assert props["camp_coverage"] == pytest.approx(1 / 3, abs=1e-3)


def test_recent_observations_outweigh_old_ones():
    """관계는 변한다. 최근 논조와 누적 이력을 따로 든다."""
    observations = [
        _obs(polarity=-1, score=0.95, days_ago=200, press="조선일보"),
        _obs(polarity=+1, score=0.90, days_ago=0, press="조선일보"),
    ]
    props = ev.aggregate(observations, now=NOW)["properties"]

    assert props["score_recent"] > 0                # 최근은 우호
    assert props["score_recent"] > props["score_cumulative"]
    assert props["first_seen"] < props["last_seen"]


def test_polarity_follows_the_weight_of_evidence():
    observations = [
        _obs(polarity=-1, score=0.9, press="조선일보"),
        _obs(polarity=-1, score=0.9, press="한겨레"),
        _obs(polarity=+1, score=0.7, press="연합뉴스"),
    ]
    edge = ev.aggregate(observations, now=NOW)
    assert edge["type"] == ev.NEGATIVE
    # 진영 안에서 이견이 있으면 신뢰가 깎인다.
    assert edge["properties"]["camps_agree"]["중도"] == 0


def test_roundup_articles_weigh_less():
    """10명을 나열한 기사에서 뽑은 쌍은 그 기사의 주제가 아니다."""
    focused = [_obs(focus=1.0, press="조선일보")]
    roundup = [_obs(focus=0.32, press="조선일보")]
    # 점수 자체는 같지만 누적 무게가 달라 이후 관측과 섞일 때 차이가 난다.
    mixed_focused = ev.aggregate(
        focused + [_obs(polarity=+1, score=0.8, press="한겨레")],
        now=NOW)["properties"]
    mixed_roundup = ev.aggregate(
        roundup + [_obs(polarity=+1, score=0.8, press="한겨레")],
        now=NOW)["properties"]
    assert mixed_roundup["score_recent"] > mixed_focused["score_recent"]


# --- 방향과 근거 무게 -------------------------------------------------------

def test_one_sided_criticism_gets_a_direction():
    """한쪽만 공격한 기사가 쌓이면 화살표를 그릴 수 있어야 한다."""
    observations = [
        _obs(press="조선일보", holder="김갑동", target="이을순"),
        _obs(press="한겨레", holder="김갑동", target="이을순"),
    ]
    props = ev.aggregate(observations, now=NOW)["properties"]
    assert props["direction"] == "a_to_b"
    assert props["holder"] == "김갑동" and props["target"] == "이을순"
    assert props["direction_support"]["backward"] == 0


def test_mutual_exchange_stays_undirected():
    """서로 주고받은 관계에 화살표를 그리면 없는 방향을 만들어 낸다."""
    observations = [
        _obs(press="조선일보", holder="김갑동", target="이을순"),
        _obs(press="한겨레", holder="이을순", target="김갑동"),
    ]
    props = ev.aggregate(observations, now=NOW)["properties"]
    assert props["direction"] == "mutual"
    assert props["holder"] is None and props["target"] is None


def test_direction_needs_a_clear_margin():
    """한 건 대 두 건 정도로는 방향을 주장하지 않는다."""
    observations = [
        _obs(press="조선일보", holder="김갑동", target="이을순"),
        _obs(press="중앙일보", holder="김갑동", target="이을순"),
        _obs(press="한겨레", holder="이을순", target="김갑동"),
    ]
    props = ev.aggregate(observations, now=NOW)["properties"]
    assert props["direction"] == "mutual"


def test_observations_without_holder_are_undirected():
    """집계 계층 이전에 쌓인 관측에는 발화 주체가 없다."""
    props = ev.aggregate([_obs(press="조선일보"), _obs(press="한겨레")],
                         now=NOW)["properties"]
    assert props["direction"] == "mutual"


def test_reporter_narration_weighs_less_than_a_quote():
    """기자가 붙인 대립 구도와 정치인의 발언은 다른 정보다."""
    quoted = _obs(press="조선일보", polarity=-1, score=0.9, stance_weight=1.0)
    narrated = _obs(press="조선일보", polarity=-1, score=0.9, stance_weight=0.3)
    opposite = _obs(press="한겨레", polarity=+1, score=0.9)

    from_quote = ev.aggregate([quoted, opposite], now=NOW)["properties"]
    from_narration = ev.aggregate([narrated, opposite], now=NOW)["properties"]

    # 반대 논조가 같은 무게일 때, 인용 근거가 있는 쪽이 더 갈등으로 기운다.
    assert from_quote["score_recent"] < from_narration["score_recent"]


def test_evidence_types_are_reported():
    observations = [
        _obs(press="조선일보", evidence_type="direct_quote"),
        _obs(press="한겨레", evidence_type="reporter_narration"),
    ]
    props = ev.aggregate(observations, now=NOW)["properties"]
    assert props["evidence_types"] == {"direct_quote": 1, "reporter_narration": 1}


def test_properties_carry_audit_fields():
    """감사에 필요한 값이 엣지에 실려야 한다. reddit 이 요구한 부분이다."""
    observations = [_obs(press="조선일보"), _obs(press="한겨레")]
    props = ev.aggregate(observations, now=NOW)["properties"]
    for field in ("score", "score_recent", "score_cumulative", "confidence",
                  "camp_coverage", "camps", "camps_agree", "n_observations",
                  "n_clusters", "n_press", "presses", "first_seen", "last_seen",
                  "peak_score", "evidence", "url", "half_life_days",
                  "display_weight", "social_impact_score", "provenance"):
        assert field in props, field
    assert props["provenance"] == "aggregate"
    assert 0.0 <= props["score"] <= 1.0
    assert set(props["presses"]) == {"조선일보", "한겨레"}
