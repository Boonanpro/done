#!/usr/bin/env python3
"""
ダンコア起動スクリプト — port 9000 で uvicorn を起動する。

Phase 1 では既存の port 8000 (main.py) と並走することを想定。
既存プロセスは一切触らず、port 9000 にだけ干渉する。

使い方:
    python scripts/start_dan_core.py
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

DAN_CORE_PORT = 9000


def is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def check_health(port: int, timeout: int = 3) -> bool:
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/health",
            headers={"User-Agent": "start_dan_core.py"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def main() -> None:
    print("=" * 60)
    print(f"Dan Core Startup (port {DAN_CORE_PORT})")
    print("=" * 60)

    if not is_port_free(DAN_CORE_PORT):
        print(f"[dan-core] ERROR: port {DAN_CORE_PORT} is already in use.")
        print(f"[dan-core] Run: netstat -ano | findstr :{DAN_CORE_PORT}")
        sys.exit(1)

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.core.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(DAN_CORE_PORT),
        "--reload",
    ]
    clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    log_file = open("D:/done/dan_core.log", "w", encoding="utf-8")
    process = subprocess.Popen(
        cmd, cwd="D:/done", stdout=log_file, stderr=subprocess.STDOUT, env=clean_env
    )
    print(f"[dan-core] uvicorn started with PID {process.pid}")

    # Wait for health
    for i in range(15):
        if check_health(DAN_CORE_PORT):
            print(f"[dan-core] SUCCESS! Running on http://127.0.0.1:{DAN_CORE_PORT}")
            print(f"[dan-core] Process PID: {process.pid}")
            print(f"[dan-core] Logs: D:/done/dan_core.log")
            sys.exit(0)
        print(f"  Waiting for dan-core... ({i + 1}/15)")
        time.sleep(1)

    print("[dan-core] ERROR: did not become healthy within 15s.")
    process.terminate()
    sys.exit(1)


if __name__ == "__main__":
    main()
