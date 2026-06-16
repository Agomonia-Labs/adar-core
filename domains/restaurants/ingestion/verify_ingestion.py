"""Print ingestion counts and sample rows."""

from __future__ import annotations

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


async def main() -> None:
    from domains.restaurants.db import connect, ingestion_counts

    conn = await connect()
    try:
        counts = await ingestion_counts(conn)
        print("Counts")
        for key, value in counts.items():
            print(f"  {key}: {value}")

        print("\nTop restaurants")
        rows = await conn.fetch(
            """
            select name, cuisine_tags, rating, review_count, website_url
            from restaurants
            order by review_count desc nulls last, rating desc nulls last
            limit 10
            """
        )
        for row in rows:
            print(
                f"  {row['name']} | {row['cuisine_tags']} | "
                f"rating={row['rating']} reviews={row['review_count']} | "
                f"{row['website_url'] or '-'}"
            )

        print("\nSample menu items")
        rows = await conn.fetch(
            """
            select r.name as restaurant_name, mi.name, mi.price, mi.source_url
            from menu_items mi
            join restaurants r on r.id = mi.restaurant_id
            order by mi.last_seen_at desc nulls last
            limit 10
            """
        )
        for row in rows:
            print(
                f"  {row['restaurant_name']} | {row['name']} | "
                f"{row['price'] or '-'} | {row['source_url'] or '-'}"
            )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

