"""Least-privilege guest access for the public ADAR Geetabitan experience."""

import asyncio
import os
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from jose import jwt

from api.routes.auth import JWT_ALGORITHM, _jwt_secret, bearer_scheme, decode_token
from src.adar.config import settings


router = APIRouter(prefix="/api/geetabitan/guest", tags=["geetabitan-guest"])

GUEST_ROLE = "geetabitan_guest"
GUEST_TOKEN_USE = "geetabitan_live_experience"
GUEST_TOKEN_TTL_SECONDS = 30 * 60
GUEST_SESSION_WINDOW_SECONDS = 10 * 60
GUEST_SESSION_WINDOW_LIMIT = 20
GUEST_QUERY_WINDOW_SECONDS = 60
GUEST_QUERY_WINDOW_LIMIT = 12
GUEST_MAX_SESSION_MESSAGES = 20

DEFAULT_ALLOWED_ORIGINS = {
    "https://labs.agomoniai.com",
    "https://www.labs.agomoniai.com",
    "http://localhost:4177",
    "http://127.0.0.1:4177",
}

EXAMPLE_QUESTIONS = [
    "আমার সোনার বাংলা গানটি খুঁজুন",
    "ভৈরবী রাগের গান দেখাও",
    "দাদরা তালের গান কী কী?",
    "স্বদেশ পর্যায়ের গানগুলো দেখাও",
    "একলা চলো রে গানের অর্থ কী?",
    "বর্ষার গান দেখাও",
]

SUPPORTED_LANGUAGES = [
    {"code": "bn-IN", "label": "বাংলা"},
    {"code": "en-US", "label": "English"},
]

_session_windows: dict[str, deque[float]] = defaultdict(deque)
_query_windows: dict[str, deque[float]] = defaultdict(deque)
_voice_windows: dict[str, deque[float]] = defaultdict(deque)
_message_counts: dict[str, int] = defaultdict(int)
_limit_lock = asyncio.Lock()


