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
import re
import uuid
from datetime import datetime, timedelta, time as dt_time, date
from typing import Optional
from zoneinfo import ZoneInfo

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.field_path import FieldPath
from google.adk.tools import ToolContext

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

def _resolve_practice_id(practice_id: str, tool_context: ToolContext = None) -> str:
    """Every tool takes practice_id so multi-practice deployments work later
    (§5 of the build plan), but a single-practice pilot shouldn't require the
    LLM to know or guess it — fall back to the deployment's configured default.

    A multi-practice caller (e.g. ADAR Eats' dine-in assistant, one restaurant
    per practice; Front Desk's multi-practice "Ask ADAR") can't rely on that
    global default, and api/main.py's scheduling_guest_chat already grounds
    every turn by writing the app's actual selected practice_id into
    tool_context.state["resolved_practice_id"] (the same mechanism find_practice
    uses) alongside a text instruction telling the model to pass practice_id on
    every tool call. The text instruction is the only thing most of these
    tools relied on until now -- if the model ever omits the optional
    practice_id argument on a single turn (nothing stops it; it's not
    required), the call silently fell through all the way to
    SCHEDULING_DEFAULT_PRACTICE_ID (a different practice entirely, with its
    own hours/timezone) instead of the practice the conversation is actually
    about. Checking tool_context.state here first closes that gap
    deterministically, the same way customer identity is already threaded
    through state rather than left to the model to repeat correctly."""
    explicit = (practice_id or "").strip()
    if explicit:
        return explicit
    if tool_context is not None:
        try:
            grounded = (tool_context.state.get("resolved_practice_id") or "").strip()
        except Exception:
            grounded = ""
        if grounded:
            return grounded
    return settings.SCHEDULING_DEFAULT_PRACTICE_ID


async def _get_practice_tz(practice_id: str) -> ZoneInfo:
    rows = await direct_query(settings.SCHEDULING_PRACTICES_COLLECTION, {"practice_id": practice_id}, limit=1)
    tz_name = (rows[0].get("timezone") if rows else None) or "UTC"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        logger.warning("Unknown timezone %r for practice %s; defaulting to UTC", tz_name, practice_id)
        return ZoneInfo("UTC")


async def _get_practice_guardrails(practice_id: str) -> tuple[ZoneInfo, int, int, int]:
    """Like _get_practice_tz, but also returns the practice's own
    lead_time_minutes/max_advance_days/slot_step_minutes. These are stored
    on the practice doc at creation (see scheduling_admin.py's PracticeIn /
    run_ingestion.py) but check_availability/get_weekly_availability
    previously never read them back -- they silently fell through to
    compute_open_slots's hardcoded module defaults (120min/60days/15min)
    for every practice regardless of what was actually configured. A
    practice that needs a tighter window (e.g. a restaurant capped at
    max_advance_days=7 for dine-in reservations) wasn't actually enforced,
    and nor was a coarser slot_step_minutes (e.g. a restaurant offering
    hour-aligned reservation times instead of every 15 minutes). One
    query, reused for tz + all three guardrails."""
    rows = await direct_query(settings.SCHEDULING_PRACTICES_COLLECTION, {"practice_id": practice_id}, limit=1)
    doc = rows[0] if rows else {}
    tz_name = doc.get("timezone") or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        logger.warning("Unknown timezone %r for practice %s; defaulting to UTC", tz_name, practice_id)
        tz = ZoneInfo("UTC")
    lead_time_minutes = int(doc.get("lead_time_minutes") or DEFAULT_LEAD_TIME_MINUTES)
    max_advance_days = int(doc.get("max_advance_days") or DEFAULT_MAX_ADVANCE_DAYS)
    slot_step_minutes = int(doc.get("slot_step_minutes") or DEFAULT_SLOT_STEP_MINUTES)
    return tz, lead_time_minutes, max_advance_days, slot_step_minutes


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


_ROLE_SEATS_RE = re.compile(r"^(\d+)-top$")


def _seats_from_role(role: str) -> int:
    """Dine-in tables are stored as providers with role="<seats>-top" (e.g.
    "4-top") -- see adar-rag's backend/routes/restaurant.py, which uses the
    identical convention for the structured booking screen's table tiers.
    Returns 0 (never matches a party size) for a non-dine-in provider whose
    role is blank or doesn't follow that pattern, e.g. a clinician."""
    m = _ROLE_SEATS_RE.match((role or "").strip())
    return int(m.group(1)) if m else 0


