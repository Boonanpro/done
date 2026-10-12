"""Lifelog upload and lookup (see app/services/lifelog.py)."""
import asyncio

from fastapi import APIRouter, HTTPException, Request

from app.api.voicelog_routes import _get_user
from app.services import lifelog

router = APIRouter(prefix="/lifelog", tags=["lifelog"])


@router.post("/segment")
async def upload_segment(request: Request):
    """One speech segment from the phone (body: a DPO1 file). Kept on the NAS; the worker writes it down."""
    user = _get_user(request)
    data = await request.body()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(413, "segment too large")
    try:
        return await asyncio.to_thread(lifelog.store_segment, user.user_id, data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/recent")
async def recent(request: Request, minutes: float = 10):
    _get_user(request)
    rows = await asyncio.to_thread(lifelog.recent, minutes)
    return {"rows": rows, "text": lifelog.as_text(rows)}


@router.get("/search")
async def search(request: Request, q: str = "", days: int = 7, date: str | None = None):
    _get_user(request)
    rows = await asyncio.to_thread(lifelog.search, q, days, 30, date)
    return {"rows": rows}
