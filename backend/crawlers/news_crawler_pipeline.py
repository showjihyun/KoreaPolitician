from dotenv import load_dotenv
import os
import time
import hashlib
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright
from newspaper import Article
from bs4 import BeautifulSoup
import sys
import psycopg
from core.name_matcher import find_names
from core.hotness import ensure_news_schema, focus_weight, rebuild_from_news
from core import relation_evidence
from core.db_config import (api_base_url, close_sync_pool,
                            db_config_from_env, env, get_sync_pool)
from core.service_time import now_kst, service_date
import logging
import threading
import traceback
import json
from crawlers.affective_analysis import AffectiveAnalyzer
import requests
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed

# Load environment variables from .env file
load_dotenv()

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data/news_crawler_pipeline.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# assembly_members_complete.json에서 국회의원 이름 전체를 읽어 POLITICIANS 리스트 생성
POLITICIANS = []
try:
    # 프로젝트 루트 기준 경로
    member_path = 'data/assembly_members_complete.json'
    if not os.path.exists(member_path):
        member_path = 'assembly_members_complete.json'

    with open(member_path, 'r', encoding='utf-8') as f:
        members = json.load(f)
        POLITICIANS = [m['name'] for m in members if m.get('name')]
    logger.info(f"총 {len(POLITICIANS)}명의 국회의원 이름을 POLITICIANS에 로드했습니다.")
except Exception as e:
    logger.warning(f"국회의원 이름 로드 실패: {e}")
    POLITICIANS = []

# NLI 모델은 처음 쓸 때 띄운다.
#
# 예전에는 이 모듈을 임포트하는 순간 모델(약 550MB)을 받아 올렸다. 그래서
# 의원 이름 목록만 필요한 SNS 파이프라인도, 수집만 하는 단계도 모델을
# 기다렸다. 수집·분석·마무리를 러너 여러 대로 나누면 그 비용이 러너마다
# 붙고, 허깅페이스에 비인증 요청이 겹쳐 받기가 막힐 위험도 생긴다.
analyzer = None
_analyzer_failed = False
_analyzer_lock = threading.Lock()


def get_analyzer():
    """분석기를 돌려준다. 띄우지 못하면 None 이고, 그 뒤로는 다시 시도하지 않는다.

    실패해도 기사 저장은 계속한다. 관계는 빠지지만 화제성은 기사만으로
    산출되기 때문이다. 대신 조용히 넘어가지 않고 처음 한 번 크게 남긴다.
    """
    global analyzer, _analyzer_failed
    if analyzer is not None or _analyzer_failed:
        return analyzer
    with _analyzer_lock:
        if analyzer is None and not _analyzer_failed:
            try:
                analyzer = AffectiveAnalyzer()
                logger.info("AffectiveAnalyzer 초기화 성공")
            except Exception as e:
                _analyzer_failed = True
                logger.error(f"[모델 없음] AffectiveAnalyzer 를 띄우지 못해 이번 회차는 "
                             f"관계 판정 없이 기사만 저장한다: {e}")
    return analyzer

# DCP(Dynamic Contextual Propagation)는 이 파이프라인에서 더 이상 쓰지 않는다.
# 두 가지 이유다. 첫째, 운영 환경에서는 동작한 적이 없다. DCPCalculator 가
# 동맹 문맥을 http://localhost:5000 에서 가져오도록 되어 있어 GitHub Actions
# 에서는 매번 실패하고 입력값을 그대로 돌려줬다. 즉 social_impact_score 는
# 늘 score 와 같았다. 둘째, 동맹을 "같은 정당"으로 정의하기 때문에 정파
# 구조를 보정하는 게 아니라 증폭한다.
#
# 대체 계획은 docs/MEDIA_BIAS_RESEARCH.md 의 알고리즘 3이다. 동맹을 국회
# 공동발의로 정의해 뉴스 밖 근거로 바꾼 뒤 다시 켠다. 그때까지
# social_impact_score 는 근거 집계가 진영 교차 검증을 반영해 채운다.
# core/dcp_algorithm.py 는 그 작업의 출발점으로 남겨 둔다.

# 네이버 기사 본문 컨테이너. 앞에서부터 먼저 잡히는 것을 쓴다.
NAVER_BODY_SELECTORS = ("#dic_area", "#newsct_article", "#articeBody", "#articleBodyContents")

_ARTICLE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def _naver_article_text(url):
    """네이버 기사 본문을 직접 파싱한다.

    newspaper3k 의 일반 추출 규칙은 네이버 마크업에서 본문을 못 찾고
    보일러플레이트 83자만 돌려준다. 실측(정치 섹션 10건): newspaper3k 는
    150자 기준을 1건만 통과했고, 전용 파서는 10건 전부 통과했다(530~2033자).
    이 때문에 분석 대상 54건 중 3건만 저장되고 있었다.

    브라우저가 필요 없어 newspaper3k 보다 빠르기도 하다.
    """
    res = requests.get(url, headers=_ARTICLE_HEADERS, timeout=15)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "lxml")
    for selector in NAVER_BODY_SELECTORS:
        node = soup.select_one(selector)
        if not node:
            continue
        for tag in node(["script", "style"]):
            tag.decompose()
        text = node.get_text("\n", strip=True)
        if text:
            return text
    return ""


def get_article_text(url):
    if not url:
        return ""
    try:
        if "naver.com" in url:
            text = _naver_article_text(url)
            if text:
                return text
            logger.warning(f"[본문 없음] 네이버 셀렉터로 본문을 못 찾음: {url}")
            # 셀렉터가 바뀐 경우를 대비해 아래 일반 경로로 넘어간다.

        article = Article(url, language='ko')
        article.download()
        article.parse()
        return article.text
    except Exception as e:
        logger.warning(f"[본문 크롤링 실패] {url} -> {e}")
        return ""

POLITICAL_KEYWORDS = [
    '의원', '국회', '정당', '후보', '대표', '대변인', '위원', '장관', '지사', '시장', '대통령', '당대표', '원내대표', '최고위원',
    '더불어민주당', '국민의힘', '정의당', '조국혁신당', '개혁신당', '기본소득당', '진보당', '민주당', '국힘', '여당', '야당'
]

def extract_politicians(text, name_list):
    """
    텍스트에서 국회의원 이름을 추출하되, 동명이인 오탐을 줄이기 위해
    정치 관련 키워드가 포함된 경우에만 유효한 것으로 판단함.
    """
    # 1. 정치 관련 키워드가 문맥(text)에 하나라도 있는지 확인
    has_keyword = any(kw in text for kw in POLITICAL_KEYWORDS)

    # 키워드가 없으면 정치 기사가 아니거나 동명이인일 확률이 높으므로 빈 리스트 반환
    if not has_keyword:
        return []

    # 예전에는 `if name in text` 단순 부분일치였다. 2글자 이름(김건·김윤·
    # 김현·박정·손솔·허영·황희)이 김건희·박정희·허영심·김윤덕 같은 낱말의
    # 앞부분과 겹쳐 실제 언급이 없는 관계를 만들어냈다.
    return find_names(text, name_list)

