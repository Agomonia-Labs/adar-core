"""Optional LLM menu extraction fallback."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from domains.restaurants.ingestion.menu_parser import parse_menu_text
from domains.restaurants.ingestion.normalization import parse_price


def llm_extraction_enabled() -> bool:
    return os.getenv("MENU_LLM_EXTRACT", "false").lower() in {"1", "true", "yes"}


async def parse_menu_with_llm(text: str, source_url: str) -> list[dict[str, Any]]:
    """Extract menu items from visible text with Gemini when enabled."""
    if not llm_extraction_enabled():
        return []
    trimmed = _compact_text(text)[:24000]
    if "$" not in trimmed or len(trimmed) < 100:
        return []

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    prompt = f"""
Extract restaurant menu items from the text below.
Return ONLY JSON with this shape:
{{"items":[{{"name":"Pad Thai","description":"","category":"Noodles","price":"17.95","currency":"USD"}}]}}

Rules:
- Include only real menu items sold by the restaurant.
- Include price only when visible in the text.
- Do not include navigation, fees, tax, tips, gift cards, or modifiers by themselves.
- Max 120 items.

Source: {source_url}

TEXT:
{trimmed}
""".strip()
    result = await client.aio.models.generate_content(
        model=os.getenv("MENU_LLM_MODEL", "gemini-2.5-flash"),
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=8192),
    )
    raw = (result.text or "").strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if match:
        raw = match.group(0)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []

    items = []
    for item in payload.get("items", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        price = parse_price(item.get("price"))
        if price is None:
            continue
        items.append({
            "name": str(item["name"]).strip(),
            "description": item.get("description") or None,
            "category": item.get("category") or None,
            "price": price,
            "currency": item.get("currency") or "USD",
            "source_url": source_url,
            "source_type": "llm_text",
            "extraction_confidence": 0.72,
        })
    return items or parse_menu_text(trimmed, source_url, source_type="llm_text_fallback")


def _compact_text(text: str) -> str:
    lines = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)
