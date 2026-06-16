"""Import human-reviewed menu items as trusted data."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from domains.restaurants.db import (
    add_price_observation,
    connect,
    upsert_menu_item,
    upsert_menu_source,
)
from domains.restaurants.ingestion.normalization import (
    menu_item_id,
    normalize_tags,
    normalize_text,
    parse_price,
)


def load_curated_items(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get("menu_items", [])
        return data
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    raise ValueError(f"Unsupported curated menu file type: {path}")


def normalize_curated_item(raw: dict[str, Any]) -> dict[str, Any]:
    item = {
        "restaurant_id": raw["restaurant_id"],
        "name": raw["name"].strip(),
        "normalized_name": normalize_text(raw["name"]),
        "description": raw.get("description"),
        "category": raw.get("category"),
        "cuisine_tags": normalize_tags(raw.get("cuisine_tags") or raw.get("cuisine")),
        "meal_tags": normalize_tags(raw.get("meal_tags") or raw.get("meal")),
        "dietary_tags": normalize_tags(raw.get("dietary_tags")),
        "price": parse_price(raw.get("price")),
        "currency": raw.get("currency") or "USD",
        "portion_size": raw.get("portion_size"),
        "serves_qty": _float_or_none(raw.get("serves_qty")),
        "availability": raw.get("availability"),
        "source_url": raw.get("source_url"),
        "source_type": raw.get("source_type") or "curated",
        "extraction_confidence": _float_or_none(raw.get("extraction_confidence")) or 1.0,
        "last_seen_at": raw.get("last_seen_at"),
    }
    item["id"] = raw.get("id") or menu_item_id(item["restaurant_id"], item)
    return item


async def ingest_curated_menu_items(path: Path) -> dict[str, int]:
    records = load_curated_items(path)
    conn = await connect()
    counts = {"menu_items": 0, "price_observations": 0, "sources": 0}
    try:
        async with conn.transaction():
            for raw in records:
                item = normalize_curated_item(raw)
                await upsert_menu_item(conn, item)
                await add_price_observation(conn, item)
                counts["menu_items"] += 1
                if item.get("price") is not None:
                    counts["price_observations"] += 1
                if item.get("source_url"):
                    await upsert_menu_source(conn, {
                        "restaurant_id": item["restaurant_id"],
                        "source_url": item["source_url"],
                        "source_type": item["source_type"],
                        "status": "verified",
                        "confidence": item["extraction_confidence"],
                        "discovered_by": "curated_import",
                    })
                    counts["sources"] += 1
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
