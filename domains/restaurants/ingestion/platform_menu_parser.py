"""Platform-aware menu extraction from embedded ordering-page JSON."""

from __future__ import annotations

import json
import re
import urllib.parse
from decimal import Decimal
from typing import Any

try:
    from bs4 import BeautifulSoup
except ModuleNotFoundError:  # pragma: no cover - deployment installs requirements.txt
    BeautifulSoup = None

from domains.restaurants.ingestion.normalization import normalize_text, parse_price


PLATFORM_HOST_HINTS = {
    "toast": ["toasttab.com", "toast.site"],
    "square": ["square.site", "squareup.com"],
    "chownow": ["chownow.com"],
    "popmenu": ["popmenu.com"],
    "clover": ["clover.com"],
    "owner": ["owner.com"],
    "spoton": ["spoton.com"],
    "menufy": ["menufy.com"],
    "bentobox": ["getbento.com", "bentobox"],
}

PRICE_KEYS = {
    "price",
    "baseprice",
    "base_price",
    "unitprice",
    "unit_price",
    "amount",
    "amountmoney",
    "amount_money",
    "priceamount",
    "price_amount",
    "menuitemprice",
    "menu_item_price",
}
NAME_KEYS = {"name", "title", "itemname", "item_name", "displayname", "display_name"}
DESCRIPTION_KEYS = {"description", "desc", "details", "subtitle"}
CATEGORY_KEYS = {"category", "categoryname", "category_name", "section", "sectionname"}


def detect_menu_platform(source_url: str, html: str = "") -> str | None:
    lowered_url = source_url.lower()
    lowered_html = html[:50000].lower()
    for platform, hints in PLATFORM_HOST_HINTS.items():
        if any(hint in lowered_url or hint in lowered_html for hint in hints):
            return platform
    parsed = urllib.parse.urlparse(source_url)
    if parsed.path and any(token in parsed.path.lower() for token in ["/order", "/ordering", "/store"]):
        return "ordering_platform"
    return None


def parse_platform_menu_html(html: str, source_url: str) -> list[dict[str, Any]]:
    """Parse menus from platform JSON blobs embedded in HTML."""
    platform = detect_menu_platform(source_url, html) or "embedded_json"
    payloads = _extract_json_payloads(html)
    items: list[dict[str, Any]] = []
    for payload in payloads:
        for node in _walk_json(payload):
            parsed = _item_from_node(node, source_url, platform)
            if parsed:
                items.append(parsed)
    return _dedupe_items(items)


def _extract_json_payloads(html: str) -> list[Any]:
    payloads: list[Any] = []
    scripts = _script_texts(html)
    for script in scripts:
        payloads.extend(_loads_direct_json(script))
        if _looks_menu_relevant(script):
            payloads.extend(_loads_embedded_json_objects(script))
    return payloads


def _script_texts(html: str) -> list[str]:
    if BeautifulSoup is None:
        return re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.I | re.S)
    soup = BeautifulSoup(html, "html.parser")
    return [script.string or script.get_text(" ", strip=False) for script in soup.find_all("script")]


def _loads_direct_json(raw: str) -> list[Any]:
    text = (raw or "").strip()
    if not text:
        return []
    if text.startswith(("window.", "self.", "__")):
        return []
    try:
        return [json.loads(text)]
    except json.JSONDecodeError:
        return []


def _loads_embedded_json_objects(raw: str) -> list[Any]:
    payloads: list[Any] = []
    text = raw or ""
    for match in re.finditer(r"[\[{]", text):
        snippet = _balanced_json_snippet(text, match.start())
        if not snippet or len(snippet) < 20:
            continue
        try:
            payloads.append(json.loads(snippet))
        except json.JSONDecodeError:
            continue
        if len(payloads) >= 20:
            break
    return payloads


def _balanced_json_snippet(text: str, start: int) -> str | None:
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for index in range(start, min(len(text), start + 2_000_000)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _looks_menu_relevant(text: str) -> bool:
    lowered = text[:2_000_000].lower()
    return any(token in lowered for token in ["menu", "item", "price", "modifier", "category"])


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


def _item_from_node(node: dict[str, Any], source_url: str, platform: str) -> dict[str, Any] | None:
    name = _first_string(node, NAME_KEYS)
    if not name or not _looks_like_item_name(name):
        return None
    price = _price_from_node(node)
    if price is None:
        return None
    description = _first_string(node, DESCRIPTION_KEYS)
    category = _first_string(node, CATEGORY_KEYS)
    return {
        "name": _clean_name(name),
        "description": description,
        "category": category,
        "price": price,
        "currency": _currency_from_node(node) or "USD",
        "source_url": source_url,
        "source_type": f"platform_{platform}",
        "extraction_confidence": 0.86,
    }


def _first_string(node: dict[str, Any], keys: set[str]) -> str | None:
    for key, value in node.items():
        if _norm_key(key) in keys and isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _price_from_node(node: dict[str, Any]) -> Decimal | None:
    for key, value in node.items():
        normalized = _norm_key(key)
        if normalized in PRICE_KEYS:
            price = _parse_platform_price(value)
            if price is not None:
                return price
        if isinstance(value, dict) and normalized in {"price", "amountmoney", "amount_money"}:
            price = _price_from_node(value)
            if price is not None:
                return price
    variations = node.get("variations") or node.get("sizes") or node.get("prices")
    if isinstance(variations, list):
        prices = [_price_from_node(v) for v in variations if isinstance(v, dict)]
        prices = [price for price in prices if price is not None]
        if prices:
            return min(prices)
    return None


def _parse_platform_price(value: Any) -> Decimal | None:
    if isinstance(value, dict):
        for nested_key in ["amount", "value", "price", "centAmount"]:
            if nested_key in value:
                price = _parse_platform_price(value[nested_key])
                if price is not None:
                    return price
        return None
    if isinstance(value, int):
        if value <= 0:
            return None
        return Decimal(value) / Decimal(100) if value >= 1000 else Decimal(value)
    if isinstance(value, float):
        if value <= 0:
            return None
        return Decimal(str(value))
    return parse_price(value)


def _currency_from_node(node: dict[str, Any]) -> str | None:
    for key, value in node.items():
        if _norm_key(key) in {"currency", "currencycode", "currency_code", "pricecurrency"} and value:
            return str(value).upper()
        if isinstance(value, dict):
            currency = _currency_from_node(value)
            if currency:
                return currency
    return None


def _looks_like_item_name(value: str) -> bool:
    text = normalize_text(value)
    if len(text) < 3 or len(text) > 120:
        return False
    blocked = {
        "menu",
        "order online",
        "checkout",
        "delivery",
        "pickup",
        "subtotal",
        "tax",
        "tip",
    }
    return text not in blocked and not re.fullmatch(r"[\d\s.$]+", text)


def _clean_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" :-|")


def _norm_key(value: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", value.lower())


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
