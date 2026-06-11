# -*- coding: utf-8 -*-
"""コア起動時の孤児 run 復旧。

コア（と execution_events を書く CLI sink スレッド）が突然死ぬと、実行中だった
run が 'running' のまま取り残され、そのターンの回答 ai_message は保存されない。
フロント（PC/モバイル）はライブのプロセス表示を「state=running の run」からしか
組み立てないため、次にコアが起き上がった瞬間、ダンの作業内容が画面から丸ごと
消える（2026-06-11: ダンが自分の残骸 python を taskkill してコアを巻き込み死、
11分の作業表示が消失した実例）。

起動時に取り残された run を failed にし、execution_events から途中経過を
ai_message として保存して、作業を可視のまま残す。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# コア起動の直後に正規の run が走り始めるレースを避けるための猶予。
# 旧コアの死から watchdog 再起動まで最短でも数秒あるので、これより新しい
# running run は「いま生きている」可能性があるとみなして触らない。
GRACE_SECONDS = 30

# 復旧メッセージに残す直近ステップ数（長大 run の全イベントを吹き出しに
# 詰めると重いので末尾だけ。全文は execution_events に残っている）。
MAX_BLOCKS = 80

# これより古い孤児 run は「中断されました」メッセージを保存しない（昔の部屋に
# 今さら通知が湧くのはノイズ）。state だけ黙って failed に直す。
MESSAGE_MAX_AGE_HOURS = 24


def _event_to_block(event: dict) -> dict | None:
    """execution_event を ai_context.blocks の1要素へ（フロントの eventToStep と同形）。"""
    etype = event.get("event_type")
    if etype in ("done", "phase"):
        return None
    if etype == "tool_use":
        return {"type": "tool", "label": event.get("tool_label") or event.get("tool_name") or "ツール実行"}
    if etype == "error":
        return {"type": "error", "text": event.get("content") or "エラー"}
    return {"type": "text", "text": event.get("content") or str(etype)}


def recover_orphaned_runs_sync() -> int:
    """state=running のまま取り残された run を failed にし、途中経過を保存する。

    Returns: 復旧した run の数。
    """
    from app.services.supabase_client import get_supabase_client

    sb = get_supabase_client().client
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=GRACE_SECONDS)).isoformat()
    runs = (
        sb.table("agent_runs")
        .select("id,room_id,project_id,state,created_at,updated_at")
        .eq("state", "running")
        .lt("created_at", cutoff)
        .execute()
    )
    message_cutoff = datetime.now(timezone.utc) - timedelta(hours=MESSAGE_MAX_AGE_HOURS)
    recovered = 0
    for run in runs.data or []:
        run_id = run["id"]
        room_id = run.get("room_id")
        try:
            created_raw = (run.get("created_at") or "").replace("Z", "+00:00")
            try:
                run_created = datetime.fromisoformat(created_raw)
            except ValueError:
                run_created = message_cutoff  # パース不能なら古い扱い（黙ってfailedのみ）
            save_message = run_created > message_cutoff
            events = (
                sb.table("execution_events")
                .select("event_type,tool_name,tool_label,content,turn_id,seq,created_at")
                .eq("run_id", run_id)
                .order("seq", desc=False)
                .order("created_at", desc=False)
                .execute()
            ).data or []

            blocks = [b for b in (_event_to_block(e) for e in events) if b]
            truncated = len(blocks) > MAX_BLOCKS
            if truncated:
                blocks = blocks[-MAX_BLOCKS:]
            last_turn_id = next(
                (e.get("turn_id") for e in reversed(events) if e.get("turn_id")), None
            )

            content = (
                "（サーバーの再起動により、この作業は途中で中断されました。"
                "途中までの作業ログを残しています。続きが必要なら「続けて」と送ってください）"
            )
            if truncated:
                content += f"\n（ログが長いため直近{MAX_BLOCKS}ステップのみ表示）"

            if room_id and save_message:
                from app.agent.cli_runner import _save_ai_message_sync

                _save_ai_message_sync(
                    room_id,
                    content,
                    blocks=blocks or None,
                    turn_id=last_turn_id,
                )
            sb.table("agent_runs").update({"state": "failed"}).eq("id", run_id).eq(
                "state", "running"
            ).execute()
            recovered += 1
            logger.info(
                "[run-recovery] orphaned run %s (room=%s) -> failed, %s",
                run_id[:8], (room_id or "?")[:8],
                f"message saved ({len(blocks)} blocks)" if (room_id and save_message)
                else "no message (run too old)",
            )
        except Exception as e:
            logger.warning("[run-recovery] failed to recover run %s: %s", run_id[:8], e)
    return recovered


async def recover_orphaned_runs() -> None:
    """起動時に裏で実行する非同期ラッパー。失敗してもコア起動は妨げない。"""
    try:
        count = await asyncio.to_thread(recover_orphaned_runs_sync)
        if count:
            logger.info("[run-recovery] recovered %d orphaned run(s)", count)
    except Exception as e:
        logger.warning("[run-recovery] startup recovery failed: %s", e)
