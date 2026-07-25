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
from pathlib import Path

DAN_CORE_PORT = 9000
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ウィンドウ無しの親(タスクスケジューラ/pythonw/watchdog)から呼ばれても
# 子コンソールの可視ウィンドウを作らせない。
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


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


def _ensure_git_hooks_installed() -> None:
    """Activate .githooks/ for this clone (mixed-scope guard etc.). Idempotent."""
    try:
        subprocess.run(
            [sys.executable, "scripts/install_git_hooks.py"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_NO_WINDOW,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[dan-core] WARN: install_git_hooks failed (non-fatal): {e}")


def main() -> None:
    print("=" * 60)
    print(f"Dan Core Startup (port {DAN_CORE_PORT})")
    print("=" * 60)

    _ensure_git_hooks_installed()

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
        # --reload は使わない。ダンコアは「不変・再起動しない」プロセス。
        # --reload はリポジトリ全体を監視するため、auto_deploy の git pull
        # (サンドボックス系ファイル含む) で reload 連鎖が発生し、Windows の
        # コンソールグループのシグナル伝播レースでワーカーが wedge する。
        # (2026-05-19 障害: ワーカーが KeyboardInterrupt を拾い port 9000 で停止)
        # コア自体のコード変更時はこのスクリプトで手動再起動する。
    ]
    clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    log_path = PROJECT_ROOT / "dan_core.log"
    log_file = open(log_path, "w", encoding="utf-8")
    process = subprocess.Popen(
        cmd, cwd=str(PROJECT_ROOT), stdout=log_file, stderr=subprocess.STDOUT, env=clean_env,
        creationflags=_NO_WINDOW,
    )
    print(f"[dan-core] uvicorn started with PID {process.pid}")

    # Wait for health
    for i in range(15):
        if check_health(DAN_CORE_PORT):
            print(f"[dan-core] SUCCESS! Running on http://127.0.0.1:{DAN_CORE_PORT}")
            print(f"[dan-core] Process PID: {process.pid}")
            print(f"[dan-core] Logs: {log_path}")
            sys.exit(0)
        print(f"  Waiting for dan-core... ({i + 1}/15)")
        time.sleep(1)

    print("[dan-core] ERROR: did not become healthy within 15s.")
    process.terminate()
    sys.exit(1)


if __name__ == "__main__":
    main()
