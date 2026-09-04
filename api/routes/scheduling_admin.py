"""
api/routes/scheduling_admin.py — CRUD for the scheduling domain's practices,
providers, and appointment types, plus a bookings query endpoint for the
admin console's calendar view.

Two levels of caller, both JWTs from api/routes/auth.py's shared login flow:
  - role="admin" — the single platform-operator login (ADMIN_EMAIL /
    ADMIN_PASSWORD). Full access to every practice, plus the only role that
    can create practices and provision practice-staff logins (see the
    "Practice staff accounts" section below).
  - role="practice_staff" — a login scoped to exactly one practice_id
    (carried in the JWT — see _create_token calls in auth.py's /login and
    /verify-otp). Same CRUD as admin, but every route checks the caller's
    token practice_id against the practice_id being read/written
    (_check_practice_access below) and 403s on a mismatch, so one practice's
    staff can never see or touch another practice's data. Cannot create
    practices, list all practices, or provision other staff accounts.

Only mounted usefully for DOMAIN=scheduling (every SCHEDULING_*_COLLECTION
setting is "" for any other domain — see src/adar/config.py — so every
route 404s cleanly elsewhere rather than risking a Firestore call against an
empty collection name).

This is mostly a plain CRUD layer, not the booking engine -- the
caller-facing booking engine (hold_slot/confirm_booking/cancel_appointment/
reschedule_appointment, used by the voice/chat assistant) stays in
domains/scheduling/tools/availability_tools.py and is untouched by this
file. An admin (or that practice's own staff) editing a provider's
working hours here takes effect immediately for the chat agent too, since
availability is always computed live against current Firestore state (see
that module's docstring).

The one exception is create_booking/cancel_booking below: a manual-entry
path so front-desk staff can add or remove an appointment directly from
the admin console (a walk-in, a phone call handled without the assistant,
fixing a mistake) without going through the assistant's hold/confirm
two-step. It duplicates availability_tools.py's double-booking check
(overlapping confirmed appointments and active holds, buffer-aware)
rather than importing it, since that module's functions are shaped for an
LLM tool call (plain-string in, plain-string out) and this needs a
structured request/response for the UI. Appointments created here are
tagged source_channel="staff_manual" so they're distinguishable from
ones the assistant booked (see the README's fake-booking-detection notes)
-- and cancelling here sends the exact same caller-facing cancellation
email as cancel_appointment does, so a caller sees no difference in which
side cancelled.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from google.cloud import firestore

from src.adar.config import settings
from api.routes.auth import get_admin, get_current_team, TEAMS_COLLECTION, _auth_db, _hash_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/scheduling", tags=["admin-scheduling"])


def _require_scheduling_domain():
    if settings.DOMAIN != "scheduling":
        raise HTTPException(status_code=404, detail="Not available for this domain")


def get_db() -> firestore.AsyncClient:
    return firestore.AsyncClient(
        project=settings.GCP_PROJECT_ID,
        database=settings.FIRESTORE_DATABASE,
    )


def _auth_client() -> firestore.AsyncClient:
    """Separate from get_db() above on purpose — practice-staff accounts are
    login records (adar_teams, same auth flow as every other domain's team
    login), which live in the auth database (_auth_db()), not the scheduling
    data database (settings.FIRESTORE_DATABASE). The two happen to be the
    same Firestore database in this deployment's current .env, but nothing
    here should assume that stays true."""
    return firestore.AsyncClient(
        project=settings.GCP_PROJECT_ID,
        database=_auth_db(),
    )


async def get_scheduling_staff(team: dict = Depends(get_current_team)) -> dict:
    """Accepts the platform admin (role="admin") or a practice-scoped staff
    login (role="practice_staff") — anything else is rejected. Route bodies
    still need _check_practice_access(team, practice_id) once they know
    which practice_id is actually being read/written, since this dependency
    alone can't see path/body params."""
    if team.get("role") not in ("admin", "practice_staff"):
        raise HTTPException(status_code=403, detail="Scheduling admin access required")
    return team