#: 한 회차에 분석할 기사 수 상한. NEWS_MAX_ARTICLES 로 조절한다.
#: 왜 필요한지는 run_pipeline 의 "분석량 상한" 주석에 적었다.
NEWS_MAX_ARTICLES = int(env("NEWS_MAX_ARTICLES", "300"))

#: 수집 + 분석에 쓸 수 있는 시간(초). 넘기면 분석을 멈추고 집계로 넘어간다.
#:
#: 상한(NEWS_MAX_ARTICLES)만으로는 시간을 못 막는다. 기사 한 건의 비용이
#: 본문 길이와 등장 의원 수에 따라 크게 달라지기 때문이다. 실제로 2026-09-04
#: 부터 09-09 까지 여섯 회차가 전부 GitHub Actions 90분 한도에 걸려 취소됐고,
#: 마지막 회차는 300건 중 140건째에서 잘렸다.
#:
#: 문제는 느린 것 자체가 아니라 **잘리는 위치**였다. 기사 저장은 기사마다
#: 하지만 엣지 집계와 화제성 산출은 분석 루프가 끝난 뒤에 한 번 도는 구조라,
#: 루프 도중에 죽으면 그날 수집분이 화면에 하나도 반영되지 않는다. API 의
#: last_updated 가 2026-09-03 에 멈춰 있던 이유가 이것이다.
#:
#: 그래서 시간을 러너가 아니라 파이프라인이 재게 한다. 예산을 넘기면 남은
#: 기사를 버리고 집계·화제성을 반드시 돌린다. 그날 분석한 만큼은 반드시
#: 화면에 나가고, 못 본 기사는 다음 회차가 가져간다.
NEWS_TIME_BUDGET_SEC = int(env("NEWS_TIME_BUDGET_SEC", "5400"))

#: 그중 수집(섹션 크롤링 + 의원 296명 검색)에 허용하는 시간(초).
#: 실측 약 11분. 네이버 검색이 응답하지 않으면 296명 x 2회 x 30초 타임아웃이
#: 예산을 통째로 먹으므로 따로 막아 둔다.
NEWS_COLLECT_BUDGET_SEC = int(env("NEWS_COLLECT_BUDGET_SEC", "1800"))

#: 예산을 넘긴 뒤 돌고 있는 워커를 기다려 주는 시간(초).
#:
#: 워커는 쌍 사이에서 예산을 보므로 대개 몇 초 안에 돌아온다. 그 결과까지는
#: 집계에 넣는 게 이득이다. 다만 무한정 기다리면 안 된다. 2026-09-13 회차가
#: 정확히 그래서 죽었다. 아래 out_of_time 처리 주석을 함께 보라.
NEWS_FINISH_GRACE_SEC = int(env("NEWS_FINISH_GRACE_SEC", "60"))

#: 기사 한 건에서 관계 쌍을 만들 이름의 최대 개수.
#:
#: 쌍의 수는 이름 수의 제곱으로 는다(n=8 은 28쌍, n=20 은 190쌍). 쌍마다
#: 창을 훑고 창마다 NLI 를 4회 부르므로, 의원을 줄줄이 나열한 기사 한 건이
#: 회차의 남은 시간을 통째로 먹을 수 있다. 2026-09-13 회차에서 기사 한 건이
#: 10분 넘게 한 워커를 붙잡고 있었고, 그 사이 로그는 한 줄도 나오지 않았다.
#:
#: 나열 기사는 관계의 근거로도 약하다. 언급 하나의 무게를 1/√n 로 깎는 것과
#: 같은 이유다(core/hotness.py 의 focus_weight). 많이 언급된 이름부터 남긴다.
RELATION_MAX_NAMES_PER_ARTICLE = int(env("RELATION_MAX_NAMES_PER_ARTICLE", "12"))

#: 기사 한 건이 이 시간을 넘기면 이름 수와 쌍 수를 남긴다.
#: 조용히 오래 걸리는 기사를 다음에 찾아낼 수 있게 하기 위한 로그다.
NEWS_SLOW_ARTICLE_SEC = int(env("NEWS_SLOW_ARTICLE_SEC", "30"))

# CPU 코어의 80%를 사용하여 병렬 처리 수 결정
MAX_WORKERS = max(1, int((os.cpu_count() or 4) * 0.8))
logger.info(f"Setting MAX_WORKERS to {MAX_WORKERS} (80% of CPU)")

def save_to_postgresql(articles, db_config=None):
    """기사들을 저장한다. 커넥션은 공유 풀에서 빌린다."""
    if not articles:
        return
    try:
        with get_sync_pool().connection() as conn:
            with conn.cursor() as cur:
                today_yyyymmdd = service_date()

                for art in articles:
                    # url 유니크 제약 기반 upsert. 경쟁 조건 없이 한 번의 왕복으로 끝난다.
                    cur.execute("""
                        INSERT INTO public.news_sentiment
                            (title, url, press, date, politicians,
                             sentiment_label, sentiment_score, content, base_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (url) DO UPDATE SET
                            title = EXCLUDED.title,
                            press = EXCLUDED.press,
                            date = EXCLUDED.date,
                            politicians = EXCLUDED.politicians,
                            sentiment_label = EXCLUDED.sentiment_label,
                            sentiment_score = EXCLUDED.sentiment_score,
                            content = EXCLUDED.content,
                            base_date = EXCLUDED.base_date,
                            inserted_at = CURRENT_TIMESTAMP
                    """, (
                        art['title'], art['url'], art['press'], art['date'],
                        ",".join(art.get('politicians', [])), art.get('sentiment_label', ""),
                        art.get('sentiment_score', 0.0), art.get('content', ""), today_yyyymmdd
                    ))
    except Exception as e:
        logger.error(f"[DB 저장 중 오류] {e}")

def wake_api(timeout: int = 180) -> bool:
    """슬립 중인 무료 인스턴스를 깨우고 준비될 때까지 기다린다.

    Render 무료 플랜은 15분 무트래픽이면 잠들고 재기동에 약 1분 걸린다.
    크롤러는 새벽에 도므로 서버는 거의 항상 자고 있다. 워밍업 없이 바로
    POST 하면 첫 요청들이 타임아웃으로 버려져 관계가 조용히 유실된다.
    """
    health = api_base_url() + "/health"
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            res = requests.get(health, timeout=30)
            if res.status_code == 200:
                logger.info(f"API 준비 완료 (시도 {attempt}회): {health}")
                return True
            logger.info(f"API 응답 {res.status_code}, 재시도")
        except requests.RequestException as e:
            logger.info(f"API 기동 대기 중 ({type(e).__name__})...")
        time.sleep(5)
    logger.error(f"{timeout}초 안에 API 를 깨우지 못했습니다: {health}")
    return False


