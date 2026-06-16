"""Restaurant recommender ingestion pipeline.

Usage:
    # Apply schema
    DOMAIN=restaurants PYTHONPATH=$(pwd) python -m domains.restaurants.ingestion.run_ingestion --only schema

    # Ingest seeded restaurants and menu items from JSON/CSV
    DOMAIN=restaurants PYTHONPATH=$(pwd) python -m domains.restaurants.ingestion.run_ingestion \
      --only restaurants --source domains/restaurants/data/sample_restaurants.json

    # Scrape one known official menu URL into an existing restaurant
    DOMAIN=restaurants PYTHONPATH=$(pwd) python -m domains.restaurants.ingestion.run_ingestion \
      --only menu-url --restaurant-id <uuid> --menu-url https://example.com/menu

    # Embed missing menu items
    DOMAIN=restaurants PYTHONPATH=$(pwd) python -m domains.restaurants.ingestion.run_ingestion --only embeddings

    # Ingest reviews from JSON/CSV
    DOMAIN=restaurants PYTHONPATH=$(pwd) python -m domains.restaurants.ingestion.run_ingestion \
      --only reviews --reviews-source domains/restaurants/data/sample_reviews.json

    # Discover restaurants from Google Places around Greater Seattle
    DOMAIN=restaurants PYTHONPATH=$(pwd) python -m domains.restaurants.ingestion.run_ingestion \
      --only places --location greater-seattle --radius-miles 60

    # Bulk scrape menus from discovered restaurant websites
    DOMAIN=restaurants PYTHONPATH=$(pwd) python -m domains.restaurants.ingestion.run_ingestion \
      --only bulk-menus --limit 25

    # Scrape menus for one cuisine using website/order-platform/PDF-like extraction
    DOMAIN=restaurants PYTHONPATH=$(pwd) MENU_DISCOVERY_MODE=browser MENU_FETCH_MODE=browser \
      python -m domains.restaurants.ingestion.run_ingestion \
      --only menus --cuisine thai --limit 25 --max-menu-pages 6

    # Optional paid LLM fallback for visible menu text when structured extraction fails
    DOMAIN=restaurants PYTHONPATH=$(pwd) MENU_LLM_EXTRACT=1 \
      python -m domains.restaurants.ingestion.run_ingestion \
      --only menus --cuisine thai --limit 25 --max-menu-pages 6

    # Dry-run alternate menu extraction without saving menu items
    DOMAIN=restaurants PYTHONPATH=$(pwd) MENU_DISCOVERY_MODE=browser MENU_FETCH_MODE=browser \
      python -m domains.restaurants.ingestion.run_ingestion \
      --only test-menus --cuisine thai --limit 10 --max-menu-pages 6

    # Ingest all successful URLs from a dry-run menu source report
    DOMAIN=restaurants PYTHONPATH=$(pwd) MENU_FETCH_MODE=browser \
      python -m domains.restaurants.ingestion.run_ingestion \
      --only ingest-tested-menus --menu-test-output domains/restaurants/data/menu_source_test.csv

    # Inspect links from a restaurant website without scraping menu items
    DOMAIN=restaurants PYTHONPATH=$(pwd) MENU_DISCOVERY_MODE=browser \
      python -m domains.restaurants.ingestion.run_ingestion \
      --only inspect-links --restaurant-name "Rachawadee"

    # Ingest manually curated menu URLs
    DOMAIN=restaurants PYTHONPATH=$(pwd) python -m domains.restaurants.ingestion.run_ingestion \
      --only manual-menus --manual-menu-source domains/restaurants/data/manual_menu_urls.json

    # Import human-reviewed menu items
    DOMAIN=restaurants PYTHONPATH=$(pwd) python -m domains.restaurants.ingestion.run_ingestion \
      --only curated-menus --curated-menu-source domains/restaurants/data/curated_menu_items.csv

    # Export open curation queue
    DOMAIN=restaurants PYTHONPATH=$(pwd) python -m domains.restaurants.ingestion.run_ingestion \
      --only export-curation --curation-export-path domains/restaurants/data/curation_queue.csv
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path


if os.environ.get("APP_ENV") != "production":
    try:
        from dotenv import load_dotenv

        load_dotenv(os.environ.get("DOTENV_FILE", ".env"), override=True)
    except ModuleNotFoundError:
        env_path = Path(os.environ.get("DOTENV_FILE", ".env"))
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip().strip('"').strip("'")


async def step_schema() -> None:
    from domains.restaurants.db import execute_schema

    print("=== Step 1: Applying restaurant Postgres schema ===")
    await execute_schema()
    print("Schema ready.")


async def step_restaurants(source: str | None) -> None:
    from domains.restaurants.ingestion.restaurant_ingest import ingest_source_file

    if not source:
        raise ValueError("--source is required for --only restaurants")
    print(f"=== Step 2: Ingesting restaurants from {source} ===")
    counts = await ingest_source_file(Path(source))
    print(
        "Ingested "
        f"{counts['restaurants']} restaurants, "
        f"{counts['menu_items']} menu items, "
        f"{counts['price_observations']} price observations."
    )


async def step_menu_url(
    restaurant_id: str | None,
    menu_url: str | None,
    cuisine_tags: str | None,
    meal_tags: str | None,
) -> None:
    from domains.restaurants.ingestion.menu_scraper import scrape_menu_url

    if not restaurant_id or not menu_url:
        raise ValueError("--restaurant-id and --menu-url are required for --only menu-url")
    print(f"=== Step 3: Scraping menu URL {menu_url} ===")
    result = await scrape_menu_url(
        restaurant_id=restaurant_id,
        source_url=menu_url,
        cuisine_tags=_split_tags(cuisine_tags),
        meal_tags=_split_tags(meal_tags),
    )
    print(
        "Scraped "
        f"{result['parsed_items']} parsed items, "
        f"{result['menu_items']} saved menu items, "
        f"{result['price_observations']} price observations."
    )


async def step_embeddings(limit: int) -> None:
    from domains.restaurants.ingestion.embedder import embed_missing_menu_items

    print(f"=== Step 4: Embedding up to {limit} menu items ===")
    count = await embed_missing_menu_items(limit=limit)
    print(f"Embedded {count} menu items.")


async def step_reviews(source: str | None) -> None:
    from domains.restaurants.ingestion.review_ingest import ingest_reviews_file

    if not source:
        raise ValueError("--reviews-source is required for --only reviews")
    print(f"=== Step 5: Ingesting reviews from {source} ===")
    counts = await ingest_reviews_file(Path(source))
    print(f"Ingested {counts['reviews']} reviews.")


async def step_places(
    location: str,
    radius_miles: float,
    tile_radius_miles: float,
    place_types: str | None,
) -> None:
    from domains.restaurants.ingestion.places_ingest import ingest_google_places_area

    print(
        "=== Step 6: Discovering restaurants from Google Places "
        f"for {location} within {radius_miles} miles ==="
    )
    counts = await ingest_google_places_area(
        location=location,
        radius_miles=radius_miles,
        tile_radius_miles=tile_radius_miles,
        included_primary_types=_split_tags(place_types) or None,
    )
    print(
        "Google Places ingestion complete: "
        f"{counts['restaurants']} restaurants saved, "
        f"{counts['duplicates']} duplicates skipped, "
        f"{counts['places_seen']} places seen across "
        f"{counts['requests']} requests / {counts['tiles']} tiles."
    )


async def step_bulk_menus(
    limit: int,
    refresh_menus: bool,
    max_menu_pages: int,
    cuisine_tags: str | None = None,
) -> None:
    from domains.restaurants.ingestion.bulk_menu_ingest import bulk_scrape_menus

    tags = _split_tags(cuisine_tags)
    print(
        "=== Step 7: Bulk scraping menus from restaurant websites "
        f"(limit={limit}, refresh={refresh_menus}, cuisine={tags or 'any'}) ==="
    )
    counts = await bulk_scrape_menus(
        limit=limit,
        refresh=refresh_menus,
        max_menu_pages_per_restaurant=max_menu_pages,
        cuisine_tags=tags,
    )
    print(
        "Bulk menu scrape complete: "
        f"{counts['restaurants_checked']} restaurants checked, "
        f"{counts['restaurants_with_menu']} restaurants with menu items, "
        f"{counts['menu_pages_attempted']} menu pages attempted, "
        f"{counts['menu_items']} menu items, "
        f"{counts['price_observations']} price observations, "
        f"{counts['errors']} errors."
    )


async def step_manual_menus(source: str | None) -> None:
    from domains.restaurants.ingestion.manual_menu_ingest import ingest_manual_menu_urls

    if not source:
        raise ValueError("--manual-menu-source is required for --only manual-menus")
    print(f"=== Step 8: Ingesting manually curated menu URLs from {source} ===")
    counts = await ingest_manual_menu_urls(Path(source))
    print(
        "Manual menu ingestion complete: "
        f"{counts['records']} records, "
        f"{counts['menu_pages_attempted']} menu pages attempted, "
        f"{counts['menu_items']} menu items, "
        f"{counts['price_observations']} price observations, "
        f"{counts['errors']} errors."
    )


async def step_curated_menus(source: str | None) -> None:
    from domains.restaurants.ingestion.curated_menu_ingest import ingest_curated_menu_items

    if not source:
        raise ValueError("--curated-menu-source is required for --only curated-menus")
    print(f"=== Step 9: Importing curated menu items from {source} ===")
    counts = await ingest_curated_menu_items(Path(source))
    print(
        "Curated menu import complete: "
        f"{counts['menu_items']} menu items, "
        f"{counts['price_observations']} price observations, "
        f"{counts['sources']} verified sources."
    )


async def step_export_curation(path: str) -> None:
    from domains.restaurants.ingestion.curation_export import export_curation_queue

    print(f"=== Step 10: Exporting curation queue to {path} ===")
    result = await export_curation_queue(Path(path))
    print(f"Exported {result['rows']} curation rows to {result['path']}.")


async def step_test_menus(
    cuisine_tags: str | None,
    restaurant_name: str | None,
    limit: int,
    max_menu_pages: int,
    output_path: str | None,
) -> None:
    from domains.restaurants.ingestion.menu_source_diagnostics import test_menu_alternates

    print(
        "=== Testing alternate menu extraction sources "
        f"(cuisine={cuisine_tags or 'any'}, restaurant={restaurant_name or 'any'}, "
        f"limit={limit}, max_pages={max_menu_pages}) ==="
    )
    report = await test_menu_alternates(
        cuisine_tags=_split_tags(cuisine_tags),
        restaurant_name=restaurant_name,
        limit=limit,
        max_menu_pages=max_menu_pages,
        output_path=Path(output_path) if output_path else None,
    )
    summary = report["summary"]
    print(
        "Menu source test complete: "
        f"{summary['restaurants_checked']} restaurants, "
        f"{summary['urls_tested']} URLs, "
        f"{summary['generic_successes']} generic successes, "
        f"{summary['platform_successes']} platform successes, "
        f"{summary['llm_successes']} LLM successes, "
        f"{summary['errors']} errors."
    )
    if output_path:
        print(f"Report written to {output_path}")
    for row in report["rows"][:20]:
        print(
            f"- {row['restaurant_name']} | {row['candidate_url'] or '-'} | "
            f"best={row['best_method'] or row['status']} "
            f"items={row['best_items']} prices={row['best_prices']} "
            f"samples={row['sample_items'] or row.get('error', '')}"
        )


async def step_ingest_tested_menus(
    report_path: str,
    min_prices: int,
    max_urls: int | None,
    cuisine_tags: str | None,
) -> None:
    from domains.restaurants.ingestion.menu_source_diagnostics import ingest_successful_menu_tests

    print(
        "=== Ingesting successful menu test URLs "
        f"(report={report_path}, min_prices={min_prices}, max_urls={max_urls or 'all'}) ==="
    )
    counts = await ingest_successful_menu_tests(
        report_path=Path(report_path),
        min_prices=min_prices,
        max_urls=max_urls,
        cuisine_tags=_split_tags(cuisine_tags),
    )
    print(
        "Tested menu ingestion complete: "
        f"{counts['candidates']} candidates, "
        f"{counts['menu_pages_attempted']} pages attempted, "
        f"{counts['menu_items']} menu items, "
        f"{counts['price_observations']} price observations, "
        f"{counts['errors']} errors."
    )


async def step_inspect_links(
    website_url: str | None,
    restaurant_name: str | None,
    output_path: str | None,
) -> None:
    from domains.restaurants.db import connect
    from domains.restaurants.ingestion.bulk_menu_ingest import inspect_website_links

    target_url = website_url
    if not target_url and restaurant_name:
        conn = await connect()
        try:
            row = await conn.fetchrow(
                """
                select name, website_url
                from restaurants
                where website_url is not null and website_url <> ''
                  and name ilike $1
                order by review_count desc nulls last, rating desc nulls last
                limit 1
                """,
                f"%{restaurant_name}%",
            )
        finally:
            await conn.close()
        if not row:
            raise ValueError(f"No restaurant with website found for name filter: {restaurant_name}")
        print(f"Inspecting links for {row['name']} ({row['website_url']})")
        target_url = row["website_url"]
    if not target_url:
        raise ValueError("--website-url or --restaurant-name is required for --only inspect-links")

    report = await inspect_website_links(target_url, output_path=output_path)
    print(
        "Link inspection complete: "
        f"{report['total_links']} links, "
        f"{report['menu_candidates']} menu/order candidates, "
        f"{report['platform_links']} platform links."
    )
    if output_path:
        print(f"Report written to {output_path}")
    for row in report["links"][:50]:
        marker = "*" if row["is_menu_candidate"] else " "
        print(f"{marker} [{row['kind']}] {row['url']}")


async def main(args: argparse.Namespace) -> None:
    if args.only == "schema":
        await step_schema()
    elif args.only == "restaurants":
        await step_restaurants(args.source)
    elif args.only == "menu-url":
        await step_menu_url(args.restaurant_id, args.menu_url, args.cuisine, args.meal)
    elif args.only == "embeddings":
        await step_embeddings(args.limit)
    elif args.only == "reviews":
        await step_reviews(args.reviews_source)
    elif args.only == "places":
        await step_places(
            args.location,
            args.radius_miles,
            args.tile_radius_miles,
            args.place_types,
        )
    elif args.only == "bulk-menus":
        await step_bulk_menus(args.limit, args.refresh_menus, args.max_menu_pages)
    elif args.only in {"menus", "cuisine-menus"}:
        await step_bulk_menus(args.limit, args.refresh_menus, args.max_menu_pages, args.cuisine)
    elif args.only == "manual-menus":
        await step_manual_menus(args.manual_menu_source)
    elif args.only == "curated-menus":
        await step_curated_menus(args.curated_menu_source)
    elif args.only == "export-curation":
        await step_export_curation(args.curation_export_path)
    elif args.only == "test-menus":
        await step_test_menus(
            args.cuisine,
            args.restaurant_name,
            args.limit,
            args.max_menu_pages,
            args.menu_test_output,
        )
    elif args.only == "ingest-tested-menus":
        await step_ingest_tested_menus(
            args.menu_test_output,
            args.min_prices,
            args.max_urls,
            args.cuisine,
        )
    elif args.only == "inspect-links":
        await step_inspect_links(args.website_url, args.restaurant_name, args.link_output)
    else:
        await step_schema()
        if args.source:
            await step_restaurants(args.source)
        if args.reviews_source:
            await step_reviews(args.reviews_source)
        await step_embeddings(args.limit)
    print("\nAll done.")


def _split_tags(value: str | None) -> list[str]:
    if not value:
        return []
    return [tag.strip() for tag in value.split(",") if tag.strip()]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Restaurant recommender ingestion pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--only",
        choices=[
            "schema",
            "restaurants",
            "menu-url",
            "embeddings",
            "reviews",
            "places",
            "bulk-menus",
            "menus",
            "cuisine-menus",
            "manual-menus",
            "curated-menus",
            "export-curation",
            "test-menus",
            "ingest-tested-menus",
            "inspect-links",
        ],
        default=None,
        help="Run one ingestion step. Default: schema, optional source ingest, embeddings.",
    )
    parser.add_argument("--source", help="JSON or CSV file containing restaurants.")
    parser.add_argument("--reviews-source", help="JSON or CSV file containing reviews.")
    parser.add_argument("--manual-menu-source", help="JSON or CSV file containing curated menu URLs.")
    parser.add_argument("--curated-menu-source", help="CSV or JSON file containing human-reviewed menu items.")
    parser.add_argument(
        "--curation-export-path",
        default="domains/restaurants/data/curation_queue.csv",
        help="CSV path for --only export-curation.",
    )
    parser.add_argument("--restaurant-id", help="Restaurant UUID for --only menu-url.")
    parser.add_argument("--restaurant-name", help="Restaurant name filter for --only test-menus.")
    parser.add_argument("--menu-url", help="Official menu URL for --only menu-url.")
    parser.add_argument("--website-url", help="Website URL for --only inspect-links.")
    parser.add_argument(
        "--link-output",
        default="domains/restaurants/data/website_links.csv",
        help="CSV/JSON report path for --only inspect-links.",
    )
    parser.add_argument(
        "--menu-test-output",
        default="domains/restaurants/data/menu_source_test.csv",
        help="CSV/JSON report path for --only test-menus or --only ingest-tested-menus.",
    )
    parser.add_argument(
        "--min-prices",
        type=int,
        default=1,
        help="Minimum dry-run priced items required for --only ingest-tested-menus.",
    )
    parser.add_argument(
        "--max-urls",
        type=int,
        help="Maximum successful test URLs to ingest with --only ingest-tested-menus.",
    )
    parser.add_argument("--cuisine", help="Comma-separated cuisine tags for scraped menu items.")
    parser.add_argument("--meal", help="Comma-separated meal tags for scraped menu items.")
    parser.add_argument("--limit", type=int, default=100, help="Embedding batch size.")
    parser.add_argument(
        "--refresh-menus",
        action="store_true",
        help="With --only bulk-menus, revisit restaurants even if menu items already exist.",
    )
    parser.add_argument(
        "--max-menu-pages",
        type=int,
        default=3,
        help="With --only bulk-menus, max candidate menu pages per restaurant.",
    )
    parser.add_argument(
        "--location",
        default="greater-seattle",
        help="Location preset or 'lat,lng'. Default: greater-seattle.",
    )
    parser.add_argument(
        "--radius-miles",
        type=float,
        default=60.0,
        help="Discovery radius in miles. Default: 60.",
    )
    parser.add_argument(
        "--tile-radius-miles",
        type=float,
        default=25.0,
        help="Google Places tile radius. Must be <= about 31 miles. Default: 25.",
    )
    parser.add_argument(
        "--place-types",
        help="Comma-separated Google includedPrimaryTypes. Default: restaurant,cafe,bakery,bar,meal_takeaway.",
    )
    asyncio.run(main(parser.parse_args()))
