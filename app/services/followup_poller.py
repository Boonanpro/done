# -*- coding: utf-8 -*-
"""Background poller that delivers deferred follow-ups.

Runs as a single asyncio task inside dan-core. Every POLL_INTERVAL it claims due
rows from pending_followups and, for each, re-invokes the agent for that room so
Dan actually checks the work and POSTS a report to the chat — the thing a
turn-based agent otherwise can't do after its turn ends.

Re-invocation goes through the normal process_message_cli path (NOT skip_save),
resuming the room's session so Dan remembers what it was waiting on.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

POLL_INTERVAL = 20          # seconds between poll cycles
MAX_PER_CYCLE = 5           # cap fires per cycle so one busy cycle can't pile up

_started = False
_task: Optional["asyncio.Task"] = None

_SYNTH_PROMPT = (
    "[システム自動再開 / scheduled follow-up]\n"
    "これはユーザーの新規メッセージではなく、あなた自身が予約した続報の自動トリガーです。\n\n"
    "あなたは少し前に、次のために続報を予約しました:\n"
    "「{note}」\n\n"
    "今、その作業の結果を実際に確認し、ユーザーに日本語でチャット報告してください。\n"
    "- 完了していれば、結果（成否・URL・確認した内容）を簡潔に報告する。\n"
    "- まだ完了していなければ、schedule_followup で短い遅延（60〜120秒）で再予約し、"
    "「まだ処理中です、もう少し待ってください」と一言だけ伝える。\n"
    "余計な前置きや内部思考は出さず、ユーザーへの報告本文だけを書くこと。"
)


def _resolve_project_id(room_id: str) -> Optional[str]:
    try:
        from app.services.supabase_client import get_supabase_client
        r = (
            get_supabase_client().client.table("projects")
            .select("id").eq("room_id", room_id).limit(1).execute()
        )
        return r.data[0]["id"] if r.data else None
    except Exception:
        return None


def _room_busy(room_id: str) -> bool:
    """True if a turn is already running for this room — defer the follow-up so
    we never interleave with the user's live turn."""
    try:
        from app.agent.streaming_session import get_session
        s = get_session(room_id)
        if s and s.is_turn_active():
            return True
    except Exception:
        pass
    try:
        from app.agent.cli_runner import is_cli_active
        if is_cli_active(room_id):
            return True
    except Exception:
        pass
    return False


async def _fire(row: Dict[str, Any]) -> None:
    from app.agent.cli_runner import process_message_cli
    from app.services.followups import mark_status

    room_id = row["room_id"]
    user_id = row.get("user_id") or ""
    note = row.get("note") or ""
    project_id = _resolve_project_id(room_id)
    content = _SYNTH_PROMPT.format(note=note)

    logger.info("[followup] firing for room=%s note=%r", room_id[:8], note[:40])
    try:
        async for _ev in process_message_cli(
            room_id=room_id,
            user_id=user_id,
            content=content,
            project_id=project_id,
            run_id=None,
        ):
            pass  # the sink saves the report; we just drive the turn to completion
        await asyncio.to_thread(mark_status, row["id"], "done")
    except Exception as e:  # noqa: BLE001
        logger.error("[followup] fire failed for room=%s: %s", room_id, e)
        # Mark done rather than risk an endless retry loop on a hard error.
        await asyncio.to_thread(mark_status, row["id"], "done")


async def _tick() -> None:
    from app.services.followups import claim_due_followups, mark_status

    rows = await asyncio.to_thread(claim_due_followups, MAX_PER_CYCLE)
    for row in rows:
        if _room_busy(row["room_id"]):
            # Put it back; retry on a later cycle when the room is idle.
            await asyncio.to_thread(mark_status, row["id"], "pending")
            continue
        await _fire(row)


async def poller_loop() -> None:
    logger.info("[followup] poller started (interval=%ss)", POLL_INTERVAL)
    while True:
        try:
            await _tick()
        except Exception as e:  # noqa: BLE001
            logger.error("[followup] tick error: %s", e)
        await asyncio.sleep(POLL_INTERVAL)


def start_poller() -> Optional["asyncio.Task"]:
    """Start the poller once. Safe to call from a FastAPI lifespan startup."""
    global _started, _task
    if _started:
        return _task
    _started = True
    _task = asyncio.create_task(poller_loop())
    return _task
