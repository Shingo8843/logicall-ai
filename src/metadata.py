"""
Parse and merge job + room metadata into a typed result for the agent.

Used by the agent entrypoint to get profile_id, profile_version, prompt_vars,
and optional tenant/sip/phone info without inline merging logic.
"""

import json
from dataclasses import dataclass


@dataclass
class DispatchMetadata:
    """Parsed dispatch and room metadata for agent configuration."""

    profile_id: str | None
    profile_version: str | None
    prompt_vars: dict | None
    phone_number: str | None
    sip_outbound_trunk_id: str | None
    tenant_id: str | None
    idempotency_key: str | None
    merged: dict


def parse_metadata(job_metadata: str | dict | None, room_metadata: str | dict | None) -> DispatchMetadata:
    """
    Merge job and room metadata and return a typed result.

    Later keys (room) override earlier (job). Values are taken from the merged dict.
    """
    merged: dict = {}

    for raw in (job_metadata, room_metadata):
        if raw is None:
            continue
        try:
            meta = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, AttributeError):
            continue
        if isinstance(meta, dict):
            merged.update(meta)

    return DispatchMetadata(
        profile_id=merged.get("profile_id"),
        profile_version=merged.get("profile_version"),
        prompt_vars=merged.get("prompt_vars") if isinstance(merged.get("prompt_vars"), dict) else None,
        phone_number=merged.get("phone_number"),
        sip_outbound_trunk_id=merged.get("sip_outbound_trunk_id"),
        tenant_id=merged.get("tenant_id"),
        idempotency_key=merged.get("idempotency_key"),
        merged=merged,
    )