def save_observations(art):
    """기사 하나가 만든 관계 판정을 근거 로그에 쌓고, 건드린 쌍을 돌려준다.

    예전에는 여기서 곧바로 /api/edge 로 엣지를 밀어 넣었다. 그러면 엣지가
    "마지막에 처리된 기사" 하나로 덮여, 몇 건의 기사가 어느 언론사에서
    나왔는지가 남지 않았다. 이제 기사는 근거만 남기고, 엣지는 파이프라인
    끝에서 쌍별로 집계해 한 번만 쓴다.
    """
    rels = art.get('relationships') or []
    if not rels:
        return []

    # 본문 지문. 통신사 전재 기사를 한 사건으로 묶는 데 쓴다.
    body_hash = relation_evidence.simhash(art.get('content', ''))
    # 나열 기사에서 뽑은 쌍은 그 기사의 주제가 아닐 확률이 높다.
    weight = focus_weight(len(art.get('politicians') or []))

    rows = []
    for rel in rels:
        # holder/target 은 이 기사가 판단한 방향이다. 발화 주체를 가릴 수
        # 없으면(상호 공방이거나 근거가 약하면) 비어 있다.
        direction = rel.get('direction')
        rows.append({
            "entity_a": rel['entity_a'],
            "entity_b": rel['entity_b'],
            "polarity": 1 if rel['type'] == relation_evidence.POSITIVE else -1,
            "score": rel['score'],
            "focus_weight": weight,
            "stance_weight": rel.get('stance_weight', 1.0),
            "holder": rel.get('holder') if direction != 'mutual' else None,
            "target": rel.get('target') if direction != 'mutual' else None,
            "evidence_type": rel.get('evidence_type'),
            "hedged": rel.get('hedged', False),
            "press": art.get('press'),
            "url": art['url'],
            "title": art.get('title'),
            "article_date": art.get('date'),
            "simhash": body_hash,
            "evidence": rel.get('evidence', ""),
        })

    try:
        relation_evidence.record_observations(rows)
    except Exception as e:
        logger.error(f"[근거 저장 실패] {art.get('url')} -> {e}")
        return []
    return [relation_evidence.pair_key(r['entity_a'], r['entity_b']) for r in rows]


def push_aggregated_edges(pair_keys):
    """쌍별로 근거를 집계해 엣지를 한 번씩만 쓴다.

    기사마다 POST 하던 것을 쌍마다 POST 로 바꾼다. 호출 수가 줄고, 무엇보다
    엣지에 실리는 값이 기사 한 건이 아니라 관측 전체의 집계가 된다.

    본체는 core/relation_evidence.py 에 있다. 소급 이관 스크립트가 NLI
    모델을 띄우지 않고도 같은 일을 할 수 있어야 하기 때문이다.
    """
    return relation_evidence.publish_edges(pair_keys)

def crawl_custom_news_list(date_str, sid1="100", max_pages=1):
    base_url = "https://news.naver.com/main/list.naver?mode=LSD&mid=sec"
    articles = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        page = context.new_page()
        for page_num in range(1, max_pages + 1):
            target_url = f"{base_url}&sid1={sid1}&date={date_str}&page={page_num}"
            try:
                page.goto(target_url, timeout=30000)
                if not page.query_selector(".list_body"): break
                items = page.query_selector_all(".list_body ul li")
                for item in items:
                    link_el = item.query_selector("dt:not(.photo) a") or item.query_selector("a")
                    if not link_el: continue
                    url = link_el.get_attribute("href")
                    title = link_el.inner_text().strip()
                    # 언론사를 빈 값으로 두던 자리다. 지금은 언론사가 진영
                    # 교차 검증의 입력이라, 비워 두면 그 기사에서 나온 관계가
                    # 전부 진영 미상(중도)으로 떨어진다. 실제로 이 함수가
                    # 만든 한 회차의 기사 67건이 그렇게 들어가 있었다.
                    press_el = item.query_selector("span.writing")
                    press = press_el.inner_text().strip() if press_el else ""
                    if url and title:
                        articles.append({"title": title, "url": url,
                                         "date": date_str, "press": press})
            except Exception as e:
                logger.error(f"Error crawling {target_url}: {e}")
        browser.close()
    return articles

def crawl_past_30_days(max_articles_per_day=5):
    """과거 60일간 뉴스 수집 (병렬 처리)"""
    all_articles = []
    today = now_kst()

    def crawl_single_day(day_offset):
        """단일 날짜의 뉴스 수집"""
        target_date = today - timedelta(days=day_offset)
        date_str = target_date.strftime("%Y%m%d")
        try:
            daily_news = crawl_custom_news_list(date_str, sid1="100", max_pages=1)
            if len(daily_news) > max_articles_per_day:
                daily_news = daily_news[:max_articles_per_day]
            logger.info(f"Day {day_offset} ({date_str}): {len(daily_news)} articles collected")
            return daily_news
        except Exception as e:
            logger.error(f"Failed to crawl day {day_offset} ({date_str}): {e}")
            return []

    # 병렬 처리로 60일간 데이터 수집
    logger.info("Starting parallel crawling for past 60 days...")
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(crawl_single_day, i) for i in range(60)]  # 60일
        for future in as_completed(futures):
            try:
                daily_articles = future.result()
                all_articles.extend(daily_articles)
            except Exception as e:
                logger.error(f"Error processing future: {e}")

    logger.info(f"Total articles collected from 60 days: {len(all_articles)}")
    return all_articles

def get_target_politicians(db_config, limit=50):
    """뉴스 데이터가 부족한 국회의원 선별"""
    try:
        with get_sync_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT politicians FROM public.news_sentiment")
                rows = cur.fetchall()
                counts = {}
                for row in rows:
                    if row[0]:
                        for name in row[0].split(','):
                            counts[name] = counts.get(name, 0) + 1
                sorted_politicians = sorted(POLITICIANS, key=lambda p: counts.get(p, 0))
                return sorted_politicians[:limit]
    except:
        return POLITICIANS[:limit]

# 네이버 목록 API 는 sid2 를 무시한다. 실측 결과 100-264 / 100-265 / 100-268 이
# 100% 동일한 목록을 돌려줬다. 즉 예전 설정(7개 조합)은 같은 섹션을 2~3번씩
# 중복으로 긁으면서 시간만 3배 쓰고 있었다. sid1 만 남긴다.
#
# 세계(104)·생활문화(103)도 확인했으나 의원 매칭이 0건이라 제외했다.
SECTION_CODES = {
    "Politics": "100",
    "Economy": "101",
    "Society": "102",
}

# 페이지네이션은 정상 동작한다. 실측(sid1=100): 페이지마다 새 기사 약 20건씩
# 누적되어 6페이지에 고유 기사 106건. 3페이지에서 5페이지로 늘리면
# 정치 섹션만으로 고유 기사 91건 -> 의원 매칭 15건이 나온다.
# (중복 제거로 아낀 시간을 여기에 쓴다.)
SECTION_MAX_PAGES = 5

