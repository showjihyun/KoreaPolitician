import json
import os

def merge_data():
    # Load API data
    api_path = "data/assembly_members_complete_api.json"
    if not os.path.exists(api_path):
        print("API data not found")
        return

    with open(api_path, "r", encoding="utf-8") as f:
        api_members = json.load(f)

    # Load existing data to preserve any specific fields if needed
    complete_path = "data/assembly_members_complete.json"
    existing_members = []
    if os.path.exists(complete_path):
        with open(complete_path, "r", encoding="utf-8") as f:
            existing_members = json.load(f)

    # Map name to existing data (to preserve photo_filename if already downloaded)
    existing_map = {m['name']: m for m in existing_members if m.get('name')}

    merged_members = []
    for api_m in api_members:
        name = api_m.get("hgNm")
        mona_cd = api_m.get("monaCd")
        
        # Merge with existing
        existing = existing_map.get(name, {})
        
        merged = {
            "name": name,
            "hjNm": api_m.get("hjNm"),
            "engNm": api_m.get("engNm"),
            "monaCd": mona_cd,
            "party": api_m.get("polyNm"),
            "region": api_m.get("origNm"),
            "gender": api_m.get("sexGbnNm"),
            "election_count": api_m.get("reeleGbnNm"),
            "photo_url": api_m.get("deptImgUrl"),
            "photo_filename": existing.get("photo_filename") or f"{name}.jpg",
            "committees": api_m.get("cmitNm"),
            "telNo": api_m.get("telNo"),
            "eMail": api_m.get("eMail"),
            "homepage": api_m.get("homepage"),
            "staff": api_m.get("staff"),
            "secretary": api_m.get("secretary"),
            "secretary2": api_m.get("secretary2"),
            "bthDate": api_m.get("bthDate"),
            "linkUrl": api_m.get("linkUrl"),
            "unitCd": "100022"
        }
        merged_members.append(merged)

    # Save back
    with open(complete_path, "w", encoding="utf-8") as f:
        json.dump(merged_members, f, ensure_ascii=False, indent=2)
    
    print(f"Merged {len(merged_members)} members with full API fields to {complete_path}")

if __name__ == "__main__":
    merge_data()
