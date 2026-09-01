"""화제성(hotness) 산출.

원래 화제성은 X·유튜브·인스타그램 수집으로 채울 계획이었으나, X 와
인스타그램은 비로그인 수집이 막혔고 유튜브도 수집이 불안정해 테이블이
계속 비어 있었다.

그래서 이미 안정적으로 수집되는 뉴스를 화제성의 1차 신호로 쓴다. 어떤
의원이 오늘 기사에 얼마나 등장했는가는 정치적 화제성의 직접적인 지표이고,
새 수집원·API 키·robots.txt 문제가 전혀 없다.

politician_sns_hotness 는 플랫폼 무관 구조라 platform='News' 로 넣으면
기존 요약 로직(politician_hotness_summary)이 그대로 동작한다. 유튜브가
복구되면 두 플랫폼이 함께 집계된다.
"""

import hashlib
import logging
import math
from datetime import datetime
from typing import Dict, Iterable, List, Sequence

from core.db_config import get_sync_pool

logger = logging.getLogger(__name__)

# --- 점수 스케일 ---------------------------------------------------------
# 뉴스와 유튜브 점수는 같은 테이블(politician_sns_hotness)에서 합산·비교되므로
# 반드시 같은 스케일이어야 한다. 기준을 여기 한 곳에 모아 둔다.
#
#   기사 1건 = 최대 100점 (단독 기사)
#   영상 1건 = 최대 100점 (1천만 조회)
#
# 처음에는 유튜브를 `조회수 x 0.05 x 채널가중치` 로 계산했는데, 실측해 보니
# 조회수가 수십만~수백만이라 점수가 100만 단위까지 나왔다. 뉴스 평균 54점,
# 유튜브 평균 17,779점으로 300배 차이가 생겨, 화제성 순위가 사실상 유튜브
# 조회수만 반영했다(점수 있는 274명 중 269명의 top_platform 이 YouTube).
# 조회수 분포는 로그정규에 가까우므로 로그로 압축해 정규화한다.
NEWS_MENTION_BASE_SCORE = 100.0

YOUTUBE_MAX_SCORE = 100.0
YOUTUBE_LOG_FLOOR = 3.0   # 10^3 = 1,000회 -> 0점 (크롤러의 채택 임계값과 동일)
YOUTUBE_LOG_CEIL = 7.0    # 10^7 = 1천만회 -> 100점

PLATFORM_NEWS = "News"
PLATFORM_YOUTUBE = "YouTube"


# --- 집계 기간 -------------------------------------------------------------
# 호불호 관계는 수집 시작부터 누적이지만, 화제성은 "지금 누가 회자되는가" 라서
# 최근 구간만 본다. 하루로 끊으면 수집이 하루 밀릴 때마다 순위가 통째로 비었고,
# 주 단위로 오르내리는 주제는 흐름이 안 보였다.
#
# 이 값을 읽는 쪽(요약 갱신, 순위 API, 최근 언급 API)이 모두 같은 창을 써야
# 한다. 한 곳만 넓히면 화면에 제 합과 안 맞는 숫자가 나간다.
TREND_DAYS = 7


def youtube_score(view_count: int, authority_weight: float = 1.0) -> float:
    """유튜브 조회수를 뉴스와 같은 스케일(0~100)로 환산한다.

        1천회    ->   0점
        1만회    ->  25점
        10만회   ->  50점
        100만회  ->  75점
        1천만회  -> 100점

    authority_weight 는 대형 정치/뉴스 채널 가중치다. 정규화 뒤에 곱하므로
    스케일이 폭주하지 않는다.
    """
    if view_count is None or view_count <= 0:
        return 0.0
    exponent = math.log10(view_count)
    ratio = (exponent - YOUTUBE_LOG_FLOOR) / (YOUTUBE_LOG_CEIL - YOUTUBE_LOG_FLOOR)
    normalized = max(0.0, min(1.0, ratio)) * YOUTUBE_MAX_SCORE
    return round(normalized * authority_weight, 2)


