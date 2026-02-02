import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re

def test_background_image():
    """김기현 의원 페이지에서 background-image 스타일 찾기"""
    url = "https://www.assembly.go.kr/members/22nd/KIMGIHYEON"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        
        print("=== background-image 스타일을 가진 요소 찾기 ===")
        
        # 모든 요소에서 style 속성 확인
        all_elements_with_style = soup.find_all(attrs={"style": True})
        
        bg_image_count = 0
        for element in all_elements_with_style:
            style = element.get("style", "")
            if "background-image" in style:
                bg_image_count += 1
                print(f"\n{bg_image_count}. {element.name} 태그:")
                print(f"   style: {style}")
                print(f"   class: {element.get('class', [])}")
                print(f"   id: {element.get('id', '')}")
                print(f"   텍스트: {element.get_text(strip=True)[:50]}")
                
                # URL 추출
                url_match = re.search(r"url\(['\"]?([^'\"]+)['\"]?\)", style)
                if url_match:
                    img_path = url_match.group(1)
                    img_url = urljoin(url, img_path)
                    print(f"   이미지 URL: {img_url}")
        
        if bg_image_count == 0:
            print("background-image 스타일을 가진 요소가 없습니다.")
        
        # span 태그만 따로 확인
        print(f"\n=== span 태그 중 style 속성을 가진 것들 ===")
        spans_with_style = soup.find_all("span", attrs={"style": True})
        
        for i, span in enumerate(spans_with_style):
            style = span.get("style", "")
            print(f"\nspan[{i+1}]:")
            print(f"   style: {style}")
            print(f"   class: {span.get('class', [])}")
            print(f"   텍스트: {span.get_text(strip=True)[:50]}")
        
        # 클래스명이 "img"인 요소들 확인
        print(f"\n=== class='img'인 요소들 ===")
        img_class_elements = soup.find_all(class_="img")
        
        for i, element in enumerate(img_class_elements):
            print(f"\n{element.name}[{i+1}] (class='img'):")
            print(f"   style: {element.get('style', '')}")
            print(f"   class: {element.get('class', [])}")
            print(f"   텍스트: {element.get_text(strip=True)[:50]}")
        
        # 전체 HTML에서 "background-image" 문자열 검색
        print(f"\n=== HTML에서 'background-image' 문자열 검색 ===")
        html_content = response.text
        bg_image_occurrences = html_content.count("background-image")
        print(f"'background-image' 발견 횟수: {bg_image_occurrences}")
        
        if bg_image_occurrences > 0:
            # 해당 부분 추출
            lines = html_content.split('\n')
            for i, line in enumerate(lines):
                if "background-image" in line:
                    print(f"라인 {i+1}: {line.strip()}")
        
    except Exception as e:
        print(f"오류 발생: {e}")

if __name__ == "__main__":
    test_background_image() 