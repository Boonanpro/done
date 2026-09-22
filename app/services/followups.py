# -*- coding: utf-8 -*-
"""Watches — Dan's single notebook for future promises (pending_followups).

One table backs three kinds of standing instructions:
  - "at":    one-shot wake at a moment ("30分後に確認", "明日10時に確認")
  - "every": recurring wake ("毎朝9時に〜をチェック")
  - "mail":  wake when matching mail arrives ("税理士からメールが来たら")

Storage note: the live table has no kind/spec columns and DDL is currently
blocked (GitHub suspension took out both the Supabase PAT and OAuth re-login),
so kind/spec ride inside the `note` TEXT column as a JSON envelope
({"w":1, kind, note, spec}). Plain-text notes are legacy "at" rows. When DDL
is possible again, promote kind/spec/fire_count to real columns and drop the
envelope — decode_watch_row() is the only place that knows the format.

`fire_at` means "next due time" for every kind: for "at" it's the wake moment,
for "every" the next tick, for "mail" the next inbox check.

Sync functions on purpose — the Supabase client is sync. Async callers can wrap
with `asyncio.to_thread` when they must not block the event loop.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

TABLE = "pending_followups"

MIN_DELAY_SECONDS = 15
MAX_ACTIVE_PER_ROOM = 100             # runaway-loop guard only; normal use should never hit this
MIN_EVERY_INTERVAL = 300              # recurring watches: 5min floor
MIN_MAIL_INTERVAL = 300               # mail checks: 5min floor
DEFAULT_MAIL_INTERVAL = 600           # mail checks: 10min default

_ENVELOPE_KEY = "w"


def encode_watch_note(kind: str, note: str, spec: Dict[str, Any]) -> str:
    return json.dumps(
        {_ENVELOPE_KEY: 1, "kind": kind, "note": note, "spec": spec or {}},
        ensure_ascii=False,
    )


def decode_watch_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Return row + {kind, plain_note, spec} decoded from the note envelope.
    Legacy plain-text notes are one-shot 'at' watches."""
    raw = row.get("note") or ""
    kind, plain, spec = "at", raw, {}
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and data.get(_ENVELOPE_KEY) == 1:
                kind = data.get("kind") or "at"
                plain = data.get("note") or ""
                spec = data.get("spec") or {}
        except (json.JSONDecodeError, TypeError):
            pass
    out = dict(row)
    out["kind"] = kind
    out["plain_note"] = plain
    out["spec"] = spec
    return out


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
    # No upper clamp: "明日の10時" must actually mean tomorrow at 10. (The old
    # 6h cap silently truncated long waits while reporting success — Dan then
    # honestly believed a promise the system had already broken.)
    delay = max(MIN_DELAY_SECONDS, delay)

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


_VALID_KINDS = ("at", "every", "mail", "handoff")

JST = timezone(timedelta(hours=9))


def next_calendar_fire(spec: Dict[str, Any], after: Optional[datetime] = None) -> Optional[datetime]:
    """Next occurrence (UTC) for calendar-style 'every' watches, computed in JST.

    spec keys: monthly_day (1-31; clamped to month length, so 31 = end of month)
    or weekly_day (0=月 .. 6=日), plus optional time_of_day "HH:MM" (default 09:00).
    Returns None if the spec has no calendar fields (plain interval watch).
    """
    monthly = spec.get("monthly_day")
    weekly = spec.get("weekly_day")
    if monthly is None and weekly is None:
        return None
    after = after or datetime.now(timezone.utc)
    local = after.astimezone(JST)
    hh, mm = 9, 0
    t = str(spec.get("time_of_day") or "").strip()
    if t:
        try:
            hh, mm = int(t.split(":")[0]), int(t.split(":")[1])
        except (ValueError, IndexError):
            pass
    if monthly is not None:
        import calendar as _cal
        day = int(monthly)
        for add_months in range(0, 3):
            y = local.year + (local.month - 1 + add_months) // 12
            mo = (local.month - 1 + add_months) % 12 + 1
            d = min(day, _cal.monthrange(y, mo)[1])
            cand = datetime(y, mo, d, hh, mm, tzinfo=JST)
            if cand > local:
                return cand.astimezone(timezone.utc)
    else:
        wd = int(weekly)
        for add in range(0, 8):
            cd = local.date() + timedelta(days=add)
            if cd.weekday() == wd:
                cand = datetime(cd.year, cd.month, cd.day, hh, mm, tzinfo=JST)
                if cand > local:
                    return cand.astimezone(timezone.utc)
    return None


