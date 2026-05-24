# -*- coding: utf-8 -*-
"""Increment 2a smoke test: route a single normal turn through the persistent
streaming session path (_process_via_streaming_session) and confirm classified
events + a non-empty result arrive. Isolated: skip_save=True, project_id=None,
minimal mcp config → no DB writes, no live-core involvement."""
import asyncio
import json
import os
import sys
import tempfile

os.environ["DAN_STREAMING_INPUT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent import cli_runner  # noqa: E402


async def main() -> int:
    fd, mcp_path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"mcpServers": {}}, f)

    system_prompt = "あなたはテスト用アシスタント。日本語で簡潔に1文だけで答えること。"
    events = []
    async for ev in cli_runner._process_via_streaming_session(
        room_id="streaming-test-room",
        user_id="test-user",
        content="1たす1はいくつ？日本語で一言だけ答えて。",
        system_prompt=system_prompt,
        mcp_config_path=mcp_path,
        project_id=None,
        run_id=None,
        skip_save=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ):
        t = ev.get("type")
        if t == "text":
            print(f"[text] {ev.get('text', '')[:160]}", flush=True)
        elif t == "tool_use":
            print(f"[tool_use] {ev.get('name')}", flush=True)
        elif t == "reasoning":
            print(f"[reasoning] {ev.get('text', '')[:80]}", flush=True)
        elif t == "result":
            print(
                f"[RESULT] is_error={ev.get('is_error')} "
                f"cli_saved={ev.get('cli_saved')} text={ev.get('text', '')[:200]}",
                flush=True,
            )
        elif t == "error":
            print(f"[ERROR] {ev.get('message')}", flush=True)
        events.append(ev)

    results = [e for e in events if e.get("type") == "result"]
    if not results:
        print("\n=== FAIL: no result event ===", flush=True)
        return 1
    if not (results[0].get("text") or "").strip():
        print("\n=== FAIL: empty result text ===", flush=True)
        return 1
    print("\n=== 2a SMOKE TEST PASS ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
