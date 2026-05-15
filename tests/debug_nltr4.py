"""Check song page structure and next-link chain."""
import requests, re
from bs4 import BeautifulSoup

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
BASE = "https://rabindra-rachanabali.nltr.org"

r = S.get(f"{BASE}/node/3648", timeout=20)
r.encoding = "utf-8"
soup = BeautifulSoup(r.text, "html.parser")

print("=== node/3648 ===")
print("Title tag:", soup.find("title").get_text() if soup.find("title") else "None")

# Find swaralipi div
for tag in soup.find_all(class_=re.compile("swarab|swarali", re.I)):
    print(f"\nFound class '{tag.get('class')}': {len(tag.get_text())} chars")
    print("Content preview:", repr(tag.get_text()[:200]))

# Find next/prev navigation
print("\n=== Navigation links ===")
for a in soup.find_all("a", href=True):
    text = a.get_text(strip=True)
    href = a["href"]
    if any(k in text for k in ["পরবর্তী","পূর্ববর্তী","প্রথম","শেষ","next","prev"]):
        print(f"  '{text}' → {href}")
    if re.search(r"/node/\d+$", href) and "/node/" in href:
        nid = int(re.search(r"/node/(\d+)$", href).group(1))
        if 3000 < nid < 16000:
            print(f"  Song link: '{text}' → node/{nid}")

# Show all divs with id or class
print("\n=== All divs with id/class ===")
for d in soup.find_all(["div","span"], class_=True)[:20]:
    cls = d.get("class","")
    txt = d.get_text(strip=True)[:60]
    if txt:
        print(f"  .{'.'.join(cls)}: {repr(txt)}")