"""
국회의원 300명 전체 데이터 수집 (병렬 처리)
assembly_post_crawler.py 기반으로 병렬 처리 추가
"""
import requests
from bs4 import BeautifulSoup
import json
import csv
import os
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import re

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ParallelAssemblyCrawler:
    def __init__(self):
        self.base_url = "https://open.assembly.go.kr/portal/assm/search/memberSchPage.do"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        
        # 이미지 저장 폴더
        self.img_dir = os.path.join(os.path.dirname(__file__), "../../img")
        if not os.path.exists(self.img_dir):
            os.makedirs(self.img_dir)
    
    def search_members_page(self, page=1):
        """특정 페이지의 의원 목록 검색 (POST 방식)"""
        try:
            form_data = {
                "currentPage": str(page),
                "pageSize": "30",
                "대수": "22"
            }
            
            response = self.session.post(self.base_url, data=form_data)
            soup = BeautifulSoup(response.text, "html.parser")
            
            members = []
            
            # tbody id="list-result-sect"에서 데이터 추출
            tbody = soup.find("tbody", id="list-result-sect")
            
            if tbody:
                rows = tbody.find_all("tr")
                logger.info(f"Page {page}: Found {len(rows)} rows")
                
                for row in rows:
                    cols = row.find_all("td")
                    if len(cols) >= 9:
                        name = cols[2].get_text(strip=True)
                        party = cols[3].get_text(strip=True)
                        committee = cols[4].get_text(strip=True)
                        region = cols[5].get_text(strip=True)
                        election_count = cols[7].get_text(strip=True)
                        
                        # 상세 페이지 링크 추출
                        link_tag = cols[2].find("a")
                        detail_link = ""
                        if link_tag:
                            onclick = link_tag.get("onclick")
                            if onclick and "memberDetail" in onclick:
                                match = re.search(r"memberDetail\\('([^']+)'\\)", onclick)
                                if match:
                                    member_id = match.group(1)
                                    detail_link = f"https://www.assembly.go.kr/members/22nd/{member_id}"
                        
                        members.append({
                            "name": name,
                            "party": party,
                            "committee": committee,
                            "region": region,
                            "election_count": election_count,
                            "detail_link": detail_link,
                            "image_url": "",
                            "thumbnail_url": ""
                        })
            else:
                logger.warning(f"Page {page}: tbody#list-result-sect not found")
            
            return members
            
        except Exception as e:
            logger.error(f"Error searching page {page}: {e}")
            return []
    
    def crawl_all_members_parallel(self, max_workers=10):
        """병렬로 전체 의원 데이터 수집"""
        logger.info("=" * 60)
        logger.info("Starting parallel crawling for all 300 assembly members...")
        logger.info("=" * 60)
        
        all_members = []
        
        # 22대 국회 약 300명, 페이지당 30명 = 10페이지
        total_pages = 11
        
        # 병렬로 페이지 크롤링
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(self.search_members_page, page) for page in range(1, total_pages + 1)]
            
            for future in as_completed(futures):
                try:
                    page_members = future.result()
                    all_members.extend(page_members)
                except Exception as e:
                    logger.error(f"Error processing page future: {e}")
        
        logger.info(f"Total members collected: {len(all_members)}")
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

def main():
    """메인 실행 함수"""
    crawler = ParallelAssemblyCrawler()
    
    # 병렬 크롤링 실행
    members = crawler.crawl_all_members_parallel(max_workers=10)
    
    # 결과 저장
    crawler.save_results(members)
    
    logger.info("=" * 60)
    logger.info(f"✓ Crawling completed! Total: {len(members)} members")
    logger.info("=" * 60)

if __name__ == "__main__":
    main()
