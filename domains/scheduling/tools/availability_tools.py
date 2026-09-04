"""
domains/scheduling/tools/availability_tools.py
Core scheduling tools: availability, holds, bookings, cancellations.

Firestore schema (all documents are scoped by `practice_id` — the tenant
boundary, same role `workspace_id` plays in adar-rag). See
domains/scheduling/README.md for the full collection reference.

Concurrency note: `hold_slot` and `confirm_booking` use Firestore
transactions so two callers can't grab the same opening at once. This is
sufficient for the in-app voice MVP (turn-based, one request at a time per
practice); a live-telephony build with much higher concurrency may want a
faster lock (e.g. Redis) in front of this — see the build plan, Phase 3.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, time as dt_time, date
from typing import Optional
from zoneinfo import ZoneInfo

from google.cloud import firestore

from src.adar.config import settings
from src.adar.db import get_db, direct_query, add_document

logger = logging.getLogger(__name__)

HOLD_TTL_MINUTES = 10
DEFAULT_LEAD_TIME_MINUTES = 120       # no bookings less than 2 hours out
DEFAULT_MAX_ADVANCE_DAYS = 60         # no bookings more than 60 days out
DEFAULT_SLOT_STEP_MINUTES = 15        # candidate slots start on a 15-minute grid


# ── Pure logic: slot computation (no Firestore — easy to unit test) ──────────

def _parse_hhmm(value: str) -> dt_time:
    hour, minute = value.strip().split(":")
    return dt_time(hour=int(hour), minute=int(minute))


def compute_open_slots(
    *,
    working_hours: list[dict],
    busy_intervals: list[tuple[datetime, datetime]],
    duration_minutes: int,
    buffer_minutes: int,
    now: datetime,
    days_ahead: int = 7,
    lead_time_minutes: int = DEFAULT_LEAD_TIME_MINUTES,
    max_advance_days: int = DEFAULT_MAX_ADVANCE_DAYS,
    slot_step_minutes: int = DEFAULT_SLOT_STEP_MINUTES,
    tz: ZoneInfo = ZoneInfo("UTC"),
    max_results: int = 12,
    window_start: Optional[datetime] = None,
) -> list[datetime]:
    """Compute open appointment-start times from working hours minus busy time.

    working_hours: [{"weekday": 0-6 (Mon=0), "start": "HH:MM", "end": "HH:MM"}]
    busy_intervals: [(start, end), ...] already-booked or held spans (tz-aware)
    Returns tz-aware datetimes, earliest first, capped at max_results.

    window_start: scan `days_ahead` days starting here instead of from `now`
    (e.g. to look at one specific future week rather than "starting today").
    lead_time_minutes / max_advance_days are still measured from `now`
    regardless — browsing a future week never bypasses those guardrails.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    scan_start = window_start if window_start is not None else now
    if scan_start.tzinfo is None:
        scan_start = scan_start.replace(tzinfo=tz)
    earliest = now + timedelta(minutes=lead_time_minutes)
    latest = now + timedelta(days=max_advance_days)
    horizon_end = scan_start + timedelta(days=days_ahead)
    window_end = min(latest, horizon_end)

    by_weekday: dict[int, list[dict]] = {}
    for wh in working_hours:
        by_weekday.setdefault(int(wh["weekday"]), []).append(wh)

    slots: list[datetime] = []
    day_cursor = scan_start.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    day_count = 0
    while day_cursor <= window_end and day_count <= days_ahead + 1 and len(slots) < max_results:
        for wh in by_weekday.get(day_cursor.weekday(), []):
            day_start = datetime.combine(day_cursor.date(), _parse_hhmm(wh["start"]), tzinfo=tz)
            day_end = datetime.combine(day_cursor.date(), _parse_hhmm(wh["end"]), tzinfo=tz)
            cursor = day_start
            while cursor + timedelta(minutes=duration_minutes) <= day_end:
                slot_end = cursor + timedelta(minutes=duration_minutes)
                if earliest <= cursor <= window_end:
                    padded_start = cursor - timedelta(minutes=buffer_minutes)
                    padded_end = slot_end + timedelta(minutes=buffer_minutes)
                    overlaps = any(
                        padded_start < busy_end and busy_start < padded_end
                        for busy_start, busy_end in busy_intervals
                    )
                    if not overlaps:
                        slots.append(cursor)
                        if len(slots) >= max_results:
                            return slots
                cursor += timedelta(minutes=slot_step_minutes)
        day_cursor += timedelta(days=1)
        day_count += 1
    return slots


