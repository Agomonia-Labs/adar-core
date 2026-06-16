"""Seed restaurant reviews from JSON or CSV files."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from domains.restaurants.db import connect, upsert_review
from domains.restaurants.ingestion.normalization import stable_uuid


def load_reviews(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get("reviews", [])
        return data

    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    raise ValueError(f"Unsupported review file type: {path}")


def normalize_review(raw: dict[str, Any]) -> dict[str, Any]:
    restaurant_id = raw["restaurant_id"]
    text = raw.get("text") or raw.get("review_text") or ""
    external_review_id = raw.get("external_review_id")
    review = {
        "id": raw.get("id") or stable_uuid(
            "review",
            restaurant_id,
            raw.get("source"),
            external_review_id,
            text[:160],
        ),
        "restaurant_id": restaurant_id,
        "source": raw.get("source") or "seed",
        "external_review_id": external_review_id,
        "rating": _float_or_none(raw.get("rating")),
        "text": text,
        "review_date": _date_or_none(raw.get("review_date") or raw.get("date")),
    }
    return review


async def ingest_reviews_file(path: Path) -> dict[str, int]:
    reviews = load_reviews(path)
    conn = await connect()
    count = 0
    try:
        async with conn.transaction():
            for raw in reviews:
                await upsert_review(conn, normalize_review(raw))
                count += 1
    finally:
        await conn.close()
    return {"reviews": count}


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date_or_none(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None
