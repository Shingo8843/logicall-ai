"""Room management and observability endpoints (LiveKit API)."""

import logging
from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from api.common.secrets import get_livekit_credentials
from api.common.livekit_client import create_livekit_api

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms", tags=["rooms"])


def _get_lk():
    creds = get_livekit_credentials()
    if not creds:
        raise HTTPException(status_code=500, detail="Failed to retrieve LiveKit credentials")
    return create_livekit_api(creds)


# ---------------------------------------------------------------------------
# List rooms
# ---------------------------------------------------------------------------


class RoomSummary(BaseModel):
    """Minimal room info for list view."""
    name: str
    num_participants: int = 0
    metadata: str | None = None


class ListRoomsResponse(BaseModel):
    rooms: list[RoomSummary]
    total: int


@router.get("", response_model=ListRoomsResponse)
async def list_rooms():
    """List all active LiveKit rooms (names and participant counts)."""
    lk = _get_lk()
    try:
        from livekit import api
        resp = await lk.room.list_rooms(api.ListRoomsRequest())
        rooms = []
        for r in getattr(resp, "rooms", []) or []:
            name = getattr(r, "name", None) or getattr(r, "sid", None) or ""
            num = getattr(r, "num_participants", 0) or 0
            meta = getattr(r, "metadata", None) or ""
            rooms.append(RoomSummary(name=name, num_participants=num, metadata=meta or None))
        return ListRoomsResponse(rooms=rooms, total=len(rooms))
    except Exception as e:
        logger.exception("List rooms failed")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await lk.aclose()


# ---------------------------------------------------------------------------
# Room summary (observability)
# ---------------------------------------------------------------------------


class RoomsSummaryResponse(BaseModel):
    total_rooms: int
    total_participants: int
    room_names: list[str]
    outbound_count: int = Field(description="Rooms whose name starts with 'outbound-'")


@router.get("/summary", response_model=RoomsSummaryResponse)
async def rooms_summary():
    """Lightweight summary: room count, participant count, and outbound room count."""
    lk = _get_lk()
    try:
        from livekit import api
        resp = await lk.room.list_rooms(api.ListRoomsRequest())
        room_list = getattr(resp, "rooms", []) or []
        names = []
        total_participants = 0
        outbound_count = 0
        for r in room_list:
            name = getattr(r, "name", None) or getattr(r, "sid", None) or ""
            if name:
                names.append(name)
            total_participants += getattr(r, "num_participants", 0) or 0
            if name.startswith("outbound-"):
                outbound_count += 1
        return RoomsSummaryResponse(
            total_rooms=len(names),
            total_participants=total_participants,
            room_names=names,
            outbound_count=outbound_count,
        )
    except Exception as e:
        logger.exception("Rooms summary failed")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await lk.aclose()


# ---------------------------------------------------------------------------
# Room status (single room)
# ---------------------------------------------------------------------------


class ParticipantSummary(BaseModel):
    identity: str
    sid: str | None = None
    metadata: str | None = None
    state: str | None = None


class RoomStatusResponse(BaseModel):
    name: str
    sid: str | None = None
    num_participants: int
    metadata: str | None = None
    participants: list[ParticipantSummary] = Field(default_factory=list)
    empty: bool = False


@router.get("/{room_name}", response_model=RoomStatusResponse)
async def room_status(
    room_name: str = Path(..., description="LiveKit room name"),
):
    """Get status of a room: metadata and participant list. Returns 404 if room not found."""
    if room_name in ("summary", ""):
        raise HTTPException(status_code=404, detail="Not found")
    lk = _get_lk()
    try:
        from livekit import api
        list_resp = await lk.room.list_rooms(api.ListRoomsRequest(names=[room_name]))
        rooms = getattr(list_resp, "rooms", []) or []
        if not rooms:
            raise HTTPException(status_code=404, detail=f"Room '{room_name}' not found")
        r = rooms[0]
        name = getattr(r, "name", None) or getattr(r, "sid", None) or room_name
        num = getattr(r, "num_participants", 0) or 0
        meta = getattr(r, "metadata", None) or None
        part_list = []
        try:
            part_resp = await lk.room.list_participants(api.ListParticipantsRequest(room=room_name))
            for p in getattr(part_resp, "participants", []) or []:
                part_list.append(ParticipantSummary(
                    identity=getattr(p, "identity", None) or getattr(p, "sid", "") or "",
                    sid=getattr(p, "sid", None),
                    metadata=getattr(p, "metadata", None),
                    state=getattr(p, "state", None),
                ))
        except Exception:
            pass
        return RoomStatusResponse(
            name=name,
            sid=getattr(r, "sid", None),
            num_participants=num,
            metadata=meta,
            participants=part_list,
            empty=(num == 0),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Room status failed")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await lk.aclose()


# ---------------------------------------------------------------------------
# List participants in a room
# ---------------------------------------------------------------------------


class ListParticipantsResponse(BaseModel):
    room: str
    participants: list[ParticipantSummary]
    total: int


@router.get("/{room_name}/participants", response_model=ListParticipantsResponse)
async def list_participants(
    room_name: str = Path(..., description="LiveKit room name"),
):
    """List participants in a room. Returns 404 if room not found."""
    if room_name in ("summary", ""):
        raise HTTPException(status_code=404, detail="Not found")
    lk = _get_lk()
    try:
        from livekit import api
        resp = await lk.room.list_participants(api.ListParticipantsRequest(room=room_name))
        participants = getattr(resp, "participants", []) or []
        out = []
        for p in participants:
            out.append(ParticipantSummary(
                identity=getattr(p, "identity", None) or getattr(p, "sid", "") or "",
                sid=getattr(p, "sid", None),
                metadata=getattr(p, "metadata", None),
                state=getattr(p, "state", None),
            ))
        return ListParticipantsResponse(room=room_name, participants=out, total=len(out))
    except Exception as e:
        err = str(e).lower()
        if "not found" in err or "does not exist" in err:
            raise HTTPException(status_code=404, detail=f"Room '{room_name}' not found")
        logger.exception("List participants failed")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await lk.aclose()


# ---------------------------------------------------------------------------
# Destroy room
# ---------------------------------------------------------------------------


class DestroyRoomResponse(BaseModel):
    room: str
    destroyed: bool = True


@router.delete("/{room_name}", response_model=DestroyRoomResponse)
async def destroy_room(
    room_name: str = Path(..., description="LiveKit room name to destroy"),
):
    """Destroy a room (disconnect all participants and end the session)."""
    if room_name in ("summary", ""):
        raise HTTPException(status_code=404, detail="Not found")
    lk = _get_lk()
    try:
        from livekit import api
        await lk.room.delete_room(api.DeleteRoomRequest(room=room_name))
        logger.info("Room destroyed: %s", room_name)
        return DestroyRoomResponse(room=room_name, destroyed=True)
    except Exception as e:
        err = str(e).lower()
        if "not found" in err or "does not exist" in err:
            raise HTTPException(status_code=404, detail=f"Room '{room_name}' not found or already closed")
        logger.exception("Destroy room failed")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await lk.aclose()
