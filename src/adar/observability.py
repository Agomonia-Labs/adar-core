"""src/adar/observability.py — backend adapter over the vendored
adar_observability package (see /adar_observability at the repo root).

Mirrors adar-rag's backend/services/telemetry.py adapter exactly: the
shared package stays generic, this file is where FastAPI-app-specific
wiring (instrumentation, defaults) lives.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import adar_observability
except ImportError:  # Supports running from a source checkout where the
    # repo root isn't already on sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import adar_observability  # noqa: F401

from adar_observability import (  # re-exported for stable app imports
    current_otel_ids,
    current_trace_id,
    enrich_current_span,
    inject_trace_headers,
    otel_span,
    safe_attributes,
    shutdown_telemetry,
    telemetry_enabled,
    traced_span,
)
from adar_observability import configure_telemetry as _configure_shared


def configure_telemetry(app=None, *, default_service_name: str = "adar-core") -> bool:
    """NOTE: deliberately does NOT call FastAPIInstrumentor.instrument_app().
    Hit in production: opentelemetry-instrumentation-fastapi's ASGI
    middleware calls `starlette_route.path` on every request to name the
    span, and crashes with `AttributeError: '_IncludedRouter' object has
    no attribute 'path'` against this FastAPI version's lazy include-router
    mechanism (FastAPI >=0.13x) — every request 500'd once OTEL_ENABLED was
    flipped on. adar-rag (DocIntel) never hit this because it pins
    fastapi==0.111.0, predating lazy routers.

    We don't need that auto-instrumentation anyway: api/main.py's own
    trace_id_middleware opens the request's root span directly via
    traced_span(), so the OTel trace/span ids are real either way — this
    function only sets up the resource/provider/exporter."""
    return _configure_shared(
        default_service_name=default_service_name,
        default_service_version="1.0.0",
    )


__all__ = [
    "configure_telemetry", "current_otel_ids", "current_trace_id",
    "enrich_current_span", "inject_trace_headers", "otel_span",
    "safe_attributes", "shutdown_telemetry", "telemetry_enabled", "traced_span",
]
