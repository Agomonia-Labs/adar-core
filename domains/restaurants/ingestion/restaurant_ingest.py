"""Seed restaurant and menu records from JSON or CSV files."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from domains.restaurants.db import (
    add_price_observation,
    connect,
    upsert_menu_item,
    upsert_restaurant,
)
from domains.restaurants.ingestion.normalization import (
    menu_item_id,
    normalize_tags,
    normalize_text,
    parse_price,
    restaurant_id,
)


def load_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get("restaurants", [])
        return data

    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    raise ValueError(f"Unsupported source file type: {path}")


def normalize_restaurant(record: dict[str, Any]) -> dict[str, Any]:
    source_refs = record.get("source_refs") or []
    if isinstance(source_refs, str):
        try:
            source_refs = json.loads(source_refs)
        except json.JSONDecodeError:
            source_refs = [{"source": source_refs}]

    normalized = {
        "id": restaurant_id(record),
        "name": record["name"].strip(),
        "normalized_name": normalize_text(record["name"]),
        "website_url": record.get("website_url") or record.get("url"),
        "phone": record.get("phone"),
        "address": record.get("address"),
        "city": record.get("city"),
        "region": record.get("region") or record.get("state"),
        "postal_code": record.get("postal_code") or record.get("zip"),
        "country": record.get("country") or "US",
        "latitude": _float_or_none(record.get("latitude") or record.get("lat")),
        "longitude": _float_or_none(record.get("longitude") or record.get("lng")),
        "rating": _float_or_none(record.get("rating")),
        "review_count": _int_or_default(record.get("review_count"), 0),
        "price_level": _int_or_none(record.get("price_level")),
        "service_types": normalize_tags(record.get("service_types")),
        "cuisine_tags": normalize_tags(record.get("cuisine_tags") or record.get("cuisine")),
        "meal_tags": normalize_tags(record.get("meal_tags") or record.get("meal")),
        "source_refs_json": json.dumps(source_refs),
    }
    return normalized


def normalize_menu_item(
    restaurant_id_value: str,
    raw_item: dict[str, Any],
    restaurant: dict[str, Any],
) -> dict[str, Any]:
    item = {
        "restaurant_id": restaurant_id_value,
        "name": raw_item["name"].strip(),
        "normalized_name": normalize_text(raw_item["name"]),
        "description": raw_item.get("description"),
        "category": raw_item.get("category"),
        "cuisine_tags": normalize_tags(
            raw_item.get("cuisine_tags") or restaurant.get("cuisine_tags")
        ),
        "meal_tags": normalize_tags(raw_item.get("meal_tags") or restaurant.get("meal_tags")),
        "dietary_tags": normalize_tags(raw_item.get("dietary_tags")),
        "price": parse_price(raw_item.get("price")),
        "currency": raw_item.get("currency") or "USD",
        "portion_size": raw_item.get("portion_size"),
        "serves_qty": _float_or_none(raw_item.get("serves_qty")),
        "availability": raw_item.get("availability"),
        "source_url": raw_item.get("source_url") or restaurant.get("website_url"),
        "source_type": raw_item.get("source_type") or "seed",
        "extraction_confidence": _float_or_none(raw_item.get("extraction_confidence")) or 0.95,
        "last_seen_at": raw_item.get("last_seen_at"),
    }
    item["id"] = menu_item_id(restaurant_id_value, item)
    return item


async def ingest_source_file(path: Path) -> dict[str, int]:
    records = load_records(path)
    conn = await connect()
    counts = {"restaurants": 0, "menu_items": 0, "price_observations": 0}
    try:
        async with conn.transaction():
            for raw in records:
                restaurant = normalize_restaurant(raw)
                saved_restaurant_id = await upsert_restaurant(conn, restaurant)
                counts["restaurants"] += 1

                for raw_item in raw.get("menu_items", []) or []:
                    item = normalize_menu_item(saved_restaurant_id, raw_item, restaurant)
                    await upsert_menu_item(conn, item)
                    await add_price_observation(conn, item)
                    counts["menu_items"] += 1
                    if item.get("price") is not None:
                        counts["price_observations"] += 1
    finally:
        await conn.close()
    return counts


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_or_default(value: Any, default: int) -> int:
    result = _int_or_none(value)
    return default if result is None else result

