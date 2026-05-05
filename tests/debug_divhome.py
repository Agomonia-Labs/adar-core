"""
debug_divhome.py — Test DivHome scraping and team discovery.
Run: PYTHONPATH=$(pwd) python tests/debug_divhome.py
"""
import asyncio, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()

ARCL_BASE = "https://www.arcl.org"

async def main():
    import httpx
    from bs4 import BeautifulSoup

    # Test different league_ids for Spring 2026 (season_id=69)
    print("Scanning DivHome pages for league_id 1-15, season_id=69...")
    print()

    async with httpx.AsyncClient(timeout=20) as client:
        for league_id in range(1, 16):
            try:
                url = f"{ARCL_BASE}/Pages/UI/DivHome.aspx?league_id={league_id}&season_id=69"
                r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                soup = BeautifulSoup(r.text, "html.parser")

                # Find division name in page
                title = soup.find("h2") or soup.find("h1") or soup.find("title")
                title_text = title.text.strip() if title else ""

                # Find team links
                teams = []
                for link in soup.find_all("a", href=True):
                    if "TeamStats" in link["href"] and link.text.strip():
                        teams.append(link.text.strip())

                if teams:
                    print(f"league_id={league_id}: {title_text[:50]} → {len(teams)} teams: {teams[:5]}")
            except Exception as e:
                pass

    print()
    print("Done — identify which league_id corresponds to Div H")

asyncio.run(main())