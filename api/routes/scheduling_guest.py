"""Short-lived, least-privilege guest access for the public Front Desk demo.

Guest tokens are intentionally separate from customer and practice-staff
identity. They are restricted to configured demo practices, never expose
staff records, operational appointments, other customers' PII, or internal
telemetry, and write bookings to an isolated demo collection. The trace-flow
endpoint returns only a sanitized projection derived from those demo bookings.
"""
import asyncio
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from google.cloud import firestore
from jose import jwt
from pydantic import BaseModel, Field, field_validator

from api.routes.auth import JWT_ALGORITHM, _admin_email, _jwt_secret, bearer_scheme, decode_token
from src.adar.notify import (
    send_appointment_confirmation_email,
    send_appointment_cancelled_email,
    send_new_booking_notification_email,
    send_booking_cancelled_notification_email,
)
from src.adar.config import settings


router = APIRouter(prefix="/api/scheduling/guest", tags=["scheduling-guest"])

logger = logging.getLogger(__name__)

GUEST_ROLE = "scheduling_guest"
GUEST_TOKEN_USE = "front_desk_demo"
GUEST_TOKEN_TTL_SECONDS = 30 * 60
GUEST_BOOKING_TTL_HOURS = 24
GUEST_MAX_BOOKINGS = 5
GUEST_TOKEN_WINDOW_SECONDS = 10 * 60
GUEST_TOKEN_WINDOW_LIMIT = 20

GUEST_ALLOWED_ORIGINS = {
    "https://labs.agomoniai.com",
    "https://www.labs.agomoniai.com",
    "http://localhost:4177",
    "http://127.0.0.1:4177",
}

_token_windows: dict[str, deque[float]] = defaultdict(deque)
_token_lock = asyncio.Lock()

# ── Chat + voice rate limiting (mirrors api/routes/arcl_guest.py) ───────────
# The endpoints above (session/practices/providers/bookings) predate the
# mobile app's chat+voice "Ask ADAR" tab -- these limits exist so that tab
# can reuse the same guest token/session infrastructure with its own,
# separately-tuned quotas, the same way ARCL and Geetabitan guest chat do.
GUEST_QUERY_WINDOW_SECONDS = 60
GUEST_QUERY_WINDOW_LIMIT = 12
GUEST_MAX_SESSION_MESSAGES = 20
GUEST_VOICE_WINDOW_SECONDS = 60
GUEST_VOICE_WINDOW_LIMIT = 10

_query_windows: dict[str, deque[float]] = defaultdict(deque)
_voice_windows: dict[str, deque[float]] = defaultdict(deque)
_message_counts: dict[str, int] = defaultdict(int)

# Voice mode covers English plus the languages ADAR's other public guest
# experiences already support (see arcl_guest.py) -- a Front Desk customer
# can speak/read in whichever of these their practice's callers use most.
SUPPORTED_LANGUAGES = [
    {"code": "en-US", "label": "English"},
    {"code": "es-US", "label": "Spanish"},
    {"code": "bn-BD", "label": "Bangla"},
    {"code": "hi-IN", "label": "Hindi"},
    {"code": "ar-XA", "label": "Arabic"},
]


async def _consume_window(
    windows: dict[str, deque[float]],
    key: str,
    window_seconds: int,
    limit: int,
    message: str,
) -> None:
    now = time.monotonic()
    cutoff = now - window_seconds
    async with _token_lock:
        window = windows[key]
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= limit:
            retry_after = max(1, int(window[0] + window_seconds - now) + 1)
            raise HTTPException(
                status_code=429,
                detail=message,
                headers={"Retry-After": str(retry_after)},
            )
        window.append(now)


async def enforce_query_rate_limit(guest: dict) -> None:
    """Applied to guest chat sends -- 12/min, 20 total per guest session,
    same shape as ARCL/Geetabitan's guest chat limits."""
    token_id = str(guest.get("jti") or guest.get("sub") or "unknown")
    await _consume_window(
        _query_windows,
        token_id,
        GUEST_QUERY_WINDOW_SECONDS,
        GUEST_QUERY_WINDOW_LIMIT,
        "Too many questions. Please wait a moment before asking again.",
    )
    async with _token_lock:
        if _message_counts[token_id] >= GUEST_MAX_SESSION_MESSAGES:
            raise HTTPException(
                status_code=429,
                detail="This guest session has reached its question limit. Start a new session to continue.",
            )
        _message_counts[token_id] += 1


