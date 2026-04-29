#!/usr/bin/env python3
"""
Auto-deploy script — GitHub mainブランチの変更を検知して自動反映。

外出先からスマホのClaude Appで開発し、mainにpushされたコードを
自宅PCに自動で反映する。

仕組み:
  1. 30秒ごとに git fetch origin main
  2. ローカルHEADとorigin/mainを比較
  3. 差分があれば git pull
  4. Pythonファイル変更時は start_backend.py で明示的に再起動
  5. フロントエンドは Next.js HMR が自動でリロード
  6. requirements.txt/package.json が変わった場合は pip install/npm install

使い方:
  python scripts/auto_deploy.py          # フォアグラウンド実行
  python scripts/auto_deploy.py --bg     # バックグラウンド実行（ログはdeploy.logへ）
  python scripts/auto_deploy.py --once   # 1回だけチェックして終了

停止:
  Ctrl+C または taskkill /F /PID <PID>
"""

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_DIR = Path("D:/done")
FRONTEND_DIR = REPO_DIR / "frontend"
LOG_FILE = REPO_DIR / "deploy.log"
LAST_DEPLOY_FILE = REPO_DIR / ".last_deploy_hash"
POLL_INTERVAL = 30  # seconds


def setup_logging(to_file: bool = False):
    handlers = []
    if to_file:
        handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8"))
    else:
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [deploy] %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def run(cmd: list[str], cwd: Path = REPO_DIR, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
        creationflags=_NO_WINDOW,
    )


def get_local_head() -> str:
    r = run(["git", "rev-parse", "HEAD"])
    return r.stdout.strip()


def get_remote_head() -> str:
    r = run(["git", "rev-parse", "origin/main"])
    return r.stdout.strip()


def git_fetch() -> bool:
    r = run(["git", "fetch", "origin", "main"], timeout=30)
    if r.returncode != 0:
        logging.warning(f"git fetch failed: {r.stderr.strip()}")
        return False
    return True


def git_pull() -> bool:
    r = run(["git", "pull", "origin", "main", "--ff-only"], timeout=30)
    if r.returncode != 0:
        logging.error(f"git pull failed: {r.stderr.strip()}")
        logging.error("Merge conflict or dirty working tree? Skipping this cycle.")
        return False
    logging.info(f"git pull: {r.stdout.strip()}")
    return True


def get_changed_files(old_head: str, new_head: str) -> list[str]:
    r = run(["git", "diff", "--name-only", old_head, new_head])
    if r.returncode != 0:
        return []
    return [f.strip() for f in r.stdout.strip().split("\n") if f.strip()]


def pip_install():
    logging.info("requirements.txt changed → running pip install...")
    r = run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"],
        timeout=120,
    )
    if r.returncode == 0:
        logging.info("pip install completed.")
    else:
        logging.error(f"pip install failed: {r.stderr.strip()}")


def npm_install():
    logging.info("package.json changed → running npm install...")
    r = run(["npm", "install"], cwd=FRONTEND_DIR, timeout=120)
    if r.returncode == 0:
        logging.info("npm install completed.")
    else:
        logging.error(f"npm install failed: {r.stderr.strip()}")


DAN_CORE_URL = "http://127.0.0.1:9000"


def restart_backend():
    """
    アプリサンドボックスを再起動する。

    新アーキ: ダンコア (port 9000) の /api/v1/sandbox/restart を叩く。
    ダンコア自体は再起動しないので、チャットセッションは維持される。

    旧アーキ (ダンコア未起動) フォールバック: start_backend.py を実行。
    """
    import urllib.error
    import urllib.request

    # まずダンコア経由で試す
    try:
        req = urllib.request.Request(
            f"{DAN_CORE_URL}/api/v1/sandbox/restart",
            method="POST",
            headers={"User-Agent": "auto_deploy.py"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 200:
                logging.info("Sandbox restarted via dan_core.")
                return
    except (urllib.error.URLError, ConnectionRefusedError, TimeoutError) as e:
        logging.warning(
            "dan_core unreachable (%s) — falling back to legacy start_backend.py",
            e,
        )

    # フォールバック: 旧 start_backend.py
    logging.info("Restarting backend via start_backend.py (legacy)...")
    r = run([sys.executable, "scripts/start_backend.py"], timeout=60)
    if r.returncode == 0:
        logging.info("Backend restarted (legacy).")
    else:
        logging.error(f"Backend restart failed: {r.stderr.strip()}")


def get_last_deploy_hash() -> str:
    """Return the commit hash from last successful deploy."""
    if LAST_DEPLOY_FILE.exists():
        return LAST_DEPLOY_FILE.read_text().strip()
    return ""


def save_last_deploy_hash(commit_hash: str) -> None:
    """Record the commit hash after a successful deploy."""
    LAST_DEPLOY_FILE.write_text(commit_hash)


def check_and_deploy() -> bool:
    """1回のチェック＆デプロイサイクル。変更があればTrueを返す。"""
    if not git_fetch():
        return False

    local = get_local_head()
    remote = get_remote_head()

    # Pull remote changes if any
    if local != remote:
        logging.info(f"Remote changes detected: {local[:8]} → {remote[:8]}")
        if not git_pull():
            return False

    # Compare current HEAD against last deployed hash
    current_head = get_local_head()
    last_deploy = get_last_deploy_hash()

    if current_head == last_deploy:
        return False

    if not last_deploy:
        # First run: record current state without restarting
        logging.info(f"First run, recording current HEAD: {current_head[:8]}")
        save_last_deploy_hash(current_head)
        return False

    logging.info(f"New commits since last deploy: {last_deploy[:8]} → {current_head[:8]}")
    changed = get_changed_files(last_deploy, current_head)
    logging.info(f"Changed files ({len(changed)}): {', '.join(changed[:10])}")

    # 依存関係の変更を検知
    needs_pip = any(f == "requirements.txt" for f in changed)
    needs_npm = any(f.startswith("frontend/package") for f in changed)

    if needs_pip:
        pip_install()
        restart_backend()

    if needs_npm:
        npm_install()
        # Next.js dev server will pick up new dependencies on next HMR cycle

    if not needs_pip:
        # uvicorn --reload はWindows上で機能しないため、Pythonファイル変更時は明示的に再起動
        py_changed = [f for f in changed if f.endswith(".py")]
        if py_changed:
            logging.info(f"Python files changed ({len(py_changed)}) → restarting backend")
            restart_backend()

    ts_changed = [f for f in changed if f.endswith((".ts", ".tsx", ".js", ".jsx", ".css"))]
    if ts_changed:
        logging.info(f"Frontend files changed ({len(ts_changed)}) → Next.js HMR will handle it")

    save_last_deploy_hash(current_head)
    logging.info("Deploy cycle complete.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Auto-deploy: poll GitHub and apply changes")
    parser.add_argument("--bg", action="store_true", help="Log to file instead of stdout")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL, help="Poll interval in seconds")
    args = parser.parse_args()

    setup_logging(to_file=args.bg)
    logging.info(f"Auto-deploy started (interval={args.interval}s, pid={__import__('os').getpid()})")

    if args.once:
        changed = check_and_deploy()
        logging.info("Done." if changed else "No changes.")
        return

    try:
        while True:
            try:
                check_and_deploy()
            except Exception as e:
                logging.error(f"Unexpected error: {e}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logging.info("Stopped by user.")


if __name__ == "__main__":
    main()
