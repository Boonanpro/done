"""Local timings only; never record task text, URLs or browser contents."""

import json
import os
import re
import threading
import time
from contextlib import aclosing
from functools import wraps
from pathlib import Path

_lock = threading.Lock()


def record_timing(phase, operation, elapsed_ms, status="ok", counts=None):
    if os.environ.get("DAN_BROWSER_METRICS", "1") == "0":
        return
    try:
        path = Path(os.environ.get("DAN_BROWSER_TIMING_LOG") or
                    Path.home() / ".dan" / "logs" / "browser-timing.jsonl")
        event = {"time": time.time(), "pid": os.getpid(), "phase": phase,
                 "operation": operation, "elapsed_ms": round(elapsed_ms, 2), "status": status}
        if counts:
            event.update({key: value for key, value in counts.items()
                          if key in {"browser_calls", "tool_calls", "error_events"} and isinstance(value, int)})
            reason = counts.get("reason")
            if isinstance(reason, str) and reason:
                # a code like 'unexpected_screen' or 'jev_unavailable' (never page text): why a workflow handed off
                event["reason"] = re.sub(r"[^A-Za-z0-9_:.-]", "", reason.split(":")[0])[:60]
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Bound per-file growth. This file is diagnostic, not an audit log.
            if path.exists() and path.stat().st_size > 10 * 1024 * 1024:
                path.replace(path.with_suffix(".previous.jsonl"))
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event) + "\n")
    except Exception:
        pass  # Diagnostics must never break an action.


def measure_browser_request(function):
    """Time the actual agent request stream, including model/server waits.

    'returned' means a result event arrived, not that the user's job succeeded.
    Preserve event contents and generator cleanup; never persist input/output.
    """
    @wraps(function)
    async def measured(*args, **kwargs):
        started = time.perf_counter()
        counts = {"browser_calls": 0, "tool_calls": 0, "error_events": 0}
        status = "interrupted"
        try:
            async with aclosing(function(*args, **kwargs)) as stream:
                async for event in stream:
                    if event.get("type") == "tool_use":
                        counts["tool_calls"] += 1
                        if event.get("name", "").split("__")[-1] in {"browser", "browser_plan", "browser_flow", "browser_script"}:
                            counts["browser_calls"] += 1
                    elif event.get("type") == "error":
                        counts["error_events"] += 1
                    elif event.get("type") == "result":
                        status = "error" if event.get("is_error") else "returned"
                    yield event
        finally:
            if counts["browser_calls"]:
                record_timing("agent_request", "browser", (time.perf_counter()-started)*1000, status, counts)
    return measured
