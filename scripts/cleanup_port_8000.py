#!/usr/bin/env python3
"""
Port 8000 cleanup script for Claude Code hooks.

Automatically kills any process listening on port 8000 before starting the backend.
This prevents the issue of multiple backend processes running simultaneously.

NOTE: netstatのPIDは信頼できないことがある。
PowerShellでuvicornプロセスを直接探して殺す方法を使用。
"""

import subprocess
import sys


def kill_uvicorn_processes() -> int:
    """
    PowerShellでuvicornを含むPythonプロセスを全て殺す。
    netstatのPIDは信頼できないため、この方法がより確実。
    """
    try:
        # PowerShellでuvicornプロセスを探して殺す
        result = subprocess.run(
            [
                "powershell", "-Command",
                """
                $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
                    Where-Object { $_.CommandLine -like '*uvicorn*' }
                if ($procs) {
                    $procs | ForEach-Object {
                        Write-Host "[cleanup] Killing uvicorn process PID: $($_.ProcessId)"
                        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                    }
                    Write-Host "[cleanup] Killed $($procs.Count) uvicorn process(es)"
                } else {
                    Write-Host "[cleanup] No uvicorn processes found"
                }
                """
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        print(result.stdout.strip())
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        return result.returncode
    except Exception as e:
        print(f"[cleanup] Error in PowerShell cleanup: {e}", file=sys.stderr)
        return 1


def get_pids_on_port(port: int = 8000) -> list[int]:
    """Get list of PIDs listening on the specified port (fallback method)."""
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
        print(f"[cleanup] Error checking port: {e}", file=sys.stderr)
        return []


def kill_pid(pid: int) -> bool:
    """Kill a process by PID (fallback method)."""
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[cleanup] Error killing PID {pid}: {e}", file=sys.stderr)
        return False


def main():
    """Clean up port 8000."""
    print("[cleanup] Starting cleanup...")

    # Primary method: Kill uvicorn processes by command line match
    kill_uvicorn_processes()

    # Fallback: Try killing by port PIDs (may have stale entries)
    pids = get_pids_on_port(8000)
    if pids:
        print(f"[cleanup] Fallback: Found {len(pids)} PID(s) on port 8000: {pids}")
        for pid in pids:
            if kill_pid(pid):
                print(f"[cleanup] Fallback: Killed PID {pid}")
            else:
                print(f"[cleanup] Fallback: Failed to kill PID {pid} (may already be dead)")

    print("[cleanup] Cleanup complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
