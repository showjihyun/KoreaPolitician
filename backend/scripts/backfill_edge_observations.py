"""기존 호불호 엣지를 근거 로그로 옮기고 다시 집계한다.

왜 필요한가
-----------
근거 집계가 들어오기 전에 만들어진 엣지에는 관측 기록이 없다. 그대로 두면
새로 집계된 엣지와 화면에서 구분되지 않는다. 근거 기사가 몇 건인지, 어느
진영이 보도했는지 알 수 없는 관계가 교차 검증을 통과한 관계와 같은 굵기로
그려지는 것이 지금 가장 큰 문제다.

무엇을 하는가
-------------
1. turing_edges 의 호불호 엣지를 훑는다.
2. properties.url 이 news_sentiment 에 있으면, 그 기사에서 언론사·본문·
   날짜를 되살려 관측 한 건으로 넣는다. 되살릴 수 있는 것은 딱 한 건이다.
   덮어쓰기 방식이 나머지를 이미 지웠기 때문이다. 그래서 이 엣지들은
   대개 진영 하나짜리(kappa = 1/3)로 남고, 화면에서 점선으로 표시된다.
   이는 손실이 아니라 실제 근거 수준을 드러내는 것이다.
3. url 이 없는 엣지는 근거를 댈 수 없는 관계다. 목록으로 보여 주고,
   --drop-unsourced 를 주면 지운다. 기본은 지우지 않는다.
4. 관측이 있는 쌍을 전부 다시 집계해 엣지를 새로 쓴다.

실행
----
    POSTGRES_HOST=... PYTHONPATH=backend python backend/scripts/backfill_edge_observations.py
    ... --drop-unsourced      근거 없는 엣지를 지운다
    ... --dry-run             바꾸지 않고 무엇을 할지만 출력한다
"""

import argparse
import logging
import os
import sys
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import relation_evidence  # noqa: E402
from core.db_config import close_sync_pool, get_sync_pool  # noqa: E402
from core.media_outlets import camp_of  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

SENTIMENT_TYPES = (relation_evidence.POSITIVE, relation_evidence.NEGATIVE)


def _node_names() -> Dict[str, str]:
    """turing_nodes id -> 이름."""
    names: Dict[str, str] = {}
    with get_sync_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, properties FROM turing_nodes")
            for node_id, props in cur.fetchall():
                name = (props or {}).get("name")
                if name:
                    names[node_id] = name
    return names


def _sentiment_edges() -> List[Tuple[str, str, str, dict]]:
    with get_sync_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_id, target_id, type, properties FROM turing_edges "
                "WHERE type = ANY(%s)",
                (list(SENTIMENT_TYPES),),
            )
            return [(r[0], r[1], r[2], r[3] or {}) for r in cur.fetchall()]


def _articles_by_url(urls: List[str]) -> Dict[str, dict]:
    if not urls:
        return {}
    found: Dict[str, dict] = {}
    with get_sync_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT url, title, press, date, content, politicians, inserted_at "
                "FROM public.news_sentiment WHERE url = ANY(%s)",
                (urls,),
            )
            for row in cur.fetchall():
                found[row[0]] = {
                    "url": row[0], "title": row[1], "press": row[2],
                    "date": row[3], "content": row[4],
                    "politicians": row[5], "inserted_at": row[6],
                }
    return found


def _normalise_legacy_score(score: float) -> float:
    """예전 엣지의 점수를 0~1 로 맞춘다.

    두 척도가 섞여 있다. 뉴스 파이프라인이 만든 엣지는 NLI 신뢰도라 0~1
    이고, 손으로 넣은 샘플은 0~100 이다. 1을 넘으면 100분율로 본다.
    """
    value = float(score or 0.0)
    if value > 1.5:
        return min(1.0, value / 100.0)
    return min(1.0, max(0.0, value))


