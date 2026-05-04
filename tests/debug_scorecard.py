"""
Check Matchscorecard.aspx structure — find dismissal data.
Run: python debug_scorecard.py
"""
import asyncio
import httpx
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/124.0.0.0 Safari/537.36"}
ARCL_BASE = "https://www.arcl.org"

async def main():
    # Use Agomoni Tigers match_id=28045
    url = f"{ARCL_BASE}/Pages/UI/Matchscorecard.aspx?match_id=28045&league_id=10&season_id=69"
    print(f"Fetching: {url}\n")

    async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
        r = await client.get(url)

    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script","style"]): tag.decompose()

    tables = soup.find_all("table")
    print(f"Total tables: {len(tables)}\n")

    for i, table in enumerate(tables):
        rows = table.find_all("tr")
        if not rows: continue
        headers = [td.get_text(strip=True) for td in rows[0].find_all(["th","td"])]
        print(f"Table {i+1} ({len(rows)-1} data rows)")
        print(f"  Headers: {headers}")
        # Show first 3 data rows
        for row in rows[1:4]:
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            print(f"  Row: {cols}")
        print()

asyncio.run(main())