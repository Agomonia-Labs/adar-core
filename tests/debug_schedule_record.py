"""
Check if schedule data is stored in Firestore and test direct scraping.
Run: python debug_schedule_stored.py
"""
import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

async def main():
    from google.cloud import firestore

    db = firestore.AsyncClient(
        project=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "tigers-arcl"),
    )

    # Check arcl_team_schedules collection
    print("=== arcl_team_schedules collection ===")
    count = 0
    async for doc in db.collection("arcl_team_schedules").limit(10).stream():
        data = doc.to_dict()
        data.pop("embedding", None)
        print(f"  Doc: team={data.get('team_name')} season={data.get('season')} "
              f"playing={data.get('playing_count',0)} umpiring={data.get('umpiring_count',0)}")
        count += 1
    print(f"Total docs found: {count}")

    print()
    print("=== arcl_player_seasons — check for Agomoni Tigers Spring 2026 ===")
    count2 = 0
    async for doc in db.collection("arcl_player_seasons")\
                       .where("team_name", "==", "Agomoni Tigers")\
                       .where("season", "==", "Spring 2026")\
                       .limit(5).stream():
        data = doc.to_dict()
        print(f"  Player: {data.get('player_name')} runs={data.get('batting_runs')} wkts={data.get('bowling_wickets')}")
        count2 += 1
    print(f"Total player records for Agomoni Tigers Spring 2026: {count2}")

    print()
    print("=== Scraping TeamStats page directly for Agomoni Tigers Spring 2026 ===")
    import httpx
    from bs4 import BeautifulSoup
    HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/124.0.0.0 Safari/537.36"}
    url = "https://www.arcl.org/Pages/UI/TeamStats.aspx?team_id=7262&league_id=10&season_id=69"
    async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        r = await client.get(url)
        soup = BeautifulSoup(r.text, "html.parser")
        tables = soup.find_all("table")
        print(f"  Status: {r.status_code} | Tables: {len(tables)}")
        if tables:
            t1 = tables[0]
            rows = t1.find_all("tr")
            print(f"  Schedule table rows: {len(rows)}")
            for row in rows[:6]:
                cols = [td.get_text(strip=True) for td in row.find_all(["th","td"])]
                print(f"    {cols}")

asyncio.run(main())