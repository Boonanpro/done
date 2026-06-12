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
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_DIR = Path("D:/done")
FRONTEND_DIR = REPO_DIR / "frontend"
WORKSPACE_DIR = Path.home() / ".dan" / "workspace"
LOG_FILE = REPO_DIR / "deploy.log"
LAST_DEPLOY_FILE = REPO_DIR / ".last_deploy_hash"
POLL_INTERVAL = 30  # seconds

DAN_CORE_PORT = 9000

# パスがこの prefix で始まる .py 変更は ダンコア (port 9000) を再起動する。
# サンドボックスだけ再起動しても、これらのモジュールは
# ダンコアプロセスにキャッシュされたままで反映されない。
DAN_CORE_PATH_PREFIXES = (
    "app/agent/",
    "app/core/",
    "app/services/",
)


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


def pull_workspace() -> None:
    """Pull ~/.dan/workspace (RULES.md / plans / artifacts) — read by dan-core's
    bootstrap_context on every prompt build, no restart needed.
    """
    if not WORKSPACE_DIR.exists():
        return
    try:
        run(["git", "fetch", "origin", "master"], cwd=WORKSPACE_DIR, timeout=30)
        r = run(
            ["git", "pull", "origin", "master", "--ff-only"],
            cwd=WORKSPACE_DIR,
            timeout=30,
        )
        if r.returncode == 0 and "Already up to date" not in r.stdout:
            logging.info(f"workspace pulled: {r.stdout.strip().splitlines()[0]}")
        elif r.returncode != 0:
            logging.warning(f"workspace pull failed: {r.stderr.strip()}")
    except subprocess.TimeoutExpired:
        logging.warning("workspace pull timed out")


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
    # npm は npm.cmd なので CreateProcess の素の PATH 解決では見つからない
    # (WinError 2)。例外を上に投げるとデプロイサイクル全体が中断し、
    # save_last_deploy_hash に到達せず同じ commit 範囲で無限リトライになる。
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        logging.error("npm not found in PATH — skipping npm install.")
        return
    try:
        r = run([npm, "install"], cwd=FRONTEND_DIR, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        logging.error(f"npm install failed: {e}")
        return
    if r.returncode == 0:
        logging.info("npm install completed.")
    else:
        logging.error(f"npm install failed: {r.stderr.strip()}")


DAN_CORE_URL = f"http://127.0.0.1:{DAN_CORE_PORT}"


def _find_pid_on_port(port: int) -> int | None:
    """Return the PID listening on `port`, or None if not found."""
    r = run(["netstat", "-ano"], cwd=REPO_DIR, timeout=10)
    if r.returncode != 0:
        return None
    needle = f":{port} "
    for line in r.stdout.splitlines():
        if needle in line and "LISTENING" in line.upper():
            parts = line.split()
            if parts:
                try:
                    return int(parts[-1])
                except ValueError:
                    continue
    return None


def restart_dan_core():
    """Kill dan-core (port 9000) then start a fresh process via start_dan_core.py.

    Used when files under DAN_CORE_PATH_PREFIXES change. Sandbox is auto-spawned
    by start_dan_core.py, so a single restart_dan_core() call replaces both.

    Note: this drops any in-flight chat sessions on dan-core. Acceptable cost
    since the alternative is running with stale code (the issue this fix addresses).
    """
    logging.info("Restarting dan-core (port 9000)...")
    pid = _find_pid_on_port(DAN_CORE_PORT)
    if pid:
        logging.info(f"Killing dan-core PID={pid}")
        run(["taskkill", "/F", "/PID", str(pid)], cwd=REPO_DIR, timeout=10)
        time.sleep(2)
    else:
        logging.info("No process on port 9000 — starting fresh.")

    proc = subprocess.Popen(
        [sys.executable, "scripts/start_dan_core.py"],
        cwd=str(REPO_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_NO_WINDOW,
    )
    logging.info(f"start_dan_core.py launched (wrapper PID={proc.pid})")


def reload_dan_skills():
    """ダンコアの SkillRegistry をディスクから再読込させる。

    `.claude/skills/**` が変わったが app/agent 等の .py は変わっていない時に使う。
    ディスクの SKILL.md を読み直すだけなので、ダンコアを再起動せず（＝実行中の
    チャットセッションを切らず）にスキル追加・変更を反映できる。
    """
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(
            f"{DAN_CORE_URL}/api/v1/chat/dan/skills/reload",
            method="POST",
            headers={"User-Agent": "auto_deploy.py"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                logging.info("Dan skills reloaded via dan_core (no restart).")
                return
    except (urllib.error.URLError, ConnectionRefusedError, TimeoutError) as e:
        logging.warning("dan_core skill reload failed (%s) — skills may be stale until next core restart.", e)


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
    # workspace は dan-core の bootstrap が毎回ディスクから読むので、
    # 再起動なしで反映される。done と並行で同期する。
    pull_workspace()

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

    # ダンコアを再起動したかどうか（再起動すれば SkillRegistry はフレッシュに
    # 再ロードされるので、別途のスキル reload は不要になる）
    dan_core_restarted = False

    if not needs_pip:
        # uvicorn --reload はWindows上で機能しないため、Pythonファイル変更時は明示的に再起動
        py_changed = [f for f in changed if f.endswith(".py")]
        if py_changed:
            dan_core_changed = [
                f for f in py_changed
                if f.startswith(DAN_CORE_PATH_PREFIXES)
            ]
            if dan_core_changed:
                logging.info(
                    f"Dan-core code changed ({len(dan_core_changed)}/{len(py_changed)} py files): "
                    f"{', '.join(dan_core_changed[:5])} → restarting dan-core"
                )
                restart_dan_core()
                dan_core_restarted = True
            else:
                logging.info(f"Sandbox-only py changed ({len(py_changed)}) → restarting sandbox")
                restart_backend()

    # スキル定義 (.claude/skills/**) の変更は .py ではないので上の分岐に乗らない。
    # ダンコアの SkillRegistry は起動時固定なので、再起動していない時だけ
    # reload エンドポイントを叩いてディスクから読み直させる（セッション維持）。
    skills_changed = [f for f in changed if f.startswith(".claude/skills/")]
    if skills_changed and not dan_core_restarted:
        logging.info(
            f"Skill definitions changed ({len(skills_changed)}): "
            f"{', '.join(skills_changed[:5])} → reloading dan-core SkillRegistry"
        )
        reload_dan_skills()

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
