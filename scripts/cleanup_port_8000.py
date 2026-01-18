#!/usr/bin/env python3
"""
Port 8000 cleanup script for Claude Code hooks.

Automatically kills any process listening on port 8000 before starting the backend.
This prevents the issue of multiple backend processes running simultaneously.
"""

import subprocess
import sys


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
    except Exception as e:
        print(f"Error checking port: {e}", file=sys.stderr)
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
    except Exception as e:
        print(f"Error killing PID {pid}: {e}", file=sys.stderr)
        return False


def main():
    """Clean up port 8000."""
    pids = get_pids_on_port(8000)

    if not pids:
        print("[cleanup] Port 8000 is free.")
        return 0

    print(f"[cleanup] Found {len(pids)} process(es) on port 8000: {pids}")

    for pid in pids:
        if kill_pid(pid):
            print(f"[cleanup] Killed PID {pid}")
        else:
            print(f"[cleanup] Failed to kill PID {pid}", file=sys.stderr)

    print("[cleanup] Port 8000 cleanup complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