async def enforce_voice_rate_limit(guest: dict) -> None:
    if os.environ.get("SCHEDULING_GUEST_VOICE_ENABLED", "true").lower() != "true":
        raise HTTPException(status_code=503, detail="Front Desk guest voice is not enabled")
    token_id = str(guest.get("jti") or guest.get("sub") or "unknown")
    await _consume_window(
        _voice_windows,
        token_id,
        GUEST_VOICE_WINDOW_SECONDS,
        GUEST_VOICE_WINDOW_LIMIT,
        "Too many voice requests. Please wait a moment before trying again.",
    )


class GuestBookingIn(BaseModel):
    practice_id: str = Field(..., min_length=1, max_length=128)
    provider_id: str = Field(..., min_length=1, max_length=128)
    appointment_type_id: str = Field(..., min_length=1, max_length=128)
    start_time: str = Field(..., min_length=10, max_length=64)
    caller_name: str = Field(..., min_length=1, max_length=120)
    caller_phone: str = Field("", max_length=40)
    caller_email: str = Field(..., min_length=5, max_length=200)

    @field_validator("caller_email")
    @classmethod
    def _validate_caller_email(cls, value: str) -> str:
        value = value.strip()
        # Deliberately simple shape check (one "@", a "." after it) --
        # good enough to catch typos/junk without a new hard dependency
        # (email-validator is not in requirements.txt).
        local, _, domain = value.partition("@")
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("Enter a valid email address")
        return value
    reason: str = Field("", max_length=500)


