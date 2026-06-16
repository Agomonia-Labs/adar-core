"""Menu parsers for structured data and simple HTML menu pages."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from html import unescape
from html.parser import HTMLParser
from typing import Any

try:
    from bs4 import BeautifulSoup
except ModuleNotFoundError:  # pragma: no cover - deployment installs requirements.txt
    BeautifulSoup = None

from domains.restaurants.ingestion.normalization import normalize_text, parse_price


PRICE_RE = re.compile(r"\$\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})?")
TEXT_PRICE_RE = re.compile(r"(?P<name>[A-Za-z][A-Za-z0-9 &'’().,/+-]{2,80})\s+(?P<price>\$?\d{1,3}(?:,\d{3})?(?:\.\d{2}))")


def parse_menu_html(html: str, source_url: str) -> list[dict[str, Any]]:
    if BeautifulSoup is None:
        return _parse_plain_html(html, source_url)
    soup = BeautifulSoup(html, "html.parser")
    items = _parse_json_ld(soup, source_url)
    if items:
        return items
    return _parse_visible_html(soup, source_url)


def parse_menu_text(text: str, source_url: str, source_type: str = "text") -> list[dict[str, Any]]:
    """Parse menu-like plain text, including PDF/OCR output."""
    candidates = []
    current_category = None
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if _looks_like_category(line):
            current_category = line.title()
            continue
        match = TEXT_PRICE_RE.search(line)
        if not match:
            continue
        name = _clean_item_name(match.group("name").strip(" .:-|"))
        if not name or len(name) < 3 or _looks_like_modifier_price(name):
            continue
        candidates.append({
            "name": name,
            "description": None,
            "category": current_category,
            "price": parse_price(match.group("price")),
            "currency": "USD",
            "source_url": source_url,
            "source_type": source_type,
            "extraction_confidence": 0.65,
        })
    return _dedupe_items(candidates)


def _parse_json_ld(soup: BeautifulSoup, source_url: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in _walk_json(payload):
            node_type = node.get("@type")
            if isinstance(node_type, list):
                is_menu_item = "MenuItem" in node_type
            else:
                is_menu_item = node_type == "MenuItem"
            if not is_menu_item or not node.get("name"):
                continue

            price = _price_from_node(node)
            items.append({
                "name": node["name"],
                "description": node.get("description"),
                "price": price,
                "currency": _currency_from_node(node) or "USD",
                "source_url": source_url,
                "source_type": "json_ld",
                "extraction_confidence": 0.95 if price is not None else 0.80,
            })
    return _dedupe_items(items)


def _parse_visible_html(soup: BeautifulSoup, source_url: str) -> list[dict[str, Any]]:
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    candidates: list[dict[str, Any]] = []
    selectors = [
        "[class*=menu]",
        "[class*=item]",
        "[class*=dish]",
        "li",
        "tr",
        "p",
        "div",
    ]
    for selector in selectors:
        for node in soup.select(selector):
            text = node.get_text(" ", strip=True)
            if not text or "$" not in text or len(text) > 260:
                continue
            price_match = PRICE_RE.search(text)
            if not price_match:
                continue
            price = parse_price(price_match.group(0))
            name = text[: price_match.start()].strip(" .:-|")
            description = text[price_match.end():].strip(" .:-|") or None
            name = _clean_item_name(name)
            if not name or len(name) < 3 or _looks_like_modifier_price(name):
                continue
            candidates.append({
                "name": name,
                "description": description,
                "price": price,
                "currency": "USD",
                "source_url": source_url,
                "source_type": "html",
                "extraction_confidence": 0.70,
            })
    return _dedupe_items(candidates)


def _walk_json(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_walk_json(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_json(child))
    return found


def _price_from_node(node: dict[str, Any]) -> Decimal | None:
    for key in ("price", "lowPrice", "highPrice"):
        price = parse_price(node.get(key))
        if price is not None:
            return price
    offers = node.get("offers")
    if isinstance(offers, dict):
        return _price_from_node(offers)
    if isinstance(offers, list):
        for offer in offers:
            if isinstance(offer, dict):
                price = _price_from_node(offer)
                if price is not None:
                    return price
    return None


def _currency_from_node(node: dict[str, Any]) -> str | None:
    currency = node.get("priceCurrency")
    if currency:
        return str(currency)
    offers = node.get("offers")
    if isinstance(offers, dict):
        return _currency_from_node(offers)
    if isinstance(offers, list):
        for offer in offers:
            if isinstance(offer, dict):
                currency = _currency_from_node(offer)
                if currency:
                    return currency
    return None


def _clean_item_name(value: str) -> str:
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"^(new|popular|special)\s+", "", value, flags=re.I)
    return value.strip()


def _looks_like_modifier_price(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered.endswith((" for", " add", " substitute", " substitution")):
        return True
    modifier_patterns = [
        r"\badd (a |an |extra )?[\w\s]{1,40} for$",
        r"\bsubstitute [\w\s]{1,60} for$",
        r"\bupgrade [\w\s]{1,60} for$",
    ]
    return any(re.search(pattern, lowered) for pattern in modifier_patterns)


def _looks_like_category(value: str) -> bool:
    if "$" in value or len(value) > 40:
        return False
    words = value.split()
    if not 1 <= len(words) <= 5:
        return False
    return value.isupper() or value.istitle()


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for item in items:
        key = (normalize_text(item.get("name")), item.get("price"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _parse_plain_html(html: str, source_url: str) -> list[dict[str, Any]]:
    parser = _TextExtractingParser()
    parser.feed(html)
    candidates = []
    for text in parser.text_lines:
        if "$" not in text or len(text) > 260:
            continue
        price_match = PRICE_RE.search(text)
        if not price_match:
            continue
        name = _clean_item_name(text[: price_match.start()].strip(" .:-|"))
        if not name or len(name) < 3:
            continue
        candidates.append({
            "name": name,
            "description": text[price_match.end():].strip(" .:-|") or None,
            "price": parse_price(price_match.group(0)),
            "currency": "USD",
            "source_url": source_url,
            "source_type": "html",
            "extraction_confidence": 0.55,
        })
    return _dedupe_items(candidates)


class _TextExtractingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self.text_lines: list[str] = []

    def handle_data(self, data: str) -> None:
        text = unescape(data).strip()
        if text:
            self._parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"div", "p", "li", "tr", "section", "article"} and self._parts:
            line = re.sub(r"\s+", " ", " ".join(self._parts)).strip()
            if line:
                self.text_lines.append(line)
            self._parts.clear()
