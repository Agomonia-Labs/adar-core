"""Bulk menu discovery and scraping for restaurants with website URLs."""

from __future__ import annotations

import asyncio
import json
import os
import urllib.parse
from html.parser import HTMLParser
from typing import Any

import httpx

from domains.restaurants.db import (
    connect,
    enqueue_menu_curation,
    log_menu_scrape_attempt,
    restaurants_for_menu_scrape,
    upsert_menu_source,
)
from domains.restaurants.ingestion.menu_scraper import USER_AGENT, scrape_menu_url


COMMON_MENU_PATHS = [
    "/menu",
    "/menus",
    "/food-menu",
    "/restaurant-menu",
    "/order",
    "/order-online",
    "/online-ordering",
    "/ordering",
    "/online-order",
    "/store",
    "/takeout",
]
PLATFORM_URL_TOKENS = [
    "toasttab.com",
    "toast.site",
    "square.site",
    "squareup.com",
    "chownow.com",
    "popmenu.com",
    "clover.com",
    "owner.com",
    "spoton.com",
    "menufy.com",
    "getbento.com",
    "bentobox",
]
MENU_DISCOVERY_MODE = os.getenv("MENU_DISCOVERY_MODE", "http").lower()


async def bulk_scrape_menus(
    limit: int = 25,
    refresh: bool = False,
    max_menu_pages_per_restaurant: int = 3,
    delay_seconds: float = 0.5,
    cuisine_tags: list[str] | None = None,
) -> dict[str, int]:
    conn = await connect()
    try:
        restaurants = await restaurants_for_menu_scrape(
            conn,
            limit=limit,
            refresh=refresh,
            cuisine_tags=cuisine_tags,
        )
    finally:
        await conn.close()

    counts = {
        "restaurants_checked": 0,
        "restaurants_with_menu": 0,
        "menu_pages_attempted": 0,
        "menu_items": 0,
        "price_observations": 0,
        "errors": 0,
    }

    for restaurant in restaurants:
        counts["restaurants_checked"] += 1
        candidates = await discover_menu_urls(
            restaurant["website_url"],
            max_candidates=max_menu_pages_per_restaurant,
        )
        saved_for_restaurant = 0
        for url in candidates:
            counts["menu_pages_attempted"] += 1
            try:
                result = await scrape_menu_url(
                    restaurant_id=restaurant["id"],
                    source_url=url,
                    cuisine_tags=list(restaurant.get("cuisine_tags") or []),
                    meal_tags=list(restaurant.get("meal_tags") or []),
                )
                counts["menu_items"] += result["menu_items"]
                counts["price_observations"] += result["price_observations"]
                saved_for_restaurant += result["menu_items"]
                if result["menu_items"] > 0:
                    break
            except Exception as exc:
                counts["errors"] += 1
                await _record_failed_attempt(restaurant, url, exc)
                print(f"Menu scrape failed for {restaurant['name']} at {url}: {exc}")
            if delay_seconds:
                await asyncio.sleep(delay_seconds)
        if saved_for_restaurant:
            counts["restaurants_with_menu"] += 1
        else:
            await _enqueue_no_menu(restaurant, candidates)

    return counts


async def _record_failed_attempt(restaurant: Any, url: str, exc: Exception) -> None:
    conn = await connect()
    try:
        await log_menu_scrape_attempt(conn, {
            "restaurant_id": restaurant["id"],
            "source_url": url,
            "source_type": "website",
            "fetch_mode": os.getenv("MENU_FETCH_MODE", "http"),
            "status": "error",
            "error": str(exc)[:2000],
        })
        await upsert_menu_source(conn, {
            "restaurant_id": restaurant["id"],
            "source_url": url,
            "source_type": "website",
            "status": "failed",
            "confidence": 0.05,
            "notes": str(exc)[:1000],
            "discovered_by": "bulk_scraper",
        })
    finally:
        await conn.close()


async def _enqueue_no_menu(restaurant: Any, candidates: list[str]) -> None:
    conn = await connect()
    try:
        await enqueue_menu_curation(conn, {
            "restaurant_id": restaurant["id"],
            "source_url": restaurant["website_url"],
            "reason": "menu_not_found_or_not_parsed",
            "priority": 2,
            "details_json": json.dumps({
                "restaurant_name": restaurant["name"],
                "candidates": candidates,
            }),
        })
    finally:
        await conn.close()


async def discover_menu_urls(website_url: str, max_candidates: int = 3) -> list[str]:
    normalized = _normalize_url(website_url)
    candidates = []

    if _looks_like_menu_url(normalized):
        candidates.append(normalized)

    candidates.extend(await _homepage_menu_links(normalized))
    candidates.extend(_common_menu_urls(normalized))

    deduped = []
    seen = set()
    for url in candidates:
        clean = url.split("#", 1)[0]
        if clean not in seen:
            seen.add(clean)
            deduped.append(clean)
        if len(deduped) >= max_candidates:
            break
    return deduped


