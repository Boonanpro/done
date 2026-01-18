#!/usr/bin/env python3
"""
Hook script for Claude Code - cleanup port 8000 before uvicorn commands.

Reads stdin to check if the bash command contains "uvicorn".
If so, runs the cleanup; otherwise exits immediately.
"""

import subprocess
import sys
import json


def get_pids_on_port(port: int = 8000) -> list[int]:
    """Get list of PIDs listening on the specified port."""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        pids = []
        for line in result.stdout.split("\n"):
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    try:
                        pid = int(parts[-1])
                        if pid > 0:
                            pids.append(pid)
                    except ValueError:
                        pass

        return list(set(pids))
    except Exception:
        return []


def kill_pid(pid: int) -> bool:
    """Kill a process by PID."""
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def cleanup_port():
    """Clean up port 8000."""
    pids = get_pids_on_port(8000)

    if not pids:
        return 0

    for pid in pids:
        kill_pid(pid)

    return 0


def main():
    """Check if uvicorn command, then cleanup."""
    try:
        # Read hook input from stdin
        stdin_data = sys.stdin.read()
        if not stdin_data.strip():
            return 0

        data = json.loads(stdin_data)
        command = data.get("tool_input", {}).get("command", "")

        # Only cleanup if this is a uvicorn command
        if "uvicorn" not in command.lower():
            return 0

        # Run cleanup
        cleanup_port()

    except Exception:
        # On any error, just return success to not block the command
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
