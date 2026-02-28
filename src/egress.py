"""
LiveKit Egress: start room composite (audio-only) recording to S3 when the agent joins.

Controlled by env:
- EGRESS_ENABLED: set to 1 or true to enable
- EGRESS_S3_BUCKET: S3 bucket name (required if enabled)
- EGRESS_S3_PREFIX: optional prefix for object keys (e.g. "recordings/")
- AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION: used for S3 upload (LiveKit egress service uploads to your bucket)

Uses LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET for the Egress API call.
"""

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("agent.egress")


def _is_egress_enabled() -> bool:
    v = os.getenv("EGRESS_ENABLED", "").strip().lower()
    return v in ("1", "true", "yes")


def _get_egress_config() -> dict | None:
    if not _is_egress_enabled():
        return None
    bucket = os.getenv("EGRESS_S3_BUCKET", "").strip()
    if not bucket:
        logger.warning("EGRESS_ENABLED set but EGRESS_S3_BUCKET is empty; egress disabled")
        return None
    url = os.getenv("LIVEKIT_URL", "").strip()
    key = os.getenv("LIVEKIT_API_KEY", "").strip()
    secret = os.getenv("LIVEKIT_API_SECRET", "").strip()
    if not url or not key or not secret:
        logger.warning("Egress enabled but LIVEKIT_URL/API_KEY/API_SECRET missing; egress disabled")
        return None
    access = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
    region = os.getenv("AWS_REGION", "us-east-1").strip()
    if not access or not secret_key:
        logger.warning("Egress enabled but AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY missing; egress disabled")
        return None
    prefix = (os.getenv("EGRESS_S3_PREFIX", "").strip() or "recordings").rstrip("/")
    return {
        "bucket": bucket,
        "prefix": prefix,
        "url": url,
        "api_key": key,
        "api_secret": secret,
        "access_key": access,
        "secret_key": secret_key,
        "region": region,
    }


async def start_room_egress(room_name: str) -> None:
    """Start audio-only room composite egress to S3. No-op if egress is disabled or config missing."""
    config = _get_egress_config()
    if not config:
        return

    from livekit.api import (
        LiveKitAPI,
        RoomCompositeEgressRequest,
        EncodedFileOutput,
        EncodedFileType,
        S3Upload,
    )

    # Object key: prefix/YYYY/MM/DD/room_name.ogg
    now = datetime.now(timezone.utc)
    date_path = now.strftime("%Y/%m/%d")
    filepath = f"{config['prefix']}/{date_path}/{room_name}.ogg"

    try:
        lk = LiveKitAPI(
            url=config["url"],
            api_key=config["api_key"],
            api_secret=config["api_secret"],
        )
        try:
            req = RoomCompositeEgressRequest(
                room_name=room_name,
                audio_only=True,
                file_outputs=[
                    EncodedFileOutput(
                        file_type=EncodedFileType.OGG,
                        filepath=filepath,
                        s3=S3Upload(
                            access_key=config["access_key"],
                            secret=config["secret_key"],
                            bucket=config["bucket"],
                            region=config["region"],
                        ),
                    )
                ],
            )
            info = await lk.egress.start_room_composite_egress(req)
            egress_id = getattr(info, "egress_id", None) or getattr(info, "id", "")
            logger.info(
                "Egress started: room=%s egress_id=%s path=%s",
                room_name,
                egress_id,
                filepath,
            )
        finally:
            await lk.aclose()
    except Exception as e:
        logger.exception("Failed to start egress for room %s: %s", room_name, e)
