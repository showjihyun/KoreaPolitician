import requests
from bs4 import BeautifulSoup
import json
import time
from urllib.parse import urljoin

class PhotoTabPostAnalyzer:
    def __init__(self):
        self.base_url = "https://open.assembly.go.kr/portal/assm/search/memberSchPage.do"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://open.assembly.go.kr/portal/assm/search/memberSchPage.do"
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
    
    def get_photo_tab_with_post(self, page=1):
        """POST 요청으로 사진보기 탭 데이터 가져오기"""
        
        # 먼저 GET 요청으로 초기 페이지 로드하여 세션 설정
        print("초기 페이지 로드 중...")
        initial_response = self.session.get(self.base_url)
        
        # POST 데이터 준비
        post_data = {
            "currentPage": page,
            "viewType": "photo",
            "searchCondition": "",
            "searchKeyword": "",
            "assmTerm": "22",  # 22대 국회
            "polyNm": "",
            "cmitNm": "",
            "origNm": "",
            "gender": "",
            "age": "",
            "reeleGbnNm": "",
            "eleGbnNm": ""
        }
        
        try:
            print(f"=== POST 요청으로 사진보기 탭 {page}페이지 분석 ===")
            response = self.session.post(self.base_url, data=post_data)
            
            print(f"응답 상태코드: {response.status_code}")
            print(f"응답 헤더: {dict(response.headers)}")
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # 전체 HTML을 파일로 저장
            with open(f"photo_tab_post_page_{page}.html", "w", encoding="utf-8") as f:
                f.write(response.text)
            print(f"POST 응답 HTML이 photo_tab_post_page_{page}.html에 저장되었습니다.")
            
            # 사진보기 결과 영역 확인
            photo_result = soup.find("div", class_="nassem_result_picture")
            if photo_result:
                print(f"\n사진보기 결과 영역 발견:")
                print(f"  스타일: {photo_result.get('style', '')}")
                print(f"  내용 길이: {len(photo_result.get_text())}")
                print(f"  내용 (처음 500자): {photo_result.get_text()[:500]}")
                
                # 사진보기 영역 내의 모든 이미지 찾기
                images = photo_result.find_all("img")
                print(f"\n사진보기 영역 내 이미지 개수: {len(images)}")
                
                for i, img in enumerate(images):
                    src = img.get("src", "")
                    alt = img.get("alt", "")
                    title = img.get("title", "")
                    
                    full_url = urljoin(self.base_url, src) if src else ""
                    
                    print(f"\n  이미지 {i+1}:")
                    print(f"    src: {src}")
                    print(f"    full_url: {full_url}")
                    print(f"    alt: {alt}")
                    print(f"    title: {title}")
                    
                    # 부모 요소 확인
                    parent = img.parent
                    if parent:
                        print(f"    부모 태그: {parent.name}")
                        print(f"    부모 클래스: {parent.get('class', [])}")
                
                # 링크나 카드 형태 요소 찾기
                links = photo_result.find_all("a")
                print(f"\n사진보기 영역 내 링크 개수: {len(links)}")
                
                for i, link in enumerate(links[:10]):  # 처음 10개만
                    href = link.get("href", "")
                    text = link.get_text(strip=True)
                    
                    print(f"\n  링크 {i+1}:")
                    print(f"    href: {href}")
                    print(f"    텍스트: {text}")
                    
                    # 링크 내부의 이미지 확인
                    link_images = link.find_all("img")
                    for j, img in enumerate(link_images):
                        img_src = img.get("src", "")
                        img_full_url = urljoin(self.base_url, img_src) if img_src else ""
                        print(f"      이미지 {j+1}: {img_full_url}")
            
            else:
                print("사진보기 결과 영역을 찾을 수 없습니다.")
            
            # 전체 페이지에서 의원 관련 이미지 패턴 찾기
            print(f"\n=== 전체 페이지 이미지 분석 ===")
            all_images = soup.find_all("img")
            
            for i, img in enumerate(all_images):
                src = img.get("src", "")
                alt = img.get("alt", "")
                
                # 의원 사진일 가능성이 있는 이미지 필터링
                if src and any(keyword in src.lower() for keyword in ["member", "assm", "profile", "photo"]):
                    full_url = urljoin(self.base_url, src)
                    print(f"\n의원 관련 이미지 후보 {i+1}:")
                    print(f"  src: {src}")
                    print(f"  full_url: {full_url}")
                    print(f"  alt: {alt}")
            
            # JavaScript 변수나 데이터 확인
            print(f"\n=== JavaScript 데이터 분석 ===")
            scripts = soup.find_all("script")
            
            for script in scripts:
                script_content = script.get_text()
                if script_content and any(keyword in script_content.lower() for keyword in 
                                        ["member", "photo", "image", "picture", ".jpg", ".png"]):
                    print(f"\n관련 스크립트 발견:")
                    print(f"  내용 (처음 300자): {script_content[:300]}")
            
            return soup
            
        except Exception as e:
            print(f"POST 요청 중 오류: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def try_ajax_request(self):
        """AJAX 요청으로 사진 데이터 가져오기 시도"""
        print(f"\n=== AJAX 요청 시도 ===")
        
        # 가능한 AJAX 엔드포인트들
        ajax_urls = [
            "/portal/assm/search/memberSchPageAjax.do",
            "/portal/assm/search/memberPhotoList.do",
            "/portal/assm/search/memberList.do",
            "/ajax/assm/search/memberSchPage.do"
        ]
        
        ajax_data = {
            "currentPage": 1,
            "viewType": "photo",
            "assmTerm": "22"
        }
        
        for ajax_url in ajax_urls:
            try:
                full_ajax_url = urljoin(self.base_url, ajax_url)
                print(f"\nAJAX 요청 시도: {full_ajax_url}")
                
                response = self.session.post(full_ajax_url, data=ajax_data)
                print(f"  상태코드: {response.status_code}")
                
                if response.status_code == 200:
                    content = response.text
                    print(f"  응답 길이: {len(content)}")
                    print(f"  응답 내용 (처음 200자): {content[:200]}")
                    
                    # JSON 응답인지 확인
                    try:
                        json_data = response.json()
                        print(f"  JSON 응답 발견!")
                        print(f"  JSON 키들: {list(json_data.keys()) if isinstance(json_data, dict) else 'Not a dict'}")
                        
                        # 파일로 저장
                        with open(f"ajax_response_{ajax_url.replace('/', '_')}.json", "w", encoding="utf-8") as f:
                            json.dump(json_data, f, ensure_ascii=False, indent=2)
                        
                    except:
                        # HTML 응답인 경우
                        if "<" in content and ">" in content:
                            with open(f"ajax_response_{ajax_url.replace('/', '_')}.html", "w", encoding="utf-8") as f:
                                f.write(content)
                            print(f"  HTML 응답 저장됨")
                
            except Exception as e:
                print(f"  AJAX 요청 실패: {e}")
    
    def run_analysis(self):
        """전체 분석 실행"""
        print("=== 국회의원 사진보기 탭 POST 분석 시작 ===")
        
        # POST 요청으로 사진보기 탭 분석
        soup = self.get_photo_tab_with_post(1)
        
        # AJAX 요청 시도
        self.try_ajax_request()
        
        print("\n=== 분석 완료 ===")

if __name__ == "__main__":
    analyzer = PhotoTabPostAnalyzer()
    analyzer.run_analysis() 