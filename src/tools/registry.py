"""Tool resolution: combine telephony built-ins and profile-scoped HTTP tools."""

import logging
import os
from collections.abc import Iterable

from livekit.agents import FunctionTool

from .http_dynamic import fetch_http_tool_definition, make_http_tool, parse_http_tool_ref
from .telephony import DEFAULT_TELEPHONY_TOOL_IDS, build_telephony_registry

logger = logging.getLogger("agent_tools")


async def resolve_tools(tool_ids: Iterable[str]) -> list[FunctionTool]:
    """
    Build a strict tool list for an agent.

    Only tool IDs in `tool_ids` are returned. This supports:
    - Built-ins: end_call, wait, send_dtmf_events (telephony; hang_up/send_dtmf are aliases)
    - Profile-scoped HTTP tools: http:<tool_id>@<version>
    """
    table_name = os.getenv("DYNAMODB_TABLE_NAME", "logicall_agent_config")
    region = os.getenv("AWS_REGION", "us-east-1")
    builtin_registry = build_telephony_registry()

    selected: list[FunctionTool] = []
    for tool_id in tool_ids:
        builtin = builtin_registry.get(tool_id)
        if builtin is not None:
            selected.append(builtin)
            continue

        http_ref = parse_http_tool_ref(tool_id)
        if http_ref is not None:
            http_def = await fetch_http_tool_definition(
                http_ref,
                table_name=table_name,
                region=region,
            )
            if http_def is None:
                continue
            selected.append(make_http_tool(http_def))
            continue

        logger.warning("Unknown tool_id requested, skipping: %s", tool_id)

    return selected
