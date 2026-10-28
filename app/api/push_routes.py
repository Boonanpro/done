"""
Push Notification API Routes
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from fastapi.security import HTTPAuthorizationCredentials

from app.config import settings
from app.api.chat_routes import get_current_user, get_optional_user, TokenData
from app.services.push_service import get_push_service

router = APIRouter(prefix="/push", tags=["push"])


class SubscribeRequest(BaseModel):
    room_id: str
    sender_type: str  # 'owner' or 'guest'
    subscription: dict  # PushSubscription JSON
    # 通知タップで開く先。ゲストは本人専用URL（/collab/join/<token>）。
    # 未指定だとオーナー用の /collab/<room> に飛んでログイン画面になる事故が起きる
    landing_url: Optional[str] = None


class NativeSubscribeRequest(BaseModel):
    token: str


@router.get("/vapid-key")
async def get_vapid_key():
    """Return the public VAPID key for push subscription."""
    return {"publicKey": settings.VAPID_PUBLIC_KEY}


async def _subscription_identity(req: SubscribeRequest, request: Request):
    from app.api.collab_routes import _room_access, get_collab_service, decode_access_token, ACCESS_TOKEN_COOKIE
    token = request.headers.get('Authorization', '').removeprefix('Bearer ')
    credentials = HTTPAuthorizationCredentials(scheme='Bearer', credentials=token) if token else None
    if req.room_id.startswith('user:'):
        owner = decode_access_token(request.cookies.get(ACCESS_TOKEN_COOKIE) or token)
        if not owner or req.room_id != f'user:{owner.user_id}' or req.sender_type != 'owner':
            raise HTTPException(status_code=403, detail='Access denied')
        return '/chat'
    service = get_collab_service()
    access = await _room_access(request, credentials, service, req.room_id)
    if access is None or req.sender_type != ('owner' if access[0] else 'guest'):
        raise HTTPException(status_code=403, detail='Access denied')
    if access[0]:
        return f'/collab/{req.room_id}'
    invites = await service.list_invites(req.room_id)
    mine = next((i for i in invites if i['id'] == access[1]), None)
    if not mine:
        raise HTTPException(status_code=403, detail='Identity not found')
    return f"/collab/join/{mine['token']}"


@router.post("/subscribe")
async def subscribe(req: SubscribeRequest, request: Request):
    """Save a push subscription."""
    svc = get_push_service()
    landing = await _subscription_identity(req, request)
    await svc.save_subscription(req.room_id, req.sender_type, req.subscription, landing_url=landing)
    return {"success": True}


@router.post("/native/subscribe")
async def subscribe_native(
    req: NativeSubscribeRequest,
    current_user: TokenData = Depends(get_current_user),
):
    """Save an Expo native push token for the signed-in user."""
    if not req.token.startswith("ExponentPushToken["):
        raise HTTPException(status_code=400, detail="Invalid Expo push token")
    svc = get_push_service()
    await svc.save_subscription(
        room_id=f"user:{current_user.user_id}",
        sender_type="owner",
        subscription={
            "endpoint": req.token,
            "keys": {"p256dh": "", "auth": ""},
        },
    )
    return {"success": True}


class NativeLocationRequest(BaseModel):
    lat: float
    lng: float
    accuracy: Optional[float] = None
    at: Optional[str] = None


@router.post("/native/location")
async def report_native_location(
    req: NativeLocationRequest,
    current_user: TokenData = Depends(get_current_user),
):
    """The phone app reports where the owner is (while the app is open). Only the latest fix is kept."""
    from app.services import user_location
    try:
        record = await user_location.report(current_user.user_id, req.lat, req.lng, req.accuracy, (req.at or "")[:40] or None)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"success": True, "area": record["area"]}


@router.get("/native/location")
async def read_native_location(current_user: TokenData = Depends(get_current_user)):
    from app.services import user_location
    return user_location.current(current_user.user_id) or {}


@router.post("/native/unsubscribe")
async def unsubscribe_native(
    req: NativeSubscribeRequest,
    current_user: TokenData = Depends(get_current_user),
):
    """Remove an Expo native push token for the signed-in user."""
    svc = get_push_service()
    await svc.remove_subscription(
        room_id=f"user:{current_user.user_id}",
        sender_type="owner",
        endpoint=req.token,
    )
    return {"success": True}


@router.post("/unsubscribe")
async def unsubscribe(req: SubscribeRequest, request: Request):
    """Remove a push subscription."""
    await _subscription_identity(req, request)
    svc = get_push_service()
    await svc.remove_subscription(
        req.room_id, req.sender_type, req.subscription.get("endpoint", "")
    )
    return {"success": True}


@router.post("/test")
async def send_test_notification(current_user: TokenData = Depends(get_current_user)):
    """Send a test push notification to the signed-in user's devices."""
    svc = get_push_service()
    result = await svc.notify_room(
        room_id=f"user:{current_user.user_id}",
        exclude_type="ai",
        title="Dan",
        body="通知テストです。Danの作業完了通知を受け取れます。",
        url="/settings",
    )
    if result["sent"] == 0:
        raise HTTPException(
            status_code=503 if result["attempted"] else 404,
            detail={
                "message": "No push notification was delivered",
                **result,
            },
        )
    return {"success": True, **result}


@router.get("/native/app-latest")
async def read_app_latest(v: Optional[str] = None, code: Optional[int] = None, device: Optional[str] = None,
                          user: Optional[TokenData] = Depends(get_optional_user)):
    """The phone app's newest APK (app/services/app_release.py): {"latest": {version_name, version_code, url, size,
    notes, published_at} | null}. The app asks on start and when it comes back to the front, and shows
    「新しい版があります［更新する］」 when the versionCode is newer than its own (mobile/app-update.tsx, 2026-10-24).
    From 1.0.77 the app adds its own version (v, code) and device; it is remembered per phone (app_release.installed)."""
    from app.services import app_release
    if v and code:
        app_release.note_installed(getattr(user, "user_id", None) or "", v, code, device or "")
    return {"latest": app_release.latest()}


@router.get("/native/app-installed")
async def read_app_installed(user: TokenData = Depends(get_current_user)):
    """The versions this user's phones last said they run (newest first)."""
    from app.services import app_release
    return {"installed": app_release.installed(user.user_id), "latest": app_release.latest()}
