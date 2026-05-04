"""
Debug duplicate players in get_team_players_live.
Run: python debug_duplicates.py
"""
import asyncio
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

async def main():
    # Agomoni Tigers Summer 2025
    # season_id=66 per confirmed mapping
    url = "https://www.arcl.org/Pages/UI/TeamStats.aspx?team_id=7262&league_id=10&season_id=66"
    print(f"URL: {url}\n")

    async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        r = await client.get(url)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script","style"]): tag.decompose()

    tables = soup.find_all("table")
    print(f"Total tables: {len(tables)}\n")

    for i, t in enumerate(tables):
        rows = t.find_all("tr")
        if not rows: continue
        headers = [th.get_text(strip=True) for th in rows[0].find_all(["th","td"])]
        print(f"Table {i+1} ({len(rows)-1} data rows) headers: {headers}")
        # Count unique player names
        players = set()
        for row in rows[1:]:
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if cols and cols[0] and cols[0].lower() not in ("player",""):
                players.add(cols[0])
        print(f"  Unique players: {len(players)}")
        print(f"  First 3: {list(players)[:3]}\n")

asyncio.run(main())