def crawl_naver_section(sid1, max_pages=SECTION_MAX_PAGES):
    """네이버 뉴스 섹션별 크롤링 (Reverse Search)"""
    base_url = "https://news.naver.com/main/list.naver?mode=LSD&mid=sec"
    articles = []

    # 섹션 이름 찾기 (로깅용)
    section_name = "Unknown"
    for sec, code in SECTION_CODES.items():
        if code == sid1:
            section_name = f"{sec}({sid1})"
            break

    logger.info(f"[{section_name}] 섹션 크롤링 시작 (최대 {max_pages} 페이지)")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        page = context.new_page()

        for page_num in range(1, max_pages + 1):
            url = f"{base_url}&sid1={sid1}&page={page_num}"
            try:
                logger.info(f"[{section_name}] 페이지 {page_num}/{max_pages} 로드 중: {url}")
                page.goto(url, timeout=30000)
                try:
                    page.wait_for_selector(".list_body", timeout=10000)
                except:
                    logger.warning(f"[{section_name}] .list_body 요소를 찾을 수 없음 (페이지 {page_num})")
                    continue

                items = page.query_selector_all(".list_body ul li")
                logger.info(f"[{section_name}] 페이지 {page_num}: 기사 {len(items)}개 발견. 분석 시작...")

                matched_count = 0
                for item in items:
                    title_el = item.query_selector("dt:not(.photo) a") or item.query_selector("a")
                    if not title_el: continue

                    title = title_el.inner_text().strip()
                    url = title_el.get_attribute("href")
                    preview_el = item.query_selector("dd span.lede")
                    preview = preview_el.inner_text().strip() if preview_el else ""

                    found_names = extract_politicians(title + " " + preview, POLITICIANS)
                    if found_names:
                        logger.info(f"  -> [MATCH] '{found_names}' 발견: {title[:30]}...")
                        matched_count += 1
                        press_el = item.query_selector("span.writing")
                        press = press_el.inner_text().strip() if press_el else "Naver"
                        articles.append({
                            "title": title,
                            "url": url,
                            "press": press,
                            "date": now_kst().strftime("%Y-%m-%d")
                        })
                logger.info(f"[{section_name}] 페이지 {page_num} 완료: {matched_count}개 기사 매칭됨.")

            except Exception as e:
                logger.warning(f"Section crawl failed (sid1={sid1} p{page_num}): {e}")

        browser.close()

    logger.info(f"[{section_name}] 크롤링 종료. 총 {len(articles)}개 유효 기사 수집.")
    return articles

# 네이버 뉴스 검색 결과에서 기사 한 건을 뽑는 스크립트.
#
# 예전 셀렉터(a.news_tit, .info_group .press)는 네이버가 검색 화면을
# sds-comps-* 컴포넌트로 갈아엎으면서 전부 0건이 됐다. 그런데 컨테이너인
# .list_news 는 그대로 남아 있어서 wait_for_selector 는 통과했고, 항목 루프가
# `if not title_el: continue` 로 조용히 다 건너뛰었다. 예외도 경고도 없이
# 의원 296명 검색이 매일 0건을 돌려주고 있었다. 섹션 크롤링이 물어 오는
# 기사만으로 파이프라인이 돌아가고 있었던 셈이다.
#
# 그래서 이번에는 (1) 실제로 몇 건을 건졌는지 세어 0이면 경고를 남기고,
# (2) 언론사는 클래스 이름 대신 "제목 링크에서 위로 올라가며 언론사 칸을
# 가진 조상을 찾는" 방식으로 잡는다. 네이버가 클래스명을 또 바꿔도 구조가
# 유지되면 살아남는다.
_NAVER_SEARCH_EXTRACT = """() => {
  const TITLE = 'span.sds-comps-text-type-headline1';
  const PRESS = 'span.sds-comps-profile-info-title-text';
  const out = [];
  document.querySelectorAll(`a:has(${TITLE})`).forEach((a) => {
    const title = (a.querySelector(TITLE)?.innerText || '').trim();
    if (!title || !a.href) return;
    let press = '';
    let node = a;
    for (let i = 0; i < 6 && node; i++) {
      node = node.parentElement;
      const el = node && node.querySelector(PRESS);
      if (el) { press = (el.innerText || '').split('\\n')[0].trim(); break; }
    }
    out.push({ title, url: a.href, press });
  });
  return out;
}"""


def crawl_naver_news_search(keyword, max_articles=10):
    articles = []
    end_date = now_kst()
    start_date = end_date - timedelta(days=365)
    ds = start_date.strftime("%Y.%m.%d")
    de = end_date.strftime("%Y.%m.%d")
    seen = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        page = context.new_page()

        # 최대 3페이지까지 검색 수행
        for page_num in range(3):
            start_idx = (page_num * 10) + 1
            search_url = f"https://search.naver.com/search.naver?where=news&query={requests.utils.quote(keyword)}&sort=1&pd=3&ds={ds}&de={de}&start={start_idx}"

            try:
                page.goto(search_url, timeout=30000)
                page.wait_for_selector("span.sds-comps-text-type-headline1", timeout=15000)
                rows = page.evaluate(_NAVER_SEARCH_EXTRACT)

                if not rows:
                    break

                for row in rows:
                    url = row.get("url")
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    articles.append({
                        "title": row["title"],
                        "url": url,
                        # 언론사를 못 읽으면 진영을 배정할 수 없다. 빈 값으로
                        # 두면 집계가 "미상" 으로 다루고 중도로 떨어뜨린다.
                        "press": row.get("press") or "",
                        "date": now_kst().strftime("%Y-%m-%d"),
                    })
                    if len(articles) >= max_articles:
                        break

                if len(articles) >= max_articles:
                    break

            except Exception as e:
                logger.warning(f"Search crawl failed for {keyword} (page {page_num+1}): {e}")
                break

        browser.close()

    # 조용한 0건이 이 함수의 예전 실패 방식이었다. 이제는 드러낸다.
    if not articles:
        logger.warning(f"[검색 0건] '{keyword}' — 네이버 검색 마크업이 또 바뀌었는지 확인할 것")
    return articles

def crawl_cnn_search(keyword, max_articles=3):
    articles = []
    search_url = f"https://www.cnn.com/search?q={requests.utils.quote(keyword)}&sort=newest"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = context.new_page()
        try:
            logger.info(f"[CNN 수집] {keyword} 검색 시작")
            page.goto(search_url, timeout=30000)
            page.wait_for_selector(".cnn-search__result", timeout=20000)
            items = page.query_selector_all(".cnn-search__result")
            for item in items:
                title_el = item.query_selector(".cnn-search__result-headline a")
                if not title_el: continue
                title = title_el.inner_text().strip()
                url = title_el.get_attribute("href")
                if url.startswith("/"): url = "https://www.cnn.com" + url
                if url and title:
                    articles.append({"title": title, "url": url, "press": "CNN", "date": now_kst().strftime("%Y-%m-%d")})
                if len(articles) >= max_articles: break
        except Exception as e:
            logger.warning(f"CNN crawling failed: {e}")
        finally:
            browser.close()
    return articles

