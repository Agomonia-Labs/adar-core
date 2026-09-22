"""Short-lived, least-privilege guest access for the public Front Desk demo.

Guest tokens are intentionally separate from customer and practice-staff
identity. They are restricted to one configured demo practice, never expose
staff records, operational appointments, other customers' PII, or traces, and
write bookings to an isolated demo collection.
"""
import asyncio
import os
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from google.cloud import firestore
from jose import jwt
from pydantic import BaseModel, Field

from api.routes.auth import JWT_ALGORITHM, _jwt_secret, bearer_scheme, decode_token
from src.adar.config import settings


router = APIRouter(prefix="/api/scheduling/guest", tags=["scheduling-guest"])

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


class GuestBookingIn(BaseModel):
    practice_id: str = Field(..., min_length=1, max_length=128)
    provider_id: str = Field(..., min_length=1, max_length=128)
    appointment_type_id: str = Field(..., min_length=1, max_length=128)
    start_time: str = Field(..., min_length=10, max_length=64)
    caller_name: str = Field(..., min_length=1, max_length=120)
    caller_phone: str = Field("", max_length=40)
    caller_email: str = Field("", max_length=200)
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
        "source_channel": "public_demo",
    }


def _overlaps(start_a: datetime, end_a: datetime, start_b, end_b) -> bool:
    return bool(start_b and end_b and start_b < end_a and start_a < end_b)


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
        "scope": ["practice:read", "guest_bookings:read", "guest_bookings:write"],
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
    guest: dict = Depends(get_scheduling_guest),
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

    resolved = _resolve_guest_practice(guest, practice_id)
    bookings = []
    async for doc in _db().collection(_guest_collection()).where(
        "practice_id", "==", resolved
    ).limit(100).stream():
        data = doc.to_dict() or {}
        if data.get("guest_id") != guest["team_id"] and data.get("demo_seed") is not True:
            continue
        starts_at = data.get("start_time")
        expires_at = data.get("expires_at")
        if expires_at and expires_at <= datetime.now(timezone.utc):
            continue
        if starts_at and start_dt <= starts_at < end_dt:
            bookings.append(_public_booking(doc.id, data))
    bookings.sort(key=lambda item: item.get("start_time") or "")
    return {"bookings": bookings}


@router.post("/bookings", status_code=201)
async def create_guest_booking(body: GuestBookingIn, guest: dict = Depends(get_scheduling_guest)):
    db = _db()
    practice_id = _resolve_guest_practice(guest, body.practice_id)
    guest_id = guest["team_id"]
    await _active_practice(db, practice_id)

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
    if starts_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Guest bookings must be in the future")

    active_count = 0
    async for existing in db.collection(_guest_collection()).where("guest_id", "==", guest_id).limit(GUEST_MAX_BOOKINGS + 1).stream():
        data = existing.to_dict() or {}
        expires_at = data.get("expires_at")
        if data.get("status") == "confirmed" and (not expires_at or expires_at > datetime.now(timezone.utc)):
            active_count += 1
    if active_count >= GUEST_MAX_BOOKINGS:
        raise HTTPException(status_code=429, detail="This guest session has reached its demo booking limit")

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
        "source_channel": "public_demo",
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=GUEST_BOOKING_TTL_HOURS),
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

        async for existing in db.collection(_guest_collection()).where(
            "practice_id", "==", practice_id
        ).limit(1000).stream(transaction=txn):
            current = existing.to_dict() or {}
            if current.get("provider_id") != body.provider_id or current.get("status") != "confirmed":
                continue
            expires_at = current.get("expires_at")
            if expires_at and expires_at <= datetime.now(timezone.utc):
                continue
            if _overlaps(starts_at, ends_at, current.get("start_time"), current.get("end_time")):
                raise ValueError("slot_taken")

        txn.set(db.collection(_guest_collection()).document(appointment_id), data)

    try:
        await _create_if_available(transaction)
    except ValueError as error:
        if str(error) == "slot_taken":
            raise HTTPException(status_code=409, detail="That demo time is no longer available")
        raise
    return _public_booking(appointment_id, data)


@router.delete("/appointments/{appointment_id}")
async def cancel_guest_booking(
    appointment_id: str,
    reason: str = "Cancelled from public Front Desk demo",
    guest: dict = Depends(get_scheduling_guest),
):
    db = _db()
    ref = db.collection(_guest_collection()).document(appointment_id)
    doc = await ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Guest booking not found")
    data = doc.to_dict() or {}
    if data.get("guest_id") != guest["team_id"]:
        raise HTTPException(status_code=404, detail="Guest booking not found")
    _resolve_guest_practice(guest, data.get("practice_id", ""))
    if data.get("demo_seed") is True:
        raise HTTPException(status_code=404, detail="Guest booking not found")
    if data.get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="Guest booking is already cancelled")
    await ref.update({
        "status": "cancelled",
        "cancel_reason": reason[:500],
        "updated_at": firestore.SERVER_TIMESTAMP,
    })
    data["status"] = "cancelled"
    return _public_booking(appointment_id, data)
