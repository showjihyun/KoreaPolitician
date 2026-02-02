"""
Playwright 기반 국회의원 300명 전체 데이터 수집 (병렬 처리)
실제 브라우저로 HTML 구조 분석 및 데이터 수집
"""
import asyncio
from playwright.async_api import async_playwright
import json
import csv
import os
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PlaywrightAssemblyCrawler:
    def __init__(self):
        self.base_url = "https://open.assembly.go.kr/portal/assm/search/memberSchPage.do"
        self.img_dir = os.path.join(os.path.dirname(__file__), "../../img")
        if not os.path.exists(self.img_dir):
            os.makedirs(self.img_dir)
    
    async def analyze_page_structure(self, page):
        """페이지 구조 분석"""
        logger.info("Analyzing page structure...")
        
        # 페이지 로드 대기
        await page.wait_for_load_state('networkidle')
        await asyncio.sleep(2)
        
        # 테이블 구조 확인
        table_exists = await page.locator('table').count() > 0
        tbody_exists = await page.locator('tbody#list-result-sect').count() > 0
        
        logger.info(f"Table exists: {table_exists}")
        logger.info(f"tbody#list-result-sect exists: {tbody_exists}")
        
        # 페이지 HTML 일부 저장 (디버깅용)
        html = await page.content()
        debug_path = os.path.join(os.path.dirname(__file__), "../../data/assembly_page_debug.html")
        with open(debug_path, 'w', encoding='utf-8') as f:
            f.write(html)
        logger.info(f"Saved page HTML to {debug_path}")
        
        return tbody_exists
    
    async def get_total_pages(self, page):
        """전체 페이지 수 확인"""
        try:
            # 페이지네이션 요소 찾기
            pagination = await page.locator('.pagination, .paging, .page').count()
            if pagination > 0:
                # 마지막 페이지 번호 찾기
                last_page = await page.locator('.pagination a, .paging a').last.text_content()
                if last_page and last_page.isdigit():
                    return int(last_page)
            
            # 기본값: 11페이지 (300명 / 30명 = 10페이지 + 여유)
            return 11
        except:
            return 11
    
    async def extract_members_from_page(self, page, page_num):
        """현재 페이지에서 의원 정보 추출"""
        logger.info(f"Extracting members from page {page_num}...")
        
        members = []
        
        try:
            # tbody#list-result-sect에서 행 찾기
            tbody = page.locator('tbody#list-result-sect')
            rows = tbody.locator('tr')
            row_count = await rows.count()
            
            logger.info(f"Page {page_num}: Found {row_count} rows")
            
            for i in range(row_count):
                row = rows.nth(i)
                cols = row.locator('td')
                col_count = await cols.count()
                
                if col_count >= 9:
                    # 데이터 추출
                    name = await cols.nth(2).text_content()
                    party = await cols.nth(3).text_content()
                    committee = await cols.nth(4).text_content()
                    region = await cols.nth(5).text_content()
                    election_count = await cols.nth(7).text_content()
                    
                    # 상세 링크 추출
                    link_elem = cols.nth(2).locator('a')
                    onclick = await link_elem.get_attribute('onclick') if await link_elem.count() > 0 else ""
                    
                    detail_link = ""
                    if onclick and "memberDetail" in onclick:
                        import re
                        match = re.search(r"memberDetail\('([^']+)'\)", onclick)
                        if match:
                            member_id = match.group(1)
                            detail_link = f"https://www.assembly.go.kr/members/22nd/{member_id}"
                    
                    members.append({
                        "name": name.strip() if name else "",
                        "party": party.strip() if party else "",
                        "committee": committee.strip() if committee else "",
                        "region": region.strip() if region else "",
                        "election_count": election_count.strip() if election_count else "",
                        "detail_link": detail_link,
                        "image_url": "",
                        "thumbnail_url": "",
                        "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    
                    logger.info(f"  - {name.strip() if name else 'Unknown'} ({party.strip() if party else 'Unknown'})")
        
        except Exception as e:
            logger.error(f"Error extracting members from page {page_num}: {e}")
        
        return members
    
    async def navigate_to_page(self, page, page_num):
        """특정 페이지로 이동"""
        try:
            if page_num == 1:
                await page.goto(self.base_url, wait_until='networkidle')
            else:
                # 페이지 번호 클릭 또는 직접 이동
                page_link = page.locator(f'a:has-text("{page_num}")')
                if await page_link.count() > 0:
                    await page_link.click()
                    await page.wait_for_load_state('networkidle')
                else:
                    # JavaScript로 페이지 이동 함수 호출
                    await page.evaluate(f'goPage({page_num})')
                    await page.wait_for_load_state('networkidle')
            
            await asyncio.sleep(1)
            return True
        except Exception as e:
            logger.error(f"Error navigating to page {page_num}: {e}")
            return False
    
    async def crawl_all_members(self):
        """전체 의원 데이터 수집"""
        logger.info("=" * 60)
        logger.info("Starting Playwright-based crawling for all 300 members...")
        logger.info("=" * 60)
        
        all_members = []
        
        async with async_playwright() as p:
            # 브라우저 시작 (headless=False로 디버깅 가능)
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            page = await context.new_page()
            
            try:
                # 첫 페이지 로드
                await page.goto(self.base_url, wait_until='networkidle')
                await asyncio.sleep(2)
                
                # 페이지 구조 분석
                has_tbody = await self.analyze_page_structure(page)
                
                if not has_tbody:
                    logger.warning("tbody#list-result-sect not found. Check debug HTML file.")
                
                # 전체 페이지 수 확인
                total_pages = await self.get_total_pages(page)
                logger.info(f"Total pages to crawl: {total_pages}")
                
                # 각 페이지 순회
                for page_num in range(1, total_pages + 1):
                    logger.info(f"\n=== Crawling page {page_num}/{total_pages} ===")
                    
                    # 페이지 이동
                    if page_num > 1:
                        success = await self.navigate_to_page(page, page_num)
                        if not success:
                            logger.warning(f"Failed to navigate to page {page_num}, skipping...")
                            continue
                    
                    # 의원 정보 추출
                    members = await self.extract_members_from_page(page, page_num)
                    all_members.extend(members)
                    
                    logger.info(f"Page {page_num} completed: {len(members)} members collected")
                    logger.info(f"Total so far: {len(all_members)} members")
                    
                    # 서버 부하 방지
                    await asyncio.sleep(1)
            
            finally:
                await browser.close()
        
        logger.info("=" * 60)
        logger.info(f"✓ Crawling completed! Total: {len(all_members)} members")
        logger.info("=" * 60)
        
        return all_members
    
    def save_results(self, members):
        """결과 저장"""
        if not members:
            logger.warning("No members to save")
            return
        
        # JSON 저장
        json_path = os.path.join(os.path.dirname(__file__), "../../data/assembly_members_complete.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(members, f, ensure_ascii=False, indent=2)
        logger.info(f"✓ Saved {len(members)} members to {json_path}")
        
        # CSV 저장
        csv_path = os.path.join(os.path.dirname(__file__), "../../data/assembly_members_complete.csv")
        with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
            if members:
                writer = csv.DictWriter(f, fieldnames=members[0].keys())
                writer.writeheader()
                writer.writerows(members)
        logger.info(f"✓ Saved CSV to {csv_path}")

async def main():
    """메인 실행 함수"""
    crawler = PlaywrightAssemblyCrawler()
    
    # 크롤링 실행
    members = await crawler.crawl_all_members()
    
    # 결과 저장
    crawler.save_results(members)

if __name__ == "__main__":
    asyncio.run(main())
