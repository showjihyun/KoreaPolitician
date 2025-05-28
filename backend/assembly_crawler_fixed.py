import requests
from bs4 import BeautifulSoup
import json
import csv
import time
import os
from urllib.parse import urljoin, urlparse

class AssemblyCrawlerFixed:
    def __init__(self):
        self.base_url = "https://open.assembly.go.kr/portal/assm/search/memberSchPage.do"
        self.detail_base_url = "https://www.assembly.go.kr/members/22nd/"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        
        # 이미지 저장 폴더 생성
        if not os.path.exists("img"):
            os.makedirs("img")
    
    def search_members_with_conditions(self, page=1):
        """검색 조건을 설정하여 국회의원 목록 가져오기"""
        # POST 요청으로 검색 실행
        search_data = {
            "currentPage": page,
            "pageSize": "20",  # 한 페이지당 20명
            "daesu": "22",     # 제22대 국회
            "searchCondition": "",
            "searchKeyword": "",
            "party": "",       # 전체 정당
            "region": "",      # 전체 지역
            "gender": "",      # 전체 성별
            "age": "",         # 전체 연령
            "electionCount": "", # 전체 당선횟수
            "electionMethod": "" # 전체 당선방법
        }
        
        try:
            # POST 요청으로 검색 실행
            response = self.session.post(self.base_url, data=search_data)
            soup = BeautifulSoup(response.text, "html.parser")
            
            members = []
            
            # 테이블에서 데이터 추출
            table = soup.find("table")
            if table:
                rows = table.find("tbody").find_all("tr") if table.find("tbody") else table.find_all("tr")[1:]
                
                for row in rows:
                    cols = row.find_all("td")
                    if len(cols) >= 9:
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
                        if link_tag and link_tag.get("onclick"):
                            # onclick에서 의원 ID 추출
                            onclick = link_tag.get("onclick")
                            if "memberDetail" in onclick:
                                # JavaScript 함수에서 ID 추출
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
            
            return members
            
        except Exception as e:
            print(f"페이지 {page} 검색 중 오류: {e}")
            return []
    
    def get_all_members_list(self):
        """모든 페이지에서 국회의원 목록 수집"""
        all_members = []
        page = 1
        
        while True:
            print(f"검색 {page}페이지 수집 중...")
            members = self.search_members_with_conditions(page)
            
            if not members:
                print(f"페이지 {page}에서 데이터가 없어 종료")
                break
                
            all_members.extend(members)
            print(f"페이지 {page} 완료, 누적 {len(all_members)}명")
            
            page += 1
            time.sleep(1)  # 서버 부하 방지
            
            # 안전장치: 최대 20페이지까지만 (300명 정도)
            if page > 20:
                break
        
        return all_members
    
    def get_member_detail_info(self, detail_url, member_name):
        """개별 국회의원 상세 정보 수집"""
        if not detail_url:
            return {}
            
        try:
            response = self.session.get(detail_url)
            soup = BeautifulSoup(response.text, "html.parser")
            
            info = {}
            
            # 기본 정보 섹션
            profile_section = soup.find("div", class_="profile_area")
            if profile_section:
                # 정당 정보
                party_elem = profile_section.find("span", class_="party")
                if party_elem:
                    info["detailed_party"] = party_elem.get_text(strip=True)
                
                # 프로필 정보 리스트
                profile_list = profile_section.find("ul", class_="profile_list")
                if profile_list:
                    for li in profile_list.find_all("li"):
                        strong = li.find("strong")
                        if strong:
                            key = strong.get_text(strip=True)
                            value = li.get_text(strip=True).replace(key, "").strip()
                            info[key] = value
            
            # 연락처 정보
            contact_section = soup.find("div", class_="contact_area")
            if contact_section:
                for li in contact_section.find_all("li"):
                    strong = li.find("strong")
                    if strong:
                        key = strong.get_text(strip=True)
                        value = li.get_text(strip=True).replace(key, "").strip()
                        info[key] = value
            
            # 약력 정보
            career_section = soup.find("div", class_="career_area")
            if career_section:
                career_list = career_section.find("ul")
                if career_list:
                    careers = [li.get_text(strip=True) for li in career_list.find_all("li")]
                    info["약력"] = careers
            
            # 프로필 사진
            img_elem = soup.find("div", class_="photo_area")
            if img_elem:
                img_tag = img_elem.find("img")
                if img_tag and img_tag.get("src"):
                    img_url = urljoin(detail_url, img_tag["src"])
                    info["photo_url"] = img_url
                    
                    # 이미지 다운로드
                    img_filename = self.download_image(img_url, member_name)
                    info["photo_filename"] = img_filename
            
            return info
            
        except Exception as e:
            print(f"상세 정보 수집 중 오류 ({detail_url}): {e}")
            return {}
    
    def download_image(self, img_url, member_name):
        """이미지 다운로드"""
        try:
            response = self.session.get(img_url)
            if response.status_code == 200:
                # 파일명 생성 (이름 + 확장자)
                parsed_url = urlparse(img_url)
                ext = os.path.splitext(parsed_url.path)[1] or ".jpg"
                # 파일명에서 특수문자 제거
                safe_name = "".join(c for c in member_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
                filename = f"{safe_name.replace(' ', '_')}{ext}"
                filepath = os.path.join("img", filename)
                
                with open(filepath, "wb") as f:
                    f.write(response.content)
                
                print(f"이미지 다운로드 완료: {filename}")
                return filename
                
        except Exception as e:
            print(f"이미지 다운로드 실패 ({img_url}): {e}")
        
        return ""
    
    def crawl_all_members(self):
        """전체 크롤링 실행"""
        print("=== 국회의원 정보 수집 시작 ===")
        
        # 1단계: 검색으로 기본 정보 수집
        print("\n1단계: 검색으로 기본 정보 수집")
        basic_members = self.get_all_members_list()
        
        if not basic_members:
            print("기본 정보 수집 실패. 종료합니다.")
            return []
        
        # 2단계: 각 의원의 상세 정보 수집
        print(f"\n2단계: {len(basic_members)}명의 상세 정보 수집")
        detailed_members = []
        
        for i, member in enumerate(basic_members):
            print(f"[{i+1}/{len(basic_members)}] {member['name']} 상세 정보 수집 중...")
            
            if member["detail_link"]:
                detail_info = self.get_member_detail_info(member["detail_link"], member["name"])
                # 기본 정보와 상세 정보 병합
                member.update(detail_info)
            
            detailed_members.append(member)
            time.sleep(0.5)  # 서버 부하 방지
        
        # 3단계: 결과 저장
        print("\n3단계: 결과 저장")
        
        # JSON 저장
        with open("assembly_members_complete.json", "w", encoding="utf-8") as f:
            json.dump(detailed_members, f, ensure_ascii=False, indent=2)
        
        # CSV 저장
        if detailed_members:
            with open("assembly_members_complete.csv", "w", newline="", encoding="utf-8") as f:
                # 모든 키를 수집해서 필드명으로 사용
                all_keys = set()
                for member in detailed_members:
                    all_keys.update(member.keys())
                
                writer = csv.DictWriter(f, fieldnames=list(all_keys))
                writer.writeheader()
                
                for member in detailed_members:
                    # 리스트 타입 필드는 문자열로 변환
                    row = {}
                    for key, value in member.items():
                        if isinstance(value, list):
                            row[key] = "; ".join(value)
                        else:
                            row[key] = value
                    writer.writerow(row)
        
        print(f"\n=== 수집 완료 ===")
        print(f"총 {len(detailed_members)}명의 국회의원 정보 수집")
        print(f"JSON: assembly_members_complete.json")
        print(f"CSV: assembly_members_complete.csv")
        print(f"이미지: img/ 폴더")
        
        return detailed_members

if __name__ == "__main__":
    crawler = AssemblyCrawlerFixed()
    crawler.crawl_all_members() 