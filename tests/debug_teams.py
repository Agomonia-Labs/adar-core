"""
Debug: check what's in adar_teams Firestore collection.
Run: python debug_teams.py
"""
import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

from google.cloud import firestore

async def main():
    db = firestore.AsyncClient(
        project=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )

    print("=== adar_teams collection ===\n")
    docs = db.collection("adar_teams").stream()
    count = 0
    async for doc in docs:
        count += 1
        d = doc.to_dict()
        d.pop("password_hash", None)
        print(f"Doc ID: {doc.id}")
        for k, v in d.items():
            print(f"  {k}: {v}")
        print()

    if count == 0:
        print("Collection is EMPTY — registration is not saving to Firestore.")
        print("\nPossible causes:")
        print("  1. GCP_PROJECT_ID or FIRESTORE_DATABASE env var is wrong")
        print(f"  2. Using project: {os.environ.get('GCP_PROJECT_ID', 'NOT SET')}")
        print(f"  3. Using database: {os.environ.get('FIRESTORE_DATABASE', '(default)')}")
    else:
        print(f"Total teams: {count}")

asyncio.run(main())