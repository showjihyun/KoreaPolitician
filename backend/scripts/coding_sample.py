"""손코딩 표본 추출과 채점.

왜 필요한가
-----------
reddit 이 지적한 가장 큰 구멍은 알고리즘이 아니다. "자동 추출한 감정 엣지에
사람이 검증한 표본이 없다. precision/recall 숫자가 없다" 는 것이었다.
근거 로그가 생겨 표집 대상이 마련됐으므로, 남은 것은 사람이 읽고 코딩하는
일이다. 이 스크립트는 그 앞뒤를 맡는다.

  sample : 층화 표집해서 코더가 채울 CSV 를 만든다
  score  : 채운 CSV 를 읽어 일치도(Krippendorff's alpha)와 정밀도를 낸다

층화 기준은 극성(갈등/우호)과 언론사 진영이다. 무작위로 뽑으면 갈등과
보수지 기사가 표본을 채워, 우호 관계나 진보지 판정의 정밀도를 못 잰다.

코딩 규칙 (코더에게 그대로 전달할 것)
------------------------------------
근거 문장과 기사 제목을 보고, 두 사람 사이에 대해 그 기사가 무엇을
말하는지 하나 고른다.

  conflict : 한쪽이 다른 쪽을 비판/공격/반대한다
  ally     : 한쪽이 다른 쪽을 지지/옹호/협력한다
  none     : 둘이 함께 언급됐을 뿐 서로에 대한 태도가 없다
  unclear  : 근거만으로는 판단할 수 없다

'none' 이 많이 나오면 추출기가 공동 언급을 관계로 잘못 읽고 있다는 뜻이다.

실행
----
    POSTGRES_HOST=... PYTHONPATH=backend python backend/scripts/coding_sample.py sample -n 200
    # data/coding_sample.csv 를 두 사람이 각자 coder1 / coder2 열에 채운 뒤
    POSTGRES_HOST=... PYTHONPATH=backend python backend/scripts/coding_sample.py score
"""

import argparse
import csv
import os
import random
import sys
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any, Dict, Iterable, List, Optional, Sequence

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import relation_evidence as ev  # noqa: E402
from core.db_config import close_sync_pool  # noqa: E402
from core.media_outlets import camp_of  # noqa: E402

DEFAULT_PATH = os.path.join("data", "coding_sample.csv")

LABELS = ("conflict", "ally", "none", "unclear")

FIELDS = [
    "id", "pair", "press", "camp", "article_date", "model_label",
    "model_score", "evidence", "title", "url", "coder1", "coder2", "note",
]


# --- 표집 -------------------------------------------------------------------

def _model_label(polarity: int) -> str:
    return "conflict" if polarity < 0 else "ally"


