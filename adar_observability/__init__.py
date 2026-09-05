"""Shared OpenTelemetry utilities for ADAR services.

Vendored from the same design already proven in adar-rag's
docintel_observability package (kept intentionally close to that source so
the two stay easy to reconcile), generalized for reuse across every ADAR
product, not just DocIntel.
"""

from .telemetry import (
    configure_telemetry,
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

__all__ = [
    "configure_telemetry", "current_otel_ids", "current_trace_id",
    "enrich_current_span", "inject_trace_headers", "otel_span",
    "safe_attributes", "shutdown_telemetry", "telemetry_enabled", "traced_span",
]
