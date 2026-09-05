"""src/adar/tracing.py — request/span recording into the Postgres trace
store, correlated with the single OTel-native trace_id (see the
observability plan doc: no dual trace-id design, unlike adar-rag).

Ported from adar-rag's backend/services/tracing.py, simplified:
  - one trace_id (OTel-native when telemetry is enabled, else a uuid4 hex
    fallback of the same shape) instead of DocIntel's separate app-level
    "trc_..." id.
  - schema columns adapted to adar-core's actual identity model (plain
    text team_id/session_id/user_id/practice_id, no FK to a users/
    workspaces table that doesn't exist here).
Every DB write is fire-and-forget-safe: a Postgres failure here never
breaks the request it's describing.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from src.adar.config import settings
from src.adar.observability import current_otel_ids, telemetry_enabled, traced_span
from src.adar.tracedb import get_trace_pool

logger = logging.getLogger(__name__)

TRACE_PREVIEW_CHARS = 600
TRACE_FIELD_CHARS = 6000

# The request's trace_id, set once by the middleware in api/main.py and
# read anywhere downstream in the same request (judge.py's evaluate_response,
# for instance) without having to thread it through every function signature.
current_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("adar_trace_id", default=None)
current_span_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("adar_span_id", default=None)

_SECRET_PATTERNS = [
    re.compile(r"(authorization\s*[:=]\s*bearer\s+)[^\s,;]+", re.I),
    re.compile(r"(api[_-]?key\s*[:=]\s*)[^\s,;]+", re.I),
    re.compile(r"(token\s*[:=]\s*)[^\s,;]+", re.I),
    re.compile(r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})"),
]


def new_trace_id() -> str:
    """Fallback trace_id used only when OTel is disabled/unavailable — same
    32-hex-char shape as a real OTel trace_id so the format is consistent
    either way."""
    return uuid.uuid4().hex


def new_span_id() -> str:
    return uuid.uuid4().hex[:16]


def new_eval_id() -> str:
    return uuid.uuid4().hex


def hash_text(text: str | None) -> str | None:
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def redact_text(value: Any, limit: int = TRACE_FIELD_CHARS) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    if not settings.TRACE_FULL_CONTENT and len(text) > limit:
        text = text[:limit] + f"... [truncated {len(text) - limit} chars]"
    for pattern in _SECRET_PATTERNS:
        if "@" in pattern.pattern:
            text = pattern.sub(r"\1***@\2", text)
        else:
            text = pattern.sub(r"\1[REDACTED]", text)
    return text


def resolve_trace_id() -> str:
    """The one place a trace_id gets minted: prefer the real OTel trace_id
    (valid once FastAPIInstrumentor + a TracerProvider are wired up), else
    fall back to a locally generated id of the same shape."""
    otel_trace_id, _ = current_otel_ids()
    return otel_trace_id or new_trace_id()


async def start_trace(
    request_type: str,
    *,
    trace_id: str | None = None,
    domain: str | None = None,
    practice_id: str | None = None,
    team_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    input_text: str | None = None,
    client_info: dict | None = None,
    metadata: dict | None = None,
) -> str:
    trace_id = trace_id or resolve_trace_id()
    current_trace_id.set(trace_id)
    preview = redact_text(input_text, TRACE_PREVIEW_CHARS)
    pool = get_trace_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO trace_flows
                       (trace_id, domain, request_type, practice_id, team_id, session_id,
                        user_id, input_text_hash, input_text_preview, client_info, metadata)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11::jsonb)
                       ON CONFLICT (trace_id) DO UPDATE SET
                         practice_id = COALESCE(trace_flows.practice_id, EXCLUDED.practice_id),
                         team_id = COALESCE(trace_flows.team_id, EXCLUDED.team_id),
                         session_id = COALESCE(trace_flows.session_id, EXCLUDED.session_id),
                         user_id = COALESCE(trace_flows.user_id, EXCLUDED.user_id),
                         input_text_hash = COALESCE(trace_flows.input_text_hash, EXCLUDED.input_text_hash),
                         input_text_preview = COALESCE(trace_flows.input_text_preview, EXCLUDED.input_text_preview),
                         client_info = trace_flows.client_info || EXCLUDED.client_info,
                         metadata = trace_flows.metadata || EXCLUDED.metadata""",
                    trace_id, domain or settings.DOMAIN, request_type, practice_id, team_id,
                    session_id, user_id, hash_text(input_text), preview,
                    json.dumps(client_info or {}, default=str, ensure_ascii=False),
                    json.dumps(metadata or {}, default=str, ensure_ascii=False),
                )
        except Exception:
            logger.exception("Trace store: failed to start trace %s", trace_id)
    return trace_id


