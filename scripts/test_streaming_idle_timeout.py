# -*- coding: utf-8 -*-
"""Verify the streaming run_turn idle-timeout fix.

Regression target: a long task whose process log / text "全部消えて回答が返って
こない". Root cause was run_turn using a fixed wall-clock timeout (600s) that
abandoned ACTIVE turns mid-work, closed the SSE, and dropped the (eventually
arriving) result so it was never saved.

This test drives StreamingSession with a tiny fake stream-json CLI (no real
`claude`), so it is deterministic and fast:

  (1) ACTIVE  — events keep flowing for far longer than the idle threshold,
                then a `result`. Must run to completion and return the result
                (the old fixed-deadline code would cut it off).
  (2) SILENT  — no output at all after start. Must be detected as a hang after
                the idle threshold, return None, set last_turn_hung, and tear
                the session down (so the next turn starts on a clean process).
"""
import os
import sys
import tempfile
import time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

from app.agent.streaming_session import StreamingSession  # noqa: E402

# Fake CLI: reads one user message line, then behaves per FAKE_MODE.
_FAKE = r'''
import sys, os, time, json
mode = os.environ.get("FAKE_MODE", "active")
sys.stdin.readline()  # consume the user message
sys.stdout.write(json.dumps({"type": "system", "session_id": "fake-sess"}) + "\n")
sys.stdout.flush()
if mode == "active":
    end = time.time() + float(os.environ.get("ACTIVE_SECONDS", "4"))
    i = 0
    while time.time() < end:
        i += 1
        sys.stdout.write(json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "step %d" % i}]}}) + "\n")
        sys.stdout.flush()
        time.sleep(0.3)
    sys.stdout.write(json.dumps({"type": "result", "result": "DONE-ACTIVE", "is_error": False}) + "\n")
    sys.stdout.flush()
    time.sleep(30)  # stay alive so the session is still "alive" after the result
else:  # silent
    time.sleep(30)  # never emit a result
'''


def _write_fake() -> str:
    fd, path = tempfile.mkstemp(suffix="_fakecli.py")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(_FAKE)
    return path


def _run_case(mode: str, idle_timeout: float, active_seconds: float = 4.0):
    fake = _write_fake()
    env = dict(os.environ)
    env["FAKE_MODE"] = mode
    env["ACTIVE_SECONDS"] = str(active_seconds)
    sess = StreamingSession(
        "idle-test-" + mode, (lambda: [sys.executable, fake]), env, PROJ
    )
    events = []
    t0 = time.time()
    result = sess.run_turn("go", lambda ev: events.append(ev.get("type")), timeout=idle_timeout)
    dt = time.time() - t0
    info = (result, sess.last_turn_hung, sess.is_alive(), dt, len(events))
    sess.stop()
    try:
        os.unlink(fake)
    except OSError:
        pass
    return info


def main() -> int:
    fails = []

    # (1) ACTIVE turn: 4s of activity, idle threshold 1.5s -> must complete.
    result, hung, alive, dt, n = _run_case("active", idle_timeout=1.5, active_seconds=4.0)
    print(f"[ACTIVE] result={result and result.get('result')!r} hung={hung} dt={dt:.1f}s events={n}")
    if result is None or result.get("result") != "DONE-ACTIVE":
        fails.append("ACTIVE turn did not complete — it was wrongly abandoned mid-work")
    if hung:
        fails.append("ACTIVE turn wrongly flagged as hung")
    if dt < 3.5:
        fails.append(f"ACTIVE turn ended too early ({dt:.1f}s) — idle timeout fired on active work")

    # (2) SILENT turn: no output, idle threshold 1.0s -> hang + teardown.
    result, hung, alive, dt, n = _run_case("silent", idle_timeout=1.0)
    print(f"[SILENT] result={result!r} hung={hung} alive_after={alive} dt={dt:.1f}s")
    if result is not None:
        fails.append("SILENT turn returned a result (expected None)")
    if not hung:
        fails.append("SILENT turn not detected as hung")
    if alive:
        fails.append("SILENT turn: session not torn down after hang")
    if dt > 3.0:
        fails.append(f"SILENT hang detection too slow ({dt:.1f}s)")

    if fails:
        print("\n=== FAIL ===")
        for x in fails:
            print("  -", x)
        return 1
    print("\n=== PASS: active long turns complete; silent turns detected + torn down ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
