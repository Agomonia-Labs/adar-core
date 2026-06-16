"""Google Places ingestion for restaurant discovery."""

from __future__ import annotations

import asyncio
import json
import math
import os
import textwrap
from typing import Any

import httpx

from domains.restaurants.db import connect, upsert_restaurant
from domains.restaurants.ingestion.normalization import normalize_tags, normalize_text, stable_uuid


GOOGLE_PLACES_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
GOOGLE_NEARBY_MAX_RADIUS_METERS = 50000
MILES_TO_METERS = 1609.344
EARTH_RADIUS_MILES = 3958.7613

LOCATION_PRESETS = {
    "greater-seattle": {
        "latitude": 47.6062,
        "longitude": -122.3321,
        "radius_miles": 60.0,
    },
    "seattle": {
        "latitude": 47.6062,
        "longitude": -122.3321,
        "radius_miles": 15.0,
    },
}

DEFAULT_PRIMARY_TYPES = [
    "restaurant",
    "cafe",
    "bakery",
    "bar",
    "meal_takeaway",
    "american_restaurant",
    "barbecue_restaurant",
    "breakfast_restaurant",
    "brunch_restaurant",
    "chinese_restaurant",
    "fast_food_restaurant",
    "hamburger_restaurant",
    "indian_restaurant",
    "indonesian_restaurant",
    "italian_restaurant",
    "japanese_restaurant",
    "korean_restaurant",
    "mediterranean_restaurant",
    "mexican_restaurant",
    "middle_eastern_restaurant",
    "pizza_restaurant",
    "ramen_restaurant",
    "seafood_restaurant",
    "spanish_restaurant",
    "steak_house",
    "sushi_restaurant",
    "thai_restaurant",
    "turkish_restaurant",
    "vegan_restaurant",
    "vegetarian_restaurant",
    "vietnamese_restaurant",
]

TYPE_TO_CUISINE = {
    "american_restaurant": "american",
    "barbecue_restaurant": "american",
    "breakfast_restaurant": "american",
    "brunch_restaurant": "american",
    "fast_food_restaurant": "fast_food",
    "hamburger_restaurant": "american",
    "indonesian_restaurant": "asian",
    "sandwich_shop": "american",
    "chinese_restaurant": "chinese",
    "indian_restaurant": "indian",
    "japanese_restaurant": "japanese",
    "korean_restaurant": "korean",
    "ramen_restaurant": "japanese",
    "thai_restaurant": "thai",
    "vietnamese_restaurant": "vietnamese",
    "mexican_restaurant": "mexican",
    "italian_restaurant": "italian",
    "mediterranean_restaurant": "mediterranean",
    "middle_eastern_restaurant": "middle_eastern",
    "seafood_restaurant": "seafood",
    "pizza_restaurant": "italian",
    "spanish_restaurant": "spanish",
    "steak_house": "american",
    "sushi_restaurant": "japanese",
    "turkish_restaurant": "mediterranean",
    "vegan_restaurant": "vegan",
    "vegetarian_restaurant": "vegetarian",
}

ASIAN_CUISINES = {
    "asian",
    "chinese",
    "indian",
    "indonesian",
    "japanese",
    "korean",
    "ramen",
    "thai",
    "vietnamese",
}


async def ingest_google_places_area(
    location: str = "greater-seattle",
    radius_miles: float | None = None,
    tile_radius_miles: float = 25.0,
    included_primary_types: list[str] | None = None,
    max_results_per_tile: int = 20,
    delay_seconds: float = 0.2,
) -> dict[str, int]:
    api_key = os.getenv("GOOGLE_PLACES_API_KEY")
    if not api_key:
        raise RuntimeError("Set GOOGLE_PLACES_API_KEY in .env.restaurants.")

    center_lat, center_lng, default_radius = _resolve_location(location)
    requested_radius = radius_miles or default_radius
    tile_radius_meters = min(
        tile_radius_miles * MILES_TO_METERS,
        GOOGLE_NEARBY_MAX_RADIUS_METERS,
    )
    primary_types = included_primary_types or DEFAULT_PRIMARY_TYPES
    centers = _grid_centers(center_lat, center_lng, requested_radius, tile_radius_miles)

    seen_place_ids: set[str] = set()
    counts = {
        "tiles": len(centers),
        "requests": 0,
        "places_seen": 0,
        "restaurants": 0,
        "duplicates": 0,
    }

    conn = await connect()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            for lat, lng in centers:
                for primary_type in primary_types:
                    places = await _nearby_search(
                        client=client,
                        api_key=api_key,
                        latitude=lat,
                        longitude=lng,
                        radius_meters=tile_radius_meters,
                        included_primary_type=primary_type,
                        max_result_count=max_results_per_tile,
                    )
                    counts["requests"] += 1
                    counts["places_seen"] += len(places)
                    for place in places:
                        place_id = place.get("id")
                        if not place_id:
                            continue
                        if place_id in seen_place_ids:
                            counts["duplicates"] += 1
                            continue
                        seen_place_ids.add(place_id)
                        restaurant = _place_to_restaurant(place)
                        await upsert_restaurant(conn, restaurant)
                        counts["restaurants"] += 1
                    if delay_seconds:
                        await asyncio.sleep(delay_seconds)
    finally:
        await conn.close()

    return counts