def backfill(drop_unsourced: bool = False, dry_run: bool = False) -> None:
    names = _node_names()
    edges = _sentiment_edges()
    logger.info("호불호 엣지 %d개를 확인한다.", len(edges))

    urls = [p.get("url") for _, _, _, p in edges if p.get("url")]
    articles = _articles_by_url([u for u in urls if u])

    rows = []
    unsourced: List[Tuple[str, str, str]] = []
    missing_article: List[str] = []

    for source_id, target_id, edge_type, props in edges:
        name_a = names.get(source_id)
        name_b = names.get(target_id)
        if not name_a or not name_b:
            continue

        # 이미 집계로 만들어진 엣지는 건드리지 않는다.
        if props.get("provenance") == "aggregate":
            continue

        url = props.get("url")
        if not url:
            unsourced.append((name_a, name_b, edge_type))
            continue

        article = articles.get(url)
        if not article:
            # 엣지에 주소는 있는데 기사 본문이 남아 있지 않은 경우다.
            # 언론사를 모르므로 진영을 배정할 수 없다. 관측은 넣되
            # 중도로 떨어지고, 교차 검증에서 한 진영으로만 센다.
            missing_article.append(url)

        content = (article or {}).get("content") or ""
        rows.append({
            "entity_a": name_a,
            "entity_b": name_b,
            "polarity": 1 if edge_type == relation_evidence.POSITIVE else -1,
            "score": _normalise_legacy_score(props.get("score")),
            "focus_weight": 1.0,
            "press": (article or {}).get("press"),
            "url": url,
            "title": (article or {}).get("title"),
            "article_date": (article or {}).get("date") or props.get("date"),
            "simhash": relation_evidence.simhash(content) if content else 0,
            "evidence": props.get("evidence") or "",
            "source": "backfill",
        })

    logger.info("근거로 옮길 엣지 %d개, 기사 본문을 못 찾은 주소 %d개",
                len(rows), len(missing_article))

    if unsourced:
        logger.warning("")
        logger.warning("근거(기사 주소)가 없는 엣지 %d개:", len(unsourced))
        for name_a, name_b, edge_type in unsourced:
            label = "우호" if edge_type == relation_evidence.POSITIVE else "갈등"
            logger.warning("  %s - %s (%s)", name_a, name_b, label)
        logger.warning("")
        logger.warning("이들은 임포터가 넣던 예시 데이터일 가능성이 높다.")
        logger.warning("지우려면 --drop-unsourced 를 준다.")

    if dry_run:
        logger.info("[dry-run] 아무것도 바꾸지 않았다.")
        return

    if rows:
        relation_evidence.ensure_schema()
        saved = relation_evidence.record_observations(rows)
        logger.info("관측 %d건 적재", saved)

    if drop_unsourced and unsourced:
        name_to_id = {v: k for k, v in names.items()}
        deleted = 0
        with get_sync_pool().connection() as conn:
            with conn.cursor() as cur:
                for name_a, name_b, edge_type in unsourced:
                    src, tgt = name_to_id.get(name_a), name_to_id.get(name_b)
                    if not src or not tgt:
                        continue
                    cur.execute(
                        "DELETE FROM turing_edges "
                        "WHERE source_id = %s AND target_id = %s AND type = %s",
                        (src, tgt, edge_type),
                    )
                    deleted += cur.rowcount
        logger.info("근거 없는 엣지 %d개 삭제", deleted)
        logger.info("API 를 재기동해야 인메모리 그래프에도 반영된다.")

    # 관측이 있는 모든 쌍을 다시 집계한다.
    keys = relation_evidence.all_pair_keys()
    aggregated = relation_evidence.aggregate_pairs(keys)
    logger.info("")
    logger.info("쌍 %d개 중 %d개가 엣지로 승격됐다.", len(keys), len(aggregated))

    single_camp = sum(1 for e in aggregated.values()
                      if e["properties"]["camp_coverage"] < 2 / 3)
    logger.info("그중 단일 진영 보도 %d개 (화면에서 점선으로 표시된다).", single_camp)
    logger.info("")
    logger.info("집계 결과를 엣지에 반영하려면 크롤러를 한 번 돌리거나,")
    logger.info("push_aggregated_edges 를 직접 호출한다:")
    logger.info("  PYTHONPATH=backend python -c \\")
    logger.info("    'from crawlers.news_crawler_pipeline import push_aggregated_edges;\\")
    logger.info("     from core.relation_evidence import all_pair_keys;\\")
    logger.info("     print(push_aggregated_edges(all_pair_keys()))'")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drop-unsourced", action="store_true",
                        help="근거 기사 주소가 없는 엣지를 지운다")
    parser.add_argument("--dry-run", action="store_true",
                        help="바꾸지 않고 계획만 출력한다")
    args = parser.parse_args()

    try:
        backfill(drop_unsourced=args.drop_unsourced, dry_run=args.dry_run)
    finally:
        close_sync_pool()


if __name__ == "__main__":
    main()
