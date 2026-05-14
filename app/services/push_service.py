"""
Web Push Notification Service
"""
import json
import logging
from typing import Optional
from pywebpush import webpush, WebPushException

from app.config import settings
from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class PushService:
    def __init__(self):
        self.supabase = get_supabase_client().client

    async def save_subscription(self, room_id: str, sender_type: str, subscription: dict):
        """Save a push subscription."""
        endpoint = subscription["endpoint"]
        keys = subscription.get("keys", {})
        data = {
            "room_id": room_id,
            "sender_type": sender_type,
            "endpoint": endpoint,
            "p256dh": keys.get("p256dh", ""),
            "auth": keys.get("auth", ""),
        }
        # Upsert
        self.supabase.table("push_subscriptions").upsert(
            data, on_conflict="room_id,sender_type,endpoint"
        ).execute()

    async def remove_subscription(self, room_id: str, sender_type: str, endpoint: str):
        """Remove a push subscription."""
        self.supabase.table("push_subscriptions").delete().match({
            "room_id": room_id,
            "sender_type": sender_type,
            "endpoint": endpoint,
        }).execute()

    async def notify_room(self, room_id: str, exclude_type: str,
                          title: str, body: str, url: Optional[str] = None) -> dict:
        """Send push notification to all subscribers in a room except the sender's type."""
        if not settings.VAPID_PRIVATE_KEY or not settings.VAPID_PUBLIC_KEY:
            return {"attempted": 0, "sent": 0, "failed": 0}

        result = self.supabase.table("push_subscriptions").select("*").eq(
            "room_id", room_id
        ).neq("sender_type", exclude_type).execute()

        sent = 0
        failed = 0
        for sub in result.data:
            try:
                subscription_info = {
                    "endpoint": sub["endpoint"],
                    "keys": {
                        "p256dh": sub["p256dh"],
                        "auth": sub["auth"],
                    }
                }
                payload = json.dumps({
                    "title": title,
                    "body": body,
                    "url": url or f"/collab/join/{room_id}",
                    "icon": "/icon-192x192.png",
                })
                webpush(
                    subscription_info=subscription_info,
                    data=payload,
                    vapid_private_key=settings.VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": "mailto:dan@done.app"},
                )
                sent += 1
            except WebPushException as e:
                failed += 1
                if e.response and e.response.status_code in (404, 410):
                    # Subscription expired, remove it
                    await self.remove_subscription(room_id, sub["sender_type"], sub["endpoint"])
                    logger.info("Removed expired push subscription: %s", sub["endpoint"][:50])
                else:
                    logger.error("Push failed: %s", e)
            except Exception as e:
                failed += 1
                logger.error("Push error: %s", e)
        return {"attempted": len(result.data), "sent": sent, "failed": failed}


def get_push_service() -> PushService:
    return PushService()
