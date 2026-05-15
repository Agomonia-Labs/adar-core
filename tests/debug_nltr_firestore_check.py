"""Check what's in Firestore geetabitan-db."""
import asyncio, os
from dotenv import load_dotenv

load_dotenv(".env.geetabitan", override=True)

from google.cloud import firestore

async def check():
    db_name  = os.environ.get("AUTH_FIRESTORE_DATABASE", "geetabitan-db")
    project  = os.environ.get("GCP_PROJECT_ID", "bdas-493785")
    coll     = os.environ.get("FIRESTORE_COLLECTION", "geetabitan_songs")

    print(f"Project:    {project}")
    print(f"Database:   {db_name}")
    print(f"Collection: {coll}")

    db = firestore.AsyncClient(project=project, database=db_name)

    # List ALL collections
    print("\n=== Collections in this database ===")
    async for c in db.collections():
        print(f"  {c.id}")

    # Count docs in geetabitan_songs
    print(f"\n=== First 5 docs in '{coll}' ===")
    count = 0
    async for doc in db.collection(coll).limit(5).stream():
        d = doc.to_dict()
        print(f"  id={doc.id} | title={d.get('title','N/A')[:50]}")
        count += 1
    if count == 0:
        print("  (empty — wrong collection name?)")

    # Try prefix search for আমার সোনার
    print("\n=== Prefix search: আমার সো ===")
    prefix = "আমার সো"
    async for doc in db.collection(coll)\
            .where("title",">=",prefix)\
            .where("title","<",prefix+"\uffff").limit(5).stream():
        print(f"  {doc.to_dict().get('title','')[:60]}")

asyncio.run(check())