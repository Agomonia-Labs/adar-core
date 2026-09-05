"""
api/routes/scheduling_traces.py — Trace Explorer admin API for ADAR Front
Desk (scheduling domain). Reads from the Postgres trace store (src/adar/
tracedb.py + src/adar/tracing.py), scoped to one practice at a time, using
the exact same auth pattern as api/routes/scheduling_admin.py.

Returns 200 with an empty/placeholder payload (rather than 500) when the
trace store isn't configured (TRACE_DB_URL unset) — the admin UI shows a
"not enabled yet" state instead of an error.
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from src.adar.config import settings
from src.adar.tracedb import get_trace_pool
from api.routes.scheduling_admin import get_scheduling_staff, _check_practice_access, _require_scheduling_domain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/scheduling", tags=["admin-scheduling-traces"])


def _parse_jsonb_fields(row: dict, fields: list[str]) -> dict:
    """asyncpg has no JSON codec registered on this pool (see tracedb.py),
    so every JSONB column comes back as a raw JSON-text string, not a
    parsed object -- e.g. an "empty" error column is the 2-character
    string "{}", not {}. Left alone, that breaks any caller (the admin
    UI's Timeline included) that checks the SHAPE of these fields rather
    than a plain string. Parse the known JSONB columns back into real
    objects before they leave this API."""
    for f in fields:
        v = row.get(f)
        if isinstance(v, str):
            try:
                row[f] = json.loads(v)
            except (ValueError, TypeError):
                pass
    return row


def _duration_ms(row: dict) -> int:
    started = row.get("started_at")
    ended = row.get("ended_at")
    if not started or not ended:
        return 0
    try:
        return max(0, int((ended - started).total_seconds() * 1000))
    except (AttributeError, TypeError):
        return 0


def _public_trace_row(row: dict) -> dict:
    return {
        "trace_id":            row.get("trace_id"),
        "request_type":        row.get("request_type"),
        "session_id":          row.get("session_id"),
        "team_id":             row.get("team_id"),
        "status":              row.get("status"),
        "input_text_preview":  row.get("input_text_preview"),
        "error_message":       row.get("error_message"),
        "started_at":          row.get("started_at"),
        "ended_at":            row.get("ended_at"),
        "duration_ms":         row.get("duration_ms") if row.get("duration_ms") is not None else _duration_ms(row),
        "span_count":          row.get("span_count", 0),
        "eval_overall":        row.get("eval_overall"),
    }


@router.get("/practices/{practice_id}/traces/summary")
async def trace_summary(practice_id: str, team: dict = Depends(get_scheduling_staff)):
    _require_scheduling_domain()
    _check_practice_access(team, practice_id)
    pool = get_trace_pool()
    if pool is None:
        return {"ready": False, "trace_count": 0, "latest_trace_at": None,
                 "message": "Postgres trace store is not configured (TRACE_DB_URL unset)."}
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT COUNT(*) AS trace_count, MAX(started_at) AS latest_trace_at
               FROM trace_flows WHERE practice_id=$1""",
            practice_id,
        )
    return {
        "ready": True,
        "trace_count": row["trace_count"] or 0,
        "latest_trace_at": row["latest_trace_at"],
        "message": None,
    }


@router.get("/practices/{practice_id}/traces")
async def list_traces(
    practice_id: str,
    team: dict = Depends(get_scheduling_staff),
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
):
    _require_scheduling_domain()
    _check_practice_access(team, practice_id)
    pool = get_trace_pool()
    if pool is None:
        return {"traces": [], "ready": False}
    limit = max(1, min(limit, 200))
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT f.trace_id, f.request_type, f.session_id, f.team_id, f.status,
                      f.input_text_preview, f.error_message, f.started_at, f.ended_at,
                      COALESCE(EXTRACT(EPOCH FROM (f.ended_at-f.started_at))*1000, 0)::bigint AS duration_ms,
                      COUNT(DISTINCT s.span_id)::int AS span_count,
                      MAX(e.overall) AS eval_overall
               FROM trace_flows f
               LEFT JOIN trace_spans s ON s.trace_id=f.trace_id
               LEFT JOIN trace_evaluations e ON e.trace_id=f.trace_id
               WHERE f.practice_id=$1
                 AND ($2::text IS NULL OR f.status=$2)
                 AND ($3::text IS NULL OR f.input_text_preview ILIKE '%' || $3 || '%' OR f.trace_id ILIKE '%' || $3 || '%')
               GROUP BY f.trace_id, f.request_type, f.session_id, f.team_id, f.status,
                        f.input_text_preview, f.error_message, f.started_at, f.ended_at
               ORDER BY f.started_at DESC
               LIMIT $4""",
            practice_id, status, search, limit,
        )
    return {"traces": [_public_trace_row(dict(r)) for r in rows], "ready": True}


@router.get("/practices/{practice_id}/traces/{trace_id}")
async def get_trace(practice_id: str, trace_id: str, team: dict = Depends(get_scheduling_staff)):
    _require_scheduling_domain()
    _check_practice_access(team, practice_id)
    pool = get_trace_pool()
    if pool is None:
        raise HTTPException(status_code=404, detail="Trace store is not configured")
    async with pool.acquire() as conn:
        trace = await conn.fetchrow(
            "SELECT * FROM trace_flows WHERE trace_id=$1 AND practice_id=$2", trace_id, practice_id,
        )
        if not trace:
            raise HTTPException(status_code=404, detail="Trace not found")
        spans = await conn.fetch(
            "SELECT * FROM trace_spans WHERE trace_id=$1 ORDER BY started_at ASC", trace_id,
        )
        llm_events = await conn.fetch(
            "SELECT * FROM trace_llm_events WHERE trace_id=$1 ORDER BY created_at ASC", trace_id,
        )
        evaluations = await conn.fetch(
            "SELECT * FROM trace_evaluations WHERE trace_id=$1 ORDER BY created_at DESC", trace_id,
        )
    trace_data = dict(trace)
    return {
        "trace": _public_trace_row({**trace_data, "span_count": len(spans)}),
        "spans": [_parse_jsonb_fields(dict(r), ["metadata", "error"]) for r in spans],
        "llm_events": [_parse_jsonb_fields(dict(r), ["tool_request_json", "tool_response_json"]) for r in llm_events],
        "evaluations": [dict(r) for r in evaluations],
    }