async def _find_providers_for_party_size(practice_id: str, party_size: int) -> list[dict]:
    """A restaurant has several same-size tables (separate providers, grouped
    into a tier only for display -- see the dine-in build plan), so "do you
    have a table for 4" must check every table that seats 4+, not just one.
    _find_provider(practice_id, None) -- the old behavior when the caller
    gave no specific resource name -- picks a single arbitrary provider
    (Firestore's first result) and reports based on that one table alone;
    if that particular table happened to be busy, the caller was told
    "no availability" even with other same-size tables standing empty.
    Returns every active table that seats at least party_size, smallest
    first (so a party of 2 is offered a 2-top before a 6-top), mirroring
    adar-rag's own tiering/ordering for the structured booking screen."""
    rows = await direct_query(settings.SCHEDULING_PROVIDERS_COLLECTION, {"practice_id": practice_id, "active": True}, limit=50)
    candidates = [r for r in rows if _seats_from_role(r.get("role") or "") >= party_size]
    candidates.sort(key=lambda r: _seats_from_role(r.get("role") or ""))
    return candidates


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


def _format_slot(dt: datetime, tz: Optional[ZoneInfo] = None) -> str:
    """Human-readable local time for a slot/appointment. Pass `tz` (the
    practice's own ZoneInfo, from _get_practice_tz/_get_practice_guardrails)
    whenever `dt` was just read back out of a Firestore document --
    Firestore always stores/returns timestamps as UTC-aware regardless of
    the zone used when the value was originally written, so an unconverted
    dt here renders "UTC" no matter what the restaurant's own hours are
    configured in. A dt that's already in-memory in the practice's own zone
    (e.g. hold_slot's own `start`, or check_availability's computed slots,
    both never re-read from Firestore before formatting) doesn't need it,
    so tz stays optional. Mirrors api/routes/scheduling_guest.py's
    _format_when, which already does this for booking-confirmation emails."""
    if tz is not None and hasattr(dt, "astimezone"):
        dt = dt.astimezone(tz)
    return dt.strftime("%A, %B %-d at %-I:%M %p %Z") if hasattr(dt, "strftime") else str(dt)


# ── Agent-facing tools ─────────────────────────────────────────────────────────

async def list_appointment_types(practice_id: str = "", tool_context: ToolContext = None) -> str:
    """List the appointment types this practice offers, with typical duration."""
    practice_id = _resolve_practice_id(practice_id, tool_context)
    rows = await direct_query(settings.SCHEDULING_APPOINTMENT_TYPES_COLLECTION, {"practice_id": practice_id}, limit=50)
    rows = [r for r in rows if r.get("active") is not False]
    if not rows:
        return "This practice hasn't configured any appointment types yet."
    lines = [f"- **{r['name']}** ({r.get('duration_minutes', 30)} min){' — ' + r['description'] if r.get('description') else ''}" for r in rows]
    return "Available appointment types:\n" + "\n".join(lines)


async def list_providers(practice_id: str = "", appointment_type_name: str = "", tool_context: ToolContext = None) -> str:
    """List bookable providers at this practice, optionally filtered by appointment type."""
    practice_id = _resolve_practice_id(practice_id, tool_context)
    rows = await direct_query(settings.SCHEDULING_PROVIDERS_COLLECTION, {"practice_id": practice_id, "active": True}, limit=50)
    if appointment_type_name:
        appt_type = await _find_appointment_type(practice_id, appointment_type_name)
        if appt_type:
            rows = [r for r in rows if appt_type["doc_id"] in (r.get("appointment_type_ids") or [])]
    if not rows:
        return "No providers are available for that right now."
    lines = [f"- **{r['name']}**{' — ' + r['role'] if r.get('role') else ''}" for r in rows]
    return "Providers:\n" + "\n".join(lines)


