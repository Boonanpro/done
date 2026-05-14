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
        body="通知テストです。Dan の作業完了通知を受け取れます。",
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
