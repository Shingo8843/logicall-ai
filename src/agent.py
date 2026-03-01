"""
Single-agent entrypoint using a static Amazon Nova profile.

Uses one statically configured agent (Amazon Nova realtime) from config.
Profile models and resolver are kept for future use.
Handles both inbound and outbound calls. Outbound dialing is done by Lambda;
the agent only joins the room and greets.
"""

import logging

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    JobContext,
    JobProcess,
    cli,
)
from livekit.plugins import silero

# Register AWS plugin on main thread so realtime (Amazon Nova) works in job processes.
import livekit.plugins.aws  # noqa: F401

from .config import get_default_profile
from .metadata import DispatchMetadata, parse_metadata
from .session_builder import build_session
from .session_hooks import attach_session_hooks
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

    Parse metadata -> resolve profile -> resolve tools -> build session ->
    start session -> attach hooks -> connect -> greet.
    Outbound dialing is done by Lambda; agent never calls SIP create participant.
    """
    ctx.log_context_fields = {
        "room": ctx.room.name,
        "job_id": ctx.job.id,
    }

    # Step 1: Parse metadata (prompt_vars for optional runtime substitution)
    meta: DispatchMetadata = parse_metadata(ctx.job.metadata, ctx.room.metadata)

    # Step 2: Use static agent profile (Amazon Nova from config)
    profile = get_default_profile()
    logger.info(
        "Using static profile: %s v%s (mode=%s)",
        profile.profile_id,
        profile.version,
        profile.mode,
    )

    # Step 3: Resolve tools from tool_refs
    requested_tool_ids = set(profile.tool_refs or [])
    enabled_tool_ids = DEFAULT_TELEPHONY_TOOL_IDS | requested_tool_ids
    tools = await resolve_tools(enabled_tool_ids)
    logger.debug("Enabled tools for session: %s", sorted(enabled_tool_ids))

    # Step 4: Build AgentSession with full configuration
    try:
        session, room_options = await build_session(
            profile=profile,
            vad=ctx.proc.userdata["vad"],
            job_context=ctx,
        )
        logger.debug("AgentSession built successfully with profile configuration")
    except Exception as e:
        logger.error("Failed to build session: %s", e, exc_info=True)
        raise

    # Step 5: Create agent with profile instructions (optional runtime prompt vars)
    prompt_vars = meta.prompt_vars
    if isinstance(prompt_vars, dict):
        system_prompt = _apply_prompt_vars(profile.system_prompt, prompt_vars)
    else:
        system_prompt = profile.system_prompt

    agent = ConfigurableAgent(system_prompt=system_prompt, tools=tools)

    # Step 6: Start session with all room options
    await session.start(
        agent=agent,
        room=ctx.room,
        room_options=room_options,
    )

    # Step 7: Attach session hooks (latency, metrics, limits)
    attach_session_hooks(session, profile, ctx.room.name, ctx.job.id, ctx)

    logger.info(
        "Agent session started: profile=%s, mode=%s, language=%s",
        profile.profile_id,
        profile.mode,
        profile.language,
    )

    # Step 8: Connect to room
    await ctx.connect()

    # Step 9: Greet (inbound or outbound: same behavior; SIP participant is already in room for outbound)
    await session.generate_reply(
        instructions="Greet the user and offer your assistance."
    )


if __name__ == "__main__":
    cli.run_app(server)