# ── Firestore-backed lookups ──────────────────────────────────────────────────

def _resolve_practice_id(practice_id: str) -> str:
    """Every tool takes practice_id so multi-practice deployments work later
    (§5 of the build plan), but a single-practice pilot shouldn't require the
    LLM to know or guess it — fall back to the deployment's configured default."""
    return (practice_id or "").strip() or settings.SCHEDULING_DEFAULT_PRACTICE_ID


async def _get_practice_tz(practice_id: str) -> ZoneInfo:
    rows = await direct_query(settings.SCHEDULING_PRACTICES_COLLECTION, {"practice_id": practice_id}, limit=1)
    tz_name = (rows[0].get("timezone") if rows else None) or "UTC"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        logger.warning("Unknown timezone %r for practice %s; defaulting to UTC", tz_name, practice_id)
        return ZoneInfo("UTC")


async def _find_appointment_type(practice_id: str, appointment_type_name: str) -> Optional[dict]:
    rows = await direct_query(settings.SCHEDULING_APPOINTMENT_TYPES_COLLECTION, {"practice_id": practice_id}, limit=50)
    # Missing `active` (every type seeded before the admin console added this
    # field) counts as active -- only an explicit active:false from the
    # admin console hides it. Same convention as find_practice below.
    rows = [r for r in rows if r.get("active") is not False]
    name_low = (appointment_type_name or "").strip().lower()
    for row in rows:
        if row.get("name", "").strip().lower() == name_low:
            return row
    return rows[0] if rows and not appointment_type_name else None


async def _find_provider(practice_id: str, provider_name: Optional[str]) -> Optional[dict]:
    rows = await direct_query(settings.SCHEDULING_PROVIDERS_COLLECTION, {"practice_id": practice_id, "active": True}, limit=50)
    if not provider_name:
        return rows[0] if rows else None
    name_low = provider_name.strip().lower()
    for row in rows:
        if name_low in row.get("name", "").strip().lower():
            return row
    return None


async def _busy_intervals(practice_id: str, provider_id: str, tz: ZoneInfo) -> list[tuple[datetime, datetime]]:
    now = datetime.now(tz)
    intervals: list[tuple[datetime, datetime]] = []
    appts = await direct_query(
        settings.SCHEDULING_APPOINTMENTS_COLLECTION,
        {"practice_id": practice_id, "provider_id": provider_id},
        limit=200,
    )
    for a in appts:
        if a.get("status") not in ("confirmed", "requested"):
            continue
        start, end = a.get("start_time"), a.get("end_time")
        if start and end:
            intervals.append((start, end))
    holds = await direct_query(
        settings.SCHEDULING_HOLDS_COLLECTION,
        {"practice_id": practice_id, "provider_id": provider_id, "status": "active"},
        limit=200,
    )
    for h in holds:
        expires_at = h.get("expires_at")
        if expires_at and expires_at > now:
            start, end = h.get("start_time"), h.get("end_time")
            if start and end:
                intervals.append((start, end))
    return intervals


def _format_slot(dt: datetime) -> str:
    return dt.strftime("%A, %B %-d at %-I:%M %p %Z") if hasattr(dt, "strftime") else str(dt)


# ── Agent-facing tools ─────────────────────────────────────────────────────────

async def list_appointment_types(practice_id: str = "") -> str:
    """List the appointment types this practice offers, with typical duration."""
    practice_id = _resolve_practice_id(practice_id)
    rows = await direct_query(settings.SCHEDULING_APPOINTMENT_TYPES_COLLECTION, {"practice_id": practice_id}, limit=50)
    rows = [r for r in rows if r.get("active") is not False]
    if not rows:
        return "This practice hasn't configured any appointment types yet."
    lines = [f"- **{r['name']}** ({r.get('duration_minutes', 30)} min){' — ' + r['description'] if r.get('description') else ''}" for r in rows]
    return "Available appointment types:\n" + "\n".join(lines)


