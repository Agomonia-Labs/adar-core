"""Dry-run diagnostics for alternate menu extraction sources."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from domains.restaurants.db import connect, restaurants_for_menu_scrape
from domains.restaurants.ingestion.bulk_menu_ingest import discover_menu_urls
from domains.restaurants.ingestion.llm_menu_parser import llm_extraction_enabled, parse_menu_with_llm
from domains.restaurants.ingestion.menu_parser import parse_menu_html
from domains.restaurants.ingestion.menu_scraper import scrape_menu_url
from domains.restaurants.ingestion.menu_scraper import fetch_menu_html
from domains.restaurants.ingestion.platform_menu_parser import (
    detect_menu_platform,
    parse_platform_menu_html,
)


async def test_menu_alternates(
    cuisine_tags: list[str] | None = None,
    restaurant_name: str | None = None,
    limit: int = 10,
    max_menu_pages: int = 6,
    output_path: Path | None = None,
) -> dict[str, Any]:
    restaurants = await _restaurants_to_test(cuisine_tags, restaurant_name, limit)
    rows: list[dict[str, Any]] = []
    summary = {
        "restaurants_checked": len(restaurants),
        "urls_tested": 0,
        "generic_successes": 0,
        "platform_successes": 0,
        "llm_successes": 0,
        "errors": 0,
    }

    for restaurant in restaurants:
        candidates = await discover_menu_urls(restaurant["website_url"], max_candidates=max_menu_pages)
        if not candidates:
            rows.append(_row(restaurant, None, status="no_candidate_urls"))
            continue
        for url in candidates:
            summary["urls_tested"] += 1
            try:
                result = await _test_url(url)
                row = _row(restaurant, url, **result)
                rows.append(row)
                if result["generic_items"]:
                    summary["generic_successes"] += 1
                if result["platform_items"]:
                    summary["platform_successes"] += 1
                if result["llm_items"]:
                    summary["llm_successes"] += 1
            except Exception as exc:
                summary["errors"] += 1
                rows.append(_row(restaurant, url, status="error", error=str(exc)[:500]))

    report = {"summary": summary, "rows": rows}
    if output_path:
        _write_report(output_path, rows)
    return report


async def _restaurants_to_test(
    cuisine_tags: list[str] | None,
    restaurant_name: str | None,
    limit: int,
) -> list[Any]:
    conn = await connect()
    try:
        if restaurant_name:
            return await conn.fetch(
                """
                select id::text, name, website_url, cuisine_tags, meal_tags
                from restaurants
                where website_url is not null and website_url <> ''
                  and name ilike $1
                order by review_count desc nulls last, rating desc nulls last
                limit $2
                """,
                f"%{restaurant_name}%",
                limit,
            )
        return await restaurants_for_menu_scrape(
            conn,
            limit=limit,
            refresh=True,
            cuisine_tags=cuisine_tags or [],
        )
    finally:
        await conn.close()


async def _test_url(url: str) -> dict[str, Any]:
    html = await fetch_menu_html(url)
    generic_items = parse_menu_html(html, url)
    platform = detect_menu_platform(url, html)
    platform_items = parse_platform_menu_html(html, url)
    llm_items = []
    if llm_extraction_enabled() and not platform_items and len(generic_items) < 5:
        llm_items = await parse_menu_with_llm(_visible_text(html), url)
    best = max(
        [
            ("generic", generic_items),
            ("platform", platform_items),
            ("llm", llm_items),
        ],
        key=lambda pair: _priced_count(pair[1]),
    )
    return {
        "status": "ok",
        "platform": platform,
        "generic_items": len(generic_items),
        "generic_prices": _priced_count(generic_items),
        "platform_items": len(platform_items),
        "platform_prices": _priced_count(platform_items),
        "llm_items": len(llm_items),
        "llm_prices": _priced_count(llm_items),
        "best_method": best[0],
        "best_items": len(best[1]),
        "best_prices": _priced_count(best[1]),
        "sample_items": "; ".join(_sample_items(best[1])),
    }


def _priced_count(items: list[dict[str, Any]]) -> int:
    return sum(1 for item in items if item.get("price") is not None)


def _sample_items(items: list[dict[str, Any]], limit: int = 5) -> list[str]:
    sample = []
    for item in items[:limit]:
        price = item.get("price")
        sample.append(f"{item.get('name')} ({price})" if price is not None else str(item.get("name")))
    return sample


def _visible_text(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
    except ModuleNotFoundError:
        return html
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def _row(restaurant: Any, url: str | None, **values: Any) -> dict[str, Any]:
    base = {
        "restaurant_id": restaurant["id"],
        "restaurant_name": restaurant["name"],
        "website_url": restaurant["website_url"],
        "candidate_url": url or "",
        "cuisine_tags": ",".join(restaurant.get("cuisine_tags") or []),
    }
    defaults = {
        "status": "",
        "platform": "",
        "generic_items": 0,
        "generic_prices": 0,
        "platform_items": 0,
        "platform_prices": 0,
        "llm_items": 0,
        "llm_prices": 0,
        "best_method": "",
        "best_items": 0,
        "best_prices": 0,
        "sample_items": "",
        "error": "",
    }
    defaults.update(values)
    return {**base, **defaults}


def _write_report(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        return
    fieldnames = list(rows[0].keys()) if rows else [
        "restaurant_id",
        "restaurant_name",
        "website_url",
        "candidate_url",
        "status",
        "best_method",
        "best_items",
        "best_prices",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_menu_test_report(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("rows", data) if isinstance(data, dict) else data
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


async def ingest_successful_menu_tests(
    report_path: Path,
    min_prices: int = 1,
    max_urls: int | None = None,
    cuisine_tags: list[str] | None = None,
) -> dict[str, Any]:
    rows = load_menu_test_report(report_path)
    candidates = _successful_rows(rows, min_prices=min_prices)
    if max_urls is not None:
        candidates = candidates[:max_urls]

    counts = {
        "candidates": len(candidates),
        "menu_pages_attempted": 0,
        "menu_items": 0,
        "price_observations": 0,
        "errors": 0,
        "ingested": [],
    }
    for row in candidates:
        restaurant_id = row.get("restaurant_id")
        url = row.get("candidate_url")
        if not restaurant_id or not url:
            counts["errors"] += 1
            continue
        counts["menu_pages_attempted"] += 1
        try:
            result = await scrape_menu_url(
                restaurant_id=restaurant_id,
                source_url=url,
                cuisine_tags=cuisine_tags or _split_csv_tags(row.get("cuisine_tags")),
            )
            counts["menu_items"] += result["menu_items"]
            counts["price_observations"] += result["price_observations"]
            counts["ingested"].append({
                "restaurant_name": row.get("restaurant_name"),
                "candidate_url": url,
                **result,
            })
            print(
                f"Saved {result['menu_items']} items / {result['price_observations']} prices "
                f"for {row.get('restaurant_name')} from {url}"
            )
        except Exception as exc:
            counts["errors"] += 1
            print(f"Failed to ingest {row.get('restaurant_name')} from {url}: {exc}")
    return counts


def _successful_rows(rows: list[dict[str, Any]], min_prices: int) -> list[dict[str, Any]]:
    deduped = []
    seen_restaurants = set()
    for row in sorted(rows, key=_row_score, reverse=True):
        restaurant_id = row.get("restaurant_id")
        url = row.get("candidate_url")
        if not restaurant_id or not url or restaurant_id in seen_restaurants:
            continue
        if _int_value(row.get("best_prices")) < min_prices:
            continue
        deduped.append(row)
        seen_restaurants.add(restaurant_id)
    return deduped


def _row_score(row: dict[str, Any]) -> tuple[int, int]:
    return (_int_value(row.get("best_prices")), _int_value(row.get("best_items")))


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _split_csv_tags(value: str | None) -> list[str]:
    if not value:
        return []
    return [tag.strip() for tag in value.split(",") if tag.strip()]
