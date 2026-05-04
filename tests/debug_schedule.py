"""
Debug TeamStats schedule table to see exact column structure.
Run: python debug_schedule.py
"""
import asyncio
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Agomoni Tigers Spring 2026
URL = "https://www.arcl.org/Pages/UI/TeamStats.aspx?team_id=7262&league_id=10&season_id=69"

async def main():
    async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        r = await client.get(URL)
        print(f"Status: {r.status_code}")
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()

        tables = soup.find_all("table")
        print(f"Total tables: {len(tables)}\n")

        # Table 1 is the schedule — show ALL rows
        if tables:
            t1 = tables[0]
            rows = t1.find_all("tr")
            headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
            print(f"=== Table 1 (Schedule) ===")
            print(f"Headers ({len(headers)}): {headers}")
            print(f"Total rows: {len(rows)}\n")

            for i, row in enumerate(rows[1:], 1):
                cols = [td.get_text(strip=True) for td in row.find_all("td")]
                print(f"Row {i}: {cols}")

asyncio.run(main())