async def find_practice(name: str = "", tool_context: ToolContext = None) -> str:
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
            if tool_context is not None:
                tool_context.state["resolved_practice_id"] = default["doc_id"]
            return f"practice_id: {default['doc_id']} — \"{default.get('name')}\". Use this practice_id on every tool call for the rest of this conversation."

    name_low = name.strip().lower()
    matches = [r for r in rows if not name_low or name_low in r.get("name", "").strip().lower()]

    if not matches:
        return "I couldn't find a practice by that name. Could you double-check the name?"
    if len(matches) == 1:
        m = matches[0]
        if tool_context is not None:
            tool_context.state["resolved_practice_id"] = m["doc_id"]
        return f"Found it — practice_id: {m['doc_id']} (\"{m.get('name')}\"). Use this practice_id on every tool call for the rest of this conversation."
    lines = [f"- {m.get('name')} (practice_id: {m['doc_id']})" for m in matches[:10]]
    return "More than one practice matches — which one did you mean?\n" + "\n".join(lines)


# Matches the time-of-day vocabulary given to the model in
# agents_config.scheduling.json's scheduling_agent instructions, so the
# two stay in lockstep -- end hour is exclusive except "night"/"tonight",
# which is open-ended (filtered by >= start hour only, so it naturally
# includes everything up to closing regardless of how late that is).
_TIME_OF_DAY_WINDOWS: dict[str, tuple[int, Optional[int]]] = {
    "morning": (6, 11),
    "noon": (11, 13),
    "midday": (11, 13),
    "afternoon": (13, 17),
    "evening": (17, 20),
    "night": (17, None),
    "tonight": (17, None),
}


def _filter_slots_by_time_of_day(slots: list[datetime], time_of_day: str) -> list[datetime]:
    window = _TIME_OF_DAY_WINDOWS.get((time_of_day or "").strip().lower())
    if not window:
        return slots
    start_hour, end_hour = window
    return [s for s in slots if s.hour >= start_hour and (end_hour is None or s.hour < end_hour)]


