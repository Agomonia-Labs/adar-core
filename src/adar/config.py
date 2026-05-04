import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "adar-arcl-api"
    APP_ENV: str = "development"
    PORT: int = int(os.environ.get('PORT', 8040))

    GOOGLE_API_KEY: str = ""
    ADK_MODEL: str = "gemini-2.5-flash"

    GCP_PROJECT_ID: str = ""
    FIRESTORE_DATABASE: str = "adar-arcl"
    SESSION_DB_URL: str = "sqlite+aiosqlite:///./arcl_sessions.db"

    ARCL_API_KEY: str = ""           # Set via Secret Manager in production
    ARCL_BASE_URL: str = "https://arcl.org"
    CRICCLUBS_URL: str = "https://cricclubs.com/ARCL"
    CRICCLUBS_CLUB_ID: str = "992"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

os.environ["GOOGLE_API_KEY"] = settings.GOOGLE_API_KEY
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "false"

# ── Firestore collections (ARCL defaults) ────────────────────────────────────
ARCL_RULES_COLLECTION          = "arcl_rules"
ARCL_PLAYERS_COLLECTION        = "arcl_players"
ARCL_TEAMS_COLLECTION          = "arcl_teams"
ARCL_FAQ_COLLECTION            = "arcl_faq"
ARCL_PLAYER_SEASON_COLLECTION  = "arcl_player_seasons"
ARCL_QUERY_EXAMPLES_COLLECTION = "arcl_query_examples"


def get_collections(tenant_id: str = "arcl") -> dict:
    """
    Return Firestore collection names for a given tenant.
    All collections are prefixed with tenant_id so tenants are fully isolated.

    Usage:
        cols = get_collections("arcl")
        cols["teams"]   # "arcl_teams"
        cols["players"] # "arcl_players"

        cols = get_collections("nwcl")
        cols["teams"]   # "nwcl_teams"
    """
    p = tenant_id.lower().strip()
    return {
        "rules":          f"{p}_rules",
        "faq":            f"{p}_faq",
        "players":        f"{p}_players",
        "teams":          f"{p}_teams",
        "player_seasons": f"{p}_player_seasons",
        "polls":          f"{p}_polls",
        "schedules":      f"{p}_team_schedules",
    }

# ── Pages to scrape ──────────────────────────────────────────────────────────
ARCL_SCRAPE_PAGES = [
    {"url": "https://arcl.org/Pages/Content/Rules.aspx",       "type": "rules", "league": "men"},
    {"url": "https://arcl.org/Docs/Mens_League_Rules.htm",     "type": "rules", "league": "men"},
    {"url": "https://arcl.org/Docs/Womens_League_Rules.htm",   "type": "rules", "league": "women"},
    {"url": "https://arcl.org/Pages/Content/FAQ.aspx",         "type": "faq",   "league": "general"},
    {"url": "https://arcl.org/Pages/Content/AboutUs.aspx",     "type": "about", "league": "general"},
]

CRICCLUBS_STANDINGS = "https://cricclubs.com/ARCL/viewPointsTable.do?clubId=992"
CRICCLUBS_SCHEDULE  = "https://cricclubs.com/ARCL/viewSchedule.do?clubId=992"
CRICCLUBS_RESULTS   = "https://cricclubs.com/ARCL/viewMatches.do?clubId=992"

# ── Season ID to Season Name mapping ────────────────────────────────────────
# Confirmed from arcl.org URLs and page titles.
# Key corrections: each season is +1 from previous guesses.
ARCL_SEASON_MAP: dict[int, str] = {
    69: "Spring 2026",      # confirmed current season
    68: "Winter 2026",      # if it exists
    67: "Fall 2025",
    66: "Summer 2025",      # confirmed
    65: "Spring 2025",      # confirmed
    64: "Winter 2024",
    63: "Summer 2024",      # confirmed (was wrongly mapped to Spring 2025)
    62: "Spring 2024",
    61: "Fall 2023",
    60: "Summer 2023",      # confirmed (was wrongly mapped to Summer 2024)
    59: "Spring 2023",
    58: "Fall 2022",
    57: "Summer 2022",
    56: "Spring 2022",
    55: "Fall 2021",
    54: "Summer 2021",
    53: "Spring 2021",
    52: "Fall 2020",
    51: "Spring 2020 (cancelled — COVID-19)",
    50: "Fall 2019",
    49: "Summer 2019",
    48: "Spring 2019",
    47: "Fall 2018",
    46: "Summer 2018",
    45: "Spring 2018",
    44: "Fall 2017",
    43: "Summer 2017",
    42: "Spring 2017",
}

# Reverse map — season name -> season_id
ARCL_SEASON_NAME_TO_ID: dict[str, int] = {v: k for k, v in ARCL_SEASON_MAP.items()}
# Explicit confirmed aliases
ARCL_SEASON_NAME_TO_ID.update({
    "Spring 2026":  69,
    "Fall 2025":    67,
    "Summer 2025":  66,
    "Spring 2025":  65,
    "Summer 2024":  63,
    "Spring 2024":  62,
    "Fall 2023":    61,
    "Summer 2023":  60,
    "Spring 2023":  59,
    "Fall 2022":    58,
    "Summer 2022":  57,
    "Spring 2022":  56,
    "Fall 2021":    55,
    "Summer 2021":  54,
    "Spring 2019":  48,
    "Summer 2019":  49,
    "Fall 2019":    50,
    "Spring 2018":  45,
    "Summer 2018":  46,
    "Fall 2018":    47,
})