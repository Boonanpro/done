#!/usr/bin/env python3
"""
Test backend startup script - port 8001 ONLY.

This script starts a test backend on port 8001 for Blue-Green testing.
It NEVER touches port 8000 (production).

Usage:
    python scripts/start_test_backend.py
"""

import re
import subprocess
import sys
import time
import socket
import urllib.request
import urllib.error

TEST_PORT = 8001


def get_port_processes(port: int) -> list[tuple[int, str]]:
    """
    Get processes listening on the specified port using netstat + wmic.
    """
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        pids = set()
        for line in result.stdout.split("\n"):
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    try:
                        pid = int(parts[-1])
                        if pid > 0:
                            pids.add(pid)
                    except ValueError:
                        pass

        processes = []
        for pid in pids:
            try:
                cmd_result = subprocess.run(
                    ["wmic", "process", "where", f"processid={pid}", "get", "commandline"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                cmdline = ""
                for line in cmd_result.stdout.split("\n"):
                    line = line.strip()
                    if line and "CommandLine" not in line:
                        cmdline = line[:80]
                        break
                processes.append((pid, cmdline or f"PID {pid}"))
            except Exception:
                processes.append((pid, f"PID {pid}"))

        return processes
    except Exception as e:
        print(f"[test-backend] Error getting port processes: {e}")
        return []


def kill_process(pid: int) -> bool:
    """Kill a process by PID using taskkill."""
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[test-backend] Error killing PID {pid}: {e}")
        return False


def is_port_free(port: int) -> bool:
    """Check if port is free by attempting to bind (immune to ghost sockets)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('127.0.0.1', port))
            return True
    except OSError:
        return False


def check_health(port: int, timeout: int = 5) -> bool:
    """Check if backend is healthy."""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/health",
            headers={"User-Agent": "start_test_backend.py"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def cleanup() -> bool:
    """Kill processes on test port and wait for it to be free."""
    print(f"[test-backend] Step 1: Finding processes on port {TEST_PORT}...")

    processes = get_port_processes(TEST_PORT)

    if not processes:
        print(f"[test-backend] No processes found on port {TEST_PORT}.")
    else:
        print(f"[test-backend] Found {len(processes)} process(es) on port {TEST_PORT}:")
        for pid, cmdline in processes:
            print(f"  PID {pid}: {cmdline}")

        print(f"[test-backend] Step 2: Killing processes on port {TEST_PORT}...")
        for pid, _ in processes:
            if kill_process(pid):
                print(f"  [OK] Killed PID {pid}")
            else:
                print(f"  [FAIL] Could not kill PID {pid}")

    # Wait for port to be free
    print(f"[test-backend] Step 3: Waiting for port {TEST_PORT} to be free...")
    for i in range(10):
        if is_port_free(TEST_PORT):
            print(f"[test-backend] Port {TEST_PORT} is free.")
            return True
        print(f"  Waiting... ({i+1}/10)")
        time.sleep(1)

    print(f"[test-backend] ERROR: Port {TEST_PORT} is still in use after 10 seconds!")
    return False


def start_uvicorn() -> subprocess.Popen:
    """Start uvicorn on test port."""
    print(f"[test-backend] Step 4: Starting uvicorn on port {TEST_PORT}...")

    cmd = [sys.executable, "-m", "uvicorn", "main:app",
           "--host", "127.0.0.1", "--port", str(TEST_PORT), "--reload"]

    import os
    clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    log_file = open("D:/done/test_backend.log", "w", encoding="utf-8")
    process = subprocess.Popen(
        cmd,
        cwd="D:/done",
        stdout=log_file,
        stderr=log_file,
        env=clean_env,
    )

    print(f"[test-backend] uvicorn started with PID {process.pid}")
    return process


def verify_startup(max_attempts: int = 15) -> bool:
    """Verify test backend started successfully."""
    print("[test-backend] Step 5: Verifying startup...")

    for i in range(max_attempts):
        if check_health(TEST_PORT):
            print("[test-backend] Health check passed!")
            return True
        print(f"  Waiting for test backend... ({i+1}/{max_attempts})")
        time.sleep(1)

    print("[test-backend] ERROR: Test backend did not respond to health check!")
    return False


def main():
    print("=" * 60)
    print(f"Test Backend Startup Script (port {TEST_PORT} only)")
    print(f"WARNING: This script NEVER touches port 8000 (production)")
    print("=" * 60)

    # Safety check: make sure we're not accidentally targeting port 8000
    assert TEST_PORT != 8000, "FATAL: TEST_PORT must not be 8000!"

    # Step 1-3: Cleanup
    if not cleanup():
        print("[test-backend] Cleanup failed. Aborting.")
        sys.exit(1)

    # Step 4: Start
    process = start_uvicorn()

    # Step 5: Verify
    if verify_startup():
        print("=" * 60)
        print(f"[test-backend] SUCCESS! Test backend running on http://127.0.0.1:{TEST_PORT}")
        print(f"[test-backend] Process PID: {process.pid}")
        print(f"[test-backend] Production (port 8000) is UNTOUCHED")
        print("=" * 60)
        sys.exit(0)
    else:
        print("[test-backend] Startup verification failed. Killing process...")
        process.terminate()
        sys.exit(1)


if __name__ == "__main__":
    main()
