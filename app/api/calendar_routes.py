"""
Calendar API Routes - connected calendar accounts (any provider, any number per user) and their events.
"""
from fastapi import APIRouter, HTTPException, Depends, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from pydantic import BaseModel

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


class ConnectRequest(BaseModel):
    provider: str = "google"
    replace_id: Optional[str] = None   # this account takes that one's place (its defaults move over)
    hint: Optional[str] = None         # the address to preselect at the provider's sign-in


class AccountRequest(BaseModel):
    account_id: Optional[str] = None


@router.post("/connect")
async def calendar_connect(
    body: Optional[ConnectRequest] = None,
    user: TokenData = Depends(get_current_user),
    service: CalendarService = Depends(get_calendar_service),
):
    """Where to sign in to add (or replace) a calendar account."""
    body = body or ConnectRequest()
    try:
        auth_url = service.get_auth_url(user.user_id, body.provider, body.replace_id, body.hint)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
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
            <h2>カレンダーを連携しました</h2>
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
    body: Optional[AccountRequest] = None,
    user: TokenData = Depends(get_current_user),
    service: CalendarService = Depends(get_calendar_service),
):
    """Remove one account (account_id), or every calendar account."""
    ok = await service.disconnect(user.user_id, (body or AccountRequest()).account_id)
    return {"success": ok}


@router.post("/default")
async def calendar_default(
    body: AccountRequest,
    user: TokenData = Depends(get_current_user),
    service: CalendarService = Depends(get_calendar_service),
):
    """The account new events go to unless another is named."""
    if not body.account_id or not service.set_default(user.user_id, body.account_id):
        raise HTTPException(status_code=404, detail="そのアカウントはありません")
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
