import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re

def debug_find_profile_image():
    """크롤러의 find_real_profile_image 함수 디버깅"""
    detail_url = "https://www.assembly.go.kr/members/22nd/KIMGIHYEON"
    member_name = "김기현"
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    session = requests.Session()
    session.headers.update(headers)
    
    try:
        response = session.get(detail_url)
        soup = BeautifulSoup(response.text, "html.parser")
        
        print("=== 방법 1: span 태그의 background-image CSS에서 프로필 사진 찾기 ===")
        spans_with_bg = soup.find_all("span", style=lambda x: x and "background-image" in x)
        
        print(f"background-image를 가진 span 태그 개수: {len(spans_with_bg)}")
        
        for i, span in enumerate(spans_with_bg):
            style = span.get("style", "")
            print(f"\nspan[{i+1}]:")
            print(f"  원본 style: {repr(style)}")
            
            if "background-image" in style and "url(" in style:
                # CSS에서 URL 추출 (줄바꿈 처리)
                clean_style = re.sub(r'\s+', ' ', style.replace('\n', ' ').replace('\r', ' '))
                print(f"  정리된 style: {repr(clean_style)}")
                
                url_match = re.search(r"url\(['\"]?([^'\"]+)['\"]?\)", clean_style)
                if url_match:
                    img_path = url_match.group(1).strip()
                    img_url = urljoin(detail_url, img_path)
                    
                    print(f"  추출된 img_path: {repr(img_path)}")
                    print(f"  완전한 img_url: {img_url}")
                    
                    # SNS 아이콘이나 로고가 아닌 실제 프로필 사진인지 확인
                    excluded_keywords = ["facebook", "youtube", "twitter", "instagram", "blog", "ico-", "logo"]
                    is_excluded = any(keyword in img_path.lower() for keyword in excluded_keywords)
                    print(f"  제외 대상인가? {is_excluded}")
                    
                    if not is_excluded:
                        # 파일 크기 확인
                        try:
                            img_response = session.head(img_url)
                            print(f"  HEAD 요청 상태코드: {img_response.status_code}")
                            
                            if img_response.status_code == 200:
                                content_length = img_response.headers.get('content-length')
                                if content_length:
                                    size_kb = int(content_length) / 1024
                                    print(f"  파일 크기: {size_kb:.1f} KB")
                                    
                                    if size_kb > 5:  # 5KB 이상
                                        print(f"  ★ 프로필 사진 후보 발견!")
                                        return img_url
                                else:
                                    print(f"  content-length 헤더 없음")
                        except Exception as e:
                            print(f"  HEAD 요청 실패: {e}")
                            # HEAD 요청 실패해도 URL이 유효해 보이면 시도
                            if any(ext in img_path.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                                print(f"  ★ 확장자 기반으로 프로필 사진 후보 발견!")
                                return img_url
                else:
                    print(f"  URL 매칭 실패")
        
        print(f"\n{member_name}: 프로필 사진을 찾을 수 없습니다.")
        return None
        
    except Exception as e:
        print(f"프로필 사진 검색 중 오류 ({detail_url}): {e}")
        return None

if __name__ == "__main__":
    result = debug_find_profile_image()
    if result:
        print(f"\n최종 결과: {result}")
    else:
        print("\n최종 결과: 프로필 사진을 찾을 수 없음") 