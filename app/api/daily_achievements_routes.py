# -*- coding: utf-8 -*-
"""「今日やったこと」API (ダンコア /api/v1/achievements)。"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.chat_routes import get_current_user
from app.services.auth_service import TokenData
from app.services import daily_achievements_service as svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/achievements", tags=["achievements"])


class AchievementPatch(BaseModel):
    status: Optional[str] = None      # done | in_progress | dismissed
    title: Optional[str] = None
    detail: Optional[str] = None
    tags: Optional[List[str]] = None


def _parse_day(day: Optional[str]) -> date:
    if not day:
        return svc.today_jst()
    try:
        return date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=400, detail="day must be YYYY-MM-DD")


@router.get("")
async def list_achievements(day: Optional[str] = None, _: TokenData = Depends(get_current_user)) -> Dict[str, Any]:
    d = _parse_day(day)
    import asyncio
    rows, days, cursor = await asyncio.gather(
        asyncio.to_thread(svc.list_for_day, d),
        asyncio.to_thread(svc.list_days, 30),
        asyncio.to_thread(svc.load_cursor),
    )
    return {
        "day": d.isoformat(),
        "today": svc.today_jst().isoformat(),
        "items": rows,
        "days": days,
        "last_run": cursor.get("last_run"),
    }


@router.get("/status")
async def poller_status(_: TokenData = Depends(get_current_user)) -> Dict[str, Any]:
    from app.services.achievement_poller import status
    return status()


@router.post("/refresh")
async def refresh(_: TokenData = Depends(get_current_user)) -> Dict[str, Any]:
    """今日の証拠を全部読み直して再判定 (判定基準を直した後などに使う)。"""
    from app.services.achievement_poller import run_once
    try:
        return await run_once(force=True)
    except Exception as e:
        logger.exception("achievement refresh failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{row_id}")
async def patch_achievement(row_id: str, body: AchievementPatch, _: TokenData = Depends(get_current_user)) -> Dict[str, Any]:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "status" in patch and patch["status"] not in ("done", "in_progress", "dismissed"):
        raise HTTPException(status_code=400, detail="bad status")
    if not patch:
        raise HTTPException(status_code=400, detail="empty patch")
    import asyncio
    row = await asyncio.to_thread(svc.update_row, row_id, patch)
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    return row


@router.get("/{row_id}/illustration")
async def get_illustration(row_id: str, _: TokenData = Depends(get_current_user)):
    """成果行の挿絵 PNG (無ければ 404)。<img> から Cookie 認証で読む。"""
    import re
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", row_id):
        raise HTTPException(status_code=400, detail="bad id")
    path = svc.illustration_path(row_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="no illustration")
    return FileResponse(str(path), media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/{row_id}/illustration")
async def make_illustration(row_id: str, force: bool = False, _: TokenData = Depends(get_current_user)) -> Dict[str, Any]:
    """挿絵を今すぐ生成 (force=true で作り直し)。"""
    import asyncio
    ok = await asyncio.to_thread(svc.generate_illustration, row_id, force)
    if not ok:
        raise HTTPException(status_code=500, detail="illustration failed")
    row = await asyncio.to_thread(svc.get_row, row_id)
    return row or {"ok": True}