async def inspect_website_links(website_url: str, output_path: str | None = None) -> dict[str, Any]:
    """Return all homepage links with menu/platform classification."""
    normalized = _normalize_url(website_url)
    links = await _homepage_link_records(normalized)
    common_links = _common_menu_urls(normalized)
    rows = []
    seen = set()
    for link in [{"url": normalized, "text": ""}, *links, *[{"url": url, "text": ""} for url in common_links]]:
        url = link["url"]
        clean = url.split("#", 1)[0]
        if clean in seen:
            continue
        seen.add(clean)
        text = link.get("text", "")
        rows.append({
            "url": clean,
            "text": text,
            "kind": _classify_link(clean, text),
            "is_menu_candidate": _looks_like_menu_url(clean, text),
            "is_platform": _is_platform_url(clean),
        })
    rows.sort(key=lambda row: (
        0 if row["is_menu_candidate"] else 1,
        0 if row["is_platform"] else 1,
        row["kind"],
        row["url"],
    ))
    if output_path:
        _write_link_report(output_path, rows)
    return {
        "website_url": normalized,
        "total_links": len(rows),
        "menu_candidates": sum(1 for row in rows if row["is_menu_candidate"]),
        "platform_links": sum(1 for row in rows if row["is_platform"]),
        "links": rows,
    }


async def _homepage_links(website_url: str) -> list[str]:
    return [record["url"] for record in await _homepage_link_records(website_url)]


async def _homepage_link_records(website_url: str) -> list[dict[str, str]]:
    if MENU_DISCOVERY_MODE in {"browser", "chrome"}:
        return await _homepage_link_records_browser(website_url)

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(website_url, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
    except Exception:
        return []

    parser = _LinkParser(base_url=str(response.url))
    parser.feed(response.text)
    return parser.links


async def _homepage_menu_links(website_url: str) -> list[str]:
    if MENU_DISCOVERY_MODE in {"browser", "chrome"}:
        return await _homepage_menu_links_browser(website_url)

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(website_url, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
    except Exception:
        return []

    parser = _LinkParser(base_url=str(response.url))
    parser.feed(response.text)
    return [link["url"] for link in parser.links if _looks_like_menu_url(link["url"], link.get("text", ""))]


async def _homepage_links_browser(website_url: str) -> list[str]:
    return [record["url"] for record in await _homepage_link_records_browser(website_url)]


async def _homepage_link_records_browser(website_url: str) -> list[dict[str, str]]:
    try:
        from playwright.async_api import async_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "MENU_DISCOVERY_MODE=browser requires Playwright. Run: "
            "pip install playwright && python -m playwright install chrome"
        ) from exc

    try:
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(channel="chrome", headless=True)
            except Exception:
                browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=USER_AGENT)
            try:
                await page.goto(website_url, wait_until="domcontentloaded", timeout=45000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                return await page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(a => ({url: a.href, text: (a.innerText || a.getAttribute('aria-label') || a.title || '').trim()}))",
                )
            finally:
                await browser.close()
    except Exception:
        return []


async def _homepage_menu_links_browser(website_url: str) -> list[str]:
    try:
        from playwright.async_api import async_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "MENU_DISCOVERY_MODE=browser requires Playwright. Run: "
            "pip install playwright && python -m playwright install chrome"
        ) from exc

    try:
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(channel="chrome", headless=True)
            except Exception:
                browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=USER_AGENT)
            try:
                await page.goto(website_url, wait_until="domcontentloaded", timeout=45000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                links = await page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(a => ({url: a.href, text: (a.innerText || a.getAttribute('aria-label') || a.title || '').trim()}))",
                )
                return [link["url"] for link in links if _looks_like_menu_url(link["url"], link.get("text", ""))]
            finally:
                await browser.close()
    except Exception:
        return []


def _common_menu_urls(website_url: str) -> list[str]:
    parsed = urllib.parse.urlparse(website_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    return [urllib.parse.urljoin(base, path) for path in COMMON_MENU_PATHS]


def _normalize_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return f"https://{url}"
    return url


def _looks_like_menu_url(url: str, text: str = "") -> bool:
    if url.lower().startswith(("tel:", "mailto:")):
        return False
    lowered = f"{url} {text}".lower()
    return any(token in lowered for token in ["menu", "order", "takeout", "delivery", "pickup"]) or any(
        token in lowered for token in PLATFORM_URL_TOKENS
    )


def _is_platform_url(url: str) -> bool:
    lowered = url.lower()
    return any(token in lowered for token in PLATFORM_URL_TOKENS)


def _classify_link(url: str, text: str = "") -> str:
    lowered = f"{url} {text}".lower()
    if url.lower().startswith(("tel:", "mailto:")):
        return "contact"
    if _is_platform_url(lowered):
        return "platform_ordering"
    if lowered.endswith(".pdf"):
        return "pdf_menu"
    if lowered.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return "image_menu"
    if any(token in lowered for token in ["menu", "menus", "food-menu", "restaurant-menu"]):
        return "menu_page"
    if any(token in lowered for token in ["order", "ordering", "takeout", "delivery", "pickup", "store"]):
        return "order_page"
    if any(token in lowered for token in ["instagram.com", "facebook.com", "x.com", "twitter.com"]):
        return "social"
    return "other"


def _write_link_report(output_path: str, rows: list[dict[str, Any]]) -> None:
    import csv
    from pathlib import Path

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["url", "text", "kind", "is_menu_candidate", "is_platform"])
        writer.writeheader()
        writer.writerows(rows)


class _LinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[dict[str, str]] = []
        self._current_link: dict[str, str] | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href")
        if not href:
            return
        self._current_link = {"url": urllib.parse.urljoin(self.base_url, href), "text": ""}
        self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_link is not None and data.strip():
            self._current_text.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_link is not None:
            self._current_link["text"] = " ".join(self._current_text).strip()
            self.links.append(self._current_link)
            self._current_link = None
            self._current_text = []
