"""
Full configuration agent with database-driven profile system.

This agent supports all LiveKit configuration options surfaced via
DynamoDB profiles with sensible defaults for everything.
Handles both inbound and outbound calls from a single entrypoint.
"""

import json
import logging
import asyncio
import time
from collections import deque

from dotenv import load_dotenv
from livekit import api
from livekit.agents import (
    Agent,
    AgentServer,
    JobContext,
    JobProcess,
    cli,
)
from livekit.plugins import silero

# Register AWS plugin on main thread so realtime (Amazon Nova) works in job processes.
# Must be imported at module load; lazy import in session_builder runs in a worker thread.
import livekit.plugins.aws  # noqa: F401

from .latency import log_latency
from .profile_resolver import resolve_profile
from .session_builder import build_session
from .tools import DEFAULT_TELEPHONY_TOOL_IDS, resolve_tools

logger = logging.getLogger("agent")

load_dotenv(".env.local")

# Metadata keys used for dispatch/routing; not used as prompt template variables.
_RESERVED_META_KEYS = frozenset({"profile_id", "profile_version", "phone_number"})


def _apply_prompt_vars(template: str, variables: dict) -> str:
    """
    Replace {{key}} placeholders in template with values from variables.
    Values are coerced to str. Missing keys are left as {{key}}.
    """
    if not variables:
        return template
    result = template
    for key, value in variables.items():
        if key in _RESERVED_META_KEYS:
            continue
        placeholder = "{{" + key + "}}"
        result = result.replace(placeholder, str(value))
    return result


class ConfigurableAgent(Agent):
    """
    Agent that uses configuration from profile.
    
    Instructions and tools are set from the profile configuration.
    """
    
    def __init__(
        self,
        system_prompt: str,
        tools: list = None,
    ) -> None:
        super().__init__(
            instructions=system_prompt,
            tools=tools or [],
        )


server = AgentServer()


