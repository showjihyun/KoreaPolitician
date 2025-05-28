import os
import time
import hashlib
from datetime import datetime, timedelta
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
# def crawl_naver_news(query="정치", days=30, max_articles=1000):
#     ... (함수 전체 주석 처리) ...

# 네이버 정치 섹션 진입점 크롤러
def crawl_naver_politics_section(max_articles=100, max_clicks=5):
    logger.info(f"[크롤링 시작] 네이버 정치 섹션: max_articles={max_articles}, max_clicks={max_clicks}")
    url = "https://news.naver.com/section/100"
    articles = []
    seen_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            channel="chrome",
            args=["--start-maximized"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()

        try:
            page.goto(url, timeout=30000)
            # 초기 기사 목록 로드 대기
            page.wait_for_selector(".sa_list", timeout=30000)

            clicks_count = 0
            while len(articles) < max_articles and clicks_count < max_clicks:
                initial_article_count = len(articles)

                # 현재 페이지의 뉴스 아이템 수집
                news_items = page.query_selector_all(".sa_list .sa_item")

                for item in news_items:
                    try:
                        title_elem = item.query_selector(".sa_text_title")
                        if not title_elem:
                            continue

                        title = title_elem.inner_text().strip()
                        url = title_elem.get_attribute("href")

                        if not url or url in seen_urls:
                            continue

                        seen_urls.add(url)

                        press_elem = item.query_selector(".sa_text_press")
                        press = press_elem.inner_text().strip() if press_elem else ""

                        date_elem = item.query_selector(".sa_text_datetime")
                        date = date_elem.inner_text().strip() if date_elem else datetime.now().strftime("%Y-%m-%d")

                        articles.append({
                            "title": title,
                            "url": url,
                            "press": press,
                            "date": date,
                        })

                        if len(articles) >= max_articles:
                            break

                    except Exception as e:
                        logger.warning(f"기사 처리 중 오류: {e}")
                        continue

                logger.info(f"현재 수집 기사 수: {len(articles)}")

                # max_articles에 도달했으면 더 이상 클릭 필요 없음
                if len(articles) >= max_articles:
                     break

                # "기사 더보기" 버튼을 텍스트 내용으로 찾아서 클릭
                try:
                    more_button = page.get_by_text("기사 더보기").first # '기사 더보기' 텍스트를 가진 첫 번째 요소를 찾음
                    if more_button.is_visible() and more_button.is_enabled():
                        more_button.click()
                        clicks_count += 1
                        logger.info(f"'기사 더보기' 버튼 클릭 시도 ({clicks_count}/{max_clicks})")
                        # 클릭 후 새로운 기사 로드를 기다립니다.
                        page.wait_for_timeout(3000) # 3초 대기 (필요에 따라 조정)

                        # 클릭 후 새로운 기사가 로드되었는지 확인 (선택 사항, 더 정확한 확인 필요 시 개선)
                        # 현재는 단순히 다음 반복에서 articles 목록 증가를 통해 간접적으로 확인
                    else:
                        logger.info("'기사 더보기' 버튼을 찾았으나 클릭할 수 없는 상태입니다. 크롤링을 중단합니다.")
                        break # 버튼이 클릭할 수 없으면 중단
                except Exception as e:
                    logger.info(f"'기사 더보기' 버튼 찾기 실패: {e}. 크롤링을 중단합니다.")
                    break # 버튼 찾기 실패 시 중단


        except Exception as e:
            logger.error(f"페이지 로드 또는 크롤링 중 오류: {e}")
            logger.debug(traceback.format_exc())
        finally:
            browser.close()

    logger.info(f"[크롤링 완료] 최종 수집 기사 수: {len(articles)}")
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
        # 테이블 생성 또는 수정
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
            -- 기준일자 컬럼에 인덱스 생성 (이미 존재하면 오류 무시)
            CREATE INDEX IF NOT EXISTS idx_news_sentiment_base_date ON public.news_sentiment (base_date);
        """)

        # 1시간 이내 데이터 삭제
        one_hour_ago = datetime.now() - timedelta(hours=1)
        cur.execute("DELETE FROM public.news_sentiment WHERE inserted_at >= %s", (one_hour_ago,))

        # 현재 날짜 (YYYYMMDD) 생성
        today_yyyymmdd = datetime.now().strftime('%Y%m%d')

        for art in articles:
            cur.execute("""
                INSERT INTO public.news_sentiment (title, url, press, date, politicians, sentiment_label, sentiment_score, content, base_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                art['title'], art['url'], art['press'], art['date'],
                ",".join(art['politicians']), art['sentiment_label'], art['sentiment_score'], art['content'],
                today_yyyymmdd
            ))
        conn.commit()
        logger.info(f"[DB 저장 완료] 총 {len(articles)}건 저장 완료")
    except Exception as e:
        logger.error(f"[DB 저장 중 오류] {e}")
        logger.debug(traceback.format_exc())
        conn.rollback() # 오류 발생 시 롤백
    finally:
        cur.close()
        conn.close()

# def crawl_naver_most_viewed_news(max_articles=30):
#     ... (함수 전체 주석 처리) ...

if __name__ == "__main__":
    logger.info("[파이프라인 시작]")
    # 1. 네이버 정치 섹션 주요 뉴스 수집
    news = crawl_naver_politics_section(max_articles=100)
    all_news = {art['url']: art for art in news}
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
        'password': os.environ.get('PG_PASSWORD', '1234'),
        'dbname': os.environ.get('PG_DB', 'postgres'),
    }
    save_to_postgresql(results, db_config)
    logger.info("[파이프라인 종료]") 