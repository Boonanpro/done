# -*- coding: utf-8 -*-
"""Deferred follow-ups (pending_followups).

Shared DB helpers for the `schedule_followup` tool (Dan registers "wake me up
later to report") and the dan-core poller (fires due rows and re-invokes Dan).

Sync functions on purpose — the Supabase client is sync. Async callers can wrap
with `asyncio.to_thread` when they must not block the event loop.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TABLE = "pending_followups"

MIN_DELAY_SECONDS = 15
MAX_DELAY_SECONDS = 6 * 60 * 60       # 6h: a single wait cap
MAX_ACTIVE_PER_ROOM = 12              # rate limit: reschedule loops can't run away


def _sb():
    from app.services.supabase_client import get_supabase_client
    return get_supabase_client().client


def schedule_followup(
    room_id: str,
    note: str,
    delay_seconds: int,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Register a deferred follow-up for `room_id`.

    Returns {"scheduled": bool, "fire_at": iso|None, "message": str}.
    Refuses (scheduled=False) on bad input or when too many follow-ups already
    exist for the room (runaway reschedule guard).
    """
    note = (note or "").strip()
    if not note:
        return {"scheduled": False, "fire_at": None, "message": "note が空です。何を確認して報告するか書いてください。"}
    try:
        delay = int(delay_seconds)
    except (TypeError, ValueError):
        return {"scheduled": False, "fire_at": None, "message": "delay_seconds は整数で指定してください。"}
    delay = max(MIN_DELAY_SECONDS, min(MAX_DELAY_SECONDS, delay))

    sb = _sb()

    # Runaway guard: cap how many live follow-ups a room may have queued.
    try:
        active = (
            sb.table(TABLE).select("id", count="exact")
            .eq("room_id", room_id).in_("status", ["pending", "firing"]).execute()
        )
        if (active.count or 0) >= MAX_ACTIVE_PER_ROOM:
            return {
                "scheduled": False,
                "fire_at": None,
                "message": "この部屋の自動続報が多すぎます。これ以上は予約しません（ユーザーに状況を直接伝えてください）。",
            }
    except Exception as e:
        logger.warning("schedule_followup count failed (continuing): %s", e)

    fire_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
    try:
        sb.table(TABLE).insert({
            "room_id": room_id,
            "user_id": user_id,
            "note": note[:4000],
            "fire_at": fire_at,
            "status": "pending",
        }).execute()
    except Exception as e:
        logger.error("schedule_followup insert failed: %s", e)
        return {"scheduled": False, "fire_at": None, "message": f"続報の予約に失敗しました: {e}"}

    return {
        "scheduled": True,
        "fire_at": fire_at,
        "message": f"{delay}秒後に自動で確認・報告するよう予約しました。",
    }


def claim_due_followups(limit: int = 5) -> List[Dict[str, Any]]:
    """Atomically-ish claim due pending follow-ups: select due rows and flip them
    to 'firing' so a later poll cycle won't double-fire them. Returns the claimed
    rows. (Single-poller design, so a select-then-update race is not a concern.)
    """
    sb = _sb()
    now = datetime.now(timezone.utc).isoformat()
    try:
        due = (
            sb.table(TABLE).select("*")
            .eq("status", "pending").lte("fire_at", now)
            .order("fire_at", desc=False).limit(limit).execute()
        )
    except Exception as e:
        logger.error("claim_due_followups select failed: %s", e)
        return []
    rows = due.data or []
    claimed = []
    for row in rows:
        try:
            sb.table(TABLE).update({
                "status": "firing",
                "attempts": (row.get("attempts") or 0) + 1,
                "updated_at": now,
            }).eq("id", row["id"]).eq("status", "pending").execute()
            claimed.append(row)
        except Exception as e:
            logger.warning("claim_due_followups claim failed for %s: %s", row.get("id"), e)
    return claimed


def mark_status(followup_id: str, status: str) -> None:
    try:
        _sb().table(TABLE).update({
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", followup_id).execute()
    except Exception as e:
        logger.warning("mark_status(%s, %s) failed: %s", followup_id, status, e)


def cancel_pending_for_room(room_id: str) -> int:
    """Cancel a room's outstanding follow-ups. Called when the user sends a new
    message: they're back, so a stale auto-report would be noise/duplicate.
    Returns the number cancelled (best-effort)."""
    try:
        res = (
            _sb().table(TABLE).update({
                "status": "cancelled",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("room_id", room_id).eq("status", "pending").execute()
        )
        return len(res.data or [])
    except Exception as e:
        logger.warning("cancel_pending_for_room(%s) failed: %s", room_id, e)
        return 0
