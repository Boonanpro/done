"""Windows のデスクトップアプリの操作を、Mac で動くダンから頼む窓口（この PC の中からだけ）。

ダンの本体を Mac に移した後も、LINE などの Windows のアプリは本人の Windows の PC にある。
Mac のダンの desktop 道具は、この窓口へ依頼を送る（app/services/desktop_control.py の _relay）。
Mac からは、Windows が張る ssh の中継（scripts/voice_relay_to_mac.ps1、-R 19000→9000）を通って
127.0.0.1 から届く。合言葉は両方の機械が持つ APP_SECRET_KEY から作る。
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import sys

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


def relay_token() -> str:
    from app.config import settings
    return hmac.new(settings.APP_SECRET_KEY.encode(), b"dan-desktop-relay", hashlib.sha256).hexdigest()


@router.post("/internal/desktop")
async def desktop(request: Request):
    if (not request.client or request.client.host not in {"127.0.0.1", "::1"}
            or request.headers.get("origin")
            or not hmac.compare_digest(request.headers.get("x-dan-desktop-token", ""), relay_token())):
        raise HTTPException(403, "Local desktop relay authentication required")
    if sys.platform != "win32":
        raise HTTPException(409, "This machine has no Windows desktop")
    params = await request.json()
    from app.services.desktop_control import run
    try:
        return {"result": await run(params)}
    except Exception as exc:  # noqa: BLE001 - the caller reports what failed
        logging.getLogger(__name__).exception("desktop relay failed")
        return {"result": {"success": False, "error": f"Windows の操作で失敗: {exc}"}}
