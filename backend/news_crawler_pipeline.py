from dotenv import load_dotenv
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
from neo4j import GraphDatabase
import json

# Load environment variables from .env file
load_dotenv()

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

# assembly_members_complete.json에서 국회의원 이름 전체를 읽어 POLITICIANS 리스트 생성
POLITICIANS = []
try:
    with open(os.path.join(os.path.dirname(__file__), '../assembly_members_complete.json'), 'r', encoding='utf-8') as f:
        members = json.load(f)
        POLITICIANS = [m['name'] for m in members if m.get('name')]
    logger.info(f"총 {len(POLITICIANS)}명의 국회의원 이름을 POLITICIANS에 로드했습니다.")
except Exception as e:
    logger.warning(f"assembly_members_complete.json에서 국회의원 이름 로드 실패: {e}")
    POLITICIANS = []

# 감정분석 파이프라인 (영어 5단계)
try:
    import torch
    if torch.cuda.is_available():
        device = 0
        logger.info("GPU(CUDA) 사용: 감정분석 파이프라인이 GPU에서 실행됩니다.")
    else:
        device = -1
        logger.info("GPU 미탑재: 감정분석 파이프라인이 CPU에서 실행됩니다.")
except ImportError:
    device = -1
    logger.warning("torch 모듈이 없어 CPU로 감정분석을 실행합니다.")

sentiment_clf = pipeline("sentiment-analysis", model="nlptown/bert-base-multilingual-uncased-sentiment", device=device)
translator = Translator()

# 1. Playwright로 네이버 뉴스 크롤링
# def crawl_naver_news(query="정치", days=30, max_articles=1000):
#     ... (함수 전체 주석 처리) ...

# (기존) 단일 섹션 크롤러는 deprecated 처리
# def crawl_naver_politics_section(max_articles=100, max_clicks=5):
#     ... (기존 코드) ...

# 여러 섹션을 순회하며 뉴스 수집

def crawl_naver_politics_sections(categories, max_articles=100, max_clicks=10):
    """
    categories: ["100", "101", ...] 형태의 섹션 리스트
    각 섹션별로 max_articles만큼 기사 수집 후 합쳐서 반환
    """
    all_articles = []
    seen_urls = set()
    for cat in categories:
        logger.info(f"[크롤링 시작] 네이버 섹션 {cat}: max_articles={max_articles}, max_clicks={max_clicks}")
        url = f"https://news.naver.com/section/{cat}"
        articles = []
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
                page.wait_for_selector(".sa_list", timeout=30000)
                clicks_count = 0
                while len(articles) < max_articles and clicks_count < max_clicks:
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
                                "section": cat
                            })
                            if len(articles) >= max_articles:
                                break
                        except Exception as e:
                            logger.warning(f"기사 처리 중 오류: {e}")
                            continue
                    logger.info(f"[{cat}] 현재 수집 기사 수: {len(articles)}")
                    if len(articles) >= max_articles:
                        break
                    try:
                        more_button = page.get_by_text("기사 더보기").first
                        if more_button.is_visible() and more_button.is_enabled():
                            more_button.click()
                            clicks_count += 1
                            logger.info(f"[{cat}] '기사 더보기' 버튼 클릭 시도 ({clicks_count}/{max_clicks})")
                            page.wait_for_timeout(3000)
                        else:
                            logger.info(f"[{cat}] '기사 더보기' 버튼을 찾았으나 클릭할 수 없는 상태입니다. 크롤링을 중단합니다.")
                            break
                    except Exception as e:
                        logger.info(f"[{cat}] '기사 더보기' 버튼 찾기 실패: {e}. 크롤링을 중단합니다.")
                        break
            except Exception as e:
                logger.error(f"[{cat}] 페이지 로드 또는 크롤링 중 오류: {e}")
                logger.debug(traceback.format_exc())
            finally:
                browser.close()
        all_articles.extend(articles)
        logger.info(f"[{cat}] [크롤링 완료] 최종 수집 기사 수: {len(articles)}")
    logger.info(f"[전체 섹션 크롤링 완료] 총 기사 수: {len(all_articles)}")
    return all_articles

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