def crawl_bbc_search(keyword, max_articles=3):
    articles = []
    search_url = f"https://www.bbc.com/search?q={requests.utils.quote(keyword)}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = context.new_page()
        try:
            logger.info(f"[BBC 수집] {keyword} 검색 시작")
            page.goto(search_url, timeout=30000)
            page.wait_for_selector("[data-testid='card-headline'], .search-result-title", timeout=20000)
            items = page.query_selector_all("[data-testid='standard-card'], .e1f96os92")
            for item in items:
                title_el = item.query_selector("a[data-testid='card-headline'], a.e1f96os91")
                if not title_el: continue
                title = title_el.inner_text().strip()
                url = title_el.get_attribute("href")
                if url.startswith("/"): url = "https://www.bbc.com" + url
                if url and title:
                    articles.append({"title": title, "url": url, "press": "BBC", "date": now_kst().strftime("%Y-%m-%d")})
                if len(articles) >= max_articles: break
        except Exception as e:
            logger.warning(f"BBC crawling failed: {e}")
        finally:
            browser.close()
    return articles

def crawl_nhk_search(keyword, max_articles=3):
    articles = []
    search_url = f"https://www3.nhk.or.jp/nhkworld/en/news/search/?query={requests.utils.quote(keyword)}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = context.new_page()
        try:
            logger.info(f"[NHK 수집] {keyword} 검색 시작")
            page.goto(search_url, timeout=30000)
            page.wait_for_selector(".c-searchList__item, .p-searchList__item", timeout=20000)
            items = page.query_selector_all(".c-searchList__item, .p-searchList__item")
            for item in items:
                title_el = item.query_selector("a")
                if not title_el: continue
                title = title_el.inner_text().strip()
                url = title_el.get_attribute("href")
                if url.startswith("/"): url = "https://www3.nhk.or.jp" + url
                if url and title:
                    articles.append({"title": title, "url": url, "press": "NHK World", "date": now_kst().strftime("%Y-%m-%d")})
                if len(articles) >= max_articles: break
        except Exception as e:
            logger.warning(f"NHK crawling failed: {e}")
        finally:
            browser.close()
    return articles

def pair_candidates(found_names, content, limit=None):
    """쌍을 만들 이름을 추린다. 많이 언급된 이름부터 남긴다.

    이름이 n개면 쌍은 n(n-1)/2 개다. 의원 20명을 나열한 기사는 190쌍이
    되고, 쌍마다 창을 훑으며 NLI 를 부르니 기사 한 건이 회차의 남은 시간을
    다 먹는다. 이런 기사는 대개 "이번 주 법안" 같은 나열 기사이고, 관계의
    근거로도 약하다.

    등장 횟수 순으로 자르고, 남은 이름은 기사에 나온 순서를 지킨다. 순서가
    바뀌면 entity_a/entity_b 가 달라져 방향 판정이 흔들린다.
    """
    cap = RELATION_MAX_NAMES_PER_ARTICLE if limit is None else limit
    if cap <= 0 or len(found_names) <= cap:
        return list(found_names)

    ranked = sorted(found_names, key=lambda n: content.count(n), reverse=True)
    kept = set(ranked[:cap])
    dropped = [n for n in found_names if n not in kept]
    logger.info(f"[나열 기사] 이름 {len(found_names)}개 중 {cap}개만 쌍으로 본다. "
                f"제외: {', '.join(dropped[:8])}{' ...' if len(dropped) > 8 else ''}")
    return [n for n in found_names if n in kept]


def process_article(art, db_config, seen_titles, seen_contents, deadline=None):
    try:
        # 예산을 넘겼으면 손대지 않고 돌려보낸다. 큐에 남은 future 는
        # run_pipeline 이 cancel() 하지만, 이미 워커가 집어간 건은 취소가
        # 안 되므로 여기서 한 번 더 본다.
        if deadline is not None and time.time() > deadline:
            return None

        # 같은 제목/본문이 여러 URL 로 들어오는 것을 여기서 한 번 걸러낸다.
        # 예전에는 검사만 하고 집합에 넣지 않아 이 두 줄이 아무 일도 하지
        # 않았다. 통신사 전재 기사가 그대로 통과해 분석 비용을 반복해서
        # 썼다. 남은 전재는 근거 집계 단계에서 SimHash 로 한 사건으로 묶인다.
        title_hash = hashlib.md5(art['title'].encode('utf-8')).hexdigest()
        if title_hash in seen_titles: return None
        seen_titles.add(title_hash)

        content = get_article_text(art['url'])
        if len(content) < 150: return None

        content_hash = hashlib.md5(content[:500].encode('utf-8')).hexdigest()
        if content_hash in seen_contents: return None
        seen_contents.add(content_hash)

        found_names = extract_politicians(content, POLITICIANS)
        if not found_names: return None

        nli = get_analyzer() if len(found_names) >= 2 else None
        if nli is not None:
            relationships = []
            pair_names = pair_candidates(found_names, content)
            pairs_seen = 0
            analysis_began = time.time()
            for i in range(len(pair_names)):
                for j in range(i+1, len(pair_names)):
                    # 예산은 쌍 사이에서 본다.
                    #
                    # 예전에는 기사를 집어들 때 한 번만 봤다. 그래서 한 번
                    # 시작한 기사는 몇 분이 걸리든 끝까지 돌았고, 그걸
                    # 기다리는 동안 회차가 러너 한도에 걸려 죽었다. 여기서
                    # 빠져나오면 이미 판정한 쌍은 그대로 저장된다.
                    if deadline is not None and time.time() > deadline:
                        logger.warning(
                            f"[시간 예산 초과] 분석을 중간에 끊는다: "
                            f"{art['title'][:25]}... (쌍 {pairs_seen}개까지)")
                        break
                    p1, p2 = pair_names[i], pair_names[j]
                    pairs_seen += 1
                    try:
                        # found_names 를 함께 넘긴다. 창 안에서 이름을 다시
                        # 확인할 때 더 긴 이름(김윤덕)을 알아야 짧은 이름
                        # (김윤)의 오탐을 막을 수 있다. 쌍은 추려도 이름
                        # 확인은 기사에 나온 전체를 써야 한다.
                        result = nli.analyze_pair(content, p1, p2, found_names)
                        if result:
                            relationships.append({
                                "entity_a": p1, "entity_b": p2, **result,
                            })
                    except: continue
                else:
                    continue
                break
            art['relationships'] = relationships

            elapsed = time.time() - analysis_began
            if elapsed > NEWS_SLOW_ARTICLE_SEC:
                logger.info(
                    f"[느린 기사] {elapsed:.0f}초 - 이름 {len(found_names)}개"
                    f"(쌍 대상 {len(pair_names)}개, 판정 {pairs_seen}쌍) "
                    f"{art['title'][:25]}...")

        art['content'] = content
        art['politicians'] = found_names
        # 회차가 정한 날짜를 쓴다. 기사마다 now() 를 찍으면 자정(UTC)을 넘긴
        # 회차에서 기사는 다음 날로, 화제성 산출은 전날로 갈라진다.
        art.setdefault('base_date', service_date())

        save_to_postgresql([art], db_config)
        pairs = save_observations(art)

        return art['title'], pairs
    except Exception as e:
        logger.error(f"Error processing {art.get('title', 'Unknown')}: {e}")
        return None

