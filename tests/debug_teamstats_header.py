"""
Run this to see the exact column headers on the TeamStats page.
This tells us exactly what the bowling table headers are named.

Usage:
  python debug_teamstats_headers.py
"""
import asyncio
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Agomoni Tigers — Spring 2026 (season_id=69, league_id=10)
# Change these to match the team you want to inspect
TEAM_ID    = "7262"
LEAGUE_ID  = "10"
SEASON_ID  = "69"
TEAM_NAME  = "Agomoni Tigers"

URL = f"https://www.arcl.org/Pages/UI/TeamStats.aspx?team_id={TEAM_ID}&league_id={LEAGUE_ID}&season_id={SEASON_ID}"


async def main():
    async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        r = await client.get(URL)
        print(f"Status: {r.status_code}  URL: {r.url}")
        print()

        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()

        tables = soup.find_all("table")
        print(f"Total tables found: {len(tables)}")
        print()

        for i, table in enumerate(tables):
            rows = table.find_all("tr")
            if not rows:
                continue

            # Headers
            header_row = rows[0]
            headers = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
            print(f"=== Table {i+1} — {len(rows)-1} data rows ===")
            print(f"  Headers ({len(headers)}): {headers}")

            # First 3 data rows
            for row in rows[1:4]:
                cols = [td.get_text(strip=True) for td in row.find_all("td")]
                if any(cols):
                    # Also check for player links
                    links = [a["href"] for a in row.find_all("a", href=True) if "player" in a["href"].lower()]
                    print(f"  Row: {cols}")
                    if links:
                        print(f"  Links: {links[:2]}")

            print()


asyncio.run(main())