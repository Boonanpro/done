# -*- coding: utf-8 -*-
"""「ダン開発の物語」の配信 (D:/dan-archive/story/index.html をダンコア経由で見せる)。

物語そのものはダンの外 (scripts/story_build.py が生成する静的HTML)。ここは
サイドバーから開けるようにするための薄い配信口だけ。
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.chat_routes import get_current_user
from app.services.auth_service import TokenData

router = APIRouter(prefix="/story", tags=["story"])
STORY_DIR = Path(os.environ.get("DAN_ARCHIVE_ROOT") or "D:/dan-archive") / "story"


@router.get("")
@router.get("/")
async def story_index(_: TokenData = Depends(get_current_user)):
    p = STORY_DIR / "index.html"
    if not p.exists():
        raise HTTPException(status_code=404, detail="story not built yet (python scripts/story_build.py)")
    return FileResponse(str(p), media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})
