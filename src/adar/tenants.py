"""
tenants.py — Multi-tenant support for Adar.

Each tenant is a cricket league with its own:
- Firestore collection prefix (tenant_id)
- Branding (name, logo, colors)
- Allowed origins (CORS)
- API key
- Scraping config (base URL, league IDs, season map)
"""
from dataclasses import dataclass, field
from typing import Optional
from google.cloud import firestore
from config import settings

TENANTS_COLLECTION = "adar_tenants"


@dataclass
class TenantConfig:
    tenant_id: str              # e.g. "arcl", "nwcl", "bcl"
    name: str                   # e.g. "American Recreational Cricket League"
    short_name: str             # e.g. "ARCL"
    base_url: str               # e.g. "https://www.arcl.org"
    api_key: str                # per-tenant API key
    allowed_origins: list[str]  # CORS origins for this tenant's frontend
    logo_url: str = ""
    primary_color: str = "#2EB87E"
    accent_color: str = "#EF9F27"
    active: bool = True
    # Collection names — auto-derived from tenant_id
    rules_collection: str = ""
    faq_collection: str = ""
    players_collection: str = ""
    teams_collection: str = ""
    player_seasons_collection: str = ""
    polls_collection: str = ""

    def __post_init__(self):
        # Auto-set collection names from tenant_id
        self.rules_collection          = f"{self.tenant_id}_rules"
        self.faq_collection            = f"{self.tenant_id}_faq"
        self.players_collection        = f"{self.tenant_id}_players"
        self.teams_collection          = f"{self.tenant_id}_teams"
        self.player_seasons_collection = f"{self.tenant_id}_player_seasons"
        self.polls_collection          = f"{self.tenant_id}_polls"


# ── Built-in tenant registry ──────────────────────────────────────────────────
# Loaded from Firestore at startup; hardcoded defaults for dev

DEFAULT_TENANTS: dict[str, TenantConfig] = {
    "arcl": TenantConfig(
        tenant_id="arcl",
        name="American Recreational Cricket League",
        short_name="ARCL",
        base_url="https://www.arcl.org",
        api_key="",  # Set via env/Secret Manager
        allowed_origins=[
            "https://arcl.tigers.agomoniai.com",
            "https://www.arcl.tigers.agomoniai.com",
            "https://adar.agomoniai.com",
            "http://localhost:5173",
            "http://localhost:3000",
        ],
        primary_color="#2EB87E",
        accent_color="#EF9F27",
    ),
    # Add new leagues here:
    # "nwcl": TenantConfig(
    #     tenant_id="nwcl",
    #     name="Northwest Cricket League",
    #     short_name="NWCL",
    #     base_url="https://www.nwcl.org",
    #     api_key="",
    #     allowed_origins=["https://nwcl.adar.agomoniai.com"],
    #     primary_color="#1565C0",
    #     accent_color="#FFA000",
    # ),
}

# In-memory cache — loaded at startup
_tenant_cache: dict[str, TenantConfig] = {}


async def load_tenants():
    """Load tenants from Firestore into memory cache."""
    global _tenant_cache
    _tenant_cache = dict(DEFAULT_TENANTS)  # start with defaults

    try:
        db = firestore.AsyncClient(
            project=settings.GCP_PROJECT_ID,
            database=settings.FIRESTORE_DATABASE,
        )
        async for doc in db.collection(TENANTS_COLLECTION).stream():
            data = doc.to_dict()
            tid = data.get("tenant_id")
            if tid and data.get("active", True):
                _tenant_cache[tid] = TenantConfig(**{
                    k: v for k, v in data.items()
                    if k in TenantConfig.__dataclass_fields__
                })
    except Exception as e:
        pass  # use defaults if Firestore unavailable


def get_tenant(tenant_id: str) -> Optional[TenantConfig]:
    return _tenant_cache.get(tenant_id)


def get_tenant_by_origin(origin: str) -> Optional[TenantConfig]:
    """Find which tenant owns a given origin URL."""
    for tenant in _tenant_cache.values():
        if origin in tenant.allowed_origins:
            return tenant
    return None


def get_tenant_by_api_key(api_key: str) -> Optional[TenantConfig]:
    """Find tenant by API key."""
    for tenant in _tenant_cache.values():
        if tenant.api_key and tenant.api_key == api_key:
            return tenant
    return None


def all_allowed_origins() -> list[str]:
    """All origins across all tenants — for CORS middleware."""
    origins = []
    for tenant in _tenant_cache.values():
        origins.extend(tenant.allowed_origins)
    return list(set(origins))


async def register_tenant(config: TenantConfig):
    """Save a new tenant to Firestore."""
    db = firestore.AsyncClient(
        project=settings.GCP_PROJECT_ID,
        database=settings.FIRESTORE_DATABASE,
    )
    data = {k: v for k, v in config.__dict__.items()}
    await db.collection(TENANTS_COLLECTION).document(config.tenant_id).set(data)
    _tenant_cache[config.tenant_id] = config