async def list_providers(practice_id: str = "", appointment_type_name: str = "") -> str:
    """List bookable providers at this practice, optionally filtered by appointment type."""
    practice_id = _resolve_practice_id(practice_id)
    rows = await direct_query(settings.SCHEDULING_PROVIDERS_COLLECTION, {"practice_id": practice_id, "active": True}, limit=50)
    if appointment_type_name:
        appt_type = await _find_appointment_type(practice_id, appointment_type_name)
        if appt_type:
            rows = [r for r in rows if appt_type["doc_id"] in (r.get("appointment_type_ids") or [])]
    if not rows:
        return "No providers are available for that right now."
    lines = [f"- **{r['name']}**{' — ' + r['role'] if r.get('role') else ''}" for r in rows]
    return "Providers:\n" + "\n".join(lines)


async def find_practice(name: str = "") -> str:
    """Multi-practice lookup: resolve which practice a caller means by name
    (e.g. "Riverside Family Medicine"), or -- called with no name -- resolve
    to this deployment's single default practice if one is configured
    (SCHEDULING_DEFAULT_PRACTICE_ID). Call this once near the start of a
    conversation, before any other scheduling tool, in every deployment
    (it's cheap and correctly no-ops to the single configured practice for a
    single-practice pilot). Once it resolves to exactly one practice, carry
    that practice_id forward yourself and pass it explicitly as practice_id
    on every other tool call for the rest of this conversation -- no tool
    remembers it between calls, only the conversation does. Returns a short
    list of candidates (with each one's practice_id) when the name matches
    more than one practice, or when no name was given and there's more than
    one active practice with no configured default -- read the options back
    to the caller and ask them to choose."""
    db = get_db()
    rows: list[dict] = []
    async for doc in db.collection(settings.SCHEDULING_PRACTICES_COLLECTION).stream():
        d = doc.to_dict() or {}
        if d.get("active") is False:
            continue
        d["doc_id"] = doc.id
        rows.append(d)

    if not name and settings.SCHEDULING_DEFAULT_PRACTICE_ID:
        default = next((r for r in rows if r["doc_id"] == settings.SCHEDULING_DEFAULT_PRACTICE_ID), None)
        if default:
            return f"practice_id: {default['doc_id']} — \"{default.get('name')}\". Use this practice_id on every tool call for the rest of this conversation."

    name_low = name.strip().lower()
    matches = [r for r in rows if not name_low or name_low in r.get("name", "").strip().lower()]

    if not matches:
        return "I couldn't find a practice by that name. Could you double-check the name?"
    if len(matches) == 1:
        m = matches[0]
        return f"Found it — practice_id: {m['doc_id']} (\"{m.get('name')}\"). Use this practice_id on every tool call for the rest of this conversation."
    lines = [f"- {m.get('name')} (practice_id: {m['doc_id']})" for m in matches[:10]]
    return "More than one practice matches — which one did you mean?\n" + "\n".join(lines)


