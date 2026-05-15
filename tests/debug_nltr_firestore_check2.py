"""Show all fields of a Geetabitan Firestore doc."""
import asyncio, os
from dotenv import load_dotenv
load_dotenv(".env.geetabitan", override=True)
from google.cloud import firestore

async def check():
    db   = firestore.AsyncClient(project="bdas-493785", database="geetabitan-db")
    coll = "geetabitan_songs"

    # Get one doc and show all fields
    async for doc in db.collection(coll).limit(1).stream():
        d = doc.to_dict()
        print("=== ALL FIELDS in one doc ===")
        for k, v in sorted(d.items()):
            val = str(v)[:120] if v else ""
            print(f"  {k:25}: {val}")
        break

    # Search for "Amar Sonar" to confirm
    print("\n=== Search 'Amar' prefix ===")
    async for doc in db.collection(coll)\
            .where("title",">=","Amar")\
            .where("title","<","Amar\uffff").limit(5).stream():
        d = doc.to_dict()
        print(f"  title={d.get('title','')[:50]}")
        # Show Bengali field if exists
        for k in ['bengali_title','title_bn','lyrics','first_line','original_title']:
            if k in d:
                print(f"    {k}={str(d[k])[:80]}")

asyncio.run(check())