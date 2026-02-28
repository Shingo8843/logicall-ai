"""
Prometheus /metrics endpoint for Grafana Cloud (or any Prometheus) scrape.

Start the HTTP server once at agent process startup (e.g. in prewarm or main).
Metrics are registered here and updated from session_hooks and latency.
"""

import logging
import os

logger = logging.getLogger("agent.metrics")

# Lazy init: server started on first ensure_metrics_started() call
_metrics_started = False

# Prometheus metrics (created on first use)
_voice_round_trip = None
_voice_round_trip_session_avg = None
_inference_duration = None
_sessions_started = None


def _get_histogram(name: str, help_text: str, buckets: list[float] | None = None):
    from prometheus_client import Histogram

    if buckets is None:
        buckets = (50, 100, 200, 500, 1000, 2000, 5000)
    return Histogram(
        name,
        help_text,
        labelnames=("profile_id",),
        buckets=buckets,
        registry=__registry(),
    )


def _get_counter(name: str, help_text: str):
    from prometheus_client import Counter

    return Counter(
        name,
        help_text,
        labelnames=("profile_id",),
        registry=__registry(),
    )


def __registry():
    from prometheus_client import REGISTRY

    return REGISTRY


def _ensure_metrics_created():
    global _voice_round_trip, _voice_round_trip_session_avg, _inference_duration, _sessions_started
    if _voice_round_trip is not None:
        return
    _voice_round_trip = _get_histogram(
        "logicall_voice_round_trip_latency_ms",
        "Voice round-trip latency (user spoke to agent spoke) in milliseconds",
    )
    _voice_round_trip_session_avg = _get_histogram(
        "logicall_voice_round_trip_session_avg_ms",
        "Per-session average voice round-trip latency in milliseconds",
    )
    _inference_duration = _get_histogram(
        "logicall_inference_duration_ms",
        "LLM/STT/TTS inference duration in milliseconds",
        buckets=(10, 25, 50, 100, 250, 500, 1000, 2500, 5000),
    )
    _sessions_started = _get_counter(
        "logicall_sessions_started_total",
        "Total agent sessions started",
    )


def record_voice_round_trip_latency_ms(latency_ms: float, profile_id: str = "default") -> None:
    """Record a single voice round-trip latency sample."""
    _ensure_metrics_created()
    _voice_round_trip.labels(profile_id=profile_id).observe(latency_ms)


def record_voice_round_trip_session_avg_ms(avg_ms: float, profile_id: str = "default") -> None:
    """Record the session-average voice round-trip latency (one sample per session)."""
    _ensure_metrics_created()
    _voice_round_trip_session_avg.labels(profile_id=profile_id).observe(avg_ms)


def record_inference_duration_ms(duration_ms: float, profile_id: str = "default") -> None:
    """Record LLM/STT/TTS inference duration."""
    _ensure_metrics_created()
    _inference_duration.labels(profile_id=profile_id).observe(duration_ms)


def record_session_started(profile_id: str = "default") -> None:
    """Increment sessions started counter."""
    _ensure_metrics_created()
    _sessions_started.labels(profile_id=profile_id).inc()


def ensure_metrics_server_started() -> bool:
    """Start the Prometheus HTTP server for /metrics if METRICS_PORT is set. Returns True if started."""
    global _metrics_started
    if _metrics_started:
        return True
    port_str = os.getenv("METRICS_PORT", "").strip()
    if not port_str:
        return False
    try:
        port = int(port_str)
    except ValueError:
        logger.warning("METRICS_PORT=%s is not a valid integer; metrics server disabled", port_str)
        return False
    if port <= 0 or port > 65535:
        logger.warning("METRICS_PORT=%s out of range; metrics server disabled", port)
        return False
    try:
        from prometheus_client import start_http_server

        _ensure_metrics_created()
        start_http_server(port, addr="0.0.0.0")
        _metrics_started = True
        logger.info("Prometheus metrics server listening on port %s", port)
        return True
    except Exception as e:
        logger.exception("Failed to start metrics server: %s", e)
        return False
