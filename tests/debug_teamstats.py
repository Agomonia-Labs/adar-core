"""
Debug script — prints the raw HTML structure of a TeamStats page
so we can see exactly how stats are laid out and fix the parser.

Usage:
  python debug_teamstats.py
"""
import asyncio
import httpx
from bs4 import BeautifulSoup

ARCL_BASE = "https://www.arcl.org"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Agomoni Tigers — Fall 2025 (season_id=66, league_id=10)
URL = "https://www.arcl.org/Pages/UI/TeamStats.aspx?team_id=7262&league_id=10&season_id=66"


async def main():
    async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        r = await client.get(URL)
        print(f"Status: {r.status_code}")
        print(f"URL: {r.url}")
        print()

        soup = BeautifulSoup(r.text, "html.parser")

        # Remove scripts/styles
        for tag in soup(["script", "style"]):
            tag.decompose()

        # Print all headings to understand page sections
        print("=== HEADINGS ===")
        for h in soup.find_all(["h1", "h2", "h3", "h4", "strong"]):
            text = h.get_text(strip=True)
            if text:
                print(f"  <{h.name}>: {text}")

        print()
        print("=== TABLES ===")
        tables = soup.find_all("table")
        print(f"Found {len(tables)} tables")
        print()

        for i, table in enumerate(tables):
            print(f"--- Table {i+1} ---")

            # Print what's above the table (section heading)
            prev = table.find_previous_sibling()
            while prev:
                text = prev.get_text(strip=True)
                if text and prev.name in ["h2", "h3", "h4", "strong", "p", "div"]:
                    print(f"  Above: <{prev.name}> {text[:100]}")
                    break
                prev = prev.find_previous_sibling()

            # Print headers
            headers = []
            header_row = table.find("tr")
            if header_row:
                headers = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
                print(f"  Headers: {headers}")

            # Print first 3 data rows
            rows = table.find_all("tr")[1:4]
            for row in rows:
                cols = [td.get_text(strip=True) for td in row.find_all("td")]
                if any(cols):
                    print(f"  Row: {cols}")

            # Print player links in this table
            links = []
            for a in table.find_all("a", href=True):
                if "player_id" in a["href"].lower() or "player" in a["href"].lower():
                    links.append(f"{a.get_text(strip=True)} -> {a['href']}")
            if links:
                print(f"  Player links: {links[:3]}")

            print()

        # Also print raw text around "batting" or "bowling" keywords
        print("=== KEYWORD SEARCH ===")
        page_text = soup.get_text(separator="\n")
        lines = page_text.splitlines()
        keywords = ["batting", "bowling", "runs", "wickets", "average", "economy", "strike"]
        for i, line in enumerate(lines):
            line = line.strip()
            if any(kw in line.lower() for kw in keywords) and len(line) > 2:
                context = lines[max(0,i-1):i+3]
                print(f"  Line {i}: {' | '.join(l.strip() for l in context if l.strip())}")


asyncio.run(main())