# -*- coding: utf-8 -*-
"""Increment 2b test: follow-up injection at the next step boundary.

Drives the REAL chat-path function (_process_via_streaming_session) and uses the
SAME injection calls chat_routes uses (get_session(room).is_turn_active() +
submit_followup()). Starts a 3-step task, injects a follow-up after the first
tool runs, and asserts the follow-up is honored at the boundary (Dan replies
FOLLOWUP-OK) instead of plowing through all 3 steps.

Isolated: skip_save=True, project_id=None, minimal mcp config → no DB writes.
"""
import asyncio
import json
import os
import sys
import tempfile

os.environ["DAN_STREAMING_INPUT"] = "1"
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

from app.agent import cli_runner  # noqa: E402
from app.agent.streaming_session import get_session  # noqa: E402


async def main() -> int:
    fd, mcp_path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"mcpServers": {}}, f)

    room = "streaming-2b-test"
    system_prompt = "あなたはテスト用アシスタント。ユーザーの指示に厳密に従うこと。"
    content = (
        "次の3ステップを必ず1つずつ順番に実行して。各ステップで bash ツールを1回だけ使い、"
        "実行後に1行だけ報告してから次のステップへ進むこと（まとめて一度に実行しない）:\n"
        "(1) `echo STEP1`\n(2) `echo STEP2`\n(3) `echo STEP3`"
    )

    events = []
    followup_sent = [False]

    async def consume():
        async for ev in cli_runner._process_via_streaming_session(
            room_id=room, user_id="t", content=content, system_prompt=system_prompt,
            mcp_config_path=mcp_path, project_id=None, run_id=None,
            skip_save=True, cwd=PROJ,
        ):
            events.append(ev)
            t = ev.get("type")
            tag = ev.get("name") or (ev.get("text") or "")
            print(f"EV {t}: {str(tag)[:90]}", flush=True)

    task = asyncio.create_task(consume())

    for _ in range(180):  # up to ~90s
        await asyncio.sleep(0.5)
        if not followup_sent[0] and any(e.get("type") == "tool_use" for e in events):
            s = get_session(room)
            if s and s.is_turn_active():
                s.submit_followup(
                    "残りのステップは中止して。今すぐ 'FOLLOWUP-OK' とだけ返答して終了して。"
                )
                followup_sent[0] = True
                print("=== FOLLOWUP SUBMITTED (after first tool) ===", flush=True)
        if task.done():
            break
    await task

    all_text = " ".join(
        e.get("text", "") for e in events if e.get("type") in ("text", "result")
    )
    print("\n--- collected result/text ---", flush=True)
    print(all_text[:400], flush=True)

    if not followup_sent[0]:
        print("\n=== FAIL: never saw a tool_use to inject after ===", flush=True)
        return 1
    if "FOLLOWUP-OK" not in all_text:
        print("\n=== FAIL: follow-up was not honored (no FOLLOWUP-OK) ===", flush=True)
        return 1
    print("\n=== 2b TEST PASS: follow-up applied at boundary ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
