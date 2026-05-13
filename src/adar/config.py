"""
src/adar/config.py
==================
Changes from original:
  - Added DOMAIN env var (default: arcl)
  - FIRESTORE_DATABASE now resolves per domain
  - Added APP_NAME, APP_ENV, PORT env vars
  - Added per-domain Firestore collection names
  - Added OFFTOPIC_GUARD dict with full raag/taal keyword sets for geetabitan
  - Added Settings class so existing code using `settings.X` continues to work
  All original ARCL values are preserved and unchanged.
"""

import os

# ── Google / GCP ──────────────────────────────────────────────────────────────
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "bdas-493785")
ADK_MODEL      = os.getenv("ADK_MODEL", "gemini-2.5-flash")
EVAL_ENABLED   = os.getenv("EVAL_ENABLED", "true").lower() == "true"

# ── Domain selector ───────────────────────────────────────────────────────────
DOMAIN = os.getenv("DOMAIN", "arcl")

# ── Firestore database (one per domain) ───────────────────────────────────────
_FIRESTORE_DEFAULTS = {
    "arcl":       "tigers-arcl",
    "geetabitan": "geetabitan-db",
}
FIRESTORE_DATABASE = os.getenv(
    "FIRESTORE_DATABASE",
    _FIRESTORE_DEFAULTS.get(DOMAIN, "tigers-arcl"),
)

# ── Session DB ────────────────────────────────────────────────────────────────
SESSION_DB_URL = os.getenv("SESSION_DB_URL", "sqlite+aiosqlite:///./sessions.db")

