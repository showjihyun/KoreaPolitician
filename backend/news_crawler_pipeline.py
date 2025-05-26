import os
import time
import hashlib
from datetime import datetime
from playwright.sync_api import sync_playwright
from newspaper import Article
from googletrans import Translator
from transformers import pipeline
import psycopg2
import logging
import traceback

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('news_crawler_pipeline.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 정치인 이름 샘플 리스트 (실제는 DB/CSV/크롤링 결과 활용)
POLITICIANS = [
    "이재명", "김기현", "이준석", "이해찬", "윤석열", "한동훈", "홍준표", "유승민", "심상정", "안철수"
]

# 감정분석 파이프라인 (영어 5단계)
sentiment_clf = pipeline("sentiment-analysis", model="nlptown/bert-base-multilingual-uncased-sentiment", device=0 if hasattr(__import__('torch'), 'cuda') and __import__('torch').cuda.is_available() else -1)
translator = Translator()

# 1. Playwright로 네이버 뉴스 크롤링
def crawl_naver_news(query="정치", days=1, max_articles=100):
    logger.info(f"[크롤링 시작] 네이버 뉴스 검색: query={query}, max_articles={max_articles}")
    articles = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"https://search.naver.com/search.naver?where=news&query={query}&pd=3&ds=&de=&docid=&nso=so:r,p:1m,a:all&mynews=0&start=1")
        time.sleep(2)
        seen_urls = set()
        while len(articles) < max_articles:
            news_cards = page.query_selector_all("ul.list_news > li")
            for card in news_cards:
                a = card.query_selector("a.news_tit")
                if not a:
                    continue
                url = a.get_attribute("href")
                title = a.get_attribute("title")
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                press = card.query_selector("a.info.press")
                press = press.inner_text().strip() if press else ""
                date = card.query_selector("span.info")
                date = date.inner_text().strip() if date else ""
                articles.append({
                    "title": title,
                    "url": url,
                    "press": press,
                    "date": date
                })
                if len(articles) >= max_articles:
                    break
            next_btn = page.query_selector("a.btn_next")
            if next_btn and not next_btn.is_disabled():
                next_btn.click()
                time.sleep(1.5)
            else:
                break
        browser.close()
    logger.info(f"[크롤링 완료] 수집 기사 수: {len(articles)}")
    return articles

# 네이버 정치 섹션 진입점 크롤러
def crawl_naver_politics_section(max_articles=100):
    logger.info(f"[크롤링 시작] 네이버 정치 섹션: max_articles={max_articles}")
    url = "https://news.naver.com/section/100"
    articles = []
    seen_urls = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url)
        page.wait_for_selector(".sa_text_title, .newsnow_tx_area a", timeout=10000)
        cards = page.query_selector_all(".sa_text_title, .newsnow_tx_area a")
        for card in cards:
            a = card
            href = a.get_attribute("href")
            title = a.inner_text().strip()
            if not href or not title or href in seen_urls:
                continue
            seen_urls.add(href)
            # 언론사, 날짜 추출 (상위 div에서 찾기)
            parent = a.evaluate_handle('node => node.closest("div.sa_area, div.newsnow_tx_area")')
            parent = parent.as_element() if parent else None
            press = ""
            date = ""
            if parent:
                press_elem = parent.query_selector(".sa_text_press, .newsnow_tx_press")
                press = press_elem.inner_text().strip() if press_elem else ""
                date_elem = parent.query_selector(".sa_text_datetime, .newsnow_tx_time")
                date = date_elem.inner_text().strip() if date_elem else ""
            articles.append({
                "title": title,
                "url": href,
                "press": press,
                "date": date
            })
            if len(articles) >= max_articles:
                break
        browser.close()
    logger.info(f"[크롤링 완료] 정치 섹션 기사 수: {len(articles)}")
    return articles

# 2. newspaper3k로 기사 본문 전문 크롤링
def get_article_text(url):
    try:
        article = Article(url, language='ko')
        article.download()
        article.parse()
        return article.text
    except Exception as e:
        logger.warning(f"[본문 크롤링 실패] {url} -> {e}")
        logger.debug(traceback.format_exc())
        return ""

# 3. 정치인 이름 자동 추출
def extract_politicians(text, name_list):
    found = set()
    for name in name_list:
        if name in text:
            found.add(name)
    return list(found)

