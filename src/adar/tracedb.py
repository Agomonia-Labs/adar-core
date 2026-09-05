"""src/adar/tracedb.py — Postgres connection pool for the trace store.

Raw asyncpg, no ORM/migration tool — this deliberately matches adar-rag's
own convention (backend/database/connection.py): a single module-level
asyncpg.Pool, created once at FastAPI startup, plus idempotent
`CREATE TABLE IF NOT EXISTS` DDL run on every boot instead of Alembic
migrations. asyncpg is already a declared dependency here (used by ADK's
own session store), so this adds zero new drivers.

Fully inert when TRACE_DB_URL is unset — init_trace_pool() becomes a no-op
and every tracing.py function silently skips its DB write (spans still
flow over OTLP to the Collector either way).
"""

from __future__ import annotations

import asyncio
import logging

import asyncpg

from src.adar.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

CREATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS trace_flows (
    trace_id           TEXT        PRIMARY KEY,
    domain             TEXT        NOT NULL,
    request_type       TEXT        NOT NULL,
    practice_id        TEXT,
    team_id            TEXT,
    session_id         TEXT,
    user_id            TEXT,
    status             TEXT        NOT NULL DEFAULT 'running',
    input_text_hash    TEXT,
    input_text_preview TEXT,
    client_info        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    metadata           JSONB       NOT NULL DEFAULT '{}'::jsonb,
    error_message      TEXT,
    started_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at           TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_trace_flows_practice ON trace_flows(practice_id);
CREATE INDEX IF NOT EXISTS idx_trace_flows_domain   ON trace_flows(domain);
CREATE INDEX IF NOT EXISTS idx_trace_flows_started  ON trace_flows(started_at DESC);

CREATE TABLE IF NOT EXISTS trace_spans (
    span_id        TEXT        PRIMARY KEY,
    trace_id       TEXT        NOT NULL REFERENCES trace_flows(trace_id) ON DELETE CASCADE,
    parent_span_id TEXT,
    name           TEXT        NOT NULL,
    status         TEXT        NOT NULL DEFAULT 'running',
    metadata       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    error          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at       TIMESTAMPTZ,
    duration_ms    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_trace_spans_trace ON trace_spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_trace_spans_name  ON trace_spans(name);

CREATE TABLE IF NOT EXISTS trace_llm_events (
    event_id           TEXT        PRIMARY KEY,
    trace_id           TEXT        NOT NULL REFERENCES trace_flows(trace_id) ON DELETE CASCADE,
    span_id            TEXT        REFERENCES trace_spans(span_id) ON DELETE SET NULL,
    provider           TEXT        NOT NULL,
    model              TEXT,
    operation          TEXT        NOT NULL,
    system_prompt      TEXT,
    user_prompt        TEXT,
    tool_request_json  JSONB       NOT NULL DEFAULT '{}'::jsonb,
    tool_response_json JSONB       NOT NULL DEFAULT '{}'::jsonb,
    llm_response       TEXT,
    input_tokens       INTEGER,
    output_tokens      INTEGER,
    latency_ms         INTEGER,
    finish_reason      TEXT,
    redaction_status   TEXT        NOT NULL DEFAULT 'redacted',
    error              TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_trace_llm_trace ON trace_llm_events(trace_id);
CREATE INDEX IF NOT EXISTS idx_trace_llm_span  ON trace_llm_events(span_id);
CREATE INDEX IF NOT EXISTS idx_trace_llm_op    ON trace_llm_events(operation);

-- Judge-agent evaluation correlation (Phase 4): the eval always reuses the
-- request's own trace_id — never a freshly minted one — so a trace and its
-- eval score are one join away.
CREATE TABLE IF NOT EXISTS trace_evaluations (
    eval_id     TEXT        PRIMARY KEY,
    trace_id    TEXT        REFERENCES trace_flows(trace_id) ON DELETE CASCADE,
    domain      TEXT,
    team_id     TEXT,
    session_id  TEXT,
    accuracy    INTEGER,
    completeness INTEGER,
    relevance   INTEGER,
    format      INTEGER,
    overall     NUMERIC,
    explanation TEXT,
    model       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_trace_evals_trace ON trace_evaluations(trace_id);
"""


async def init_trace_pool() -> asyncpg.Pool | None:
    """Hard-capped at a few seconds total. A hung/unreachable Postgres
    connection must NEVER be able to block the rest of app startup — if it
    did, Cloud Run's readiness probe would time out and take down every
    endpoint (chat, STT, everything), not just tracing. Production hit
    exactly this: asyncpg.create_pool() has no built-in connect timeout of
    its own, so a bad socket path / unreachable instance can hang
    indefinitely instead of failing fast."""
    global _pool
    if not settings.TRACE_DB_ENABLED:
        logger.info("TRACE_DB_URL not set — Postgres trace store disabled")
        return None
    try:
        _pool = await asyncio.wait_for(
            asyncpg.create_pool(
                settings.TRACE_DB_URL, min_size=1, max_size=10,
                timeout=5, command_timeout=10,
            ),
            timeout=8,
        )
        async with _pool.acquire() as conn:
            await asyncio.wait_for(conn.execute(CREATE_SCHEMA), timeout=10)
        logger.info("Trace store ready (Postgres)")
        return _pool
    except asyncio.TimeoutError:
        logger.error(
            "Postgres trace store did not respond within the startup timeout "
            "(unreachable instance, wrong socket path, or bad credentials) — "
            "continuing WITHOUT the trace store rather than blocking startup."
        )
        _pool = None
        return None
    except Exception:
        logger.exception("Failed to initialize Postgres trace store; tracing DB writes will be skipped")
        _pool = None
        return None


def get_trace_pool() -> asyncpg.Pool | None:
    return _pool


async def close_trace_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
