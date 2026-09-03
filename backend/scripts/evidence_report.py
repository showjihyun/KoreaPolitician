"""근거 로그 분포 리포트.

무엇에 쓰나
-----------
1단계 보정을 넣은 뒤 조율값을 정하려면 실제 분포를 봐야 한다. 이 스크립트는
그 판단에 필요한 숫자만 뽑는다.

  - 사건 수 분포: RELATION_MIN_CLUSTERS 를 2로 올리면 관계가 몇 개 남는가.
    지금은 1이라 기사 한 건짜리 관계도 엣지가 된다. 표본이 쌓이면 올려야
    하는데, 얼마나 잃는지 모르고 올릴 수는 없다.
  - 진영 커버리지 분포: 교차 검증을 통과하는 관계가 실제로 얼마나 되나.
    거의 없다면 수집원이 한 포털에 몰려 있다는 뜻이고, 매체를 넓혀야 한다.
  - 표에 없는 언론사: core/media_outlets.py 에 채워야 할 목록. 미등재 매체는
    전부 중도로 떨어져 교차 검증을 약화시킨다.
  - 전재 비율: 사건 하나당 기사 몇 건인가. 통신사 의존도의 실측치다.
  - 극성 균형: 갈등과 우호의 비율. reddit 이 지적한 "갈등 36 대 우호 3" 이
    부정성 편향인지 추출기 결함인지 보려면 이 수치를 계속 봐야 한다.

실행
----
    POSTGRES_HOST=... PYTHONPATH=backend python backend/scripts/evidence_report.py
    ... --json          기계가 읽을 형태로 출력
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import relation_evidence as ev  # noqa: E402
from core.db_config import close_sync_pool, get_sync_pool  # noqa: E402
from core.media_outlets import CAMPS, camp_of, is_known_press  # noqa: E402


def _bar(count: int, total: int, width: int = 28) -> str:
    if total <= 0:
        return ""
    filled = int(round(width * count / total))
    return "#" * filled + "." * (width - filled)


def collect() -> Dict[str, Any]:
    keys = ev.all_pair_keys()
    grouped = ev.load_observations(keys) if keys else {}

    total_observations = sum(len(v) for v in grouped.values())
    cluster_counts: Counter = Counter()
    coverage_counts: Counter = Counter()
    confidence_buckets: Counter = Counter()
    polarity_counts: Counter = Counter()
    press_counts: Counter = Counter()
    unknown_press: Counter = Counter()
    camp_observation_counts: Counter = Counter()
    clusters_total = 0
    promoted = 0
    survive_two = 0
    cross_camp = 0
    pair_rows: List[Dict[str, Any]] = []

    for key, observations in grouped.items():
        for obs in observations:
            press = obs.get("press") or "(미상)"
            press_counts[press] += 1
            camp_observation_counts[camp_of(obs.get("press"))] += 1
            if not is_known_press(obs.get("press")):
                unknown_press[press] += 1

        edge = ev.aggregate(observations)
        if not edge:
            continue
        promoted += 1
        props = edge["properties"]
        n_clusters = props["n_clusters"]
        clusters_total += n_clusters
        cluster_counts[min(n_clusters, 6)] += 1
        if n_clusters >= 2:
            survive_two += 1

        coverage = props["camp_coverage"]
        covered = round(coverage * len(CAMPS))
        coverage_counts[covered] += 1
        if coverage >= 2 / 3:
            cross_camp += 1

        confidence_buckets[min(9, int(props["confidence"] * 10))] += 1
        polarity_counts[edge["type"]] += 1

        pair_rows.append({
            "pair": key,
            "type": edge["type"],
            "n_observations": props["n_observations"],
            "n_clusters": n_clusters,
            "camp_coverage": coverage,
            "confidence": props["confidence"],
            "score": props["score"],
            "camps_agree": props["camps_agree"],
        })

    return {
        "pairs": len(grouped),
        "promoted": promoted,
        "observations": total_observations,
        "clusters": clusters_total,
        "survive_min_clusters_2": survive_two,
        "cross_camp": cross_camp,
        "cluster_counts": dict(cluster_counts),
        "coverage_counts": dict(coverage_counts),
        "confidence_buckets": dict(confidence_buckets),
        "polarity_counts": dict(polarity_counts),
        "press_counts": press_counts.most_common(20),
        "unknown_press": unknown_press.most_common(30),
        "camp_observation_counts": dict(camp_observation_counts),
        "pairs_detail": sorted(pair_rows, key=lambda r: -r["confidence"])[:20],
        "settings": {
            "half_life_days": ev.HALF_LIFE_DAYS,
            "simhash_distance": ev.NEAR_DUPLICATE_DISTANCE,
            "cluster_window_days": ev.CLUSTER_WINDOW_DAYS,
            "camp_reliability": ev.CAMP_RELIABILITY,
            "min_clusters": ev.MIN_CLUSTERS,
        },
    }


def render(data: Dict[str, Any]) -> None:
    out = print
    out("=" * 62)
    out("관계 근거 분포 리포트")
    out("=" * 62)

    if not data["observations"]:
        out("")
        out("근거 기록이 없다. 크롤러를 한 번 돌리거나,")
        out("scripts/backfill_edge_observations.py 로 기존 엣지를 옮긴다.")
        return

    settings = data["settings"]
    out(f"설정  반감기 {settings['half_life_days']}일 · "
        f"SimHash 거리 {settings['simhash_distance']} · "
        f"클러스터 창 {settings['cluster_window_days']}일 · "
        f"진영 신뢰상한 {settings['camp_reliability']} · "
        f"최소 사건 {settings['min_clusters']}")
    out("")
    out(f"관측(기사) {data['observations']}건 → 사건 {data['clusters']}건 "
        f"→ 관계 {data['promoted']}개 (쌍 {data['pairs']}개 중)")

    if data["clusters"]:
        ratio = data["observations"] / data["clusters"]
        out(f"전재 비율  사건 하나당 기사 {ratio:.2f}건 "
            f"({'전재가 거의 없다' if ratio < 1.3 else '통신사 전재가 상당하다'})")

    out("")
    out("-- 사건 수 분포 (관계당) " + "-" * 36)
    total = data["promoted"] or 1
    for n in sorted(data["cluster_counts"]):
        count = data["cluster_counts"][n]
        label = f"{n}건" if n < 6 else "6건+"
        out(f"  {label:>5}  {count:>5}  {_bar(count, total)}")
    survive = data["survive_min_clusters_2"]
    out(f"  최소 사건을 2로 올리면 {survive}/{total}개가 남는다 "
        f"({100 * survive / total:.0f}%)")

    out("")
    out("-- 진영 커버리지 " + "-" * 44)
    for n in sorted(data["coverage_counts"]):
        count = data["coverage_counts"][n]
        out(f"  진영 {n}개  {count:>5}  {_bar(count, total)}")
    out(f"  교차 검증 통과(2개 이상): {data['cross_camp']}/{total} "
        f"({100 * data['cross_camp'] / total:.0f}%) — 나머지는 화면에서 점선")

    out("")
    out("-- 신뢰도 분포 " + "-" * 46)
    for bucket in sorted(data["confidence_buckets"]):
        count = data["confidence_buckets"][bucket]
        out(f"  {bucket / 10:.1f}~{(bucket + 1) / 10:.1f}  {count:>5}  {_bar(count, total)}")

    out("")
    out("-- 극성 균형 " + "-" * 48)
    conflicts = data["polarity_counts"].get(ev.NEGATIVE, 0)
    allies = data["polarity_counts"].get(ev.POSITIVE, 0)
    out(f"  갈등 {conflicts} · 우호 {allies}")
    if allies:
        out(f"  갈등/우호 = {conflicts / allies:.1f}")
    out("  뉴스 가치 연구(Galtung & Ruge 1965, Soroka 2006)는 갈등 우위를")
    out("  예측한다. 다만 추출기가 부정 표현에 치우쳤을 수도 있어, 이 비율만")
    out("  으로는 둘을 구분할 수 없다. 손코딩 표본이 필요하다.")

    out("")
    out("-- 진영별 기사 수 " + "-" * 43)
    camp_counts = data["camp_observation_counts"]
    camp_total = sum(camp_counts.values()) or 1
    for camp in CAMPS:
        count = camp_counts.get(camp, 0)
        out(f"  {camp:<6} {count:>6}  {_bar(count, camp_total)}")

    out("")
    out("-- 상위 언론사 " + "-" * 46)
    for press, count in data["press_counts"][:12]:
        mark = "" if is_known_press(press) else "  <- 진영표에 없음"
        out(f"  {press:<14} {count:>6}{mark}")

    if data["unknown_press"]:
        out("")
        out("-- 진영표에 없는 매체 " + "-" * 39)
        out("   core/media_outlets.py 에 채우면 교차 검증이 정확해진다.")
        out("   지금은 전부 중도로 떨어진다.")
        for press, count in data["unknown_press"][:20]:
            out(f"  {press:<20} {count:>6}")

    out("")
    out("-- 신뢰도 상위 관계 " + "-" * 41)
    for row in data["pairs_detail"][:12]:
        kind = "갈등" if row["type"] == ev.NEGATIVE else "우호"
        agree = " ".join(f"{c[0]}{n}" for c, n in row["camps_agree"].items() if n)
        out(f"  {row['pair']:<20} {kind} "
            f"신뢰 {row['confidence']:.2f} · 사건 {row['n_clusters']} · "
            f"기사 {row['n_observations']} · {agree}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="JSON 으로 출력")
    args = parser.parse_args()

    try:
        data = collect()
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        else:
            render(data)
    finally:
        close_sync_pool()


if __name__ == "__main__":
    main()
