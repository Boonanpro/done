# -*- coding: utf-8 -*-
"""Reproduce + verify the double-save fix: two CONCURRENT _process_via_streaming_session
calls on the same room (simulates a follow-up request that raced is_turn_active and
fell through to a fresh process_message_cli). With run_turn serialized, the 2nd call
must be routed as a follow-up (no parallel loop), so the answer is NOT saved twice.
"""
import asyncio
import json
import os
import sys
import tempfile
import threading

os.environ["DAN_STREAMING_INPUT"] = "1"
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

from app.agent import cli_runner  # noqa: E402
from app.agent.streaming_session import get_session  # noqa: E402

saves = []


def rec_save(room_id, content, reasoning_steps=None, reasoning_full=None, blocks=None, created_at=None):
    saves.append((content or "")[:40])
    print(f"[SAVE] tid={threading.get_ident()} created_at={created_at} content={(content or '')[:40]!r}", flush=True)
    return True


cli_runner._save_ai_message_sync = rec_save


def mcp():
    fd, p = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"mcpServers": {}}, f)
    return p


async def consume(room, content, tag, events):
    async for ev in cli_runner._process_via_streaming_session(
        room_id=room, user_id="t", content=content,
        system_prompt="あなたはテスト用。指示に厳密に従う。", mcp_config_path=mcp(),
        project_id=None, run_id=None, skip_save=False, cwd=PROJ,
    ):
        events.append((tag, ev.get("type")))


async def main() -> int:
    room = "concurrent-test"
    evA = []
    taskA = asyncio.create_task(consume(
        room,
        "次の3ステップを必ず1つずつ順に。各ステップで bash を1回だけ使い1行報告してから次へ:\n(1) `echo S1` (2) `echo S2` (3) `echo S3`",
        "A", evA,
    ))

    # When A has run its first tool, fire a CONCURRENT second call (the race).
    started_B = [False]
    evB = []
    taskB = None
    for _ in range(160):
        await asyncio.sleep(0.5)
        if not started_B[0] and any(t == "tool_use" for _, t in evA):
            s = get_session(room)
            print(f"[concurrent fire] is_turn_active={s.is_turn_active() if s else None}", flush=True)
            taskB = asyncio.create_task(consume(
                room, "残りは中止して。今すぐ 'CONCURRENT-OK' とだけ返答して終了して。", "B", evB,
            ))
            started_B[0] = True
        if taskA.done() and (taskB is None or taskB.done()):
            break
    await taskA
    if taskB:
        await taskB

    print(f"\n=== SAVES ({len(saves)}) ===", flush=True)
    for s in saves:
        print(f"  {s!r}", flush=True)
    dupes = {x for x in saves if saves.count(x) > 1 and x.strip()}
    ok_followup = any("CONCURRENT-OK" in s for s in saves)
    if dupes:
        print(f"\n=== FAIL: duplicate save: {dupes} ===", flush=True)
        return 1
    if not ok_followup:
        print("\n=== WARN: follow-up (CONCURRENT-OK) not seen in saves ===", flush=True)
    print("\n=== CONCURRENT TEST PASS: no duplicate save ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