# 5. Postgresql 저장 함수 (with 문 사용)
def save_to_postgresql(articles, db_config):
    try:
        with psycopg2.connect(**db_config) as conn:
            with conn.cursor() as cur:
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
        if 'conn' in locals():
            conn.rollback()

# def crawl_naver_most_viewed_news(max_articles=30):
#     ... (함수 전체 주석 처리) ...

# Neo4J 관계 생성 함수 (Cartesian Product 방지)
def create_article_and_relationships(tx, article):
    # 기사 노드 생성 또는 매칭
    tx.run("MERGE (a:Article {url: $url}) "
           "SET a.title = $title, a.press = $press, a.date = $date, a.sentiment_label = $sentiment_label, a.sentiment_score = $sentiment_score, a.base_date = $base_date",
           url=article['url'], title=article['title'], press=article['press'], date=article['date'],
           sentiment_label=article['sentiment_label'], sentiment_score=article['sentiment_score'], base_date=article['base_date'])

    politicians = article.get('politicians', [])
    if len(politicians) >= 2:
        # 기사와 정치인 관계 (PUBLISHED_ABOUT)
        for politician_name in politicians:
            tx.run("MERGE (p:Politician {name: $name})", name=politician_name)
            # Cartesian Product 방지: MATCH ... WHERE ... RETURN ... LIMIT 1
            tx.run("MATCH (a:Article {url: $url}) WITH a MATCH (p:Politician {name: $name}) MERGE (a)-[:PUBLISHED_ABOUT]->(p)", url=article['url'], name=politician_name)

        # 정치인 간 관계 (MENTIONED_TOGETHER) 및 감정 관계 (POSITIVE_SENTIMENT, NEGATIVE_SENTIMENT)
        for i in range(len(politicians)):
            for j in range(i + 1, len(politicians)):
                name1 = politicians[i]
                name2 = politicians[j]
                # Cartesian Product 방지: MATCH ... WITH ... MATCH ...
                tx.run("MATCH (p1:Politician {name: $name1}) WITH p1 MATCH (p2:Politician {name: $name2}) MERGE (p1)-[:MENTIONED_TOGETHER]->(p2)", name1=name1, name2=name2)
                sentiment_label = article.get('sentiment_label')
                if sentiment_label:
                    relation_type = None
                    if '5 stars' in sentiment_label or '4 stars' in sentiment_label:
                        relation_type = 'POSITIVE_SENTIMENT'
                    elif '1 star' in sentiment_label or '2 stars' in sentiment_label:
                        relation_type = 'NEGATIVE_SENTIMENT'
                    if relation_type:
                        tx.run(f"MATCH (p1:Politician {{name: $name1}}) WITH p1 MATCH (p2:Politician {{name: $name2}}) MERGE (p1)-[r:{relation_type}]->(p2) SET r.count = coalesce(r.count, 0) + 1, r.via_article = $url",
                               name1=name1, name2=name2, url=article['url'])

# 6. Neo4J 저장 함수 (with 문 사용, 내부 함수 제거)
def save_to_neo4j(articles):
    uri = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    user = os.environ.get('NEO4J_USER', 'neo4j')
    password = os.environ.get('NEO4J_PASSWORD', 'password')

    logger.info("[Neo4J 저장 시작]")
    try:
        with GraphDatabase.driver(uri, auth=(user, password)) as driver:
            driver.verify_connectivity()
            logger.info("Neo4J 연결 성공")

            with driver.session() as session:
                for i, art in enumerate(articles):
                    if art.get('politicians') and len(art['politicians']) >= 2:
                        try:
                            logger.info(f"[Neo4J 저장] 기사 {i+1}/{len(articles)} - {art['title']}")
                            session.execute_write(create_article_and_relationships, art)
                        except Exception as e:
                            logger.warning(f"[Neo4J 저장 오류] 기사: {art.get('title', '제목 없음')} -> {e}")
                            logger.debug(traceback.format_exc())
    except Exception as e:
        logger.error(f"[Neo4J 연결 오류] {e}")
        logger.debug(traceback.format_exc())
    logger.info("[Neo4J 저장 완료]")

