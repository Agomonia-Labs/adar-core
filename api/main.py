import os
from dotenv import load_dotenv
# Only load .env in local development — never in production
if os.environ.get("APP_ENV") != "production":
    load_dotenv(override=True)

import uuid
import time
import logging
from typing import Optional
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader

from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai.types import Content, Part

from src.adar.agents.agents import build_arcl_orchestrator
from google.cloud import firestore as _firestore
from api.routes.polls import router as polls_router
from api.routes.auth import router as auth_router, get_current_team
from api.routes.admin import router as admin_router
from api.routes.payments import router as payments_router
from evaluation.judge import evaluate_response
from api.schemas import ChatRequest, ChatResponse, SessionResponse
from src.adar.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

session_service: DatabaseSessionService = None
arcl_orchestrator = None
APP_NAME = settings.APP_NAME

# ── Rate limiting ────────────────────────────────────────────────────────────
# Simple in-memory rate limiter: max 20 requests per minute per IP
RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW   = 60  # seconds
_rate_buckets: dict = defaultdict(list)


def _check_rate_limit(ip: str) -> bool:
    """Returns True if request is allowed, False if rate limited."""
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    # Remove old entries
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
    If ARCL_API_KEY is not set in config, auth is skipped (dev mode).
    Also accepts requests with no key when JWT auth will handle it separately.
    """
    expected = getattr(settings, "ARCL_API_KEY", None)
    if not expected:
        return True  # No key configured — allow all
    if not api_key:
        return True  # No key sent — allow (JWT auth handles identity)
    if api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global session_service, arcl_orchestrator
    logger.info("Starting Adar ARCL API...")
    session_service = DatabaseSessionService(db_url=settings.SESSION_DB_URL)
    arcl_orchestrator = build_arcl_orchestrator()
    logger.info(f"ARCL orchestrator ready — model: {settings.ADK_MODEL}")
    yield
    logger.info("Shutting down Adar ARCL API...")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Adar ARCL API",
    description="Multi-agent AI assistant for the American Recreational Cricket League",
    version="1.0.0",
    lifespan=lifespan,
    # Disable docs in production to avoid exposing schema
    docs_url="/docs" if getattr(settings, "APP_ENV", "production") != "production" else None,
    redoc_url=None,
)

# Register routers


# Determine origins based on environment
_PROD_ORIGINS = [
    "https://arcl.tigers.agomoniai.com",
    "https://www.arcl.tigers.agomoniai.com",
    "https://adar.agomoniai.com",
    "https://www.adar.agomoniai.com",
]
_DEV_ORIGINS = [
    "http://localhost:5173", "http://localhost:5174",
    "http://localhost:6001", "http://localhost:3000",
    "http://127.0.0.1:5173", "http://127.0.0.1:6001",
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

    # Reset usage if it's a new day
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

    # Quota by plan if not explicitly set
    PLAN_QUOTAS = {"basic": 50, "standard": 200, "unlimited": 1000, "complimentary": 200}
    plan = data.get("subscription_plan", "standard")
    daily_quota = (
        data.get("daily_quota") or
        data.get("quota_daily") or
        PLAN_QUOTAS.get(plan, 200)
    )
    logger.info(f"Usage check: team={team_id} used={usage_today} quota={daily_quota}")
    return {
        "used_today": int(usage_today or 0),
        "daily_quota": int(daily_quota or 200),
        "resets_at": "midnight UTC",
        "plan": plan,
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

    # Sanitise user_id — only allow alphanumeric + underscore/dash
    import re
    if not re.match(r'^[a-zA-Z0-9_\-]{1,64}$', request.user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id format")

    try:
        session = await get_or_create_session(request.user_id, request.session_id)

        runner = Runner(
            agent=arcl_orchestrator,
            app_name=APP_NAME,
            session_service=session_service,
        )

        # ── Off-topic guard — block non-ARCL questions cheaply ──
        OFF_TOPIC = [
            "python","javascript","java","ruby","golang","write a program",
            "write code","write a script","recipe","cooking","weather","stock market",
            "crypto","bitcoin","movie","music","song","lyrics","joke","poem",
            "write an essay","write a story","translate","machine learning tutorial",
            "sql injection","how to hack","calculus","algebra",
        ]
        ARCL_HINTS = [
            "arcl","cricket","batting","bowling","wicket","runs","overs","innings",
            "umpire","wide","lbw","caught","bowled","dismissed","scorecard",
            "schedule","standing","division","season","player","team","match",
            "league","spring","summer","rule","eligible","stats","average",
            "strike rate","economy","agomoni","tigers","spring 2026",
        ]
        msg_low = message.lower()
        if any(k in msg_low for k in OFF_TOPIC) and not any(k in msg_low for k in ARCL_HINTS):
            return ChatResponse(
                response="I'm Adar, the ARCL cricket assistant. I can only help with ARCL cricket questions — player stats, team performance, rules, schedules and scorecards. What would you like to know about ARCL cricket?",
                session_id=str(session.id),
                user_id=request.user_id,
                eval=None,
            )
        # ─────────────────────────────────────────────────────────

        user_message = Content(role="user", parts=[Part(text=message)])

        response_text = ""
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

        logger.info(f"Chat OK — ip={client_ip} user={request.user_id} len={len(message)}")

        # Run evaluation and include in response (async, best-effort)
        # Increment daily usage counter — fire and forget
        # Increment usage directly (awaited) — skip for admin
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
                "usage_today": _current + 1,
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
                    team_id="arcl",
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
            eval={"scores": eval_result["scores"], "explanation": eval_result["explanation"]}
                 if eval_result else None,
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


@app.get("/api/tenant")
async def get_tenant_info():
    """Return branding info for the frontend."""
    return {
        "tenant_id":     "arcl",
        "name":          "American Recreational Cricket League",
        "short_name":    "ARCL",
        "logo_url":      "",
        "primary_color": "#2EB87E",
        "accent_color":  "#EF9F27",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "env": settings.APP_ENV,
        "model": settings.ADK_MODEL,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=settings.APP_ENV == "development",
    )