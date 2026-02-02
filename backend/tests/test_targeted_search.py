import os
import requests
from playwright.sync_api import sync_playwright
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def crawl_naver_news_search(keyword, max_articles=5):
    articles = []
    search_url = f"https://search.naver.com/search.naver?where=news&query={requests.utils.quote(keyword)}&sort=0"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        page = context.new_page()
        
        try:
            logger.info(f"[TEST] 검색 키워드: {keyword}")
            page.goto(search_url, timeout=30000)
            page.wait_for_selector(".list_news", timeout=10000)
            
            items = page.query_selector_all(".list_news .bx")
            for item in items:
                title_el = item.query_selector(".news_tit")
                if not title_el: continue
                
                title = title_el.inner_text().strip()
                url = title_el.get_attribute("href")
                
                if url and title:
                    articles.append({"title": title, "url": url})
                
                if len(articles) >= max_articles:
                    break
        except Exception as e:
            logger.error(f"Search error: {e}")
        finally:
            browser.close()
            
    return articles

if __name__ == "__main__":
    test_keywords = ["박수영 경제", "강성희 사회", "김웅 정치"]
    for kw in test_keywords:
        results = crawl_naver_news_search(kw)
        print(f"\nResults for '{kw}':")
        for r in results:
            print(f"- {r['title']} ({r['url']})")