def _check_practice_access(team: dict, practice_id: str) -> None:
    """Enforces that a practice_staff token can only touch its own
    practice_id. No-op for role="admin" (unrestricted, per the module
    docstring above)."""
    if team.get("role") == "practice_staff" and team.get("practice_id") != practice_id:
        raise HTTPException(status_code=403, detail="Not authorized for this practice")


def _doc_to_dict(doc) -> dict:
    d = doc.to_dict() or {}
    d["id"] = doc.id
    ts = d.get("created_at")
    if hasattr(ts, "isoformat"):
        d["created_at"] = ts.isoformat()
    return d


# ── Models ──────────────────────────────────────────────────────────────────

class WorkingHour(BaseModel):
    weekday: int   # 0=Monday .. 6=Sunday (matches compute_open_slots' convention)
    start:   str   # "HH:MM"
    end:     str   # "HH:MM"


class PracticeIn(BaseModel):
    name: str
    timezone: str = "UTC"
    lead_time_minutes: int = 120
    max_advance_days: int = 60
    notification_email: str = ""


class PracticePatch(BaseModel):
    name: Optional[str] = None
    timezone: Optional[str] = None
    lead_time_minutes: Optional[int] = None
    max_advance_days: Optional[int] = None
    active: Optional[bool] = None
    notification_email: Optional[str] = None


class ProviderIn(BaseModel):
    name: str
    role: str = ""
    bio: str = ""
    appointment_type_ids: list[str] = []
    working_hours: list[WorkingHour] = []