def ensure_news_schema(db_config=None):
    """news_sentiment 스키마를 준비한다. 파이프라인 시작 시 한 번만 부른다.

    예전에는 save_to_postgresql 안에 DDL 이 있어 기사 한 건마다 CREATE TABLE /
    CREATE INDEX 가 실행됐다. 분석 스레드 8개가 동시에 치면 카탈로그 잠금
    경합이 생기고, 관리형 DB 에서는 커넥션 한도까지 겹친다.

    화제성 산출이 이 테이블을 읽으므로, 무거운 크롤러 모듈을 임포트하지 않고도
    스키마를 만들 수 있도록 여기에 둔다.
    """
    with get_sync_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.news_sentiment (
                    id SERIAL PRIMARY KEY,
                    title TEXT,
                    url TEXT,
                    press TEXT,
                    date TEXT,
                    politicians TEXT,
                    sentiment_label TEXT,
                    sentiment_score FLOAT,
                    content TEXT,
                    base_date TEXT,
                    inserted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_news_sentiment_base_date ON public.news_sentiment (base_date);
                -- url 유니크 제약이 없어 SELECT 후 INSERT 하는 동안 다른 스레드가
                -- 같은 url 을 넣으면 중복 행이 생겼다. 제약을 걸고 upsert 로 바꾼다.
                CREATE UNIQUE INDEX IF NOT EXISTS uq_news_sentiment_url ON public.news_sentiment (url);
            """)


def _focus_weight(mention_count: int) -> float:
    """기사 한 건이 여러 의원을 나열할수록 개인당 주목도는 낮다.

    개각 기사처럼 10명을 나열한 글과 한 명을 다루는 글을 같게 볼 수는 없다.
    다만 선형으로 나누면 나열 기사가 지나치게 죽으므로 제곱근을 쓴다.
    (1명 -> 1.00, 4명 -> 0.50, 10명 -> 0.32)
    """
    return 1.0 / math.sqrt(max(1, mention_count))


def _post_id(url: str, title: str) -> str:
    """기사당 안정적인 식별자. UNIQUE(member_name, platform, post_id) 로 중복 방지."""
    seed = (url or title or "").encode("utf-8")
    return "news_" + hashlib.md5(seed).hexdigest()[:16]


def record_news_hotness(base_date: str) -> int:
    """해당 날짜의 news_sentiment 를 읽어 화제성 행을 만든다.

    반환값은 기록한 (의원, 기사) 쌍의 수.
    같은 날 다시 실행해도 post_id 가 같아 upsert 되므로 중복이 쌓이지 않는다.
    """
    pool = get_sync_pool()
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT title, url, press, politicians, sentiment_label, sentiment_score
                FROM public.news_sentiment
                WHERE base_date = %s AND politicians IS NOT NULL AND politicians <> ''
                """,
                (base_date,),
            )
            articles = cur.fetchall()

        rows = []
        for title, url, press, politicians, label, score in articles:
            names = [n.strip() for n in (politicians or "").split(",") if n.strip()]
            if not names:
                continue
            weight = _focus_weight(len(names))
            pid = _post_id(url, title)
            for name in names:
                rows.append((
                    name,
                    PLATFORM_NEWS,
                    press or "Press",
                    pid,
                    (title or "")[:300],
                    {"url": url, "press": press, "sentiment_label": label,
                     "mentioned_with": len(names) - 1},
                    round(NEWS_MENTION_BASE_SCORE * weight, 2),
                    score or 0.0,
                ))

        if not rows:
            logger.info(f"[화제성] {base_date} 기사에서 의원 언급을 찾지 못했습니다.")
            return 0

        from psycopg.types.json import Jsonb
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO public.politician_sns_hotness
                    (member_name, platform, author_type, post_id, content_preview,
                     engagement_data, hot_score, sentiment_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (member_name, platform, post_id) DO UPDATE SET
                    engagement_data = EXCLUDED.engagement_data,
                    hot_score = EXCLUDED.hot_score,
                    sentiment_score = EXCLUDED.sentiment_score,
                    collected_at = NOW()
                """,
                [(a, b, c, d, e, Jsonb(f), g, h) for a, b, c, d, e, f, g, h in rows],
            )
        conn.commit()
        logger.info(f"[화제성] 뉴스 기반 {len(rows)}건 기록 "
                    f"(기사 {len(articles)}건, 의원 {len({r[0] for r in rows})}명)")
        return len(rows)
    except Exception:
        if conn is not None:
            conn.rollback()
        logger.exception("[화제성] 뉴스 기반 기록 실패")
        raise
    finally:
        if conn is not None:
            pool.putconn(conn)


def update_summary(name: str) -> None:
    """의원 한 명의 요약 테이블(politician_hotness_summary)을 갱신한다.

    최근 일주일을 현재 점수로, 전체 이력을 누적 점수로 쓴다.
    하루로 끊으면 수집이 하루 밀릴 때마다 순위가 통째로 비었다. 뉴스는
    주 단위로 오르내리는 주제가 많아 일주일이 흐름을 더 잘 보여 준다.
    플랫폼과 무관하게 동작하므로 뉴스·유튜브가 함께 집계된다.
    """
    pool = get_sync_pool()
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT SUM(hot_score) AS total_score, platform, COUNT(*) AS post_count
                FROM public.politician_sns_hotness
                WHERE member_name = %s
                  AND collected_at > NOW() - (%s * INTERVAL '1 day')
                GROUP BY platform
                ORDER BY total_score DESC
                """,
                (name, TREND_DAYS),
            )
            rows = cur.fetchall()
            current_total = sum(r[0] for r in rows) if rows else 0
            top_platform = rows[0][1] if rows else "N/A"

            cur.execute(
                "SELECT SUM(hot_score) FROM public.politician_sns_hotness WHERE member_name = %s",
                (name,),
            )
            cumulative_total = cur.fetchone()[0] or 0

            cur.execute(
                """
                INSERT INTO public.politician_hotness_summary
                    (member_name, current_hot_score, cumulative_hot_score, top_platform, last_updated)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (member_name) DO UPDATE SET
                    -- 집계 창이 일주일이라, 이 값은 하루치 증감이 아니라
                    -- 하루 어긋난 두 주간 합계의 차다. 아직 읽는 곳이 없다.
                    daily_change = %s - politician_hotness_summary.current_hot_score,
                    current_hot_score = %s,
                    cumulative_hot_score = %s,
                    top_platform = %s,
                    last_updated = NOW()
                """,
                (name, current_total, cumulative_total, top_platform,
                 current_total, current_total, cumulative_total, top_platform),
            )
        conn.commit()
    except Exception as exc:                                   # noqa: BLE001
        if conn is not None:
            conn.rollback()
        logger.error(f"[화제성] 요약 갱신 실패 ({name}): {exc}")
    finally:
        if conn is not None:
            pool.putconn(conn)


