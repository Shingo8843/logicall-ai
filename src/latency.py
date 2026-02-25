"""
Latency measurement helpers for voice round-trip and tool/LLM calls.

Logs structured fields (room, job_id, metric, latency_ms) for aggregation
in CloudWatch, Datadog, or similar.
"""

import logging
import time
from functools import wraps
from inspect import signature
from typing import Any

logger = logging.getLogger("agent.latency")


def log_latency(
    metric: str,
    latency_ms: float,
    *,
    room: str | None = None,
    job_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Log a latency measurement with optional context."""
    msg = f"{metric} latency_ms={latency_ms:.1f}"
    log_extra = {}
    if room:
        log_extra["room"] = room
    if job_id:
        log_extra["job_id"] = job_id
    if extra:
        log_extra.update(extra)
    if log_extra:
        logger.info(msg, extra={"extra": log_extra})
    else:
        logger.info(msg)


def timed_async_tool(tool_name: str, fn):
    """Wrap an async tool function to log execution latency.

    Preserves the original function's signature and annotations so that
    schema builders (e.g. AWS Bedrock realtime tool config) see real
    parameter names and types instead of *args/**kwargs.
    """

    @wraps(fn)
    async def wrapped(*args, **kwargs):
        start = time.perf_counter()
        try:
            return await fn(*args, **kwargs)
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            log_latency("tool_call", elapsed_ms, extra={"tool": tool_name})

    try:
        wrapped.__signature__ = signature(fn)
    except ValueError:
        pass
    wrapped.__annotations__ = getattr(fn, "__annotations__", {}).copy()
    return wrapped
