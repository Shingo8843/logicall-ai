"""Telephony tools: LiveKit SDK end_call and send_dtmf_events, plus custom wait."""

import os
import asyncio
import logging
from typing import Any

from livekit.agents import function_tool

from ..latency import timed_async_tool

logger = logging.getLogger("agent_tools")

# SDK naming: end_call, send_dtmf_events. Aliases hang_up/send_dtmf for backward compatibility.
DEFAULT_TELEPHONY_TOOL_IDS = {"end_call", "wait", "send_dtmf_events"}

# EndCallTool delete_room: set to "0" or "false" to only shutdown session (room stays).
_HANG_UP_DELETE_ROOM = os.environ.get("LOGICALL_HANG_UP_DELETE_ROOM", "true").lower() in ("1", "true", "yes")


async def _wait(seconds: int = 2) -> str:
    """Intentionally pause while backend operations complete."""
    clamped = max(0, min(int(seconds), 30))
    logger.info("wait requested: %ss", clamped)
    if clamped > 0:
        await asyncio.sleep(clamped)
    return f"Waited {clamped} second(s)"


def build_telephony_registry() -> dict[str, Any]:
    """
    Build the registry of telephony tools using LiveKit SDK where available.

    - end_call: livekit.agents.beta.tools.EndCallTool (delete_room from env)
    - send_dtmf_events: livekit.agents.beta.tools.send_dtmf_events
    - wait: custom (no SDK equivalent)
    - hang_up: alias for end_call
    - send_dtmf: alias for send_dtmf_events
    """
    from livekit.agents.beta.tools.end_call import EndCallTool
    from livekit.agents.beta.tools.send_dtmf import send_dtmf_events

    end_call_toolset = EndCallTool(delete_room=_HANG_UP_DELETE_ROOM)
    end_call_tools = end_call_toolset.tools  # list of Tool
    end_call_tool = end_call_tools[0] if end_call_tools else None

    registry = {}
    if end_call_tool:
        registry["end_call"] = end_call_tool
        registry["hang_up"] = end_call_tool  # backward compat

    registry["send_dtmf_events"] = send_dtmf_events
    registry["send_dtmf"] = send_dtmf_events  # backward compat

    registry["wait"] = function_tool(
        timed_async_tool("wait", _wait),
        name="wait",
        description="Pause for a short number of seconds while waiting for backend state.",
    )

    return registry
