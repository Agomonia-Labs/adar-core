"""
api/routes/scheduling_admin.py — Admin-only CRUD for the scheduling domain's
practices, providers, and appointment types, plus a bookings query endpoint
for the admin console's calendar view.

All routes require admin JWT (role=admin) — same auth as api/routes/admin.py,
just scoped to the scheduling data model instead of adar_teams. Only mounted
usefully for DOMAIN=scheduling (every SCHEDULING_*_COLLECTION setting is ""
for any other domain — see src/adar/config.py — so every route 404s cleanly
elsewhere rather than risking a Firestore call against an empty collection
name).

This is intentionally a plain CRUD layer, not the booking engine — the
booking engine (holds/confirm/cancel/reschedule with transactional
double-booking protection) stays in domains/scheduling/tools/availability_tools.py
and is untouched by this file. An admin editing a provider's working hours
here takes effect immediately for the chat agent too, since availability is
always computed live against current Firestore state (see that module's
docstring).
"""
import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from google.cloud import firestore

from src.adar.config import settings
from api.routes.auth import get_admin

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


class PracticePatch(BaseModel):
    name: Optional[str] = None
    timezone: Optional[str] = None
    lead_time_minutes: Optional[int] = None
    max_advance_days: Optional[int] = None
    active: Optional[bool] = None


class ProviderIn(BaseModel):
    name: str
    role: str = ""
    appointment_type_ids: list[str] = []
    working_hours: list[WorkingHour] = []


class ProviderPatch(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
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
        "active": True,
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    await ref.set(data)
    logger.info(f"Admin created practice {practice_id} ({body.name})")
    return _doc_to_dict(await ref.get())


@router.patch("/practices/{practice_id}")
async def update_practice(practice_id: str, body: PracticePatch, _: dict = Depends(get_admin)):
    _require_scheduling_domain()
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
async def list_providers(practice_id: str, _: dict = Depends(get_admin)):
    _require_scheduling_domain()
    db = get_db()
    out = []
    async for doc in db.collection(settings.SCHEDULING_PROVIDERS_COLLECTION) \
            .where("practice_id", "==", practice_id).stream():
        out.append(_doc_to_dict(doc))
    out.sort(key=lambda p: p.get("name", ""))
    return {"providers": out}


@router.post("/practices/{practice_id}/providers")
async def create_provider(practice_id: str, body: ProviderIn, _: dict = Depends(get_admin)):
    _require_scheduling_domain()
    db = get_db()
    practice_snap = await db.collection(settings.SCHEDULING_PRACTICES_COLLECTION).document(practice_id).get()
    if not practice_snap.exists:
        raise HTTPException(status_code=404, detail="Practice not found")
    ref = db.collection(settings.SCHEDULING_PROVIDERS_COLLECTION).document()
    data = {
        "practice_id": practice_id,
        "name": body.name.strip(),
        "role": body.role,
        "appointment_type_ids": body.appointment_type_ids,
        "working_hours": [wh.model_dump() for wh in body.working_hours],
        "active": True,
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    await ref.set(data)
    logger.info(f"Admin created provider {ref.id} ({body.name}) for practice {practice_id}")
    return _doc_to_dict(await ref.get())


@router.patch("/providers/{provider_id}")
async def update_provider(provider_id: str, body: ProviderPatch, _: dict = Depends(get_admin)):
    _require_scheduling_domain()
    db = get_db()
    ref = db.collection(settings.SCHEDULING_PROVIDERS_COLLECTION).document(provider_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Provider not found")
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
async def list_appointment_types(practice_id: str, _: dict = Depends(get_admin)):
    _require_scheduling_domain()
    db = get_db()
    out = []
    async for doc in db.collection(settings.SCHEDULING_APPOINTMENT_TYPES_COLLECTION) \
            .where("practice_id", "==", practice_id).stream():
        out.append(_doc_to_dict(doc))
    out.sort(key=lambda t: t.get("name", ""))
    return {"appointment_types": out}


@router.post("/practices/{practice_id}/appointment-types")
async def create_appointment_type(practice_id: str, body: AppointmentTypeIn, _: dict = Depends(get_admin)):
    _require_scheduling_domain()
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
async def update_appointment_type(type_id: str, body: AppointmentTypePatch, _: dict = Depends(get_admin)):
    _require_scheduling_domain()
    db = get_db()
    ref = db.collection(settings.SCHEDULING_APPOINTMENT_TYPES_COLLECTION).document(type_id)
    snap = await ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Appointment type not found")
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
    _: dict = Depends(get_admin),
):
    """Bookings whose start_time falls in [start, end) (ISO 8601 datetimes,
    e.g. from a calendar's visible week/month range). Filtered in Python
    (not a Firestore range query) to avoid needing a new composite index —
    matches the pattern already used by availability_tools.py's own queries,
    and appointment volume per practice is small enough this is cheap."""
    _require_scheduling_domain()
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
