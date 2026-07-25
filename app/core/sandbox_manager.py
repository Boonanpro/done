"""
SandboxManager — アプリサンドボックス（port 8000）の subprocess 管理

責務:
  - サンドボックスの起動 / 停止 / 再起動
  - ヘルスチェック（HTTP /health）
  - プロセス死亡の自動検知（オプション）
  - ログファイル管理

ダンコア起動時に SandboxManager() を1つだけ生成し、API経由で操作する。
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# コアは pythonw(ウィンドウ無し)で動くため、コンソール系の子プロセス
# (python.exe / taskkill / netstat 等)を素の Popen で起こすと Windows が
# 新しい可視コンソールを割り当ててターミナルが「勝手に開く」。
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


@dataclass
class SandboxStatus:
    pid: Optional[int]
    port: int
    running: bool
    healthy: bool
    started_at: Optional[float]
    log_path: str


class SandboxManager:
    """
    サンドボックスプロセス（uvicorn）の生存管理。

    Phase 1 では「dummy mode」をデフォルトとし、既存の port 8000 プロセスとは
    ぶつからないようにする。既存プロセスに干渉せず、新しいサンドボックスを
    別ポート（デフォルト 8002）で起動して動作確認する用途を想定。
    """

    def __init__(
        self,
        port: int = 8002,
        app_module: str = "app.sandbox.main:app",
        cwd: Optional[Path] = None,
        log_path: Optional[Path] = None,
    ) -> None:
        self.port = port
        self.app_module = app_module
        self.cwd = cwd or PROJECT_ROOT
        self.log_path = log_path or (self.cwd / "sandbox.log")
        self._proc: Optional[subprocess.Popen] = None
        self._started_at: Optional[float] = None
        self._lock = threading.Lock()
        # restart() で追加注入された env vars。次回 spawn 時に os.environ にマージされる。
        # テスト用に DAN_DEV_NO_AUTH=1 を一時的に注入したい時に使う。
        self._extra_env: dict[str, str] = {}

    # --- 公開API -----------------------------------------------------

    def status(self) -> SandboxStatus:
        running = self._is_running()
        healthy = self._check_health() if running else False
        return SandboxStatus(
            pid=self._proc.pid if self._proc else None,
            port=self.port,
            running=running,
            healthy=healthy,
            started_at=self._started_at,
            log_path=str(self.log_path),
        )

    def start(self) -> SandboxStatus:
        with self._lock:
            if self._is_running():
                logger.info("sandbox already running (PID %s)", self._proc.pid)
                return self.status()

            if not self._is_port_free(self.port):
                raise RuntimeError(
                    f"port {self.port} is occupied by another process. "
                    "Stop it before starting the sandbox."
                )

            self._proc = self._spawn()
            self._started_at = time.time()
            logger.info("sandbox started: PID %s on port %s", self._proc.pid, self.port)
            return self.status()

    def stop(self, timeout: float = 5.0) -> SandboxStatus:
        with self._lock:
            pid = self._proc.pid if self._is_running() else None
            try:
                if pid is not None:
                    self._kill_tree(pid, timeout=timeout)
                # 念のため: ポート上の残存リスナーも全部 kill
                self._kill_listeners_on_port(self.port)
            except Exception as e:
                logger.warning("error during sandbox stop: %s", e)
            finally:
                self._proc = None
                self._started_at = None
            # ポートが解放されるのを待つ（Windowsは時々遅い）
            for _ in range(20):
                if self._is_port_free(self.port):
                    break
                time.sleep(0.2)
            logger.info("sandbox stopped (was PID %s)", pid)
            return self.status()

    @staticmethod
    def _kill_tree(pid: int, timeout: float = 5.0) -> None:
        """
        プロセスツリーを丸ごと終了する。
        uvicorn --reload は multiprocessing.spawn の子プロセス（実ワーカー）を
        起こすが、それは Job Object 経由で親に紐付かないため
        taskkill /T だけでは残ることがある。parent_pid=<pid> を持つ
        Python の spawn 子も追跡して個別に kill する。
        """
        if sys.platform != "win32":
            import signal
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            return

        # まず /T でツリーごと kill
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            timeout=timeout,
            creationflags=_NO_WINDOW,
        )

        # multiprocessing spawn 子を探して個別 kill
        try:
            result = subprocess.run(
                ["wmic", "process", "where", "name='python.exe'",
                 "get", "processid,commandline"],
                capture_output=True, text=True, timeout=5,
                creationflags=_NO_WINDOW,
            )
            target = f"parent_pid={pid}"
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or "CommandLine" in line:
                    continue
                if target in line:
                    parts = line.split()
                    if parts:
                        try:
                            child_pid = int(parts[-1])
                            subprocess.run(
                                ["taskkill", "/F", "/PID", str(child_pid)],
                                capture_output=True, timeout=3,
                                creationflags=_NO_WINDOW,
                            )
                            logger.info("killed orphan spawn child PID %s (parent=%s)",
                                        child_pid, pid)
                        except ValueError:
                            pass
        except Exception as e:
            logger.warning("failed to scan for spawn children of %s: %s", pid, e)

    def restart(self, extra_env: Optional[dict[str, str]] = None) -> SandboxStatus:
        """サンドボックスを再起動。

        extra_env: 次回 spawn 時に追加注入する環境変数。テスト用に
                   DAN_DEV_NO_AUTH=1 を一時的に立てたい時に使う。None なら前回の値を維持。
                   空 dict を渡せばクリア（通常起動に戻す）。
        """
        self.stop()
        if extra_env is not None:
            self._extra_env = dict(extra_env)
        # Wait briefly for port release
        for _ in range(10):
            if self._is_port_free(self.port):
                break
            time.sleep(0.3)
        return self.start()

    def wait_until_healthy(self, timeout: float = 15.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._check_health():
                return True
            time.sleep(0.5)
        return False

    # --- 内部ヘルパ --------------------------------------------------

    def _spawn(self) -> subprocess.Popen:
        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            self.app_module,
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
        ]
        # --reload is opt-in. On Windows the uvicorn reloader hits an asyncio
        # AssertionError in ProactorEventLoop._attach during teardown and the
        # whole process tree dies without auto-recovery (2026-05-19/20
        # outages). For ordinary running we want a stable worker; code changes
        # are picked up via the explicit POST /api/v1/sandbox/restart endpoint.
        # For dev work where you want hot-reload, set DAN_SANDBOX_RELOAD=1.
        if os.environ.get("DAN_SANDBOX_RELOAD", "").lower() in ("1", "true", "yes", "on"):
            cmd.append("--reload")
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        env["DAN_SANDBOX_PORT"] = str(self.port)
        # restart で注入された extra env をマージ（テスト用認証バイパス等）
        for k, v in self._extra_env.items():
            env[k] = v

        log_file = open(self.log_path, "w", encoding="utf-8")
        return subprocess.Popen(
            cmd,
            cwd=str(self.cwd),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=_NO_WINDOW,
        )

    def _is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @staticmethod
    def _kill_listeners_on_port(port: int) -> None:
        """
        指定ポートを LISTEN しているプロセスを全部 kill する（Windows）。
        netstat -ano で PID を引いて taskkill する。
        """
        if sys.platform != "win32":
            return
        try:
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=5,
                creationflags=_NO_WINDOW,
            )
            target_pids: set[int] = set()
            needle = f":{port} "
            for line in result.stdout.splitlines():
                if needle in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        try:
                            pid = int(parts[-1])
                            if pid > 0:
                                target_pids.add(pid)
                        except ValueError:
                            pass
            for pid in target_pids:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True, timeout=3,
                    creationflags=_NO_WINDOW,
                )
                logger.info("killed orphan listener PID %s on port %s", pid, port)
        except Exception as e:
            logger.warning("failed to clean port %s listeners: %s", port, e)

    def _is_port_free(self, port: int) -> bool:
        # bind() で実際に確保できるか確認（connect_ex より確実）
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", port))
                return True
        except OSError:
            return False

    def _check_health(self, timeout: float = 2.0) -> bool:
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/health",
                headers={"User-Agent": "dan-core/sandbox-manager"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except (urllib.error.URLError, ConnectionRefusedError, TimeoutError):
            return False
        except Exception as e:
            logger.debug("health check error: %s", e)
            return False
