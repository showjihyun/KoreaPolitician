import requests
from bs4 import BeautifulSoup
import json
import time
from urllib.parse import urljoin

class PhotoTabAnalyzer:
    def __init__(self):
        self.base_url = "https://open.assembly.go.kr/portal/assm/search/memberSchPage.do"
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
    
    def analyze_photo_tab(self, page=1):
        """사진보기 탭 분석"""
        params = {
            "currentPage": page,
            "viewType": "photo"  # 사진보기 탭
        }
        
        try:
            print(f"=== 사진보기 탭 {page}페이지 분석 ===")
            response = self.session.get(self.base_url, params=params)
            soup = BeautifulSoup(response.text, "html.parser")
            
            # 전체 HTML을 파일로 저장 (디버깅용)
            with open(f"photo_tab_page_{page}.html", "w", encoding="utf-8") as f:
                f.write(response.text)
            print(f"전체 HTML이 photo_tab_page_{page}.html에 저장되었습니다.")
            
            # HTML 구조 전체 출력 (디버깅용)
            print("\n=== HTML 구조 분석 ===")
            
            # 1. 사진 관련 클래스나 ID 찾기
            photo_elements = soup.find_all(class_=lambda x: x and any(
                keyword in str(x).lower() for keyword in ["photo", "picture", "image", "member", "card"]
            ))
            
            print(f"사진 관련 요소 개수: {len(photo_elements)}")
            
            for i, elem in enumerate(photo_elements[:10]):  # 처음 10개만
                print(f"\n요소 {i+1}:")
                print(f"  태그: {elem.name}")
                print(f"  클래스: {elem.get('class', [])}")
                print(f"  ID: {elem.get('id', '')}")
                print(f"  내용 (처음 200자): {elem.get_text()[:200]}")
            
            # 2. 모든 이미지 태그 분석
            images = soup.find_all("img")
            print(f"\n=== 이미지 태그 분석 (총 {len(images)}개) ===")
            
            for i, img in enumerate(images):
                src = img.get("src", "")
                alt = img.get("alt", "")
                title = img.get("title", "")
                class_attr = img.get("class", [])
                
                # 절대 URL로 변환
                full_url = urljoin(self.base_url, src) if src else ""
                
                print(f"\n이미지 {i+1}:")
                print(f"  src: {src}")
                print(f"  full_url: {full_url}")
                print(f"  alt: {alt}")
                print(f"  title: {title}")
                print(f"  class: {class_attr}")
                
                # 부모 요소 확인
                parent = img.parent
                if parent:
                    parent_class = parent.get("class", [])
                    parent_id = parent.get("id", "")
                    print(f"  부모 태그: {parent.name}")
                    print(f"  부모 class: {parent_class}")
                    print(f"  부모 id: {parent_id}")
                
                # 이미지 크기 확인
                if full_url and full_url.startswith("http"):
                    try:
                        img_response = self.session.head(full_url)
                        if img_response.status_code == 200:
                            content_length = img_response.headers.get('content-length')
                            if content_length:
                                size_kb = int(content_length) / 1024
                                print(f"  파일 크기: {size_kb:.1f} KB")
                                
                                # 큰 이미지일 가능성이 높은 것들 표시
                                if size_kb > 10:  # 10KB 이상
                                    print(f"  ★ 프로필 사진 후보 (큰 이미지)")
                    except:
                        print(f"  파일 크기 확인 실패")
            
            # 3. JavaScript나 data 속성에서 이미지 정보 찾기
            print(f"\n=== data 속성 분석 ===")
            data_elements = soup.find_all(attrs=lambda attrs: attrs and any(
                key.startswith('data-') for key in attrs.keys()
            ))
            
            for i, elem in enumerate(data_elements[:10]):  # 처음 10개만
                print(f"\ndata 속성 요소 {i+1}:")
                print(f"  태그: {elem.name}")
                data_attrs = {k: v for k, v in elem.attrs.items() if k.startswith('data-')}
                for key, value in data_attrs.items():
                    print(f"  {key}: {value}")
            
            # 4. 스크립트 태그에서 이미지 URL 패턴 찾기
            print(f"\n=== 스크립트 분석 ===")
            scripts = soup.find_all("script")
            
            for i, script in enumerate(scripts):
                script_content = script.get_text()
                if script_content and any(keyword in script_content.lower() for keyword in 
                                        ["image", "photo", "picture", ".jpg", ".png", ".gif"]):
                    print(f"\n스크립트 {i+1} (이미지 관련):")
                    print(f"  내용 (처음 500자): {script_content[:500]}")
            
            # 5. 특정 패턴으로 멤버 카드 찾기
            print(f"\n=== 멤버 카드 패턴 분석 ===")
            
            # 다양한 선택자 시도
            selectors = [
                ".photo_list .member_card",
                ".member_card",
                ".photo_list li",
                ".photo_list div",
                "li[class*='member']",
                "div[class*='member']",
                "div[class*='photo']",
                "ul li",
                ".list li",
                "#list-result-sect",
                "tbody#list-result-sect",
                ".nassem_result_picture"
            ]
            
            for selector in selectors:
                try:
                    cards = soup.select(selector)
                    if cards:
                        print(f"\n선택자 '{selector}' 결과: {len(cards)}개")
                        
                        for i, card in enumerate(cards[:3]):  # 처음 3개만
                            print(f"  카드 {i+1}:")
                            print(f"    태그: {card.name}")
                            print(f"    클래스: {card.get('class', [])}")
                            print(f"    내용 (처음 200자): {card.get_text()[:200]}")
                            
                            # 카드 내부의 이미지 찾기
                            card_images = card.find_all("img")
                            for j, img in enumerate(card_images):
                                src = img.get("src", "")
                                full_url = urljoin(self.base_url, src) if src else ""
                                print(f"      이미지 {j+1}: {full_url}")
                except:
                    continue
            
            # 6. 특정 텍스트 패턴 찾기 (의원 이름이나 정당명)
            print(f"\n=== 텍스트 패턴 분석 ===")
            page_text = soup.get_text()
            
            # 정당명이 포함된 부분 찾기
            parties = ["더불어민주당", "국민의힘", "정의당", "개혁신당"]
            for party in parties:
                if party in page_text:
                    print(f"정당명 '{party}' 발견")
            
            # 7. 폼 데이터나 hidden input 확인
            print(f"\n=== 폼 데이터 분석 ===")
            forms = soup.find_all("form")
            for i, form in enumerate(forms):
                print(f"\n폼 {i+1}:")
                print(f"  action: {form.get('action', '')}")
                print(f"  method: {form.get('method', '')}")
                
                inputs = form.find_all("input")
                for j, inp in enumerate(inputs):
                    print(f"    input {j+1}: name={inp.get('name', '')}, value={inp.get('value', '')}, type={inp.get('type', '')}")
            
            return soup
            
        except Exception as e:
            print(f"사진보기 페이지 {page} 분석 중 오류: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def find_hover_image_patterns(self, soup):
        """마우스 호버 시 나타나는 이미지 패턴 찾기"""
        print(f"\n=== 호버 이미지 패턴 분석 ===")
        
        # 1. title 속성에 이미지 URL이 있는지 확인
        title_elements = soup.find_all(attrs={"title": True})
        for elem in title_elements:
            title = elem.get("title", "")
            if any(ext in title.lower() for ext in [".jpg", ".jpeg", ".png", ".gif"]):
                print(f"title 속성에서 이미지 발견: {title}")
        
        # 2. data-* 속성에 이미지 URL이 있는지 확인
        data_image_elements = soup.find_all(attrs=lambda attrs: attrs and any(
            "image" in key.lower() or "photo" in key.lower() or "picture" in key.lower()
            for key in attrs.keys() if key.startswith('data-')
        ))
        
        for elem in data_image_elements:
            for key, value in elem.attrs.items():
                if key.startswith('data-') and any(ext in str(value).lower() for ext in [".jpg", ".jpeg", ".png", ".gif"]):
                    print(f"data 속성에서 이미지 발견: {key}={value}")
        
        # 3. CSS background-image 패턴
        style_elements = soup.find_all(attrs={"style": lambda x: x and "background-image" in x})
        for elem in style_elements:
            style = elem.get("style", "")
            print(f"background-image 발견: {style}")
    
    def run_analysis(self):
        """전체 분석 실행"""
        print("=== 국회의원 사진보기 탭 분석 시작 ===")
        
        # 첫 번째 페이지 분석
        soup = self.analyze_photo_tab(1)
        
        if soup:
            # 호버 패턴 분석
            self.find_hover_image_patterns(soup)
        
        print("\n=== 분석 완료 ===")

if __name__ == "__main__":
    analyzer = PhotoTabAnalyzer()
    analyzer.run_analysis() 