class ProviderPatch(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    bio: Optional[str] = None
    appointment_type_ids: Optional[list[str]] = None
    working_hours: Optional[list[WorkingHour]] = None
    active: Optional[bool] = None


class AppointmentTypeIn(BaseModel):
    name: str
    duration_minutes: int = 30
    buffer_minutes: int = 0
    description: str = ""


class AppointmentTypePatch(BaseModel):
    name: Optional[str] = None
    duration_minutes: Optional[int] = None
    buffer_minutes: Optional[int] = None
    description: Optional[str] = None
    active: Optional[bool] = None


class StaffIn(BaseModel):
    email: str
    password: str
    name: str = ""


class BookingIn(BaseModel):
    provider_id: str
    appointment_type_id: str
    start_time: str          # ISO 8601 -- naive is treated as UTC
    caller_name: str
    caller_phone: str = ""
    caller_email: str = ""
    reason: str = ""


# ── Practices ───────────────────────────────────────────────────────────────

@router.get("/practices")
async def list_practices(_: dict = Depends(get_admin)):
    _require_scheduling_domain()
    db = get_db()
    out = []
    async for doc in db.collection(settings.SCHEDULING_PRACTICES_COLLECTION).stream():
        out.append(_doc_to_dict(doc))
    out.sort(key=lambda p: p.get("name", ""))
    return {"practices": out}


@router.post("/practices")
async def create_practice(body: PracticeIn, _: dict = Depends(get_admin)):
    _require_scheduling_domain()
    db = get_db()
    ref = db.collection(settings.SCHEDULING_PRACTICES_COLLECTION).document()
    practice_id = ref.id
    data = {
        "practice_id": practice_id,
        "name": body.name.strip(),
        "timezone": body.timezone,
        "lead_time_minutes": body.lead_time_minutes,
        "max_advance_days": body.max_advance_days,
        # Where new-booking notifications go (see confirm_booking in
        # availability_tools.py) — falls back to the platform ADMIN_EMAIL
        # at send time when left blank, so this is optional here.
        "notification_email": body.notification_email.strip(),
        "active": True,
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    await ref.set(data)
    logger.info(f"Admin created practice {practice_id} ({body.name})")
    return _doc_to_dict(await ref.get())


@router.get("/practices/{practice_id}")
async def get_practice(practice_id: str, team: dict = Depends(get_scheduling_staff)):
    """Single-practice fetch — the counterpart practice_staff needs since
    list_practices above stays admin-only (it would otherwise leak every
    other practice's name to a practice_staff login)."""
    _require_scheduling_domain()
    _check_practice_access(team, practice_id)
    db = get_db()
    ref = db.collection(settings.SCHEDULING_PRACTICES_COLLECTION).document(practice_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Practice not found")
    return _doc_to_dict(snap)


@router.patch("/practices/{practice_id}")
async def update_practice(practice_id: str, body: PracticePatch, team: dict = Depends(get_scheduling_staff)):
    _require_scheduling_domain()
    _check_practice_access(team, practice_id)
    db = get_db()
    ref = db.collection(settings.SCHEDULING_PRACTICES_COLLECTION).document(practice_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Practice not found")
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    await ref.update(updates)
    logger.info(f"Admin updated practice {practice_id}: {list(updates.keys())}")
    return _doc_to_dict(await ref.get())


# ── Providers ───────────────────────────────────────────────────────────────

@router.get("/practices/{practice_id}/providers")
async def list_providers(practice_id: str, team: dict = Depends(get_scheduling_staff)):
    _require_scheduling_domain()
    _check_practice_access(team, practice_id)
    db = get_db()
    out = []
    async for doc in db.collection(settings.SCHEDULING_PROVIDERS_COLLECTION) \
            .where("practice_id", "==", practice_id).stream():
        out.append(_doc_to_dict(doc))
    out.sort(key=lambda p: p.get("name", ""))
    return {"providers": out}


@router.post("/practices/{practice_id}/providers")
async def create_provider(practice_id: str, body: ProviderIn, team: dict = Depends(get_scheduling_staff)):
    _require_scheduling_domain()
    _check_practice_access(team, practice_id)
    db = get_db()
    practice_snap = await db.collection(settings.SCHEDULING_PRACTICES_COLLECTION).document(practice_id).get()
    if not practice_snap.exists:
        raise HTTPException(status_code=404, detail="Practice not found")
    ref = db.collection(settings.SCHEDULING_PROVIDERS_COLLECTION).document()
    data = {
        "practice_id": practice_id,
        "name": body.name.strip(),
        "role": body.role,
        "bio": body.bio.strip(),
        "appointment_type_ids": body.appointment_type_ids,
        "working_hours": [wh.model_dump() for wh in body.working_hours],
        "active": True,
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    await ref.set(data)
    logger.info(f"Admin created provider {ref.id} ({body.name}) for practice {practice_id}")
    return _doc_to_dict(await ref.get())


@router.patch("/providers/{provider_id}")
async def update_provider(provider_id: str, body: ProviderPatch, team: dict = Depends(get_scheduling_staff)):
    _require_scheduling_domain()
    db = get_db()
    ref = db.collection(settings.SCHEDULING_PROVIDERS_COLLECTION).document(provider_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Provider not found")
    _check_practice_access(team, snap.to_dict().get("practice_id"))
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "working_hours" in updates:
        updates["working_hours"] = [
            (wh.model_dump() if hasattr(wh, "model_dump") else wh) for wh in updates["working_hours"]
        ]
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    await ref.update(updates)
    logger.info(f"Admin updated provider {provider_id}: {list(updates.keys())}")
    return _doc_to_dict(await ref.get())


# ── Appointment types ───────────────────────────────────────────────────────

@router.get("/practices/{practice_id}/appointment-types")
async def list_appointment_types(practice_id: str, team: dict = Depends(get_scheduling_staff)):
    _require_scheduling_domain()
    _check_practice_access(team, practice_id)
    db = get_db()
    out = []
    async for doc in db.collection(settings.SCHEDULING_APPOINTMENT_TYPES_COLLECTION) \
            .where("practice_id", "==", practice_id).stream():
        out.append(_doc_to_dict(doc))
    out.sort(key=lambda t: t.get("name", ""))
    return {"appointment_types": out}


@router.post("/practices/{practice_id}/appointment-types")
async def create_appointment_type(practice_id: str, body: AppointmentTypeIn, team: dict = Depends(get_scheduling_staff)):
    _require_scheduling_domain()
    _check_practice_access(team, practice_id)
    db = get_db()
    practice_snap = await db.collection(settings.SCHEDULING_PRACTICES_COLLECTION).document(practice_id).get()
    if not practice_snap.exists:
        raise HTTPException(status_code=404, detail="Practice not found")
    ref = db.collection(settings.SCHEDULING_APPOINTMENT_TYPES_COLLECTION).document()
    data = {
        "practice_id": practice_id,
        "name": body.name.strip(),
        "duration_minutes": body.duration_minutes,
        "buffer_minutes": body.buffer_minutes,
        "description": body.description,
        "active": True,
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    await ref.set(data)
    logger.info(f"Admin created appointment type {ref.id} ({body.name}) for practice {practice_id}")
    return _doc_to_dict(await ref.get())


@router.patch("/appointment-types/{type_id}")
async def update_appointment_type(type_id: str, body: AppointmentTypePatch, team: dict = Depends(get_scheduling_staff)):
    _require_scheduling_domain()
    db = get_db()
    ref = db.collection(settings.SCHEDULING_APPOINTMENT_TYPES_COLLECTION).document(type_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Appointment type not found")
    _check_practice_access(team, snap.to_dict().get("practice_id"))
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    await ref.update(updates)
    logger.info(f"Admin updated appointment type {type_id}: {list(updates.keys())}")
    return _doc_to_dict(await ref.get())


# ── Bookings (read-only, for the admin calendar view) ───────────────────────

@router.get("/practices/{practice_id}/bookings")
async def list_bookings(
    practice_id: str,
    start: str,
    end: str,
    provider_id: str = "",
    status: str = "",
    team: dict = Depends(get_scheduling_staff),
):
    """Bookings whose start_time falls in [start, end) (ISO 8601 datetimes,
    e.g. from a calendar's visible week/month range). Filtered in Python
    (not a Firestore range query) to avoid needing a new composite index —
    matches the pattern already used by availability_tools.py's own queries,
    and appointment volume per practice is small enough this is cheap."""
    _require_scheduling_domain()
    _check_practice_access(team, practice_id)
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="start/end must be ISO 8601 datetimes")
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=dt_timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=dt_timezone.utc)

    db = get_db()
    query = db.collection(settings.SCHEDULING_APPOINTMENTS_COLLECTION).where("practice_id", "==", practice_id)
    if provider_id:
        query = query.where("provider_id", "==", provider_id)
    query = query.limit(1000)

    out = []
    async for doc in query.stream():
        d = doc.to_dict()
        s = d.get("start_time")
        if not s or s < start_dt or s >= end_dt:
            continue
        if status and d.get("status") != status:
            continue
        out.append({
            "id": doc.id,
            "practice_id": d.get("practice_id"),
            "provider_id": d.get("provider_id"),
            "provider_name": d.get("provider_name"),
            "appointment_type_name": d.get("appointment_type_name"),
            "start_time": d.get("start_time").isoformat() if hasattr(d.get("start_time"), "isoformat") else d.get("start_time"),
            "end_time": d.get("end_time").isoformat() if hasattr(d.get("end_time"), "isoformat") else d.get("end_time"),
            "caller_name": d.get("caller_name"),
            "caller_phone": d.get("caller_phone"),
            "caller_email": d.get("caller_email"),
            "reason": d.get("reason"),
            "status": d.get("status"),
        })
    out.sort(key=lambda a: a["start_time"] or "")
    return {"bookings": out}


def _booking_to_dict(doc_id: str, d: dict) -> dict:
    return {
        "id": doc_id,
        "practice_id": d.get("practice_id"),
        "provider_id": d.get("provider_id"),
        "provider_name": d.get("provider_name"),
        "appointment_type_id": d.get("appointment_type_id"),
        "appointment_type_name": d.get("appointment_type_name"),
        "start_time": d.get("start_time").isoformat() if hasattr(d.get("start_time"), "isoformat") else d.get("start_time"),
        "end_time": d.get("end_time").isoformat() if hasattr(d.get("end_time"), "isoformat") else d.get("end_time"),
        "caller_name": d.get("caller_name"),
        "caller_phone": d.get("caller_phone"),
        "caller_email": d.get("caller_email"),
        "reason": d.get("reason"),
        "status": d.get("status"),
        "source_channel": d.get("source_channel"),
    }


def _format_when(dt) -> str:
    return dt.strftime("%A, %B %-d at %-I:%M %p %Z") if hasattr(dt, "strftime") else str(dt)


@router.post("/practices/{practice_id}/bookings")
async def create_booking(practice_id: str, body: BookingIn, team: dict = Depends(get_scheduling_staff)):
    """Manually add a confirmed appointment -- for a walk-in or a phone call
    a staff member is handling directly, without going through the
    voice/chat assistant. Same overlap protection as hold_slot/confirm_booking
    in availability_tools.py (confirmed/requested appointments and active
    holds for this provider, buffer-padded), just collapsed into one step
    since a staff member confirming in the admin console doesn't need a
    separate hold phase."""
    _require_scheduling_domain()
    _check_practice_access(team, practice_id)
    db = get_db()

    provider_snap = await db.collection(settings.SCHEDULING_PROVIDERS_COLLECTION).document(body.provider_id).get()
    if not provider_snap.exists or provider_snap.to_dict().get("practice_id") != practice_id:
        raise HTTPException(status_code=404, detail="Provider not found")
    provider = provider_snap.to_dict()

    type_snap = await db.collection(settings.SCHEDULING_APPOINTMENT_TYPES_COLLECTION).document(body.appointment_type_id).get()
    if not type_snap.exists or type_snap.to_dict().get("practice_id") != practice_id:
        raise HTTPException(status_code=404, detail="Appointment type not found")
    appt_type = type_snap.to_dict()

    if not body.caller_name.strip():
        raise HTTPException(status_code=400, detail="caller_name is required")

    try:
        start = datetime.fromisoformat(body.start_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="start_time must be an ISO 8601 datetime")
    if start.tzinfo is None:
        start = start.replace(tzinfo=dt_timezone.utc)
    duration = int(appt_type.get("duration_minutes", 30))
    buffer_minutes = int(appt_type.get("buffer_minutes", 0))
    end = start + timedelta(minutes=duration)
    padded_start = start - timedelta(minutes=buffer_minutes)
    padded_end = end + timedelta(minutes=buffer_minutes)

    transaction = db.transaction()

    @firestore.async_transactional
    async def _txn(txn: firestore.AsyncTransaction):
        appts_ref = db.collection(settings.SCHEDULING_APPOINTMENTS_COLLECTION)
        async for doc in appts_ref.where("practice_id", "==", practice_id).where(
            "provider_id", "==", body.provider_id
        ).where("status", "in", ["confirmed", "requested"]).stream(transaction=txn):
            d = doc.to_dict()
            if d.get("start_time") and d.get("end_time") and d["start_time"] < padded_end and padded_start < d["end_time"]:
                raise ValueError("slot_taken")

        now = datetime.now(start.tzinfo)
        holds_ref = db.collection(settings.SCHEDULING_HOLDS_COLLECTION)
        async for doc in holds_ref.where("practice_id", "==", practice_id).where(
            "provider_id", "==", body.provider_id
        ).where("status", "==", "active").stream(transaction=txn):
            d = doc.to_dict()
            if d.get("expires_at") and d["expires_at"] <= now:
                continue
            if d.get("start_time") and d.get("end_time") and d["start_time"] < padded_end and padded_start < d["end_time"]:
                raise ValueError("slot_held")

        appointment_id = str(uuid.uuid4())
        ref = appts_ref.document(appointment_id)
        txn.set(ref, {
            "practice_id": practice_id,
            "provider_id": body.provider_id,
            "provider_name": provider.get("name", ""),
            "appointment_type_id": body.appointment_type_id,
            "appointment_type_name": appt_type.get("name", ""),
            "start_time": start,
            "end_time": end,
            "caller_name": body.caller_name.strip(),
            "caller_phone": body.caller_phone.strip(),
            "caller_email": body.caller_email.strip(),
            "reason": body.reason.strip(),
            "status": "confirmed",
            "source_channel": "staff_manual",
            "created_by_team_id": team.get("team_id"),
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        })
        return appointment_id

    try:
        appointment_id = await _txn(transaction)
    except ValueError as exc:
        if str(exc) in ("slot_taken", "slot_held"):
            raise HTTPException(status_code=409, detail="That time overlaps an existing appointment or hold for this provider")
        raise

    logger.info(f"Staff {team.get('team_id')} manually booked appointment {appointment_id} for practice {practice_id}")

    # Best-effort caller confirmation email -- mirrors confirm_booking in
    # availability_tools.py. No staff-facing "new booking" notification here
    # (unlike confirm_booking) since the staff member creating this entry is
    # already the one who knows about it.
    if body.caller_email.strip():
        try:
            from src.adar.notify import send_appointment_confirmation_email
            practice_snap = await db.collection(settings.SCHEDULING_PRACTICES_COLLECTION).document(practice_id).get()
            practice_name = (practice_snap.to_dict() or {}).get("name", "your practice") if practice_snap.exists else "your practice"
            await send_appointment_confirmation_email(
                to=body.caller_email.strip(),
                caller_name=body.caller_name.strip(),
                practice_name=practice_name,
                appointment_type_name=appt_type.get("name", ""),
                provider_name=provider.get("name", ""),
                when_formatted=_format_when(start),
                appointment_id=appointment_id,
            )
        except Exception:
            logger.exception("Manual-booking confirmation email failed for %s (booking still created)", appointment_id)

    ref = db.collection(settings.SCHEDULING_APPOINTMENTS_COLLECTION).document(appointment_id)
    snap = await ref.get()
    return _booking_to_dict(snap.id, snap.to_dict())


@router.delete("/appointments/{appointment_id}")
async def cancel_booking(appointment_id: str, reason: str = "", team: dict = Depends(get_scheduling_staff)):
    """Cancel an appointment from the admin console -- same effect as the
    voice/chat assistant's cancel_appointment tool (status -> cancelled,
    same caller-facing cancellation email), just reachable by staff without
    the caller having to call back."""
    _require_scheduling_domain()
    db = get_db()
    ref = db.collection(settings.SCHEDULING_APPOINTMENTS_COLLECTION).document(appointment_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Appointment not found")
    data = snap.to_dict()
    _check_practice_access(team, data.get("practice_id"))
    if data.get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="Already cancelled")

    await ref.update({
        "status": "cancelled",
        "cancel_reason": reason,
        "cancelled_by_team_id": team.get("team_id"),
        "updated_at": firestore.SERVER_TIMESTAMP,
    })
    logger.info(f"Staff {team.get('team_id')} cancelled appointment {appointment_id}")

    caller_email = data.get("caller_email")
    if caller_email:
        try:
            from src.adar.notify import send_appointment_cancelled_email
            practice_snap = await db.collection(settings.SCHEDULING_PRACTICES_COLLECTION).document(data["practice_id"]).get()
            practice_name = (practice_snap.to_dict() or {}).get("name", "your practice") if practice_snap.exists else "your practice"
            await send_appointment_cancelled_email(
                to=caller_email,
                caller_name=data.get("caller_name", ""),
                practice_name=practice_name,
                appointment_type_name=data.get("appointment_type_name", "appointment"),
                provider_name=data.get("provider_name", "the provider"),
                when_formatted=_format_when(data.get("start_time")),
                appointment_id=appointment_id,
                cancel_reason=reason,
            )
        except Exception:
            logger.exception("Cancellation email failed for %s (cancellation still applied)", appointment_id)

    snap = await ref.get()
    return _booking_to_dict(snap.id, snap.to_dict())



# ── Practice staff accounts (admin-only — this is how a practice_staff ─────
# login gets provisioned in the first place; see the module docstring and
# get_scheduling_staff/_check_practice_access above for how it's enforced
# afterward) ─────────────────────────────────────────────────────────────

@router.post("/practices/{practice_id}/staff")
async def create_staff_account(practice_id: str, body: StaffIn, _: dict = Depends(get_admin)):
    """Provision a login scoped to exactly this practice. Reuses the same
    adar_teams collection and password hashing as every other domain's team
    login (api/routes/auth.py) so sign-in goes through the existing
    /api/auth/login + /verify-otp flow unchanged — the only difference is
    role="practice_staff" plus practice_id on the record, which
    get_scheduling_staff/_check_practice_access above key off of. Skips the
    billing/pending_payment machinery in /register entirely: staff accounts
    are active immediately, since scheduling has BILLING_ENABLED=false and a
    payment gate makes no sense for a practice's own front-desk login."""
    _require_scheduling_domain()
    db = get_db()
    practice_snap = await db.collection(settings.SCHEDULING_PRACTICES_COLLECTION).document(practice_id).get()
    if not practice_snap.exists:
        raise HTTPException(status_code=404, detail="Practice not found")

    email = body.email.strip().lower()
    auth_db = _auth_client()
    existing = auth_db.collection(TEAMS_COLLECTION).where("email", "==", email).limit(1)
    async for _doc in existing.stream():
        raise HTTPException(status_code=409, detail="Email already registered")

    team_id = f"sched_{practice_id}_{email.split('@')[0]}"[:60]
    ref = auth_db.collection(TEAMS_COLLECTION).document(team_id)
    data = {
        "team_id": team_id,
        "team_name": body.name.strip() or practice_snap.to_dict().get("name", "Practice staff"),
        "email": email,
        "password_hash": _hash_password(body.password),
        "contact_person": body.name.strip(),
        "status": "active",
        "role": "practice_staff",
        "practice_id": practice_id,
        "quota_rpm": 20,
        "quota_daily": 500,
        "created_at": datetime.now(dt_timezone.utc).isoformat(),
        "approved_at": None,
    }
    await ref.set(data)
    logger.info(f"Admin created practice-staff account {team_id} ({email}) for practice {practice_id}")
    return {"team_id": team_id, "email": email, "team_name": data["team_name"], "practice_id": practice_id}


@router.get("/practices/{practice_id}/staff")
async def list_staff_accounts(practice_id: str, _: dict = Depends(get_admin)):
    """Never returns password_hash — email/name/created_at only."""
    _require_scheduling_domain()
    auth_db = _auth_client()
    out = []
    async for doc in auth_db.collection(TEAMS_COLLECTION).where("practice_id", "==", practice_id).where("role", "==", "practice_staff").stream():
        d = doc.to_dict()
        out.append({
            "team_id": d.get("team_id", doc.id),
            "email": d.get("email"),
            "team_name": d.get("team_name"),
            "created_at": d.get("created_at"),
        })
    out.sort(key=lambda s: s.get("email") or "")
    return {"staff": out}


@router.delete("/practices/{practice_id}/staff/{team_id}")
async def delete_staff_account(practice_id: str, team_id: str, _: dict = Depends(get_admin)):
    _require_scheduling_domain()
    auth_db = _auth_client()
    ref = auth_db.collection(TEAMS_COLLECTION).document(team_id)
    snap = await ref.get()
    if not snap.exists or snap.to_dict().get("practice_id") != practice_id or snap.to_dict().get("role") != "practice_staff":
        raise HTTPException(status_code=404, detail="Staff account not found")
    await ref.delete()
    logger.info(f"Admin deleted practice-staff account {team_id} for practice {practice_id}")
    return {"deleted": team_id}
