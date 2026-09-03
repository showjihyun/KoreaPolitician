"""관계 근거(observation) 적재와 집계.

왜 있는가
---------
예전에는 기사 하나가 관계 하나를 통째로 결정했다. graph_storage.add_edge 가
(source, target, type) 키로 properties 를 dict.update 하기 때문에, 같은 쌍을
다룬 500번째 기사가 앞의 499건을 조용히 덮어썼다. 그래서 엣지에는 항상
"마지막에 처리된 기사 한 건"만 남았고, 기사 수도 언론사 분포도 시간 흐름도
남지 않았다. 집계에 기반한 어떤 편향 보정도 계산 자체가 불가능했다.

이 모듈은 그 앞단을 바꾼다. 기사에서 나온 판정을 지우지 않고 전부
edge_observations 에 쌓고, 엣지는 그 관측들을 집계한 결과로만 쓴다.

무엇을 보정하는가
-----------------
1. 사건 단위 중복 제거. 통신사 전재 기사는 여러 URL 로 들어오지만 편집
   판단은 한 번이다. 본문 SimHash 로 묶어 클러스터 하나를 관측 한 건으로
   센다. 근거: 연합뉴스가 포털 송고량의 70% 이상을 차지한다는 점, 그리고
   docs/MEDIA_BIAS_RESEARCH.md 의 알고리즘 5(a).

2. 진영 교차 검증. 갈등 보도가 한 진영에서만 나왔다면 그것은 사건이 아니라
   공격 선택일 수 있다. 진영이 다른 매체가 같은 극성을 독립적으로 보도했을
   때만 신뢰도를 올린다. 근거: Mullainathan & Shleifer(2005), Gentzkow &
   Shapiro(2006), Budak·Goel·Rao(2016), 박영흠(2024). 알고리즘 2.

3. 시간 감쇠. 관계와 편향은 시기에 따라 변한다(Kim·Lelkes·McCrain 2022,
   이신행 2024). 최근 논조와 누적 이력을 따로 보관해, 화면이 둘을 섞어
   보여 주지 않게 한다. 알고리즘 5(c).

무엇을 아직 보정하지 않는가
---------------------------
언론사x정당 논조 기준선(알고리즘 1)과 부정성 선택 편향 역가중(알고리즘 3),
어그로 할인(알고리즘 5(b))은 2단계다. 언론사별 표본이 셀당 수십 건은 쌓여야
기준선이 노이즈가 아니게 되고, 지금은 수집 시작 직후라 표본이 없다.
"""

import hashlib
import logging
import os
import re
from collections import Counter
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core.db_config import get_sync_pool
from core.media_outlets import CAMPS, camp_of, cluster_camp

logger = logging.getLogger(__name__)


# --- 조율 상수 -------------------------------------------------------------
# 값을 바꾸면 관계 판정이 통째로 바뀐다. 환경변수로 열어 두되 기본값의
# 근거를 함께 적는다.

