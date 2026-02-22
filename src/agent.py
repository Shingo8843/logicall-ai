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
from .profile_resolver import resolve_profile
from .session_builder import build_session
from .tools import DEFAULT_TELEPHONY_TOOL_IDS, resolve_tools

logger = logging.getLogger("agent")

load_dotenv(".env.local")


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
    
    # Step 1: Resolve profile_id and outbound dial info from metadata
    profile_id = None
    profile_version = None
    phone_number = None

    for raw_meta in (ctx.job.metadata, ctx.room.metadata):
        if not raw_meta:
            continue
        try:
            meta = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
        except (json.JSONDecodeError, AttributeError):
            continue
        if profile_id is None:
            profile_id = meta.get("profile_id")
        if profile_version is None:
            profile_version = meta.get("profile_version")
        if phone_number is None:
            phone_number = meta.get("phone_number")
    
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
    
    # Step 5: Create agent with profile instructions
    agent = ConfigurableAgent(
        system_prompt=profile.system_prompt,
        tools=tools,
    )
    
    # Step 6: Start session with all room options
    await session.start(
        agent=agent,
        room=ctx.room,
        room_options=room_options,
    )
    
    logger.info(
        f"Agent session started: profile={profile.profile_id}, "
        f"mode={profile.mode}, language={profile.language}"
    )
    
    # Step 7: Connect to room
    await ctx.connect()

    # Step 8: Outbound dial or inbound greeting
    if phone_number:
        sip_trunk_id = profile.sip_outbound_trunk_id
        if not sip_trunk_id:
            logger.error("Outbound call requested but no sip_outbound_trunk_id in profile")
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
