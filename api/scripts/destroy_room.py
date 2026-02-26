"""
Destroy a LiveKit room (disconnects all participants and ends the session).

Usage:
  From project root, with LIVEKIT_* in .env.local or env:
    uv run python api/scripts/destroy_room.py <room_name>
    uv run python api/scripts/destroy_room.py outbound-abc123xyz

  Or set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET.
"""

import asyncio
import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env.local")
load_dotenv()


async def main() -> None:
    room_name = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("ROOM_NAME", "")).strip()
    if not room_name:
        print("Usage: python api/scripts/destroy_room.py <room_name>")
        print("   or: ROOM_NAME=outbound-xxx python api/scripts/destroy_room.py")
        sys.exit(1)

    # Reuse same credential loading as the Lambda/API
    try:
        from api.common.secrets import get_livekit_credentials
        from api.common.livekit_client import create_livekit_api
    except ImportError:
        url = os.getenv("LIVEKIT_URL")
        key = os.getenv("LIVEKIT_API_KEY")
        secret = os.getenv("LIVEKIT_API_SECRET")
        if not url or not key or not secret:
            print("Set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET (e.g. in .env.local)")
            sys.exit(1)
        creds = {"LIVEKIT_URL": url, "LIVEKIT_API_KEY": key, "LIVEKIT_API_SECRET": secret}
        from livekit.api import LiveKitAPI
        lk = LiveKitAPI(url=url, api_key=key, api_secret=secret)
    else:
        creds = get_livekit_credentials()
        if not creds:
            print("Failed to load LiveKit credentials (env or Secrets Manager)")
            sys.exit(1)
        lk = create_livekit_api(creds)

    from livekit import api

    try:
        await lk.room.delete_room(api.DeleteRoomRequest(room=room_name))
        print(f"Room '{room_name}' destroyed.")
    except Exception as e:
        err_msg = str(e)
        if "not found" in err_msg.lower() or "does not exist" in err_msg.lower():
            print(f"Room '{room_name}' not found or already closed.")
        else:
            print(f"Error: {e}")
        sys.exit(1)
    finally:
        await lk.aclose()


if __name__ == "__main__":
    asyncio.run(main())
