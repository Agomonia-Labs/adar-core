"""Restaurant discovery and ranking tools."""

import json

from domains.restaurants.tools.query_utils import (
    cuisine_filter,
    extract_budget,
    extract_cuisine,
    extract_location,
    extract_meal,
    extract_quantity,
    haversine_sql,
    json_safe,
    money,
    primary_cuisine_filter,
    resolve_location,
    rows_to_json,
    table,
)
from domains.restaurants.db import connect


async def parse_food_request(query: str) -> dict:
    """Extract structured constraints from a restaurant recommendation query."""
    cuisine = extract_cuisine(query)
    meal = extract_meal(query)
    budget = extract_budget(query)
    quantity = extract_quantity(query)
    return {
        "status": "ok",
        "query": query,
        "location": extract_location(query),
        "cuisine": cuisine,
        "meal": meal,
        "budget": budget,
        "quantity": quantity,
    }


async def find_restaurants(
    location: str,
    radius_miles: float = 5,
    cuisine: str | None = None,
    meal: str | None = None,
    limit: int = 10,
) -> dict:
    """Find restaurants by geo radius and category filters."""
    coords = resolve_location(location)
    if not coords:
        return {"status": "error", "message": "Unknown location."}
    lat, lng = coords
    cuisine_tags = cuisine_filter(cuisine)
    meal_tags = [meal] if meal else []
    distance_sql = haversine_sql("$1", "$2")

    conn = await connect()
    try:
        rows = await conn.fetch(
            f"""
            select id::text, name, cuisine_tags, meal_tags, rating, review_count,
                   website_url, {distance_sql} as distance_miles
            from restaurants r
            where r.latitude is not null and r.longitude is not null
              and ({distance_sql}) <= $3
              and ($4::text[] = '{{}}'::text[] or r.cuisine_tags && $4::text[])
              and ($5::text[] = '{{}}'::text[] or r.meal_tags && $5::text[])
            order by rating desc nulls last, review_count desc nulls last
            limit $6
            """,
            lat,
            lng,
            radius_miles,
            cuisine_tags,
            meal_tags,
            limit,
        )
    finally:
        await conn.close()

    result_rows = [
        [
            row["name"],
            ", ".join(row["cuisine_tags"] or []),
            f"{float(row['distance_miles']):.1f} mi",
            row["rating"] or "-",
            row["review_count"] or 0,
        ]
        for row in rows
    ]
    return {
        "status": "ok",
        "count": len(rows),
        "restaurants": rows_to_json(rows),
        "formatted": table(["Restaurant", "Cuisine", "Distance", "Rating", "Reviews"], result_rows)
        if result_rows else "No matching restaurants found.",
    }


async def count_restaurants(
    cuisine: str | None = None,
    location: str | None = None,
    radius_miles: float | None = None,
) -> dict:
    """Count restaurants in the system, optionally filtered by cuisine and location."""
    cuisine_tags = primary_cuisine_filter(cuisine)
    use_location = bool(location and radius_miles)
    coords = resolve_location(location) if use_location else None
    distance_sql = haversine_sql("$1", "$2")

    conn = await connect()
    try:
        if use_location and coords:
            lat, lng = coords
            row = await conn.fetchrow(
                f"""
                select count(*)::int as restaurant_count,
                       count(*) filter (
                         where exists (
                           select 1 from menu_items mi where mi.restaurant_id = r.id
                         )
                       )::int as restaurants_with_menus
                from restaurants r
                where r.latitude is not null and r.longitude is not null
                  and ({distance_sql}) <= $3
                  and ($4::text[] = '{{}}'::text[] or r.cuisine_tags && $4::text[])
                """,
                lat, lng, radius_miles, cuisine_tags,
            )
        else:
            row = await conn.fetchrow(
                """
                select count(*)::int as restaurant_count,
                       count(*) filter (
                         where exists (
                           select 1 from menu_items mi where mi.restaurant_id = restaurants.id
                         )
                       )::int as restaurants_with_menus
                from restaurants
                where ($1::text[] = '{}'::text[] or cuisine_tags && $1::text[])
                """,
                cuisine_tags,
            )
    finally:
        await conn.close()

    count = row["restaurant_count"] if row else 0
    with_menus = row["restaurants_with_menus"] if row else 0
    label = f"{cuisine} restaurants" if cuisine else "restaurants"
    location_note = f" within {radius_miles:g} miles of {location}" if use_location else ""
    return {
        "status": "ok",
        "cuisine": cuisine,
        "location": location if use_location else None,
        "radius_miles": radius_miles if use_location else None,
        "count": count,
        "restaurants_with_menus": with_menus,
        "formatted": (
            f"There are {count} {label} in the system{location_note}. "
            f"{with_menus} of them currently have ingested menu items."
        ),
    }


