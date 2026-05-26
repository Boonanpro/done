# -*- coding: utf-8 -*-
"""Verify the deferred follow-up poller against the real pending_followups table
(process_message_cli is mocked so no real agent turn runs).

  (1) a DUE row -> poller fires (re-invokes the agent for that room) and marks
      the row 'done'.
  (2) when the room is busy -> poller defers (no fire) and leaves it 'pending'.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "D:/done")

from app.services.supabase_client import get_supabase_client  # noqa: E402
import app.agent.cli_runner as cli_runner  # noqa: E402
import app.services.followup_poller as poller  # noqa: E402

sb = get_supabase_client().client
ROOM = "test-poller-room-xyz"


def _cleanup():
    sb.table("pending_followups").delete().eq("room_id", ROOM).execute()


def _insert_due():
    past = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    sb.table("pending_followups").insert({
        "room_id": ROOM, "user_id": "u1", "note": "デプロイ完了を確認して報告",
        "fire_at": past, "status": "pending",
    }).execute()


def _status():
    r = sb.table("pending_followups").select("status").eq("room_id", ROOM).execute()
    return [x["status"] for x in (r.data or [])]


def main() -> int:
    fails = []
    _cleanup()

    calls = []

    async def fake_pmc(room_id, user_id, content, project_id=None, run_id=None, **kw):
        calls.append({"room_id": room_id, "content": content[:40]})
        yield {"type": "result", "text": "報告: 完了しました"}

    cli_runner.process_message_cli = fake_pmc

    # (1) DUE row, room idle -> fires + done
    _insert_due()
    poller._room_busy = lambda r: False
    asyncio.run(poller._tick())
    print(f"[fire] calls={len(calls)} status={_status()}")
    if len(calls) != 1 or calls[0]["room_id"] != ROOM:
        fails.append("due follow-up did not fire process_message_cli for the room")
    if _status() != ["done"]:
        fails.append(f"fired row not marked done (status={_status()})")

    # (2) DUE row, room busy -> deferred, no fire, stays pending
    _cleanup()
    calls.clear()
    _insert_due()
    poller._room_busy = lambda r: True
    asyncio.run(poller._tick())
    print(f"[busy] calls={len(calls)} status={_status()}")
    if calls:
        fails.append("fired while room was busy (should defer)")
    if _status() != ["pending"]:
        fails.append(f"busy row not left pending (status={_status()})")

    _cleanup()

    if fails:
        print("\n=== FAIL ===")
        for x in fails:
            print("  -", x)
        return 1
    print("\n=== PASS: due follow-ups fire + mark done; busy rooms defer ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