def prewarm(proc: JobProcess):
    """Prewarm VAD model for faster session startup."""
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name="logicall-agent")
async def my_agent(ctx: JobContext):
    """
    Agent entrypoint with full configuration support.
    
    Configuration resolution order:
    1. Check room metadata for profile_id
    2. Fetch default profile pointer from DynamoDB
    3. Load profile with all configuration options
    4. Build AgentSession with resolved config
    5. Apply all session behavior, room I/O, and connection options
    """
    # Logging setup
    ctx.log_context_fields = {
        "room": ctx.room.name,
        "job_id": ctx.job.id,
    }
    
    # Step 1: Resolve profile_id, outbound dial info, and prompt_vars from metadata
    profile_id = None
    profile_version = None
    phone_number = None
    merged_meta: dict = {}

    for raw_meta in (ctx.job.metadata, ctx.room.metadata):
        if not raw_meta:
            continue
        try:
            meta = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
        except (json.JSONDecodeError, AttributeError):
            continue
        if isinstance(meta, dict):
            merged_meta.update(meta)
        if profile_id is None:
            profile_id = meta.get("profile_id") if isinstance(meta, dict) else None
        if profile_version is None:
            profile_version = meta.get("profile_version") if isinstance(meta, dict) else None
        if phone_number is None:
            phone_number = meta.get("phone_number") if isinstance(meta, dict) else None
    
    # Step 2: Resolve profile configuration
    # TODO: Extract tenant_id from context (room, job, or environment)
    tenant_id = "default"
    
    try:
        profile = await resolve_profile(
            tenant_id=tenant_id,
            profile_id=profile_id,
            profile_version=profile_version,
        )
        logger.info(
            f"Loaded profile: {profile.profile_id} v{profile.version} "
            f"(mode={profile.mode}, tenant={tenant_id})"
        )
    except Exception as e:
        logger.error(f"Failed to resolve profile: {e}, using defaults", exc_info=True)
        from .config import get_default_profile
        profile = get_default_profile()
    
    # Step 3: Resolve tools from tool_refs
    default_tool_ids = DEFAULT_TELEPHONY_TOOL_IDS
    requested_tool_ids = set(profile.tool_refs or [])
    enabled_tool_ids = default_tool_ids | requested_tool_ids

    # Build strict pass-only tool list.
    tools = await resolve_tools(enabled_tool_ids)

    logger.debug(
        "Enabled tools for session: %s",
        sorted(enabled_tool_ids),
    )
    
    # Step 4: Build AgentSession with full configuration
    try:
        session, room_options = await build_session(
            profile=profile,
            vad=ctx.proc.userdata["vad"],
            job_context=ctx,
        )
        logger.debug("AgentSession built successfully with profile configuration")
    except Exception as e:
        logger.error(f"Failed to build session: {e}", exc_info=True)
        raise
    
    # Step 5: Create agent with profile instructions (with optional runtime prompt vars)
    # prompt_vars from dispatch/room metadata (e.g. logistics_company, agent_name, tracking_number)
    # are substituted into the profile's system_prompt so each call can be personalized.
    prompt_vars = merged_meta.get("prompt_vars")
    if isinstance(prompt_vars, dict):
        system_prompt = _apply_prompt_vars(profile.system_prompt, prompt_vars)
    else:
        system_prompt = profile.system_prompt

    agent = ConfigurableAgent(
        system_prompt=system_prompt,
        tools=tools,
    )
    
    # Step 6: Start session with all room options
    await session.start(
        agent=agent,
        room=ctx.room,
        room_options=room_options,
    )

    # Latency: voice round-trip (user final transcript -> first agent speech)
    voice_round_trip_state = {
        "turn_start_time": None,
        "samples_ms": [],  # collected for session-end average
    }
    room_name = ctx.room.name
    job_id = ctx.job.id

    @session.on("user_input_transcribed")
    def _on_user_input_transcribed(event) -> None:
        if getattr(event, "is_final", False):
            voice_round_trip_state["turn_start_time"] = time.perf_counter()

    # Minimum ms to log: in realtime mode, user_input_transcribed (final) can fire
    # right before speech_created, giving bogus 3–4 ms; only report plausible round-trips.
    VOICE_ROUND_TRIP_MIN_MS = 50.0

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
        # Log LLM/TTS/STT metrics if they expose latency or token counts
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

    logger.info(
        f"Agent session started: profile={profile.profile_id}, "
        f"mode={profile.mode}, language={profile.language}"
    )

    # Step 7: Connect to room
    await ctx.connect()

    # Step 8: Outbound dial or inbound greeting
    if phone_number:
        # Trunk ID can come from dispatch metadata (e.g. Lambda trigger) or from profile
        sip_trunk_id = merged_meta.get("sip_outbound_trunk_id") or profile.sip_outbound_trunk_id
        if not sip_trunk_id:
            logger.error(
                "Outbound call requested but no sip_outbound_trunk_id. "
                "Pass it in the trigger request (sip_outbound_trunk_id) or set it on the profile in DynamoDB."
            )
            ctx.shutdown()
            return

        try:
            await ctx.api.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    room_name=ctx.room.name,
                    sip_trunk_id=sip_trunk_id,
                    sip_call_to=phone_number,
                    participant_identity=phone_number,
                    participant_name=f"Call to {phone_number}",
                    krisp_enabled=True,
                    wait_until_answered=True,
                )
            )
            logger.info("Outbound call to %s answered", phone_number)
        except api.TwirpError as e:
            logger.error(
                "SIP participant creation failed: %s (SIP %s %s)",
                e.message,
                e.metadata.get("sip_status_code"),
                e.metadata.get("sip_status"),
            )
            ctx.shutdown()
            return
        except Exception as e:
            logger.error("Outbound call failed: %s", e, exc_info=True)
            ctx.shutdown()
            return
    else:
        await session.generate_reply(
            instructions="Greet the user and offer your assistance."
        )

    # Step 9: Apply profile limits (if any)
    limits = profile.limits
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

    # Enforce max session duration.
    max_minutes = limits.max_minutes
    timeout_task: asyncio.Task | None = None
    if max_minutes is not None and max_minutes > 0:
        timeout_seconds = float(max_minutes) * 60.0

        async def _timeout_shutdown() -> None:
            await asyncio.sleep(timeout_seconds)
            _trigger_shutdown(f"max_minutes={max_minutes}")

        timeout_task = asyncio.create_task(_timeout_shutdown())

    # Enforce tool usage limits.
    @session.on("function_tools_executed")
    def _on_function_tools_executed(ev) -> None:  # type: ignore
        call_count = len(getattr(ev, "function_calls", []) or [])
        if call_count <= 0:
            return

        now = time.time()
        timestamps = limit_state["tool_call_timestamps"]

        limit_state["tool_calls_total"] += call_count
        for _ in range(call_count):
            timestamps.append(now)

        # Keep only the trailing 60-second window for per-minute checks.
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


if __name__ == "__main__":
    cli.run_app(server)