async def check_availability(
    appointment_type_name: str,
    practice_id: str = "",
    provider_name: str = "",
    days_ahead: int = 7,
    start_date: str = "",
) -> str:
    """Find open appointment slots for a given appointment type (and optionally
    a specific provider). By default looks at the next `days_ahead` days
    starting today. Pass start_date (YYYY-MM-DD) to look at a specific future
    week/window instead — e.g. after get_weekly_availability shows which weeks
    have openings and the caller picks one. Always call this before proposing
    a time to the caller."""
    practice_id = _resolve_practice_id(practice_id)
    appt_type = await _find_appointment_type(practice_id, appointment_type_name)
    if not appt_type:
        return f"I couldn't find an appointment type called '{appointment_type_name}'. Call list_appointment_types to see what's offered."
    provider = await _find_provider(practice_id, provider_name or None)
    if not provider:
        return "I couldn't find an available provider for that appointment type."

    tz = await _get_practice_tz(practice_id)
    window_start = None
    if start_date:
        try:
            window_start = datetime.combine(datetime.fromisoformat(start_date).date(), dt_time(0, 0), tzinfo=tz)
        except ValueError:
            return "That doesn't look like a valid date — please use YYYY-MM-DD."
    busy = await _busy_intervals(practice_id, provider["doc_id"], tz)
    slots = compute_open_slots(
        working_hours=provider.get("working_hours") or [],
        busy_intervals=busy,
        duration_minutes=int(appt_type.get("duration_minutes", 30)),
        buffer_minutes=int(appt_type.get("buffer_minutes", 0)),
        now=datetime.now(tz),
        days_ahead=days_ahead,
        tz=tz,
        window_start=window_start,
    )
    window_desc = f"the week of {window_start.strftime('%B %-d')}" if window_start else f"the next {days_ahead} days"
    if not slots:
        return f"{provider['name']} has no open '{appt_type['name']}' slots in {window_desc}. Try a different week or provider."
    # Give the caller-facing text alongside the exact ISO timestamp (with UTC
    # offset) for the model to copy verbatim into hold_slot's slot_start_iso
    # -- don't reconstruct it from the human-readable time, since that's lost
    # the offset and led to hold_slot crashing on naive-vs-aware comparisons.
    lines = [f"{i + 1}. {_format_slot(s)} [slot_start_iso: {s.isoformat()}]" for i, s in enumerate(slots)]
    return (
        f"Open '{appt_type['name']}' slots with {provider['name']} ({window_desc}):\n" + "\n".join(lines) +
        "\n\nTo book one, tell me which time and your name — I'll hold it for a few minutes while we confirm. "
        "When calling hold_slot, pass the bracketed slot_start_iso value exactly as shown, not a reconstructed time."
    )


async def get_weekly_availability(
    appointment_type_name: str,
    practice_id: str = "",
    provider_name: str = "",
    weeks_ahead: int = 8,
) -> str:
    """Give a broad view of which upcoming weeks have any openings at all —
    call this when the caller wants to browse rather than pick a specific day
    (e.g. "what's open over the next couple months"). weeks_ahead=8 covers
    about two months. Returns which weekdays have at least one open slot per
    week, NOT specific times — once the caller picks a week, call
    check_availability with start_date set to that week's Monday to get exact
    times to offer."""
    practice_id = _resolve_practice_id(practice_id)
    appt_type = await _find_appointment_type(practice_id, appointment_type_name)
    if not appt_type:
        return f"I couldn't find an appointment type called '{appointment_type_name}'. Call list_appointment_types to see what's offered."
    provider = await _find_provider(practice_id, provider_name or None)
    if not provider:
        return "I couldn't find an available provider for that appointment type."

    tz = await _get_practice_tz(practice_id)
    now = datetime.now(tz)
    busy = await _busy_intervals(practice_id, provider["doc_id"], tz)
    # One scan across the whole span, generous max_results so it isn't cut
    # off partway through — this is a summary pass, not the final slot list.
    slots = compute_open_slots(
        working_hours=provider.get("working_hours") or [],
        busy_intervals=busy,
        duration_minutes=int(appt_type.get("duration_minutes", 30)),
        buffer_minutes=int(appt_type.get("buffer_minutes", 0)),
        now=now,
        days_ahead=weeks_ahead * 7,
        tz=tz,
        max_results=2000,
    )
    if not slots:
        return (
            f"{provider['name']} has no open '{appt_type['name']}' slots in the next "
            f"{weeks_ahead} weeks. Try a different provider or appointment type."
        )

    # Group by ISO week (Monday-anchored), independent of the practice's
    # max_advance_days — a week can show as partially open right up against
    # that cutoff, which is expected, not a bug.
    weeks: dict[date, set[str]] = {}
    for s in slots:
        monday = s.date() - timedelta(days=s.weekday())
        weeks.setdefault(monday, set()).add(s.strftime("%a"))

    lines = []
    for monday in sorted(weeks.keys()):
        sunday = monday + timedelta(days=6)
        days_open = sorted(
            weeks[monday],
            key=lambda d: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].index(d),
        )
        lines.append(
            f"Week of {monday.strftime('%b %-d')}\u2013{sunday.strftime('%b %-d')}: "
            + ", ".join(days_open)
        )

    return (
        f"Weeks with openings for '{appt_type['name']}' with {provider['name']} "
        f"(next {weeks_ahead} weeks):\n" + "\n".join(lines) +
        "\n\nAsk which week works, then call check_availability with that week's "
        "Monday as start_date to get exact times."
    )