def _require_guest_enabled() -> None:
    if settings.DOMAIN != "geetabitan":
        raise HTTPException(status_code=404, detail="Not available for this domain")
    if os.environ.get("GEETABITAN_GUEST_ACCESS_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=503, detail="Geetabitan guest access is not enabled")


def _allowed_origins() -> set[str]:
    configured = os.environ.get("GEETABITAN_GUEST_ALLOWED_ORIGINS", "")
    return DEFAULT_ALLOWED_ORIGINS | {
        value.strip().rstrip("/") for value in configured.split(",") if value.strip()
    }


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limit_key(request: Request) -> str:
    origin = request.headers.get("origin", "command-line").rstrip("/").lower()
    return f"{origin}|{_client_ip(request)}"


def _enforce_allowed_origin(request: Request) -> None:
    origin = request.headers.get("origin", "").rstrip("/")
    if origin and origin not in _allowed_origins():
        raise HTTPException(
            status_code=403,
            detail="The Geetabitan live experience must run from Agomonia Labs or an approved local origin",
        )


async def _consume_window(
    windows: dict[str, deque[float]],
    key: str,
    window_seconds: int,
    limit: int,
    message: str,
) -> None:
    now = time.monotonic()
    cutoff = now - window_seconds
    async with _limit_lock:
        window = windows[key]
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= limit:
            retry_after = max(1, int(window[0] + window_seconds - now) + 1)
            raise HTTPException(status_code=429, detail=message, headers={"Retry-After": str(retry_after)})
        window.append(now)


async def enforce_session_rate_limit(request: Request) -> None:
    await _consume_window(
        _session_windows,
        _rate_limit_key(request),
        GUEST_SESSION_WINDOW_SECONDS,
        GUEST_SESSION_WINDOW_LIMIT,
        "Too many guest sessions. Please reuse the current session or try again later.",
    )


async def enforce_query_rate_limit(guest: dict) -> None:
    token_id = str(guest.get("jti") or guest.get("sub") or "unknown")
    await _consume_window(
        _query_windows,
        token_id,
        GUEST_QUERY_WINDOW_SECONDS,
        GUEST_QUERY_WINDOW_LIMIT,
        "Too many questions. Please wait a moment before asking again.",
    )
    async with _limit_lock:
        if _message_counts[token_id] >= GUEST_MAX_SESSION_MESSAGES:
            raise HTTPException(
                status_code=429,
                detail="This guest session has reached its question limit. Start a new experience to continue.",
            )
        _message_counts[token_id] += 1


async def enforce_voice_rate_limit(guest: dict) -> None:
    if os.environ.get("GEETABITAN_GUEST_VOICE_ENABLED", "true").lower() != "true":
        raise HTTPException(status_code=503, detail="Geetabitan guest voice is not enabled")
    token_id = str(guest.get("jti") or guest.get("sub") or "unknown")
    await _consume_window(
        _voice_windows,
        f"voice:{token_id}",
        GUEST_QUERY_WINDOW_SECONDS,
        20,
        "Too many voice requests. Please wait a moment before trying again.",
    )


def issue_guest_token() -> tuple[str, str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=GUEST_TOKEN_TTL_SECONDS)
    guest_id = f"geetabitan_guest_{uuid.uuid4().hex[:24]}"
    token = jwt.encode(
        {
            "team_id": guest_id,
            "sub": guest_id,
            "role": GUEST_ROLE,
            "status": "active",
            "domain": "geetabitan",
            "token_use": GUEST_TOKEN_USE,
            "scope": ["geetabitan:query", "geetabitan:voice", "geetabitan:session"],
            "jti": uuid.uuid4().hex,
            "iat": now,
            "exp": expires_at,
        },
        _jwt_secret(),
        algorithm=JWT_ALGORITHM,
    )
    return token, guest_id, expires_at


async def get_geetabitan_guest(credentials=Depends(bearer_scheme)) -> dict:
    _require_guest_enabled()
    if not credentials:
        raise HTTPException(status_code=401, detail="Guest authentication required")
    payload = decode_token(credentials.credentials)
    if (
        payload.get("role") != GUEST_ROLE
        or payload.get("token_use") != GUEST_TOKEN_USE
        or payload.get("domain") != "geetabitan"
    ):
        raise HTTPException(status_code=403, detail="A Geetabitan guest token is required")
    return payload


@router.post("/session", status_code=201)
async def create_guest_session(request: Request, response: Response):
    _require_guest_enabled()
    _enforce_allowed_origin(request)
    await enforce_session_rate_limit(request)
    token, guest_id, expires_at = issue_guest_token()
    response.headers["Cache-Control"] = "no-store"
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": GUEST_TOKEN_TTL_SECONDS,
        "expires_at": expires_at.isoformat(),
        "guest_id": guest_id,
        "scope": ["geetabitan:query", "geetabitan:voice", "geetabitan:session"],
    }


@router.get("/capabilities")
async def get_guest_capabilities(guest: dict = Depends(get_geetabitan_guest)):
    return {
        "product": "ADAR Geetabitan",
        "domain": guest["domain"],
        "features": [
            "song search by title, lyric or theme",
            "raag, taal and paryay exploration",
            "meaning, context, emotion and imagery",
            "notation discovery",
            "Bengali text and voice conversation",
        ],
        "languages": SUPPORTED_LANGUAGES,
        "max_questions": GUEST_MAX_SESSION_MESSAGES,
        "voice_enabled": os.environ.get("GEETABITAN_GUEST_VOICE_ENABLED", "true").lower() == "true",
    }


@router.get("/examples")
async def get_guest_examples(guest: dict = Depends(get_geetabitan_guest)):
    return {"questions": EXAMPLE_QUESTIONS, "domain": guest["domain"]}


def clear_test_state() -> None:
    """Reset process-local rate-limit state for deterministic unit tests."""
    _session_windows.clear()
    _query_windows.clear()
    _voice_windows.clear()
    _message_counts.clear()
