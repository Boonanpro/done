# -*- coding: utf-8 -*-
"""Increment #0 test: DB persistence survives an SSE drop.

Simulates the salonboard failure: the consumer (SSE) abandons the generator
mid-turn (phone backgrounds). With saves moved into the sink/reader-thread, the
final ai_message must STILL be saved after the generator is closed.

Patches _save_ai_message_sync to record calls (no real DB write).
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

saved = []
_orig = cli_runner._save_ai_message_sync


def _recording_save(room_id, content, reasoning_steps=None, reasoning_full=None, blocks=None):
    saved.append({"content": content, "blocks": blocks})
    print(f"[SAVE CALLED] content={content[:60]!r} blocks={len(blocks or [])}", flush=True)
    return True


cli_runner._save_ai_message_sync = _recording_save


async def main() -> int:
    fd, mcp_path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"mcpServers": {}}, f)

    system_prompt = "あなたはテスト用アシスタント。指示に厳密に従う。"
    content = "bashツールで1回だけ `echo HELLO` を実行してから、一言『DONE』とだけ返答して終了して。"

    gen = cli_runner._process_via_streaming_session(
        room_id="streaming-2c-drop-test", user_id="t", content=content,
        system_prompt=system_prompt, mcp_config_path=mcp_path,
        project_id=None, run_id=None, skip_save=False, cwd=PROJ,
    )

    # Consume only the FIRST event, then abandon + close the generator
    # (= the SSE client disconnected / phone backgrounded mid-turn).
    first = None
    async for ev in gen:
        first = ev.get("type")
        print(f"[GOT FIRST EVENT] {first} -> dropping consumer now", flush=True)
        break
    await gen.aclose()
    print("[GENERATOR CLOSED] (simulated SSE drop)", flush=True)

    # The reader thread keeps running the turn; the final ai_message must still
    # be saved. Poll up to 40s for the recorder.
    for _ in range(80):
        if saved:
            break
        await asyncio.sleep(0.5)

    if not saved:
        print("\n=== FAIL: ai_message was NOT saved after SSE drop (#0 NOT fixed) ===", flush=True)
        return 1
    print(f"\n=== #0 TEST PASS: ai_message saved despite SSE drop ({len(saved)} save(s)) ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
