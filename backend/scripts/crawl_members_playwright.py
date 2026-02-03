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
    
    async def set_page_size_max(self, page):
        """페이지 크기를 300으로 설정 시도"""
        try:
            logger.info("Attempting to set page size to 300...")
            # hidden input 값 변경
            await page.evaluate("""() => {
                const rowsInput = document.querySelector('input[name="rows"]');
                if (rowsInput) rowsInput.value = '300';
                
                const pageSizeSelect = document.querySelector('select[name="pageSize"]');
                if (pageSizeSelect) {
                    // 옵션이 없어도 강제 추가 시도
                    const option = document.createElement('option');
                    option.value = '300';
                    option.text = '300';
                    pageSizeSelect.add(option);
                    pageSizeSelect.value = '300';
                }
            }""")
            
            # 검색 버튼 클릭하여 적용
            search_btn = page.locator('#btnSearch')
            if await search_btn.count() > 0:
                await search_btn.click()
                await page.wait_for_load_state('networkidle')
                await asyncio.sleep(3) # 데이터 로드 대기
                return True
        except Exception as e:
            logger.error(f"Failed to set page size: {e}")
        return False

    async def crawl_all_members(self):
        """전체 의원 데이터 수집"""
        logger.info("=" * 60)
        logger.info("Starting Playwright-based crawling for all 300 members...")
        logger.info("=" * 60)
        
        all_members = []
        
        async with async_playwright() as p:
            # 브라우저 시작 (headless=True for speed, False for debugging)
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            page = await context.new_page()
            
            try:
                # 첫 페이지 로드
                logger.info(f"Navigating to {self.base_url}")
                await page.goto(self.base_url, wait_until='networkidle')
                await asyncio.sleep(2)
                
                # 한 페이지에 모두 표시 시도 (Turbo Mode)
                await self.set_page_size_max(page)
                
                # 현재 페이지에서 추출
                logger.info("Extracting members from page...")
                members = await self.extract_members_from_page(page, "Current")
                all_members.extend(members)
                logger.info(f"Initial collection: {len(members)} members")
                
                # 300명이 안 되면 페이지네이션 진행
                if len(all_members) < 290: # 300명 근처가 아니면
                    logger.info("Did not collect all members in one go. Starting pagination...")
                    
                    # 전체 페이지 수 재확인 (페이지당 10명 기준일 수 있음)
                    total_pages = 15 # 넉넉하게
                    
                    for page_num in range(2, total_pages + 1):
                        logger.info(f"\n=== Navigating to page {page_num} ===")
                        
                        # 다음 페이지로 이동
                        # 1. 숫자 버튼 클릭 시도
                        next_page_btn = page.locator(f'#list-sect-pager a.number:has-text("{page_num}")')
                        
                        # 2. 없으면 '다음 10페이지' 버튼 클릭 (11페이지 넘어갈 때)
                        if await next_page_btn.count() == 0:
                            next_10_btn = page.locator('#list-sect-pager a.btn_page_next')
                            if await next_10_btn.count() > 0:
                                await next_10_btn.click()
                                await asyncio.sleep(2)
                                next_page_btn = page.locator(f'#list-sect-pager a.number:has-text("{page_num}")')
                        
                        if await next_page_btn.count() > 0:
                            # 현재 첫 번째 행의 이름 저장 (변경 확인용)
                            first_row_name = await page.locator('tbody#list-result-sect tr').first.locator('td').nth(2).text_content() if await page.locator('tbody#list-result-sect tr').count() > 0 else ""
                            
                            await next_page_btn.click()
                            
                            # 데이터 변경 대기 (이름이 바뀔 때까지)
                            try:
                                await page.wait_for_function(
                                    f"document.querySelector('tbody#list-result-sect tr td:nth-child(3)').textContent.trim() !== '{first_row_name.strip()}'",
                                    timeout=5000
                                )
                            except:
                                await asyncio.sleep(2) # 타임아웃 시 그냥 대기
                                
                            # 추출
                            new_members = await self.extract_members_from_page(page, page_num)
                            if not new_members:
                                logger.info("No members found on this page. Stopping.")
                                break
                                
                            # 중복 방지
                            existing_names = set(m['name'] for m in all_members)
                            for m in new_members:
                                if m['name'] not in existing_names:
                                    all_members.append(m)
                                    
                            logger.info(f"Total collected so far: {len(all_members)}")
                            
                            if len(all_members) >= 300:
                                logger.info("Reached 300 members!")
                                break
                        else:
                            logger.info(f"Page {page_num} link not found. Assuming end of list.")
                            break
            
            except Exception as e:
                logger.error(f"Critical error: {e}")
                import traceback
                logger.error(traceback.format_exc())
            
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
