"""Official menu scraping helpers."""

from __future__ import annotations

import urllib.parse
import urllib.robotparser
from datetime import datetime, timezone
import os
import tempfile
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from domains.restaurants.db import (
    add_price_observation,
    connect,
    log_menu_scrape_attempt,
    upsert_menu_item,
    upsert_menu_source,
)
from domains.restaurants.ingestion.image_menu_parser import extract_image_text
from domains.restaurants.ingestion.menu_parser import parse_menu_html, parse_menu_text
from domains.restaurants.ingestion.llm_menu_parser import parse_menu_with_llm
from domains.restaurants.ingestion.platform_menu_parser import (
    detect_menu_platform,
    parse_platform_menu_html,
)
from domains.restaurants.ingestion.normalization import (
    menu_item_id,
    normalize_tags,
    normalize_text,
)


USER_AGENT = "AdarRestaurantIngestion/0.1 (+https://agomoniai.com)"
MENU_FETCH_MODE = os.getenv("MENU_FETCH_MODE", "http").lower()
MENU_BROWSER_OCR_FALLBACK = os.getenv("MENU_BROWSER_OCR_FALLBACK", "true").lower() in {"1", "true", "yes"}
MENU_BROWSER_TIMEOUT_MS = int(os.getenv("MENU_BROWSER_TIMEOUT_MS", "45000"))
MENU_BROWSER_SETTLE_MS = int(os.getenv("MENU_BROWSER_SETTLE_MS", "5000"))
OCR_HTML_MARKER = "adar-browser-ocr"


async def robots_allowed(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        try:
            response = await client.get(robots_url, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError:
            return True
    if response.status_code >= 400:
        return True
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(response.text.splitlines())
    return parser.can_fetch(USER_AGENT, url)


async def fetch_menu_html(url: str) -> str:
    if not await robots_allowed(url):
        raise PermissionError(f"robots.txt disallows scraping {url}")
    if MENU_FETCH_MODE in {"browser", "chrome"}:
        return await fetch_menu_html_with_browser(url)
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(url, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.text


async def fetch_menu_html_with_browser(url: str) -> str:
    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "MENU_FETCH_MODE=browser requires Playwright. Run: "
            "pip install playwright && python -m playwright install chrome"
        ) from exc

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=USER_AGENT)
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=MENU_BROWSER_TIMEOUT_MS)
            if response and response.status >= 400:
                raise httpx.HTTPStatusError(
                    f"Browser fetch failed with HTTP {response.status}",
                    request=httpx.Request("GET", url),
                    response=httpx.Response(response.status, request=httpx.Request("GET", url)),
                )
            try:
                await page.wait_for_load_state("networkidle", timeout=MENU_BROWSER_SETTLE_MS)
            except PlaywrightTimeoutError:
                pass
            return await page.content()
        except PlaywrightTimeoutError:
            if not MENU_BROWSER_OCR_FALLBACK:
                raise
            text = await _ocr_browser_page(page, url)
            if text.strip():
                return _ocr_text_as_html(text)
            raise
        finally:
            await browser.close()


async def scrape_menu_url(
    restaurant_id: str,
    source_url: str,
    cuisine_tags: list[str] | None = None,
    meal_tags: list[str] | None = None,
) -> dict[str, Any]:
    html = await fetch_menu_html(source_url)
    parsed_items = parse_menu_html(html, source_url)
    if not parsed_items and OCR_HTML_MARKER in html:
        parsed_items = parse_menu_text(_visible_text(html), source_url, source_type="browser_screenshot_ocr")
    platform = detect_menu_platform(source_url, html)
    platform_items = parse_platform_menu_html(html, source_url) if platform or not parsed_items else []
    if platform_items and (
        not parsed_items
        or sum(1 for item in platform_items if item.get("price") is not None)
        > sum(1 for item in parsed_items if item.get("price") is not None)
    ):
        parsed_items = platform_items
    if not parsed_items:
        parsed_items = await parse_menu_with_llm(_visible_text(html), source_url)
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
                    "cuisine_tags": normalize_tags(cuisine_tags),
                    "meal_tags": normalize_tags(meal_tags),
                    "dietary_tags": normalize_tags(parsed.get("dietary_tags")),
                    "last_seen_at": datetime.now(timezone.utc),
                }
                await upsert_menu_item(conn, item)
                await add_price_observation(conn, item)
                counts["menu_items"] += 1
                if item.get("price") is not None:
                    counts["price_observations"] += 1
            await upsert_menu_source(conn, {
                "restaurant_id": restaurant_id,
                "source_url": source_url,
                "source_type": "website",
                "status": "parsed" if counts["menu_items"] else "no_items",
                "confidence": 0.75 if counts["menu_items"] else 0.20,
                "discovered_by": "scraper",
                "last_checked_at": datetime.now(timezone.utc),
            })
            await log_menu_scrape_attempt(conn, {
                "restaurant_id": restaurant_id,
                "source_url": source_url,
                "source_type": "website",
                "fetch_mode": MENU_FETCH_MODE,
                "status": "success" if counts["menu_items"] else "no_items",
                "items_found": counts["menu_items"],
                "prices_found": counts["price_observations"],
            })
    finally:
        await conn.close()
    return {
        "source_url": source_url,
        "parsed_items": len(parsed_items),
        **counts,
    }


def _visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


async def _ocr_browser_page(page: Any, url: str) -> str:
    screenshot_path = Path(tempfile.gettempdir()) / f"adar_menu_ocr_{abs(hash(url))}.png"
    await page.screenshot(path=str(screenshot_path), full_page=True)
    try:
        return extract_image_text(screenshot_path)
    finally:
        try:
            screenshot_path.unlink(missing_ok=True)
        except OSError:
            pass


def _ocr_text_as_html(text: str) -> str:
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return f"<html><body data-source='{OCR_HTML_MARKER}'><pre>{escaped}</pre></body></html>"