# ── Auth ──────────────────────────────────────────────────────────────────────
JWT_SECRET     = os.getenv("JWT_SECRET", "change-me-in-production")
ADMIN_EMAIL    = os.getenv("ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

# ── Stripe ────────────────────────────────────────────────────────────────────
STRIPE_SECRET_KEY      = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET  = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_BASIC     = os.getenv("STRIPE_PRICE_BASIC", "")
STRIPE_PRICE_STANDARD  = os.getenv("STRIPE_PRICE_STANDARD", "")
STRIPE_PRICE_UNLIMITED = os.getenv("STRIPE_PRICE_UNLIMITED", "")
FRONTEND_URL           = os.getenv("FRONTEND_URL", "http://localhost:5173")

# ── App identity ──────────────────────────────────────────────────────────────
_APP_NAME_DEFAULTS = {
    "arcl":       "adar-arcl-api",
    "geetabitan": "adar-geetabitan-api",
}
APP_NAME = os.getenv("APP_NAME", _APP_NAME_DEFAULTS.get(DOMAIN, "adar-api"))
APP_ENV  = os.getenv("APP_ENV", "development")
PORT     = int(os.getenv("PORT", "8040"))

# ── API key (domain-scoped) ───────────────────────────────────────────────────
ARCL_API_KEY       = os.getenv("ARCL_API_KEY", "")
GEETABITAN_API_KEY = os.getenv("GEETABITAN_API_KEY", "")
API_KEY = GEETABITAN_API_KEY if DOMAIN == "geetabitan" else ARCL_API_KEY

# ── Firestore collection names ────────────────────────────────────────────────
if DOMAIN == "geetabitan":
    FS_SONGS_COLLECTION    = "geetabitan_songs"
    FS_EVALS_COLLECTION    = "geetabitan_evals"
    FS_SESSIONS_COLLECTION = "geetabitan_sessions"
else:
    # Original ARCL names kept exactly as they were — so existing
    # domains/arcl/tools/*.py imports continue to work with no changes.
    ARCL_RULES_COLLECTION          = os.getenv("ARCL_RULES_COLLECTION",          "arcl_rules")
    ARCL_FAQ_COLLECTION            = os.getenv("ARCL_FAQ_COLLECTION",            "arcl_faq")
    ARCL_PLAYERS_COLLECTION        = os.getenv("ARCL_PLAYERS_COLLECTION",        "arcl_players")
    ARCL_PLAYER_SEASON_COLLECTION  = os.getenv("ARCL_PLAYER_SEASON_COLLECTION",  "arcl_player_seasons")
    ARCL_TEAMS_COLLECTION          = os.getenv("ARCL_TEAMS_COLLECTION",          "arcl_teams")
    ARCL_MATCHES_COLLECTION        = os.getenv("ARCL_MATCHES_COLLECTION",        "arcl_matches")
    ARCL_SCHEDULE_COLLECTION       = os.getenv("ARCL_SCHEDULE_COLLECTION",       "arcl_schedule")
    ARCL_STANDINGS_COLLECTION      = os.getenv("ARCL_STANDINGS_COLLECTION",      "arcl_standings")
    FS_EVALS_COLLECTION            = "arcl_evals"

    # ── Season reference data ─────────────────────────────────────────────────
    # Maps numeric season IDs (as used in arcl.org URLs) to human-readable names.
    # Update this dict whenever a new ARCL season is added.
    ARCL_SEASON_MAP: dict = {
        69: "Spring 2026",
        68: "Fall 2025",
        67: "Spring 2025",
        66: "Fall 2024",
        65: "Spring 2024",
    }

    # Reverse lookup: season name → season ID
    ARCL_SEASON_NAME_TO_ID: dict = {v: k for k, v in {
        69: "Spring 2026",
        68: "Fall 2025",
        67: "Spring 2025",
        66: "Fall 2024",
        65: "Spring 2024",
    }.items()}

    # ── Scrape pages ──────────────────────────────────────────────────────────
    # List of arcl.org page paths the ingestion scraper visits.
    # league_id 2–13 covers all active ARCL divisions.
    ARCL_SCRAPE_PAGES: list = [
        f"/Pages/UI/DivHome.aspx?league_id={lid}&season_id={sid}"
        for lid in range(2, 14)
        for sid in [69]   # extend list for multi-season scrapes
    ]

    # ── CricClubs live-data URLs ─────────────────────────────────────────────
    # Used by src/adar/tools/live_tools.py to fetch live standings/schedule/results.
    # Override via env vars if your CricClubs club ID or league slug changes.
    _CC_BASE = os.getenv("CRICCLUBS_BASE_URL", "https://cricclubs.com")
    _CC_CLUB = os.getenv("CRICCLUBS_CLUB_ID",  "5693")   # ARCL club ID on CricClubs

    CRICCLUBS_STANDINGS = os.getenv(
        "CRICCLUBS_STANDINGS",
        f"{_CC_BASE}/ARCL/listMatches.do?league_id=0&clubId={_CC_CLUB}",
    )
    CRICCLUBS_SCHEDULE  = os.getenv(
        "CRICCLUBS_SCHEDULE",
        f"{_CC_BASE}/ARCL/listUpcomingMatches.do?league_id=0&clubId={_CC_CLUB}",
    )
    CRICCLUBS_RESULTS   = os.getenv(
        "CRICCLUBS_RESULTS",
        f"{_CC_BASE}/ARCL/listMatches.do?league_id=0&clubId={_CC_CLUB}",
    )

    # FS_* aliases — same values, available if new code prefers the prefix
    FS_RULES_COLLECTION         = ARCL_RULES_COLLECTION
    FS_FAQ_COLLECTION           = ARCL_FAQ_COLLECTION
    FS_PLAYERS_COLLECTION       = ARCL_PLAYERS_COLLECTION
    FS_PLAYER_SEASON_COLLECTION = ARCL_PLAYER_SEASON_COLLECTION
    FS_TEAMS_COLLECTION         = ARCL_TEAMS_COLLECTION
    FS_MATCHES_COLLECTION       = ARCL_MATCHES_COLLECTION
    FS_SCHEDULE_COLLECTION      = ARCL_SCHEDULE_COLLECTION
    FS_STANDINGS_COLLECTION     = ARCL_STANDINGS_COLLECTION

# ── Off-topic keyword guard (domain-aware) ────────────────────────────────────
# main.py reads three keys per domain:
#   off_topic  — denylist: if ANY of these appear in the message …
#   hints      — allowlist: … AND NONE of these appear → reject
#   reject_msg — the reply sent when the guard fires
OFFTOPIC_GUARD: dict = {
    "arcl": {
        "off_topic": [
            "python", "javascript", "java", "ruby", "golang",
            "write a program", "write code", "write a script",
            "recipe", "cooking", "weather", "stock market",
            "crypto", "bitcoin", "movie", "music", "song", "lyrics",
            "joke", "poem", "write an essay", "write a story",
            "translate", "machine learning tutorial",
            "sql injection", "how to hack", "calculus", "algebra",
        ],
        "hints": [
            "arcl", "cricket", "batting", "bowling", "wicket", "runs",
            "overs", "innings", "umpire", "wide", "lbw", "caught",
            "bowled", "dismissed", "scorecard", "schedule", "standing",
            "division", "season", "player", "team", "match", "league",
            "spring", "summer", "rule", "eligible", "stats", "average",
            "strike rate", "economy", "agomoni", "tigers", "spring 2026",
        ],
        "reject_msg": (
            "I'm Adar, the ARCL cricket assistant. I can only help with "
            "ARCL cricket questions — player stats, team performance, rules, "
            "schedules and scorecards. What would you like to know about ARCL cricket?"
        ),
    },
    "geetabitan": {
        "off_topic": [
            "python", "javascript", "java", "write a program", "write code",
            "recipe", "cooking", "weather", "stock market", "crypto", "bitcoin",
            "cricket", "football", "soccer", "how to hack", "sql injection",
            "calculus", "algebra", "write an essay", "machine learning tutorial",
        ],
        "hints": [
            # Bengali — general
            "গান", "গীত", "রবীন্দ্র", "ঠাকুর", "পর্যায়", "পূজা",
            "প্রেম", "স্বদেশ", "প্রকৃতি", "বিচিত্র", "আনুষ্ঠানিক",
            "গীতবিতান", "স্তবক", "সুর", "কবিতা", "সংগীত",
            # Bengali — raag names
            "রাগ", "ভৈরবী", "বাউল", "কাফি", "ইমন", "পিলু", "বেহাগ",
            "খাম্বাজ", "ভূপালি", "কীর্তন", "মিশ্র", "দরবারি",
            "মালকোষ", "কেদার", "শ্রী", "ভৈরব", "তোড়ি", "সারঙ্গ",
            "বিভাস", "বসন্ত", "ললিত", "জয়জয়ন্তী", "হামির",
            "কল্যাণ", "পূরবী", "আসাবরী", "দেশ", "পহাড়ি",
            # Bengali — taal names
            "তাল", "দাদরা", "কাহারবা", "তিনতাল", "রূপকড়া",
            "ঝাঁপতাল", "একতাল", "তেওরা", "ঝুমরা", "চৌতাল",
            "মাত্রা", "বিভাগ", "ছন্দ", "ত্রিতাল", "দীপচন্দী",
            # Bengali — summary / meaning words
            "মানে", "অর্থ", "প্রেক্ষাপট", "আবেগ", "চিত্রকল্প",
            "ইতিহাস", "রূপক", "ব্যাখ্যা", "সারসংক্ষেপ",
            # Roman / English
            "song", "tagore", "rabindra", "geetabitan", "paryay",
            "raag", "raga", "taal", "taala", "puja", "prem",
            "swadesh", "prakriti", "stanza", "bhairavi", "baul",
            "kafi", "emon", "pilu", "behag", "bhupali", "dadra",
            "kaharwa", "teentaal", "rupakda", "jhaptaal", "ektaal",
            "meaning", "context", "emotion", "imagery", "summary",
        ],
        "reject_msg": (
            "আমি শুধু রবীন্দ্রসঙ্গীত ও গীতবিতান বিষয়ক প্রশ্নের উত্তর দিতে পারি।"
        ),
    },
}


# ── Settings object ───────────────────────────────────────────────────────────
# Provides attribute-style access (`settings.X`) so all existing imports of
# `from src.adar.config import settings` continue to work without change.
# New code can import the module-level constants directly instead.

class _Settings:
    # App identity
    APP_NAME: str  = APP_NAME
    APP_ENV:  str  = APP_ENV
    PORT:     int  = PORT

    # Google / GCP
    GOOGLE_API_KEY: str  = GOOGLE_API_KEY
    GCP_PROJECT_ID: str  = GCP_PROJECT_ID
    ADK_MODEL:      str  = ADK_MODEL
    EVAL_ENABLED:   bool = EVAL_ENABLED

    # Domain
    DOMAIN: str = DOMAIN

    # Firestore
    FIRESTORE_DATABASE: str = FIRESTORE_DATABASE

    # Session
    SESSION_DB_URL: str = SESSION_DB_URL

    # Auth
    JWT_SECRET:     str = JWT_SECRET
    ADMIN_EMAIL:    str = ADMIN_EMAIL
    ADMIN_PASSWORD: str = ADMIN_PASSWORD

    # Stripe
    STRIPE_SECRET_KEY:      str = STRIPE_SECRET_KEY
    STRIPE_WEBHOOK_SECRET:  str = STRIPE_WEBHOOK_SECRET
    STRIPE_PRICE_BASIC:     str = STRIPE_PRICE_BASIC
    STRIPE_PRICE_STANDARD:  str = STRIPE_PRICE_STANDARD
    STRIPE_PRICE_UNLIMITED: str = STRIPE_PRICE_UNLIMITED
    FRONTEND_URL:           str = FRONTEND_URL

    # API keys
    ARCL_API_KEY:       str = ARCL_API_KEY
    GEETABITAN_API_KEY: str = GEETABITAN_API_KEY
    API_KEY:            str = API_KEY

    # ARCL collection names (only meaningful when DOMAIN == "arcl")
    ARCL_RULES_COLLECTION:         str = ARCL_RULES_COLLECTION         if DOMAIN == "arcl" else ""
    ARCL_FAQ_COLLECTION:           str = ARCL_FAQ_COLLECTION           if DOMAIN == "arcl" else ""
    ARCL_PLAYERS_COLLECTION:       str = ARCL_PLAYERS_COLLECTION       if DOMAIN == "arcl" else ""
    ARCL_PLAYER_SEASON_COLLECTION: str = ARCL_PLAYER_SEASON_COLLECTION if DOMAIN == "arcl" else ""
    ARCL_TEAMS_COLLECTION:         str = ARCL_TEAMS_COLLECTION         if DOMAIN == "arcl" else ""
    ARCL_MATCHES_COLLECTION:       str = ARCL_MATCHES_COLLECTION       if DOMAIN == "arcl" else ""
    ARCL_SCHEDULE_COLLECTION:      str = ARCL_SCHEDULE_COLLECTION      if DOMAIN == "arcl" else ""
    ARCL_STANDINGS_COLLECTION:     str = ARCL_STANDINGS_COLLECTION     if DOMAIN == "arcl" else ""

    # ARCL season + scrape data (only meaningful when DOMAIN == "arcl")
    ARCL_SEASON_MAP:        dict = ARCL_SEASON_MAP        if DOMAIN == "arcl" else {}
    ARCL_SEASON_NAME_TO_ID: dict = ARCL_SEASON_NAME_TO_ID if DOMAIN == "arcl" else {}
    ARCL_SCRAPE_PAGES:      list = ARCL_SCRAPE_PAGES      if DOMAIN == "arcl" else []

    # CricClubs live-data URLs (only meaningful when DOMAIN == "arcl")
    CRICCLUBS_STANDINGS: str = CRICCLUBS_STANDINGS if DOMAIN == "arcl" else ""
    CRICCLUBS_SCHEDULE:  str = CRICCLUBS_SCHEDULE  if DOMAIN == "arcl" else ""
    CRICCLUBS_RESULTS:   str = CRICCLUBS_RESULTS   if DOMAIN == "arcl" else ""


settings = _Settings()