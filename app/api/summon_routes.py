"""Dan's call for the owner (app/services/owner_summon.py): the phone app answers it, the dashboard shows it."""
import asyncio

from fastapi import APIRouter, Depends

from app.api.chat_routes import get_current_user, TokenData
from app.services import owner_summon

router = APIRouter(prefix="/summon", tags=["summon"])


@router.get("/active")
async def active(current_user: TokenData = Depends(get_current_user)):
    """Open summonses of the signed-in owner (the dashboard rings while there is one)."""
    rows = await asyncio.to_thread(owner_summon.live, current_user.user_id)
    return {"summons": [{"id": s["id"], "room_id": s["room_id"], "project_id": s.get("project_id"), "title": s.get("title"),
                         "reason": s["reason"], "state": s["state"], "deadline": s["deadline"]} for s in rows]}


@router.post("/{summon_id}/answer")
async def answer(summon_id: str, current_user: TokenData = Depends(get_current_user)):
    """The owner reacted (tapped the notification, pressed the banner): the ringing stops."""
    s = await asyncio.to_thread(owner_summon.read, summon_id)
    if not s or s.get("user_id") != current_user.user_id:
        return {"success": False}
    await asyncio.to_thread(owner_summon.answer, summon_id, "tap")
    return {"success": True}