async def check_availability(
    appointment_type_name: str,
    practice_id: str = "",
    provider_name: str = "",
    party_size: int = 0,
    days_ahead: int = 7,
    start_date: str = "",
    time_of_day: str = "",
    tool_context: ToolContext = None,
) -> str:
    """Find open appointment slots for a given appointment type. By default
    looks at the next `days_ahead` days starting today. Pass start_date
    (YYYY-MM-DD) to look at a specific future week/window instead -- e.g.
    after get_weekly_availability shows which weeks have openings and the
    caller picks one. Always call this before proposing a time to the caller.

    Pass party_size (number of guests) whenever the caller gave one, instead
    of provider_name -- a dine-in practice has several identical tables of
    the same size, modeled as separate providers, and this checks every
    table that fits that many people rather than one arbitrary one (a
    caller is never going to name a specific table). Only pass provider_name
    when the caller named a specific resource directly (e.g. a clinician by
    name) -- leave party_size at 0 in that case.

    Pass time_of_day ("morning", "noon", "afternoon", "evening", or
    "night"/"tonight") whenever the caller named one, instead of filtering
    the results yourself before speaking -- this guarantees the slots you
    read back actually fall in the window the caller asked for, rather than
    relying on you to notice and discard a mismatched one (e.g. a caller
    asking for "tomorrow night" must never be read a morning or afternoon
    time). Leave it blank when the caller didn't name a time of day."""
    practice_id = _resolve_practice_id(practice_id, tool_context)
    appt_type = await _find_appointment_type(practice_id, appointment_type_name)
    if not appt_type:
        return f"I couldn't find an appointment type called '{appointment_type_name}'. Call list_appointment_types to see what's offered."

    providers: list[dict]
    if provider_name:
        provider = await _find_provider(practice_id, provider_name)
        if not provider:
            return "I couldn't find an available provider for that appointment type."
        providers = [provider]
        subject = provider["name"]
    else:
        # No specific resource named -- check every active provider that
        # fits (party_size filters by size; party_size=0 means "any size",
        # so this still checks ALL of them). This is deliberately the
        # default whenever provider_name is blank, not conditioned on the
        # model actually having passed party_size: relying on the model to
        # remember a new argument every time proved unreliable (the same
        # lesson as this practice's other instruction-only fixes this
        # session), so "no name given" now always means "check everything",
        # which is also simply more correct than picking one arbitrary
        # provider even for a single-resource-per-visit practice.
        providers = await _find_providers_for_party_size(practice_id, party_size or 0)
        if not providers:
            return (f"No table here seats a party of {party_size}." if party_size
                    else "I couldn't find an available provider for that appointment type.")
        subject = f"a table for {party_size}" if party_size else "any available provider"

    tz, lead_time_minutes, max_advance_days, slot_step_minutes = await _get_practice_guardrails(practice_id)
    window_start = None
    if start_date:
        try:
            window_start = datetime.combine(datetime.fromisoformat(start_date).date(), dt_time(0, 0), tzinfo=tz)
        except ValueError:
            return "That doesn't look like a valid date — please use YYYY-MM-DD."

    # Union the open slots across every qualifying table/provider -- a time
    # is offerable as long as AT LEAST ONE of them is free then, not only
    # the first one Firestore happens to return (see
    # _find_providers_for_party_size for why checking just one table was
    # the actual bug: a caller was told "no availability" some nights
    # purely because the one table checked was busy, with other same-size
    # tables standing empty).
    all_slots_set: set[datetime] = set()
    for p in providers:
        busy = await _busy_intervals(practice_id, p["doc_id"], tz)
        p_slots = compute_open_slots(
            working_hours=p.get("working_hours") or [],
            busy_intervals=busy,
            duration_minutes=int(appt_type.get("duration_minutes", 30)),
            buffer_minutes=int(appt_type.get("buffer_minutes", 0)),
            now=datetime.now(tz),
            days_ahead=days_ahead,
            lead_time_minutes=lead_time_minutes,
            max_advance_days=max_advance_days,
            tz=tz,
            window_start=window_start,
            slot_step_minutes=slot_step_minutes,
            # compute_open_slots defaults to max_results=12 and stops
            # scanning the instant it hits that cap -- fine for "give me a
            # few options", wrong here: with a normal multi-hour working day
            # (e.g. 11am-10pm), the 12th candidate (at slot_step_minutes
            # apart) can land in the early afternoon, so it never even
            # reaches evening/night slots to report them. That's what made
            # the time_of_day filter correctly report "no night slots" --
            # the slots it was filtering had already been truncated away
            # before generation got that far. A generous cap here (we
            # filter/trim down to a caller-facing 12 AFTER merging all
            # providers and applying time_of_day below) ensures a full
            # day's -- or week's -- worth of real candidates actually gets
            # generated before any filtering happens.
            max_results=500,
        )
        all_slots_set.update(p_slots)
    all_slots = sorted(all_slots_set)

    window_desc = f"the week of {window_start.strftime('%B %-d')}" if window_start else f"the next {days_ahead} days"
    if not all_slots:
        return f"{subject} has no open '{appt_type['name']}' slots in {window_desc}. Try a different week{' or party size' if party_size else ' or provider'}."

    slots = _filter_slots_by_time_of_day(all_slots, time_of_day)
    if not slots:
        # Slots exist that day/week, just not in the window the caller
        # named -- say so plainly instead of reading back one of the
        # mismatched ones (the actual bug being fixed here: a caller
        # asking for "tomorrow night" was being told "no" and then handed
        # a morning slot anyway).
        label = (time_of_day or "").strip().lower()
        other_times_exist = any(True for _ in all_slots)
        suffix = " There are openings at other times — want to hear those instead?" if other_times_exist else ""
        return f"{subject} has no {label} '{appt_type['name']}' slots in {window_desc}.{suffix}"

    # Cap how many we read back after merging/filtering, same as the old
    # single-provider max_results=12 default.
    slots = slots[:12]

    # Give the caller-facing text alongside the exact ISO timestamp (with UTC
    # offset) for the model to copy verbatim into hold_slot's slot_start_iso
    # -- don't reconstruct it from the human-readable time, since that's lost
    # the offset and led to hold_slot crashing on naive-vs-aware comparisons.
    lines = [f"{i + 1}. {_format_slot(s)} [slot_start_iso: {s.isoformat()}]" for i, s in enumerate(slots)]
    return (
        f"Open '{appt_type['name']}' slots for {subject} ({window_desc}):\n" + "\n".join(lines) +
        "\n\nTo book one, tell me which time and your name — I'll hold it for a few minutes while we confirm. "
        "When calling hold_slot, pass the bracketed slot_start_iso value exactly as shown, not a reconstructed time"
        + (f", along with the same party_size ({party_size})." if party_size else ".")
    )


