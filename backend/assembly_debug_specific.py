import requests
from bs4 import BeautifulSoup

def debug_list_result_sect():
    """tbody id='list-result-sect' 구조 상세 분석"""
    url = "https://open.assembly.go.kr/portal/assm/search/memberSchPage.do"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    try:
        response = requests.get(url, headers=headers)
        print(f"응답 상태코드: {response.status_code}")
        print(f"응답 길이: {len(response.text)}")
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # 1. tbody id="list-result-sect" 찾기
        target_tbody = soup.find("tbody", id="list-result-sect")
        print(f"\ntbody#list-result-sect 존재 여부: {target_tbody is not None}")
        
        if target_tbody:
            print(f"tbody 내용 길이: {len(target_tbody.get_text())}")
            rows = target_tbody.find_all("tr")
            print(f"tbody 내 tr 개수: {len(rows)}")
            
            if rows:
                for i, row in enumerate(rows[:3]):  # 처음 3개 행만 확인
                    cols = row.find_all("td")
                    print(f"행 {i+1}: td 개수 = {len(cols)}")
                    if cols:
                        for j, col in enumerate(cols):
                            print(f"  td[{j}]: {col.get_text(strip=True)[:50]}")
        
        # 2. 모든 tbody 요소 찾기
        all_tbody = soup.find_all("tbody")
        print(f"\n전체 tbody 개수: {len(all_tbody)}")
        
        for i, tbody in enumerate(all_tbody):
            tbody_id = tbody.get("id", "")
            tbody_class = tbody.get("class", [])
            rows_count = len(tbody.find_all("tr"))
            print(f"tbody[{i}]: id='{tbody_id}', class={tbody_class}, rows={rows_count}")
        
        # 3. 특정 키워드로 검색
        keywords = ["국회의원", "의원명", "정당", "지역구"]
        for keyword in keywords:
            elements = soup.find_all(string=lambda text: text and keyword in text)
            print(f"\n'{keyword}' 포함 텍스트 개수: {len(elements)}")
            if elements:
                for elem in elements[:3]:  # 처음 3개만 출력
                    print(f"  - {elem.strip()[:100]}")
        
        # 4. 폼 데이터 확인 (POST 요청이 필요한지)
        forms = soup.find_all("form")
        print(f"\n폼 개수: {len(forms)}")
        
        for i, form in enumerate(forms):
            action = form.get("action", "")
            method = form.get("method", "GET")
            inputs = form.find_all("input")
            print(f"form[{i}]: action='{action}', method='{method}', inputs={len(inputs)}")
            
            # 숨겨진 입력 필드 확인
            hidden_inputs = form.find_all("input", type="hidden")
            for hidden in hidden_inputs:
                name = hidden.get("name", "")
                value = hidden.get("value", "")
                print(f"  hidden: {name}={value}")
        
        # 5. JavaScript 관련 확인
        scripts = soup.find_all("script")
        print(f"\n스크립트 태그 개수: {len(scripts)}")
        
        for script in scripts:
            if script.string and ("memberSchPage" in script.string or "list-result" in script.string):
                print(f"관련 스크립트 발견:")
                print(script.string[:200] + "...")
                break
        
    except Exception as e:
        print(f"오류 발생: {e}")

if __name__ == "__main__":
    debug_list_result_sect() 