def collect_all_sources_for_name(name, deadline=None):
    """특정 의원에 대한 다국어/다양한 소스 수집"""
    if deadline is not None and time.time() > deadline:
        return []

    results = []
    try:
        # 검색어 다양화 및 수집 개수 증가 (2 -> 10)
        results.extend(crawl_naver_news_search(f"{name} 의원", max_articles=5))
        results.extend(crawl_naver_news_search(f"{name} 국회", max_articles=5)) # 총 10개
    except: pass

    # intl_keyword = f"{name} South Korea"
    # try:
    #     results.extend(crawl_cnn_search(intl_keyword, max_articles=1))
    #     results.extend(crawl_bbc_search(intl_keyword, max_articles=1))
    #     results.extend(crawl_nhk_search(intl_keyword, max_articles=1))
    # except: pass

    if results:
        logger.info(f"[Keywords] '{name}' 수집 완료: {len(results)}건")

    return results

def collect_news(collect_deadline=None):
    """1~4단계. 수집하고, 중복을 걷어내고, 상한까지 자른 기사 목록을 돌려준다.

    DB 에도 API 에도 쓰지 않는다. 그래서 수집만 따로 돌리는 러너는 비밀값
    없이도 돈다.
    """
    started = time.time()

    # 1. 대상 선정 (전체 의원 수집)
    target_names = POLITICIANS
    logger.info(f"이번 회차 타겟 수집 대상: 전체 {len(target_names)}명 병렬 수집 시작")

    # 2. 뉴스 소스 수집 (병렬 - 키워드 검색 + 섹션 스캔)
    news_pool = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as collection_executor:
        futures = {}

        # A. 섹션별 크롤링 (Reverse Search) - 우선 순위 높음
        logger.info("[섹션별 뉴스 수집 시작] 정치, 경제, 사회 분야 스캔...")
        for section, sid1 in SECTION_CODES.items():
            futures[collection_executor.submit(crawl_naver_section, sid1)] = f"Section: {section} ({sid1})"

        # B. 개별 의원 키워드 검색
        logger.info("[개별 의원 키워드 검색 작업 등록 중...]")
        for name in target_names:
             futures[collection_executor.submit(collect_all_sources_for_name, name, collect_deadline)] = f"Keyword: {name}"

        total_tasks = len(futures)
        completed_tasks = 0
        for future in as_completed(futures):
            completed_tasks += 1
            task_info = futures[future]
            try:
                res = future.result()
                if res: news_pool.extend(res)
                # 10회마다 또는 마지막에 진행률 출력
                if completed_tasks % 10 == 0 or completed_tasks == total_tasks:
                    logger.info(f"[{completed_tasks}/{total_tasks}] 뉴스 수집 진행 중... ({task_info})")
            except Exception as e:
                logger.error(f"Collection error ({task_info}): {e}")

    if collect_deadline is not None and time.time() > collect_deadline:
        logger.warning(f"[수집 예산 초과] {time.time() - started:.0f}초 사용. "
                       "일부 의원의 검색을 건너뛰었습니다.")

    # 3. 중복 제거
    #
    # 주소가 같은 기사, 그리고 제목이 같은 기사를 뺀다. 제목 검사는 원래
    # 분석 워커 안에서만 했다. 분석을 러너 여러 대로 나누면 워커끼리 제목
    # 집합을 나눠 갖지 못하므로, 나누기 전인 여기서 한 번 걸러야 같은 기사를
    # 두 러너가 따로 분석하지 않는다.
    unique_news = []
    seen_urls = set()
    seen_titles = set()
    for n in news_pool:
        title_hash = hashlib.md5((n.get('title') or '').encode('utf-8')).hexdigest()
        if n['url'] in seen_urls or title_hash in seen_titles:
            continue
        unique_news.append(n)
        seen_urls.add(n['url'])
        seen_titles.add(title_hash)

    # 4. 분석량 상한
    #
    # 의원별 검색이 고쳐지기 전에는 기사가 하루 30건 안팎이라 상한이 필요
    # 없었다. 이제 296명 검색이 실제로 결과를 물어 오므로 수백 건이 된다.
    # 기사 한 건은 본문 내려받기 + 등장 의원 쌍마다 NLI 4회라, 그냥 두면
    # 한 회차가 끝없이 길어진다.
    #
    # 이 상한만으로는 시간을 못 막는다. 기사 한 건의 비용이 본문 길이와
    # 등장 의원 수에 따라 크게 달라지기 때문이다. 예전 주석에는 "37건에
    # 6분이니 300건이면 약 50분" 이라고 적혀 있었는데, 실제 2026-09-09
    # 회차는 300건 중 140건을 처리하는 데 76분을 썼다(스레드 8개). 시간은
    # NEWS_TIME_BUDGET_SEC 가 재고, 이 값은 한 회차가 손댈 기사 수만 정한다.
    collected = len(unique_news)
    if len(unique_news) > NEWS_MAX_ARTICLES:
        unique_news = unique_news[:NEWS_MAX_ARTICLES]
    logger.info(f"분석 대상 기사 총합: {len(unique_news)}개 "
                f"(수집 {collected}개, 상한 {NEWS_MAX_ARTICLES}, {time.time() - started:.0f}초)")
    return unique_news