# 카테고리별 크롤링 함수 (정치, 경제, 사회 등)
def crawl_naver_news_section(category, max_articles=50, max_clicks=5):
    logger.info(f"[크롤링 시작] 네이버 섹션 {category}: max_articles={max_articles}, max_clicks={max_clicks}")
    url = f"https://news.naver.com/section/{category}"
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
            page.wait_for_selector(".sa_list", timeout=30000)

            clicks_count = 0
            while len(articles) < max_articles and clicks_count < max_clicks:
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
                if len(articles) >= max_articles:
                    break
                try:
                    more_button = page.get_by_text("기사 더보기").first
                    if more_button.is_visible() and more_button.is_enabled():
                        more_button.click()
                        clicks_count += 1
                        logger.info(f"'기사 더보기' 버튼 클릭 시도 ({clicks_count}/{max_clicks})")
                        page.wait_for_timeout(3000)
                    else:
                        logger.info("'기사 더보기' 버튼을 찾았으나 클릭할 수 없는 상태입니다. 크롤링을 중단합니다.")
                        break
                except Exception as e:
                    logger.info(f"'기사 더보기' 버튼 찾기 실패: {e}. 크롤링을 중단합니다.")
                    break
        except Exception as e:
            logger.error(f"페이지 로드 또는 크롤링 중 오류: {e}")
            logger.debug(traceback.format_exc())
        finally:
            browser.close()
    logger.info(f"[크롤링 완료] 최종 수집 기사 수: {len(articles)}")
    return articles

# 여러 카테고리 뉴스 수집 (중복 URL 제거, 최소/최대 개수 보장)
def crawl_all_categories(categories, min_per_cat=3, max_per_cat=50):
    all_articles = []
    seen_urls = set()
    for cat in categories:
        articles = crawl_naver_news_section(cat, max_articles=max_per_cat)
        count = 0
        for art in articles:
            if art['url'] not in seen_urls:
                all_articles.append(art)
                seen_urls.add(art['url'])
                count += 1
            if count >= max_per_cat:
                break
        if count < min_per_cat:
            logger.warning(f"카테고리 {cat}에서 기사 부족: {count}개")
    return all_articles

if __name__ == "__main__":
    logger.info("[파이프라인 시작]")
    # 주요 카테고리: 정치(100), 경제(101), 사회(102)
    categories = ["100", "101", "102"]
    news = crawl_naver_politics_sections(categories, max_articles=100, max_clicks=10)
    all_news = {art['url']: art for art in news}
    logger.info(f"[총 기사 수] {len(all_news)}")
    results = []
    for i, art in enumerate(all_news.values()):
        logger.info(f"[{i+1}/{len(all_news)}] 기사 제목: {art['title']}")
        logger.info(f"기사 URL: {art['url']}")
        content = get_article_text(art['url'])
        logger.info(f"기사 본문 추출 완료 (길이: {len(content)})")
        found_names = extract_politicians(content, POLITICIANS)
        logger.info(f"추출된 국회의원 이름: {found_names}")
        if len(found_names) >= 2 and content:
            try:
                logger.info(f"감정분석 시작: {found_names}")
                sentiment_label, sentiment_score = analyze_article_sentiment(content)
                logger.info(f"감정분석 결과: label={sentiment_label}, score={sentiment_score}")
            except Exception as e:
                logger.warning(f"감정분석 오류: {e}")
                sentiment_label, sentiment_score = "", 0.0
        else:
            sentiment_label, sentiment_score = "", 0.0
            logger.info("감정분석 생략: 추출된 이름이 2명 미만이거나 본문 없음")
        art['content'] = content
        art['politicians'] = found_names
        art['sentiment_label'] = sentiment_label
        art['sentiment_score'] = sentiment_score
        art['base_date'] = datetime.now().strftime('%Y%m%d')
        results.append(art)
    # 4. DB 저장
    db_config = {
        'host': os.environ.get('POSTGRES_HOST', 'localhost'),
        'port': int(os.environ.get('POSTGRES_PORT', 5432)),
        'user': os.environ.get('POSTGRES_USER', 'postgres'),
        'password': os.environ.get('POSTGRES_PASSWORD', '1234'),
        'dbname': os.environ.get('POSTGRES_DB', 'postgres'),
    }
    save_to_postgresql(results, db_config)
    logger.info("[DB 저장 완료]")
    # 5. Neo4J 저장
    save_to_neo4j(results)
    logger.info("[Neo4J 저장 완료]")
    logger.info("[파이프라인 종료]") 