async def get_weekly_availability(
    appointment_type_name: str,
    practice_id: str = "",
    provider_name: str = "",
    party_size: int = 0,
    weeks_ahead: int = 8,
    tool_context: ToolContext = None,
) -> str:
    """Give a broad view of which upcoming weeks have any openings at all —
    call this when the caller wants to browse rather than pick a specific day
    (e.g. "what's open over the next couple months"). weeks_ahead=8 covers
    about two months. Returns which weekdays have at least one open slot per
    week, NOT specific times — once the caller picks a week, call
    check_availability with start_date set to that week's Monday to get exact
    times to offer.

    Pass party_size (and leave provider_name blank), same as
    check_availability, when the caller gave a party size rather than
    naming a specific resource — this checks every table/provider that
    fits, not one arbitrary one."""
    practice_id = _resolve_practice_id(practice_id, tool_context)
    appt_type = await _find_appointment_type(practice_id, appointment_type_name)
    if not appt_type:
        return f"I couldn't find an appointment type called '{appointment_type_name}'. Call list_appointment_types to see what's offered."

    if provider_name:
        provider = await _find_provider(practice_id, provider_name)
        if not provider:
            return "I couldn't find an available provider for that appointment type."
        providers = [provider]
        subject = provider["name"]
    else:
        # Same reasoning as check_availability: no name given means check
        # every active provider, not one arbitrary pick -- regardless of
        # whether party_size was actually passed this turn.
        providers = await _find_providers_for_party_size(practice_id, party_size or 0)
        if not providers:
            return (f"No table here seats a party of {party_size}." if party_size
                    else "I couldn't find an available provider for that appointment type.")
        subject = f"a table for {party_size}" if party_size else "any available provider"

    tz, lead_time_minutes, max_advance_days, slot_step_minutes = await _get_practice_guardrails(practice_id)
    now = datetime.now(tz)
    # One scan across the whole span, generous max_results so it isn't cut
    # off partway through — this is a summary pass, not the final slot list.
    # Union across every qualifying provider, same reasoning as
    # check_availability: one table being booked up doesn't mean the whole
    # week is closed when others of the same size are free.
    slots_set: set[datetime] = set()
    for p in providers:
        busy = await _busy_intervals(practice_id, p["doc_id"], tz)
        slots_set.update(compute_open_slots(
            working_hours=p.get("working_hours") or [],
            busy_intervals=busy,
            duration_minutes=int(appt_type.get("duration_minutes", 30)),
            buffer_minutes=int(appt_type.get("buffer_minutes", 0)),
            now=now,
            days_ahead=weeks_ahead * 7,
            lead_time_minutes=lead_time_minutes,
            max_advance_days=max_advance_days,
            tz=tz,
            max_results=2000,
        ))
    slots = sorted(slots_set)
    if not slots:
        return (
            f"{subject} has no open '{appt_type['name']}' slots in the next "
            f"{weeks_ahead} weeks. Try a different {'party size' if party_size else 'provider'} or appointment type."
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
        f"Weeks with openings for '{appt_type['name']}' with {subject} "
        f"(next {weeks_ahead} weeks):\n" + "\n".join(lines) +
        "\n\nAsk which week works, then call check_availability with that week's "
        "Monday as start_date to get exact times."
    )


async def _attempt_hold_txn(practice_id: str, provider: dict, appt_type: dict, start: datetime, end: datetime, caller_name: str) -> str:
    """One provider's worth of hold_slot's transactional overlap check +
    write, factored out so hold_slot can try it against several candidate
    tables in turn when it was given a party_size instead of one specific
    provider. Raises ValueError("slot_taken"/"slot_held") if that table
    isn't actually free at this time -- the caller loops to the next
    candidate on that, exactly as if it had called check_availability for
    just that one table and gotten no results."""
    db = get_db()
    transaction = db.transaction()

    @firestore.async_transactional
    async def _txn(txn: firestore.AsyncTransaction):
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

    return await _txn(transaction)


