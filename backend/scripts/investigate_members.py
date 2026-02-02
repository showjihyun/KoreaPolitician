import json, os, requests
print("--- Investigation ---")
try:
    with open(os.path.join(os.path.dirname(__file__), '../../data/assembly_members_complete.json'), encoding='utf-8') as f: data = json.load(f)
    names = [m.get('name', 'N/A') for m in data]
    parties = set(m.get('party', 'N/A') for m in data)
    print(f"Count: {len(data)}")
    print(f"Prominent check (MP expected): Cho Kuk:{'조국' in names}, Lee Jae-myung:{'이재명' in names}")
    print(f"Incorrect check (Non-MP expected): Yoon Suk-yeol:{'윤석열' in names}, Han Dong-hoon:{'한동훈' in names}")
    print(f"Parties in database: {sorted(list(parties))}")
    print(f"Last 5 names: {names[-5:]}")
    # Satellite parties merged into main parties after election start
    satellite = ['국민의미래', '더불어민주연합', '더불어시민당']
    print(f"Satellite parties found: {[s for s in satellite if s in parties]}")
    
    # Check for 21st assembly members who are no longer in the 22nd
    retired_21st = ['박병석', '김진표', '심상정', '최강욱', '유호정']
    print(f"Found retired 21st members: {[n for n in retired_21st if n in names]}")

except Exception as e: print(f"File Error: {e}")

try:
    # Use official Open API with UNIT_CD 100022 (22nd Assembly)
    # nwvrqwxyaytdsfvhu: 국회의원 현황
    url = "https://open.assembly.go.kr/portal/openapi/nwvrqwxyaytdsfvhu?Type=json&pIndex=1&pSize=10&UNIT_CD=100022"
    r = requests.get(url, timeout=10)
    if r.status_code == 200:
        res = r.json()
        if 'nwvrqwxyaytdsfvhu' in res:
            row = res['nwvrqwxyaytdsfvhu'][1]['row'][0]
            print(f"API Success: Found {row.get('HG_NM')} ({row.get('POLY_NM')}) via nwvrqwxyaytdsfvhu")
        else: print(f"API Structure Error: {res.keys()}")
    else: print(f"API HTTP Error: {r.status_code}")
except Exception as e: print(f"API Connectivity Error: {e}")
