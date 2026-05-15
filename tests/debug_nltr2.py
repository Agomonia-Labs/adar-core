"""
Run locally to test which approach works:
  python nltr_debug2.py
"""
import requests, re

HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "bn,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer":         "https://rabindra-rachanabali.nltr.org/",
    "Connection":      "keep-alive",
}

BASE = "https://rabindra-rachanabali.nltr.org"
s = requests.Session()
s.headers.update(HEADERS)

# Test 1: index page with letter আ
print("=== Test 1: Index page ===")
r = s.get(f"{BASE}/node/6624", params={"r": "আ"}, timeout=20)
print(f"Status: {r.status_code}, Length: {len(r.text)}")
links = re.findall(r'href="(/node/\d+)"', r.text)
print(f"Node links found: {len(links)}")
print("Sample:", links[:10])
print(r.text[:500])

# Test 2: known song page
print("\n=== Test 2: Direct song page (node/4049) ===")
r2 = s.get(f"{BASE}/node/4049", timeout=20)
print(f"Status: {r2.status_code}, Length: {len(r2.text)}")
print(r2.text[:800])

# Test 3: try paryay page with page param
print("\n=== Test 3: পূজা paryay page ===")
r3 = s.get(f"{BASE}/node/6594", timeout=20)
print(f"Status: {r3.status_code}, Length: {len(r3.text)}")
links3 = re.findall(r'href="(/node/\d+)"', r3.text)
print(f"Node links: {len(links3)}, Sample: {links3[:10]}")