async def get_restaurant_details(
    restaurant_name: str,
    location: str | None = None,
) -> dict:
    """Return address/contact/profile details for one restaurant matched by name."""
    name_query = (restaurant_name or "").strip()
    if not name_query:
        return {"status": "error", "message": "restaurant_name is required"}

    lat, lng = resolve_location(location)
    distance_sql = haversine_sql("$1", "$2")
    conn = await connect()
    try:
        row = await conn.fetchrow(
            f"""
            select r.id::text, r.name, r.address, r.city, r.region, r.postal_code,
                   r.country, r.phone, r.website_url, r.rating, r.review_count,
                   r.price_level, r.cuisine_tags, r.meal_tags,
                   {distance_sql} as distance_miles,
                   count(mi.id)::int as menu_items_ingested,
                   max(mi.last_seen_at) as latest_menu_seen_at,
                   similarity(lower(r.name), lower($3)) as name_similarity
            from restaurants r
            left join menu_items mi on mi.restaurant_id = r.id
            where r.latitude is not null and r.longitude is not null
              and (
                lower(r.name) like ('%' || lower($3) || '%')
                or lower($3) like ('%' || lower(r.name) || '%')
                or r.normalized_name % lower($3)
              )
            group by r.id, r.name, r.address, r.city, r.region, r.postal_code,
                     r.country, r.phone, r.website_url, r.rating, r.review_count,
                     r.price_level, r.cuisine_tags, r.meal_tags, r.latitude, r.longitude
            order by name_similarity desc, distance_miles asc, r.review_count desc nulls last
            limit 1
            """,
            lat, lng, name_query,
        )
    finally:
        await conn.close()

    if not row:
        return {
            "status": "ok",
            "query": name_query,
            "count": 0,
            "formatted": f"No restaurant matched {name_query}.",
        }

    details = rows_to_json([row])[0]
    address_parts = [
        row["address"],
        row["city"],
        row["region"],
        row["postal_code"],
    ]
    address = ", ".join(str(part) for part in address_parts if part)
    fields = [
        ["Name", row["name"]],
        ["Address", address or "-"],
        ["Phone", row["phone"] or "-"],
        ["Website", row["website_url"] or "-"],
        ["Cuisine", ", ".join(row["cuisine_tags"] or []) or "-"],
        ["Rating", row["rating"] or "-"],
        ["Reviews", row["review_count"] or 0],
        ["Distance", f"{float(row['distance_miles']):.1f} mi" if row["distance_miles"] is not None else "-"],
        ["Menu items", row["menu_items_ingested"] or 0],
        ["Latest menu seen", row["latest_menu_seen_at"] or "-"],
    ]
    return {
        "status": "ok",
        "query": name_query,
        "count": 1,
        "restaurant": details,
        "formatted": table(["Field", "Value"], fields),
    }


