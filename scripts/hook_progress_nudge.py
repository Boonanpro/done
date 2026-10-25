"""PostToolUse / Stop hook: remind Dan to write the chat's work lines with the progress tool (2026-10-25).

The chat shows the owner a few lines while a turn runs (app/services/work_progress.py). They read well only when
Dan writes them itself (done = what was done and found, doing = what it does now). With the instruction alone it did
not: after the 15:50 restart a test turn on Claude used 13 tools and one on GPT used 4, with no progress call in
either, so the owner saw only words picked per tool kind (「ページを操作しています」「調べています」).

So after each tool this counts the tools used in the turn since the last progress call and, at the 3rd without one
(the 6th once progress has been written in the turn), tells the model through additionalContext. One- or two-tool
answers are never nudged. Stop (end of a turn) clears the count.

Both backends: Claude Code runs it from the room workspace's .claude/settings.json; Codex through
scripts/codex_hook_bridge.py (PostToolUse for every tool, app/agent/codex_runner.build_codex_profile). Codex sends a
turn_id; Claude does not, so a turn there ends at Stop or after 10 minutes without a tool.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / ".data" / "progress_nudge"
TURN_GAP_SECONDS = 600
FIRST_NUDGE = 3   # tools in a turn with no progress yet
LATER_NUDGE = 6   # tools since the last progress call, once one was made

NUDGE_FIRST = (
    "本人のチャットには、まだ作業の様子が出ていません。段取りの区切りで progress を呼び、"
    "doing に今していること（「〜しています」）、段取りが終わったら done に何をして何が分かったか"
    "（「〜しました」「〜でした」）を書いてください。返事の本文には書きません。"
)
NUDGE_LATER = (
    "しばらく progress を書いていません。終わった段取りがあれば done（何をして何が分かったか）と、"
    "次の doing を progress で書いてください。"
)


def _activity_line():
    """app/agent/activity_line.py without importing the app package (keeps the hook fast)."""
    spec = importlib.util.spec_from_file_location("_dan_activity_line", PROJECT_ROOT / "app" / "agent" / "activity_line.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _state_path(payload: dict) -> Path | None:
    key = str(payload.get("session_id") or payload.get("transcript_path") or "")
    if not key:
        return None
    return STATE_DIR / (re.sub(r"[^A-Za-z0-9_.-]", "_", key)[-120:] + ".json")


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path: Path, state: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _prune(now: float) -> None:
    try:
        for f in STATE_DIR.glob("*.json"):
            if now - f.stat().st_mtime > 86400:
                f.unlink(missing_ok=True)
    except OSError:
        pass


def decide(state: dict, tool_name: str, turn_id: str, now: float, silent: set, base_name) -> tuple[dict, str]:
    """(new state, the reminder to show or "") for one finished tool. Pure, for the tests."""
    same_turn = (
        (turn_id and state.get("turn") == turn_id)
        or (not turn_id and not state.get("turn") and now - float(state.get("at") or 0) < TURN_GAP_SECONDS)
    )
    if not same_turn:
        state = {"since": 0, "wrote": False}
    state = {**state, "turn": turn_id, "at": now}
    name = base_name(tool_name)
    if name == "progress":
        return {**state, "since": 0, "wrote": True}, ""
    if name in silent:
        return state, ""
    since = int(state.get("since") or 0) + 1
    state = {**state, "since": since}
    if not state.get("wrote"):
        return state, (NUDGE_FIRST if since == FIRST_NUDGE else "")
    return state, (NUDGE_LATER if since and since % LATER_NUDGE == 0 else "")


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    path = _state_path(payload)
    if path is None:
        return 0
    event = payload.get("hook_event_name") or ""
    now = time.time()
    if event == "Stop":
        path.unlink(missing_ok=True)
        _prune(now)
        return 0
    if event != "PostToolUse":
        return 0
    try:
        al = _activity_line()
        silent, base_name = set(al._SILENT) | {"ToolSearch", "TodoWrite"}, al._base_name
    except Exception:  # noqa: BLE001
        return 0
    state, text = decide(_load(path), str(payload.get("tool_name") or ""), str(payload.get("turn_id") or ""),
                         now, silent, base_name)
    _save(path, state)
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
