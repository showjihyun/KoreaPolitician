import requests
import json
import time

def fetch_all_members():
    url = "https://open.assembly.go.kr/portal/assm/search/searchAssmMemberSch.do"
    all_data = []
    
    # Based on intercepted data:
    # statusCd=&unitCd=100022&gubunId=MA&excelNm=&schHgNm=&schPoly=&schCmit=&schUpOrig=&schOrig=&schSexGbn=&schAge=&schReeleGbn=&schElectGbn=&rows=100&page=1
    
    for page in range(1, 4): # If 100 rows per page, 3 pages cover 296 members
        payload = {
            "unitCd": "100022",
            "gubunId": "MA",
            "rows": "100",
            "page": str(page)
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest"
        }
        
        print(f"Fetching page {page}...")
        response = requests.post(url, data=payload, headers=headers)
        if response.status_code == 200:
            res_json = response.json()
            data = res_json.get("data", [])
            print(f"  Got {len(data)} members")
            all_data.extend(data)
            if len(data) < 100:
                break
        else:
            print(f"  Error: {response.status_code}")
            break
        time.sleep(1)
        
    return all_data

if __name__ == "__main__":
    members = fetch_all_members()
    print(f"Total fetched: {len(members)}")
    
    # Save to final path
    save_path = "data/assembly_members_complete_api.json"
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(members, f, ensure_ascii=False, indent=2)
    print(f"Saved to {save_path}")
