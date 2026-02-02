from dotenv import load_dotenv
import os
import time
import hashlib
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from newspaper import Article
import psycopg2
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
    with open(os.path.join(os.path.dirname(__file__), '../../data/assembly_members_complete.json'), 'r', encoding='utf-8') as f:
        members = json.load(f)
        POLITICIANS = [m['name'] for m in members if m.get('name')]
    logger.info(f"총 {len(POLITICIANS)}명의 국회의원 이름을 POLITICIANS에 로드했습니다.")
except Exception as e:
    logger.warning(f"assembly_members_complete.json에서 국회의원 이름 로드 실패: {e}")
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

def extract_politicians(text, name_list):
    found = set()
    for name in name_list:
        if name in text:
            found.add(name)
    return list(found)

def save_to_postgresql(articles, db_config):
    try:
        with psycopg2.connect(**db_config) as conn:
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
                    CREATE INDEX IF NOT EXISTS idx_news_sentiment_url ON public.news_sentiment (url);
                """)
                today_yyyymmdd = datetime.now().strftime('%Y%m%d')
                for art in articles:
                    # 중복 체크 (URL 기준)
                    cur.execute("SELECT id FROM public.news_sentiment WHERE url = %s LIMIT 1", (art['url'],))
                    if cur.fetchone():
                        continue
                        
                    cur.execute("""
                        INSERT INTO public.news_sentiment (title, url, press, date, politicians, sentiment_label, sentiment_score, content, base_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        art['title'], art['url'], art['press'], art['date'],
                        ",".join(art.get('politicians', [])), art.get('sentiment_label', ""), 
                        art.get('sentiment_score', 0.0), art.get('content', ""), today_yyyymmdd
                    ))
                conn.commit()
    except Exception as e:
        logger.error(f"[DB 저장 중 오류] {e}")

def save_to_turingdb(results):
    api_url = "http://localhost:5000/api/edge"
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
                response = requests.post(api_url, json=payload)
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
        with psycopg2.connect(**db_config) as conn:
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

def crawl_naver_news_search(keyword, max_articles=5):
    articles = []
    search_url = f"https://search.naver.com/search.naver?where=news&query={requests.utils.quote(keyword)}&sort=0"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        page = context.new_page()
        try:
            page.goto(search_url, timeout=30000)
            page.wait_for_selector(".list_news, .news_list", timeout=15000)
            items = page.query_selector_all("li.bx, div.news_area")
            for item in items:
                title_el = item.query_selector("a.news_tit, a.tit")
                if not title_el: continue
                title = title_el.inner_text().strip()
                url = title_el.get_attribute("href")
                press = item.query_selector(".info_group .press, .info.press").inner_text().strip() if item.query_selector(".info_group .press, .info.press") else "Naver"
                if url and title and not any(a['url'] == url for a in articles):
                    articles.append({"title": title, "url": url, "press": press, "date": datetime.now().strftime("%Y-%m-%d")})
                if len(articles) >= max_articles: break
        finally:
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
        results.extend(crawl_naver_news_search(f"{name} 정치", max_articles=2))
        results.extend(crawl_naver_news_search(f"{name} 의정활동", max_articles=2))
    except: pass
    
    intl_keyword = f"{name} South Korea"
    try:
        results.extend(crawl_cnn_search(intl_keyword, max_articles=1))
        results.extend(crawl_bbc_search(intl_keyword, max_articles=1))
        results.extend(crawl_nhk_search(intl_keyword, max_articles=1))
    except: pass
    
    return results

def run_pipeline(db_config):
    logger.info("--------------------------------------------------")
    logger.info(f"[파이프라인 실행 시작] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 1. 대상 선정 (데이터가 부족한 20명 우선 수집)
    target_names = get_target_politicians(db_config, limit=20)
    logger.info(f"이번 회차 타겟 수집 대상: {target_names}")
    
    # 2. 뉴스 소스 수집 (병렬)
    news_pool = []
    with ThreadPoolExecutor(max_workers=5) as collection_executor:
        future_to_name = {collection_executor.submit(collect_all_sources_for_name, name): name for name in target_names}
        for future in as_completed(future_to_name):
            try:
                news_pool.extend(future.result())
            except Exception as e:
                logger.error(f"Error during collection for a politician: {e}")
            
    # 3. 글로벌 이슈 수집
    logger.info("[글로벌 일반 뉴스 수집 시작]")
    try:
        news_pool.extend(crawl_cnn_search("Asia Politics", max_articles=3))
        news_pool.extend(crawl_bbc_search("South Korea News", max_articles=3))
        news_pool.extend(crawl_nhk_search("Asia Politics", max_articles=3))
    except Exception as e:
        logger.warning(f"Global source collection failed: {e}")

    # 4. 중복 제거
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
    db_config = {
        'host': os.environ.get('POSTGRES_HOST', 'localhost'),
        'port': int(os.environ.get('POSTGRES_PORT', 5432)),
        'user': os.environ.get('POSTGRES_USER', 'postgres'),
        'password': os.environ.get('POSTGRES_PASSWORD', '1234'),
        'dbname': os.environ.get('POSTGRES_DB', 'postgres'),
    }
    
    # 반복 간격 (분 단위)
    INTERVAL_MINUTES = 60
    
    logger.info(f"=== Autonomous Political Analysis Service v1.0 ===")
    logger.info(f"수집 간격: {INTERVAL_MINUTES}분")
    
    while True:
        try:
            run_pipeline(db_config)
        except Exception as e:
            logger.error(f"Pipeline critical error in main loop: {e}")
            logger.error(traceback.format_exc())
            
        logger.info(f"Next run in {INTERVAL_MINUTES} minutes...")
        time.sleep(INTERVAL_MINUTES * 60)