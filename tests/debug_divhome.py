"""
Debug DivHome standings scraping.
Run: python debug_divhome.py
"""
import asyncio
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Test these combinations
TEST_PAGES = [
    (63, 10, "Spring 2025 Div H"),
    (66, 10, "Fall 2025 Div H"),
    (69, 10, "Spring 2026 Div H"),
    (63, 7,  "Spring 2025 Men Div A-D"),
    (63, 8,  "Spring 2025 Men Div E-H"),
]

async def fetch_and_inspect(season_id, league_id, label):
    url = f"https://www.arcl.org/Pages/UI/DivHome.aspx?teams_stats_type_id=2&season_id={season_id}&league_id={league_id}"
    print(f"\n{'='*60}")
    print(f"{label} — s={season_id} l={league_id}")
    print(f"URL: {url}")

    async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        try:
            r = await client.get(url)
            print(f"Status: {r.status_code}  Final URL: {r.url}")

            if r.status_code != 200:
                print(f"ERROR: non-200 response")
                return

            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()

            # Page text length
            text = soup.get_text(strip=True)
            print(f"Page text length: {len(text)} chars")
            print(f"First 200 chars: {text[:200]}")

            # All headings
            headings = [h.get_text(strip=True) for h in soup.find_all(["h1","h2","h3","h4"])]
            print(f"Headings: {headings[:10]}")

            # All tables
            tables = soup.find_all("table")
            print(f"Tables found: {len(tables)}")
            for i, t in enumerate(tables):
                rows = t.find_all("tr")
                headers = [th.get_text(strip=True) for th in rows[0].find_all(["th","td"])] if rows else []
                print(f"  Table {i+1}: {len(rows)} rows, headers: {headers}")
                # First data row
                if len(rows) > 1:
                    cols = [td.get_text(strip=True) for td in rows[1].find_all("td")]
                    print(f"  First row: {cols}")

                    # Any links with team_id?
                    links = [a["href"] for a in t.find_all("a", href=True) if "team_id" in a["href"].lower()]
                    if links:
                        print(f"  Team links: {links[:3]}")

        except Exception as e:
            print(f"EXCEPTION: {e}")

async def main():
    for season_id, league_id, label in TEST_PAGES:
        await fetch_and_inspect(season_id, league_id, label)
        await asyncio.sleep(0.5)

asyncio.run(main())