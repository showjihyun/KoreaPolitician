from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json
import csv
import os
import time
import requests
from urllib.parse import urlparse

BASE_URL = "https://open.assembly.go.kr/portal/assm/search/memberSchPage.do"
UNIT_CD = "100022"  # 제22대 국회의원

class AssemblyCrawlerPlaywright:
    def __init__(self):
        if not os.path.exists("img"):
            os.makedirs("img")

    def download_image(self, img_url, member_name):
        if not img_url:
            return ""
        try:
            response = requests.get(img_url, headers={"User-Agent": "Mozilla/5.0"})
            if response.status_code == 200:
                ext = os.path.splitext(urlparse(img_url).path)[1] or ".jpg"
                filename = f"{member_name.replace(' ', '_')}{ext}"
                filepath = os.path.join("img", filename)
                with open(filepath, "wb") as f:
                    f.write(response.content)
                print(f"이미지 다운로드 완료: {filename}")
                return filename
        except Exception as e:
            print(f"이미지 다운로드 실패 ({img_url}): {e}")
        return ""

    def extract_list_tab_info(self, page, page_num):
        """목록보기 탭에서 추가 정보 추출"""
        try:
            # 목록보기 탭 클릭
            tab_btns = page.query_selector_all("#tab-btn-sect a")
            if tab_btns and len(tab_btns) > 0:
                list_tab = tab_btns[0]  # 첫 번째가 목록보기
                if not list_tab.get_attribute("class") or "on" not in list_tab.get_attribute("class"):
                    list_tab.click()
                    print("    목록보기 탭 클릭 완료")
                    time.sleep(1)
            
            # 목록보기 탭의 테이블 로드 대기
            page.wait_for_selector("#list-result-sect tr", timeout=10000)
            time.sleep(1)
            
            # HTML 파싱
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            
            # 목록보기 테이블 행들 추출
            rows = soup.select("#list-result-sect tr")
            list_info = []
            
            for row in rows:
                cells = row.select("td")
                if len(cells) >= 9:
                    name_elem = cells[2].select_one("a.hgNm")
                    name = name_elem.get_text(strip=True) if name_elem else ""
                    
                    info = {
                        "name": name,
                        "rownum": cells[0].get_text(strip=True),  # 번호
                        "unit": cells[1].get_text(strip=True),   # 대수
                        "party": cells[3].get_text(strip=True),  # 정당
                        "committees": cells[4].get_text(strip=True),  # 소속위원회
                        "region": cells[5].get_text(strip=True),      # 지역
                        "gender": cells[6].get_text(strip=True),      # 성별
                        "election_count": cells[7].get_text(strip=True),  # 당선횟수
                        "election_method": cells[8].get_text(strip=True)  # 당선방법
                    }
                    list_info.append(info)
            
            print(f"    목록보기에서 {len(list_info)}명 정보 추출")
            return list_info
            
        except Exception as e:
            print(f"    목록보기 탭 정보 추출 실패: {e}")
            return []

    def crawl_all_members(self):
        print("=== 국회의원 정보 수집 시작 (사진보기+목록보기 통합) ===")
        members = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)  # 디버깅을 위해 headless=False
            page = browser.new_page()
            
            # 첫 페이지 접속
            print(f"  - 1페이지 접속 중...")
            page.goto(f"{BASE_URL}?viewType=photo&assmTerm=22")
            
            # 사진보기 탭 클릭
            try:
                tab_btns = page.query_selector_all("#tab-btn-sect a")
                if tab_btns and len(tab_btns) > 1:
                    photo_tab = tab_btns[1]
                    if not photo_tab.get_attribute("class") or "on" not in photo_tab.get_attribute("class"):
                        photo_tab.click()
                        print("    사진보기 탭 클릭 완료")
                        time.sleep(1)
            except Exception as e:
                print(f"    탭 클릭 실패: {e}")
            
            page_num = 1
            while True:
                print(f"  - {page_num}페이지 크롤링 중...")
                
                # 1. 사진보기 탭에서 기본 정보 + 사진 수집
                try:
                    page.wait_for_selector(".nassem_result_ul > li > a.nassem_reslut_pic", timeout=10000)
                    time.sleep(1)
                except Exception:
                    print(f"    카드 없음: {page_num}페이지 (종료)")
                    break
                
                # 사진보기 탭 HTML 파싱
                html = page.content()
                soup = BeautifulSoup(html, "html.parser")
                cards = soup.select(".nassem_result_ul > li > a.nassem_reslut_pic")
                print(f"    사진보기: {len(cards)}명 발견")
                
                if not cards:
                    print(f"    더 이상 카드 없음, 종료")
                    break
                
                # 사진보기 탭 정보 추출
                photo_info = []
                for idx, card in enumerate(cards):
                    img_elem = card.select_one("div > img")
                    photo_url = img_elem["src"] if img_elem else ""
                    
                    span_elem = card.select_one("span")
                    party = ""
                    name = ""
                    if span_elem:
                        i_elem = span_elem.select_one("i")
                        party = i_elem.get_text(strip=True) if i_elem else ""
                        name = span_elem.get_text(strip=True).replace(party, "").strip()
                    
                    photo_filename = self.download_image(photo_url, name)
                    
                    photo_info.append({
                        "name": name,
                        "party": party,
                        "photo_url": photo_url,
                        "photo_filename": photo_filename,
                        "index": idx
                    })
                
                # 2. 목록보기 탭에서 추가 정보 수집
                list_info = self.extract_list_tab_info(page, page_num)
                
                # 3. 사진보기와 목록보기 정보 매칭 및 통합
                for photo_data in photo_info:
                    # 이름으로 매칭
                    matched_list_data = None
                    for list_data in list_info:
                        if list_data["name"] == photo_data["name"]:
                            matched_list_data = list_data
                            break
                    
                    # monaCd, unitCd 계산
                    monaCd = str((page_num-1)*30 + photo_data["index"] + 1)
                    unitCd = UNIT_CD
                    
                    # 통합 데이터 생성
                    member_data = {
                        "name": photo_data["name"],
                        "party": photo_data["party"],
                        "photo_url": photo_data["photo_url"],
                        "photo_filename": photo_data["photo_filename"],
                        "monaCd": monaCd,
                        "unitCd": unitCd,
                        # 목록보기에서 가져온 추가 정보
                        "rownum": matched_list_data["rownum"] if matched_list_data else "",
                        "unit": matched_list_data["unit"] if matched_list_data else "제22대",
                        "committees": matched_list_data["committees"] if matched_list_data else "",
                        "region": matched_list_data["region"] if matched_list_data else "",
                        "gender": matched_list_data["gender"] if matched_list_data else "",
                        "election_count": matched_list_data["election_count"] if matched_list_data else "",
                        "election_method": matched_list_data["election_method"] if matched_list_data else ""
                    }
                    
                    members.append(member_data)
                    
                    if len(members) >= 300:
                        print(f"    300명 이상 수집, 종료")
                        break
                    
                    time.sleep(0.1)
                
                if len(members) >= 300:
                    break
                
                # 4. 다음 페이지로 이동 (사진보기 탭으로 다시 전환 후)
                # 사진보기 탭으로 다시 전환
                try:
                    tab_btns = page.query_selector_all("#tab-btn-sect a")
                    if tab_btns and len(tab_btns) > 1:
                        photo_tab = tab_btns[1]
                        photo_tab.click()
                        time.sleep(1)
                except Exception:
                    pass
                
                # 다음 페이지로 이동
                next_page_num = page_num + 1
                try:
                    next_page_btn = page.query_selector(f"#pic-sect-pager .page-number:has-text('{next_page_num}')")
                    if next_page_btn:
                        print(f"    {next_page_num}페이지 버튼 클릭 중...")
                        next_page_btn.click()
                        time.sleep(2)
                        page_num = next_page_num
                    else:
                        print(f"    {next_page_num}페이지 버튼 없음, 종료")
                        break
                except Exception as e:
                    print(f"    페이지 이동 실패: {e}")
                    break
            
            browser.close()
        
        print(f"[수집 완료] 총 {len(members)}명")
        print("[저장] JSON, CSV, 이미지")
        
        # JSON 저장
        with open("assembly_members_complete.json", "w", encoding="utf-8") as f:
            json.dump(members, f, ensure_ascii=False, indent=2)
        
        # CSV 저장
        if members:
            with open("assembly_members_complete.csv", "w", newline="", encoding="utf-8") as f:
                all_keys = set()
                for member in members:
                    all_keys.update(member.keys())
                writer = csv.DictWriter(f, fieldnames=list(all_keys))
                writer.writeheader()
                for member in members:
                    row = {}
                    for key, value in member.items():
                        if isinstance(value, list):
                            row[key] = "; ".join(value)
                        else:
                            row[key] = value
                    writer.writerow(row)
        
        print("[저장 완료] (assembly_members_complete.json, assembly_members_complete.csv, img/ 폴더)")
        print(f"=== 전체 수집 완료: 총 {len(members)}명 ===")
        return members

if __name__ == "__main__":
    crawler = AssemblyCrawlerPlaywright()
    crawler.crawl_all_members() 