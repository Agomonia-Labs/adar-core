"""Normalization helpers for restaurant ingestion."""

from __future__ import annotations

import hashlib
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any


_SPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^a-z0-9&+' -]+")
_PRICE_RE = re.compile(r"(?<!\d)\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)")


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = value.lower().replace("\u00a0", " ")
    value = _NON_WORD_RE.sub(" ", value)
    return _SPACE_RE.sub(" ", value).strip()


def normalize_tags(values: list[str] | str | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [v.strip() for v in values.split(",")]
    tags = []
    for value in values:
        tag = normalize_text(str(value)).replace(" ", "_")
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def parse_price(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, int | float | Decimal):
        try:
            return Decimal(str(value)).quantize(Decimal("0.01"))
        except InvalidOperation:
            return None
    match = _PRICE_RE.search(str(value).replace(",", ""))
    if not match:
        return None
    try:
        return Decimal(match.group(1)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def stable_uuid(namespace: str, *parts: object) -> str:
    raw = "|".join(str(p or "") for p in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"adar:{namespace}:{digest}"))


def restaurant_id(record: dict[str, Any]) -> str:
    return record.get("id") or stable_uuid(
        "restaurant",
        normalize_text(record.get("name")),
        normalize_text(record.get("address")),
        record.get("latitude"),
        record.get("longitude"),
    )


def menu_item_id(restaurant_id_value: str, item: dict[str, Any]) -> str:
    return item.get("id") or stable_uuid(
        "menu-item",
        restaurant_id_value,
        normalize_text(item.get("name")),
        normalize_text(item.get("category")),
        normalize_text(item.get("source_url")),
    )

