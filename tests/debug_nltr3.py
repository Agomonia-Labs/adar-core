"""Check paryay pagination to see how many songs per page."""
import requests, re

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

BASE = "https://rabindra-rachanabali.nltr.org"

PARYAY = {
    "পূজা":    6594,
    "প্রেম":   6599,
    "স্বদেশ": 6619,
}

for name, nid in PARYAY.items():
    all_links = set()
    for pg in range(0, 5):
        params = {"page": pg} if pg > 0 else {}
        r = S.get(f"{BASE}/node/{nid}", params=params, timeout=20)
        if r.status_code != 200:
            break
        links = re.findall(r'href="(/node/(\d+))"', r.text)
        song_links = [(href, int(nid2)) for href, nid2 in links
                      if 3000 < int(nid2) < 16000]
        if not song_links:
            print(f"  {name} page {pg}: no song links — stopping pagination")
            break
        new = {nid2 for _, nid2 in song_links if nid2 not in all_links}
        all_links |= {nid2 for _, nid2 in song_links}
        print(f"  {name} page {pg}: {len(song_links)} links, {len(new)} new, total {len(all_links)}")
        print(f"    Sample: {[nid2 for _, nid2 in song_links[:5]]}")
    print()

# Also check a direct song page for content
print("=== Direct song page node/4049 ===")
r = S.get(f"{BASE}/node/4049", timeout=20)
soup_text = r.text
# Find title
title_m = re.search(r'<title>([^<]+)</title>', soup_text)
print("Title:", title_m.group(1) if title_m else "not found")
# Find notation-related content
print("Has 'swaralipi' class?", 'swarabitan' in soup_text.lower() or 'swaralipi' in soup_text.lower())
print("Has Bengali text?", bool(re.search(r'[\u0980-\u09FF]{20,}', soup_text)))
# Print a section of the body
body_start = soup_text.find('<body')
if body_start > 0:
    print("\nBody preview (chars 500-2000):")
    print(soup_text[body_start+500:body_start+1500])