async def hold_slot(
    appointment_type_name: str,
    provider_name: str,
    slot_start_iso: str,
    caller_name: str,
    practice_id: str = "",
) -> str:
    """Place a short-lived hold on a specific slot (from check_availability's
    results) so it can't be double-booked while the caller confirms. Returns a
    hold_id — pass it to confirm_booking within a few minutes."""
    practice_id = _resolve_practice_id(practice_id)
    appt_type = await _find_appointment_type(practice_id, appointment_type_name)
    provider = await _find_provider(practice_id, provider_name)
    if not appt_type or not provider:
        return "I couldn't match that appointment type and provider — please check availability again."

    try:
        start = datetime.fromisoformat(slot_start_iso)
    except ValueError:
        return "That doesn't look like a valid time — please pick one of the times I listed."
    if start.tzinfo is None:
        # check_availability only ever shows the caller/LLM a human-readable
        # time string (see _format_slot), never a raw offset-aware ISO
        # timestamp -- so the model sometimes reconstructs slot_start_iso
        # without a UTC offset. Assume it means the practice's own local
        # time (which is what the human-readable string was rendered in),
        # rather than crashing when comparing against Firestore's
        # timezone-aware timestamps below.
        start = start.replace(tzinfo=await _get_practice_tz(practice_id))
    duration = int(appt_type.get("duration_minutes", 30))
    end = start + timedelta(minutes=duration)

    db = get_db()
    transaction = db.transaction()

    @firestore.async_transactional
    async def _txn(txn: firestore.AsyncTransaction):
        # Re-check for overlapping confirmed appointments / active holds inside the transaction.
        appts_ref = db.collection(settings.SCHEDULING_APPOINTMENTS_COLLECTION)
        holds_ref = db.collection(settings.SCHEDULING_HOLDS_COLLECTION)
        now = datetime.now(start.tzinfo or ZoneInfo("UTC"))

        async for doc in appts_ref.where("practice_id", "==", practice_id).where(
            "provider_id", "==", provider["doc_id"]
        ).where("status", "in", ["confirmed", "requested"]).stream(transaction=txn):
            d = doc.to_dict()
            if d.get("start_time") and d.get("end_time") and d["start_time"] < end and start < d["end_time"]:
                raise ValueError("slot_taken")

        async for doc in holds_ref.where("practice_id", "==", practice_id).where(
            "provider_id", "==", provider["doc_id"]
        ).where("status", "==", "active").stream(transaction=txn):
            d = doc.to_dict()
            if d.get("expires_at") and d["expires_at"] <= now:
                continue
            if d.get("start_time") and d.get("end_time") and d["start_time"] < end and start < d["end_time"]:
                raise ValueError("slot_held")

        hold_id = str(uuid.uuid4())
        txn.set(holds_ref.document(hold_id), {
            "practice_id": practice_id,
            "provider_id": provider["doc_id"],
            "provider_name": provider["name"],
            "appointment_type_id": appt_type["doc_id"],
            "appointment_type_name": appt_type["name"],
            "start_time": start,
            "end_time": end,
            "caller_name": caller_name,
            "status": "active",
            "expires_at": now + timedelta(minutes=HOLD_TTL_MINUTES),
            "created_at": firestore.SERVER_TIMESTAMP,
        })
        return hold_id

    try:
        hold_id = await _txn(transaction)
    except ValueError as exc:
        if str(exc) in ("slot_taken", "slot_held"):
            return "Sorry — that slot was just taken. Please call check_availability again for current openings."
        raise

    return (
        f"Held {_format_slot(start)} with {provider['name']} for {HOLD_TTL_MINUTES} minutes "
        f"(hold_id: {hold_id}). Confirm the caller's phone number and reason for visit, then call "
        f"confirm_booking to finish booking it."
    )


