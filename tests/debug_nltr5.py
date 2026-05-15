"""Dump full HTML structure of a স্বদেশ song to find where notation lives."""
import requests, re
from bs4 import BeautifulSoup

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
BASE = "https://rabindra-rachanabali.nltr.org"

# node/4755 = সার্থক জনম (from your log)
r = S.get(f"{BASE}/node/4755", timeout=20)
r.encoding = "utf-8"
soup = BeautifulSoup(r.text, "html.parser")

print(f"Total HTML: {len(r.text)} chars\n")

# Show ALL divs and spans with their content
print("=== ALL elements with content > 20 chars ===")
for tag in soup.find_all(["div","span","p","td","table"]):
    cls = " ".join(tag.get("class", []))
    tid = tag.get("id","")
    text = tag.get_text(strip=True)
    if len(text) > 20:
        print(f"\n<{tag.name} class='{cls}' id='{tid}'>")
        print(f"  TEXT ({len(text)} chars): {repr(text[:150])}")

# Also check for elements with font-family swarabitan in style
print("\n\n=== Elements with swarabitan in style ===")
for tag in soup.find_all(style=True):
    if "swarabitan" in tag.get("style","").lower():
        print(f"<{tag.name} style='{tag['style']}'>")
        print(f"  TEXT: {repr(tag.get_text()[:200])}")

# Save full HTML
with open("/tmp/nltr_song.html","w",encoding="utf-8") as f:
    f.write(r.text)
print(f"\nSaved full HTML to /tmp/nltr_song.html")
print("Run: grep -i 'swarab\\|notation\\|স্বরলিপি' /tmp/nltr_song.html | head -20")