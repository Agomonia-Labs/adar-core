"""
One-off diagnostic: list every scheduling_practices doc, and every
scheduling_appointments doc, to check whether a booking's practice_id
matches what the admin console currently has selected / SCHEDULING_DEFAULT_PRACTICE_ID.

Run from the adar-core repo root:
  DOMAIN=scheduling PYTHONPATH=$(pwd) GOOGLE_APPLICATION_CREDENTIALS=/Users/brajadas/keys/genai-eval-sa.json \
    python3 _diagnose_booking.py
"""
import asyncio
from google.cloud import firestore

PROJECT_ID = "bdas-493785"
DATABASE = "adar-scheduling-db"

async def main():
    db = firestore.AsyncClient(project=PROJECT_ID, database=DATABASE)

    print("=== scheduling_practices ===")
    practices = {}
    async for doc in db.collection("scheduling_practices").stream():
        d = doc.to_dict() or {}
        practices[doc.id] = d.get("name")
        print(f"  {doc.id}  active={d.get('active', '<missing>')}  name={d.get('name')!r}")

    print("\n=== scheduling_appointments (all, sorted by start_time) ===")
    rows = []
    async for doc in db.collection("scheduling_appointments").stream():
        d = doc.to_dict() or {}
        rows.append((doc.id, d))
    rows.sort(key=lambda r: str(r[1].get("start_time")))
    for doc_id, d in rows:
        pname = practices.get(d.get("practice_id"), "<unknown practice>")
        print(f"  id={doc_id[:8]}  practice_id={d.get('practice_id')} ({pname})  "
              f"provider={d.get('provider_name')}  start={d.get('start_time')}  "
              f"status={d.get('status')}  caller={d.get('caller_name')} / {d.get('caller_email')}")

asyncio.run(main())