async def list_restaurants(
    cuisine: str | None = None,
    location: str | None = None,
    radius_miles: float | None = None,
    menu_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List restaurants in the system, optionally filtered by cuisine and location."""
    cuisine_tags = primary_cuisine_filter(cuisine)
    use_location = bool(location and radius_miles)
    coords = resolve_location(location) if use_location else None
    limit = min(max(1, int(limit or 100)), 200)
    offset = max(0, int(offset or 0))
    normalized_menu_status = (menu_status or "all").lower()
    if normalized_menu_status not in {"all", "with", "without"}:
        normalized_menu_status = "all"
    distance_sql = haversine_sql("$1", "$2")
    menu_filter_sql_rows = """
        and (
          $7::text = 'all'
          or ($7::text = 'with' and exists (select 1 from menu_items m where m.restaurant_id = r.id))
          or ($7::text = 'without' and not exists (select 1 from menu_items m where m.restaurant_id = r.id))
        )
    """
    menu_filter_sql_total = """
        and (
          $5::text = 'all'
          or ($5::text = 'with' and exists (select 1 from menu_items m where m.restaurant_id = r.id))
          or ($5::text = 'without' and not exists (select 1 from menu_items m where m.restaurant_id = r.id))
        )
    """

    conn = await connect()
    try:
        if use_location and coords:
            lat, lng = coords
            total_row = await conn.fetchrow(
                f"""
                select count(*)::int as total_count
                from restaurants r
                where r.latitude is not null and r.longitude is not null
                  and ({distance_sql}) <= $3
                  and ($4::text[] = '{{}}'::text[] or r.cuisine_tags && $4::text[])
                  {menu_filter_sql_total}
                """,
                lat, lng, radius_miles, cuisine_tags, normalized_menu_status,
            )
            rows = await conn.fetch(
                f"""
                select r.id::text, r.name, r.city, r.address, r.rating, r.review_count,
                       r.cuisine_tags, r.website_url,
                       count(mi.id)::int as menu_items_ingested,
                       {distance_sql} as distance_miles
                from restaurants r
                left join menu_items mi on mi.restaurant_id = r.id
                where r.latitude is not null and r.longitude is not null
                  and ({distance_sql}) <= $3
                  and ($4::text[] = '{{}}'::text[] or r.cuisine_tags && $4::text[])
                  {menu_filter_sql_rows}
                group by r.id, r.name, r.city, r.address, r.rating, r.review_count,
                         r.cuisine_tags, r.website_url, r.latitude, r.longitude
                order by r.rating desc nulls last, r.review_count desc nulls last, r.name asc
                limit $5 offset $6
                """,
                lat, lng, radius_miles, cuisine_tags, limit, offset,
            )
        else:
            total_row = await conn.fetchrow(
                """
                select count(*)::int as total_count
                from restaurants r
                where ($1::text[] = '{}'::text[] or r.cuisine_tags && $1::text[])
                  and (
                    $2::text = 'all'
                    or ($2::text = 'with' and exists (select 1 from menu_items m where m.restaurant_id = r.id))
                    or ($2::text = 'without' and not exists (select 1 from menu_items m where m.restaurant_id = r.id))
                  )
                """,
                cuisine_tags, normalized_menu_status,
            )
            rows = await conn.fetch(
                """
                select r.id::text, r.name, r.city, r.address, r.rating, r.review_count,
                       r.cuisine_tags, r.website_url,
                       count(mi.id)::int as menu_items_ingested,
                       null::float as distance_miles
                from restaurants r
                left join menu_items mi on mi.restaurant_id = r.id
                where ($1::text[] = '{}'::text[] or r.cuisine_tags && $1::text[])
                  and (
                    $4::text = 'all'
                    or ($4::text = 'with' and exists (select 1 from menu_items m where m.restaurant_id = r.id))
                    or ($4::text = 'without' and not exists (select 1 from menu_items m where m.restaurant_id = r.id))
                  )
                group by r.id, r.name, r.city, r.address, r.rating, r.review_count,
                         r.cuisine_tags, r.website_url
                order by r.rating desc nulls last, r.review_count desc nulls last, r.name asc
                limit $2 offset $3
                """,
                cuisine_tags, limit, offset, normalized_menu_status,
            )
    finally:
        await conn.close()

    total_count = total_row["total_count"] if total_row else 0
    result_rows = [
        [
            row["name"],
            row.get("city") or "-",
            ", ".join(row["cuisine_tags"] or []),
            f"{float(row['distance_miles']):.1f} mi" if row["distance_miles"] is not None else "-",
            row["rating"] or "-",
            row["review_count"] or 0,
            row["menu_items_ingested"] or 0,
        ]
        for row in rows
    ]
    label = f"{cuisine} restaurants" if cuisine else "restaurants"
    if normalized_menu_status == "with":
        label = f"{label} with menus"
    elif normalized_menu_status == "without":
        label = f"{label} without menus"
    location_note = f" within {radius_miles:g} miles of {location}" if use_location else ""
    shown_end = min(offset + len(rows), total_count)
    formatted = (
        f"Showing {offset + 1 if rows else 0}-{shown_end} of {total_count} {label}{location_note}.\n\n"
        + table(["Restaurant", "City", "Cuisine", "Distance", "Rating", "Reviews", "Menu items"], result_rows)
        if result_rows
        else f"No {label} found{location_note}."
    )
    return {
        "status": "ok",
        "cuisine": cuisine,
        "location": location if use_location else None,
        "radius_miles": radius_miles if use_location else None,
        "menu_status": normalized_menu_status,
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "count": len(rows),
        "restaurants": rows_to_json(rows),
        "formatted": formatted,
    }


async def restaurant_genre_summary() -> dict:
    """Summarize restaurant counts by cuisine/genre tag."""
    conn = await connect()
    try:
        rows = await conn.fetch(
            """
            select tag as cuisine, count(*)::int as restaurant_count
            from restaurants r
            cross join unnest(r.cuisine_tags) as tag
            group by tag
            order by restaurant_count desc, tag asc
            """
        )
    finally:
        await conn.close()
    formatted_rows = [[row["cuisine"], row["restaurant_count"]] for row in rows]
    return {
        "status": "ok",
        "count": len(rows),
        "genres": rows_to_json(rows),
        "formatted": table(["Genre", "Restaurants"], formatted_rows) if formatted_rows else "No genre data found.",
    }


async def rank_recommendations(candidates_json: str = "[]", user_constraints_json: str = "{}") -> dict:
    """Rank recommendation candidates using deterministic scoring.

    Args:
        candidates_json: JSON array of candidate restaurant/menu result objects.
        user_constraints_json: JSON object with user constraints such as budget, quantity, and location.
    """
    try:
        candidates = json.loads(candidates_json or "[]")
    except json.JSONDecodeError:
        candidates = []
    try:
        constraints = json.loads(user_constraints_json or "{}")
    except json.JSONDecodeError:
        constraints = {}
    if not isinstance(candidates, list):
        candidates = []
    if not isinstance(constraints, dict):
        constraints = {}
    ranked = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        rating = float(candidate.get("rating") or 0)
        review_count = min(float(candidate.get("review_count") or 0), 1000) / 1000
        price = float(candidate.get("price") or 0)
        distance = float(candidate.get("distance_miles") or 0)
        score = (
            rating / 5 * 0.35 +
            review_count * 0.20 +
            (1 / (1 + price)) * 0.25 +
            (1 / (1 + distance)) * 0.20
        )
        ranked.append({**candidate, "recommendation_score": round(score, 3)})
    ranked.sort(key=lambda item: item["recommendation_score"], reverse=True)
    return {
        "status": "ok",
        "candidate_count": len(ranked),
        "user_constraints": constraints,
        "recommendations": json_safe(ranked[:10]),
    }
