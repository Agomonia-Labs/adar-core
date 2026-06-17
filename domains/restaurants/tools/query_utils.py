"""Shared query helpers for restaurant tools."""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from domains.restaurants.db import connect
from domains.restaurants.ingestion.normalization import normalize_tags


LOCATION_PRESETS = {
    "greater seattle": (47.6062, -122.3321),
    "greater-seattle": (47.6062, -122.3321),
    "seattle": (47.6062, -122.3321),
    "bellevue": (47.6101, -122.2015),
    "bothell": (47.7601, -122.2054),
    "redmond": (47.6740, -122.1215),
    "kirkland": (47.6769, -122.2060),
    "renton": (47.4829, -122.2171),
    "tacoma": (47.2529, -122.4443),
    "everett": (47.9789, -122.2021),
}

LOCATION_ALIASES = {
    "bellvue": "bellevue",
}

CUISINE_ALIASES = {
    "asian": ["asian"],
    "indian": ["indian", "asian"],
    "thai": ["thai", "asian"],
    "italian": ["italian"],
    "american": ["american"],
    "chinese": ["chinese", "asian"],
    "japanese": ["japanese", "asian"],
    "korean": ["korean", "asian"],
    "mexican": ["mexican"],
    "fast food": ["fast_food"],
    "fast_food": ["fast_food"],
    "seafood": ["seafood"],
    "vegan": ["vegan"],
    "vegetarian": ["vegetarian"],
}

DISH_CUISINE_HINTS = {
    "goat biryani": "indian",
    "goat biriyani": "indian",
    "lamb biryani": "indian",
    "lamb biriyani": "indian",
    "mutton biryani": "indian",
    "mutton biriyani": "indian",
    "biryani": "indian",
    "biriyani": "indian",
    "biriani": "indian",
    "butter chicken": "indian",
    "chana masala": "indian",
    "chicken tikka": "indian",
    "chicken tikka masala": "indian",
    "curry": "indian",
    "dal": "indian",
    "dosa": "indian",
    "masala": "indian",
    "naan": "indian",
    "paneer": "indian",
    "samosa": "indian",
    "tandoori": "indian",
    "tikka masala": "indian",
    "pad thai": "thai",
    "tom kha": "thai",
    "tom yum": "thai",
    "green curry": "thai",
    "drunken noodles": "thai",
    "pho": "vietnamese",
    "ramen": "japanese",
    "sushi": "japanese",
    "teriyaki": "japanese",
    "bulgogi": "korean",
    "bibimbap": "korean",
    "taco": "mexican",
    "burrito": "mexican",
    "quesadilla": "mexican",
    "pizza": "italian",
    "pasta": "italian",
}


def resolve_location(location: str | None) -> tuple[float, float] | None:
    if not location:
        return LOCATION_PRESETS["seattle"]
    lowered = location.strip().lower()
    lowered = LOCATION_ALIASES.get(lowered, lowered)
    if lowered in LOCATION_PRESETS:
        return LOCATION_PRESETS[lowered]
    if "," in lowered:
        try:
            lat_raw, lng_raw = lowered.split(",", 1)
            return float(lat_raw.strip()), float(lng_raw.strip())
        except ValueError:
            return LOCATION_PRESETS["seattle"]
    for key, coords in LOCATION_PRESETS.items():
        if key in lowered:
            return coords
    return LOCATION_PRESETS["seattle"]


def extract_location(text: str) -> str | None:
    lowered = text.lower()
    for alias, canonical in LOCATION_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return canonical
    for key in sorted(LOCATION_PRESETS, key=len, reverse=True):
        label = key.replace("-", " ")
        if re.search(rf"\b{re.escape(label)}\b", lowered):
            return key
    return None


def cuisine_filter(cuisine: str | None) -> list[str]:
    if not cuisine:
        return []
    normalized = cuisine.strip().lower().replace("-", " ")
    if normalized in {"american fast food", "american_fast_food"}:
        return ["american", "fast_food"]
    return CUISINE_ALIASES.get(normalized, normalize_tags(cuisine))


def cuisine_filter_requires_all(cuisine: str | None) -> bool:
    if not cuisine:
        return False
    normalized = cuisine.strip().lower().replace("-", " ").replace("_", " ")
    return normalized in {"american fast food"}


def primary_cuisine_filter(cuisine: str | None) -> list[str]:
    """Use exact cuisine for cuisine-specific browsing; keep Asian broad only for Asian."""
    if not cuisine:
        return []
    normalized = cuisine.strip().lower().replace("-", " ").replace(" ", "_")
    if normalized == "american_fast_food":
        return ["american", "fast_food"]
    if normalized == "asian":
        return ["asian"]
    if normalized == "fast_food":
        return ["fast_food"]
    if normalized in CUISINE_ALIASES:
        return [normalized]
    return normalize_tags(cuisine)


def haversine_sql(lat_param: str = "$1", lng_param: str = "$2") -> str:
    return f"""
        3958.7613 * 2 * asin(
          sqrt(
            power(sin(radians((r.latitude - {lat_param}) / 2)), 2) +
            cos(radians({lat_param})) * cos(radians(r.latitude)) *
            power(sin(radians((r.longitude - {lng_param}) / 2)), 2)
          )
        )
    """


def money(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"${float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def table(headers: list[str], rows: list[list[Any]]) -> str:
    def cell(value: Any) -> str:
        return str(value).replace("|", "\\|")

    out = [
        "| " + " | ".join(cell(header) for header in headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        out.append("| " + " | ".join(cell(value) for value in row) + " |")
    return "\n".join(out)


def json_safe(value: Any) -> Any:
    """Convert DB values into ADK/Gemini JSON-serializable values."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    return value


def rows_to_json(rows: list[Any]) -> list[dict[str, Any]]:
    return [json_safe(dict(row)) for row in rows]


def extract_budget(text: str) -> float | None:
    match = re.search(r"(?:under|below|less than|budget|within|<=?)\s*\$?\s*(\d+(?:\.\d+)?)", text, re.I)
    if match:
        return float(match.group(1))
    return None


def extract_quantity(text: str) -> int:
    match = re.search(r"(?:qty|quantity|for|serves?)\s*(\d+)", text, re.I)
    if match:
        return max(1, int(match.group(1)))
    return 1


def extract_cuisine(text: str) -> str | None:
    lowered = text.lower()
    if "american" in lowered and "fast food" in lowered:
        return "american fast food"
    for cuisine in sorted(CUISINE_ALIASES, key=len, reverse=True):
        if cuisine.replace("_", " ") in lowered:
            return cuisine
    for dish, cuisine in DISH_CUISINE_HINTS.items():
        if dish in lowered:
            return cuisine
    return None


def extract_meal(text: str) -> str | None:
    lowered = text.lower()
    for meal in ["breakfast", "brunch", "lunch", "dinner", "late night"]:
        if meal in lowered:
            return meal.replace(" ", "_")
    return None


async def vector_for_query(query: str) -> str | None:
    try:
        from src.adar.db import embed_text

        embedding = await embed_text(query, task_type="RETRIEVAL_QUERY")
        return "[" + ",".join(str(v) for v in embedding) + "]"
    except Exception as exc:
        print(f"Vector query unavailable, falling back to keyword search: {exc}")
        return None
