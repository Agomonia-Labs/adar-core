"""
Check the LeagueSchedule page for Agomoni Tigers matches.
Run: python debug_league_schedule.py
"""
import asyncio
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

TEAM_NAME  = "Agomoni Tigers"
LEAGUE_ID  = 10
SEASON_ID  = 69

URLS = [
    f"https://www.arcl.org/Pages/UI/LeagueSchedule.aspx?league_id={LEAGUE_ID}&season_id={SEASON_ID}",
    f"https://www.arcl.org/Pages/UI/TeamStats.aspx?team_id=7262&league_id={LEAGUE_ID}&season_id={SEASON_ID}",
]

async def inspect(url, label):
    print(f"\n{'='*60}")
    print(f"{label}")
    print(f"URL: {url}")
    async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        r = await client.get(url)
        print(f"Status: {r.status_code}")
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script","style"]): tag.decompose()

        tables = soup.find_all("table")
        print(f"Tables: {len(tables)}")
        for i, t in enumerate(tables):
            rows = t.find_all("tr")
            if not rows: continue
            headers = [th.get_text(strip=True) for th in rows[0].find_all(["th","td"])]
            print(f"\n  Table {i+1} — {len(rows)-1} data rows")
            print(f"  Headers: {headers}")
            team_rows = []
            for row in rows[1:]:
                cols = [td.get_text(strip=True) for td in row.find_all("td")]
                if any(TEAM_NAME.lower() in c.lower() for c in cols):
                    team_rows.append(cols)
                    print(f"  [TEAM MATCH] {cols}")
            if not team_rows:
                # Show first 3 rows anyway
                for row in rows[1:4]:
                    cols = [td.get_text(strip=True) for td in row.find_all("td")]
                    if any(cols): print(f"  Sample: {cols}")

async def main():
    for url, label in zip(URLS, ["LeagueSchedule", "TeamStats"]):
        await inspect(url, label)

asyncio.run(main())