async def _nearby_search(
    client: httpx.AsyncClient,
    api_key: str,
    latitude: float,
    longitude: float,
    radius_meters: float,
    included_primary_type: str,
    max_result_count: int,
) -> list[dict[str, Any]]:
    payload = {
        "includedPrimaryTypes": [included_primary_type],
        "maxResultCount": max(1, min(max_result_count, 20)),
        "rankPreference": "POPULARITY",
        "locationRestriction": {
            "circle": {
                "center": {"latitude": latitude, "longitude": longitude},
                "radius": radius_meters,
            }
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": ",".join([
            "places.id",
            "places.displayName",
            "places.formattedAddress",
            "places.location",
            "places.rating",
            "places.userRatingCount",
            "places.priceLevel",
            "places.websiteUri",
            "places.nationalPhoneNumber",
            "places.primaryType",
            "places.types",
            "places.dineIn",
            "places.takeout",
            "places.delivery",
            "places.servesBreakfast",
            "places.servesBrunch",
            "places.servesLunch",
            "places.servesDinner",
            "places.servesVegetarianFood",
        ]),
    }
    response = await client.post(GOOGLE_PLACES_NEARBY_URL, json=payload, headers=headers)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text
        try:
            detail = json.dumps(response.json(), indent=2)
        except json.JSONDecodeError:
            pass
        raise RuntimeError(
            textwrap.dedent(
                f"""
                Google Places Nearby Search failed with HTTP {response.status_code}.

                Request primary type: {included_primary_type}
                Request center: {latitude}, {longitude}
                Request radius meters: {radius_meters:.0f}

                Google response:
                {detail}

                Common fixes:
                - Set GOOGLE_PLACES_API_KEY in .env.restaurants.
                - Enable Places API (New) for the Google Cloud project that owns the key.
                - Ensure billing is enabled on that Google Cloud project.
                - If the key is restricted, allow this API and allow server/IP usage from this machine.
                """
            ).strip()
        ) from exc
    return response.json().get("places", [])


def _place_to_restaurant(place: dict[str, Any]) -> dict[str, Any]:
    place_id = place["id"]
    types = place.get("types") or []
    primary_type = place.get("primaryType")
    display_name = place.get("displayName") or {}
    location = place.get("location") or {}
    service_types = []
    meal_tags = []

    for key, tag in [
        ("dineIn", "dine_in"),
        ("takeout", "takeout"),
        ("delivery", "delivery"),
    ]:
        if place.get(key) is True:
            service_types.append(tag)

    for key, tag in [
        ("servesBreakfast", "breakfast"),
        ("servesBrunch", "brunch"),
        ("servesLunch", "lunch"),
        ("servesDinner", "dinner"),
    ]:
        if place.get(key) is True:
            meal_tags.append(tag)

    cuisine_tags = _cuisine_tags(primary_type, types)
    if place.get("servesVegetarianFood") is True:
        cuisine_tags.append("vegetarian")

    return {
        "id": stable_uuid("google-place", place_id),
        "name": display_name.get("text") or place_id,
        "normalized_name": normalize_text(display_name.get("text") or place_id),
        "website_url": place.get("websiteUri"),
        "phone": place.get("nationalPhoneNumber"),
        "address": place.get("formattedAddress"),
        "city": None,
        "region": "WA",
        "postal_code": None,
        "country": "US",
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "rating": place.get("rating"),
        "review_count": place.get("userRatingCount") or 0,
        "price_level": _price_level(place.get("priceLevel")),
        "service_types": normalize_tags(service_types),
        "cuisine_tags": normalize_tags(cuisine_tags),
        "meal_tags": normalize_tags(meal_tags),
        "source_refs_json": json.dumps([
            {
                "source": "google_places",
                "place_id": place_id,
                "primary_type": primary_type,
                "types": types,
            }
        ]),
    }


def _cuisine_tags(primary_type: str | None, types: list[str]) -> list[str]:
    tags = []
    for place_type in [primary_type, *types]:
        if place_type in TYPE_TO_CUISINE and TYPE_TO_CUISINE[place_type] not in tags:
            tags.append(TYPE_TO_CUISINE[place_type])
    if any(tag in ASIAN_CUISINES for tag in tags) and "asian" not in tags:
        tags.append("asian")
    if not tags:
        tags.append("restaurant")
    return tags


def _price_level(value: str | None) -> int | None:
    if not value:
        return None
    mapping = {
        "PRICE_LEVEL_FREE": 0,
        "PRICE_LEVEL_INEXPENSIVE": 1,
        "PRICE_LEVEL_MODERATE": 2,
        "PRICE_LEVEL_EXPENSIVE": 3,
        "PRICE_LEVEL_VERY_EXPENSIVE": 4,
    }
    return mapping.get(value)


def _resolve_location(location: str) -> tuple[float, float, float]:
    preset = LOCATION_PRESETS.get(location.lower())
    if preset:
        return preset["latitude"], preset["longitude"], preset["radius_miles"]

    if "," in location:
        lat_raw, lng_raw = location.split(",", 1)
        return float(lat_raw.strip()), float(lng_raw.strip()), 60.0

    raise ValueError(
        f"Unknown location '{location}'. Use 'greater-seattle' or 'lat,lng'."
    )


def _grid_centers(
    center_lat: float,
    center_lng: float,
    radius_miles: float,
    tile_radius_miles: float,
) -> list[tuple[float, float]]:
    spacing = tile_radius_miles * 1.35
    offsets = []
    steps = math.ceil(radius_miles / spacing)
    for y in range(-steps, steps + 1):
        for x in range(-steps, steps + 1):
            east_miles = x * spacing
            north_miles = y * spacing
            if math.hypot(east_miles, north_miles) <= radius_miles:
                offsets.append((north_miles, east_miles))

    centers = []
    for north_miles, east_miles in offsets:
        lat = center_lat + math.degrees(north_miles / EARTH_RADIUS_MILES)
        lng = center_lng + math.degrees(
            east_miles / (EARTH_RADIUS_MILES * math.cos(math.radians(center_lat)))
        )
        centers.append((lat, lng))
    return centers or [(center_lat, center_lng)]
