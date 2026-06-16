import os
from dotenv import load_dotenv
# Only load .env in local development — never in production.
# Set DOTENV_FILE=.env.geetabitan to run as Geetabitan locally.
if os.environ.get("APP_ENV") != "production":
    _env_file = os.environ.get("DOTENV_FILE", ".env")
    load_dotenv(_env_file, override=True)

import uuid
import time
import logging
import re
from typing import Optional
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader

from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai.types import Content, Part

# ── CHANGE 1: import build_agents (was build_arcl_orchestrator) ──────────────
from src.adar.agents.agents import build_agents
from google.cloud import firestore as _firestore
from api.routes.polls import router as polls_router
from api.routes.auth  import router as auth_router, get_current_team
from api.routes.music import router as music_router
from api.routes.admin import router as admin_router
from api.routes.payments import router as payments_router
from evaluation.judge import evaluate_response
from api.schemas import ChatRequest, ChatResponse, SessionResponse
from src.adar.config import settings
from src.adar.config import DOMAIN, OFFTOPIC_GUARD

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

session_service: DatabaseSessionService = None
# ── CHANGE 2: generic name (was arcl_orchestrator) ───────────────────────────
orchestrator = None
APP_NAME = settings.APP_NAME


def _strip_song_ids(text: str) -> str:
    """Remove internal song identifiers from user-facing model output."""
    if not text:
        return text
    text = re.sub(r"\[song_id:[^\]]+\]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*[—-]?\s*song_id\s*:\s*`?[^`\s|),।.!?]+`?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsong_id\b\s*[:=]\s*`?[^`\s|),।.!?]+`?", "", text, flags=re.IGNORECASE)
    return text


def _is_youtube_play_request(text: str) -> bool:
    return bool(re.search(r"youtube|youtu\.be|ইউটিউব|play|listen|শুন|শোন|লিংক", text or "", re.IGNORECASE))


def _has_youtube_url(text: str) -> bool:
    return bool(re.search(r"https://(?:www\.)?(?:youtube\.com|youtu\.be)/", text or "", re.IGNORECASE))


def _is_restaurant_price_query(text: str) -> bool:
    if DOMAIN != "restaurants":
        return False
    lowered = (text or "").lower()
    return bool(re.search(r"\b(compare|cheapest|price|prices|cost|costs|how much)\b", lowered))


def _is_restaurant_count_query(text: str) -> bool:
    if DOMAIN != "restaurants":
        return False
    lowered = (text or "").lower()
    return bool(
        re.search(r"\b(how many|count|number of|total)\b", lowered)
        and re.search(r"\b(restaurant|restaurants|places)\b", lowered)
    )


def _is_restaurant_detail_query(text: str) -> bool:
    if DOMAIN != "restaurants":
        return False
    lowered = (text or "").lower()
    return bool(
        re.search(r"\b(address|phone|website|site|url|rating|reviews|review count|where is|location|details|detail|profile|contact)\b", lowered)
        and (
            re.search(r"[\"“”'][^\"“”']{3,}[\"“”']", text or "")
            or re.search(r"\b(restaurant|cafe|bistro|kitchen|bar|grill)\b", lowered)
        )
    )


def _is_restaurant_genre_summary_query(text: str) -> bool:
    if DOMAIN != "restaurants":
        return False
    lowered = (text or "").lower()
    return bool(
        re.search(r"\b(group|grouped|summary|summarize|breakdown|by genre|by category|by type)\b", lowered)
        and re.search(r"\b(restaurant|restaurants|genre|genres|category|categories|type|types)\b", lowered)
    )


def _is_restaurant_list_query(text: str) -> bool:
    if DOMAIN != "restaurants":
        return False
    lowered = (text or "").lower()
    if _is_restaurant_price_query(lowered) or _is_restaurant_count_query(lowered):
        return False
    if re.search(r"\b(with|without|no|missing|doesn'?t have|do not have|don'?t have|has|have)\b.{0,30}\b(menu|menus|meny|menue)\b", lowered):
        return bool(re.search(r"\b(restaurant|restaurants|places)\b", lowered))
    return bool(
        re.search(r"\b(show|list|give|get|display)\b", lowered)
        and re.search(r"\b(all|entire|every|full list|list)\b", lowered)
        and re.search(r"\b(restaurant|restaurants|places)\b", lowered)
    )


def _restaurant_menu_status_from_query(text: str) -> str:
    lowered = (text or "").lower()
    if re.search(r"\b(without|missing|no)\b.{0,40}\b(menu|menus|meny|menue)\b", lowered):
        return "without"
    if re.search(r"\b(doesn'?t have|does not have|do not have|don'?t have)\b.{0,40}\b(menu|menus|meny|menue)\b", lowered):
        return "without"
    if re.search(r"\b(with|has|have)\b.{0,40}\b(menu|menus|meny|menue)\b", lowered):
        return "with"
    return "all"