async def confirm_booking(
    hold_id: str,
    caller_name: str,
    caller_phone: str,
    practice_id: str = "",
    reason: str = "",
    caller_email: str = "",
) -> str:
    """Convert an active hold (from hold_slot) into a confirmed appointment.
    Fails if the hold has expired or was already used — call hold_slot again
    in that case. If caller_email is given, a confirmation email is sent
    after the booking is confirmed (best-effort — a failed send never undoes
    the booking, since Firestore is already the source of truth by then)."""
    practice_id = _resolve_practice_id(practice_id)
    db = get_db()
    transaction = db.transaction()
    hold_ref = db.collection(settings.SCHEDULING_HOLDS_COLLECTION).document(hold_id)

    @firestore.async_transactional
    async def _txn(txn: firestore.AsyncTransaction):
        snap = await hold_ref.get(transaction=txn)
        if not snap.exists:
            raise ValueError("not_found")
        hold = snap.to_dict()
        if hold.get("practice_id") != practice_id:
            raise ValueError("not_found")
        if hold.get("status") != "active":
            raise ValueError("already_used")
        now = datetime.now(hold["start_time"].tzinfo or ZoneInfo("UTC"))
        if hold.get("expires_at") and hold["expires_at"] <= now:
            raise ValueError("expired")

        appointment_id = str(uuid.uuid4())
        appt_ref = db.collection(settings.SCHEDULING_APPOINTMENTS_COLLECTION).document(appointment_id)
        txn.set(appt_ref, {
            "practice_id": practice_id,
            "provider_id": hold["provider_id"],
            "provider_name": hold["provider_name"],
            "appointment_type_id": hold["appointment_type_id"],
            "appointment_type_name": hold["appointment_type_name"],
            "start_time": hold["start_time"],
            "end_time": hold["end_time"],
            "caller_name": caller_name,
            "caller_phone": caller_phone,
            "caller_email": caller_email,
            "reason": reason,
            "status": "confirmed",
            "source_channel": "voice_in_app",
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        })
        txn.update(hold_ref, {"status": "confirmed"})
        return appointment_id, hold["start_time"], hold["provider_name"], hold["appointment_type_name"]

    try:
        appointment_id, start, provider_name, appointment_type_name = await _txn(transaction)
    except ValueError as exc:
        reason_map = {
            "not_found": "I can't find that hold — please check availability and hold a slot again.",
            "already_used": "That hold was already confirmed or released — please check availability again.",
            "expired": "That hold expired — please check availability and hold a slot again.",
        }
        return reason_map.get(str(exc), "I couldn't confirm that booking — please try again.")

    practice_rows = await direct_query(settings.SCHEDULING_PRACTICES_COLLECTION, {"practice_id": practice_id}, limit=1)
    practice = practice_rows[0] if practice_rows else {}
    practice_name = practice.get("name") or "your practice"

    email_sent = False
    if caller_email:
        try:
            from src.adar.notify import send_appointment_confirmation_email
            await send_appointment_confirmation_email(
                to=caller_email,
                caller_name=caller_name,
                practice_name=practice_name,
                appointment_type_name=appointment_type_name,
                provider_name=provider_name,
                when_formatted=_format_slot(start),
                appointment_id=appointment_id,
            )
            email_sent = True
        except Exception:
            logger.exception("Appointment confirmation email failed for %s (booking still confirmed)", appointment_id)

    # Staff-facing "new booking" notification — separate from the caller's
    # confirmation email above and never allowed to affect it: this is
    # purely so front-desk staff learn about a new booking without opening
    # the admin calendar. Falls back to the platform ADMIN_EMAIL when the
    # practice hasn't set its own notification_email (matches today's
    # reality that one operator runs every practice on a deployment until
    # per-practice staff logins exist).
    notify_to = practice.get("notification_email") or settings.ADMIN_EMAIL
    if notify_to:
        try:
            from src.adar.notify import send_new_booking_notification_email
            await send_new_booking_notification_email(
                to=notify_to,
                practice_name=practice_name,
                caller_name=caller_name,
                caller_phone=caller_phone,
                caller_email=caller_email,
                appointment_type_name=appointment_type_name,
                provider_name=provider_name,
                when_formatted=_format_slot(start),
                appointment_id=appointment_id,
                reason=reason,
            )
        except Exception:
            logger.exception("New-booking staff notification failed for %s (booking still confirmed)", appointment_id)

    result = (
        f"Booked. {caller_name} is confirmed with {provider_name} for {_format_slot(start)} "
        f"(confirmation ID: {appointment_id[:8]})."
    )
    if caller_email:
        result += f" A confirmation email is on its way to {caller_email}." if email_sent else (
            " I tried to send a confirmation email but it didn't go through — give them the "
            "confirmation ID directly."
        )
    else:
        result += " No email was given, so make sure they have the confirmation ID."
    return result


