# -*- coding: utf-8 -*-
"""Trace: reproduce the interrupt->continuation scenario and count how many
times the ai_message is saved (and from which thread / with which created_at),
to pinpoint the double-save seen in the live test (turn-2 saved twice)."""
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

calls = []


def rec_save(room_id, content, reasoning_steps=None, reasoning_full=None, blocks=None, created_at=None):
    calls.append((threading.get_ident(), (content or "")[:40], created_at, len(blocks or [])))
    print(f"[SAVE] tid={threading.get_ident()} created_at={created_at} content={(content or '')[:40]!r} blocks={len(blocks or [])}", flush=True)
    return True


cli_runner._save_ai_message_sync = rec_save


async def main() -> int:
    fd, mcp_path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"mcpServers": {}}, f)

    content = (
        "次の3ステップを必ず1つずつ順に。各ステップで bash を1回だけ使い1行報告してから次へ:\n"
        "(1) `echo S1` (2) `echo S2` (3) `echo S3`"
    )
    events = []
    fu = [False]

    async def consume():
        async for ev in cli_runner._process_via_streaming_session(
            room_id="dbl-save-test", user_id="t", content=content,
            system_prompt="あなたはテスト用。指示に厳密に従う。", mcp_config_path=mcp_path,
            project_id=None, run_id=None, skip_save=False, cwd=PROJ,
        ):
            events.append(ev)
            if ev.get("type") == "result":
                print(f"[RESULT EVENT] continuation={ev.get('continuation')} text={(ev.get('text') or '')[:30]!r}", flush=True)

    task = asyncio.create_task(consume())
    for _ in range(160):
        await asyncio.sleep(0.5)
        if not fu[0] and any(e.get("type") == "tool_use" for e in events):
            s = get_session("dbl-save-test")
            if s and s.is_turn_active():
                s.submit_followup("残りのステップは中止して。今すぐ 'FU-DONE' とだけ返答して終了して。")
                fu[0] = True
                print("=== FU SUBMITTED (after first tool) ===", flush=True)
        if task.done():
            break
    await task

    print(f"\n=== TOTAL SAVE CALLS: {len(calls)} ===", flush=True)
    for c in calls:
        print(c, flush=True)
    # Detect duplicate (same content saved more than once)
    contents = [c[1] for c in calls]
    dupes = {x for x in contents if contents.count(x) > 1}
    if dupes:
        print(f"\n!!! DUPLICATE SAVE DETECTED: {dupes}", flush=True)
    else:
        print("\nno duplicate save", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
