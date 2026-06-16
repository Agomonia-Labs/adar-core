"""Postgres helpers for the restaurant recommender domain."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


DATABASE_URL_ENV = "RESTAURANTS_DATABASE_URL"


def get_database_url() -> str:
    url = os.getenv(DATABASE_URL_ENV) or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            f"Set {DATABASE_URL_ENV}=postgresql://user:password@host:5432/restaurants "
            "or DATABASE_URL to a Postgres database "
            "with pgvector enabled."
        )
    return url


async def connect() -> asyncpg.Connection:
    import asyncpg

    return await asyncpg.connect(get_database_url())


async def execute_schema(schema_path: Path | None = None) -> None:
    path = schema_path or Path(__file__).parent / "ingestion" / "schema.sql"
    sql = path.read_text(encoding="utf-8")
    conn = await connect()
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


async def upsert_restaurant(conn: Any, restaurant: dict[str, Any]) -> str:
    row = await conn.fetchrow(
        """
        insert into restaurants (
            id, name, normalized_name, website_url, phone, address, city, region,
            postal_code, country, latitude, longitude, rating, review_count,
            price_level, service_types, cuisine_tags, meal_tags, source_refs,
            updated_at
        )
        values (
            $1, $2, $3, $4, $5, $6, $7, $8,
            $9, coalesce($10, 'US'), $11, $12,
            $13, coalesce($14, 0), $15, $16, $17, $18,
            coalesce($19::jsonb, '[]'::jsonb), now()
        )
        on conflict (id) do update set
            name = excluded.name,
            normalized_name = excluded.normalized_name,
            website_url = coalesce(excluded.website_url, restaurants.website_url),
            phone = coalesce(excluded.phone, restaurants.phone),
            address = coalesce(excluded.address, restaurants.address),
            city = coalesce(excluded.city, restaurants.city),
            region = coalesce(excluded.region, restaurants.region),
            postal_code = coalesce(excluded.postal_code, restaurants.postal_code),
            country = coalesce(excluded.country, restaurants.country),
            latitude = coalesce(excluded.latitude, restaurants.latitude),
            longitude = coalesce(excluded.longitude, restaurants.longitude),
            rating = coalesce(excluded.rating, restaurants.rating),
            review_count = greatest(restaurants.review_count, excluded.review_count),
            price_level = coalesce(excluded.price_level, restaurants.price_level),
            service_types = excluded.service_types,
            cuisine_tags = excluded.cuisine_tags,
            meal_tags = excluded.meal_tags,
            source_refs = excluded.source_refs,
            updated_at = now()
        returning id::text
        """,
        restaurant["id"],
        restaurant["name"],
        restaurant["normalized_name"],
        restaurant.get("website_url"),
        restaurant.get("phone"),
        restaurant.get("address"),
        restaurant.get("city"),
        restaurant.get("region"),
        restaurant.get("postal_code"),
        restaurant.get("country", "US"),
        restaurant.get("latitude"),
        restaurant.get("longitude"),
        restaurant.get("rating"),
        restaurant.get("review_count", 0),
        restaurant.get("price_level"),
        restaurant.get("service_types", []),
        restaurant.get("cuisine_tags", []),
        restaurant.get("meal_tags", []),
        restaurant.get("source_refs_json", "[]"),
    )
    return row["id"]


async def upsert_menu_item(conn: Any, item: dict[str, Any]) -> str:
    row = await conn.fetchrow(
        """
        insert into menu_items (
            id, restaurant_id, name, normalized_name, description, category,
            cuisine_tags, meal_tags, dietary_tags, price, currency, portion_size,
            serves_qty, availability, source_url, source_type,
            extraction_confidence, last_seen_at, search_tsv
        )
        values (
            $1, $2, $3, $4, $5, $6, $7, $8, $9,
            $10, coalesce($11, 'USD'), $12, $13, $14, $15, $16,
            $17, coalesce($18, now()),
            to_tsvector(
              'english',
              coalesce($3, '') || ' ' ||
              coalesce($5, '') || ' ' ||
              coalesce($6, '') || ' ' ||
              array_to_string($7::text[], ' ') || ' ' ||
              array_to_string($8::text[], ' ') || ' ' ||
              array_to_string($9::text[], ' ')
            )
        )
        on conflict (id) do update set
            name = excluded.name,
            normalized_name = excluded.normalized_name,
            description = coalesce(excluded.description, menu_items.description),
            category = coalesce(excluded.category, menu_items.category),
            cuisine_tags = excluded.cuisine_tags,
            meal_tags = excluded.meal_tags,
            dietary_tags = excluded.dietary_tags,
            price = coalesce(excluded.price, menu_items.price),
            currency = coalesce(excluded.currency, menu_items.currency),
            portion_size = coalesce(excluded.portion_size, menu_items.portion_size),
            serves_qty = coalesce(excluded.serves_qty, menu_items.serves_qty),
            availability = coalesce(excluded.availability, menu_items.availability),
            source_url = coalesce(excluded.source_url, menu_items.source_url),
            source_type = coalesce(excluded.source_type, menu_items.source_type),
            extraction_confidence = greatest(
                coalesce(menu_items.extraction_confidence, 0),
                coalesce(excluded.extraction_confidence, 0)
            ),
            last_seen_at = greatest(menu_items.last_seen_at, excluded.last_seen_at),
            search_tsv = excluded.search_tsv
        returning id::text
        """,
        item["id"],
        item["restaurant_id"],
        item["name"],
        item["normalized_name"],
        item.get("description"),
        item.get("category"),
        item.get("cuisine_tags", []),
        item.get("meal_tags", []),
        item.get("dietary_tags", []),
        item.get("price"),
        item.get("currency", "USD"),
        item.get("portion_size"),
        item.get("serves_qty"),
        item.get("availability"),
        item.get("source_url"),
        item.get("source_type"),
        item.get("extraction_confidence"),
        item.get("last_seen_at"),
    )
    return row["id"]


async def add_price_observation(conn: Any, item: dict[str, Any]) -> None:
    if item.get("price") is None:
        return
    await conn.execute(
        """
        insert into price_observations (
            menu_item_id, restaurant_id, price, currency, source_url, confidence
        )
        values ($1, $2, $3, coalesce($4, 'USD'), $5, $6)
        on conflict do nothing
        """,
        item["id"],
        item["restaurant_id"],
        item["price"],
        item.get("currency", "USD"),
        item.get("source_url"),
        item.get("extraction_confidence"),
    )


async def upsert_menu_source(conn: Any, source: dict[str, Any]) -> str:
    row = await conn.fetchrow(
        """
        insert into menu_sources (
            restaurant_id, source_url, source_type, status, confidence, notes,
            discovered_by, last_checked_at, updated_at
        )
        values ($1, $2, coalesce($3, 'website'), coalesce($4, 'pending'), $5, $6,
                coalesce($7, 'system'), $8, now())
        on conflict (restaurant_id, source_url) do update set
            source_type = coalesce(excluded.source_type, menu_sources.source_type),
            status = excluded.status,
            confidence = coalesce(excluded.confidence, menu_sources.confidence),
            notes = coalesce(excluded.notes, menu_sources.notes),
            discovered_by = coalesce(excluded.discovered_by, menu_sources.discovered_by),
            last_checked_at = coalesce(excluded.last_checked_at, menu_sources.last_checked_at),
            updated_at = now()
        returning id::text
        """,
        source["restaurant_id"],
        source["source_url"],
        source.get("source_type"),
        source.get("status"),
        source.get("confidence"),
        source.get("notes"),
        source.get("discovered_by"),
        source.get("last_checked_at"),
    )
    return row["id"]


async def log_menu_scrape_attempt(conn: Any, attempt: dict[str, Any]) -> str:
    row = await conn.fetchrow(
        """
        insert into menu_scrape_attempts (
            restaurant_id, source_url, source_type, fetch_mode, status,
            http_status, items_found, prices_found, error
        )
        values ($1, $2, $3, $4, $5, $6, coalesce($7, 0), coalesce($8, 0), $9)
        returning id::text
        """,
        attempt["restaurant_id"],
        attempt["source_url"],
        attempt.get("source_type"),
        attempt.get("fetch_mode"),
        attempt["status"],
        attempt.get("http_status"),
        attempt.get("items_found"),
        attempt.get("prices_found"),
        attempt.get("error"),
    )
    return row["id"]


async def enqueue_menu_curation(conn: Any, item: dict[str, Any]) -> str:
    row = await conn.fetchrow(
        """
        insert into menu_curation_queue (
            restaurant_id, source_url, reason, status, priority, details, updated_at
        )
        values ($1, $2, $3, coalesce($4, 'open'), coalesce($5, 2),
                coalesce($6::jsonb, '{}'::jsonb), now())
        on conflict (restaurant_id, source_url, reason) do update set
            status = excluded.status,
            priority = least(menu_curation_queue.priority, excluded.priority),
            details = menu_curation_queue.details || excluded.details,
            updated_at = now()
        returning id::text
        """,
        item["restaurant_id"],
        item.get("source_url"),
        item["reason"],
        item.get("status"),
        item.get("priority"),
        item.get("details_json", "{}"),
    )
    return row["id"]


async def menu_items_missing_embeddings(
    conn: Any,
    limit: int,
) -> list[Any]:
    return await conn.fetch(
        """
        select id::text, name, description, category, cuisine_tags, meal_tags,
               dietary_tags
        from menu_items
        where embedding is null
        order by last_seen_at desc nulls last
        limit $1
        """,
        limit,
    )


async def update_menu_embedding(
    conn: Any,
    item_id: str,
    embedding: list[float],
) -> None:
    vector_literal = "[" + ",".join(str(v) for v in embedding) + "]"
    await conn.execute(
        "update menu_items set embedding = $2::vector where id = $1",
        item_id,
        vector_literal,
    )


async def upsert_review(conn: Any, review: dict[str, Any]) -> str:
    row = await conn.fetchrow(
        """
        insert into reviews (
            id, restaurant_id, source, external_review_id, rating, text, review_date,
            search_tsv
        )
        values ($1, $2, $3, $4, $5, $6, $7::date, to_tsvector('english', coalesce($6, '')))
        on conflict (id) do update set
            source = coalesce(excluded.source, reviews.source),
            external_review_id = coalesce(excluded.external_review_id, reviews.external_review_id),
            rating = coalesce(excluded.rating, reviews.rating),
            text = coalesce(excluded.text, reviews.text),
            review_date = coalesce(excluded.review_date, reviews.review_date),
            search_tsv = excluded.search_tsv
        returning id::text
        """,
        review["id"],
        review["restaurant_id"],
        review.get("source"),
        review.get("external_review_id"),
        review.get("rating"),
        review.get("text"),
        review.get("review_date"),
    )
    return row["id"]


async def restaurants_for_menu_scrape(
    conn: Any,
    limit: int = 25,
    refresh: bool = False,
    cuisine_tags: list[str] | None = None,
) -> list[Any]:
    tags = cuisine_tags or []
    if refresh:
        return await conn.fetch(
            """
            select id::text, name, website_url, cuisine_tags, meal_tags
            from restaurants
            where website_url is not null and website_url <> ''
              and ($2::text[] = '{}'::text[] or cuisine_tags && $2::text[])
            order by review_count desc nulls last, rating desc nulls last
            limit $1
            """,
            limit,
            tags,
        )

    return await conn.fetch(
        """
        select r.id::text, r.name, r.website_url, r.cuisine_tags, r.meal_tags
        from restaurants r
        left join menu_items mi on mi.restaurant_id = r.id
        where r.website_url is not null and r.website_url <> ''
          and ($2::text[] = '{}'::text[] or r.cuisine_tags && $2::text[])
        group by r.id, r.name, r.website_url, r.cuisine_tags, r.meal_tags,
                 r.review_count, r.rating
        having count(mi.id) = 0
        order by r.review_count desc nulls last, r.rating desc nulls last
        limit $1
        """,
        limit,
        tags,
    )


async def ingestion_counts(conn: Any) -> dict[str, int]:
    row = await conn.fetchrow(
        """
        select
          (select count(*) from restaurants) as restaurants,
          (select count(*) from menu_items) as menu_items,
          (select count(*) from price_observations) as price_observations,
          (select count(*) from reviews) as reviews,
          (select count(*) from menu_items where embedding is not null) as embedded_menu_items,
          (select count(*) from menu_sources) as menu_sources,
          (select count(*) from menu_scrape_attempts) as menu_scrape_attempts,
          (select count(*) from menu_curation_queue where status = 'open') as open_curation_items,
          (select count(*) from menu_feedback where status = 'open') as open_feedback_items
        """
    )
    return dict(row)
