"""
Push Notification API Routes
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from app.config import settings
from app.api.chat_routes import get_current_user, TokenData
from app.services.push_service import get_push_service

router = APIRouter(prefix="/push", tags=["push"])


class SubscribeRequest(BaseModel):
    room_id: str
    sender_type: str  # 'owner' or 'guest'
    subscription: dict  # PushSubscription JSON


class NativeSubscribeRequest(BaseModel):
    token: str


@router.get("/vapid-key")
async def get_vapid_key():
    """Return the public VAPID key for push subscription."""
    return {"publicKey": settings.VAPID_PUBLIC_KEY}


@router.post("/subscribe")
async def subscribe(req: SubscribeRequest):
    """Save a push subscription."""
    svc = get_push_service()
    await svc.save_subscription(req.room_id, req.sender_type, req.subscription)
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
async def unsubscribe(req: SubscribeRequest):
    """Remove a push subscription."""
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