# 4. 감정분석 (한글→영어 번역 후 5단계)
def analyze_article_sentiment(text):
    try:
        # 입력 길이 제한 (512자)
        max_length = 512
        if len(text) > max_length:
            text = text[:max_length]
        en = translator.translate(text, src='ko', dest='en').text
        result = sentiment_clf(en)
        return result[0]['label'], float(result[0]['score'])
    except Exception as e:
        logger.warning(f"[감정분석 실패] {e}")
        logger.debug(traceback.format_exc())
        return "", 0.0

# 5. Postgresql 저장 함수
def save_to_postgresql(articles, db_config):
    try:
        conn = psycopg2.connect(**db_config)
    except Exception as e:
        logger.error(f"[DB 연결 오류] {e}")
        logger.debug(traceback.format_exc())
        return
    cur = conn.cursor()
    try:
        cur.execute('''
            CREATE TABLE IF NOT EXISTS public.news_sentiment (
                id SERIAL PRIMARY KEY,
                title TEXT,
                url TEXT,
                press TEXT,
                date TEXT,
                politicians TEXT,
                sentiment_label TEXT,
                sentiment_score FLOAT,
                content TEXT
            );
        ''')
        for art in articles:
            cur.execute('''
                INSERT INTO public.news_sentiment (title, url, press, date, politicians, sentiment_label, sentiment_score, content)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                art['title'], art['url'], art['press'], art['date'],
                ",".join(art['politicians']), art['sentiment_label'], art['sentiment_score'], art['content']
            ))
        conn.commit()
        logger.info(f"[DB 저장 완료] 총 {len(articles)}건 저장 완료")
    except Exception as e:
        logger.error(f"[DB 저장 중 오류] {e}")
        logger.debug(traceback.format_exc())
    finally:
        cur.close()
        conn.close()

def crawl_naver_most_viewed_news(max_articles=30):
    logger.info(f"[크롤링 시작] 네이버 랭킹(많이 본 뉴스): max_articles={max_articles}")
    url = "https://news.naver.com/main/ranking/popularDay.naver"
    articles = []
    seen_urls = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url)
        page.wait_for_selector(".rankingnews_box", timeout=10000)
        ranking_boxes = page.query_selector_all(".rankingnews_box")
        for box in ranking_boxes:
            news_links = box.query_selector_all("a")
            for a in news_links:
                href = a.get_attribute("href")
                title = a.inner_text().strip()
                if not href or not title or href in seen_urls:
                    continue
                seen_urls.add(href)
                # 언론사명 추출 (상위 div나 span 등에서)
                press = ""
                press_elem = box.query_selector(".rankingnews_name, .press")
                press = press_elem.inner_text().strip() if press_elem else ""
                articles.append({
                    "title": title,
                    "url": href,
                    "press": press,
                    "date": "",
                })
                if len(articles) >= max_articles:
                    break
            if len(articles) >= max_articles:
                break
        browser.close()
    logger.info(f"[크롤링 완료] 랭킹 기사 수: {len(articles)}")
    return articles

if __name__ == "__main__":
    logger.info("[파이프라인 시작]")
    # 1. 정치 섹션 헤드라인
    news = crawl_naver_politics_section(max_articles=30)
    # 2. 언론사별 많이 본 뉴스
    most_viewed = crawl_naver_most_viewed_news(max_articles=30)
    # 3. 중복 제거 및 합치기
    all_news = {art['url']: art for art in news + most_viewed}
    logger.info(f"[총 기사 수] {len(all_news)}")
    results = []
    for i, art in enumerate(all_news.values()):
        logger.info(f"[{i+1}/{len(all_news)}] {art['title']}")
        content = get_article_text(art['url'])
        found_names = extract_politicians(content, POLITICIANS)
        if len(found_names) >= 2 and content:
            sentiment_label, sentiment_score = analyze_article_sentiment(content)
        else:
            sentiment_label, sentiment_score = "", 0.0
        art['content'] = content
        art['politicians'] = found_names
        art['sentiment_label'] = sentiment_label
        art['sentiment_score'] = sentiment_score
        results.append(art)
    # 4. DB 저장
    db_config = {
        'host': os.environ.get('PG_HOST', 'localhost'),
        'port': os.environ.get('PG_PORT', 5432),
        'user': os.environ.get('PG_USER', 'postgres'),
        'password': os.environ.get('PG_PASSWORD', 'password'),
        'dbname': os.environ.get('PG_DB', 'postgres'),
    }
    save_to_postgresql(results, db_config)
    logger.info("[파이프라인 종료]") 