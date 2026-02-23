"""Shared LiveKit API client factory."""

from typing import Any

from livekit.api import LiveKitAPI


def create_livekit_api(creds: dict[str, Any]) -> LiveKitAPI:
    """Create a LiveKitAPI instance from Secrets Manager credentials."""
    return LiveKitAPI(
        url=creds["LIVEKIT_URL"],
        api_key=creds["LIVEKIT_API_KEY"],
        api_secret=creds["LIVEKIT_API_SECRET"],
    )
