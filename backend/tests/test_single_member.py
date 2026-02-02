import requests
from bs4 import BeautifulSoup

def test_kimgihyeon_page():
    """김기현 의원 페이지 HTML 구조 분석"""
    url = "https://www.assembly.go.kr/members/22nd/KIMGIHYEON"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    try:
        response = requests.get(url, headers=headers)
        print(f"응답 상태코드: {response.status_code}")
        print(f"응답 길이: {len(response.text)}")
        
        if response.status_code != 200:
            print("페이지 접근 실패")
            return
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # 페이지 제목 확인
        title = soup.find("title")
        print(f"페이지 제목: {title.get_text() if title else 'None'}")
        
        # 이름 추출 시도
        print("\n=== 이름 추출 시도 ===")
        h1_tags = soup.find_all("h1")
        for i, h1 in enumerate(h1_tags):
            print(f"h1[{i}]: {h1.get_text(strip=True)}")
        
        h2_tags = soup.find_all("h2")
        for i, h2 in enumerate(h2_tags):
            print(f"h2[{i}]: {h2.get_text(strip=True)}")
        
        # 클래스명으로 검색
        name_candidates = soup.find_all(class_=lambda x: x and ("name" in str(x).lower() or "title" in str(x).lower()))
        for i, elem in enumerate(name_candidates):
            print(f"name/title class[{i}]: {elem.get_text(strip=True)[:50]}")
        
        # 정당 정보 추출 시도
        print("\n=== 정당 정보 추출 시도 ===")
        party_keywords = ["국민의힘", "더불어민주당", "정의당", "개혁신당"]
        for keyword in party_keywords:
            elements = soup.find_all(string=lambda text: text and keyword in text)
            if elements:
                print(f"'{keyword}' 발견: {len(elements)}개")
                for elem in elements[:2]:
                    parent = elem.parent if elem.parent else None
                    print(f"  - {elem.strip()} (부모: {parent.name if parent else 'None'})")
        
        # 프로필 관련 클래스 찾기
        print("\n=== 프로필 관련 요소 ===")
        profile_elements = soup.find_all(class_=lambda x: x and "profile" in str(x).lower())
        for i, elem in enumerate(profile_elements):
            print(f"profile class[{i}]: {elem.name} - {elem.get('class')} - {elem.get_text(strip=True)[:100]}")
        
        # 테이블 구조 확인
        print("\n=== 테이블 구조 ===")
        tables = soup.find_all("table")
        for i, table in enumerate(tables):
            rows = table.find_all("tr")
            print(f"table[{i}]: {len(rows)}개 행")
            if rows:
                for j, row in enumerate(rows[:3]):
                    cells = row.find_all(["td", "th"])
                    cell_texts = [cell.get_text(strip=True) for cell in cells]
                    print(f"  row[{j}]: {cell_texts}")
        
        # dl/dt/dd 구조 확인
        print("\n=== dl/dt/dd 구조 ===")
        dls = soup.find_all("dl")
        for i, dl in enumerate(dls):
            dts = dl.find_all("dt")
            dds = dl.find_all("dd")
            print(f"dl[{i}]: {len(dts)}개 dt, {len(dds)}개 dd")
            for dt, dd in zip(dts, dds):
                print(f"  {dt.get_text(strip=True)}: {dd.get_text(strip=True)}")
        
        # 이미지 확인
        print("\n=== 이미지 ===")
        images = soup.find_all("img")
        for i, img in enumerate(images):
            src = img.get("src", "")
            alt = img.get("alt", "")
            print(f"img[{i}]: src={src[:50]}, alt={alt}")
        
        # 전체 텍스트에서 키워드 검색
        print("\n=== 전체 텍스트 키워드 검색 ===")
        page_text = soup.get_text()
        keywords = ["김기현", "국민의힘", "부산", "선거구", "위원회"]
        for keyword in keywords:
            if keyword in page_text:
                print(f"'{keyword}' 발견됨")
            else:
                print(f"'{keyword}' 없음")
        
    except Exception as e:
        print(f"오류 발생: {e}")

if __name__ == "__main__":
    test_kimgihyeon_page() 