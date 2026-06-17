"""Menu pricing comparison tools."""

import re

from domains.restaurants.db import connect
from domains.restaurants.tools.menu_tools import hybrid_search_menu_items
from domains.restaurants.tools.query_utils import (
    extract_cuisine,
    haversine_sql,
    money,
    primary_cuisine_filter,
    resolve_location,
    rows_to_json,
    table,
)


SPELLING_NORMALIZATIONS = {
    "biriyani": "biryani",
    "biriani": "biryani",
    "noddles": "noodles",
    "nodles": "noodles",
}

STRICT_PHRASE_QUERIES = {
    "fried rice",
    "pad thai",
}

SOURCE_TRUST = {
    "curated": 6,
    "json_ld": 5,
    "platform_toast": 5,
    "platform": 4,
    "html": 2,
    "llm_text": 2,
    "browser_screenshot_ocr": 1,
    "image_ocr": 1,
    "pdf": 1,
}


def _normalize_item_query(query: str) -> str:
    normalized = (query or "").lower().replace("-", " ")
    normalized = re.sub(r"[^a-z0-9 ]+", " ", normalized)
    for source, target in SPELLING_NORMALIZATIONS.items():
        normalized = re.sub(rf"\b{re.escape(source)}\b", target, normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _item_query_variants(query: str) -> list[str]:
    canonical = _normalize_item_query(query)
    if not canonical:
        return []
    if canonical in {"pad thai noodles", "pad thai noodle"}:
        canonical = "pad thai"
    variants = [canonical]
    if canonical == "pad noodles":
        variants.append("pad thai")
    if canonical == "pad thai":
        variants.extend(["pad thai noodles", "pad thai noodle"])
    if canonical == "tom yum soup":
        variants.append("tom yum")
    elif canonical == "tom yum":
        variants.append("tom yum soup")
    if canonical == "chicken tikka masala":
        variants.extend(["tikka masala chicken", "tikka masala"])
    elif canonical == "tikka masala chicken":
        variants.extend(["chicken tikka masala", "tikka masala"])
    elif canonical == "tikka masala":
        variants.extend(["chicken tikka masala", "tikka masala chicken"])
    if "biryani" in canonical:
        if re.search(r"\bgoat\b", canonical):
            variants.extend([
                re.sub(r"\bgoat\b", "mutton", canonical),
                re.sub(r"\bgoat\b", "lamb", canonical),
            ])
        elif re.search(r"\bmutton\b", canonical):
            variants.extend([
                re.sub(r"\bmutton\b", "goat", canonical),
                re.sub(r"\bmutton\b", "lamb", canonical),
            ])
        elif re.search(r"\blamb\b", canonical):
            variants.extend([
                re.sub(r"\blamb\b", "goat", canonical),
                re.sub(r"\blamb\b", "mutton", canonical),
            ])
    deduped = []
    seen = set()
    for variant in variants:
        if variant and variant not in seen:
            deduped.append(variant)
            seen.add(variant)
    return deduped


def _requires_strict_phrase(query: str) -> bool:
    canonical = _normalize_item_query(query)
    return canonical in STRICT_PHRASE_QUERIES


def _source_trust(item: dict) -> int:
    source_type = str(item.get("source_type") or "").lower()
    if source_type.startswith("platform_"):
        return SOURCE_TRUST.get(source_type, SOURCE_TRUST["platform"])
    return SOURCE_TRUST.get(source_type, 0)


def _confidence(item: dict) -> float:
    try:
        return float(item.get("extraction_confidence") or 0)
    except (TypeError, ValueError):
        return 0


def _same_dish_key(item_query: str, item: dict) -> tuple:
    canonical = _normalize_item_query(item_query)
    name = _normalize_item_query(str(item.get("name") or ""))
    restaurant_key = item.get("restaurant_id") or item.get("restaurant_name")
    if canonical in {"pad thai", "pad thai noodles", "pad thai noodle"} and "pad thai" in name:
        return restaurant_key, "pad thai"
    if canonical in {"fried rice"} and "fried rice" in name:
        return restaurant_key, "fried rice"
    if canonical in {"tom yum", "tom yum soup"} and "tom yum" in name:
        return restaurant_key, "tom yum"
    if canonical in {"chicken tikka masala", "tikka masala chicken", "tikka masala"} and "tikka masala" in name:
        return restaurant_key, "chicken tikka masala"
    return restaurant_key, name


def _preferred_duplicate(existing: dict, candidate: dict) -> dict:
    existing_rank = (_source_trust(existing), _confidence(existing), str(existing.get("last_seen_at") or ""))
    candidate_rank = (_source_trust(candidate), _confidence(candidate), str(candidate.get("last_seen_at") or ""))
    return candidate if candidate_rank > existing_rank else existing


async def _direct_priced_item_search_variants(
    item_query: str,
    cuisine: str | None,
    location: str | None,
    radius_miles: float,
    limit: int = 12,
) -> list[dict]:
    matches = []
    seen_ids = set()
    variants = _item_query_variants(item_query)
    fetch_limit = max(limit, 250)
    for variant in variants:
        for item in await _direct_priced_item_search(
            item_query=variant,
            cuisine=cuisine,
            location=location,
            radius_miles=radius_miles,
            limit=fetch_limit,
        ):
            item_id = item.get("id")
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            matches.append(item)
    return matches


def _item_name_matches(query: str, item: dict) -> bool:
    variants = _item_query_variants(query)
    token_sets = [
        [token for token in variant.split() if len(token) > 1]
        for variant in variants
    ]
    if not token_sets:
        return True
    haystack = " ".join(
        str(item.get(field) or "").lower()
        for field in ["name", "description", "category"]
    )
    if _requires_strict_phrase(query):
        return any(variant in haystack for variant in variants)
    return any(all(token in haystack for token in tokens) for tokens in token_sets)


def _is_irrelevant_price_match(query: str, item: dict) -> bool:
    query_l = _normalize_item_query(query)
    source_url = str(item.get("source_url") or "").lower()
    source_type = str(item.get("source_type") or "").lower()
    haystack = " ".join(
        str(item.get(field) or "").lower()
        for field in ["name", "description", "category"]
    )
    name_text = " ".join(
        str(item.get(field) or "").lower()
        for field in ["name", "description", "category"]
    )
    name_category_text = " ".join(
        str(item.get(field) or "").lower()
        for field in ["name", "category"]
    )
    if (
        "clover.com/online-ordering" in source_url
        and source_type == "html"
        and _confidence(item) < 0.85
    ):
        return True
    if "soup" in query_l and any(
        token in haystack
        for token in ["tequila", "vodka", "rum", "gin", "whiskey", "cocktail", "margarita", "agave"]
    ):
        return True
    if query_l == "fried rice":
        if re.search(r"\b(side|sides|kid|kids|add|extra|sub|substitute|substitution)\b", name_text):
            return True
        try:
            if float(item.get("price") or 0) < 8:
                return True
        except (TypeError, ValueError):
            return True
    if query_l in {"pad thai", "pad thai noodles", "pad thai noodle"}:
        if re.search(r"\b(side|sides|kid|kids|add|extra|sub|substitute|substitution)\b", name_text):
            return True
        try:
            if float(item.get("price") or 0) < 8:
                return True
        except (TypeError, ValueError):
            return True
    if query_l in {"chicken tikka masala", "tikka masala chicken", "tikka masala"}:
        if "tikka masala" not in _normalize_item_query(name_category_text):
            return True
        if re.search(r"\b(sauce|side|sides|add|extra|party|catering)\b", name_category_text):
            return True
        if query_l in {"chicken tikka masala", "tikka masala chicken"}:
            other_protein = re.search(r"\b(beef|lamb|goat|mutton|prawns?|shrimps?|seafood|fish|salmon|paneer|tofu|vegetables?|veggie)\b", name_category_text)
            if other_protein and "chicken" not in name_category_text:
                return True
        try:
            price = float(item.get("price") or 0)
        except (TypeError, ValueError):
            return True
        if price < 8 or price > 60:
            return True
    return False


async def _restaurant_fallback(
    cuisine: str | None,
    location: str | None,
    radius_miles: float,
    limit: int = 12,
) -> list[dict]:
    cuisine_tags = primary_cuisine_filter(cuisine)
    if not cuisine_tags:
        return []
    lat, lng = resolve_location(location)
    distance_sql = haversine_sql("$1", "$2")
    conn = await connect()
    try:
        rows = await conn.fetch(
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
            lat, lng, max(radius_miles, 60), cuisine_tags, limit,
        )
        return rows_to_json(rows)
    finally:
        await conn.close()


async def _direct_priced_item_search(
    item_query: str,
    cuisine: str | None,
    location: str | None,
    radius_miles: float,
    limit: int = 12,
) -> list[dict]:
    tokens = [token for token in item_query.lower().replace("-", " ").split() if len(token) > 1]
    if not tokens:
        return []
    exact_phrase = _normalize_item_query(item_query) if _requires_strict_phrase(item_query) else None
    cuisine_tags = primary_cuisine_filter(cuisine)
    lat, lng = resolve_location(location)
    distance_sql = haversine_sql("$1", "$2")
    item_text = """
        lower(
            coalesce(mi.name, '') || ' ' ||
            coalesce(mi.description, '') || ' ' ||
            coalesce(mi.category, '')
        )
    """
    conn = await connect()
    try:
        rows = await conn.fetch(
            f"""
            select mi.id::text, mi.name, mi.description, mi.price, mi.currency,
                   mi.source_url, mi.source_type, mi.extraction_confidence,
                   mi.last_seen_at, r.id::text as restaurant_id, r.name as restaurant_name,
                   r.rating, r.review_count, r.cuisine_tags,
                   {distance_sql} as distance_miles
            from menu_items mi
            join restaurants r on r.id = mi.restaurant_id
            where r.latitude is not null and r.longitude is not null
              and ({distance_sql}) <= $3
              and mi.price is not null
              and mi.price >= 5
              and ($4::text[] = '{{}}'::text[] or r.cuisine_tags && $4::text[] or mi.cuisine_tags && $4::text[])
              and ($7::text is null or {item_text} like ('%' || $7::text || '%'))
              and not exists (
                  select 1 from unnest($5::text[]) token
                  where {item_text} not like ('%' || token || '%')
              )
            order by mi.price asc, distance_miles asc, r.rating desc nulls last
            limit $6
            """,
            lat, lng, radius_miles, cuisine_tags, tokens, limit, exact_phrase,
        )
        return rows_to_json(rows)
    finally:
        await conn.close()


async def compare_menu_prices(
    item_query: str,
    location: str | None = None,
    quantity: int = 1,
    radius_miles: float = 5,
    cuisine: str | None = None,
) -> dict:
    """Compare prices for similar menu items across restaurants."""
    canonical_item_query = _normalize_item_query(item_query) or item_query
    inferred_cuisine = cuisine or extract_cuisine(item_query) or extract_cuisine(canonical_item_query)
    search_radius_miles = radius_miles
    expanded_search = False
    priced = await _direct_priced_item_search_variants(
        item_query=item_query,
        cuisine=inferred_cuisine,
        location=location,
        radius_miles=radius_miles,
        limit=12,
    )
    if not priced and inferred_cuisine and radius_miles < 60:
        expanded_search = True
        search_radius_miles = 60
        priced = await _direct_priced_item_search_variants(
            item_query=item_query,
            cuisine=inferred_cuisine,
            location=location,
            radius_miles=60,
            limit=12,
        )

    search = await hybrid_search_menu_items(
        query=canonical_item_query,
        location=location,
        radius_miles=radius_miles,
        cuisine=inferred_cuisine,
        limit=12,
    )
    items = search.get("items", [])
    if not priced:
        priced = [
            item for item in items
            if item.get("price") is not None
            and _item_name_matches(item_query, item)
            and not _is_irrelevant_price_match(item_query, item)
        ]
    else:
        priced = [
            item for item in priced
            if not _is_irrelevant_price_match(item_query, item)
        ]
    best_by_dish = {}
    for item in priced:
        key = _same_dish_key(item_query, item)
        existing = best_by_dish.get(key)
        best_by_dish[key] = item if existing is None else _preferred_duplicate(existing, item)
    priced = sorted(best_by_dish.values(), key=lambda item: float(item["price"]))
    priced = priced[:12]
    rows = [
        [
            item["restaurant_name"],
            item["name"],
            money(item["price"]),
            money(float(item["price"]) * quantity),
            f"{float(item['distance_miles']):.1f} mi",
            item.get("rating") or "-",
        ]
        for item in priced
    ]
    fallback = search.get("restaurant_fallback", [])
    if priced and inferred_cuisine:
        fallback = await _restaurant_fallback(inferred_cuisine, location, radius_miles)
    if not priced and not fallback and search.get("inferred_cuisine"):
        cuisine_search = await hybrid_search_menu_items(
            query=f"{search['inferred_cuisine']} menu",
            location=location,
            radius_miles=max(radius_miles, 60),
            cuisine=search["inferred_cuisine"],
            limit=12,
        )
        fallback = cuisine_search.get("restaurant_fallback", [])
    if not priced and not fallback and inferred_cuisine:
        fallback = await _restaurant_fallback(inferred_cuisine, location, radius_miles)
    fallback_rows = [
        [
            restaurant["name"],
            restaurant.get("city") or "-",
            f"{float(restaurant['distance_miles']):.1f} mi",
            restaurant.get("rating") or "-",
            restaurant.get("review_count") or 0,
            restaurant.get("menu_items_ingested") or 0,
        ]
        for restaurant in fallback
    ]
    price_table = table(["Restaurant", "Item", "Unit Price", f"Qty {quantity} Subtotal", "Distance", "Rating"], rows)
    priced_by_restaurant_id = {
        item.get("restaurant_id"): item
        for item in priced
        if item.get("restaurant_id")
    }
    coverage_rows = []
    for restaurant in fallback:
        match = priced_by_restaurant_id.get(restaurant.get("id"))
        if match:
            coverage_rows.append([
                restaurant["name"],
                match["name"],
                money(match["price"]),
                f"{float(restaurant['distance_miles']):.1f} mi",
                restaurant.get("menu_items_ingested") or 0,
            ])
        else:
            menu_count = restaurant.get("menu_items_ingested") or 0
            coverage_rows.append([
                restaurant["name"],
                "No exact item ingested" if menu_count else "No menu ingested",
                "-",
                f"{float(restaurant['distance_miles']):.1f} mi",
                menu_count,
            ])
    coverage_table = table(
        ["Restaurant", "Item availability", "Price", "Distance", "Menu items"],
        coverage_rows,
    ) if coverage_rows else ""
    expansion_message = (
        f"No priced {item_query} match was found within {radius_miles:g} miles; expanded to {search_radius_miles:g} miles."
        if expanded_search and priced
        else None
    )
    if rows and coverage_table:
        formatted_price = f"{price_table}\n\nAvailability across matching restaurants:\n\n{coverage_table}"
    else:
        formatted_price = price_table
    formatted = (
        f"{expansion_message}\n\n{formatted_price}" if expansion_message else formatted_price
        if rows
        else table(["Restaurant", "City", "Distance", "Rating", "Reviews", "Menu items"], fallback_rows)
        if fallback_rows
        else "No priced menu matches found."
    )
    return {
        "status": "ok",
        "item_query": item_query,
        "quantity": quantity,
        "count": len(priced),
        "search_radius_miles": search_radius_miles,
        "expanded_search": expanded_search and bool(priced),
        "lowest_price": float(priced[0]["price"]) if priced else None,
        "highest_price": float(priced[-1]["price"]) if priced else None,
        "restaurant_fallback_count": len(fallback),
        "restaurant_fallback": fallback,
        "message": (
            expansion_message
            if expansion_message
            else
            f"No priced menu matches found for {item_query}; showing cuisine-matched restaurants instead."
            if fallback_rows
            else None
        ),
        "formatted": formatted,
    }
