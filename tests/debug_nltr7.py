"""Check #kobita structure of স্বদেশ songs."""
import requests
from bs4 import BeautifulSoup

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
BASE = "https://rabindra-rachanabali.nltr.org"

for nid in [4673, 4678, 4681]:
    r = S.get(f"{BASE}/node/{nid}", timeout=20)
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    print(f"\n=== node/{nid} ===")
    print(f"Title tag: {soup.find('title').get_text()}")
    kobita = soup.find(id="kobita")
    if kobita:
        print(f"#kobita HTML:\n{str(kobita)[:800]}")
    else:
        # Try #content
        content = soup.find(id="content")
        print(f"No #kobita! #content:\n{str(content)[:500] if content else 'None'}")