def mark_data_updated(when: str = None) -> None:
    """system_settings.last_data_update 를 갱신한다.

    /api/stats 의 last_updated 가 이 값을 읽는데, 지금까지는 run_news_sns.py
    (우리가 CI 에서 쓰지 않는 데몬)만 갱신해서 값이 멈춰 있었다. 화면에
    "데이터 기준 시각" 을 보여주려면 실제 수집 시점이 들어가야 한다.
    """
    stamp = when or datetime.now().strftime("%Y-%m-%d")
    pool = get_sync_pool()
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO system_settings (key, value, updated_at)
                VALUES ('last_data_update', %s, CURRENT_TIMESTAMP)
                ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """,
                (stamp,),
            )
        conn.commit()
        logger.info(f"[화제성] 데이터 기준일 갱신: {stamp}")
    except Exception as exc:                                   # noqa: BLE001
        if conn is not None:
            conn.rollback()
        logger.error(f"[화제성] 기준일 갱신 실패: {exc}")
    finally:
        if conn is not None:
            pool.putconn(conn)


def refresh_summaries(names: Iterable[str]) -> int:
    """여러 의원의 요약을 갱신한다."""
    unique = sorted({n for n in names if n})
    for name in unique:
        update_summary(name)
    logger.info(f"[화제성] 요약 갱신 {len(unique)}명")
    return len(unique)


def rebuild_from_news(base_date: str) -> int:
    """뉴스 기반 화제성 기록 + 해당 의원 요약 갱신을 한 번에 수행한다."""
    recorded = record_news_hotness(base_date)
    if not recorded:
        return 0

    pool = get_sync_pool()
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT member_name FROM public.politician_sns_hotness
                WHERE platform = %s
                  AND collected_at > NOW() - (%s * INTERVAL '1 day')
                """,
                (PLATFORM_NEWS, TREND_DAYS),
            )
            names = [r[0] for r in cur.fetchall()]
    finally:
        if conn is not None:
            pool.putconn(conn)

    refresh_summaries(names)
    mark_data_updated()
    return recorded
