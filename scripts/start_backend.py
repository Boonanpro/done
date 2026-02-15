#!/usr/bin/env python3
"""
Backend startup script - THE ONLY WAY to start the backend.

This script:
1. Finds and kills ALL uvicorn processes using wmic (reliable)
2. Waits for port 8000 to be free
3. Starts uvicorn with subprocess.Popen
4. Verifies startup with health check

Usage:
    python scripts/start_backend.py
"""

import re
import subprocess
import sys
import time
import socket
import urllib.request
import urllib.error


def get_uvicorn_processes() -> list[tuple[int, str]]:
    """
    Get all Python processes related to uvicorn using wmic.

    This includes:
    - uvicorn main process (contains "uvicorn" in command)
    - Child processes spawned by uvicorn (contains "parent_pid=" in command)
    """
    try:
        result = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "processid,commandline"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        processes = []
        uvicorn_pids = set()

        # First pass: find uvicorn main processes
        for line in result.stdout.split("\n"):
            line = line.strip()
            if not line or "CommandLine" in line:
                continue
            if "uvicorn" in line.lower():
                parts = line.split()
                if parts:
                    try:
                        pid = int(parts[-1])
                        cmdline = " ".join(parts[:-1])[:60]
                        processes.append((pid, cmdline))
                        uvicorn_pids.add(pid)
                    except ValueError:
                        pass

        # Second pass: find child processes (multiprocessing spawn)
        for line in result.stdout.split("\n"):
            line = line.strip()
            if not line or "CommandLine" in line:
                continue
            # Check for multiprocessing spawn children
            if "multiprocessing" in line.lower() and "spawn" in line.lower():
                # Extract parent_pid from command line
                match = re.search(r'parent_pid=(\d+)', line)
                if match:
                    parent_pid = int(match.group(1))
                    # If parent is a uvicorn process (or was killed), include this child
                    parts = line.split()
                    if parts:
                        try:
                            pid = int(parts[-1])
                            if pid not in uvicorn_pids:  # Don't add duplicates
                                cmdline = f"[child of PID {parent_pid}]"
                                processes.append((pid, cmdline))
                        except ValueError:
                            pass

        return processes
    except Exception as e:
        print(f"[start] Error getting processes: {e}")
        return []


def kill_process(pid: int) -> bool:
    """Kill a process by PID using taskkill."""
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[start] Error killing PID {pid}: {e}")
        return False


def is_port_free(port: int = 8000) -> bool:
    """Check if port is free."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) != 0


def check_health(timeout: int = 5) -> bool:
    """Check if backend is healthy."""
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8000/health",
            headers={"User-Agent": "start_backend.py"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def get_sdk_processes() -> list[tuple[int, str]]:
    """
    Get all SDK-related processes (claude.exe and mcp_server.py).

    These are spawned by the Agent SDK during project execution
    and must be cleaned up on backend restart.
    """
    processes = []
    try:
        # claude.exe (SDK agent processes)
        result = subprocess.run(
            ["wmic", "process", "where", "name='claude.exe'", "get", "processid,commandline"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.split("\n"):
            line = line.strip()
            if not line or "CommandLine" in line:
                continue
            parts = line.split()
            if parts:
                try:
                    pid = int(parts[-1])
                    processes.append((pid, "claude.exe"))
                except ValueError:
                    pass

        # mcp_server.py (MCP server processes spawned by SDK)
        result = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "processid,commandline"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.split("\n"):
            line = line.strip()
            if not line or "CommandLine" in line:
                continue
            if "mcp_server.py" in line:
                parts = line.split()
                if parts:
                    try:
                        pid = int(parts[-1])
                        processes.append((pid, "mcp_server.py"))
                    except ValueError:
                        pass
    except Exception as e:
        print(f"[start] Error getting SDK processes: {e}")
    return processes


def cleanup() -> bool:
    """Kill all uvicorn processes, SDK processes, and wait for port to be free."""
    print("[start] Step 1: Finding uvicorn processes with wmic...")

    processes = get_uvicorn_processes()

    if not processes:
        print("[start] No uvicorn processes found.")
    else:
        print(f"[start] Found {len(processes)} uvicorn process(es):")
        for pid, cmdline in processes:
            print(f"  PID {pid}: {cmdline}...")

        print("[start] Step 2: Killing all uvicorn processes...")
        for pid, _ in processes:
            if kill_process(pid):
                print(f"  [OK] Killed PID {pid}")
            else:
                print(f"  [FAIL] Could not kill PID {pid}")

    # Kill leftover SDK processes (claude.exe, mcp_server.py)
    print("[start] Step 2b: Cleaning up SDK processes (claude.exe, mcp_server.py)...")
    sdk_procs = get_sdk_processes()
    if not sdk_procs:
        print("[start] No SDK processes found.")
    else:
        print(f"[start] Found {len(sdk_procs)} SDK process(es):")
        for pid, name in sdk_procs:
            print(f"  PID {pid}: {name}")
        for pid, name in sdk_procs:
            if kill_process(pid):
                print(f"  [OK] Killed {name} PID {pid}")
            else:
                print(f"  [FAIL] Could not kill {name} PID {pid}")

    # Wait for port to be free
    print("[start] Step 3: Waiting for port 8000 to be free...")
    for i in range(15):
        if is_port_free(8000):
            print("[start] Port 8000 is free.")
            return True
        print(f"  Waiting... ({i+1}/15)")
        time.sleep(1)

    print("[start] ERROR: Port 8000 is still in use after 15 seconds!")
    return False


def start_uvicorn() -> subprocess.Popen:
    """Start uvicorn server with subprocess.Popen."""
    print("[start] Step 4: Starting uvicorn...")

    cmd = [sys.executable, "-m", "uvicorn", "main:app",
           "--host", "0.0.0.0", "--port", "8000", "--reload"]

    # CLAUDECODE を除外した環境変数を渡す
    # （Claude Code セッション内から起動しても SDK が動くようにする）
    import os
    clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    log_file = open("D:/done/backend.log", "w", encoding="utf-8")
    process = subprocess.Popen(
        cmd,
        cwd="D:/done",
        stdout=log_file,
        stderr=log_file,
        env=clean_env,
    )

    print(f"[start] uvicorn started with PID {process.pid}")
    return process


def verify_startup(max_attempts: int = 10) -> bool:
    """Verify backend started successfully."""
    print("[start] Step 5: Verifying startup...")

    for i in range(max_attempts):
        if check_health():
            print("[start] Health check passed!")
            return True
        print(f"  Waiting for backend... ({i+1}/{max_attempts})")
        time.sleep(1)

    print("[start] ERROR: Backend did not respond to health check!")
    return False


def main():
    print("=" * 60)
    print("Backend Startup Script (wmic-based, reliable)")
    print("=" * 60)

    # Step 1-3: Cleanup
    if not cleanup():
        print("[start] Cleanup failed. Aborting.")
        sys.exit(1)

    # Step 4: Start
    process = start_uvicorn()

    # Step 5: Verify
    if verify_startup():
        print("=" * 60)
        print(f"[start] SUCCESS! Backend running on http://127.0.0.1:8000")
        print(f"[start] Process PID: {process.pid}")
        print("=" * 60)
        sys.exit(0)
    else:
        print("[start] Startup verification failed. Killing process...")
        process.terminate()
        sys.exit(1)


if __name__ == "__main__":
    main()
