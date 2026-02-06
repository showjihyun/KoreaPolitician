"""
정치인 데이터 크롤러
- 국회의원 상세 정보
- 프로필 사진
- 관계 정보
"""

import asyncio
import json
import os
from typing import List, Dict, Any
from playwright.async_api import async_playwright, Page
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PoliticianCrawler:
    def __init__(self, output_dir: str = "data"):
        self.output_dir = output_dir
        self.images_dir = os.path.join(output_dir, "images", "members", "KR")
        os.makedirs(self.images_dir, exist_ok=True)
        
    async def crawl_assembly_member_detail(self, member: Dict[str, Any], page: Page) -> Dict[str, Any]:
        """국회의원 상세 정보 크롤링"""
        url = member.get("linkUrl")
        if not url:
            # Fallback to monaCd if linkUrl is missing
            member_id = member.get("monaCd")
            if not member_id: return None
            url = f"https://www.assembly.go.kr/portal/assm/member/memPop.do?num={member_id}"
        
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            # 기본 정보 추출 (22대 전용 셀렉터 및 폴백)
            # 이름
            name = ""
            name_cell = await page.query_selector(".member_header .name, .profile_info .name, .name")
            if name_cell:
                name = await name_cell.text_content()
            
            # 경력 정보 (주요약력)
            careers = []
            # 22대 상세 페이지: .part_r.report .list pre
            pre_elem = await page.query_selector(".part_r.report pre, .hyeonReport pre, pre")
            if pre_elem:
                pre_text = await pre_elem.text_content()
                if pre_text:
                    # 줄바꿈으로 분리
                    careers = [line.strip() for line in pre_text.split('\n') if line.strip()]
            
            if not careers:
                # '주요약력' 텍스트를 포함하는 dt의 형제 dd들 또는 ul li (폴백)
                career_items = await page.locator("dt:has-text('주요약력') + dd, .career_list li, .history li").all()
                for item in career_items:
                    career_text = await item.text_content()
                    if career_text:
                        careers.append(career_text.strip())
            
            if not careers:
                # 다른 패턴 시도
                items = await page.locator(".profile_detail dt:has-text('약력') + dd li").all()
                careers = [await i.text_content() for i in items if await i.text_content()]

            return {
                "careers": [c.strip() for c in careers if c.strip()],
            }
            
        except Exception as e:
            logger.error(f"Error crawling member {member.get('name')}: {e}")
            return None
    
    async def download_image(self, url: str, filename: str, page: Page) -> str:
        """이미지 다운로드"""
        try:
            if not url:
                return None
                
            # 이미지 다운로드
            response = await page.request.get(url)
            if response.ok:
                image_path = os.path.join(self.images_dir, filename)
                with open(image_path, "wb") as f:
                    f.write(await response.body())
                logger.info(f"Downloaded image: {filename}")
                return image_path
            else:
                logger.error(f"Failed to download image: {url}")
                return None
                
        except Exception as e:
            logger.error(f"Error downloading image {url}: {e}")
            return None
    
    async def crawl_all_members(self, members_data: List[Dict]) -> List[Dict]:
        """모든 의원 정보 크롤링"""
        results = []
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            
            for i, member in enumerate(members_data):
                logger.info(f"Crawling {i+1}/{len(members_data)}: {member.get('name')}")
                
                # 상세 정보 크롤링 (linkUrl 또는 monaCd가 있는 경우)
                if member.get("linkUrl") or member.get("monaCd"):
                    detail = await self.crawl_assembly_member_detail(member, page)
                    if detail:
                        member.update(detail)
                
                # 이미지 다운로드 (photo_url이 있고 local 파일이 없는 경우)
                photo_url = member.get("photo_url")
                if photo_url:
                    filename = f"{member.get('name')}.jpg"
                    if not os.path.exists(os.path.join(self.images_dir, filename)):
                        local_path = await self.download_image(photo_url, filename, page)
                        if local_path:
                            member["photo_local"] = local_path
                
                results.append(member)
                
                # 요청 간 딜레이
                await asyncio.sleep(1)
            
            await browser.close()
        
        return results
    
    async def crawl_relationships(self, member_name: str, page: Page) -> List[Dict]:
        """정치인 관계 정보 크롤링 (뉴스 기반)"""
        relationships = []
        
        try:
            # 네이버 뉴스 검색
            search_url = f"https://search.naver.com/search.naver?where=news&query={member_name}+만남"
            await page.goto(search_url, wait_until="networkidle")
            
            # 뉴스 제목에서 다른 정치인 이름 추출
            news_items = await page.locator(".news_tit").all()
            
            for item in news_items[:10]:  # 상위 10개만
                title = await item.text_content()
                # 여기서 NLP로 관계 추출 가능
                # 예: "이재명-윤석열 회담" -> ALLY 또는 RIVAL
                
            return relationships
            
        except Exception as e:
            logger.error(f"Error crawling relationships for {member_name}: {e}")
            return []


async def main():
    """메인 실행 함수"""
    # 프로젝트 루트 기준 경로 설정
    input_file = "data/assembly_members_complete.json"
    if not os.path.exists(input_file):
        # 루트에 있을 수도 있으니 확인
        input_file = "assembly_members_complete.json"

    # 기존 데이터 로드
    with open(input_file, "r", encoding="utf-8") as f:
        members_data = json.load(f)
    
    # 크롤러 실행
    crawler = PoliticianCrawler(output_dir="data")
    
    # 상세 정보 및 이미지 크롤링
    logger.info("Starting to crawl member details and images...")
    enhanced_data = await crawler.crawl_all_members(members_data)
    
    # 결과 저장
    output_file = "data/assembly_members_complete.json" # 최신본으로 갱신
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(enhanced_data, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Crawling completed. Updated {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
