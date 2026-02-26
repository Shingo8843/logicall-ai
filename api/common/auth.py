"""
API key authentication for the Lambda API.

Expects API_KEY (or LOGICALL_API_KEY) in the environment. Clients send the key via:
  - Header: Authorization: Bearer <api_key>
  - Header: X-API-Key: <api_key>

If API_KEY is not set, all requests are rejected with 503 (server not configured).
"""

import logging
import os
from typing import Annotated

from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)

# Optional: allow a second env name for the key
API_KEY_ENV = os.getenv("API_KEY") or os.getenv("LOGICALL_API_KEY") or ""


def get_api_key_from_headers(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> str:
    """
    FastAPI dependency: extract API key from Authorization or X-API-Key header.
    Raises 401 if missing/invalid, 503 if server has no API_KEY configured.
    """
    if not API_KEY_ENV or not API_KEY_ENV.strip():
        logger.warning("API_KEY (or LOGICALL_API_KEY) not set; rejecting request")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key authentication not configured",
        )

    provided: str | None = None
    if x_api_key and x_api_key.strip():
        provided = x_api_key.strip()
    elif authorization and authorization.strip().lower().startswith("bearer "):
        provided = authorization.strip()[7:].strip()

    if not provided or provided != API_KEY_ENV:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return provided


# Dependency for use in routers: Depends(verify_api_key)
verify_api_key = get_api_key_from_headers
