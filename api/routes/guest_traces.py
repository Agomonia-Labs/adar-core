"""Guest-owned, sanitized execution traces for public Live Experiences."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException

from src.adar.tracedb import get_trace_pool


def _duration_ms(started: datetime | None, ended: datetime | None) -> int:
    if not started or not ended:
        return 0
    return max(0, int((ended - started).total_seconds() * 1000))


def _tool_label(name: str) -> str:
    value = name.removeprefix("tool:").replace("_", " ").strip()
    return value.title() or "Knowledge Tool"


def _span_step(row: dict[str, Any]) -> dict[str, Any]:
    raw_name = str(row.get("name") or "workflow")
    is_tool = raw_name.startswith("tool:")
    if is_tool:
        label = _tool_label(raw_name)
        kind = "tool"
        detail = "ADAR executed a domain tool and returned evidence to the agent."
    elif raw_name == "agent_run":
        label = "Agent orchestration"
        kind = "agent"
        detail = "The domain agent selected the appropriate reasoning and retrieval path."
    else:
        label = raw_name.replace("_", " ").title()
        kind = "workflow"
        detail = "A governed workflow stage completed."
    return {
        "id": str(row.get("span_id") or raw_name),
        "kind": kind,
        "name": label,
        "detail": detail,
        "status": row.get("status") or "completed",
        "duration_ms": int(row.get("duration_ms") or 0),
        "started_at": row.get("started_at"),
    }


def _llm_step(row: dict[str, Any]) -> dict[str, Any]:
    model = str(row.get("model") or "configured model")
    tokens = int(row.get("input_tokens") or 0) + int(row.get("output_tokens") or 0)
    token_detail = f" {tokens} tokens were processed." if tokens else ""
    return {
        "id": str(row.get("event_id") or "model-generation"),
        "kind": "reasoning",
        "name": "Grounded response generation",
        "detail": f"{model} synthesized the answer from the selected domain evidence.{token_detail}",
        "status": "error" if row.get("error") else "success",
        "duration_ms": int(row.get("latency_ms") or 0),
        "started_at": row.get("created_at"),
    }


def build_public_trace_projection(
    trace: dict[str, Any],
    spans: list[dict[str, Any]],
    llm_events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build an allowlisted projection; raw prompts, metadata and payloads never leave."""
    started_at = trace.get("started_at")
    ended_at = trace.get("ended_at")
    timed_steps = [_span_step(row) for row in spans] + [_llm_step(row) for row in llm_events]
    timed_steps.sort(
        key=lambda item: (
            item["started_at"].timestamp()
            if isinstance(item.get("started_at"), datetime)
            else 0
        )
    )
    steps = [
        {
            "id": "request",
            "kind": "request",
            "name": "Question received",
            "detail": "The guest request passed domain, rate-limit and access checks.",
            "status": "success",
            "duration_ms": 0,
            "started_at": started_at,
        },
        {
            "id": "session",
            "kind": "context",
            "name": "Conversation context",
            "detail": "ADAR resolved the temporary guest session and its follow-up context.",
            "status": "success",
            "duration_ms": 0,
            "started_at": started_at,
        },
        *timed_steps,
        {
            "id": "response",
            "kind": "response",
            "name": "Grounded answer delivered",
            "detail": "The formatted answer was returned to this Live Experience.",
            "status": "success" if trace.get("status") == "success" else trace.get("status", "running"),
            "duration_ms": 0,
            "started_at": ended_at,
        },
    ]
    return {
        "ready": True,
        "projection": "guest_safe",
        "trace": {
            "trace_id": trace.get("trace_id"),
            "domain": trace.get("domain"),
            "status": trace.get("status"),
            "question": trace.get("input_text_preview"),
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_ms": _duration_ms(started_at, ended_at),
            "step_count": len(steps),
        },
        "steps": steps,
    }


async def get_guest_trace_projection(trace_id: str, guest: dict, domain: str) -> dict[str, Any]:
    pool = get_trace_pool()
    if pool is None:
        return {
            "ready": False,
            "projection": "guest_safe",
            "trace": {"trace_id": trace_id, "domain": domain, "status": "unavailable"},
            "steps": [],
            "message": "The trace store is not configured for this deployment.",
        }

    owner_id = str(guest.get("sub") or guest.get("team_id") or "")
    async with pool.acquire() as conn:
        trace_row = await conn.fetchrow(
            """SELECT trace_id, domain, status, input_text_preview, started_at, ended_at
               FROM trace_flows
               WHERE trace_id=$1 AND domain=$2 AND team_id=$3""",
            trace_id,
            domain,
            owner_id,
        )
        if not trace_row:
            raise HTTPException(status_code=404, detail="Trace not found")
        span_rows = await conn.fetch(
            """SELECT span_id, name, status, duration_ms, started_at
               FROM trace_spans WHERE trace_id=$1 ORDER BY started_at ASC""",
            trace_id,
        )
        llm_rows = await conn.fetch(
            """SELECT event_id, model, operation, input_tokens, output_tokens,
                      latency_ms, error, created_at
               FROM trace_llm_events WHERE trace_id=$1 ORDER BY created_at ASC""",
            trace_id,
        )
    return build_public_trace_projection(
        dict(trace_row),
        [dict(row) for row in span_rows],
        [dict(row) for row in llm_rows],
    )