def analyze_articles(articles, db_config, deadline, base_date=None):
    """5단계. 기사를 분석해 저장하고 (저장 수, 건드린 쌍 키) 를 돌려준다."""
    unique_news = articles
    if base_date:
        for art in unique_news:
            art['base_date'] = base_date

    # 5. 분석 및 저장 (병렬)
    #
    # 예산을 넘기면 남은 기사를 버리고 빠져나온다. 끝까지 도는 것보다
    # 6·7 단계(엣지 집계, 화제성)에 도달하는 것이 중요하다. 여기서 잘리면
    # 그날 저장한 기사가 화면에 한 건도 안 나가기 때문이다.
    processed_count = 0
    total_saved = 0
    seen_titles = set()
    seen_contents = set()
    touched_pairs = []
    analysis_started = time.time()
    out_of_time = False

    # with 문을 쓰지 않는다. 블록을 빠져나갈 때 shutdown(wait=True) 이
    # 걸려, 돌고 있는 워커가 끝날 때까지 여기서 붙잡힌다. 2026-09-13 회차는
    # 그 상태로 열 분을 서 있다가 러너에게 죽었다. 예산을 넘기면 기다리지
    # 않고 집계로 넘어가야 한다.
    analysis_executor = ThreadPoolExecutor(max_workers=8)
    future_to_art = {
        analysis_executor.submit(process_article, art, db_config,
                                 seen_titles, seen_contents, deadline): art
        for art in unique_news
    }
    try:
        # 전체 대기 시간을 예산 + 유예로 묶는다. 예산을 넘긴 뒤에도 유예
        # 동안 돌아오는 결과는 집계에 넣고, 그 뒤로는 두고 간다.
        wait_left = max(1.0, deadline + NEWS_FINISH_GRACE_SEC - time.time())
        for future in as_completed(future_to_art, timeout=wait_left):
            if future.cancelled():
                continue
            try:
                result = future.result()
                processed_count += 1
                if result:
                    title, pairs = result
                    touched_pairs.extend(pairs)
                    total_saved += 1
                    logger.info(f"[{total_saved}/{len(unique_news)}] 업데이트/저장 완료: {title[:30]}...")
            except CancelledError:
                continue
            except Exception as e:
                logger.error(f"Error processing article: {e}")

            if not out_of_time and time.time() > deadline:
                out_of_time = True
                # cancel() 은 아직 시작하지 않은 것만 취소한다. 이미 워커가
                # 집어간 건은 스스로 빠져나오게 두고(process_article 이 쌍
                # 사이에서 예산을 본다), 몇 건이 그런 상태인지 남긴다.
                # 예전에는 취소된 개수만 찍어서, 300건이 다 시작된 회차에서
                # "남은 기사 0건" 이라고만 적고 그대로 멈춰 있었다.
                queued = sum(1 for f in future_to_art if f.cancel())
                running = sum(1 for f in future_to_art if f.running())
                logger.warning(
                    f"[시간 예산 초과] {NEWS_TIME_BUDGET_SEC // 60}분을 넘겼다. "
                    f"대기 {queued}건은 다음 회차로 넘기고, 돌고 있는 {running}건은 "
                    f"최대 {NEWS_FINISH_GRACE_SEC}초만 기다린다. "
                    "집계와 화제성은 그대로 진행한다.")
    except TimeoutError:
        # concurrent.futures.TimeoutError 는 3.11 부터 내장 TimeoutError 다.
        running = sum(1 for f in future_to_art if f.running())
        logger.warning(f"[마무리] 아직 돌고 있는 {running}건을 두고 집계로 넘어간다.")
    finally:
        # wait=False 로 지금 바로 돌려받는다. 파이썬이 인터프리터 종료 때
        # 워커를 한 번 더 join 하지만, 그때는 집계와 화제성이 이미 끝나 있다.
        analysis_executor.shutdown(wait=False, cancel_futures=True)

    logger.info(f"[파이프라인 실행 종료] 총 {total_saved}개 기사 처리됨 "
                f"(검토 {processed_count}건, 분석 {time.time() - analysis_started:.0f}초)")

    return total_saved, touched_pairs


def finish_run(touched_pairs, base_date=None, since=None):
    """6~7단계. 쌍별로 근거를 집계해 엣지를 쓰고, 화제성을 산출한다.

    since 를 주면 그 뒤에 적재된 관측의 쌍도 함께 집계한다. 분석 러너가
    한도에 걸려 쌍 목록을 넘기지 못해도, 죽기 전까지 저장한 근거는 반영된다.
    """
    pairs = set(touched_pairs or [])
    if since is not None:
        try:
            recovered = set(relation_evidence.pair_keys_observed_since(since)) - pairs
            if recovered:
                logger.info(f"[관계 집계] 넘겨받지 못한 쌍 {len(recovered)}개를 DB 에서 찾아 더한다")
            pairs |= recovered
        except Exception as e:
            logger.error(f"[관계 집계] since 이후 관측을 읽지 못해 넘겨받은 쌍만 집계한다: {e}")

    # 6. 관계 집계. 기사 단위 판정을 쌍 단위로 모아 엣지를 다시 쓴다.
    #
    # 이 단계가 없으면 엣지는 마지막 기사 하나로 덮인다. 여기서 통신사
    # 전재를 한 사건으로 묶고(SimHash), 진영이 다른 매체가 같은 극성을
    # 보도했는지 세고(교차 검증), 오래된 근거의 무게를 줄인다(반감기).
    if pairs:
        # 분석에 한 시간 넘게 걸리는 회차가 있다. Render 무료 인스턴스는
        # 15분 무트래픽이면 잠들므로, 시작할 때 깨워 둔 것과 무관하게 지금
        # 다시 자고 있다. 여기서 안 깨우면 첫 POST 들이 타임아웃으로 버려져
        # 그날 관계가 조용히 유실된다.
        wake_api()
        saved, total = push_aggregated_edges(sorted(pairs))
        logger.info(f"[관계 집계] 쌍 {len(pairs)}개 중 {total}개 승격, {saved}개 저장")

    # 수집한 뉴스로 화제성을 산출한다. X/인스타는 비로그인 수집이 막혔고
    # 유튜브도 불안정해 화제성 테이블이 계속 비어 있었다. 뉴스 언급 빈도는
    # 이미 안정적으로 수집되는 데이터이고 정치적 화제성의 직접적인 신호다.
    try:
        rebuild_from_news(base_date or service_date())
    except Exception as e:
        logger.error(f"화제성 산출 실패: {e}")

    logger.info("--------------------------------------------------")


def select_shard(articles, shard, shards):
    """shards 대 중 shard 번째가 맡을 기사. 순서로 나누므로 매번 같게 갈린다."""
    if shards < 1 or not 0 <= shard < shards:
        raise ValueError(f"잘못된 샤드 지정: {shard}/{shards}")
    return [art for i, art in enumerate(articles) if i % shards == shard]


