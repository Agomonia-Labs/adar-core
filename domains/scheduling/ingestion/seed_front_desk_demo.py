"""Idempotently seed the public Front Desk showcase into scheduling Firestore."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from google.cloud import firestore

from src.adar.config import settings
from src.adar.db import get_db


DEFAULT_FILE = Path(__file__).with_name("front_desk_demo.json")
GUEST_COLLECTION = "scheduling_guest_bookings"


def _working_hours(provider: dict) -> list[dict]:
    return [
        {"weekday": weekday, "start": provider["start"], "end": provider["end"]}
        for weekday in provider["weekdays"]
    ]


def _next_start(practice: dict, booking: dict) -> datetime:
    tz = ZoneInfo(practice["timezone"])
    now = datetime.now(tz)
    days_ahead = (int(booking["weekday"]) - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (now + timedelta(days=days_ahead)).replace(
        hour=int(booking["hour"]),
        minute=int(booking.get("minute", 0)),
        second=0,
        microsecond=0,
    ).astimezone(timezone.utc)


def _validate(practices: list[dict]) -> None:
    practice_ids = [practice["id"] for practice in practices]
    if len(practice_ids) != len(set(practice_ids)):
        raise ValueError("Practice IDs must be unique")
    for practice in practices:
        type_ids = {item["id"] for item in practice["appointment_types"]}
        provider_ids = {item["id"] for item in practice["providers"]}
        for provider in practice["providers"]:
            unknown = set(provider["appointment_type_ids"]) - type_ids
            if unknown:
                raise ValueError(f"{provider['id']} references unknown appointment types: {sorted(unknown)}")
        for booking in practice.get("seed_bookings", []):
            if booking["provider_id"] not in provider_ids:
                raise ValueError(f"{booking['id']} references an unknown provider")
            if booking["appointment_type_id"] not in type_ids:
                raise ValueError(f"{booking['id']} references an unknown appointment type")


async def seed(path: Path, *, dry_run: bool = False) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    practices = payload.get("practices") or []
    _validate(practices)
    if dry_run:
        return [practice["id"] for practice in practices]

    db = get_db()
    batch = db.batch()
    now = firestore.SERVER_TIMESTAMP

    for practice in practices:
        practice_id = practice["id"]
        batch.set(
            db.collection(settings.SCHEDULING_PRACTICES_COLLECTION).document(practice_id),
            {
                "practice_id": practice_id,
                "name": practice["name"],
                "domain": practice["domain"],
                "tagline": practice["tagline"],
                "location": practice["location"],
                "timezone": practice["timezone"],
                "lead_time_minutes": practice["lead_time_minutes"],
                "max_advance_days": practice["max_advance_days"],
                "color": practice["color"],
                "notification_email": "",
                "demo_seed": True,
                "active": True,
                "updated_at": now,
            },
            merge=True,
        )

        type_by_id = {item["id"]: item for item in practice["appointment_types"]}
        provider_by_id = {item["id"]: item for item in practice["providers"]}
        for appointment_type in practice["appointment_types"]:
            batch.set(
                db.collection(settings.SCHEDULING_APPOINTMENT_TYPES_COLLECTION).document(appointment_type["id"]),
                {
                    **appointment_type,
                    "practice_id": practice_id,
                    "demo_seed": True,
                    "active": True,
                    "updated_at": now,
                },
                merge=True,
            )

        for provider in practice["providers"]:
            batch.set(
                db.collection(settings.SCHEDULING_PROVIDERS_COLLECTION).document(provider["id"]),
                {
                    "practice_id": practice_id,
                    "name": provider["name"],
                    "role": provider["role"],
                    "bio": provider["bio"],
                    "appointment_type_ids": provider["appointment_type_ids"],
                    "working_hours": _working_hours(provider),
                    "demo_seed": True,
                    "active": True,
                    "updated_at": now,
                },
                merge=True,
            )

        for booking in practice.get("seed_bookings", []):
            appointment_type = type_by_id[booking["appointment_type_id"]]
            provider = provider_by_id[booking["provider_id"]]
            start = _next_start(practice, booking)
            end = start + timedelta(minutes=int(appointment_type["duration_minutes"]))
            batch.set(
                db.collection(GUEST_COLLECTION).document(booking["id"]),
                {
                    "practice_id": practice_id,
                    "guest_id": "demo_seed",
                    "provider_id": provider["id"],
                    "provider_name": provider["name"],
                    "appointment_type_id": appointment_type["id"],
                    "appointment_type_name": appointment_type["name"],
                    "start_time": start,
                    "end_time": end,
                    "caller_name": booking["caller_name"],
                    "caller_phone": "(206) 555-0100",
                    "caller_email": "demo@example.com",
                    "reason": "Existing demo appointment",
                    "status": "confirmed",
                    "source_channel": "public_demo_seed",
                    "demo_seed": True,
                    "updated_at": now,
                },
                merge=True,
            )

    await batch.commit()
    return [practice["id"] for practice in practices]


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed all public Front Desk demo practices.")
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if settings.DOMAIN != "scheduling":
        raise SystemExit("Run with DOMAIN=scheduling so scheduling collection names are configured.")
    practice_ids = asyncio.run(seed(args.file, dry_run=args.dry_run))
    print("Front Desk demo practice IDs:")
    print(",".join(practice_ids))


if __name__ == "__main__":
    main()
