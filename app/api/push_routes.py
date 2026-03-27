"""
Push Notification API Routes
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Optional

from app.config import settings
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
