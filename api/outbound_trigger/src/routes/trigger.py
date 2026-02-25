"""Route for triggering outbound calls via LiveKit agent dispatch."""

import json
import logging
import random
import string

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.common.secrets import get_livekit_credentials
from api.common.livekit_client import create_livekit_api

logger = logging.getLogger(__name__)

router = APIRouter()


class TriggerRequest(BaseModel):
    phone_number: str = Field(..., pattern=r"^\+\d{7,15}$", description="E.164 phone number")
    agent_name: str = Field(default="logicall-agent", description="Agent name to dispatch")
    profile_id: str | None = Field(
        default=None,
        description="Optional AgentProfile ID to use for this call",
    )
    profile_version: str | None = Field(
        default=None,
        description="Optional AgentProfile version; defaults to latest if omitted",
    )
    prompt_vars: dict | None = Field(
        default=None,
        description="Variables to substitute in the profile prompt, e.g. {'logistics_company': 'Acme', 'agent_name': 'Alex', 'tracking_number': '123'}",
    )
    metadata: dict | None = Field(default=None, description="Extra metadata for the dispatch")


class TriggerResponse(BaseModel):
    room: str
    phone_number: str
    agent_name: str


def _random_room_name() -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    return f"outbound-{suffix}"


@router.post("/trigger", response_model=TriggerResponse)
async def trigger_outbound_call(req: TriggerRequest):
    creds = get_livekit_credentials()
    if not creds:
        raise HTTPException(status_code=500, detail="Failed to retrieve LiveKit credentials")

    dispatch_meta = {"phone_number": req.phone_number}

    # Allow caller to select a specific AgentProfile.
    # The LiveKit agent worker reads `profile_id` and `profile_version`
    # from room/job metadata and resolves the configuration from DynamoDB.
    if req.profile_id is not None:
        dispatch_meta["profile_id"] = req.profile_id
    if req.profile_version is not None:
        dispatch_meta["profile_version"] = req.profile_version
    if req.prompt_vars:
        dispatch_meta["prompt_vars"] = {k: str(v) for k, v in req.prompt_vars.items()}
    if req.metadata:
        dispatch_meta.update(req.metadata)

    room_name = _random_room_name()

    lk = create_livekit_api(creds)
    try:
        from livekit.api import CreateAgentDispatchRequest

        await lk.agent_dispatch.create_dispatch(
            CreateAgentDispatchRequest(
                agent_name=req.agent_name,
                room=room_name,
                metadata=json.dumps(dispatch_meta),
            )
        )
    except Exception as e:
        logger.exception("Failed to dispatch agent")
        raise HTTPException(status_code=500, detail=f"Dispatch failed: {e}")
    finally:
        await lk.aclose()

    logger.info("Dispatched outbound call: room=%s phone=%s agent=%s", room_name, req.phone_number, req.agent_name)

    return TriggerResponse(
        room=room_name,
        phone_number=req.phone_number,
        agent_name=req.agent_name,
    )