async def finish_trace(
    trace_id: str,
    status: str = "success",
    error_message: str | None = None,
    practice_id: str | None = None,
) -> None:
    """practice_id is an optional correction applied at the END of the
    request: start_trace() tags every trace with whatever practice_id was
    known BEFORE the agent ran (usually just the deployment's configured
    default), since the real practice is only resolved mid-conversation by
    the find_practice tool. When the caller has since learned the real
    practice_id (from session.state — see api/main.py's /api/chat), pass it
    here and it overwrites the placeholder. Pass None to leave whatever
    start_trace already wrote untouched."""
    pool = get_trace_pool()
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE trace_flows
                   SET status=$2, error_message=$3, ended_at=NOW(),
                       practice_id=COALESCE($4, practice_id)
                   WHERE trace_id=$1""",
                trace_id, status, redact_text(error_message, 1200) if error_message else None,
                practice_id,
            )
    except Exception:
        logger.exception("Trace store: failed to finish trace %s", trace_id)


@contextlib.asynccontextmanager
async def span(name: str, *, trace_id: str | None = None, metadata: dict | None = None):
    trace_id = trace_id or current_trace_id.get()
    if not trace_id:
        yield None
        return
    parent_span_id = current_span_id.get()
    started = time.perf_counter()
    with traced_span(name, attributes={"adar.trace.id": trace_id, **(metadata or {})}):
        _, otel_span_id = current_otel_ids()
        span_id = otel_span_id or new_span_id()
        pool = get_trace_pool()
        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO trace_spans (span_id, trace_id, parent_span_id, name, metadata)
                           VALUES ($1,$2,$3,$4,$5::jsonb) ON CONFLICT (span_id) DO NOTHING""",
                        span_id, trace_id, parent_span_id, name,
                        json.dumps(metadata or {}, default=str, ensure_ascii=False),
                    )
            except Exception:
                logger.exception("Trace store: failed to start span %s", name)
        span_token = current_span_id.set(span_id)
        try:
            yield span_id
        except Exception as exc:
            duration = int((time.perf_counter() - started) * 1000)
            if pool is not None:
                try:
                    async with pool.acquire() as conn:
                        await conn.execute(
                            """UPDATE trace_spans
                               SET status='error', error=$2::jsonb, ended_at=NOW(), duration_ms=$3
                               WHERE span_id=$1""",
                            span_id,
                            json.dumps({"type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False),
                            duration,
                        )
                except Exception:
                    logger.exception("Trace store: failed to record span error %s", name)
            raise
        else:
            duration = int((time.perf_counter() - started) * 1000)
            if pool is not None:
                try:
                    async with pool.acquire() as conn:
                        await conn.execute(
                            """UPDATE trace_spans SET status='success', ended_at=NOW(), duration_ms=$2
                               WHERE span_id=$1""",
                            span_id, duration,
                        )
                except Exception:
                    logger.exception("Trace store: failed to finish span %s", name)
        finally:
            current_span_id.reset(span_token)


async def record_tool_span(
    *,
    trace_id: str | None = None,
    parent_span_id: str | None = None,
    name: str,
    args: dict | None = None,
    result: Any = None,
    error: str | None = None,
    duration_ms: int = 0,
) -> None:
    """Records one already-completed ADK tool call (find_practice,
    check_availability, hold_slot, ...) as a child span under agent_run.
    Unlike span() above (an enter/exit context manager for code we're
    wrapping directly), ADK only tells us about a tool call after the fact
    -- the function_call and function_response events arrive as a pair
    further down the event stream (see _run_agent_with_retries in
    api/main.py) -- so this is a single INSERT with timestamps computed
    from the already-known duration, not a context manager."""
    trace_id = trace_id or current_trace_id.get()
    pool = get_trace_pool()
    if not trace_id or pool is None:
        return
    span_id = new_span_id()
    ended = datetime.now(timezone.utc)
    started = ended - timedelta(milliseconds=max(duration_ms, 0))
    metadata_json = json.dumps(
        {"args": args or {}, "result_preview": redact_text(result, 800)},
        default=str, ensure_ascii=False,
    )
    error_json = json.dumps({"message": error} if error else {}, ensure_ascii=False)
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO trace_spans
                   (span_id, trace_id, parent_span_id, name, status, metadata, error, duration_ms, started_at, ended_at)
                   VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8,$9,$10)
                   ON CONFLICT (span_id) DO NOTHING""",
                span_id, trace_id, parent_span_id, f"tool:{name}",
                "error" if error else "success",
                metadata_json, error_json, duration_ms, started, ended,
            )
    except Exception:
        logger.exception("Trace store: failed to record tool span %s", name)


async def record_llm_event(
    *,
    trace_id: str | None = None,
    span_id: str | None = None,
    provider: str,
    model: str | None = None,
    operation: str,
    system_prompt: str | None = None,
    user_prompt: str | None = None,
    llm_response: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    latency_ms: int | None = None,
    finish_reason: str | None = None,
    error: str | None = None,
) -> None:
    trace_id = trace_id or current_trace_id.get()
    pool = get_trace_pool()
    if not trace_id or pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO trace_llm_events
                   (event_id, trace_id, span_id, provider, model, operation,
                    system_prompt, user_prompt, llm_response, input_tokens,
                    output_tokens, latency_ms, finish_reason, redaction_status, error)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)""",
                uuid.uuid4().hex, trace_id, span_id, provider, model, operation,
                redact_text(system_prompt), redact_text(user_prompt), redact_text(llm_response),
                input_tokens, output_tokens, latency_ms, finish_reason,
                "full" if settings.TRACE_FULL_CONTENT else "redacted",
                redact_text(error, 1200) if error else None,
            )
    except Exception:
        logger.exception("Trace store: failed to record LLM event for trace %s", trace_id)


async def record_evaluation(
    *,
    trace_id: str | None,
    domain: str,
    team_id: str | None,
    session_id: str | None,
    scores: dict,
    explanation: str,
    model: str | None,
) -> None:
    """Phase 4: judge-agent eval correlation. Called from evaluation/judge.py
    with the SAME trace_id the request already has — never a freshly minted
    one, unlike adar-rag's agent_evals.py anti-pattern."""
    pool = get_trace_pool()
    if not trace_id or pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO trace_evaluations
                   (eval_id, trace_id, domain, team_id, session_id,
                    accuracy, completeness, relevance, format, overall, explanation, model)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
                new_eval_id(), trace_id, domain, team_id, session_id,
                scores.get("accuracy"), scores.get("completeness"), scores.get("relevance"),
                scores.get("format"), scores.get("overall"), explanation, model,
            )
    except Exception:
        logger.exception("Trace store: failed to record evaluation for trace %s", trace_id)