def _is_restaurant_menu_item_query(text: str) -> bool:
    if DOMAIN != "restaurants":
        return False
    lowered = (text or "").lower()
    if _is_restaurant_price_query(lowered):
        return False
    if re.search(r"[\"“”'][^\"“”']{3,}[\"“”']", text or ""):
        return True
    if re.search(r"\b(these|those|this|that|they|it|them)\b.{0,30}\bnot\b", lowered):
        return True
    return bool(re.search(
        r"\b(menu|menus|meny|menue|dish|dishes|item|items|serve|serves|serving|have|has|available|availability|find|show|recommend|option|options)\b",
        lowered,
    ))


def _is_single_restaurant_menu_query(text: str) -> bool:
    if DOMAIN != "restaurants":
        return False
    lowered = (text or "").lower()
    return bool(
        re.search(r"\b(menu|menus|meny|menue)\b", lowered)
        and re.search(r"\b(restaurant|place|cafe|bistro|kitchen|bar|grill|thai|indian|italian|chinese|american)\b", lowered)
    )


def _extract_restaurant_name_for_menu(text: str) -> str:
    raw = text or ""
    quoted = re.findall(r"[\"“”']([^\"“”']{3,})[\"“”']", raw)
    if quoted:
        return quoted[-1].strip(" .,?!")
    name = raw.lower()
    name = re.sub(r"\b(show|find|get|give|me|the|a|an|their|its|full|restaurant|restaurants|menu|menus|meny|menue|for|of|at|in|near|around)\b", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .,?!")
    return name


def _restaurant_query_locations(text: str) -> list[str]:
    aliases = {"bellvue": "bellevue"}
    known = [
        "greater seattle", "seattle", "bellevue", "bellvue", "bothell",
        "redmond", "kirkland", "renton", "tacoma", "everett",
    ]
    lowered = (text or "").lower()
    locations = []
    for name in known:
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            canonical = aliases.get(name, name)
            if canonical not in locations:
                locations.append(canonical)
    return locations


def _restaurant_location_terms(text: str) -> list[str]:
    known = [
        "greater seattle", "seattle", "bellevue", "bellvue", "bothell",
        "redmond", "kirkland", "renton", "tacoma", "everett",
    ]
    lowered = (text or "").lower()
    return [name for name in known if re.search(rf"\b{re.escape(name)}\b", lowered)]


def _extract_restaurant_price_item(text: str, location: str | None = None) -> str:
    item = (text or "").lower()
    protected_phrases = {
        "pad thai": "padthai",
    }
    for phrase, token in protected_phrases.items():
        item = re.sub(rf"\b{re.escape(phrase)}\b", token, item)
    item = re.sub(
        r"\b(compare|comparison|cheapest|cheap|least expensive|find|show|me|the|a|an|what|which|are|is|have|has|with|price|prices|cost|costs|how much|for|from|of|these|those|this|that|restaurant|restaurants)\b",
        " ",
        item,
    )
    item = re.sub(
        r"\b(thai|indian|italian|american|asian|chinese|japanese|korean|mexican|vietnamese|seafood|vegetarian|vegan)\b",
        " ",
        item,
    )
    item = re.sub(r"\bnear me\b", " ", item)
    locations = _restaurant_location_terms(text)
    if location and location not in locations:
        locations.append(location)
    for loc in locations:
        loc_label = loc.replace("-", " ")
        item = re.sub(rf"\b(near|in|around)\s+{re.escape(loc_label)}\b", " ", item)
        item = re.sub(rf"\b{re.escape(loc_label)}\b", " ", item)
    item = re.sub(r"\b(in|near|around)\s+[a-z ]+$", " ", item)
    item = re.sub(r"\bnear\s+[a-z ]+$", " ", item)
    for phrase, token in protected_phrases.items():
        item = re.sub(rf"\b{re.escape(token)}\b", phrase, item)
    item = re.sub(r"[,;/]+", " ", item)
    item = re.sub(r"\s+", " ", item).strip(" .,?!")
    return item or (text or "").strip()


def _extract_restaurant_menu_item(text: str, location: str | None = None) -> str:
    raw = text or ""
    quoted = re.findall(r"[\"“”']([^\"“”']{3,})[\"“”']", raw)
    if quoted:
        return quoted[-1].strip(" .,?!")
    item = raw.lower()
    item = re.sub(
        r"\b(these|those|this|that|they|it|them|are|is|were|was|not|no|specific|actual|real|exact|same|list|previous|results|result)\b",
        " ",
        item,
    )
    item = re.sub(
        r"\b(which|what|where|who|find|show|me|the|a|an|restaurant|restaurants|place|places|nearby|near|around|in|with|that|have|has|serve|serves|serving|available|availability|menu|menus|meny|menue|dish|dishes|item|items|option|options|recommend|recommendation|recommendations)\b",
        " ",
        item,
    )
    item = re.sub(
        r"\b(thai|indian|italian|american|asian|chinese|japanese|korean|mexican|vietnamese|seafood|vegetarian|vegan)\b",
        " ",
        item,
    )
    item = re.sub(r"\bnear me\b", " ", item)
    if location:
        item = re.sub(rf"\b(near|in|around)\s+{re.escape(location.replace('-', ' '))}\b", " ", item)
        item = re.sub(rf"\b{re.escape(location.replace('-', ' '))}\b", " ", item)
    item = re.sub(r"\bnear\s+[a-z ]+$", " ", item)
    item = re.sub(r"\s+", " ", item).strip(" .,?!")
    return item


async def _restaurant_price_response(message: str) -> str | None:
    if not _is_restaurant_price_query(message):
        return None
    from domains.restaurants.tools.restaurant_tools import parse_food_request
    from domains.restaurants.tools.pricing_tools import compare_menu_prices

    parsed = await parse_food_request(message)
    item_query = _extract_restaurant_price_item(message, parsed.get("location"))
    lowered = message.lower()
    parsed_location = parsed.get("location")
    query_locations = _restaurant_query_locations(message)
    search_location = "greater seattle" if len(query_locations) > 1 else (parsed_location or "seattle")
    if "near me" in lowered:
        radius_miles = 5
    elif len(query_locations) > 1:
        radius_miles = 60
    elif "cheapest" in lowered and parsed_location in {"greater seattle", "greater-seattle", "seattle", None}:
        radius_miles = 60
    elif "cheapest" in lowered and parsed_location:
        radius_miles = 15
    else:
        radius_miles = 5
    result = await compare_menu_prices(
        item_query=item_query,
        location=search_location,
        quantity=parsed.get("quantity") or 1,
        cuisine=parsed.get("cuisine"),
        radius_miles=radius_miles,
    )
    if result.get("count", 0) > 0:
        lowest = result.get("lowest_price")
        prefix = f"Lowest found for {item_query}: ${lowest:.2f}." if lowest is not None else f"Found prices for {item_query}."
        return f"{prefix}\n\n{result.get('formatted', '')}"
    if result.get("formatted"):
        return result["formatted"]
    return None


async def _restaurant_count_response(message: str) -> str | None:
    if not _is_restaurant_count_query(message):
        return None
    from domains.restaurants.tools.restaurant_tools import parse_food_request, count_restaurants

    parsed = await parse_food_request(message)
    locations = _restaurant_query_locations(message)
    location = locations[0] if len(locations) == 1 else None
    radius_miles = 15 if location else None
    result = await count_restaurants(
        cuisine=parsed.get("cuisine"),
        location=location,
        radius_miles=radius_miles,
    )
    return result.get("formatted")


def _extract_restaurant_name_for_detail(text: str) -> str:
    quoted = re.findall(r"[\"“”']([^\"“”']{3,})[\"“”']", text or "")
    if quoted:
        return quoted[-1].strip(" .,?!")
    name = (text or "").lower()
    name = re.sub(
        r"\b(what|whats|what's|is|are|the|address|phone|website|site|url|rating|reviews|review count|where|location|details|detail|profile|contact|of|for|at|restaurant|restaurants)\b",
        " ",
        name,
    )
    return re.sub(r"\s+", " ", name).strip(" .,?!")


def _quoted_restaurant_names(text: str) -> list[str]:
    names = []
    seen = set()
    for raw in re.findall(r"[\"“”']([^\"“”']{3,})[\"“”']", text or ""):
        name = raw.strip(" .,?!")
        key = name.lower()
        if name and key not in seen:
            names.append(name)
            seen.add(key)
    return names


async def _restaurant_detail_response(message: str) -> str | None:
    if not _is_restaurant_detail_query(message):
        return None
    from domains.restaurants.tools.restaurant_tools import parse_food_request, get_restaurant_details
    from domains.restaurants.tools.query_utils import table

    quoted_names = _quoted_restaurant_names(message)
    if len(quoted_names) > 1:
        parsed = await parse_food_request(message)
        rows = []
        for restaurant_name in quoted_names:
            result = await get_restaurant_details(
                restaurant_name=restaurant_name,
                location=parsed.get("location") or "seattle",
            )
            restaurant = result.get("restaurant") or {}
            address_parts = [
                restaurant.get("address"),
                restaurant.get("city"),
                restaurant.get("region"),
                restaurant.get("postal_code"),
            ]
            address = ", ".join(str(part) for part in address_parts if part)
            rows.append([
                restaurant.get("name") or restaurant_name,
                address or "-",
                restaurant.get("phone") or "-",
                restaurant.get("website_url") or "-",
                restaurant.get("rating") or "-",
                restaurant.get("review_count") or 0,
                restaurant.get("menu_items_ingested") or 0,
            ])
        return table(["Restaurant", "Address", "Phone", "Website", "Rating", "Reviews", "Menu items"], rows)

    parsed = await parse_food_request(message)
    restaurant_name = _extract_restaurant_name_for_detail(message)
    if not restaurant_name:
        return None
    result = await get_restaurant_details(
        restaurant_name=restaurant_name,
        location=parsed.get("location") or "seattle",
    )
    return result.get("formatted")


async def _restaurant_direct_response(message: str) -> str | None:
    """Deterministic restaurant-domain router before the ADK fallback."""
    for handler in [
        _restaurant_count_response,
        _restaurant_detail_response,
        _restaurant_listing_response,
        _restaurant_price_response,
        _single_restaurant_menu_response,
        _restaurant_menu_item_response,
    ]:
        response = await handler(message)
        if response:
            return response
    return None


async def _restaurant_listing_response(message: str) -> str | None:
    if _is_restaurant_genre_summary_query(message):
        from domains.restaurants.tools.restaurant_tools import restaurant_genre_summary

        result = await restaurant_genre_summary()
        return result.get("formatted")
    if not _is_restaurant_list_query(message):
        return None
    from domains.restaurants.tools.restaurant_tools import parse_food_request, list_restaurants

    parsed = await parse_food_request(message)
    locations = _restaurant_query_locations(message)
    location = locations[0] if len(locations) == 1 else None
    result = await list_restaurants(
        cuisine=parsed.get("cuisine"),
        location=location,
        radius_miles=60 if location else None,
        menu_status=_restaurant_menu_status_from_query(message),
        limit=100,
    )
    return result.get("formatted")


async def _single_restaurant_menu_response(message: str) -> str | None:
    if not _is_single_restaurant_menu_query(message):
        return None
    from domains.restaurants.tools.restaurant_tools import parse_food_request
    from domains.restaurants.tools.menu_tools import get_restaurant_menu

    parsed = await parse_food_request(message)
    restaurant_name = _extract_restaurant_name_for_menu(message)
    if not restaurant_name:
        return None
    result = await get_restaurant_menu(
        restaurant_name=restaurant_name,
        location=parsed.get("location") or "seattle",
        limit=40,
    )
    if result.get("formatted"):
        return result["formatted"]
    return None


async def _restaurant_menu_item_response(message: str) -> str | None:
    if not _is_restaurant_menu_item_query(message):
        return None
    from domains.restaurants.tools.restaurant_tools import parse_food_request
    from domains.restaurants.tools.menu_tools import hybrid_search_menu_items

    parsed = await parse_food_request(message)
    item_query = _extract_restaurant_menu_item(message, parsed.get("location"))
    if not item_query or len(item_query.split()) > 6:
        return None
    cuisine = parsed.get("cuisine")
    lowered = message.lower()
    radius_miles = 5 if "near me" in lowered else 60
    result = await hybrid_search_menu_items(
        query=item_query,
        location=parsed.get("location") or "seattle",
        radius_miles=radius_miles,
        cuisine=cuisine,
        limit=12,
    )
    if result.get("count", 0) > 0:
        cuisine_note = f" ({cuisine})" if cuisine else ""
        return f"Found menu matches for {item_query}{cuisine_note}:\n\n{result.get('formatted', '')}"
    if result.get("formatted"):
        return result["formatted"]
    return None

# ── Rate limiting ────────────────────────────────────────────────────────────
# Simple in-memory rate limiter: max 20 requests per minute per IP
RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW   = 60  # seconds
_rate_buckets: dict = defaultdict(list)


def _check_rate_limit(ip: str) -> bool:
    """Returns True if request is allowed, False if rate limited."""
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    _rate_buckets[ip] = [t for t in _rate_buckets[ip] if t > window_start]
    if len(_rate_buckets[ip]) >= RATE_LIMIT_REQUESTS:
        return False
    _rate_buckets[ip].append(now)
    return True


# ── API key auth ─────────────────────────────────────────────────────────────
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _verify_api_key(api_key: Optional[str] = Depends(API_KEY_HEADER)) -> bool:
    """
    Verify API key if one is configured.
    # ── CHANGE 3: reads settings.API_KEY which resolves per DOMAIN ────────────
    If no key is configured, auth is skipped (dev mode).
    """
    expected = getattr(settings, "API_KEY", None)
    if not expected:
        return True  # No key configured — allow all (dev mode)
    if not api_key:
        return True  # No key sent — JWT auth handles identity
    if api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── CHANGE 4: use generic orchestrator + build_agents() ──────────────────
    global session_service, orchestrator
    logger.info(f"Starting Adar {DOMAIN.upper()} API...")
    session_service = DatabaseSessionService(db_url=settings.SESSION_DB_URL)
    orchestrator, _ = build_agents()
    logger.info(f"Orchestrator ready — domain: {DOMAIN}  model: {settings.ADK_MODEL}")
    yield
    logger.info(f"Shutting down Adar {DOMAIN.upper()} API...")


# ── App ───────────────────────────────────────────────────────────────────────

# ── CHANGE 5: title/description are domain-aware ─────────────────────────────
_DOMAIN_META = {
    "arcl": {
        "title":       "Adar ARCL API",
        "description": "Multi-agent AI assistant for the American Recreational Cricket League",
    },
    "geetabitan": {
        "title":       "Adar Geetabitan API",
        "description": "Multi-agent AI assistant for Geetabitan — Rabindranath Tagore's complete songs",
    },
    "restaurants": {
        "title":       "Adar Restaurants API",
        "description": "Multi-agent AI assistant for restaurants food recommendations, menu search, price comparison, and reviews",
    },
}
_meta = _DOMAIN_META.get(DOMAIN, _DOMAIN_META["arcl"])

app = FastAPI(
    title       = _meta["title"],
    description = _meta["description"],
    version     = "1.0.0",
    lifespan    = lifespan,
    docs_url    = "/docs" if getattr(settings, "APP_ENV", "production") != "production" else None,
    redoc_url   = None,
)

# ── CHANGE 6: CORS origins include geetabitan domain ─────────────────────────
_PROD_ORIGINS = [
    "https://arcl.tigers.agomoniai.com",
    "https://www.arcl.tigers.agomoniai.com",
    "https://adar.agomoniai.com",
    "https://www.adar.agomoniai.com",
    "https://geetabitan.adar.agomoniai.com",
    "https://www.geetabitan.adar.agomoniai.com",
    # Firebase default URLs
    "https://geetabitan-adar.web.app",
    "https://geetabitan-adar.firebaseapp.com",
]
_DEV_ORIGINS = [
    "http://localhost:6001", "http://localhost:6002", "http://localhost:5173", "http://localhost:3000",
    "http://127.0.0.1:6001", "http://127.0.0.1:6002", "http://127.0.0.1:5173", "http://127.0.0.1:3000",
]
_ALL_ORIGINS = _PROD_ORIGINS + (_DEV_ORIGINS if settings.APP_ENV != "production" else [])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALL_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(polls_router)
app.include_router(auth_router)
app.include_router(music_router)

@app.get("/api/ingestion/status")
async def ingestion_status(team: dict = Depends(get_current_team)):
    """Return ingestion status for the current team."""
    team_id = team["team_id"]
    if team_id == "admin" or team.get("role") == "admin":
        return {"status": "complete", "message": ""}
    db = _firestore.AsyncClient(
        project=settings.GCP_PROJECT_ID,
        database=settings.FIRESTORE_DATABASE,
    )
    doc = await db.collection("adar_teams").document(team_id).get()
    data = doc.to_dict() if doc.exists else {}
    status = data.get("ingestion_status", "complete")
    message = data.get("ingestion_message", "")
    return {"status": status, "message": message, "team_id": team_id}


@app.get("/api/usage")
async def get_usage(
    team: dict = Depends(get_current_team),
    _auth: bool = Depends(_verify_api_key),
):
    """Return today's usage and quota for the current team."""
    from datetime import datetime, timezone
    db = _firestore.AsyncClient(
        project=settings.GCP_PROJECT_ID,
        database=settings.FIRESTORE_DATABASE,
    )
    team_id = team["team_id"]
    if team_id == "admin" or team.get("role") == "admin":
        return {"used_today": 0, "daily_quota": 99999, "resets_at": "never", "plan": "admin"}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    doc = await db.collection("adar_teams").document(team_id).get()
    data = doc.to_dict() if doc.exists else {}

    last_reset = data.get("usage_reset_date", "")
    usage_today = data.get("usage_today", 0)
    logger.info(f"Usage read: team={team_id} today={today} last_reset={last_reset!r} count={usage_today} db={settings.FIRESTORE_DATABASE}")
    if last_reset != today:
        logger.info(f"Resetting usage: last_reset={last_reset!r} != today={today!r}")
        usage_today = 0
        await db.collection("adar_teams").document(team_id).update({
            "usage_today": 0,
            "usage_reset_date": today,
        })

    PLAN_QUOTAS = {"basic": 50, "standard": 200, "unlimited": 1000, "complimentary": 200}
    plan = data.get("subscription_plan", "standard")
    daily_quota = (
        data.get("daily_quota") or
        data.get("quota_daily") or
        PLAN_QUOTAS.get(plan, 200)
    )
    logger.info(f"Usage check: team={team_id} used={usage_today} quota={daily_quota}")
    return {
        "used_today":  int(usage_today or 0),
        "daily_quota": int(daily_quota or 200),
        "resets_at":   "midnight UTC",
        "plan":        plan,
    }


@app.get("/api/arcl/teams")
async def get_arcl_teams(season: int = 69):
    """Return all ARCL team names for registration dropdown — scraped live from arcl.org."""
    import httpx
    from bs4 import BeautifulSoup
    import re
    teams = []
    seen = set()
    base = "https://www.arcl.org"
    async with httpx.AsyncClient(timeout=20) as client:
        for league_id in range(2, 14):
            try:
                url = f"{base}/Pages/UI/DivHome.aspx?league_id={league_id}&season_id={season}"
                r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                soup = BeautifulSoup(r.text, "html.parser")
                for link in soup.find_all("a", href=True):
                    if "TeamStats" in link["href"]:
                        name = link.text.strip()
                        tid = re.search(r"team_id=(\d+)", link["href"])
                        if name and name not in seen and tid:
                            seen.add(name)
                            teams.append({"name": name, "team_id": int(tid.group(1)), "league_id": league_id})
            except Exception:
                continue
    teams.sort(key=lambda x: x["name"])
    return {"teams": teams, "season_id": season}


app.include_router(admin_router)
app.include_router(payments_router)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def get_or_create_session(user_id: str, session_id: Optional[str]):
    sid = session_id or str(uuid.uuid4())
    if session_id:
        try:
            session = await session_service.get_session(
                app_name=APP_NAME,
                user_id=user_id,
                session_id=sid,
            )
            if session:
                return session
        except Exception:
            pass
    return await session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=sid,
        state={},
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    http_request: Request,
    _auth: bool = Depends(_verify_api_key),
):
    # Rate limiting
    client_ip = _get_client_ip(http_request)
    if not _check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait a moment before trying again.",
        )

    # Input validation
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    if len(message) > 2000:
        raise HTTPException(status_code=400, detail="Message too long (max 2000 characters)")

    if not re.match(r'^[a-zA-Z0-9_\-]{1,64}$', request.user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id format")

    try:
        session = await get_or_create_session(request.user_id, request.session_id)

        # ── CHANGE 7: use generic orchestrator (was arcl_orchestrator) ────────
        runner = Runner(
            agent=orchestrator,
            app_name=APP_NAME,
            session_service=session_service,
        )

        # ── CHANGE 8: domain-aware off-topic guard ────────────────────────────
        # Reads OFF_TOPIC blocklist and domain hint allowlist from OFFTOPIC_GUARD
        # config so this block works for both ARCL and Geetabitan with zero
        # code duplication.
        _guard      = OFFTOPIC_GUARD.get(DOMAIN, {})
        _off_topic  = _guard.get("off_topic",  [])   # denylist (always blocked)
        _hints      = _guard.get("hints",      [])   # allowlist (domain context)
        _reject_msg = _guard.get("reject_msg", "")
        msg_low = message.lower()
        if _off_topic and _hints:
            if any(k in msg_low for k in _off_topic) and not any(k in msg_low for k in _hints):
                return ChatResponse(
                    response=_reject_msg,
                    session_id=str(session.id),
                    user_id=request.user_id,
                    eval=None,
                )
        # ─────────────────────────────────────────────────────────────────────

        user_message = Content(role="user", parts=[Part(text=message)])

        response_text = await _restaurant_direct_response(message) or ""
        if not response_text:
            async for event in runner.run_async(
                user_id=request.user_id,
                session_id=session.id,
                new_message=user_message,
            ):
                if hasattr(event, "is_final_response") and event.is_final_response():
                    if event.content and event.content.parts:
                        for part in event.content.parts:
                            if hasattr(part, "text") and part.text:
                                response_text += part.text

        if not response_text:
            response_text = "I couldn't find an answer. Please try rephrasing your question."
        response_text = _strip_song_ids(response_text)
        if _is_youtube_play_request(message) and not _has_youtube_url(response_text):
            try:
                from domains.geetabitan.tools.song_tools import play_youtube_song
                response_text = _strip_song_ids(await play_youtube_song(message))
            except Exception as yt_err:
                logger.warning(f"YouTube fallback failed: {yt_err}")

        logger.info(f"Chat OK — ip={client_ip} user={request.user_id} len={len(message)}")

        # Increment daily usage counter
        try:
            from datetime import datetime, timezone
            from jose import jwt as _jose_jwt
            _auth_header = http_request.headers.get("Authorization", "")
            _token = _auth_header.replace("Bearer ", "")
            _payload = _jose_jwt.decode(
                _token,
                os.environ.get('JWT_SECRET', 'change-me-in-production-use-secret-manager'),
                algorithms=["HS256"],
                options={"verify_exp": False},
            )
            _team_id = _payload.get("team_id", request.user_id)
            if _payload.get("role") == "admin" or _team_id == "admin":
                raise Exception("skip — admin user")
            _today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            _cli = _firestore.AsyncClient(
                project=settings.GCP_PROJECT_ID,
                database=settings.FIRESTORE_DATABASE,
            )
            _ref = _cli.collection("adar_teams").document(_team_id)
            _doc = await _ref.get()
            _data = _doc.to_dict() if _doc.exists else {}
            _current = int(_data.get("usage_today") or 0)
            if _data.get("usage_reset_date", "") != _today:
                _current = 0
            await _ref.update({
                "usage_today":      _current + 1,
                "usage_reset_date": _today,
            })
            logger.info(f"Usage: team={_team_id} count={_current + 1}")
        except Exception as _e:
            logger.error(f"Usage increment failed: {_e}", exc_info=True)

        eval_result = None
        try:
            eval_enabled = os.environ.get("EVAL_ENABLED", "true").lower() == "true"
            if eval_enabled and len(response_text) > 30:
                eval_result = await evaluate_response(
                    question=message,
                    response=response_text,
                    # ── CHANGE 9: team_id uses DOMAIN (was hardcoded "arcl") ──
                    team_id=DOMAIN,
                    session_id=str(session.id),
                    user_id=request.user_id,
                    enabled=True,
                )
        except Exception as eval_err:
            logger.warning(f"Eval failed (non-fatal): {eval_err}")

        return ChatResponse(
            response=response_text,
            session_id=session.id,
            user_id=request.user_id,
            eval={
                "scores":      eval_result["scores"],
                "explanation": eval_result.get("explanation", ""),
            } if eval_result else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/sessions/{session_id}", response_model=SessionResponse)
async def get_session_endpoint(
    session_id: str,
    user_id: str,
    _auth: bool = Depends(_verify_api_key),
):
    try:
        session = await session_service.get_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return SessionResponse(session_id=session.id, state=session.state or {})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/api/sessions/{session_id}")
async def delete_session_endpoint(
    session_id: str,
    user_id: str,
    _auth: bool = Depends(_verify_api_key),
):
    try:
        await session_service.delete_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )
        return {"deleted": True, "session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# ── CHANGE 10: /api/tenant is domain-aware ───────────────────────────────────
_TENANT_INFO = {
    "arcl": {
        "tenant_id":     "arcl",
        "name":          "American Recreational Cricket League",
        "short_name":    "ARCL",
        "logo_url":      "",
        "primary_color": "#2EB87E",
        "accent_color":  "#EF9F27",
    },
    "geetabitan": {
        "tenant_id":     "geetabitan",
        "name":          "গীতবিতান — রবীন্দ্রনাথ ঠাকুরের গান",
        "short_name":    "Geetabitan",
        "logo_url":      "",
        "primary_color": "#8B1A1A",
        "accent_color":  "#D4A017",
    },
}

@app.get("/api/tenant")
async def get_tenant_info():
    """Return branding info for the frontend — resolved from DOMAIN env var."""
    return _TENANT_INFO.get(DOMAIN, _TENANT_INFO["arcl"])



@app.options("/api/demo/tts")
async def demo_tts_options():
    """CORS preflight for demo TTS — allow any origin."""
    from fastapi.responses import Response as _R
    r = _R()
    r.headers["Access-Control-Allow-Origin"]  = "*"
    r.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return r


@app.post("/api/demo/tts")
async def demo_tts(request: Request):
    """
    Text-to-speech for the Geetabitan demo.
    Uses GEETABITAN_TTS_API_KEY (restricted to texttospeech.googleapis.com).
    Voice: bn-BD-Standard-B (Bangladeshi male).
    Returns base64-encoded MP3. Cached in memory.
    """
    import base64, hashlib
    import httpx

    body = await request.json()
    raw_text = (body.get("text") or "").strip()
    text = raw_text[:1200].strip()
    if len(text) > 380:
        parts = []
        current = ""
        for word in text.split():
            candidate = f"{current} {word}".strip()
            if len(candidate) > 360 and current:
                parts.append(current.rstrip("।.!?") + "।")
                current = word
            else:
                current = candidate
        if current:
            parts.append(current.rstrip("।.!?") + "।")
        text = " ".join(parts)
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    if not hasattr(app.state, "tts_cache"):
        app.state.tts_cache = {}
    cache_key = hashlib.md5(text.encode()).hexdigest()
    if cache_key in app.state.tts_cache:
        from fastapi.responses import JSONResponse as _JR
        return _JR(
            content={"audio": app.state.tts_cache[cache_key], "cached": True},
            headers={"Access-Control-Allow-Origin": "*"},
        )

    # Use dedicated TTS key (restricted only to texttospeech.googleapis.com)
    api_key = os.environ.get("GEETABITAN_TTS_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="TTS API key not configured")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}",
                json={
                    "input": {"text": text},
                    "voice": {
                        "languageCode": "bn-IN",
                        "name":         "bn-IN-Chirp3-HD-Fenrir",  # best quality Bengali male
                    },
                    "audioConfig": {
                        "audioEncoding": "MP3",
                        # speakingRate and pitch not supported by Chirp3-HD
                    },
                },
            )
        if resp.status_code != 200:
            logger.error(f"TTS API {resp.status_code}: {resp.text[:200]}")
            raise HTTPException(status_code=502, detail=f"TTS error: {resp.text[:200]}")
        audio = resp.json().get("audioContent", "")
        app.state.tts_cache[cache_key] = audio
        from fastapi.responses import JSONResponse as _JR
        return _JR(
            content={"audio": audio, "cached": False},
            headers={"Access-Control-Allow-Origin": "*"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS error: {e}")
        raise HTTPException(status_code=500, detail=str(e))



@app.post("/api/stt")
async def speech_to_text(
    request: Request,
    team: dict = Depends(get_current_team),
):
    """
    Speech-to-text using Google Cloud Speech-to-Text v2 (Chirp 2 model).
    Accepts base64 WebM audio, returns Bengali transcription.
    Used as fallback when Web Speech API is unavailable (Firefox, iOS Safari).
    """
    import base64
    import httpx

    body  = await request.json()
    audio = body.get("audio", "")
    lang  = body.get("lang", "bn-IN")
    mime  = body.get("mime", "audio/webm")   # Firefox sends audio/ogg

    if not audio:
        raise HTTPException(status_code=400, detail="audio is required")

    logger.info(f"STT request: lang={lang} mime={mime} audio_len={len(audio)}")

    # Convert Safari's audio/mp4 (AAC) to FLAC for Google STT
    # Safari MediaRecorder only produces audio/mp4 which Google STT doesn't support
    if "mp4" in mime or "aac" in mime:
        try:
            import base64 as _b64
            import io
            from pydub import AudioSegment

            raw_bytes = _b64.b64decode(audio)
            seg       = AudioSegment.from_file(io.BytesIO(raw_bytes), format="mp4")
            seg       = seg.set_channels(1).set_frame_rate(16000)
            out_buf   = io.BytesIO()
            seg.export(out_buf, format="flac")
            audio     = _b64.b64encode(out_buf.getvalue()).decode()
            mime      = "audio/flac"
            logger.info(f"Converted mp4→flac, new audio_len={len(audio)}")
        except Exception as e:
            logger.error(f"Audio conversion failed: {e}")
            raise HTTPException(status_code=400, detail="Audio format not supported. Try Chrome or Firefox.")

    # Map MIME to Google STT encoding
    encoding_map = {
        "audio/webm":              "WEBM_OPUS",
        "audio/webm;codecs=opus":  "WEBM_OPUS",
        "audio/ogg":               "OGG_OPUS",
        "audio/ogg;codecs=opus":   "OGG_OPUS",
        "audio/flac":              "FLAC",
    }
    encoding = encoding_map.get(mime.split(";")[0].strip(), "WEBM_OPUS")

    # Use dedicated Speech key (has speech.googleapis.com allowed)
    api_key = (
        os.environ.get("GEETABITAN_SPEECH_API_KEY")
        or os.environ.get("GEETABITAN_TTS_API_KEY")
        or os.environ.get("GOOGLE_API_KEY", "")
    )
    if not api_key:
        raise HTTPException(status_code=500, detail="API key not configured")

    # Google Cloud Speech-to-Text v1 REST API
    payload = {
        "config": {
            "encoding":                   encoding,
            "languageCode":               lang,
            "enableAutomaticPunctuation": True,
        },
        "audio": {
            "content": audio,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://speech.googleapis.com/v1/speech:recognize?key={api_key}",
                json=payload,
            )
        if resp.status_code != 200:
            logger.error(f"STT API error {resp.status_code}: {resp.text[:500]}")
            raise HTTPException(status_code=502, detail=resp.text[:300])

        data        = resp.json()
        results     = data.get("results", [])
        transcript  = " ".join(
            r["alternatives"][0]["transcript"]
            for r in results
            if r.get("alternatives")
        )
        return {"text": transcript.strip()}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"STT error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "app":    settings.APP_NAME,
        "env":    settings.APP_ENV,
        "model":  settings.ADK_MODEL,
        "domain": DOMAIN,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=settings.APP_ENV == "development",
    )
