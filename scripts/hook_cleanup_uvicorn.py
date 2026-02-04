#!/usr/bin/env python3
"""
Hook script for Claude Code - BLOCK direct uvicorn commands.

This hook:
1. Detects any uvicorn command
2. ALWAYS blocks it
3. Instructs to use 'python scripts/start_backend.py' instead

Why block instead of cleanup?
- start_backend.py kills both parent AND child processes
- start_backend.py verifies startup with health check
- start_backend.py provides clear logging
- Hooks may not wait for completion, causing race conditions

Exit codes:
- 0: Success (with JSON output for deny)
"""

import sys
import json


def log_debug(msg: str):
    """Write debug log to file."""
    import datetime
    try:
        with open("D:/done/logs/hook_debug.log", "a", encoding="utf-8") as f:
            timestamp = datetime.datetime.now().isoformat()
            f.write(f"[{timestamp}] {msg}\n")
    except Exception:
        pass


def main():
    log_debug("=" * 50)
    log_debug("Hook script started")

    try:
        # Read hook input from stdin
        stdin_data = sys.stdin.read()

        if not stdin_data.strip():
            log_debug("Empty stdin, exiting")
            return 0

        data = json.loads(stdin_data)
        command = data.get("tool_input", {}).get("command", "")
        log_debug(f"Command: {command[:100] if command else 'none'}")

        # Only check for uvicorn commands
        if "uvicorn" not in command.lower():
            log_debug("Not a uvicorn command, allowing")
            return 0

        # Check if this is start_backend.py calling uvicorn (allow it)
        if "start_backend.py" in command:
            log_debug("start_backend.py detected, allowing")
            return 0

        # Block direct uvicorn commands
        log_debug("BLOCKING direct uvicorn command")
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "Direct uvicorn commands are blocked. "
                    "Use 'python scripts/start_backend.py' instead. "
                    "This ensures all old processes are killed and startup is verified."
                )
            }
        }
        print(json.dumps(output))
        return 0

    except Exception as e:
        log_debug(f"Exception: {e}")
        # On error, allow (don't block everything)
        return 0


if __name__ == "__main__":
    sys.exit(main())
