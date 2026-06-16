"""Menu search and ingestion tools."""

from domains.restaurants.db import connect
from domains.restaurants.ingestion.menu_scraper import scrape_menu_url
from domains.restaurants.tools.query_utils import (
    extract_cuisine,
    haversine_sql,
    money,
    primary_cuisine_filter,
    resolve_location,
    rows_to_json,
    table,
    vector_for_query,
)


def _strict_item_rows(query: str, rows: list) -> list:
    tokens = [token for token in query.lower().replace("-", " ").split() if len(token) > 1]
    if not tokens:
        return []
    strict = []
    for row in rows:
        data = dict(row)
        haystack = " ".join(
            str(data.get(field) or "").lower()
            for field in ["name", "category"]
        )
        if all(token in haystack for token in tokens):
            strict.append(row)
    return strict


async def get_restaurant_menu(
    restaurant_name: str,
    location: str | None = None,
    limit: int = 30,
) -> dict:
    """Return ingested menu items for one restaurant matched by name."""
    name_query = (restaurant_name or "").strip()
    if not name_query:
        return {"status": "error", "message": "restaurant_name is required"}

    lat, lng = resolve_location(location)
    distance_sql = haversine_sql("$1", "$2")
    conn = await connect()
    try:
        restaurant = await conn.fetchrow(
            f"""
            select r.id::text, r.name, r.address, r.city, r.rating, r.review_count,
                   r.cuisine_tags, r.website_url, {distance_sql} as distance_miles,
                   similarity(lower(r.name), lower($3)) as name_similarity
            from restaurants r
            where r.latitude is not null and r.longitude is not null
              and (
                lower(r.name) like ('%' || lower($3) || '%')
                or lower($3) like ('%' || lower(r.name) || '%')
                or r.normalized_name % lower($3)
              )
            order by name_similarity desc, distance_miles asc, r.review_count desc nulls last
            limit 1
            """,
            lat, lng, name_query,
        )
        if not restaurant:
            return {
                "status": "ok",
                "query": name_query,
                "count": 0,
                "formatted": f"No restaurant matched {name_query}.",
            }
        rows = await conn.fetch(
            """
            select mi.id::text, mi.name, mi.description, mi.category, mi.price,
                   mi.currency, mi.source_url, mi.source_type,
                   mi.extraction_confidence, mi.last_seen_at
            from menu_items mi
            where mi.restaurant_id = $1::uuid
              and (mi.price is null or mi.price >= 5)
            order by mi.category asc nulls last, mi.price asc nulls last, mi.name asc
            limit $2
            """,
            restaurant["id"], limit,
        )
    finally:
        await conn.close()

    deduped_rows = []
    seen = set()
    for row in rows:
        key = (
            str(row["name"] or "").lower(),
            str(row["category"] or "").lower(),
            float(row["price"]) if row["price"] is not None else None,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped_rows.append(row)
    rows = deduped_rows

    formatted_rows = [
        [
            row["category"] or "-",
            row["name"],
            money(row["price"]),
            row["source_type"] or "-",
        ]
        for row in rows
    ]
    formatted = (
        f"Matched restaurant: {restaurant['name']} "
        f"({float(restaurant['distance_miles']):.1f} mi, rating {restaurant['rating'] or '-'})\n\n"
        + (
            table(["Category", "Item", "Price", "Source"], formatted_rows)
            if formatted_rows
            else "No ingested menu items found for this restaurant."
        )
    )
    return {
        "status": "ok",
        "query": name_query,
        "restaurant": rows_to_json([restaurant])[0],
        "count": len(rows),
        "items": rows_to_json(rows),
        "formatted": formatted,
    }


async def hybrid_search_menu_items(
    query: str,
    location: str | None = None,
    radius_miles: float = 5,
    cuisine: str | None = None,
    max_price: float | None = None,
    limit: int = 10,
) -> dict:
    """Search menu items with pgvector semantic match plus keyword match."""
    inferred_cuisine = cuisine or extract_cuisine(query)
    is_broad_cuisine_query = bool(
        inferred_cuisine
        and any(word in query.lower() for word in ["menu", "menus", "items", "different", "options", "dishes"])
    )
    if is_broad_cuisine_query and radius_miles <= 5:
        radius_miles = 60

    coords = resolve_location(location)
    lat, lng = coords
    cuisine_tags = primary_cuisine_filter(inferred_cuisine)
    fallback_cuisine_tags = primary_cuisine_filter(inferred_cuisine) if inferred_cuisine else cuisine_tags
    vector = await vector_for_query(query)
    distance_sql = haversine_sql("$1", "$2")

    conn = await connect()
    restaurant_fallback = []
    try:
        if is_broad_cuisine_query:
            rows = await conn.fetch(
                f"""
                select mi.id::text, mi.name, mi.description, mi.price, mi.currency,
                       mi.source_url, mi.source_type, mi.extraction_confidence,
                       mi.last_seen_at, r.id::text as restaurant_id, r.name as restaurant_name,
                       r.rating, r.review_count, r.cuisine_tags,
                       {distance_sql} as distance_miles,
                       0::float as keyword_score
                from menu_items mi
                join restaurants r on r.id = mi.restaurant_id
                where r.latitude is not null and r.longitude is not null
                  and ({distance_sql}) <= $3
                  and ($4::text[] = '{{}}'::text[] or r.cuisine_tags && $4::text[])
                  and ($5::numeric is null or mi.price <= $5)
                  and (mi.price is null or mi.price >= 5)
                order by r.rating desc nulls last,
                         r.review_count desc nulls last,
                         mi.category asc nulls last,
                         mi.name asc
                limit $6
                """,
                lat, lng, radius_miles, cuisine_tags, max_price, limit,
            )
        elif vector:
            rows = await conn.fetch(
                f"""
                select mi.id::text, mi.name, mi.description, mi.price, mi.currency,
                       mi.source_url, mi.source_type, mi.extraction_confidence,
                       mi.last_seen_at, r.id::text as restaurant_id, r.name as restaurant_name,
                       r.rating, r.review_count, r.cuisine_tags,
                       {distance_sql} as distance_miles,
                       ts_rank(mi.search_tsv, plainto_tsquery('english', $3)) as keyword_score,
                       1 - (mi.embedding <=> $7::vector) as semantic_score
                from menu_items mi
                join restaurants r on r.id = mi.restaurant_id
                where r.latitude is not null and r.longitude is not null
                  and ({distance_sql}) <= $4
                  and ($5::text[] = '{{}}'::text[] or r.cuisine_tags && $5::text[] or mi.cuisine_tags && $5::text[])
                  and ($6::numeric is null or mi.price <= $6)
                  and (mi.price is null or mi.price >= 5)
                order by (
                    coalesce(ts_rank(mi.search_tsv, plainto_tsquery('english', $3)), 0) * 0.35 +
                    coalesce(1 - (mi.embedding <=> $7::vector), 0) * 0.65
                ) desc,
                r.rating desc nulls last
                limit $8
                """,
                lat, lng, query, radius_miles, cuisine_tags, max_price, vector, limit,
            )
        else:
            rows = await conn.fetch(
                f"""
                select mi.id::text, mi.name, mi.description, mi.price, mi.currency,
                       mi.source_url, mi.source_type, mi.extraction_confidence,
                       mi.last_seen_at, r.id::text as restaurant_id, r.name as restaurant_name,
                       r.rating, r.review_count, r.cuisine_tags,
                       {distance_sql} as distance_miles,
                       ts_rank(mi.search_tsv, plainto_tsquery('english', $3)) as keyword_score
                from menu_items mi
                join restaurants r on r.id = mi.restaurant_id
                where r.latitude is not null and r.longitude is not null
                  and ({distance_sql}) <= $4
                  and ($5::text[] = '{{}}'::text[] or r.cuisine_tags && $5::text[] or mi.cuisine_tags && $5::text[])
                  and ($6::numeric is null or mi.price <= $6)
                  and (mi.price is null or mi.price >= 5)
                  and (mi.search_tsv @@ plainto_tsquery('english', $3)
                       or mi.normalized_name % lower($3))
                order by keyword_score desc, r.rating desc nulls last
                limit $7
                """,
                lat, lng, query, radius_miles, cuisine_tags, max_price, limit,
            )

        if not rows and cuisine_tags and is_broad_cuisine_query:
            rows = await conn.fetch(
                f"""
                select mi.id::text, mi.name, mi.description, mi.price, mi.currency,
                       mi.source_url, mi.source_type, mi.extraction_confidence,
                       mi.last_seen_at, r.id::text as restaurant_id, r.name as restaurant_name,
                       r.rating, r.review_count, r.cuisine_tags,
                       {distance_sql} as distance_miles,
                       0::float as keyword_score
                from menu_items mi
                join restaurants r on r.id = mi.restaurant_id
                where r.latitude is not null and r.longitude is not null
                  and ({distance_sql}) <= $3
                  and (
                      (case when $7::boolean then r.cuisine_tags && $4::text[]
                            else r.cuisine_tags && $4::text[] or mi.cuisine_tags && $4::text[]
                       end)
                  )
                  and ($5::numeric is null or mi.price <= $5)
                  and (mi.price is null or mi.price >= 5)
                order by r.review_count desc nulls last,
                         r.rating desc nulls last,
                         mi.price asc nulls last
                limit $6
                """,
                lat, lng, max(radius_miles, 60), cuisine_tags, max_price, limit, is_broad_cuisine_query,
            )
        if not rows and fallback_cuisine_tags:
            restaurant_fallback = await conn.fetch(
                f"""
                select r.id::text, r.name, r.address, r.city, r.rating, r.review_count,
                       r.price_level, r.website_url, r.cuisine_tags,
                       {distance_sql} as distance_miles,
                       count(mi.id)::int as menu_items_ingested
                from restaurants r
                left join menu_items mi on mi.restaurant_id = r.id
                where r.latitude is not null and r.longitude is not null
                  and ({distance_sql}) <= $3
                  and r.cuisine_tags && $4::text[]
                group by r.id, r.name, r.address, r.city, r.rating, r.review_count,
                         r.price_level, r.website_url, r.cuisine_tags, r.latitude, r.longitude
                order by r.rating desc nulls last,
                         r.review_count desc nulls last,
                         distance_miles asc
                limit $5
                """,
                lat, lng, max(radius_miles, 60), fallback_cuisine_tags, limit,
            )
    finally:
        await conn.close()

    if rows and not is_broad_cuisine_query:
        strict_rows = _strict_item_rows(query, rows)
        if strict_rows:
            rows = strict_rows

    formatted_rows = [
        [
            row["restaurant_name"],
            row["name"],
            money(row["price"]),
            f"{float(row['distance_miles']):.1f} mi",
            row["rating"] or "-",
            row["source_type"] or "-",
        ]
        for row in rows
    ]
    fallback_rows = [
        [
            row["name"],
            row["city"] or "-",
            f"{float(row['distance_miles']):.1f} mi",
            row["rating"] or "-",
            row["review_count"] or 0,
            row["menu_items_ingested"],
        ]
        for row in restaurant_fallback
    ]
    formatted = (
        table(["Restaurant", "Item", "Price", "Distance", "Rating", "Source"], formatted_rows)
        if formatted_rows
        else table(["Restaurant", "City", "Distance", "Rating", "Reviews", "Menu items"], fallback_rows)
        if fallback_rows
        else "No matching menu items found."
    )

    return {
        "status": "ok",
        "query": query,
        "inferred_cuisine": inferred_cuisine,
        "radius_miles": radius_miles,
        "count": len(rows),
        "items": rows_to_json(rows),
        "restaurant_fallback_count": len(restaurant_fallback),
        "restaurant_fallback": rows_to_json(restaurant_fallback),
        "message": (
            f"No ingested {inferred_cuisine} menu items were found; showing matching restaurants instead."
            if restaurant_fallback and not rows
            else None
        ),
        "formatted": formatted,
    }


async def check_menu_freshness(restaurant_id: str) -> dict:
    """Check whether a restaurant menu is fresh, acceptable, stale, or unknown."""
    conn = await connect()
    try:
        row = await conn.fetchrow(
            """
            select max(last_seen_at) as last_seen_at, count(*) as menu_items
            from menu_items
            where restaurant_id = $1
            """,
            restaurant_id,
        )
    finally:
        await conn.close()
    last_seen = row["last_seen_at"] if row else None
    if not last_seen:
        tier = "unknown"
    else:
        from datetime import datetime, timezone

        age_days = (datetime.now(timezone.utc) - last_seen).days
        tier = "fresh" if age_days <= 7 else "acceptable" if age_days <= 30 else "stale"
    return {
        "status": "ok",
        "restaurant_id": restaurant_id,
        "freshness": tier,
        "last_seen_at": str(last_seen) if last_seen else None,
        "menu_items": row["menu_items"] if row else 0,
    }


async def scrape_restaurant_menu(restaurant_id: str, source_url: str | None = None) -> dict:
    """Scrape and parse a restaurant menu when allowed and necessary."""
    if not source_url:
        return {"status": "error", "message": "source_url is required", "restaurant_id": restaurant_id}
    result = await scrape_menu_url(restaurant_id=restaurant_id, source_url=source_url)
    return {"status": "ok", **result}
