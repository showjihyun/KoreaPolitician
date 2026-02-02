import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

def analyze_profile_images():
    """김기현 의원 페이지의 모든 이미지 분석"""
    url = "https://www.assembly.go.kr/members/22nd/KIMGIHYEON"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        
        print("=== 모든 이미지 분석 ===")
        images = soup.find_all("img")
        
        for i, img in enumerate(images):
            src = img.get("src", "")
            alt = img.get("alt", "")
            title = img.get("title", "")
            class_attr = img.get("class", [])
            
            # 절대 URL로 변환
            full_url = urljoin(url, src) if src else ""
            
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
            
            # 이미지 크기 확인 (실제 다운로드해서 크기 체크)
            if full_url and full_url.startswith("http"):
                try:
                    img_response = requests.head(full_url, headers=headers)
                    content_length = img_response.headers.get('content-length')
                    if content_length:
                        size_kb = int(content_length) / 1024
                        print(f"  파일 크기: {size_kb:.1f} KB")
                        
                        # 큰 이미지일 가능성이 높은 것들 표시
                        if size_kb > 10:  # 10KB 이상
                            print(f"  ★ 프로필 사진 후보 (큰 이미지)")
                except:
                    print(f"  파일 크기 확인 실패")
        
        # 특정 패턴으로 프로필 사진 찾기
        print("\n=== 프로필 사진 후보 검색 ===")
        
        # 1. 클래스명에 photo, profile, member 포함된 이미지
        profile_candidates = soup.find_all("img", class_=lambda x: x and any(
            keyword in str(x).lower() for keyword in ["photo", "profile", "member", "picture"]
        ))
        
        for i, img in enumerate(profile_candidates):
            src = img.get("src", "")
            full_url = urljoin(url, src)
            print(f"후보 {i+1} (클래스 기반): {full_url}")
        
        # 2. alt 속성에 이름이나 프로필 관련 키워드 포함
        name_candidates = soup.find_all("img", alt=lambda x: x and any(
            keyword in str(x).lower() for keyword in ["김기현", "프로필", "사진", "의원"]
        ))
        
        for i, img in enumerate(name_candidates):
            src = img.get("src", "")
            full_url = urljoin(url, src)
            print(f"후보 {i+1} (alt 기반): {full_url}")
        
        # 3. 특정 디렉토리 패턴 (보통 프로필 사진은 특정 폴더에 저장됨)
        directory_candidates = soup.find_all("img", src=lambda x: x and any(
            keyword in str(x).lower() for keyword in ["profile", "member", "photo", "picture", "portrait"]
        ))
        
        for i, img in enumerate(directory_candidates):
            src = img.get("src", "")
            full_url = urljoin(url, src)
            print(f"후보 {i+1} (디렉토리 기반): {full_url}")
        
        # 4. 큰 이미지 파일들 (프로필 사진은 보통 크기가 큼)
        print("\n=== 큰 이미지 파일들 ===")
        for i, img in enumerate(images):
            src = img.get("src", "")
            full_url = urljoin(url, src) if src else ""
            
            if full_url and full_url.startswith("http"):
                try:
                    img_response = requests.head(full_url, headers=headers)
                    content_length = img_response.headers.get('content-length')
                    if content_length:
                        size_kb = int(content_length) / 1024
                        if size_kb > 5:  # 5KB 이상인 이미지들
                            print(f"큰 이미지: {full_url} ({size_kb:.1f} KB)")
                except:
                    pass
        
    except Exception as e:
        print(f"오류 발생: {e}")

if __name__ == "__main__":
    analyze_profile_images() 