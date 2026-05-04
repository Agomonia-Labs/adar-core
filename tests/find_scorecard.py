"""
Find scorecard URL structure on arcl.org and check dismissal data availability.
Run: python find_scorecard.py
"""
import asyncio
import httpx
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/124.0.0.0 Safari/537.36"}
ARCL_BASE = "https://www.arcl.org"

async def main():
    # Agomoni Tigers Spring 2026 schedule
    url = (f"{ARCL_BASE}/Pages/UI/LeagueSchedule.aspx"
           f"?league_id=10&season_id=69")

    async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
        r = await client.get(url)
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script","style"]): tag.decompose()

        print("=== Scorecard links found ===\n")
        scorecard_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if any(kw in href.lower() for kw in ["scorecard","score","match","game"]):
                print(f"  Text: {a.get_text(strip=True)[:40]}")
                print(f"  URL:  {href}\n")
                scorecard_links.append(href)

        if not scorecard_links:
            print("No scorecard links found on schedule page.")
            print("\n=== All links on page ===")
            for a in soup.find_all("a", href=True)[:30]:
                print(f"  {a.get_text(strip=True)[:30]:30} -> {a['href']}")

        # Also check a match result row for any inline links
        print("\n=== Tables on page ===")
        for i, table in enumerate(soup.find_all("table")):
            rows = table.find_all("tr")
            if rows:
                hdrs = [td.get_text(strip=True) for td in rows[0].find_all(["th","td"])]
                print(f"Table {i+1} ({len(rows)} rows): {hdrs[:6]}")

asyncio.run(main())