def _require_guest_enabled() -> None:
    if settings.DOMAIN != "scheduling":
        raise HTTPException(status_code=404, detail="Not available for this domain")
    if os.environ.get("SCHEDULING_GUEST_ACCESS_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=503, detail="Guest Front Desk access is not enabled")


def _guest_practice_ids() -> list[str]:
    configured = os.environ.get("SCHEDULING_GUEST_PRACTICE_IDS", "").strip()
    if not configured:
        configured = os.environ.get("SCHEDULING_GUEST_PRACTICE_ID", "").strip()
    practice_ids = list(dict.fromkeys(
        item.strip() for item in configured.split(",") if item.strip()
    ))
    if not practice_ids:
        raise HTTPException(status_code=503, detail="Guest Front Desk practice is not configured")
    return practice_ids


def _guest_practice_id() -> str:
    return _guest_practice_ids()[0]


def _guest_collection() -> str:
    return os.environ.get("SCHEDULING_GUEST_BOOKINGS_COLLECTION", "scheduling_guest_bookings").strip()


def _db() -> firestore.AsyncClient:
    return firestore.AsyncClient(project=settings.GCP_PROJECT_ID, database=settings.FIRESTORE_DATABASE)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limit_key(request: Request) -> str:
    """Keep local development from consuming the public site's IP quota."""
    origin = request.headers.get("origin", "command-line").rstrip("/").lower()
    return f"{origin}|{_client_ip(request)}"


def _enforce_allowed_origin(request: Request) -> None:
    """Reject browser origins that cannot use the returned token.

    Requests without Origin remain available to deployment smoke tests and
    command-line clients. Browsers opened through file:// send Origin: null;
    rejecting that before rate accounting avoids issuing unusable tokens.
    """
    origin = request.headers.get("origin", "").rstrip("/")
    if origin and origin not in GUEST_ALLOWED_ORIGINS:
        raise HTTPException(
            status_code=403,
            detail="Guest Front Desk must run from Agomonia Labs or http://localhost:4177",
        )


async def _enforce_token_rate_limit(request: Request) -> None:
    now = time.monotonic()
    cutoff = now - GUEST_TOKEN_WINDOW_SECONDS
    key = _rate_limit_key(request)
    async with _token_lock:
        window = _token_windows[key]
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= GUEST_TOKEN_WINDOW_LIMIT:
            retry_after = max(1, int(window[0] + GUEST_TOKEN_WINDOW_SECONDS - now) + 1)
            raise HTTPException(
                status_code=429,
                detail="Too many guest sessions. Please reuse the current session or try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        window.append(now)


def _issue_guest_token(practice_ids: str | list[str]) -> tuple[str, str, datetime]:
    if isinstance(practice_ids, str):
        practice_ids = [practice_ids]
    default_practice_id = practice_ids[0]
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=GUEST_TOKEN_TTL_SECONDS)
    guest_id = f"guest_{uuid.uuid4().hex}"
    token = jwt.encode(
        {
            "team_id": guest_id,
            "sub": guest_id,
            "role": GUEST_ROLE,
            "status": "active",
            "practice_id": default_practice_id,
            "practice_ids": practice_ids,
            "token_use": GUEST_TOKEN_USE,
            "jti": uuid.uuid4().hex,
            "iat": now,
            "exp": expires_at,
        },
        _jwt_secret(),
        algorithm=JWT_ALGORITHM,
    )
    return token, guest_id, expires_at


async def get_scheduling_guest(credentials=Depends(bearer_scheme)) -> dict:
    _require_guest_enabled()
    if not credentials:
        raise HTTPException(status_code=401, detail="Guest authentication required")
    payload = decode_token(credentials.credentials)
    if payload.get("role") != GUEST_ROLE or payload.get("token_use") != GUEST_TOKEN_USE:
        raise HTTPException(status_code=403, detail="A Front Desk guest token is required")
    configured_ids = set(_guest_practice_ids())
    token_ids = set(payload.get("practice_ids") or [payload.get("practice_id")])
    if not token_ids or not token_ids.issubset(configured_ids):
        raise HTTPException(status_code=403, detail="Guest token is not valid for the configured demo practices")
    return payload


def decode_customer_token(token: str) -> dict | None:
    """Same identity check as get_scheduling_customer below, but for a raw
    token string instead of FastAPI's bearer-scheme dependency. Used by
    scheduling_guest_chat (api/main.py) to opportunistically attach a
    signed-in customer's real identity to an otherwise-anonymous guest chat
    turn (via a separate X-Customer-Token header -- the chat's own
    Authorization header stays the anonymous guest token, which is what
    scopes rate limiting and the allowed-practices check). Returns None
    rather than raising on any failure: a missing, stale, or malformed
    customer token should just mean the turn stays anonymous, never break
    the conversation."""
    if not token:
        return None
    try:
        payload = decode_token(token)
    except Exception:
        return None
    if payload.get("role") == GUEST_ROLE or payload.get("token_use") == GUEST_TOKEN_USE:
        return None
    if not (payload.get("email") or "").strip():
        return None
    return payload


async def get_scheduling_customer(credentials=Depends(bearer_scheme)) -> dict:
    """A real, signed-in Front Desk account -- required to create, list, or
    cancel a booking. This is deliberately the SAME login (email + password,
    OTP-verified) already live at scheduling.adar.agomoniai.com, decoded with
    auth.py's own decode_token/secret -- there is no separate "customer"
    auth system, just the existing team login used for a different role."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Sign in to manage appointments")
    payload = decode_token(credentials.credentials)
    if payload.get("role") == GUEST_ROLE or payload.get("token_use") == GUEST_TOKEN_USE:
        raise HTTPException(status_code=403, detail="Sign in with your account to manage appointments")
    if not (payload.get("email") or "").strip():
        raise HTTPException(status_code=403, detail="Your account has no email on file")
    return payload


def _resolve_customer_practice(practice_id: str) -> str:
    resolved = (practice_id or "").strip()
    if not resolved or resolved not in set(_guest_practice_ids()):
        raise HTTPException(status_code=403, detail="This practice is not available")
    return resolved


def _resolve_guest_practice(guest: dict, practice_id: str = "") -> str:
    resolved = practice_id.strip() or guest.get("practice_id", "")
    token_ids = set(guest.get("practice_ids") or [guest.get("practice_id")])
    if resolved not in token_ids or resolved not in set(_guest_practice_ids()):
        raise HTTPException(status_code=403, detail="Guest access is not allowed for this practice")
    return resolved


def _public_practice(doc) -> dict:
    data = doc.to_dict() or {}
    return {
        "id": doc.id,
        "practice_id": doc.id,
        "name": data.get("name", "Demo Practice"),
        "domain": data.get("domain", "Scheduling"),
        "tagline": data.get("tagline", "Appointments and provider availability"),
        "color": data.get("color", "#167a67"),
        "timezone": data.get("timezone", "UTC"),
        "lead_time_minutes": data.get("lead_time_minutes", 120),
        "max_advance_days": data.get("max_advance_days", 60),
        "location": data.get("location", "Online"),
        "active": data.get("active", True),
    }


def _public_booking(doc_id: str, data: dict) -> dict:
    def json_time(value):
        return value.isoformat() if hasattr(value, "isoformat") else value

    return {
        "id": doc_id,
        "practice_id": data.get("practice_id"),
        "provider_id": data.get("provider_id"),
        "provider_name": data.get("provider_name"),
        "appointment_type_id": data.get("appointment_type_id"),
        "appointment_type_name": data.get("appointment_type_name"),
        "start_time": json_time(data.get("start_time")),
        "end_time": json_time(data.get("end_time")),
        "caller_name": data.get("caller_name"),
        "caller_phone": data.get("caller_phone"),
        "caller_email": data.get("caller_email"),
        "reason": data.get("reason"),
        "status": data.get("status", "confirmed"),
        "source_channel": data.get("source_channel", "front_desk_app"),
    }


def _public_trace(doc_id: str, data: dict) -> dict:
    """Build a PII-free workflow projection for the public product demo."""
    def json_time(value):
        return value.isoformat() if hasattr(value, "isoformat") else value

    cancelled = data.get("status") == "cancelled"
    if cancelled:
        request_type = "cancel_appointment"
        steps = [
            {"name": "Resolve booking", "detail": "Matched the guest-owned appointment", "ms": 18},
            {"name": "Authorize action", "detail": "Validated guest session and practice scope", "ms": 12},
            {"name": "Commit cancellation", "detail": "Updated the isolated demo booking", "ms": 41},
            {"name": "Update calendar", "detail": "Removed the appointment from active availability", "ms": 23},
        ]
    else:
        request_type = "book_appointment"
        steps = [
            {"name": "Resolve practice", "detail": data.get("practice_id", "Demo practice"), "ms": 16},
            {"name": "Resolve service", "detail": data.get("appointment_type_name", "Appointment"), "ms": 14},
            {"name": "Check availability", "detail": data.get("provider_name", "Selected provider"), "ms": 52},
            {"name": "Revalidate at commit", "detail": "Transactional overlap protection", "ms": 37},
            {"name": "Commit booking", "detail": "Persisted to the isolated guest calendar", "ms": 64},
            {"name": "Prepare notifications", "detail": "Prepared the configured confirmation workflow", "ms": 28},
        ]
    started_at = data.get("created_at") or data.get("updated_at") or data.get("start_time")
    return {
        "trace_id": f"guest-{doc_id}",
        "practice_id": data.get("practice_id"),
        "request_type": request_type,
        "started_at": json_time(started_at),
        "status": "completed",
        "duration_ms": sum(step["ms"] for step in steps),
        "span_count": len(steps),
        "projection": "guest_safe",
        "steps": steps,
    }


def _overlaps(start_a: datetime, end_a: datetime, start_b, end_b) -> bool:
    return bool(start_b and end_b and start_b < end_a and start_a < end_b)


def _format_when(dt: datetime, tz_name: str) -> str:
    """Human-readable local time for booking-confirmation emails --
    mirrors domains/scheduling/tools/availability_tools.py's _format_slot
    (duplicated locally to avoid importing the agent-tools module here)."""
    local_dt = dt
    if tz_name:
        try:
            local_dt = dt.astimezone(ZoneInfo(tz_name))
        except Exception:
            local_dt = dt
    return local_dt.strftime("%A, %B %-d at %-I:%M %p %Z")


async def _active_practice(db: firestore.AsyncClient, practice_id: str):
    doc = await db.collection(settings.SCHEDULING_PRACTICES_COLLECTION).document(practice_id).get()
    if not doc.exists or (doc.to_dict() or {}).get("active") is False:
        raise HTTPException(status_code=404, detail="The configured guest practice is unavailable")
    return doc


@router.post("/session", status_code=201)
async def create_guest_session(request: Request, response: Response):
    """Issue a short-lived token for the configured public demo practices."""
    _require_guest_enabled()
    _enforce_allowed_origin(request)
    await _enforce_token_rate_limit(request)
    practice_ids = _guest_practice_ids()
    db = _db()
    for practice_id in practice_ids:
        await _active_practice(db, practice_id)
    token, guest_id, expires_at = _issue_guest_token(practice_ids)
    response.headers["Cache-Control"] = "no-store"
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": GUEST_TOKEN_TTL_SECONDS,
        "expires_at": expires_at.isoformat(),
        "guest_id": guest_id,
        "practice_id": practice_ids[0],
        "practice_ids": practice_ids,
        "scope": ["practice:read", "guest_bookings:read", "guest_bookings:write", "guest_traces:read"],
    }


@router.get("/practices")
async def list_guest_practices(guest: dict = Depends(get_scheduling_guest)):
    db = _db()
    practices = [
        _public_practice(await _active_practice(db, practice_id))
        for practice_id in guest.get("practice_ids") or [guest["practice_id"]]
    ]
    return {"practices": practices}


@router.get("/practice")
async def get_guest_practice(
    practice_id: str = "",
    guest: dict = Depends(get_scheduling_guest),
):
    resolved = _resolve_guest_practice(guest, practice_id)
    return _public_practice(await _active_practice(_db(), resolved))


@router.get("/providers")
async def list_guest_providers(
    practice_id: str = "",
    guest: dict = Depends(get_scheduling_guest),
):
    db = _db()
    resolved = _resolve_guest_practice(guest, practice_id)
    providers = []
    async for doc in db.collection(settings.SCHEDULING_PROVIDERS_COLLECTION).where(
        "practice_id", "==", resolved
    ).stream():
        data = doc.to_dict() or {}
        if data.get("active") is False:
            continue
        providers.append({
            "id": doc.id,
            "name": data.get("name", "Provider"),
            "role": data.get("role", ""),
            "bio": data.get("bio", ""),
            "appointment_type_ids": data.get("appointment_type_ids", []),
            "working_hours": data.get("working_hours", []),
        })
    providers.sort(key=lambda item: item["name"])
    return {"providers": providers}


@router.get("/appointment-types")
async def list_guest_appointment_types(
    practice_id: str = "",
    guest: dict = Depends(get_scheduling_guest),
):
    db = _db()
    resolved = _resolve_guest_practice(guest, practice_id)
    appointment_types = []
    async for doc in db.collection(settings.SCHEDULING_APPOINTMENT_TYPES_COLLECTION).where(
        "practice_id", "==", resolved
    ).stream():
        data = doc.to_dict() or {}
        if data.get("active") is False:
            continue
        appointment_types.append({
            "id": doc.id,
            "name": data.get("name", "Appointment"),
            "duration_minutes": data.get("duration_minutes", 30),
            "buffer_minutes": data.get("buffer_minutes", 0),
            "description": data.get("description", ""),
        })
    appointment_types.sort(key=lambda item: item["name"])
    return {"appointment_types": appointment_types}


@router.get("/bookings")
async def list_guest_bookings(
    start: str,
    end: str,
    practice_id: str = "",
    customer: dict = Depends(get_scheduling_customer),
):
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="start/end must be ISO 8601 datetimes")
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)

    resolved = _resolve_customer_practice(practice_id)
    bookings = []
    async for doc in _db().collection(settings.SCHEDULING_APPOINTMENTS_COLLECTION).where(
        "practice_id", "==", resolved
    ).limit(200).stream():
        data = doc.to_dict() or {}
        if data.get("guest_id") != customer["team_id"]:
            continue
        starts_at = data.get("start_time")
        if starts_at and start_dt <= starts_at < end_dt:
            bookings.append(_public_booking(doc.id, data))
    bookings.sort(key=lambda item: item.get("start_time") or "")
    return {"bookings": bookings}


@router.get("/traces")
async def list_guest_traces(
    practice_id: str = "",
    guest: dict = Depends(get_scheduling_guest),
):
    """Return sanitized trace flows for visible guest-demo bookings only."""
    resolved = _resolve_guest_practice(guest, practice_id)
    traces = []
    async for doc in _db().collection(_guest_collection()).where(
        "practice_id", "==", resolved
    ).limit(100).stream():
        data = doc.to_dict() or {}
        if data.get("guest_id") != guest["team_id"] and data.get("demo_seed") is not True:
            continue
        expires_at = data.get("expires_at")
        if expires_at and expires_at <= datetime.now(timezone.utc):
            continue
        traces.append(_public_trace(doc.id, data))
    traces.sort(key=lambda item: item.get("started_at") or "", reverse=True)
    return {"traces": traces, "projection": "guest_safe"}


@router.post("/bookings", status_code=201)
async def create_guest_booking(body: GuestBookingIn, customer: dict = Depends(get_scheduling_customer)):
    """Books a real appointment for a signed-in ADAR Front Desk customer --
    this app is a full production booking channel, not a demo, so this
    writes straight into SCHEDULING_APPOINTMENTS_COLLECTION, the same
    collection scheduling_admin.py's practice-admin console and provider
    calendar read from (and the same one the Ask ADAR chat agent's
    hold_slot/confirm_booking tools already write into). No artificial
    per-customer booking cap or expiry -- those only ever made sense for
    the old throwaway public demo."""
    db = _db()
    practice_id = _resolve_customer_practice(body.practice_id)
    guest_id = customer["team_id"]
    customer_email = (customer.get("email") or "").strip().lower()
    practice_doc = await _active_practice(db, practice_id)
    practice_data = practice_doc.to_dict() or {}

    provider_doc = await db.collection(settings.SCHEDULING_PROVIDERS_COLLECTION).document(body.provider_id).get()
    provider = provider_doc.to_dict() or {} if provider_doc.exists else {}
    if not provider_doc.exists or provider.get("practice_id") != practice_id or provider.get("active") is False:
        raise HTTPException(status_code=404, detail="Provider not found")

    type_doc = await db.collection(settings.SCHEDULING_APPOINTMENT_TYPES_COLLECTION).document(body.appointment_type_id).get()
    appointment_type = type_doc.to_dict() or {} if type_doc.exists else {}
    if not type_doc.exists or appointment_type.get("practice_id") != practice_id or appointment_type.get("active") is False:
        raise HTTPException(status_code=404, detail="Appointment type not found")

    try:
        starts_at = datetime.fromisoformat(body.start_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="start_time must be an ISO 8601 datetime")
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if starts_at <= now:
        raise HTTPException(status_code=400, detail="Bookings must be in the future")
    # This REST path (unlike the voice/chat tools' check_availability, which
    # only ever offers slots already inside the window) lets the client pick
    # any start_time directly, so the practice's own lead_time_minutes/
    # max_advance_days guardrails have to be re-checked here too -- otherwise
    # a customer could book arbitrarily far out (or with no notice at all)
    # regardless of what the practice configured, e.g. the 7-day cap a
    # dine-in restaurant practice relies on.
    lead_time_minutes = int(practice_data.get("lead_time_minutes") or 120)
    max_advance_days = int(practice_data.get("max_advance_days") or 60)
    if starts_at < now + timedelta(minutes=lead_time_minutes):
        raise HTTPException(status_code=400, detail=f"Bookings need at least {lead_time_minutes} minutes' notice")
    if starts_at > now + timedelta(days=max_advance_days):
        raise HTTPException(status_code=400, detail=f"Bookings can only be made up to {max_advance_days} days in advance")

    duration = int(appointment_type.get("duration_minutes", 30))
    ends_at = starts_at + timedelta(minutes=duration)
    appointment_id = str(uuid.uuid4())
    data = {
        "practice_id": practice_id,
        "guest_id": guest_id,
        "provider_id": body.provider_id,
        "provider_name": provider.get("name", ""),
        "appointment_type_id": body.appointment_type_id,
        "appointment_type_name": appointment_type.get("name", ""),
        "start_time": starts_at,
        "end_time": ends_at,
        "caller_name": body.caller_name.strip(),
        "caller_phone": body.caller_phone.strip(),
        "caller_email": body.caller_email.strip(),
        "reason": body.reason.strip(),
        "status": "confirmed",
        "source_channel": "front_desk_app",
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP,
    }

    transaction = db.transaction()

    @firestore.async_transactional
    async def _create_if_available(txn: firestore.AsyncTransaction):
        async for existing in db.collection(settings.SCHEDULING_APPOINTMENTS_COLLECTION).where(
            "practice_id", "==", practice_id
        ).limit(1000).stream(transaction=txn):
            current = existing.to_dict() or {}
            if current.get("provider_id") != body.provider_id:
                continue
            if current.get("status") not in {"confirmed", "requested"}:
                continue
            if _overlaps(starts_at, ends_at, current.get("start_time"), current.get("end_time")):
                raise ValueError("slot_taken")

        txn.set(db.collection(settings.SCHEDULING_APPOINTMENTS_COLLECTION).document(appointment_id), data)

    try:
        await _create_if_available(transaction)
    except ValueError as error:
        if str(error) == "slot_taken":
            raise HTTPException(status_code=409, detail="That time is no longer available")
        raise

    await _send_booking_emails(
        practice_data=practice_data,
        provider_data=provider,
        appointment_type_name=appointment_type.get("name", ""),
        caller_name=body.caller_name.strip(),
        caller_phone=body.caller_phone.strip(),
        caller_email=str(body.caller_email).strip(),
        customer_email=customer_email,
        reason=body.reason.strip(),
        when_formatted=_format_when(starts_at, practice_data.get("timezone", "")),
        appointment_id=appointment_id,
    )

    return _public_booking(appointment_id, data)


async def _send_booking_emails(
    *,
    practice_data: dict,
    provider_data: dict,
    appointment_type_name: str,
    caller_name: str,
    caller_phone: str,
    caller_email: str,
    customer_email: str,
    reason: str,
    when_formatted: str,
    appointment_id: str,
) -> None:
    """Best-effort booking notification fan-out. Targets (deduped so the
    same inbox never receives an identical email twice):
      1) the email entered on the booking form (caller_email)
      2) the signed-in account's own email, if different from (1)
      3) the provider's own email, if the practice has one on file
      4) the practice's admin/notification_email, falling back to the
         platform ADMIN_EMAIL when the practice hasn't set one
    A send failure here never fails the booking -- see notify.send_email,
    which already logs and swallows SMTP errors the same way."""
    practice_name = practice_data.get("name", "your practice")
    provider_name = provider_data.get("name", "")

    customer_targets = {addr for addr in {caller_email.lower(), customer_email.lower()} if addr}
    for to in customer_targets:
        try:
            await send_appointment_confirmation_email(
                to=to,
                caller_name=caller_name,
                practice_name=practice_name,
                appointment_type_name=appointment_type_name,
                provider_name=provider_name,
                when_formatted=when_formatted,
                appointment_id=appointment_id,
            )
        except Exception:
            logger.exception("Failed to send booking confirmation email to %s", to)

    admin_email = (practice_data.get("notification_email") or "").strip().lower() or _admin_email()
    provider_email = (provider_data.get("email") or "").strip().lower()
    staff_targets = {addr for addr in {admin_email, provider_email} if addr}
    for to in staff_targets:
        try:
            await send_new_booking_notification_email(
                to=to,
                practice_name=practice_name,
                caller_name=caller_name,
                caller_phone=caller_phone,
                appointment_type_name=appointment_type_name,
                provider_name=provider_name,
                when_formatted=when_formatted,
                appointment_id=appointment_id,
                caller_email=caller_email,
                reason=reason,
            )
        except Exception:
            logger.exception("Failed to send new-booking notification email to %s", to)


async def _send_cancellation_emails(
    *,
    practice_data: dict,
    provider_data: dict,
    appointment_type_name: str,
    caller_name: str,
    caller_phone: str,
    caller_email: str,
    customer_email: str,
    cancel_reason: str,
    when_formatted: str,
    appointment_id: str,
) -> None:
    """Best-effort cancellation notification fan-out -- the mirror of
    _send_booking_emails above, sent whenever a confirmed appointment is
    cancelled from any channel (this REST endpoint's My Appointments
    "Cancel" button, or the scheduling agent's cancel_appointment /
    reschedule_appointment tools). Same dedup rule and same 4 possible
    targets: the caller's booking-form email + the signed-in account's own
    email (customer confirmation), and the provider's own email + the
    practice's notification_email/ADMIN_EMAIL (staff notification). A send
    failure here never fails the cancellation -- see notify.send_email."""
    practice_name = practice_data.get("name", "your practice")
    provider_name = provider_data.get("name", "")

    customer_targets = {addr for addr in {caller_email.lower(), customer_email.lower()} if addr}
    for to in customer_targets:
        try:
            await send_appointment_cancelled_email(
                to=to,
                caller_name=caller_name,
                practice_name=practice_name,
                appointment_type_name=appointment_type_name,
                provider_name=provider_name,
                when_formatted=when_formatted,
                appointment_id=appointment_id,
                cancel_reason=cancel_reason,
            )
        except Exception:
            logger.exception("Failed to send cancellation email to %s", to)

    admin_email = (practice_data.get("notification_email") or "").strip().lower() or _admin_email()
    provider_email = (provider_data.get("email") or "").strip().lower()
    staff_targets = {addr for addr in {admin_email, provider_email} if addr}
    for to in staff_targets:
        try:
            await send_booking_cancelled_notification_email(
                to=to,
                practice_name=practice_name,
                caller_name=caller_name,
                caller_phone=caller_phone,
                appointment_type_name=appointment_type_name,
                provider_name=provider_name,
                when_formatted=when_formatted,
                appointment_id=appointment_id,
                caller_email=caller_email,
                cancel_reason=cancel_reason,
            )
        except Exception:
            logger.exception("Failed to send cancellation staff notification to %s", to)


@router.delete("/appointments/{appointment_id}")
async def cancel_guest_booking(
    appointment_id: str,
    reason: str = "Cancelled from ADAR Front Desk app",
    customer: dict = Depends(get_scheduling_customer),
):
    """Cancels a signed-in customer's own booking and sends the same
    customer+provider+practice-admin email fan-out confirm_booking sends
    on a new booking (_send_cancellation_emails, shared with the
    scheduling agent's cancel_appointment tool) -- this used to silently
    update the booking's status with no email at all."""
    db = _db()
    ref = db.collection(settings.SCHEDULING_APPOINTMENTS_COLLECTION).document(appointment_id)
    doc = await ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Booking not found")
    data = doc.to_dict() or {}
    if data.get("guest_id") != customer["team_id"]:
        raise HTTPException(status_code=404, detail="Booking not found")
    practice_id = _resolve_customer_practice(data.get("practice_id", ""))
    if data.get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="Booking is already cancelled")
    await ref.update({
        "status": "cancelled",
        "cancel_reason": reason[:500],
        "updated_at": firestore.SERVER_TIMESTAMP,
    })
    data["status"] = "cancelled"

    try:
        practice_snap = await db.collection(settings.SCHEDULING_PRACTICES_COLLECTION).document(practice_id).get()
        practice_data = practice_snap.to_dict() or {} if practice_snap.exists else {}
    except Exception:
        logger.warning("Could not load practice %s for cancellation notifications", practice_id, exc_info=True)
        practice_data = {}

    provider_data: dict = {}
    provider_id = data.get("provider_id", "")
    if provider_id:
        try:
            provider_snap = await db.collection(settings.SCHEDULING_PROVIDERS_COLLECTION).document(provider_id).get()
            if provider_snap.exists:
                provider_data = provider_snap.to_dict() or {}
        except Exception:
            logger.warning("Could not load provider %s for cancellation notifications", provider_id, exc_info=True)
    provider_data.setdefault("name", data.get("provider_name", ""))

    await _send_cancellation_emails(
        practice_data=practice_data,
        provider_data=provider_data,
        appointment_type_name=data.get("appointment_type_name", "appointment"),
        caller_name=data.get("caller_name", ""),
        caller_phone=data.get("caller_phone", ""),
        caller_email=(data.get("caller_email") or "").strip(),
        customer_email=(customer.get("email") or "").strip().lower(),
        cancel_reason=reason[:500],
        when_formatted=_format_when(data["start_time"], practice_data.get("timezone", "")),
        appointment_id=appointment_id,
    )

    return _public_booking(appointment_id, data)
