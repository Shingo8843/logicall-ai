"""Retrieve LiveKit credentials from env or AWS Secrets Manager."""

import json
import logging
import os
from functools import lru_cache
from typing import Any

import boto3

logger = logging.getLogger(__name__)

SECRET_ID = os.getenv("LIVEKIT_SECRET_ID", "livekit-agent-secrets")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Keys required for LiveKit API (normalize to these)
REQUIRED_KEYS = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")


def _normalize_creds(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Ensure dict has LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET (any casing)."""
    key_map = {k.upper(): k for k in raw}
    out = {}
    for req in REQUIRED_KEYS:
        if req in key_map and raw.get(key_map[req]):
            out[req] = raw[key_map[req]]
        elif raw.get(req):
            out[req] = raw[req]
        else:
            return None
    return out


@lru_cache(maxsize=1)
def get_livekit_credentials() -> dict[str, Any] | None:
    """
    Get LiveKit credentials (cached for Lambda lifetime).

    Order: (1) Environment variables LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
           (2) AWS Secrets Manager secret from LIVEKIT_SECRET_ID (default: livekit-agent-secrets).

    Secret must be JSON with keys LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
    (or lowercase equivalents). Returns None and logs on failure.
    """
    # 1. Try environment variables (useful for Lambda env config or local dev)
    env_creds = {
        "LIVEKIT_URL": os.getenv("LIVEKIT_URL"),
        "LIVEKIT_API_KEY": os.getenv("LIVEKIT_API_KEY"),
        "LIVEKIT_API_SECRET": os.getenv("LIVEKIT_API_SECRET"),
    }
    if all(env_creds.values()):
        return env_creds

    # 2. Try Secrets Manager
    try:
        client = boto3.client("secretsmanager", region_name=AWS_REGION)
        resp = client.get_secret_value(SecretId=SECRET_ID)
        raw = json.loads(resp["SecretString"])
        if isinstance(raw, dict):
            normalized = _normalize_creds(raw)
            if normalized:
                return normalized
        logger.error("Secret %s missing required keys: %s", SECRET_ID, REQUIRED_KEYS)
    except Exception as e:
        resp = getattr(e, "response", None)
        err_code = (resp.get("Error", {}).get("Code", "") if isinstance(resp, dict) else "")
        if err_code == "ResourceNotFoundException":
            logger.error(
                "Secret not found: %s. Create it in AWS Secrets Manager or set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET on the Lambda.",
                SECRET_ID,
            )
        else:
            logger.exception("Failed to retrieve secret %s: %s", SECRET_ID, e)
    return None
