# -*- coding: utf-8 -*-
"""Lock in the streaming --resume wiring (deterministic, no real claude).

Context-survives-restart relies on the streaming launch command carrying
`--resume <saved session id>`. This patches get_or_create_session to capture
the build_cmd the streaming path constructs and asserts:
  - resume_session_id set  -> `--resume <id>` IS in the command
  - resume_session_id None -> `--resume` is NOT in the command

(The fact that --resume actually restores context in the persistent
stream-json mode was verified separately against the real CLI.)
"""
import asyncio
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

from app.agent import cli_runner  # noqa: E402
import app.agent.streaming_session as ss  # noqa: E402


class _FakeSession:
    last_turn_hung = False

    def run_turn(self, content, sink, timeout=600):
        sink({"type": "system", "session_id": "sess-xyz"})
        sink({"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}})
        sink({"type": "result", "result": "OK", "is_error": False})
        return {"result": "OK"}


async def _collect_cmd(resume_session_id):
    captured = {}

    def fake_get_or_create(room_id, build_cmd, env, cwd):
        captured["cmd"] = build_cmd()
        return _FakeSession()

    ss.get_or_create_session = fake_get_or_create
    cli_runner._save_session = lambda *a, **k: None
    cli_runner._update_run_sync = lambda *a, **k: None

    async for _ in cli_runner._process_via_streaming_session(
        room_id="resume-wiring-test", user_id="t", content="hi",
        system_prompt="test", mcp_config_path="dummy.json",
        project_id=None, run_id=None, skip_save=True, cwd=PROJ,
        resume_session_id=resume_session_id,
    ):
        pass
    return captured.get("cmd", [])


def main() -> int:
    fails = []

    cmd_with = asyncio.run(_collect_cmd("SID-12345"))
    print("[with resume] --resume present:", "--resume" in cmd_with,
          "| id present:", "SID-12345" in cmd_with)
    if "--resume" not in cmd_with or "SID-12345" not in cmd_with:
        fails.append("resume_session_id set but launch command lacks --resume <id>")
    # --resume must be immediately followed by the id
    if "--resume" in cmd_with and cmd_with[cmd_with.index("--resume") + 1] != "SID-12345":
        fails.append("--resume not followed by the session id")

    cmd_without = asyncio.run(_collect_cmd(None))
    print("[no resume]   --resume present:", "--resume" in cmd_without)
    if "--resume" in cmd_without:
        fails.append("no saved session but launch command still has --resume")

    if fails:
        print("\n=== FAIL ===")
        for x in fails:
            print("  -", x)
        return 1
    print("\n=== PASS: --resume wired only when a saved session exists ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