def create_watch(
    room_id: str,
    user_id: Optional[str],
    kind: str,
    note: str,
    *,
    fire_at: Optional[datetime] = None,
    delay_seconds: Optional[int] = None,
    spec: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Register a watch (standing instruction) for `room_id`.

    Returns {"scheduled": bool, "id": str|None, "fire_at": iso|None, "message": str}.
    """
    note = (note or "").strip()
    if not note:
        return {"scheduled": False, "id": None, "fire_at": None,
                "message": "note が空です。何を見張って何を報告するか書いてください。"}
    if kind not in _VALID_KINDS:
        return {"scheduled": False, "id": None, "fire_at": None,
                "message": f"kind は {_VALID_KINDS} のいずれかです。"}

    spec = dict(spec or {})
    now = datetime.now(timezone.utc)

    if kind == "every":
        cal_first = next_calendar_fire(spec, now)
        if cal_first is not None:
            # Calendar mode: 毎月N日 / 毎週X曜 (JST). interval_seconds not needed.
            first = fire_at or cal_first
        else:
            try:
                interval = max(MIN_EVERY_INTERVAL, int(spec.get("interval_seconds") or 0))
            except (TypeError, ValueError):
                return {"scheduled": False, "id": None, "fire_at": None,
                        "message": "every には interval_seconds（秒、300以上）か monthly_day/weekly_day が必要です。"}
            if not spec.get("interval_seconds"):
                return {"scheduled": False, "id": None, "fire_at": None,
                        "message": "every には interval_seconds（秒、300以上）か monthly_day/weekly_day が必要です。"}
            spec["interval_seconds"] = interval
            first = fire_at or (now + timedelta(seconds=interval))
    elif kind == "mail":
        if not (spec.get("from") or "").strip():
            return {"scheduled": False, "id": None, "fire_at": None,
                    "message": "mail には from（差出人アドレスまたはドメイン）が必要です。"}
        spec["mailbox"] = spec.get("mailbox") or "icloud"
        try:
            spec["interval_seconds"] = max(
                MIN_MAIL_INTERVAL, int(spec.get("interval_seconds") or DEFAULT_MAIL_INTERVAL))
        except (TypeError, ValueError):
            spec["interval_seconds"] = DEFAULT_MAIL_INTERVAL
        # First check runs soon; it baselines last_uid without waking anyone.
        first = now + timedelta(seconds=MIN_DELAY_SECONDS)
    elif kind == "handoff":
        # 「この話は新しいチャットで」の引き継ぎ。新ルームでダンが一言目を話す
        # ためのワンショット起動。待つ理由が無いので次のポーラー周期で即発火。
        first = now
    else:  # at
        if fire_at is None:
            try:
                delay = max(MIN_DELAY_SECONDS, int(delay_seconds))
            except (TypeError, ValueError):
                return {"scheduled": False, "id": None, "fire_at": None,
                        "message": "at には fire_at（日時）か delay_seconds（秒）が必要です。"}
            fire_at = now + timedelta(seconds=delay)
        if fire_at <= now:
            return {"scheduled": False, "id": None, "fire_at": None,
                    "message": "fire_at が過去です。未来の日時を指定してください。"}
        first = fire_at

    sb = _sb()
    # Runaway guard (shared with schedule_followup).
    try:
        active = (
            sb.table(TABLE).select("id", count="exact")
            .eq("room_id", room_id).in_("status", ["pending", "firing"]).execute()
        )
        if (active.count or 0) >= MAX_ACTIVE_PER_ROOM:
            return {"scheduled": False, "id": None, "fire_at": None,
                    "message": "この部屋の見張り・予約が多すぎます。watch(action=\"list\") で確認し、不要なものを cancel してください。"}
    except Exception as e:
        logger.warning("create_watch count failed (continuing): %s", e)

    payload = {
        "room_id": room_id,
        "user_id": user_id,
        "note": encode_watch_note(kind, note[:3000], spec),
        "fire_at": first.isoformat(),
        "status": "pending",
    }
    try:
        res = sb.table(TABLE).insert(payload).execute()
        watch_id = (res.data or [{}])[0].get("id")
    except Exception as e:
        logger.error("create_watch insert failed: %s", e)
        return {"scheduled": False, "id": None, "fire_at": None,
                "message": f"見張りの登録に失敗しました: {e}"}

    label = {"at": "予約", "every": "定期見張り", "mail": "メール見張り", "handoff": "引き継ぎ起動"}[kind]
    return {"scheduled": True, "id": watch_id, "fire_at": first.isoformat(),
            "message": f"{label}を登録しました（id={watch_id}, 次回={first.isoformat()}）。"}


def list_watches(room_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Active (pending/firing) watches, decoded. All rooms when room_id is None."""
    try:
        q = _sb().table(TABLE).select("*").in_("status", ["pending", "firing"])
        if room_id:
            q = q.eq("room_id", room_id)
        res = q.order("fire_at", desc=False).limit(200).execute()
    except Exception as e:
        logger.error("list_watches failed: %s", e)
        return []
    return [decode_watch_row(r) for r in (res.data or [])]


def cancel_watch(watch_id: str, room_id: Optional[str] = None) -> bool:
    try:
        q = (
            _sb().table(TABLE).update({
                "status": "cancelled",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", watch_id).in_("status", ["pending", "firing"])
        )
        if room_id:
            q = q.eq("room_id", room_id)
        res = q.execute()
        return bool(res.data)
    except Exception as e:
        logger.warning("cancel_watch(%s) failed: %s", watch_id, e)
        return False


def reschedule_watch(
    row_id: str,
    kind: str,
    note: str,
    spec: Dict[str, Any],
    next_fire_at: datetime,
) -> None:
    """Advance a recurring watch (every/mail) to its next due time, persisting
    updated spec (last_uid, fire_count, ...) back into the note envelope."""
    try:
        _sb().table(TABLE).update({
            "note": encode_watch_note(kind, note, spec),
            "fire_at": next_fire_at.isoformat(),
            "status": "pending",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", row_id).execute()
    except Exception as e:
        logger.error("reschedule_watch(%s) failed: %s", row_id, e)


def held_room_ids(*, strict: bool = False) -> List[str]:
    """Rooms whose browser must NOT be idle-reaped: an active one-shot wait
    ('at') or any watch that explicitly asked to hold the browser open."""
    try:
        res = (
            _sb().table(TABLE).select("room_id, note")
            .in_("status", ["pending", "firing"]).limit(500).execute()
        )
    except Exception as e:
        logger.warning("held_room_ids failed: %s", e)
        if strict:
            raise
        return []
    out = set()
    for row in res.data or []:
        d = decode_watch_row(row)
        if d["kind"] == "at" or d["spec"].get("hold_browser"):
            if row.get("room_id"):
                out.add(row["room_id"])
    return sorted(out)


def claim_due_followups(limit: int = 5) -> List[Dict[str, Any]]:
    """Atomically-ish claim due pending follow-ups: select due rows and flip them
    to 'firing' so a later poll cycle won't double-fire them. Returns the claimed
    rows. (Single-poller design, so a select-then-update race is not a concern.)
    """
    sb = _sb()
    now = datetime.now(timezone.utc).isoformat()

    # Crash recovery: a row stays 'firing' forever if the core died mid-fire
    # (observed: a July row stuck 32 days, permanently blocking quiet checks).
    # Reclaim rows that have been 'firing' for over 30 minutes as due again.
    try:
        stale_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        stuck = (
            sb.table(TABLE).select("id")
            .eq("status", "firing").lt("updated_at", stale_cutoff)
            .limit(10).execute()
        )
        for row in stuck.data or []:
            sb.table(TABLE).update({
                "status": "pending", "updated_at": now,
            }).eq("id", row["id"]).eq("status", "firing").execute()
            logger.warning("claim_due_followups: recovered stuck firing row %s", row["id"])
    except Exception as e:
        logger.warning("claim_due_followups stuck-recovery failed (continuing): %s", e)

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
            result = sb.table(TABLE).update({
                "status": "firing",
                "attempts": (row.get("attempts") or 0) + 1,
                "updated_at": now,
            }).eq("id", row["id"]).eq("status", "pending").execute()
            if result.data:
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
        rows = _sb().table(TABLE).select('*').eq('room_id', room_id).eq('status', 'pending').execute().data or []
        ids = [r['id'] for r in rows if not decode_watch_row(r)['spec'].get('command_center')]
        if not ids:
            return 0
        res = _sb().table(TABLE).update({'status': 'cancelled', 'updated_at': datetime.now(timezone.utc).isoformat()}).in_('id', ids).eq('status', 'pending').execute()
        return len(res.data or [])
    except Exception as e:
        logger.warning("cancel_pending_for_room(%s) failed: %s", room_id, e)
        return 0
