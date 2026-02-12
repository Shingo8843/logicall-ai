"""
Full configuration agent with database-driven profile system.

This agent supports all LiveKit configuration options surfaced via
DynamoDB profiles with sensible defaults for everything.
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
from .profile_resolver import resolve_profile
from .session_builder import build_session

logger = logging.getLogger("agent")

load_dotenv(".env.local")


class ConfigurableAgent(Agent):
    """
    Agent that uses configuration from profile.
    
    Instructions and tools are set from the profile configuration.
    """
    
    def __init__(self, system_prompt: str, tools: list = None) -> None:
        super().__init__(
            instructions=system_prompt,
            tools=tools or [],
        )


server = AgentServer()


def prewarm(proc: JobProcess):
    """Prewarm VAD model for faster session startup."""
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session()
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
    
    # Step 1: Resolve profile_id from room metadata or default
    profile_id = None
    profile_version = None
    
    # Check room metadata for profile_id
    if ctx.room.metadata:
        # Room metadata is typically a JSON string, parse it
        import json
        try:
            metadata = json.loads(ctx.room.metadata) if isinstance(ctx.room.metadata, str) else ctx.room.metadata
            profile_id = metadata.get("profile_id")
            profile_version = metadata.get("profile_version")
        except (json.JSONDecodeError, AttributeError):
            logger.debug("Could not parse room metadata, using defaults")
    
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
    # TODO: Fetch tool definitions from DynamoDB
    tools = []
    # For now, tools are empty - implement tool resolution later
    
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
    
    # Step 8: Apply profile limits (if any)
    # TODO: Implement limit monitoring and enforcement
    # This would track:
    # - max_minutes: Total session duration
    # - max_tool_calls: Total tool calls
    # - max_tool_calls_per_minute: Rate limiting


if __name__ == "__main__":
    cli.run_app(server)
