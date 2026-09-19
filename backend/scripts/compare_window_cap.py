"""창 상한(RELATION_MAX_WINDOWS_PER_PAIR)이 갈등·우호 판정을 바꾸는지 잰다.

2026-09-13 에 쌍 하나에서 채점할 창을 8개로 묶었다. 그 뒤로 갈등 대 우호가
107:32 에서 362:275 로 좁아졌다. 같은 기간에 분석량도 늘어서(러너 여섯 대)
둘 중 무엇이 비율을 움직였는지 알 수 없었다.

여기서는 분석량을 고정한다. 같은 기사, 같은 쌍에 상한만 켜고 꺼서 두 번
판정하고 결과를 나란히 놓는다. 다른 조건이 없으므로 차이가 나면 그것은
상한 때문이다.

    PYTHONPATH=backend python backend/scripts/compare_window_cap.py [기사수]

실측(2026-09-19, 기사 22건에서 판정이 나온 쌍 16개): 극성이 뒤집힌 쌍 0개.
쌍 하나가 판정에 쓰는 창은 중앙값 1개, 최대 2개로 상한(8)에 닿지도 않았다.
상한은 두 사람이 같은 기사에서 수십 번 함께 언급되는 드문 기사에서만 걸린다.
"""

import io
import sys
from collections import Counter

# 윈도우 콘솔은 cp949 라 한글 출력이 깨진다.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import crawlers.affective_analysis as aa  # noqa: E402
from crawlers.news_crawler_pipeline import (  # noqa: E402
    POLITICIANS,
    crawl_naver_section,
    extract_politicians,
    get_analyzer,
    get_article_text,
    pair_candidates,
)

WANT = int(sys.argv[1]) if len(sys.argv) > 1 else 20
WINDOWS = []
UNCAPPED = 10 ** 6


def collect(want):
    """정치 섹션에서 의원이 둘 이상 나오는 기사를 모은다."""
    articles = []
    seen = set()
    pool = []
    for sid in ("100", "101", "102"):          # 정치 · 경제 · 사회
        pool.extend(crawl_naver_section(sid, max_pages=5))
    print(f"  후보 기사 {len(pool)}건", flush=True)
    for item in pool:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        body = get_article_text(item["url"])
        if len(body) < 150:
            continue
        names = extract_politicians(body, POLITICIANS)
        if len(names) < 2:
            continue
        articles.append((item["title"], body, names))
        print(f"  [{len(articles)}/{want}] 이름 {len(names)}명 - {item['title'][:34]}", flush=True)
        if len(articles) >= want:
            break
    return articles


CALLS = {"n": 0}
_real_predict = aa.AffectiveAnalyzer.predict_nli


def _counting_predict(self, premise, hypothesis_text):
    CALLS["n"] += 1
    return _real_predict(self, premise, hypothesis_text)


aa.AffectiveAnalyzer.predict_nli = _counting_predict


def judge(analyzer, body, names, cap):
    """상한을 이 값으로 두고 기사 하나의 쌍들을 판정한다.

    쌍마다 NLI 호출 수도 센다. 창 하나에 4회이므로 호출 수를 4로 나누면
    그 쌍에서 채점한 창의 수다. 상한이 실제로 걸렸는지 이 값으로 본다.
    """
    aa.MAX_WINDOWS_PER_PAIR = cap
    out = {}
    pair_names = pair_candidates(names, body)
    for i in range(len(pair_names)):
        for j in range(i + 1, len(pair_names)):
            a, b = pair_names[i], pair_names[j]
            CALLS["n"] = 0
            result = analyzer.analyze_pair(body, a, b, names)
            windows = CALLS["n"] / 4
            if result:
                out[(a, b)] = (result["type"], round(result["score"], 3),
                               result["n_windows"], windows)
    return out


def main():
    print(f"기사 수집(의원 2명 이상, 목표 {WANT}건)", flush=True)
    articles = collect(WANT)
    print(f"수집 완료: {len(articles)}건\n", flush=True)

    analyzer = get_analyzer()
    if analyzer is None:
        print("모델을 띄우지 못했다")
        return 1

    capped_all, uncapped_all = Counter(), Counter()
    flips, kept, only_capped, only_uncapped = [], 0, 0, 0

    for n, (title, body, names) in enumerate(articles, 1):
        capped = judge(analyzer, body, names, 8)
        uncapped = judge(analyzer, body, names, UNCAPPED)
        for pair in set(capped) | set(uncapped):
            c, u = capped.get(pair), uncapped.get(pair)
            if u:
                WINDOWS.append(u[3])
            if c:
                capped_all[c[0]] += 1
            if u:
                uncapped_all[u[0]] += 1
            if c and u:
                if c[0] != u[0]:
                    flips.append((title[:26], pair, u, c))
                else:
                    kept += 1
            elif c:
                only_capped += 1
            else:
                only_uncapped += 1
        print(f"[{n}/{len(articles)}] 쌍 {len(set(capped) | set(uncapped))}개 - {title[:30]}",
              flush=True)

    total = kept + len(flips) + only_capped + only_uncapped
    print("\n=== 결과 ===")
    print(f"판정이 나온 쌍: {total}개")
    print(f"  상한 있음  갈등 {capped_all[aa.NEGATIVE_SENTIMENT]} / 우호 {capped_all[aa.POSITIVE_SENTIMENT]}")
    print(f"  상한 없음  갈등 {uncapped_all[aa.NEGATIVE_SENTIMENT]} / 우호 {uncapped_all[aa.POSITIVE_SENTIMENT]}")
    print(f"  양쪽 같은 판정: {kept}개")
    print(f"  극성이 뒤집힌 쌍: {len(flips)}개")
    print(f"  상한 있을 때만 판정됨: {only_capped}개 / 없을 때만: {only_uncapped}개")
    over = [w for w in WINDOWS if w > 8]
    if WINDOWS:
        WINDOWS.sort()
        print(f"  상한 없이 채점한 창 수: 중앙값 {WINDOWS[len(WINDOWS)//2]:.0f}개, "
              f"최대 {max(WINDOWS):.0f}개, 8개를 넘은 쌍 {len(over)}/{len(WINDOWS)}")
    for title, pair, u, c in flips[:12]:
        print(f"    {pair[0]}-{pair[1]}: 상한없음 {u[0][:8]}({u[1]}, 창 {u[2]}) "
              f"-> 상한있음 {c[0][:8]}({c[1]}, 창 {c[2]})  [{title}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
