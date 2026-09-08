"""Run Dan's Claude Code hooks from Codex CLI.

Codex hooks send the same JSON as Claude Code (``hook_event_name``,
``tool_name``, ``tool_input``), except that file edits arrive as one
``apply_patch`` call whose ``tool_input.command`` is the raw patch. This bridge
turns that into per-file ``Write``/``Edit`` payloads and runs the hooks that
``D:/dan-workspace/.claude/settings.json`` declares for the matching event, so
both backends enforce the same guards (broad-kill ban, feature guard, npm /
shadcn auto-install, artifact registration, forbidden patterns...).

Output contract (Codex): stdout JSON ``hookSpecificOutput`` with
``permissionDecision: deny`` blocks a PreToolUse; ``additionalContext`` on
PostToolUse is shown to the model. Exit code 2 from a Claude hook = deny.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = Path(os.environ.get("DAN_CLI_WORKSPACE") or "D:/dan-workspace")
SETTINGS = Path(os.environ.get("DAN_HOOK_SETTINGS") or (WORKSPACE / ".claude" / "settings.json"))
LOG = PROJECT_ROOT / "codex_hook_bridge.log"
HOOK_TIMEOUT = int(os.environ.get("DAN_HOOK_TIMEOUT", "120"))

_PATCH_FILE_RE = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+?)\s*$", re.MULTILINE)


def _log(msg: str) -> None:
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def _load_hooks(event: str) -> list[tuple[str, str]]:
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        _log(f"settings unreadable ({SETTINGS}): {e}")
        return []
    out = []
    for group in (data.get("hooks") or {}).get(event) or []:
        matcher = group.get("matcher") or ""
        for hook in group.get("hooks") or []:
            if hook.get("type", "command") == "command" and hook.get("command"):
                out.append((matcher, hook["command"]))
    return out


def _matches(matcher: str, tool_name: str) -> bool:
    if not matcher or matcher == "*":
        return True
    try:
        return re.fullmatch(matcher, tool_name) is not None or re.search(matcher, tool_name) is not None
    except re.error:
        return matcher == tool_name


def _synthesize(payload: dict) -> list[dict]:
    """Codex payload → list of Claude-shaped payloads."""
    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    if tool != "apply_patch":
        return [payload]
    patch = tool_input.get("command") or tool_input.get("patch") or ""
    out = []
    for kind, path in _PATCH_FILE_RE.findall(patch):
        if kind == "Delete":
            continue
        name = "Write" if kind == "Add" else "Edit"
        p = dict(payload)
        p["tool_name"] = name
        p["tool_input"] = {"file_path": path.strip()}
        out.append(p)
    return out


def _run_hook(command: str, payload: dict) -> tuple[int, str, str]:
    env = dict(os.environ)
    env.setdefault("CLAUDE_PROJECT_DIR", str(PROJECT_ROOT))
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = command.replace("$CLAUDE_PROJECT_DIR", str(PROJECT_ROOT))
    try:
        proc = subprocess.run(
            cmd, input=json.dumps(payload, ensure_ascii=False), capture_output=True,
            text=True, encoding="utf-8", errors="replace", shell=True, timeout=HOOK_TIMEOUT,
            cwd=str(PROJECT_ROOT), env=env,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return 0, "", f"hook timeout ({HOOK_TIMEOUT}s): {cmd[:80]}"
    except Exception as e:  # noqa: BLE001
        return 0, "", f"hook failed to start: {e}"


def _deny_reason(rc: int, stdout: str, stderr: str) -> str | None:
    if rc == 2:
        return (stderr.strip() or stdout.strip() or "blocked by hook")[:600]
    try:
        data = json.loads(stdout.strip() or "{}")
    except Exception:  # noqa: BLE001
        return None
    hso = data.get("hookSpecificOutput") or {}
    if hso.get("permissionDecision") == "deny":
        return (hso.get("permissionDecisionReason") or "blocked by hook")[:600]
    if data.get("decision") == "block":
        return (data.get("reason") or "blocked by hook")[:600]
    return None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:  # noqa: BLE001
        return 0
    event = payload.get("hook_event_name") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if event not in ("PreToolUse", "PostToolUse"):
        return 0
    hooks = _load_hooks(event)
    if not hooks:
        return 0

    contexts: list[str] = []
    for shaped in _synthesize(payload):
        tool = shaped.get("tool_name") or ""
        for matcher, command in hooks:
            if not _matches(matcher, tool):
                continue
            rc, out, err = _run_hook(command, shaped)
            _log(f"{event} {tool} {command[:70]} rc={rc} out={out.strip()[:120]!r} err={err.strip()[:120]!r}")
            if event == "PreToolUse":
                reason = _deny_reason(rc, out, err)
                if reason:
                    print(json.dumps({
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": reason,
                        }
                    }, ensure_ascii=False))
                    return 0
            else:
                text = out.strip()
                if text:
                    # Claude shows plain hook stdout to the model; Codex wants
                    # additionalContext. JSON outputs are passed as-is text.
                    contexts.append(text[:2000])
    if event == "PostToolUse" and contexts:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "\n".join(contexts)[:4000],
            }
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