def sample(n: int, path: str, seed: int) -> None:
    keys = ev.all_pair_keys()
    if not keys:
        print("근거 기록이 없다. 크롤러를 한 번 돌린 뒤 다시 실행한다.")
        return

    grouped = ev.load_observations(keys)
    rows: List[Dict[str, Any]] = []
    for key, observations in grouped.items():
        for obs in observations:
            rows.append({
                "id": obs["id"],
                "pair": key,
                "press": obs.get("press") or "",
                "camp": camp_of(obs.get("press")),
                "article_date": obs.get("article_date") or "",
                "model_label": _model_label(obs["polarity"]),
                "model_score": round(obs["score"], 3),
                "evidence": (obs.get("evidence") or "").replace("\n", " "),
                "title": (obs.get("title") or "").replace("\n", " "),
                "url": obs.get("url") or "",
                "coder1": "", "coder2": "", "note": "",
            })

    # 층: (극성, 진영). 각 층에서 같은 몫씩 뽑고, 모자란 층의 몫은 되돌린다.
    strata: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        strata[(row["model_label"], row["camp"])].append(row)

    rng = random.Random(seed)
    for bucket in strata.values():
        rng.shuffle(bucket)

    picked: List[Dict[str, Any]] = []
    remaining = dict(strata)
    while len(picked) < n and remaining:
        quota = max(1, (n - len(picked)) // len(remaining))
        for stratum in list(remaining):
            bucket = remaining[stratum]
            take = min(quota, len(bucket), n - len(picked))
            picked.extend(bucket[:take])
            del bucket[:take]
            if not bucket:
                del remaining[stratum]
            if len(picked) >= n:
                break

    rng.shuffle(picked)   # 코더가 층을 눈치채지 못하게 섞는다

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(picked)

    print(f"전체 관측 {len(rows)}건 중 {len(picked)}건을 뽑아 {path} 에 썼다.")
    print()
    print("층별 표본 수:")
    counts = Counter((r["model_label"], r["camp"]) for r in picked)
    for (label, camp), count in sorted(counts.items()):
        available = len(strata[(label, camp)]) + count
        print(f"  {label:<9} {camp:<5} {count:>4} / 모집단 {available}")
    print()
    print("코더 두 사람이 coder1 / coder2 열을 각자 채운다.")
    print(f"허용 값: {', '.join(LABELS)}")
    print("서로 상의하지 않고 채워야 일치도가 의미를 갖는다.")
    print("model_label 열은 정답이 아니라 채점 대상이다. 보고 따라 적지 말 것.")


# --- 채점 -------------------------------------------------------------------

def krippendorff_alpha(units: Sequence[Sequence[str]]) -> Optional[float]:
    """명목 척도 Krippendorff's alpha.

    units 는 단위마다 코더들이 매긴 라벨 목록이다. 두 명 미만이 코딩한
    단위는 제외한다(일치를 잴 수 없다).

    alpha = 1 - Do/De 이며 Do 는 관측된 불일치, De 는 우연히 기대되는
    불일치다. 단순 일치율과 달리 라벨 분포가 치우쳐 있을 때 부풀지 않는다.
    갈등이 압도적으로 많은 우리 데이터에서는 이 보정이 꼭 필요하다.
    """
    coincidence: Dict[tuple, float] = defaultdict(float)
    usable = 0
    for labels in units:
        valid = [x for x in labels if x]
        m = len(valid)
        if m < 2:
            continue
        usable += 1
        for a, b in combinations(valid, 2):
            coincidence[(a, b)] += 1 / (m - 1)
            coincidence[(b, a)] += 1 / (m - 1)
        for label in valid:
            coincidence[(label, label)] += 0.0

    if not usable:
        return None

    marginals: Dict[str, float] = defaultdict(float)
    for (a, _b), value in coincidence.items():
        marginals[a] += value
    total = sum(marginals.values())
    if total <= 1:
        return None

    observed = sum(value for (a, b), value in coincidence.items() if a != b)
    expected = sum(
        marginals[a] * marginals[b]
        for a in marginals for b in marginals if a != b
    ) / (total - 1)

    if expected == 0:
        # 모두 같은 라벨이면 불일치가 정의되지 않는다.
        return 1.0 if observed == 0 else None
    return 1.0 - observed / expected


def score(path: str) -> None:
    if not os.path.exists(path):
        print(f"{path} 가 없다. 먼저 sample 로 만든 뒤 코더가 채워야 한다.")
        return

    with open(path, encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    def clean(value: Optional[str]) -> str:
        value = (value or "").strip().lower()
        return value if value in LABELS else ""

    coded = [(clean(r.get("coder1")), clean(r.get("coder2")), r) for r in rows]
    both = [(a, b, r) for a, b, r in coded if a and b]
    any_coded = [(a, b, r) for a, b, r in coded if a or b]

    print("=" * 62)
    print("손코딩 채점")
    print("=" * 62)
    print(f"표본 {len(rows)}건 · 한 명 이상 코딩 {len(any_coded)}건 · "
          f"두 명 모두 코딩 {len(both)}건")

    invalid = sum(1 for r in rows
                  if (r.get("coder1") or "").strip() and not clean(r.get("coder1")))
    invalid += sum(1 for r in rows
                   if (r.get("coder2") or "").strip() and not clean(r.get("coder2")))
    if invalid:
        print(f"경고: 허용 값이 아닌 입력 {invalid}건은 미코딩으로 처리했다.")

    if not both:
        print("")
        print("두 사람이 함께 코딩한 항목이 없어 일치도를 낼 수 없다.")
        return

    agree = sum(1 for a, b, _ in both if a == b)
    print("")
    print("-- 코더 간 일치 " + "-" * 45)
    print(f"  단순 일치율   {100 * agree / len(both):.1f}% ({agree}/{len(both)})")

    alpha = krippendorff_alpha([(a, b) for a, b, _ in both])
    if alpha is None:
        print("  Krippendorff alpha  계산 불가")
    else:
        verdict = ("합의 수준으로 쓸 만하다" if alpha >= 0.80
                   else "잠정 결론에만 쓸 수 있다" if alpha >= 0.67
                   else "코딩 규칙이나 추출기를 손봐야 한다")
        print(f"  Krippendorff alpha  {alpha:.3f} — {verdict}")
        print("  기준: 0.80 이상 합의, 0.67~0.80 잠정, 그 아래는 보고 불가")

    disagreed = Counter((a, b) for a, b, _ in both if a != b)
    if disagreed:
        print("")
        print("  불일치 조합 (많은 순):")
        for (a, b), count in disagreed.most_common(6):
            print(f"    {a} vs {b}: {count}")

    # 두 코더가 합의한 항목만 정답으로 본다.
    gold = [(a, r) for a, b, r in both if a == b]
    print("")
    print("-- 추출기 성능 (두 코더가 합의한 " + f"{len(gold)}건 기준) " + "-" * 15)
    if not gold:
        print("  합의 항목이 없어 계산할 수 없다.")
        return

    for label in ("conflict", "ally"):
        predicted = [(g, r) for g, r in gold if r["model_label"] == label]
        actual = [(g, r) for g, r in gold if g == label]
        tp = sum(1 for g, r in predicted if g == label)
        precision = tp / len(predicted) if predicted else None
        recall = tp / len(actual) if actual else None
        name = "갈등" if label == "conflict" else "우호"
        parts = [f"  {name:<4} 예측 {len(predicted):>4} · 실제 {len(actual):>4}"]
        parts.append(f"정밀도 {precision:.2f}" if precision is not None else "정밀도 -")
        parts.append(f"재현율 {recall:.2f}" if recall is not None else "재현율 -")
        print(" · ".join(parts))

    wrong = Counter(g for g, r in gold if g != r["model_label"])
    if wrong:
        print("")
        print("  추출기가 틀린 방향:")
        for label, count in wrong.most_common():
            print(f"    실제 {label} 인데 관계로 뽑음: {count}")
        if wrong.get("none"):
            print("    'none' 이 많으면 공동 언급을 관계로 읽고 있다는 뜻이다.")
            print("    발화 주체 귀속(문서 알고리즘 4)이 필요하다는 신호다.")

    print("")
    print("-- 진영별 정밀도 " + "-" * 44)
    by_camp: Dict[str, List[bool]] = defaultdict(list)
    for g, r in gold:
        by_camp[r["camp"]].append(g == r["model_label"])
    for camp, results in sorted(by_camp.items()):
        hit = sum(results)
        print(f"  {camp:<6} {hit}/{len(results)}  {100 * hit / len(results):.0f}%")
    print("  진영별로 정밀도가 크게 다르면, 추출기가 특정 진영의 문체에")
    print("  약하다는 뜻이라 언론사 논조 보정(알고리즘 1)보다 먼저 고쳐야 한다.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_sample = sub.add_parser("sample", help="코딩용 CSV 를 만든다")
    p_sample.add_argument("-n", type=int, default=200, help="표본 수 (기본 200)")
    p_sample.add_argument("--path", default=DEFAULT_PATH)
    p_sample.add_argument("--seed", type=int, default=22,
                          help="재현 가능한 표집을 위한 난수 씨앗")

    p_score = sub.add_parser("score", help="채운 CSV 를 채점한다")
    p_score.add_argument("--path", default=DEFAULT_PATH)

    args = parser.parse_args()
    try:
        if args.command == "sample":
            sample(args.n, args.path, args.seed)
        else:
            score(args.path)
    finally:
        close_sync_pool()


if __name__ == "__main__":
    main()
