import os
from dotenv import load_dotenv
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

from agents import build_arcl_orchestrator
from polls import router as polls_router
from auth import router as auth_router, get_current_team
from admin import router as admin_router
from payments import router as payments_router
from evaluation.judge import evaluate_response
from models import ChatRequest, ChatResponse, SessionResponse
from config import settings

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


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://arcl.tigers.agomoniai.com",
        "https://www.arcl.tigers.agomoniai.com",
        "https://adar.agomoniai.com",
        "https://www.adar.agomoniai.com",
        "http://localhost:6001",
        "http://localhost:3000",
        "http://127.0.0.1:6001",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["POST", "GET", "DELETE", "OPTIONS", "PUT"],
    allow_headers=["Content-Type", "X-API-Key", "X-Tenant-ID", "Authorization"],
)


app.include_router(polls_router)
app.include_router(auth_router)
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
        "main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=settings.APP_ENV == "development",
    )