def run_pipeline(db_config):
    """한 프로세스에서 수집부터 마무리까지 전부 돈다. 로컬과 도커용이다.

    GitHub Actions 는 단계를 러너 여러 대로 나눠 돈다(.github/workflows/crawl.yml).
    """
    logger.info("--------------------------------------------------")
    logger.info(f"[파이프라인 실행 시작] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 이 회차에 쓸 수 있는 시간. 러너가 잘라내기 전에 우리가 먼저 멈춘다.
    budget_started = time.time()
    deadline = budget_started + NEWS_TIME_BUDGET_SEC
    collect_deadline = min(deadline, budget_started + NEWS_COLLECT_BUDGET_SEC)
    base_date = service_date()
    logger.info(f"[시간 예산] 수집 {NEWS_COLLECT_BUDGET_SEC // 60}분 / "
                f"전체 {NEWS_TIME_BUDGET_SEC // 60}분")

    articles = collect_news(collect_deadline)
    total_saved, touched_pairs = analyze_articles(articles, db_config, deadline, base_date)
    finish_run(touched_pairs, base_date)
    return total_saved

# --- 단계별 실행 -------------------------------------------------------------
#
# GitHub Actions 러너 한 대(vCPU 4개)로는 뉴스가 많은 날의 NLI 계산을 90분
# 안에 끝내지 못한다. 2026-09-15, 09-16 두 회차는 모두 예산에 걸려 300건 중
# 215건, 176건만 분석했다. 러너가 느려서가 아니었다(둘 다 AMD EPYC, AVX-512).
# 실제 창 길이(약 230토큰)에서 NLI 한 번이 코어 하나로 0.6초이고, 창 하나에
# 4번, 쌍 하나에 창 최대 8개, 기사 하나에 쌍 최대 66개를 부르기 때문이다.
#
# 그래서 수집은 한 번, 분석은 러너 여러 대에 나눠, 마무리는 다시 한 번
# 돈다. 러너 사이에는 JSON 파일(Actions 아티팩트)만 오간다.
#
#   collect  --out articles.json                         기사 목록 (DB 안 씀)
#   analyze  --articles articles.json --shard i --shards n --out pairs-i.json
#   finish   --pairs-dir DIR --base-date YYYYMMDD --since ISO8601
#
# 인자 없이 부르면 예전처럼 한 프로세스에서 전부 돈다(로컬, 도커, run_news_sns.py).

#: finish 가 since 뒤의 관측을 찾을 때 두는 여유. since 는 러너 시계, observed_at
#: 은 DB 시계라 조금 어긋날 수 있다. 쌍이 몇 개 더 잡혀도 집계는 같은 결과다.
SINCE_MARGIN = timedelta(minutes=10)


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _github_output(**values):
    """Actions 의 다음 잡이 읽을 값을 남긴다. Actions 밖에서는 아무 일도 안 한다."""
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as f:
        for key, value in values.items():
            f.write(f"{key}={value}\n")


def cli_collect(args):
    started = datetime.now(timezone.utc)
    base_date = service_date()
    budget_started = time.time()
    logger.info(f"[수집] 예산 {NEWS_COLLECT_BUDGET_SEC // 60}분")

    articles = collect_news(budget_started + NEWS_COLLECT_BUDGET_SEC)
    _write_json(args.out, {"base_date": base_date, "collected_at": started.isoformat(),
                           "articles": articles})
    _github_output(base_date=base_date, since=started.isoformat(), articles=len(articles))

    if not articles:
        # 조용한 0 은 예외보다 나쁘다. 네이버 마크업이 바뀌면 이렇게 보인다.
        logger.error("[수집 0건] 분석할 기사가 없다. 수집기가 고장 났을 가능성이 크다.")
        return 1
    return 0


def cli_analyze(args):
    payload = _read_json(args.articles)
    articles = select_shard(payload["articles"], args.shard, args.shards)
    deadline = time.time() + NEWS_TIME_BUDGET_SEC
    logger.info(f"[분석 {args.shard + 1}/{args.shards}] 기사 {len(articles)}건 "
                f"(전체 {len(payload['articles'])}건), 예산 {NEWS_TIME_BUDGET_SEC // 60}분")

    ensure_news_schema()
    relation_evidence.ensure_schema()
    saved, pairs = analyze_articles(articles, db_config_from_env(), deadline,
                                    payload.get("base_date"))
    _write_json(args.out, {"shard": args.shard, "shards": args.shards,
                           "base_date": payload.get("base_date"),
                           "analyzed": len(articles), "saved": saved,
                           "pairs": sorted(set(pairs))})
    return 0


def cli_finish(args):
    pairs, reports = [], []
    pairs_dir = Path(args.pairs_dir)
    for path in sorted(pairs_dir.glob("pairs-*.json")) if pairs_dir.is_dir() else []:
        report = _read_json(path)
        reports.append(report)
        pairs.extend(report.get("pairs") or [])

    expected = args.shards
    got = sorted(r["shard"] for r in reports)
    logger.info(f"[마무리] 분석 결과 {len(reports)}/{expected}개, 저장 "
                f"{sum(r.get('saved', 0) for r in reports)}건, 쌍 {len(set(pairs))}개")
    if expected and len(reports) < expected:
        missing = sorted(set(range(expected)) - set(got))
        logger.warning(f"[마무리] 결과를 넘기지 못한 분석 러너: {missing}. "
                       "그 러너가 저장한 근거는 DB 에서 찾아 집계한다.")

    base_date = args.base_date or next((r["base_date"] for r in reports if r.get("base_date")), None)
    since = datetime.fromisoformat(args.since) - SINCE_MARGIN if args.since else None

    ensure_news_schema()
    relation_evidence.ensure_schema()
    finish_run(pairs, base_date, since)
    return 0


def cli_full(args):
    # 무료 인스턴스는 자고 있다. 먼저 깨워야 관계 저장이 유실되지 않는다.
    ensure_news_schema()
    relation_evidence.ensure_schema()
    if not wake_api():
        logger.warning("API 를 깨우지 못했습니다. 관계 저장은 실패할 수 있으나 "
                       "뉴스 수집/감성분석은 계속 진행합니다.")
    run_pipeline(db_config_from_env())
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="뉴스 수집·관계 분석 파이프라인")
    stages = parser.add_subparsers(dest="stage")

    collect = stages.add_parser("collect", help="기사 목록만 모은다")
    collect.add_argument("--out", required=True)

    analyze = stages.add_parser("analyze", help="기사 목록의 일부를 분석해 저장한다")
    analyze.add_argument("--articles", required=True)
    analyze.add_argument("--shard", type=int, required=True)
    analyze.add_argument("--shards", type=int, required=True)
    analyze.add_argument("--out", required=True)

    finish = stages.add_parser("finish", help="관계를 집계하고 화제성을 산출한다")
    finish.add_argument("--pairs-dir", required=True)
    finish.add_argument("--shards", type=int, default=0, help="기대하는 분석 결과 수")
    finish.add_argument("--base-date")
    finish.add_argument("--since", help="collect 가 시작한 시각(ISO 8601)")
    return parser


if __name__ == "__main__":
    # 이 스크립트는 1회 실행이다. 반복 스케줄링은 상위(run_news_sns.py 또는
    # GitHub Actions cron)가 담당한다. 예전에는 마지막에 60분 sleep 이 있어
    # Actions job 이 수집을 끝내고도 잠들어 timeout 으로 취소됐다.
    args = build_parser().parse_args()
    handler = {"collect": cli_collect, "analyze": cli_analyze,
               "finish": cli_finish}.get(args.stage, cli_full)

    logger.info(f"=== Autonomous Political Analysis Service v1.0 ({args.stage or 'full'}) ===")

    exit_code = 0
    try:
        exit_code = handler(args)
    except Exception as e:
        logger.error(f"Pipeline critical error in single run: {e}")
        logger.error(traceback.format_exc())
        exit_code = 1
    finally:
        close_sync_pool()
        logging.shutdown()

    # 분석 워커가 아직 돌고 있으면 파이썬은 종료할 때 그 스레드를 join 한다.
    #
    # 여기까지 왔다면 저장은 워커 안에서 커밋됐고 결과 파일도 썼다(analyze),
    # 또는 집계와 화제성이 끝났다(full). 남은 워커를 기다려서 얻을 것은 없고,
    # 러너 한도에 걸려 실패로 남을 위험만 있다. 로그도 방금 내려썼으므로,
    # 남은 스레드가 있으면 여기서 끊는다.
    if threading.active_count() > 1:
        os._exit(exit_code)

    sys.exit(exit_code)
