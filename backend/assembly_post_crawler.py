import requests
from bs4 import BeautifulSoup
import json
import csv
import time
import os
from urllib.parse import urljoin

class AssemblyPostCrawler:
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
        
        # 이미지 저장 폴더 생성
        if not os.path.exists("img"):
            os.makedirs("img")
    
    def get_initial_page(self):
        """초기 페이지에서 필요한 폼 데이터 추출"""
        try:
            response = self.session.get(self.base_url)
            soup = BeautifulSoup(response.text, "html.parser")
            
            # 검색 폼 찾기
            search_form = soup.find("form")
            form_data = {}
            
            if search_form:
                # 숨겨진 입력 필드들 수집
                hidden_inputs = search_form.find_all("input", type="hidden")
                for hidden in hidden_inputs:
                    name = hidden.get("name", "")
                    value = hidden.get("value", "")
                    if name:
                        form_data[name] = value
                
                # 기본 검색 조건 설정
                form_data.update({
                    "currentPage": "1",
                    "pageSize": "20",
                    "daesu": "22",  # 제22대 국회
                    "searchCondition": "",
                    "searchKeyword": "",
                    "party": "",
                    "region": "",
                    "gender": "",
                    "age": "",
                    "electionCount": "",
                    "electionMethod": ""
                })
            
            return form_data
            
        except Exception as e:
            print(f"초기 페이지 로드 중 오류: {e}")
            return {}
    
    def search_members_with_post(self, page=1):
        """POST 요청으로 국회의원 검색 실행"""
        # 초기 폼 데이터 가져오기
        form_data = self.get_initial_page()
        
        if not form_data:
            print("폼 데이터를 가져올 수 없습니다.")
            return []
        
        # 페이지 번호 업데이트
        form_data["currentPage"] = str(page)
        
        try:
            # POST 요청으로 검색 실행
            response = self.session.post(self.base_url, data=form_data)
            soup = BeautifulSoup(response.text, "html.parser")
            
            members = []
            
            # tbody id="list-result-sect"에서 데이터 추출
            tbody = soup.find("tbody", id="list-result-sect")
            
            if tbody:
                rows = tbody.find_all("tr")
                print(f"페이지 {page}: tbody#list-result-sect에서 {len(rows)}개 행 발견")
                
                for row in rows:
                    cols = row.find_all("td")
                    if len(cols) >= 9:  # 9개 컬럼 확인
                        number = cols[0].get_text(strip=True)
                        daesu = cols[1].get_text(strip=True)
                        name = cols[2].get_text(strip=True)
                        party = cols[3].get_text(strip=True)
                        committee = cols[4].get_text(strip=True)
                        region = cols[5].get_text(strip=True)
                        gender = cols[6].get_text(strip=True)
                        election_count = cols[7].get_text(strip=True)
                        election_method = cols[8].get_text(strip=True)
                        
                        # 상세 페이지 링크 추출
                        link_tag = cols[2].find("a")
                        detail_link = ""
                        if link_tag:
                            href = link_tag.get("href")
                            onclick = link_tag.get("onclick")
                            
                            if href:
                                detail_link = urljoin("https://www.assembly.go.kr", href)
                            elif onclick and "memberDetail" in onclick:
                                # onclick에서 의원 ID 추출
                                import re
                                match = re.search(r"memberDetail\('([^']+)'\)", onclick)
                                if match:
                                    member_id = match.group(1)
                                    detail_link = f"https://www.assembly.go.kr/members/22nd/{member_id}"
                        
                        members.append({
                            "number": number,
                            "daesu": daesu,
                            "name": name,
                            "party": party,
                            "committee": committee,
                            "region": region,
                            "gender": gender,
                            "election_count": election_count,
                            "election_method": election_method,
                            "detail_link": detail_link
                        })
                        
                        print(f"  - {name} ({party}, {region})")
            else:
                print(f"페이지 {page}: tbody#list-result-sect를 찾을 수 없습니다.")
            
            return members
            
        except Exception as e:
            print(f"페이지 {page} 검색 중 오류: {e}")
            return []
    
    def get_all_members_list(self):
        """모든 페이지에서 국회의원 목록 수집"""
        all_members = []
        page = 1
        
        while True:
            print(f"\n=== 페이지 {page} 검색 중 ===")
            members = self.search_members_with_post(page)
            
            if not members:
                print(f"페이지 {page}에서 데이터가 없어 종료")
                break
                
            all_members.extend(members)
            print(f"페이지 {page} 완료, 누적 {len(all_members)}명")
            
            page += 1
            time.sleep(1)  # 서버 부하 방지
            
            # 안전장치: 최대 15페이지까지만 (300명 정도)
            if page > 15:
                break
        
        return all_members
    
    def save_results(self, members):
        """결과를 JSON과 CSV로 저장"""
        if not members:
            print("저장할 데이터가 없습니다.")
            return
        
        # JSON 저장
        with open("assembly_members_post.json", "w", encoding="utf-8") as f:
            json.dump(members, f, ensure_ascii=False, indent=2)
        
        # CSV 저장
        with open("assembly_members_post.csv", "w", newline="", encoding="utf-8") as f:
            if members:
                fieldnames = members[0].keys()
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(members)
        
        print(f"\n=== 저장 완료 ===")
        print(f"총 {len(members)}명의 국회의원 정보 수집")
        print(f"JSON: assembly_members_post.json")
        print(f"CSV: assembly_members_post.csv")
    
    def crawl_all_members(self):
        """전체 크롤링 실행"""
        print("=== 국회의원 정보 수집 시작 (POST 방식) ===")
        
        # 국회의원 목록 수집
        members = self.get_all_members_list()
        
        # 결과 저장
        self.save_results(members)
        
        return members

if __name__ == "__main__":
    crawler = AssemblyPostCrawler()
    crawler.crawl_all_members() 