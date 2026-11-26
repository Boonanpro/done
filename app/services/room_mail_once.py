# -*- coding: utf-8 -*-
"""One mail wakes a room once.

A mail can reach a room by several roads at the same time: the email poller routes a reply to a mail Dan sent
(inbound_wakeup), and every mail watch of the room whose sender matches checks the mailbox on its own
(followup_poller._fire_mail). Each road woke the room with the same mail, and Dan said the same thing two or three
times (2026-11-26: one JLCPCB "case closed" mail woke the pin room at 23:19, 23:21 and 23:28 — the reply routing and
two jlcpcb.com watches; 本人「同じ話を何度もしてるよね」).

claim(room, message_id, by) is the one gate every road passes: the first road takes the mail for the room, the others
see it taken and do not wake. The same road may claim again (a wake that did not land is retried). When a road takes
the mail it carries the notes of every mail watch of the room that waits for that sender (watch_notes), so the one
wake still knows what each watch was for.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

PATH = Path(os.environ.get("DAN_ROOM_MAIL_ONCE", str(Path.home() / ".dan" / "state" / "room_mail_once.json")))
KEEP_SECONDS = 14 * 24 * 3600


def _key(room_id: str, message_id: str) -> str:
    return f"{room_id}|{(message_id or '').strip().lower()}"


def claim(room_id: str, message_id: str, by: str) -> bool:
    """True when this road may wake the room for this mail (first to take it, or the same road again)."""
    if not room_id or not (message_id or "").strip():
        return True   # nothing to tell two roads apart by: never block a wake
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(PATH, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.seek(0)
            try:
                data = json.loads(fh.read() or "{}")
            except ValueError:
                data = {}
            now = time.time()
            data = {k: v for k, v in data.items() if now - float(v.get("at") or 0) < KEEP_SECONDS}
            key = _key(room_id, message_id)
            held = data.get(key)
            if held and held.get("by") != by:
                logger.info("[mail-once] room=%s mail already taken by %s; %s does not wake", room_id[:8], held.get("by"), by)
                return False
            data[key] = {"by": by, "at": now}
            fh.seek(0)
            fh.truncate()
            fh.write(json.dumps(data, ensure_ascii=False))
            return True
    except Exception:  # noqa: BLE001
        logger.exception("[mail-once] ledger unusable; waking anyway")
        return True


def release(room_id: str, message_id: str, by: str) -> None:
    """Give the mail back (the wake that took it did not run), so another road may wake for it."""
    if not room_id or not (message_id or "").strip():
        return
    try:
        with open(PATH, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.seek(0)
            try:
                data = json.loads(fh.read() or "{}")
            except ValueError:
                return
            key = _key(room_id, message_id)
            if (data.get(key) or {}).get("by") == by:
                data.pop(key)
                fh.seek(0)
                fh.truncate()
                fh.write(json.dumps(data, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        logger.exception("[mail-once] release failed")


def sender_matches(want: str, sender: str) -> bool:
    want = (want or "").strip().lower().lstrip("@")
    return bool(want) and want in (sender or "").lower()


def watch_notes(room_id: str, sender: str, subject: str = "", *, skip: str = "") -> List[str]:
    """The notes of the room's active mail watches that wait for this sender (and subject when the watch names one)."""
    try:
        from app.services.followups import TABLE, decode_watch_row
        from app.services.supabase_client import get_supabase_client
        rows = (get_supabase_client().client.table(TABLE).select("*").eq("room_id", room_id)
                .eq("status", "pending").execute().data or [])
    except Exception:  # noqa: BLE001
        return []
    notes = []
    for row in rows:
        if row.get("id") == skip:
            continue
        d: Dict[str, Any] = decode_watch_row(row)
        spec = d.get("spec") or {}
        if d.get("kind") != "mail" or not sender_matches(spec.get("from", ""), sender):
            continue
        if spec.get("subject_contains") and spec["subject_contains"] not in (subject or ""):
            continue
        note = (d.get("plain_note") or "").strip()
        if note and note not in notes:
            notes.append(note)
    return notes


def notes_block(notes: List[str]) -> str:
    if not notes:
        return ""
    return ("このメールを待っている見張り（このメールでは1回だけ起こします。全部を読んで、本人への報告は1つにまとめる。"
            "本人がすることの無い知らせなら、報告は1行にする）:\n"
            + "\n".join(f"・{n}" for n in notes) + "\n")
