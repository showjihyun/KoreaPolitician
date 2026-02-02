import requests
from bs4 import BeautifulSoup

def debug_assembly_page():
    """국회 정보공개포털 HTML 구조 디버깅"""
    url = "https://open.assembly.go.kr/portal/assm/search/memberSchPage.do"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    try:
        response = requests.get(url, headers=headers)
        print(f"응답 상태코드: {response.status_code}")
        print(f"응답 길이: {len(response.text)}")
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # 페이지 제목 확인
        title = soup.find("title")
        print(f"페이지 제목: {title.get_text() if title else 'None'}")
        
        # 테이블 구조 확인
        tables = soup.find_all("table")
        print(f"테이블 개수: {len(tables)}")
        
        for i, table in enumerate(tables):
            print(f"\n=== 테이블 {i+1} ===")
            rows = table.find_all("tr")
            print(f"행 개수: {len(rows)}")
            
            if rows:
                # 첫 번째 행 (헤더) 확인
                first_row = rows[0]
                headers = [th.get_text(strip=True) for th in first_row.find_all(["th", "td"])]
                print(f"헤더: {headers}")
                
                # 두 번째 행 (데이터) 확인
                if len(rows) > 1:
                    second_row = rows[1]
                    data = [td.get_text(strip=True) for td in second_row.find_all("td")]
                    print(f"첫 번째 데이터: {data}")
        
        # 폼 요소 확인
        forms = soup.find_all("form")
        print(f"\n폼 개수: {len(forms)}")
        
        # 검색 관련 요소 확인
        search_elements = soup.find_all(["input", "select", "button"])
        print(f"입력 요소 개수: {len(search_elements)}")
        
        # 페이지네이션 확인
        pagination = soup.find_all(class_=lambda x: x and ("page" in x.lower() or "paging" in x.lower()))
        print(f"페이지네이션 요소: {len(pagination)}")
        
        # 실제 HTML 일부 출력 (디버깅용)
        print(f"\n=== HTML 샘플 (처음 1000자) ===")
        print(response.text[:1000])
        
    except Exception as e:
        print(f"오류 발생: {e}")

if __name__ == "__main__":
    debug_assembly_page() 