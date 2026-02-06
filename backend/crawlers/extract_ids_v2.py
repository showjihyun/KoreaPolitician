from playwright.sync_api import sync_playwright
import json
import time
import re

def extract_ids():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        url = "https://open.assembly.go.kr/portal/assm/search/memberSchPage.do?viewType=list&assmTerm=22"
        print(f"Navigating to {url}")
        page.goto(url)
        
        # Wait for the table to load
        try:
            page.wait_for_selector("#list-result-sect tr", timeout=30000)
        except:
            print("Initial table timeout")
        
        # Select "100개씩 보기" if possible to reduce page turns
        try:
            page.select_option("#page_unit", "100")
            page.wait_for_timeout(3000)
        except:
            print("Could not select 100 per page")

        all_members = []
        
        page_num = 1
        while len(all_members) < 300:
            print(f"Processing page {page_num}...")
            
            # Extract names and IDs using evaluate
            # We will use the fact that clicking the link eventually calls memberDetail(monaCd)
            # We'll try to find the monaCd by looking at the page's source OR by intercepting the click
            
            # New strategy: Search for 'memberDetail(' in the whole page source
            # and map it to nearby names
            
            members = page.evaluate("""() => {
                const rows = Array.from(document.querySelectorAll('#list-result-sect tr'));
                return rows.map(tr => {
                    const a = tr.querySelector('a.hgNm');
                    if (!a) return null;
                    const name = a.innerText.trim();
                    const onclick = a.getAttribute('onclick') || '';
                    const monaCdMatch = onclick.match(/memberDetail\\('([^']+)'\\)/);
                    const monaCd = monaCdMatch ? monaCdMatch[1] : '';
                    
                    const cells = Array.from(tr.querySelectorAll('td'));
                    const party = cells[3] ? cells[3].innerText.trim() : '';
                    const region = cells[5] ? cells[5].innerText.trim() : '';
                    
                    return { name, monaCd, party, region };
                }).filter(m => m !== null);
            }""")
            
            # If monaCd is STILL empty, it means it's not in the onclick.
            # Let's check the href of the detail link if we can find it.
            
            for m in members:
                if not m['monaCd']:
                    # Fallback: maybe it's in a different element?
                    pass
            
            all_members.extend(members)
            print(f"Found {len(members)} members on page {page_num}. Total: {len(all_members)}")
            
            if len(members) == 0:
                break
                
            # Try to go to next page
            next_page = page_num + 1
            try:
                # Find the next page button in the pager
                next_btn = page.query_selector(f"#list-sect-pager a:text('{next_page}')")
                if not next_btn:
                    # Try to find the "Next" Arrow button (usually class 'next' or similar)
                    next_btn = page.query_selector("#list-sect-pager .page-next, #list-sect-pager a.next")
                    if next_btn:
                        print(f"Clicking Next Group button to reach page {next_page}...")
                        next_btn.click()
                        time.sleep(3)
                        # After clicking NEXT, we still might need to click the specific page number if it didn't auto-load
                        # but usually it goes to the first page of the next group (e.g., 11)
                        page_num = next_page
                    else:
                        print("No more pages and no 'Next' button found")
                        break
                else:
                    next_btn.click()
                    time.sleep(3)
                    page_num = next_page
            except Exception as e:
                print(f"Error moving to next page: {e}")
                break
                
        browser.close()
        return all_members

if __name__ == "__main__":
    members = extract_ids()
    with open("extrated_ids.json", "w", encoding="utf-8") as f:
        json.dump(members, f, ensure_ascii=False, indent=2)
    print(f"Extracted {len(members)} IDs to extrated_ids.json")
