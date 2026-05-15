"""Check পূজা song node/3648 — should have notation."""
import requests
from bs4 import BeautifulSoup

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
BASE = "https://rabindra-rachanabali.nltr.org"

r = S.get(f"{BASE}/node/3648", timeout=20)
r.encoding = "utf-8"
soup = BeautifulSoup(r.text, "html.parser")

print(f"HTML size: {len(r.text)} chars")
print(f"Title: {soup.find('title').get_text()}")

# Show ALL divs with content
print("\n=== Content divs ===")
seen = set()
for tag in soup.find_all(["div","span"]):
    cls  = " ".join(tag.get("class",[]))
    tid  = tag.get("id","")
    text = tag.get_text(strip=True)
    key  = (cls, tid)
    if key in seen or len(text) < 30:
        continue
    seen.add(key)
    print(f"  [{tag.name} .{cls} #{tid}] {len(text)} chars: {repr(text[:120])}")

# Specifically look for swarabitan
print("\n=== Swarabitan search ===")
for tag in soup.find_all(True):
    style = tag.get("style","")
    cls   = " ".join(tag.get("class",[]))
    if "swarab" in style.lower() or "swarab" in cls.lower():
        print(f"Found: <{tag.name} class='{cls}' style='{style}'>")
        print(f"  Text: {repr(tag.get_text()[:200])}")

# Check if notation is iframe or linked
print("\n=== iframes and special tags ===")
for tag in soup.find_all(["iframe","object","embed"]):
    print(f"  <{tag.name}>: {tag.attrs}")

# Save
with open("/tmp/nltr_puja.html","w",encoding="utf-8") as f:
    f.write(r.text)

# Grep for swarabitan in raw HTML
import re
matches = re.findall(r'.{50}[Ss]warab.{50}', r.text)
print(f"\n=== 'Swarab' in raw HTML ({len(matches)} matches) ===")
for m in matches[:10]:
    print(f"  {repr(m)}")

# Check #kobita and other content divs raw HTML
kobita = soup.find(id="kobita")
if kobita:
    print(f"\n=== #kobita inner HTML (first 1000 chars) ===")
    print(str(kobita)[:1000])