async def hold_slot(
    appointment_type_name: str,
    slot_start_iso: str,
    caller_name: str,
    provider_name: str = "",
    party_size: int = 0,
    practice_id: str = "",
    tool_context: ToolContext = None,
) -> str:
    """Place a short-lived hold on a specific slot (from check_availability's
    results) so it can't be double-booked while the caller confirms. Returns a
    hold_id — pass it to confirm_booking within a few minutes.

    Pass the SAME party_size you gave check_availability (and leave
    provider_name blank) when that's how you found this slot — a dine-in
    table reservation has several same-size tables, and this tries each one
    that fits the party until it finds one actually free at this exact
    time, rather than failing just because one arbitrary table is busy."""
    practice_id = _resolve_practice_id(practice_id, tool_context)
    appt_type = await _find_appointment_type(practice_id, appointment_type_name)
    if not appt_type:
        return "I couldn't match that appointment type — please check availability again."

    if provider_name:
        provider = await _find_provider(practice_id, provider_name)
        providers = [provider] if provider else []
    else:
        # Same reasoning as check_availability: no name given means try
        # every active provider in turn, not one arbitrary pick.
        providers = await _find_providers_for_party_size(practice_id, party_size or 0)
    if not providers:
        return "I couldn't match that to an available table/provider — please check availability again."

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

    held_provider = None
    hold_id = None
    for candidate in providers:
        try:
            hold_id = await _attempt_hold_txn(practice_id, candidate, appt_type, start, end, caller_name)
            held_provider = candidate
            break
        except ValueError as exc:
            if str(exc) in ("slot_taken", "slot_held"):
                continue
            raise

    if hold_id is None:
        return "Sorry — that slot was just taken. Please call check_availability again for current openings."

    provider = held_provider
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
    tool_context: ToolContext = None,
) -> str:
    """Convert an active hold (from hold_slot) into a confirmed appointment.
    Fails if the hold has expired or was already used — call hold_slot again
    in that case. If caller_email is given, a confirmation email is sent
    after the booking is confirmed (best-effort — a failed send never undoes
    the booking, since Firestore is already the source of truth by then).

    This is a full production booking channel, not a demo. When this
    conversation belongs to a signed-in ADAR Front Desk customer,
    api/main.py's scheduling_guest_chat seeds tool_context.state with that
    customer's real team_id/email via the ADK runner's state_delta --
    never as an LLM-suppliable argument, so nothing typed in the
    conversation can spoof it. When present, the appointment is tagged
    with that account's guest_id so it shows up in the account's My
    Appointments tab (same collection/field MyAppointmentsScreen already
    reads for Book-tab bookings), and the full customer+provider+practice
    email fan-out (_send_booking_emails, shared with the Book tab's REST
    booking path in scheduling_guest.py) runs instead of the old
    caller-email-only / practice-admin-only pair."""
    practice_id = _resolve_practice_id(practice_id, tool_context)
    db = get_db()
    transaction = db.transaction()
    hold_ref = db.collection(settings.SCHEDULING_HOLDS_COLLECTION).document(hold_id)

    customer_team_id = ""
    customer_email = ""
    if tool_context is not None:
        try:
            customer_team_id = (tool_context.state.get("_customer_team_id") or "").strip()
            customer_email = (tool_context.state.get("_customer_email") or "").strip()
        except Exception:
            logger.warning("Could not read customer identity from tool_context.state", exc_info=True)

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
        appt_data = {
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
            "source_channel": "ask_adar_chat" if customer_team_id else "voice_in_app",
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        if customer_team_id:
            appt_data["guest_id"] = customer_team_id
        txn.set(appt_ref, appt_data)
        txn.update(hold_ref, {"status": "confirmed"})
        return (
            appointment_id, hold["start_time"], hold["provider_id"],
            hold["provider_name"], hold["appointment_type_name"],
        )

    try:
        appointment_id, start, provider_id, provider_name, appointment_type_name = await _txn(transaction)
    except ValueError as exc:
        reason_map = {
            "not_found": "I can't find that hold — please check availability and hold a slot again.",
            "already_used": "That hold was already confirmed or released — please check availability again.",
            "expired": "That hold expired — please check availability and hold a slot again.",
        }
        return reason_map.get(str(exc), "I couldn't confirm that booking — please try again.")

    practice_rows = await direct_query(settings.SCHEDULING_PRACTICES_COLLECTION, {"practice_id": practice_id}, limit=1)
    practice_data = practice_rows[0] if practice_rows else {}

    # `start` just came back out of the hold doc via the transaction above,
    # so it's UTC-aware regardless of the practice's configured zone (see
    # _format_slot) -- re-localize once here, before either the email or
    # the chat reply below format it.
    try:
        start = start.astimezone(await _get_practice_tz(practice_id))
    except Exception:
        logger.warning("Could not localize booking time to practice %s timezone", practice_id, exc_info=True)

    provider_data: dict = {}
    try:
        provider_snap = await db.collection(settings.SCHEDULING_PROVIDERS_COLLECTION).document(provider_id).get()
        if provider_snap.exists:
            provider_data = provider_snap.to_dict() or {}
    except Exception:
        logger.warning("Could not load provider %s for booking notifications", provider_id, exc_info=True)
    provider_data.setdefault("name", provider_name)

    # Shared with the Book tab's REST booking path (create_guest_booking in
    # scheduling_guest.py) so both channels notify the same targets: the
    # caller's typed email + the signed-in account's email (deduped), and
    # the provider's own email + the practice admin/ADMIN_EMAIL (deduped).
    # Imported here rather than at module load time to avoid a circular
    # import -- api.routes.scheduling_guest is already fully loaded by the
    # time this tool runs (domains.*.tools is imported lazily inside
    # build_agents(), well after api/main.py finishes importing its routers).
    email_sent = False
    try:
        from api.routes.scheduling_guest import _send_booking_emails
        await _send_booking_emails(
            practice_data=practice_data,
            provider_data=provider_data,
            appointment_type_name=appointment_type_name,
            caller_name=caller_name,
            caller_phone=caller_phone,
            caller_email=caller_email,
            customer_email=customer_email,
            reason=reason,
            when_formatted=_format_slot(start),
            appointment_id=appointment_id,
        )
        email_sent = bool(caller_email or customer_email)
    except Exception:
        logger.exception("Booking notification email fan-out failed for %s (booking still confirmed)", appointment_id)

    result = (
        f"Booked. {caller_name} is confirmed with {provider_name} for {_format_slot(start)} "
        f"(confirmation ID: {appointment_id[:8]})."
    )
    confirmation_target = caller_email or customer_email
    if confirmation_target:
        result += f" A confirmation email is on its way to {confirmation_target}." if email_sent else (
            " I tried to send a confirmation email but it didn't go through — give them the "
            "confirmation ID directly."
        )
    else:
        result += " No email was given, so make sure they have the confirmation ID."
    return result


async def _resolve_appointment(db, appointment_id: str):
    """The confirmation ID the caller has is only the first 8 characters
    of the real Firestore document id -- confirm_booking deliberately
    truncates it (f"...(confirmation ID: {appointment_id[:8]})") so it's
    short enough to read/type back. Looking that short string up as an
    exact document id (the previous behavior) always misses, which is why
    cancel/reschedule used to fail with "I couldn't find an appointment
    with that confirmation ID" even for a real, active appointment.
    Try an exact match first (covers a full id, if one's ever passed
    directly), then fall back to a document-id prefix range query for the
    short form everyone actually has. Returns (ref, snap); ref is None if
    the prefix matched zero or more than one document (ambiguous)."""
    coll = db.collection(settings.SCHEDULING_APPOINTMENTS_COLLECTION)
    prefix = (appointment_id or "").strip()
    if not prefix:
        return None, None
    ref = coll.document(prefix)
    snap = await ref.get()
    if snap.exists:
        return ref, snap
    # Firestore's document-id filter (__key__/__name__) requires the
    # comparison value to be an actual document reference, not a bare
    # string -- passing the plain prefix string here fails at query time
    # with "400 __key__ filter value must be a Key". coll.document(...)
    # builds a syntactically valid reference even though no document with
    # that exact (usually partial) id exists; only its path is used for
    # the range comparison.
    query = (
        coll
        .where(filter=FieldFilter(FieldPath.document_id(), ">=", coll.document(prefix)))
        .where(filter=FieldFilter(FieldPath.document_id(), "<", coll.document(prefix + "\uf8ff")))
        .limit(2)
    )
    matches = [doc async for doc in query.stream()]
    if len(matches) == 1:
        doc = matches[0]
        return coll.document(doc.id), doc
    return None, None


async def cancel_appointment(
    appointment_id: str, practice_id: str = "", reason: str = "",
    tool_context: ToolContext = None,
) -> str:
    """Cancel a confirmed appointment by its confirmation ID. Sends the same
    customer+provider+practice-admin email fan-out as a Front Desk app
    cancellation (_send_cancellation_emails, shared with cancel_guest_booking
    in api/routes/scheduling_guest.py) -- not just a customer-only email."""
    practice_id = _resolve_practice_id(practice_id, tool_context)
    db = get_db()
    ref, snap = await _resolve_appointment(db, appointment_id)
    if ref is None or not snap.exists or snap.to_dict().get("practice_id") != practice_id:
        return "I couldn't find an appointment with that confirmation ID."
    appointment_id = ref.id  # the resolved FULL id, for the email call below
    data = snap.to_dict()
    if data.get("status") == "cancelled":
        return "That appointment is already cancelled."
    # data["start_time"] just came back out of Firestore, so it's UTC-aware
    # regardless of the practice's configured zone (see _format_slot) --
    # re-localize once here, before either the email or the chat reply
    # below format it.
    if data.get("start_time") is not None:
        try:
            data["start_time"] = data["start_time"].astimezone(await _get_practice_tz(practice_id))
        except Exception:
            logger.warning("Could not localize cancellation time to practice %s timezone", practice_id, exc_info=True)
    await ref.update({
        "status": "cancelled",
        "cancel_reason": reason,
        "updated_at": firestore.SERVER_TIMESTAMP,
    })

    customer_email = ""
    if tool_context is not None:
        try:
            customer_email = (tool_context.state.get("_customer_email") or "").strip()
        except Exception:
            logger.warning("Could not read customer identity from tool_context.state", exc_info=True)

    practice_rows = await direct_query(settings.SCHEDULING_PRACTICES_COLLECTION, {"practice_id": practice_id}, limit=1)
    practice_data = practice_rows[0] if practice_rows else {}

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

    caller_email = data.get("caller_email") or ""
    email_sent = False
    try:
        from api.routes.scheduling_guest import _send_cancellation_emails
        await _send_cancellation_emails(
            practice_data=practice_data,
            provider_data=provider_data,
            appointment_type_name=data.get("appointment_type_name", "appointment"),
            caller_name=data.get("caller_name", ""),
            caller_phone=data.get("caller_phone", ""),
            caller_email=caller_email,
            customer_email=customer_email,
            cancel_reason=reason,
            when_formatted=_format_slot(data["start_time"]),
            appointment_id=appointment_id,
        )
        email_sent = bool(caller_email or customer_email)
    except Exception:
        logger.exception("Cancellation email fan-out failed for %s (cancellation still applied)", appointment_id)

    confirmation_target = caller_email or customer_email
    result = f"Cancelled the {data.get('appointment_type_name', 'appointment')} with {data.get('provider_name', 'the provider')} on {_format_slot(data['start_time'])}."
    if confirmation_target:
        result += " A cancellation email was sent." if email_sent else " (Cancellation email failed to send — let them know directly.)"
    return result


async def reschedule_appointment(
    appointment_id: str, practice_id: str = "", tool_context: ToolContext = None,
) -> str:
    """Start a reschedule: cancels the existing appointment and tells the
    caller to pick a new time via check_availability + hold_slot. Kept as two
    steps deliberately, so the caller always confirms the new time before the
    old one is given up for good."""
    result = await cancel_appointment(
        appointment_id, practice_id=practice_id, reason="reschedule requested",
        tool_context=tool_context,
    )
    if result.startswith("Cancelled"):
        return result + " Now let's find a new time — what date or provider works best?"
    return result


async def list_my_appointments(caller_phone: str, practice_id: str = "", tool_context: ToolContext = None) -> str:
    """Look up upcoming confirmed appointments by the caller's phone number
    (a soft identity match — no clinical data is read back)."""
    practice_id = _resolve_practice_id(practice_id, tool_context)
    rows = await direct_query(
        settings.SCHEDULING_APPOINTMENTS_COLLECTION,
        {"practice_id": practice_id, "caller_phone": caller_phone, "status": "confirmed"},
        limit=20,
    )
    if not rows:
        return "I don't see any upcoming appointments under that phone number."
    # Each row's start_time just came back out of Firestore, so it's
    # UTC-aware regardless of the practice's configured zone (see
    # _format_slot) -- re-localize before formatting below.
    tz = await _get_practice_tz(practice_id)
    for r in rows:
        if r.get("start_time") is not None:
            try:
                r["start_time"] = r["start_time"].astimezone(tz)
            except Exception:
                logger.warning("Could not localize appointment time to practice %s timezone", practice_id, exc_info=True)
    lines = [
        f"- {r.get('appointment_type_name', 'Appointment')} with {r.get('provider_name', 'provider')} "
        f"on {_format_slot(r['start_time'])} (confirmation ID: {r['doc_id'][:8]})"
        for r in rows
    ]
    return "Upcoming appointments:\n" + "\n".join(lines)
