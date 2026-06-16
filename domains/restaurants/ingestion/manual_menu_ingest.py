"""Ingest manually curated menu URLs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from domains.restaurants.db import (
    add_price_observation,
    connect,
    log_menu_scrape_attempt,
    upsert_menu_item,
    upsert_menu_source,
)
from domains.restaurants.ingestion.normalization import menu_item_id, normalize_text
from domains.restaurants.ingestion.image_menu_parser import parse_image_menu
from domains.restaurants.ingestion.menu_scraper import scrape_menu_url
from domains.restaurants.ingestion.normalization import normalize_tags
from domains.restaurants.ingestion.pdf_menu_parser import parse_pdf_menu


def load_manual_menu_urls(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get("menus", [])
        return data

    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    raise ValueError(f"Unsupported manual menu file type: {path}")


async def ingest_manual_menu_urls(path: Path) -> dict[str, int]:
    records = load_manual_menu_urls(path)
    counts = {
        "records": 0,
        "menu_pages_attempted": 0,
        "menu_items": 0,
        "price_observations": 0,
        "errors": 0,
    }
    for record in records:
        counts["records"] += 1
        restaurant_id = record.get("restaurant_id")
        menu_url = record.get("menu_url") or record.get("url")
        file_path = record.get("file_path") or record.get("path")
        source_value = menu_url or file_path
        if not restaurant_id or not source_value:
            counts["errors"] += 1
            print(f"Skipping manual menu record missing restaurant_id and menu_url/file_path: {record}")
            continue

        counts["menu_pages_attempted"] += 1
        try:
            cuisine_tags = normalize_tags(record.get("cuisine") or record.get("cuisine_tags"))
            meal_tags = normalize_tags(record.get("meal") or record.get("meal_tags"))
            if file_path:
                result = await _ingest_local_menu_file(
                    restaurant_id=restaurant_id,
                    file_path=Path(file_path),
                    source_url=menu_url or file_path,
                    cuisine_tags=cuisine_tags,
                    meal_tags=meal_tags,
                )
            else:
                result = await scrape_menu_url(
                    restaurant_id=restaurant_id,
                    source_url=menu_url,
                    cuisine_tags=cuisine_tags,
                    meal_tags=meal_tags,
                )
            counts["menu_items"] += result["menu_items"]
            counts["price_observations"] += result["price_observations"]
            print(
                f"Saved {result['menu_items']} menu items for "
                f"{record.get('restaurant_name') or restaurant_id} from {source_value}"
            )
        except Exception as exc:
            counts["errors"] += 1
            print(
                f"Manual menu scrape failed for "
                f"{record.get('restaurant_name') or restaurant_id} at {source_value}: {exc}"
            )
    return counts


async def _ingest_local_menu_file(
    restaurant_id: str,
    file_path: Path,
    source_url: str,
    cuisine_tags: list[str],
    meal_tags: list[str],
) -> dict[str, int]:
    if file_path.suffix.lower() == ".pdf":
        parsed_items = parse_pdf_menu(file_path, source_url=source_url)
        source_type = "pdf"
        discovered_by = "manual_pdf"
    elif file_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
        parsed_items = parse_image_menu(file_path, source_url=source_url)
        source_type = "image_ocr"
        discovered_by = "manual_image_ocr"
    else:
        raise ValueError(f"Unsupported manual menu file type: {file_path}")

    conn = await connect()
    counts = {"menu_items": 0, "price_observations": 0}
    try:
        async with conn.transaction():
            for parsed in parsed_items:
                item = {
                    **parsed,
                    "id": menu_item_id(restaurant_id, parsed),
                    "restaurant_id": restaurant_id,
                    "normalized_name": normalize_text(parsed["name"]),
                    "cuisine_tags": cuisine_tags,
                    "meal_tags": meal_tags,
                    "dietary_tags": normalize_tags(parsed.get("dietary_tags")),
                }
                await upsert_menu_item(conn, item)
                await add_price_observation(conn, item)
                counts["menu_items"] += 1
                if item.get("price") is not None:
                    counts["price_observations"] += 1
            await upsert_menu_source(conn, {
                "restaurant_id": restaurant_id,
                "source_url": source_url,
                "source_type": source_type,
                "status": "parsed" if counts["menu_items"] else "no_items",
                "confidence": 0.70 if counts["menu_items"] else 0.20,
                "discovered_by": discovered_by,
            })
            await log_menu_scrape_attempt(conn, {
                "restaurant_id": restaurant_id,
                "source_url": source_url,
                "source_type": source_type,
                "fetch_mode": "file",
                "status": "success" if counts["menu_items"] else "no_items",
                "items_found": counts["menu_items"],
                "prices_found": counts["price_observations"],
            })
    finally:
        await conn.close()
    return counts
