"""
Google Calendar API Routes - OAuth連携 + 予定CRUD
"""
from fastapi import APIRouter, HTTPException, Depends, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional

from app.services.auth_service import decode_access_token, TokenData
from app.services.calendar_service import get_calendar_service, CalendarService

router = APIRouter(prefix="/calendar", tags=["calendar"])
security = HTTPBearer(auto_error=False)

ACCESS_TOKEN_COOKIE = "done_access_token"


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> TokenData:
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token and credentials:
        token = credentials.credentials
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token_data = decode_access_token(token)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return token_data


@router.post("/connect")
async def calendar_connect(
    user: TokenData = Depends(get_current_user),
    service: CalendarService = Depends(get_calendar_service),
):
    """OAuth認証URLを返す"""
    auth_url = service.get_auth_url(user.user_id)
    return {"auth_url": auth_url}


@router.get("/callback")
async def calendar_callback(
    code: str = Query(...),
    state: str = Query(...),
    service: CalendarService = Depends(get_calendar_service),
):
    """GoogleからのOAuthコールバック"""
    success, message, email = await service.handle_callback(code, state)
    if success:
        return HTMLResponse(content=f"""
        <html><body style="background:#0a0a0a;color:#fff;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
        <div style="text-align:center">
            <h2>Googleカレンダー連携完了</h2>
            <p>{email}</p>
            <p style="color:#888">このウィンドウを閉じてください</p>
        </div>
        </body></html>
        """)
    raise HTTPException(status_code=400, detail=message)


@router.get("/status")
async def calendar_status(
    user: TokenData = Depends(get_current_user),
    service: CalendarService = Depends(get_calendar_service),
):
    """連携状態を確認"""
    return await service.get_status(user.user_id)


@router.post("/disconnect")
async def calendar_disconnect(
    user: TokenData = Depends(get_current_user),
    service: CalendarService = Depends(get_calendar_service),
):
    """連携解除"""
    await service.disconnect(user.user_id)
    return {"success": True}


@router.get("/events")
async def get_events(
    days: int = Query(default=7, ge=1, le=30),
    user: TokenData = Depends(get_current_user),
    service: CalendarService = Depends(get_calendar_service),
):
    """予定一覧取得"""
    events = service.get_events(user.user_id, days=days)
    return {"events": events}


@router.get("/free-slots")
async def get_free_slots(
    days: int = Query(default=7, ge=1, le=14),
    user: TokenData = Depends(get_current_user),
    service: CalendarService = Depends(get_calendar_service),
):
    """空き時間取得"""
    slots = service.find_free_slots(user.user_id, days=days)
    return {"slots": slots}