def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("환경변수 %s 가 실수가 아닙니다: %r. 기본값 %s 사용", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    return int(_env_float(name, float(default)))


#: 최근 논조의 반감기(일). 45일이면 지난 분기의 충돌은 절반 무게가 된다.
#: 저장소의 설계 메모(.refs)는 EWMA alpha 0.1~0.3 을 제안했는데, 일 단위로
#: 환산하면 반감기 2~7일이라 정치 관계에는 지나치게 빠르다. 국회 회기가
#: 분기 단위로 돌아가는 점을 감안해 분기의 절반으로 잡았다.
HALF_LIFE_DAYS = _env_float("RELATION_HALF_LIFE_DAYS", 45.0)

#: 같은 사건으로 볼 SimHash 해밍 거리 상한(63비트 기준).
#:
#: 실측(backend/tests/test_relation_evidence.py 와 같은 본문 기준):
#:   같은 원문에 매체별 저작권/기자 문구만 붙은 경우      거리 5
#:   같은 원문을 절반으로 자른 경우                       거리 4
#:   같은 날 같은 주제지만 다른 취재                      거리 26
#: 두 무리가 크게 벌어져 있어 6은 안전한 경계다. 넉넉히 잡으면 독립 보도를
#: 하나로 뭉쳐 교차 검증 신호가 사라지므로 그 아래로 눌러 둔다.
NEAR_DUPLICATE_DISTANCE = _env_int("RELATION_SIMHASH_DISTANCE", 6)

#: 같은 사건으로 볼 날짜 창(일). 전재는 당일~익일에 몰린다.
CLUSTER_WINDOW_DAYS = _env_int("RELATION_CLUSTER_WINDOW_DAYS", 1)

#: 진영 하나가 도달할 수 있는 신뢰 상한. 한 진영이 아무리 많이 써도
#: 0.7 을 넘지 못하게 해서, 교차 검증 없이는 확신하지 않는다.
CAMP_RELIABILITY = _env_float("RELATION_CAMP_RELIABILITY", 0.7)

#: 엣지로 승격하는 데 필요한 최소 사건 수. 지금은 수집 시작 직후라 1이다.
#: 관측이 쌓이면 2로 올린다(알고리즘 3의 "관측 2건 이상").
MIN_CLUSTERS = _env_int("RELATION_MIN_CLUSTERS", 1)

#: SimHash 비트 수. Postgres BIGINT 가 부호 있는 64비트라 63비트만 쓴다.
#: 1비트를 버려도 근접 중복 판정에는 영향이 없다.
SIMHASH_BITS = 63

POSITIVE = "POSITIVE_SENTIMENT"
NEGATIVE = "NEGATIVE_SENTIMENT"

#: 관측 로그. 크롤러(동기 풀)와 API(비동기 풀) 양쪽이 같은 DDL 을 쓴다.
OBSERVATION_SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS public.edge_observations (
        id BIGSERIAL PRIMARY KEY,
        pair_key TEXT NOT NULL,
        entity_a TEXT NOT NULL,
        entity_b TEXT NOT NULL,
        polarity SMALLINT NOT NULL,
        score DOUBLE PRECISION NOT NULL,
        focus_weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
        press TEXT,
        camp TEXT,
        url TEXT NOT NULL,
        title TEXT,
        article_date TEXT,
        simhash BIGINT,
        evidence TEXT,
        source TEXT NOT NULL DEFAULT 'news',
        observed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    -- 같은 기사가 같은 쌍을 두 번 넣지 못하게 한다. 재수집해도 표본이
    -- 부풀지 않아야 신뢰도 계산이 의미를 갖는다.
    CREATE UNIQUE INDEX IF NOT EXISTS uq_edge_observations_pair_url
        ON public.edge_observations (pair_key, url);
    CREATE INDEX IF NOT EXISTS idx_edge_observations_pair
        ON public.edge_observations (pair_key);
    CREATE INDEX IF NOT EXISTS idx_edge_observations_observed
        ON public.edge_observations (observed_at DESC);

    -- 발화 주체 귀속(알고리즘 4)에서 늘어난 열. 기존 DB 도 따라오도록
    -- ALTER 로 둔다.
    ALTER TABLE public.edge_observations
        ADD COLUMN IF NOT EXISTS holder TEXT,
        ADD COLUMN IF NOT EXISTS target TEXT,
        ADD COLUMN IF NOT EXISTS evidence_type TEXT,
        ADD COLUMN IF NOT EXISTS hedged BOOLEAN NOT NULL DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS stance_weight DOUBLE PRECISION NOT NULL DEFAULT 1.0;
"""


def ensure_schema() -> None:
    """관측 로그 스키마를 준비한다. 크롤러 시작 시 한 번 부른다."""
    with get_sync_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(OBSERVATION_SCHEMA_SQL)


# --- 쌍 식별 ---------------------------------------------------------------

def pair_key(name_a: str, name_b: str) -> str:
    """두 이름을 순서와 무관한 하나의 키로 만든다.

    엣지 방향은 지금 의미가 없다. name_matcher.find_names 가 sorted() 로
    돌려주고 파이프라인이 i<j 로 짝을 만들기 때문에, entity_a 는 늘
    가나다순으로 앞선 이름일 뿐 발화 주체가 아니다. 발화 주체 귀속은
    2단계(알고리즘 4)에서 들어온다. 그때까지는 무방향으로 다룬다.
    """
    a, b = sorted([name_a.strip(), name_b.strip()])
    return f"{a}|{b}"


def split_pair_key(key: str) -> Tuple[str, str]:
    a, _, b = key.partition("|")
    return a, b


# --- SimHash ---------------------------------------------------------------

_WS = re.compile(r"\s+")


def _shingles(text: str, size: int = 4) -> List[str]:
    """한국어 본문용 문자 4-그램.

    어절 단위 shingle 은 조사가 붙고 띄어쓰기가 흔들리는 한국어에서
    전재 기사끼리도 크게 달라진다. 문자 n-그램이 안정적이다.
    """
    normalized = _WS.sub(" ", text or "").strip()
    if len(normalized) < size:
        return [normalized] if normalized else []
    return [normalized[i:i + size] for i in range(len(normalized) - size + 1)]


def simhash(text: str, limit: int = 1500) -> int:
    """본문 앞부분의 SimHash(63비트).

    앞부분만 보는 이유는 전재 기사가 뒤에 매체별 저작권 문구나 기자
    소개를 덧붙이기 때문이다. 도입부가 같으면 같은 원문으로 본다.
    """
    grams = _shingles((text or "")[:limit])
    if not grams:
        return 0
    vector = [0] * SIMHASH_BITS
    for gram in grams:
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for bit in range(SIMHASH_BITS):
            if value >> bit & 1:
                vector[bit] += 1
            else:
                vector[bit] -= 1
    out = 0
    for bit in range(SIMHASH_BITS):
        if vector[bit] > 0:
            out |= 1 << bit
    return out


def hamming(a: int, b: int) -> int:
    return bin((a or 0) ^ (b or 0)).count("1")


# --- 날짜 ------------------------------------------------------------------

_DATE_PATTERNS = ("%Y%m%d", "%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d")


def parse_date(value: Any) -> Optional[date]:
    """수집원마다 다른 날짜 표기를 date 로 맞춘다.

    섹션 크롤러는 "20260902", 검색 크롤러와 해외 소스는 "2026-09-02" 를
    돌려준다. 못 읽는 값은 None 으로 두고 관측 시각으로 대체한다.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    head = text.split(" ")[0].split("T")[0].rstrip(".")
    for pattern in _DATE_PATTERNS:
        try:
            return datetime.strptime(head, pattern).date()
        except ValueError:
            continue
    return None


def _observation_date(obs: Dict[str, Any], fallback: date) -> date:
    parsed = parse_date(obs.get("article_date"))
    if parsed:
        return parsed
    observed = obs.get("observed_at")
    if isinstance(observed, datetime):
        return observed.date()
    parsed = parse_date(observed)
    return parsed or fallback


# --- 클러스터링 ------------------------------------------------------------

def _normalized_title(obs: Dict[str, Any]) -> str:
    return _WS.sub(" ", str(obs.get("title") or "")).strip().lower()


def assign_clusters(observations: Sequence[Dict[str, Any]],
                    today: Optional[date] = None) -> List[List[Dict[str, Any]]]:
    """같은 사건을 다룬 관측을 묶는다.

    쌍 단위로만 묶으므로 비교 대상이 적다. 전체 기사에 대한 전역
    클러스터링은 필요 없다. 같은 사건을 다루면서 같은 두 사람을 함께
    언급한 기사끼리만 뭉치면 되기 때문이다.

    묶는 조건은 (a) 날짜가 CLUSTER_WINDOW_DAYS 안이고, (b) 본문 SimHash 가
    가깝거나 정규화한 제목이 같을 때다. 제목 조건을 함께 두는 이유는
    전재 기사가 제목은 그대로 두고 본문만 잘라 싣는 경우가 흔해서다.
    """
    fallback = today or datetime.now(timezone.utc).date()
    ordered = sorted(
        observations,
        key=lambda o: (_observation_date(o, fallback), str(o.get("url") or "")),
    )
    clusters: List[List[Dict[str, Any]]] = []
    meta: List[Tuple[date, int, str]] = []  # (대표 날짜, 대표 simhash, 대표 제목)

    for obs in ordered:
        obs_date = _observation_date(obs, fallback)
        obs_hash = int(obs.get("simhash") or 0)
        obs_title = _normalized_title(obs)

        joined = False
        for index, (c_date, c_hash, c_title) in enumerate(meta):
            if abs((obs_date - c_date).days) > CLUSTER_WINDOW_DAYS:
                continue
            same_text = (
                obs_hash and c_hash
                and hamming(obs_hash, c_hash) <= NEAR_DUPLICATE_DISTANCE
            )
            same_title = bool(obs_title) and obs_title == c_title
            if same_text or same_title:
                clusters[index].append(obs)
                joined = True
                break
        if not joined:
            clusters.append([obs])
            meta.append((obs_date, obs_hash, obs_title))

    return clusters


# --- 집계 ------------------------------------------------------------------

def observation_weight(obs: Dict[str, Any]) -> float:
    """관측 하나의 무게.

    두 가지를 곱한다.

    focus_weight  기사가 여러 의원을 나열할수록 개인당 신호가 약하다(1/sqrt).
    stance_weight 정치인의 직접 발언(1.0)이 간접 인용(0.7)보다, 그것이 다시
                  기자 서술(0.3)보다 무겁다. 추측성 서술은 절반으로 깎인다.
                  유재광·오경수(2012)가 보인 "신문이 발언을 자사 프레임에
                  맞춰 고른다" 는 문제를 근거 종류로 분리해 다루기 위함이다.
    """
    return float(obs.get("focus_weight", 1.0)) * float(obs.get("stance_weight", 1.0))


def _cluster_summary(members: Sequence[Dict[str, Any]],
                     fallback: date) -> Dict[str, Any]:
    """클러스터 하나를 관측 한 건으로 압축한다."""
    weight_pos = sum(
        float(m.get("score", 0.0)) * observation_weight(m)
        for m in members if int(m.get("polarity", 0)) > 0
    )
    weight_neg = sum(
        float(m.get("score", 0.0)) * observation_weight(m)
        for m in members if int(m.get("polarity", 0)) < 0
    )
    polarity = 1 if weight_pos >= weight_neg else -1
    agreeing = [m for m in members if int(m.get("polarity", 0)) == polarity]
    total_weight = sum(observation_weight(m) for m in agreeing) or 1.0
    score = sum(
        float(m.get("score", 0.0)) * observation_weight(m)
        for m in agreeing
    ) / total_weight

    presses = [m.get("press") for m in members if m.get("press")]
    best = max(agreeing or members, key=lambda m: float(m.get("score", 0.0)))

    # 방향. holder 가 비어 있는 관측(상호이거나 집계 이전 데이터)은 어느
    # 쪽에도 세지 않는다.
    entity_a = str(members[0].get("entity_a") or "")
    forward = sum(float(m.get("score", 0.0)) * observation_weight(m)
                  for m in agreeing if m.get("holder") == entity_a)
    backward = sum(float(m.get("score", 0.0)) * observation_weight(m)
                   for m in agreeing if m.get("target") == entity_a and m.get("holder"))

    return {
        "polarity": polarity,
        "score": score,
        "weight": total_weight / max(1, len(agreeing)),
        "camp": cluster_camp(presses),
        "camps": sorted({camp_of(p) for p in presses}) if presses else [],
        "presses": sorted(set(presses)),
        "date": min(_observation_date(m, fallback) for m in members),
        "size": len(members),
        "best": best,
        "forward": forward,
        "backward": backward,
        "evidence_types": sorted({m.get("evidence_type") for m in agreeing
                                  if m.get("evidence_type")}),
    }


def _direction(forward: float, backward: float) -> str:
    """어느 쪽이 말하는 쪽인지 정한다.

    한쪽이 다른 쪽의 두 배 이상일 때만 방향을 인정한다. 서로 주고받은
    기사에서는 양쪽 모두 높게 나오는데, 그때 한쪽을 고르면 없는 방향을
    만들어 내는 셈이다. 예전 엣지의 화살표가 정확히 그런 상태였다.
    """
    if forward <= 0 and backward <= 0:
        return "mutual"
    if backward <= 0:
        return "a_to_b"
    if forward <= 0:
        return "b_to_a"
    # 딱 두 배는 방향으로 치지 않는다. 2대 1은 상호 공방에서 흔한 모양이다.
    if forward > 2 * backward:
        return "a_to_b"
    if backward > 2 * forward:
        return "b_to_a"
    return "mutual"


def _confidence(camp_total: Dict[str, int], camp_agree: Dict[str, int]) -> float:
    """진영 교차 검증 신뢰도.

    진영 하나를 잡음 섞인 관측자로 본다. 한 진영 안에서 사건이 늘어날수록
    신뢰가 오르되 CAMP_RELIABILITY 를 넘지 못하고, 진영 안에서 극성이
    갈리면 그만큼 깎인다. 그다음 진영들을 독립으로 보고 noisy-OR 로 합친다.

        보수만 1건       -> 0.35
        보수만 3건       -> 0.61
        보수 1 + 진보 1  -> 0.58
        보수 3 + 진보 3  -> 0.85

    한 진영이 아무리 많이 써도 0.7 을 못 넘고, 두 진영이 각자 쓰면 그
    위로 올라간다. Mullainathan & Shleifer(2005)의 교차 확인 논지를
    그대로 옮긴 모양이다.
    """
    product = 1.0
    for camp in CAMPS:
        agree = camp_agree.get(camp, 0)
        total = camp_total.get(camp, 0)
        if agree <= 0 or total <= 0:
            continue
        volume = 1.0 - 0.5 ** agree
        consensus = agree / total
        product *= 1.0 - (CAMP_RELIABILITY * volume * consensus)
    return round(1.0 - product, 4)


def aggregate(observations: Sequence[Dict[str, Any]],
              now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """관측 목록에서 엣지 하나를 만든다. 순수 함수라 테스트가 쉽다.

    돌려주는 dict 는 (type, properties) 두 키를 갖는다. 승격 조건을 못
    채우면 None 이다.
    """
    if not observations:
        return None

    now = now or datetime.now(timezone.utc)
    today = now.date()
    clusters = assign_clusters(observations, today=today)
    summaries = [_cluster_summary(members, today) for members in clusters]
    if len(summaries) < MIN_CLUSTERS:
        return None

    # 시간 가중. 반감기 지수 감쇠는 일 단위 EWMA 와 같은 형태이면서
    # 배치 재계산에 강하다(관측이 없는 날을 건너뛰어도 결과가 같다).
    def time_weight(summary: Dict[str, Any]) -> float:
        age = max(0, (today - summary["date"]).days)
        return 0.5 ** (age / HALF_LIFE_DAYS) if HALF_LIFE_DAYS > 0 else 1.0

    weighted_recent = 0.0
    weight_recent = 0.0
    weighted_total = 0.0
    weight_total = 0.0
    for summary in summaries:
        base = summary["weight"]
        signed = summary["polarity"] * summary["score"]
        tw = time_weight(summary)
        weighted_recent += signed * base * tw
        weight_recent += base * tw
        weighted_total += signed * base
        weight_total += base

    score_recent = weighted_recent / weight_recent if weight_recent else 0.0
    score_cumulative = weighted_total / weight_total if weight_total else 0.0
    polarity = 1 if score_recent >= 0 else -1
    if score_recent == 0:
        polarity = 1 if score_cumulative >= 0 else -1

    camp_total: Dict[str, int] = {camp: 0 for camp in CAMPS}
    camp_agree: Dict[str, int] = {camp: 0 for camp in CAMPS}
    for summary in summaries:
        camp = summary["camp"]
        camp_total[camp] = camp_total.get(camp, 0) + 1
        if summary["polarity"] == polarity:
            camp_agree[camp] = camp_agree.get(camp, 0) + 1

    covered = sum(1 for camp in CAMPS if camp_agree.get(camp, 0) > 0)
    camp_coverage = covered / len(CAMPS)
    confidence = _confidence(camp_total, camp_agree)

    agreeing = [s for s in summaries if s["polarity"] == polarity]
    best = max(agreeing or summaries, key=lambda s: s["score"])["best"]
    presses = sorted({p for s in summaries for p in s["presses"]})
    dates = [s["date"] for s in summaries]

    forward = sum(s["forward"] for s in agreeing)
    backward = sum(s["backward"] for s in agreeing)
    direction = _direction(forward, backward)
    entity_a = str(observations[0].get("entity_a") or "")
    entity_b = str(observations[0].get("entity_b") or "")
    holder = entity_a if direction == "a_to_b" else entity_b if direction == "b_to_a" else None
    target = entity_b if direction == "a_to_b" else entity_a if direction == "b_to_a" else None
    evidence_types = Counter(
        obs.get("evidence_type") for obs in observations if obs.get("evidence_type")
    )

    magnitude = abs(score_recent)
    properties = {
        # 기존 소비자(get_intelligence 의 갈등 정렬, 프론트)가 그대로 쓰도록
        # score 는 0~1 크기 그대로 둔다. 부호는 type 이 들고 있다.
        "score": round(magnitude, 4),
        "score_recent": round(score_recent, 4),
        "score_cumulative": round(score_cumulative, 4),
        "polarity": polarity,
        # 표시 굵기. 진영 교차가 안 된 관계는 절반 무게로 그린다.
        "display_weight": round(magnitude * (0.5 + 0.5 * camp_coverage), 4),
        # 영향력 순위(get_intelligence)가 읽는 값. 예전에는 DCP 계산기가
        # 채웠지만 운영 환경에서는 API 주소를 localhost 로 잡고 있어 늘
        # 실패해 base_intensity 를 그대로 돌려줬다. 즉 값이 score 와 같았다.
        # 이제는 진영 교차 검증을 반영한 무게를 쓴다. DCP 의 "같은 정당이면
        # 동맹" 가정은 정파 구조를 보정하는 게 아니라 증폭하므로, 공동발의
        # 기반으로 바꾸는 2단계(알고리즘 3) 전까지는 쓰지 않는다.
        "social_impact_score": round(magnitude * (0.5 + 0.5 * camp_coverage), 4),
        "confidence": confidence,
        "camp_coverage": round(camp_coverage, 4),
        "camps": camp_total,
        "camps_agree": camp_agree,
        "n_observations": len(observations),
        "n_clusters": len(summaries),
        "n_press": len(presses),
        "presses": presses[:12],
        "first_seen": min(dates).isoformat(),
        "last_seen": max(dates).isoformat(),
        "peak_score": round(max(s["score"] for s in summaries), 4),
        "evidence": str(best.get("evidence") or "")[:200],
        "evidence_type": best.get("evidence_type"),
        "evidence_types": dict(evidence_types),
        "url": best.get("url"),
        "press": best.get("press"),
        "date": best.get("article_date"),
        # 방향. mutual 이면 화면에 화살표를 그리지 않는다. a_to_b 는 엣지의
        # source 가 말하는 쪽이라는 뜻이다(source 는 가나다순으로 앞선 이름).
        "direction": direction,
        "holder": holder,
        "target": target,
        "direction_support": {"forward": round(forward, 4),
                              "backward": round(backward, 4)},
        "half_life_days": HALF_LIFE_DAYS,
        "provenance": "aggregate",
    }
    return {"type": POSITIVE if polarity > 0 else NEGATIVE, "properties": properties}


# --- 적재 / 조회 -----------------------------------------------------------

def _to_signed_bigint(value: int) -> int:
    """63비트 SimHash 는 BIGINT 범위 안이라 그대로 넣어도 된다."""
    return int(value) & ((1 << SIMHASH_BITS) - 1)


def record_observations(rows: Iterable[Dict[str, Any]]) -> int:
    """관측을 적재한다. 같은 (쌍, 기사)는 최신 판정으로 덮는다.

    덮어쓰기가 여기서는 안전하다. 같은 기사를 다시 분석한 결과일 뿐,
    다른 기사의 근거를 지우지 않기 때문이다.
    """
    payload = []
    for row in rows:
        key = pair_key(row["entity_a"], row["entity_b"])
        entity_a, entity_b = split_pair_key(key)
        payload.append((
            key, entity_a, entity_b,
            int(row["polarity"]), float(row["score"]),
            float(row.get("focus_weight", 1.0)),
            row.get("press") or None,
            camp_of(row.get("press")),
            row["url"],
            (row.get("title") or "")[:500] or None,
            row.get("article_date") or None,
            _to_signed_bigint(row.get("simhash") or 0),
            (row.get("evidence") or "")[:500] or None,
            row.get("source") or "news",
            row.get("holder") or None,
            row.get("target") or None,
            row.get("evidence_type") or None,
            bool(row.get("hedged", False)),
            float(row.get("stance_weight", 1.0)),
        ))
    if not payload:
        return 0

    with get_sync_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO public.edge_observations
                    (pair_key, entity_a, entity_b, polarity, score, focus_weight,
                     press, camp, url, title, article_date, simhash, evidence, source,
                     holder, target, evidence_type, hedged, stance_weight)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s)
                ON CONFLICT (pair_key, url) DO UPDATE SET
                    polarity = EXCLUDED.polarity,
                    score = EXCLUDED.score,
                    focus_weight = EXCLUDED.focus_weight,
                    press = EXCLUDED.press,
                    camp = EXCLUDED.camp,
                    title = EXCLUDED.title,
                    article_date = EXCLUDED.article_date,
                    simhash = EXCLUDED.simhash,
                    evidence = EXCLUDED.evidence,
                    holder = EXCLUDED.holder,
                    target = EXCLUDED.target,
                    evidence_type = EXCLUDED.evidence_type,
                    hedged = EXCLUDED.hedged,
                    stance_weight = EXCLUDED.stance_weight
                """,
                payload,
            )
    return len(payload)


#: 관측 조회 컬럼. 감사 엔드포인트(비동기 풀)도 같은 순서를 쓴다.
OBSERVATION_COLUMNS = """
    pair_key, entity_a, entity_b, polarity, score, focus_weight,
    press, url, title, article_date, simhash, evidence, observed_at, id,
    holder, target, evidence_type, hedged, stance_weight
"""

_SELECT_COLUMNS = OBSERVATION_COLUMNS


def row_to_observation(row: Sequence[Any]) -> Dict[str, Any]:
    """OBSERVATION_COLUMNS 순서의 행 하나를 dict 로."""
    return {
        "pair_key": row[0],
        "entity_a": row[1],
        "entity_b": row[2],
        "polarity": int(row[3]),
        "score": float(row[4]),
        "focus_weight": float(row[5]),
        "press": row[6],
        "url": row[7],
        "title": row[8],
        "article_date": row[9],
        "simhash": int(row[10] or 0),
        "evidence": row[11],
        "observed_at": row[12],
        "id": row[13] if len(row) > 13 else None,
        "holder": row[14] if len(row) > 14 else None,
        "target": row[15] if len(row) > 15 else None,
        "evidence_type": row[16] if len(row) > 16 else None,
        "hedged": bool(row[17]) if len(row) > 17 else False,
        "stance_weight": float(row[18]) if len(row) > 18 and row[18] is not None else 1.0,
    }


_row_to_observation = row_to_observation


def annotate_clusters(observations: Sequence[Dict[str, Any]],
                      now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """관측마다 몇 번 사건으로 묶였는지 표시해서 돌려준다.

    감사에 필요하다. 전재 기사 20건이 사건 하나로 접힌 것을 밖에서 볼 수
    없으면, 신뢰도가 왜 그 값인지 설명할 방법이 없다.
    """
    now = now or datetime.now(timezone.utc)
    clusters = assign_clusters(observations, today=now.date())
    by_url: Dict[str, int] = {}
    for index, members in enumerate(clusters):
        for member in members:
            by_url[str(member.get("url"))] = index

    annotated = []
    for obs in observations:
        row = dict(obs)
        row["cluster"] = by_url.get(str(obs.get("url")))
        row["camp"] = camp_of(obs.get("press"))
        annotated.append(row)
    return annotated


def load_observations(pair_keys: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
    """여러 쌍의 관측을 한 번에 읽는다."""
    if not pair_keys:
        return {}
    grouped: Dict[str, List[Dict[str, Any]]] = {key: [] for key in pair_keys}
    with get_sync_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_SELECT_COLUMNS} FROM public.edge_observations "
                "WHERE pair_key = ANY(%s)",
                (list(pair_keys),),
            )
            for row in cur.fetchall():
                grouped[row[0]].append(_row_to_observation(row))
    return grouped


def all_pair_keys() -> List[str]:
    with get_sync_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT pair_key FROM public.edge_observations")
            return [r[0] for r in cur.fetchall()]


def aggregate_pairs(pair_keys: Sequence[str],
                    now: Optional[datetime] = None) -> Dict[str, Dict[str, Any]]:
    """쌍마다 집계된 엣지를 만든다. 승격 못 한 쌍은 결과에서 빠진다."""
    grouped = load_observations(pair_keys)
    result: Dict[str, Dict[str, Any]] = {}
    for key, observations in grouped.items():
        edge = aggregate(observations, now=now)
        if edge:
            result[key] = edge
    return result


def publish_edges(pair_keys: Sequence[str]) -> Tuple[int, int]:
    """쌍별 집계를 API 로 밀어 넣는다. (저장 성공 수, 승격된 쌍 수).

    크롤러와 소급 이관 스크립트가 같이 쓴다. 여기 두는 이유는 소급 이관이
    NLI 모델을 띄우지 않고도 반영할 수 있어야 하기 때문이다. 크롤러 모듈을
    임포트하면 torch 와 transformers 가 따라 올라온다.

    DB 에 직접 쓰지 않고 API 를 거치는 이유는, API 프로세스가 그래프를
    메모리에 들고 있어서 뒤에서 DB 만 고치면 재기동 전까지 갈라지기 때문이다.
    """
    import requests                                   # noqa: PLC0415
    from core.db_config import api_base_url, env      # noqa: PLC0415

    keys = sorted({k for k in pair_keys if k})
    if not keys:
        return 0, 0

    try:
        edges = aggregate_pairs(keys)
    except Exception as e:                             # noqa: BLE001
        logger.error(f"[관계 집계 실패] {e}")
        return 0, 0

    api_url = api_base_url() + "/api/edge"
    headers = {}
    write_token = env("API_WRITE_TOKEN")
    if write_token:
        headers["X-API-Key"] = write_token

    saved = 0
    for key, edge in edges.items():
        entity_a, entity_b = split_pair_key(key)
        payload = {
            "source": entity_a,
            "target": entity_b,
            "type": edge["type"],
            "properties": edge["properties"],
        }
        try:
            # 타임아웃이 없으면 슬립 중인 무료 인스턴스를 깨우는 동안
            # 무한 대기할 수 있다.
            response = requests.post(api_url, json=payload,
                                     headers=headers, timeout=60)
            if response.status_code == 200:
                saved += 1
            else:
                logger.warning(
                    f"[엣지 저장 거부] {key} {response.status_code} {response.text[:120]}")
        except Exception as e:                         # noqa: BLE001
            logger.error(f"Error saving to TuringDB: {e}")

    skipped = len(keys) - len(edges)
    if skipped:
        logger.info(f"[관계 집계] 근거가 기준에 못 미쳐 보류한 쌍 {skipped}개")
    return saved, len(edges)
