from dotenv import load_dotenv
import os
import time
import hashlib
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from newspaper import Article
import sys
import psycopg
from core.name_matcher import find_names
from core.db_config import (api_base_url, close_sync_pool,
                            db_config_from_env, env, get_sync_pool)
import logging
import traceback
import json
from crawlers.affective_analysis import AffectiveAnalyzer
from core.dcp_algorithm import DCPCalculator
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

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

# Initialize Core Services
try:
    analyzer = AffectiveAnalyzer()
    logger.info("AffectiveAnalyzer 초기화 성공")
except Exception as e:
    logger.error(f"Failed to initialize AffectiveAnalyzer: {e}")
    analyzer = None

dcp_calc = DCPCalculator()
logger.info("DCPCalculator 초기화 성공")

def get_article_text(url):
    try:
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

# CPU 코어의 80%를 사용하여 병렬 처리 수 결정
MAX_WORKERS = max(1, int((os.cpu_count() or 4) * 0.8))
logger.info(f"Setting MAX_WORKERS to {MAX_WORKERS} (80% of CPU)")

def ensure_news_schema(db_config=None):
    """news_sentiment 스키마를 준비한다. 파이프라인 시작 시 한 번만 부른다.

    예전에는 save_to_postgresql 안에 DDL 이 있어 기사 한 건마다 CREATE TABLE /
    CREATE INDEX 가 실행됐다. 분석 스레드 8개가 동시에 치면 카탈로그 잠금
    경합이 생기고, 관리형 DB 에서는 커넥션 한도까지 겹친다.
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


def save_to_postgresql(articles, db_config=None):
    """기사들을 저장한다. 커넥션은 공유 풀에서 빌린다."""
    if not articles:
        return
    try:
        with get_sync_pool().connection() as conn:
            with conn.cursor() as cur:
                today_yyyymmdd = datetime.now().strftime('%Y%m%d')

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


def save_to_turingdb(results):
    # 배포 환경(GitHub Actions 등)에서는 API_BASE_URL 로 백엔드 주소를 지정한다.
    api_url = api_base_url() + "/api/edge"
    # 쓰기 엔드포인트는 인증을 요구한다.
    headers = {}
    write_token = env("API_WRITE_TOKEN")
    if write_token:
        headers["X-API-Key"] = write_token
    count = 0
    for art in results:
        if 'relationships' not in art: continue
        for rel in art['relationships']:
            try:
                payload = {
                    "source": rel['entity_a'],
                    "target": rel['entity_b'],
                    "type": rel['type'],
                    "properties": {
                        "score": rel['score'],
                        "social_impact_score": rel.get('social_impact_score', 0.0),
                        "evidence": rel.get('evidence', "")[:200],
                        "url": art['url'],
                        "date": art['date']
                    }
                }
                # 타임아웃이 없으면 슬립 중인 무료 인스턴스를 깨우는 동안
                # 무한 대기할 수 있다.
                response = requests.post(api_url, json=payload,
                                         headers=headers, timeout=60)
                if response.status_code == 200: count += 1
            except Exception as e:
                logger.error(f"Error saving to TuringDB: {e}")
    return count

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
                    if url and title:
                        articles.append({"title": title, "url": url, "date": date_str, "press": ""})
            except Exception as e:
                logger.error(f"Error crawling {target_url}: {e}")
        browser.close()
    return articles

def crawl_past_30_days(max_articles_per_day=5):
    """과거 60일간 뉴스 수집 (병렬 처리)"""
    all_articles = []
    today = datetime.now()

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
                            "date": datetime.now().strftime("%Y-%m-%d")
                        })
                logger.info(f"[{section_name}] 페이지 {page_num} 완료: {matched_count}개 기사 매칭됨.")

            except Exception as e:
                logger.warning(f"Section crawl failed (sid1={sid1} p{page_num}): {e}")

        browser.close()

    logger.info(f"[{section_name}] 크롤링 종료. 총 {len(articles)}개 유효 기사 수집.")
    return articles

def crawl_naver_news_search(keyword, max_articles=10):
    articles = []
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    ds = start_date.strftime("%Y.%m.%d")
    de = end_date.strftime("%Y.%m.%d")

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
                page.wait_for_selector(".list_news, .news_list", timeout=15000)
                items = page.query_selector_all("li.bx, div.news_area")

                if not items: break

                for item in items:
                    title_el = item.query_selector("a.news_tit, a.tit")
                    if not title_el: continue
                    title = title_el.inner_text().strip()
                    url = title_el.get_attribute("href")
                    press = item.query_selector(".info_group .press, .info.press").inner_text().strip() if item.query_selector(".info_group .press, .info.press") else "Naver"

                    if url and title and not any(a['url'] == url for a in articles):
                        articles.append({"title": title, "url": url, "press": press, "date": datetime.now().strftime("%Y-%m-%d")})

                    if len(articles) >= max_articles: break

                if len(articles) >= max_articles: break

            except Exception as e:
                logger.warning(f"Search crawl failed for {keyword} (page {page_num+1}): {e}")
                break

        browser.close()
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
                    articles.append({"title": title, "url": url, "press": "CNN", "date": datetime.now().strftime("%Y-%m-%d")})
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
                    articles.append({"title": title, "url": url, "press": "BBC", "date": datetime.now().strftime("%Y-%m-%d")})
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
                    articles.append({"title": title, "url": url, "press": "NHK World", "date": datetime.now().strftime("%Y-%m-%d")})
                if len(articles) >= max_articles: break
        except Exception as e:
            logger.warning(f"NHK crawling failed: {e}")
        finally:
            browser.close()
    return articles

def process_article(art, db_config, seen_titles, seen_contents):
    try:
        title_hash = hashlib.md5(art['title'].encode('utf-8')).hexdigest()
        if title_hash in seen_titles: return None

        content = get_article_text(art['url'])
        if len(content) < 150: return None

        content_hash = hashlib.md5(content[:500].encode('utf-8')).hexdigest()
        if content_hash in seen_contents: return None

        found_names = extract_politicians(content, POLITICIANS)
        if not found_names: return None

        if len(found_names) >= 2:
            relationships = []
            for i in range(len(found_names)):
                for j in range(i+1, len(found_names)):
                    p1, p2 = found_names[i], found_names[j]
                    try:
                        rtype, score, evidence = analyzer.analyze_relationship(content, p1, p2)
                        if rtype:
                            fscore = dcp_calc.calculate_impact_score(p1, p2, rtype, score)
                            relationships.append({"entity_a": p1, "entity_b": p2, "type": rtype, "score": score, "social_impact_score": fscore, "evidence": evidence})
                    except: continue
            art['relationships'] = relationships

        art['content'] = content
        art['politicians'] = found_names
        art['base_date'] = datetime.now().strftime('%Y%m%d')

        save_to_postgresql([art], db_config)
        save_to_turingdb([art])

        return art['title']
    except Exception as e:
        logger.error(f"Error processing {art.get('title', 'Unknown')}: {e}")
        return None

def collect_all_sources_for_name(name):
    """특정 의원에 대한 다국어/다양한 소스 수집"""
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

def run_pipeline(db_config):
    logger.info("--------------------------------------------------")
    logger.info(f"[파이프라인 실행 시작] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. 대상 선정 (전체 의원 수집)
    # target_names = get_target_politicians(db_config, limit=20)
    target_names = POLITICIANS
    logger.info(f"이번 회차 타겟 수집 대상: 전체 {len(target_names)}명 병렬 수집 시작")

    # 2. 뉴스 소스 수집 (병렬 - 키워드 검색 + 섹션 스캔)
    news_pool = []
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
             futures[collection_executor.submit(collect_all_sources_for_name, name)] = f"Keyword: {name}"

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

    # 3. 중복 제거
    unique_news = []
    seen_urls = set()
    for n in news_pool:
        if n['url'] not in seen_urls:
            unique_news.append(n)
            seen_urls.add(n['url'])
    logger.info(f"분석 대상 기사 총합: {len(unique_news)}개")

    # 5. 분석 및 저장 (병렬)
    processed_count = 0
    total_saved = 0
    seen_titles = set()
    seen_contents = set()

    with ThreadPoolExecutor(max_workers=8) as analysis_executor:
        future_to_art = {analysis_executor.submit(process_article, art, db_config, seen_titles, seen_contents): art for art in unique_news}
        for future in as_completed(future_to_art):
            try:
                result = future.result()
                processed_count += 1
                if result:
                    total_saved += 1
                    logger.info(f"[{total_saved}/{len(unique_news)}] 업데이트/저장 완료: {result[:30]}...")
            except Exception as e:
                logger.error(f"Error processing article: {e}")

    logger.info(f"[파이프라인 실행 종료] 총 {total_saved}개 기사 처리됨")
    logger.info("--------------------------------------------------")
    return total_saved

if __name__ == "__main__":
    # 이 스크립트는 1회 실행이다. 반복 스케줄링은 상위(run_news_sns.py 또는
    # GitHub Actions cron)가 담당한다. 예전에는 마지막에 60분 sleep 이 있어
    # Actions job 이 수집을 끝내고도 잠들어 timeout 으로 취소됐다.
    db_config = db_config_from_env()

    logger.info("=== Autonomous Political Analysis Service v1.0 ===")

    exit_code = 0
    try:
        ensure_news_schema()
        # 무료 인스턴스는 자고 있다. 먼저 깨워야 관계 저장이 유실되지 않는다.
        if not wake_api():
            logger.warning("API 를 깨우지 못했습니다. 관계 저장은 실패할 수 있으나 "
                           "뉴스 수집/감성분석은 계속 진행합니다.")
        run_pipeline(db_config)
    except Exception as e:
        logger.error(f"Pipeline critical error in single run: {e}")
        logger.error(traceback.format_exc())
        exit_code = 1
    finally:
        close_sync_pool()

    sys.exit(exit_code)