"""Regression smoke test for the edited cli_runner read path (reader-thread + queue).
Runs a trivial real CLI turn end-to-end and confirms it streams events AND returns
(does not hang). Exercises the normal-EOF path of _run_cli_process after the change.
"""
import asyncio, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.cli_runner import process_message_cli

async def main():
    start = time.time()
    events = 0
    got_result = False
    async for event in process_message_cli(
        room_id="smoke_cli_runner_test",
        user_id="00000000-0000-0000-0000-000000000000",
        content="Reply with exactly the word: PONG. Nothing else.",
        project_title="smoke",
        project_description="",
        project_status="in_progress",
        skip_save=True,
        skip_resume=True,
        cwd="D:/dan-workspace",
    ):
        et = str(event.get("type") or "")
        events += 1
        if et in {"text", "result"}:
            txt = str(event.get("text") or event.get("message") or "")[:80]
            print(f"  [{et}] {txt}")
        if et == "result":
            got_result = True
    elapsed = time.time() - start
    print(f"\nstreamed {events} events, result={got_result}, returned in {elapsed:.1f}s")
    assert events > 0, "FAIL: no events streamed"
    assert elapsed < 120, f"FAIL: took {elapsed:.1f}s (possible hang)"
    print("PASS: CLI turn completed and the generator returned (no hang)")

asyncio.run(main())
