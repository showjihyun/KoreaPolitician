import requests
from bs4 import BeautifulSoup
import json
import csv
import time
import os
from urllib.parse import urljoin, urlparse
import re

class AssemblyDirectCrawler:
    def __init__(self):
        self.base_url = "https://www.assembly.go.kr/members/22nd/"
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
    
    def get_known_member_ids(self):
        """알려진 국회의원 ID 목록 (샘플)"""
        # 실제로는 더 많은 ID가 있지만, 테스트용으로 몇 개만 포함
        known_ids = [
            "KIMGIHYEON",  # 김기현
            "LEEJUNSEOK",  # 이준석 (예시)
            "LEEJEMYUNG",  # 이재명 (예시)
            "YOONSEOKRYUL", # 윤석열은 대통령이므로 국회의원 아님
            "HANDEOKSU",   # 한덕수 (예시)
        ]
        return known_ids
    
    def generate_possible_ids(self, names):
        """이름을 기반으로 가능한 ID 생성"""
        possible_ids = []
        for name in names:
            # 한글 이름을 영어로 변환 (간단한 예시)
            # 실제로는 더 정교한 변환이 필요
            if name == "김기현":
                possible_ids.append("KIMGIHYEON")
            elif name == "이재명":
                possible_ids.append("LEEJEMYUNG")
            elif name == "이준석":
                possible_ids.append("LEEJUNSEOK")
            # 더 많은 매핑 추가 가능
        return possible_ids
    
    def get_member_detail_info(self, member_id):
        """개별 국회의원 상세 정보 수집"""
        detail_url = f"{self.base_url}{member_id}"
        
        try:
            response = self.session.get(detail_url)
            if response.status_code != 200:
                print(f"페이지 접근 실패: {detail_url} (상태코드: {response.status_code})")
                return None
                
            soup = BeautifulSoup(response.text, "html.parser")
            
            info = {
                "member_id": member_id,
                "detail_url": detail_url
            }
            
            # 이름 추출
            name_elem = soup.find("h1")
            if name_elem:
                name_text = name_elem.get_text(strip=True)
                # "국회의원 김기현" -> "김기현"
                name = name_text.replace("국회의원", "").strip()
                info["name"] = name
            
            # 정당 정보
            party_elem = soup.find("span", string=re.compile("국민의힘|더불어민주당|정의당"))
            if not party_elem:
                # 다른 방법으로 정당 찾기
                party_elem = soup.find("div", class_="party")
                if not party_elem:
                    # 텍스트에서 정당 추출
                    text = soup.get_text()
                    parties = ["국민의힘", "더불어민주당", "정의당", "개혁신당", "국민의당"]
                    for party in parties:
                        if party in text:
                            info["party"] = party
                            break
            else:
                info["party"] = party_elem.get_text(strip=True)
            
            # 국회의원 소개 섹션에서 정보 추출
            intro_section = soup.find("div", class_="profile_info") or soup.find("section", class_="member_info")
            if intro_section:
                # 선거구, 소속위원회, 당선횟수 등
                for dt_dd in intro_section.find_all(["dt", "dd", "li"]):
                    text = dt_dd.get_text(strip=True)
                    if "선거구" in text:
                        info["region"] = text.replace("선거구", "").strip()
                    elif "소속위원회" in text:
                        info["committee"] = text.replace("소속위원회", "").strip()
                    elif "당선횟수" in text:
                        info["election_count"] = text.replace("당선횟수", "").strip()
                    elif "전화" in text:
                        info["phone"] = text.replace("사무실 전화", "").strip()
                    elif "이메일" in text or "@" in text:
                        info["email"] = text
            
            # 주요약력 섹션
            career_section = soup.find("div", class_="career") or soup.find("section", class_="career")
            if career_section:
                career_items = career_section.find_all("li")
                careers = [item.get_text(strip=True) for item in career_items if item.get_text(strip=True)]
                info["career"] = careers
            
            # 프로필 사진
            img_elem = soup.find("img", src=re.compile(r"\.(jpg|jpeg|png|gif)", re.I))
            if img_elem and img_elem.get("src"):
                img_url = urljoin(detail_url, img_elem["src"])
                info["photo_url"] = img_url
                
                # 이미지 다운로드
                if info.get("name"):
                    img_filename = self.download_image(img_url, info["name"])
                    info["photo_filename"] = img_filename
            
            # 추가 정보 추출 (텍스트 기반)
            page_text = soup.get_text()
            
            # 연락처 정보 추출
            phone_match = re.search(r'02-\d{3,4}-\d{4}', page_text)
            if phone_match:
                info["phone"] = phone_match.group()
            
            # 이메일 추출
            email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', page_text)
            if email_match:
                info["email"] = email_match.group()
            
            return info
            
        except Exception as e:
            print(f"상세 정보 수집 중 오류 ({detail_url}): {e}")
            return None
    
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
    
    def crawl_known_members(self):
        """알려진 의원 ID로 정보 수집"""
        print("=== 국회의원 정보 수집 시작 (직접 접근 방식) ===")
        
        member_ids = self.get_known_member_ids()
        collected_members = []
        
        for i, member_id in enumerate(member_ids):
            print(f"[{i+1}/{len(member_ids)}] {member_id} 정보 수집 중...")
            
            member_info = self.get_member_detail_info(member_id)
            if member_info:
                collected_members.append(member_info)
                print(f"✓ {member_info.get('name', member_id)} 정보 수집 완료")
            else:
                print(f"✗ {member_id} 정보 수집 실패")
            
            time.sleep(1)  # 서버 부하 방지
        
        # 결과 저장
        if collected_members:
            print(f"\n=== 결과 저장 ===")
            
            # JSON 저장
            with open("assembly_members_direct.json", "w", encoding="utf-8") as f:
                json.dump(collected_members, f, ensure_ascii=False, indent=2)
            
            # CSV 저장
            with open("assembly_members_direct.csv", "w", newline="", encoding="utf-8") as f:
                if collected_members:
                    all_keys = set()
                    for member in collected_members:
                        all_keys.update(member.keys())
                    
                    writer = csv.DictWriter(f, fieldnames=list(all_keys))
                    writer.writeheader()
                    
                    for member in collected_members:
                        row = {}
                        for key, value in member.items():
                            if isinstance(value, list):
                                row[key] = "; ".join(value)
                            else:
                                row[key] = value
                        writer.writerow(row)
            
            print(f"총 {len(collected_members)}명의 국회의원 정보 수집 완료")
            print(f"JSON: assembly_members_direct.json")
            print(f"CSV: assembly_members_direct.csv")
            print(f"이미지: img/ 폴더")
        
        return collected_members
    
    def test_single_member(self, member_id="KIMGIHYEON"):
        """단일 의원 테스트"""
        print(f"=== {member_id} 단일 테스트 ===")
        member_info = self.get_member_detail_info(member_id)
        if member_info:
            print("수집된 정보:")
            for key, value in member_info.items():
                print(f"  {key}: {value}")
        else:
            print("정보 수집 실패")
        return member_info

if __name__ == "__main__":
    crawler = AssemblyDirectCrawler()
    
    # 먼저 단일 의원 테스트
    print("1. 단일 의원 테스트")
    test_result = crawler.test_single_member("KIMGIHYEON")
    
    if test_result:
        print("\n2. 알려진 의원들 정보 수집")
        crawler.crawl_known_members()
    else:
        print("단일 테스트 실패. 크롤링을 중단합니다.") 