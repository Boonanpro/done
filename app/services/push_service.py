"""
Web Push Notification Service
"""
import json
import logging
import urllib.request
from typing import Optional
from pywebpush import webpush, WebPushException

from app.config import settings
from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class PushService:
    def __init__(self):
        self.supabase = get_supabase_client().client

    async def save_subscription(self, room_id: str, sender_type: str, subscription: dict,
                                landing_url: Optional[str] = None, sender_id: Optional[str] = None):
        """Save a push subscription. landing_url=通知タップで開くURL（ゲストは本人専用URL）

        sender_id=購読者の身元（ゲストは本人の招待ID）。同じ部屋の別のゲストの発言を
        その人に届け、本人の発言だけを除くために使う。"""
        endpoint = subscription["endpoint"]
        keys = subscription.get("keys", {})
        data = {
            "room_id": room_id,
            "sender_type": sender_type,
            "endpoint": endpoint,
            "p256dh": keys.get("p256dh", ""),
            "auth": keys.get("auth", ""),
        }
        if landing_url:
            data["landing_url"] = landing_url
        if sender_id:
            data["sender_id"] = sender_id
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

    @staticmethod
    def _is_sender(sub: dict, exclude_type: str, exclude_sender_id: Optional[str]) -> bool:
        """その購読が発言者本人のものか。

        身元つきの購読（sender_id）は身元で比べるので、同じ種類（ゲスト同士）でも
        別人には届く。身元の無い古い購読は従来どおり種類で比べる。"""
        if exclude_sender_id and sub.get("sender_id"):
            return sub["sender_id"] == exclude_sender_id
        return sub.get("sender_type") == exclude_type

    async def notify_room(self, room_id: str, exclude_type: str,
                          title: str, body: str, url: Optional[str] = None,
                          data: Optional[dict] = None, channel_id: Optional[str] = None,
                          sound: Optional[str] = None,
                          exclude_sender_id: Optional[str] = None) -> dict:
        """Send push notification to all subscribers in a room except the sender.

        exclude_sender_id を渡すと発言者本人だけを除く（同じ種類の他の参加者には届く）。
        無ければ従来どおり発言者の種類ごと除く。
        data / channel_id / sound: extra payload for the phone app (owner_summon rings on its own channel)."""
        result = self.supabase.table("push_subscriptions").select("*").eq(
            "room_id", room_id
        ).execute()
        targets = [sub for sub in (result.data or [])
                   if not self._is_sender(sub, exclude_type, exclude_sender_id)]

        sent = 0
        failed = 0
        for sub in targets:
            if str(sub.get("endpoint", "")).startswith("ExponentPushToken["):
                ok = await self._send_expo_push(
                    token=sub["endpoint"],
                    title=title,
                    body=body,
                    url=url or "/chat",
                    data=data,
                    channel_id=channel_id,
                    sound=sound,
                )
                if ok:
                    sent += 1
                else:
                    failed += 1
                continue

            if not settings.VAPID_PRIVATE_KEY or not settings.VAPID_PUBLIC_KEY:
                failed += 1
                continue

            try:
                subscription_info = {
                    "endpoint": sub["endpoint"],
                    "keys": {
                        "p256dh": sub["p256dh"],
                        "auth": sub["auth"],
                    }
                }
                # 購読側が着地URLを持っていればそれを優先（ゲスト=本人専用URL。
                # 部屋URL /collab/<room> はオーナー専用でゲストが開くとログイン画面になる）
                payload = json.dumps({
                    "title": title,
                    "body": body,
                    "url": sub.get("landing_url") or url or "/collab",
                    "icon": "/icon-192x192.png",
                    **({"data": data} if data else {}),
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
        return {"attempted": len(targets), "sent": sent, "failed": failed}

    async def _send_expo_push(self, token: str, title: str, body: str, url: str, data: Optional[dict] = None,
                              channel_id: Optional[str] = None, sound: Optional[str] = None) -> bool:
        """Send a native Expo push notification."""
        payload = json.dumps({
            "to": token,
            "title": title,
            "body": body,
            "sound": sound or "default",
            "priority": "high",
            "channelId": channel_id or "default",
            "data": {**(data or {}), "url": url},
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://exp.host/--/api/v2/push/send",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
                text = resp.read().decode("utf-8", errors="replace")
            if 200 <= status < 300:
                data = json.loads(text)
                ticket = data.get("data", {})
                if ticket.get("status") == "ok":
                    return True
                logger.warning("Expo push ticket failed: %s", ticket)
            else:
                logger.warning("Expo push HTTP %s: %s", status, text[:200])
        except Exception as e:
            logger.error("Expo push error: %s", e)
        return False


def get_push_service() -> PushService:
    return PushService()
