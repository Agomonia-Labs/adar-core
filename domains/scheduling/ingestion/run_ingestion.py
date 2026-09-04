"""
domains/scheduling/ingestion/run_ingestion.py
Seed a practice's providers, appointment types, and working hours into
Firestore from a JSON file (see sample_practice.json for the shape).

This is the "provider roster ingestion" step §5 of the build plan calls out
as the role arcl_scraper.py plays for team data — except there's no live
site to scrape here, so it's a straightforward structured-JSON loader
instead. A real deployment would eventually replace/extend this with a
PMS/EHR sync (see the build plan's decisions section).

Usage:
    DOMAIN=scheduling PYTHONPATH=$(pwd) python -m domains.scheduling.ingestion.run_ingestion \\
        --file domains/scheduling/ingestion/sample_practice.json

Prints the created practice_id — set that as SCHEDULING_DEFAULT_PRACTICE_ID
for a single-practice pilot deployment so the agent never has to ask which
practice a caller means.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from src.adar.config import settings
from src.adar.db import add_document, get_db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("scheduling.ingestion")


async def seed_practice(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    practice = payload["practice"]
    practice_id = await add_document(settings.SCHEDULING_PRACTICES_COLLECTION, {
        "practice_id": None,  # filled in below once we have the doc id
        "name": practice["name"],
        "timezone": practice.get("timezone", "UTC"),
        "lead_time_minutes": practice.get("lead_time_minutes", 120),
        "max_advance_days": practice.get("max_advance_days", 60),
        # Where new-booking notifications go (confirm_booking in
        # availability_tools.py) — optional, falls back to the platform
        # ADMIN_EMAIL at send time when left blank.
        "notification_email": practice.get("notification_email", ""),
        "active": True,
    })
    # practice_id doubles as its own tenant key — store it on the doc too so
    # direct_query({"practice_id": ...}) filters work the same way every
    # other collection's tenant filter does.
    db = get_db()
    await db.collection(settings.SCHEDULING_PRACTICES_COLLECTION).document(practice_id).update({
        "practice_id": practice_id,
    })
    log.info("Created practice %s (%s)", practice["name"], practice_id)

    appt_type_ids: dict[str, str] = {}
    for appt_type in payload.get("appointment_types", []):
        type_id = await add_document(settings.SCHEDULING_APPOINTMENT_TYPES_COLLECTION, {
            "practice_id": practice_id,
            "name": appt_type["name"],
            "duration_minutes": appt_type.get("duration_minutes", 30),
            "buffer_minutes": appt_type.get("buffer_minutes", 0),
            "description": appt_type.get("description", ""),
            "active": True,
        })
        appt_type_ids[appt_type["name"]] = type_id
        log.info("  + appointment type %s (%s)", appt_type["name"], type_id)

    for provider in payload.get("providers", []):
        type_ids_for_provider = [
            appt_type_ids[name]
            for name in provider.get("appointment_types", [])
            if name in appt_type_ids
        ]
        provider_id = await add_document(settings.SCHEDULING_PROVIDERS_COLLECTION, {
            "practice_id": practice_id,
            "name": provider["name"],
            "role": provider.get("role", ""),
            "bio": provider.get("bio", ""),
            "appointment_type_ids": type_ids_for_provider,
            "working_hours": provider.get("working_hours", []),
            "active": True,
        })
        log.info("  + provider %s (%s)", provider["name"], provider_id)

    return practice_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a practice into Firestore for the scheduling domain.")
    parser.add_argument("--file", default="domains/scheduling/ingestion/sample_practice.json")
    args = parser.parse_args()

    # Fail fast with a clear message instead of letting this fall through to
    # an opaque Firestore error. If DOMAIN wasn't "scheduling" at process
    # start, config.py's scheduling branch never ran and every
    # SCHEDULING_*_COLLECTION name (settings.SCHEDULING_PRACTICES_COLLECTION
    # etc.) silently resolves to "" — Firestore then rejects the empty
    # collection path with "A document must have an even number of path
    # elements", which gives no hint that DOMAIN was the actual problem.
    if settings.DOMAIN != "scheduling":
        raise SystemExit(
            f"DOMAIN is {settings.DOMAIN!r}, not 'scheduling' — this process "
            "needs DOMAIN=scheduling set BEFORE python starts (it's read once "
            "at import time, so `export DOMAIN=scheduling` in an earlier "
            "command or a different terminal tab doesn't count).\n"
            "Run it as:\n"
            "  DOMAIN=scheduling PYTHONPATH=$(pwd) python -m "
            "domains.scheduling.ingestion.run_ingestion --file "
            f"{args.file}"
        )

    practice_id = asyncio.run(seed_practice(args.file))
    print(f"\nDone. practice_id = {practice_id}")
    print(f"Set SCHEDULING_DEFAULT_PRACTICE_ID={practice_id} for a single-practice pilot deployment.")


if __name__ == "__main__":
    main()
