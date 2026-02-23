"""Retrieve secrets from AWS Secrets Manager with in-memory caching."""

import json
import logging
import os
from functools import lru_cache
from typing import Any

import boto3

logger = logging.getLogger(__name__)

SECRET_ID = os.getenv("LIVEKIT_SECRET_ID", "livekit-agent-secrets")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

_client = boto3.client("secretsmanager", region_name=AWS_REGION)


@lru_cache(maxsize=1)
def get_livekit_credentials() -> dict[str, Any] | None:
    """Fetch LiveKit credentials from Secrets Manager (cached for Lambda lifetime)."""
    try:
        resp = _client.get_secret_value(SecretId=SECRET_ID)
        return json.loads(resp["SecretString"])
    except Exception:
        logger.exception("Failed to retrieve secret %s", SECRET_ID)
        return None
