"""
Run this to see ALL unique division names stored in Firestore.
This tells us exactly what's stored and why division queries fail.

Usage:
  python debug_divisions.py
"""
import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

from google.cloud import firestore

async def main():
    db = firestore.AsyncClient(
        project=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "tigers-arcl"),
    )

    print("=== Scanning arcl_teams collection ===")
    print("(showing all unique division+season combinations)\n")

    divs = {}
    count = 0

    async for doc in db.collection("arcl_teams").limit(500).stream():
        data = doc.to_dict()
        count += 1
        div    = data.get("division", "NO_DIVISION")
        season = data.get("season", "NO_SEASON")
        wins   = data.get("wins", 0)
        losses = data.get("losses", 0)

        if wins > 0 or losses > 0:
            key = f"{season} | {div}"
            if key not in divs:
                divs[key] = {"teams": [], "count": 0}
            divs[key]["count"] += 1
            divs[key]["teams"].append(data.get("team_name", "?"))

    print(f"Total documents scanned: {count}")
    print(f"Unique season+division combos with real data: {len(divs)}\n")

    for key in sorted(divs.keys()):
        info = divs[key]
        print(f"  [{info['count']} teams] {key}")
        for t in info["teams"][:5]:
            print(f"    - {t}")
        if len(info["teams"]) > 5:
            print(f"    ... and {len(info['teams'])-5} more")

asyncio.run(main())