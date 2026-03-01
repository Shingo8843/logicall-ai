"""
Session event hooks: latency, metrics, and profile limits.

Attach to an AgentSession after session.start() so the agent entrypoint
stays thin and LiveKit-first behavior is preserved.
"""

import asyncio
import logging
import time
from collections import deque

from .latency import log_latency

logger = logging.getLogger("agent.session_hooks")

VOICE_ROUND_TRIP_MIN_MS = 50.0


def attach_session_hooks(session, profile, room_name: str, job_id: str, ctx):
    """
    Attach latency listeners, metrics logging, and profile limits to the session.

    - user_input_transcribed / speech_created: voice round-trip latency
    - close: session-average round-trip
    - metrics_collected: LLM/TTS/STT metrics
    - function_tools_executed: limits enforcement (max_tool_calls, max_tool_calls_per_minute)
    - max_minutes: timeout task and shutdown callback

    Caller must call ctx.add_shutdown_callback(_cleanup_limit_tasks) with the returned cleanup.
    """
    limits = profile.limits
    voice_round_trip_state = {
        "turn_start_time": None,
        "samples_ms": [],
    }

    @session.on("user_input_transcribed")
    def _on_user_input_transcribed(event) -> None:
        if getattr(event, "is_final", False):
            voice_round_trip_state["turn_start_time"] = time.perf_counter()

    @session.on("speech_created")
    def _on_speech_created(event) -> None:
        t0 = voice_round_trip_state.get("turn_start_time")
        if t0 is not None:
            latency_ms = (time.perf_counter() - t0) * 1000
            voice_round_trip_state["turn_start_time"] = None
            if latency_ms >= VOICE_ROUND_TRIP_MIN_MS:
                voice_round_trip_state["samples_ms"].append(latency_ms)
                log_latency(
                    "voice_round_trip",
                    latency_ms,
                    room=room_name,
                    job_id=job_id,
                    extra={"source": getattr(event, "source", "unknown")},
                )

    @session.on("close")
    def _on_session_close(event) -> None:
        samples = voice_round_trip_state.get("samples_ms") or []
        if not samples:
            return
        n = len(samples)
        avg_ms = sum(samples) / n
        log_latency(
            "voice_round_trip_session_avg",
            avg_ms,
            room=room_name,
            job_id=job_id,
            extra={
                "count": n,
                "min_ms": min(samples),
                "max_ms": max(samples),
            },
        )

    @session.on("metrics_collected")
    def _on_metrics_collected(event) -> None:
        metrics = getattr(event, "metrics", None)
        if metrics is None:
            return
        name = type(metrics).__name__
        extra = {"room": room_name, "job_id": job_id}
        if hasattr(metrics, "input_tokens"):
            extra["input_tokens"] = metrics.input_tokens
        if hasattr(metrics, "output_tokens"):
            extra["output_tokens"] = metrics.output_tokens
        if hasattr(metrics, "latency_ms"):
            log_latency(f"llm_{name}", metrics.latency_ms, room=room_name, job_id=job_id, extra=extra)
        elif hasattr(metrics, "duration_ms"):
            log_latency(f"inference_{name}", metrics.duration_ms, room=room_name, job_id=job_id, extra=extra)
        elif extra.get("input_tokens") is not None or extra.get("output_tokens") is not None:
            logger.debug("metrics_collected %s", name, extra={"extra": extra})

    # Limits
    limit_state = {
        "triggered": False,
        "tool_calls_total": 0,
        "tool_call_timestamps": deque(),
    }

    def _trigger_shutdown(reason: str) -> None:
        if limit_state["triggered"]:
            return
        limit_state["triggered"] = True
        logger.warning("Profile limit reached, shutting down session: %s", reason)
        session.shutdown(drain=True)

    timeout_task: asyncio.Task | None = None
    max_minutes = limits.max_minutes
    if max_minutes is not None and max_minutes > 0:
        timeout_seconds = float(max_minutes) * 60.0

        async def _timeout_shutdown() -> None:
            await asyncio.sleep(timeout_seconds)
            _trigger_shutdown(f"max_minutes={max_minutes}")

        timeout_task = asyncio.create_task(_timeout_shutdown())

    @session.on("function_tools_executed")
    def _on_function_tools_executed(ev) -> None:
        call_count = len(getattr(ev, "function_calls", []) or [])
        if call_count <= 0:
            return

        now = time.time()
        timestamps = limit_state["tool_call_timestamps"]

        limit_state["tool_calls_total"] += call_count
        for _ in range(call_count):
            timestamps.append(now)

        one_minute_ago = now - 60.0
        while timestamps and timestamps[0] < one_minute_ago:
            timestamps.popleft()

        max_tool_calls = limits.max_tool_calls
        if max_tool_calls is not None and limit_state["tool_calls_total"] > max_tool_calls:
            _trigger_shutdown(
                f"max_tool_calls={max_tool_calls}, "
                f"current_total={limit_state['tool_calls_total']}"
            )
            return

        max_tool_calls_per_minute = limits.max_tool_calls_per_minute
        if (
            max_tool_calls_per_minute is not None
            and len(timestamps) > max_tool_calls_per_minute
        ):
            _trigger_shutdown(
                f"max_tool_calls_per_minute={max_tool_calls_per_minute}, "
                f"current_last_minute={len(timestamps)}"
            )

    async def _cleanup_limit_tasks() -> None:
        if timeout_task is not None and not timeout_task.done():
            timeout_task.cancel()
            try:
                await timeout_task
            except asyncio.CancelledError:
                pass

    ctx.add_shutdown_callback(_cleanup_limit_tasks)