async def cancel_appointment(appointment_id: str, practice_id: str = "", reason: str = "") -> str:
    """Cancel a confirmed appointment by its confirmation ID."""
    practice_id = _resolve_practice_id(practice_id)
    db = get_db()
    ref = db.collection(settings.SCHEDULING_APPOINTMENTS_COLLECTION).document(appointment_id)
    snap = await ref.get()
    if not snap.exists or snap.to_dict().get("practice_id") != practice_id:
        return "I couldn't find an appointment with that confirmation ID."
    data = snap.to_dict()
    if data.get("status") == "cancelled":
        return "That appointment is already cancelled."
    await ref.update({
        "status": "cancelled",
        "cancel_reason": reason,
        "updated_at": firestore.SERVER_TIMESTAMP,
    })

    caller_email = data.get("caller_email")
    email_sent = False
    if caller_email:
        try:
            from src.adar.notify import send_appointment_cancelled_email
            practice_rows = await direct_query(settings.SCHEDULING_PRACTICES_COLLECTION, {"practice_id": practice_id}, limit=1)
            practice_name = practice_rows[0].get("name") if practice_rows else "your practice"
            await send_appointment_cancelled_email(
                to=caller_email,
                caller_name=data.get("caller_name", ""),
                practice_name=practice_name,
                appointment_type_name=data.get("appointment_type_name", "appointment"),
                provider_name=data.get("provider_name", "the provider"),
                when_formatted=_format_slot(data["start_time"]),
                appointment_id=appointment_id,
                cancel_reason=reason,
            )
            email_sent = True
        except Exception:
            logger.exception("Cancellation email failed for %s (cancellation still applied)", appointment_id)

    result = f"Cancelled the {data.get('appointment_type_name', 'appointment')} with {data.get('provider_name', 'the provider')} on {_format_slot(data['start_time'])}."
    if caller_email:
        result += " A cancellation email was sent." if email_sent else " (Cancellation email failed to send — let them know directly.)"
    return result


async def reschedule_appointment(appointment_id: str, practice_id: str = "") -> str:
    """Start a reschedule: cancels the existing appointment and tells the
    caller to pick a new time via check_availability + hold_slot. Kept as two
    steps deliberately, so the caller always confirms the new time before the
    old one is given up for good."""
    result = await cancel_appointment(appointment_id, practice_id=practice_id, reason="reschedule requested")
    if result.startswith("Cancelled"):
        return result + " Now let's find a new time — what date or provider works best?"
    return result


async def list_my_appointments(caller_phone: str, practice_id: str = "") -> str:
    """Look up upcoming confirmed appointments by the caller's phone number
    (a soft identity match — no clinical data is read back)."""
    practice_id = _resolve_practice_id(practice_id)
    rows = await direct_query(
        settings.SCHEDULING_APPOINTMENTS_COLLECTION,
        {"practice_id": practice_id, "caller_phone": caller_phone, "status": "confirmed"},
        limit=20,
    )
    if not rows:
        return "I don't see any upcoming appointments under that phone number."
    lines = [
        f"- {r.get('appointment_type_name', 'Appointment')} with {r.get('provider_name', 'provider')} "
        f"on {_format_slot(r['start_time'])} (confirmation ID: {r['doc_id'][:8]})"
        for r in rows
    ]
    return "Upcoming appointments:\n" + "\n".join(lines)
