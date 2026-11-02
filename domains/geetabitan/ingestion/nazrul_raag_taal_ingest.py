"""
domains/geetabitan/ingestion/nazrul_raag_taal_ingest.py

STEP 3 of 3 in the raag/taal backfill pipeline (fetch -> match -> ingest).

Reads the CSV you reviewed/edited by hand (domains/geetabitan/data/
nazrul_raag_taal_review.csv, produced by nazrul_raag_taal_match_candidates.py)
and writes raag/taal/swaralipi_image_url into Firestore for every row you
approved. Updates each doc directly by its `firestore_id` column (no fuzzy
matching here at all — that already happened in step 2, and you reviewed it).

A row counts as approved if its `status` column is y / yes / approved / 1
(case-insensitive). Everything else is skipped. Whatever is in that row's
`raag` / `taal` / `swaralipi_image_url` columns at the time you run this is
exactly what gets written — so if you corrected a value by hand, or pasted
in an alt2/alt3 candidate's values, that's what goes in.

Additive by default: a field is only written if it's currently empty on the
Firestore doc. Pass --force to overwrite a field that's already set (use
this if you're deliberately correcting a bad value, not for routine runs).

USAGE:
  DOTENV_FILE=.env.geetabitan PYTHONPATH=$(pwd) \\
  python -m domains.geetabitan.ingestion.nazrul_raag_taal_ingest --dry-run

  DOTENV_FILE=.env.geetabitan PYTHONPATH=$(pwd) \\
  python -m domains.geetabitan.ingestion.nazrul_raag_taal_ingest
"""

import argparse
import asyncio
import csv
import logging
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REVIEW_CSV = DATA_DIR / "nazrul_raag_taal_review.csv"

APPROVED_VALUES = {"y", "yes", "approved", "1", "true"}


def is_approved(row: dict) -> bool:
    return (row.get("status") or "").strip().lower() in APPROVED_VALUES


async def run(dry_run: bool, force: bool):
    from domains.geetabitan.ingestion.nazrul_swaralipi_scraper import get_songs_db
    from domains.geetabitan.config import NAZRUL_FIRESTORE_COLLECTION

    rows = list(csv.DictReader(open(REVIEW_CSV, encoding="utf-8")))
    approved = [r for r in rows if is_approved(r)]
    logger.info(f"{len(rows)} rows in review file, {len(approved)} marked approved.")

    db = get_songs_db()
    stats = {"updated": 0, "no_change": 0, "missing_doc": 0, "malformed_row": 0}

    for row in approved:
        fid = (row.get("firestore_id") or "").strip()
        title = (row.get("our_title") or "").strip()
        if not fid or not title:
            logger.warning(f"  Skipping malformed row (missing firestore_id/our_title): {row}")
            stats["malformed_row"] += 1
            continue

        doc_ref = db.collection(NAZRUL_FIRESTORE_COLLECTION).document(fid)
        snap = await doc_ref.get()
        if not snap.exists:
            logger.warning(f"  No Firestore doc for firestore_id={fid} ({title[:40]})")
            stats["missing_doc"] += 1
            continue

        existing = snap.to_dict() or {}
        update = {}
        for field, csv_key in (("raag", "raag"), ("taal", "taal"),
                                ("nazrulgeeti_org_swaralipi_image_url", "swaralipi_image_url")):
            val = (row.get(csv_key) or "").strip()
            if not val:
                continue
            if force or not (existing.get(field) or "").strip():
                update[field] = val

        if not update:
            stats["no_change"] += 1
            continue

        logger.info(f"  {row['our_title'][:35]:35s} -> {update}")
        if not dry_run:
            await doc_ref.update(update)
        stats["updated"] += 1

    logger.info(f"\n{'='*55}\nFinal stats: {stats}")


async def main():
    from dotenv import load_dotenv
    load_dotenv(os.environ.get("DOTENV_FILE", ".env.geetabitan"), override=True)

    p = argparse.ArgumentParser(description="Ingest human-reviewed raag/taal CSV into Firestore")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="overwrite fields that already have a value")
    args = p.parse_args()

    await run(args.dry_run, args.force)


if __name__ == "__main__":
    asyncio.run(main())
