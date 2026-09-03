# -*- coding: utf-8 -*-
"""フロントのコード変更を検知して、ダンのUIを自動スクショする常駐ウォッチャー。

ユーザーは何もしない。frontend/src (成果物を除く) のファイルが変わり、
3分以上静かになったら scripts/ui_snapshot.py --auto を裏で実行する。
--auto は全ページを撮って「前回から見た目が変わった画面だけ」保存するので、
UIの試行錯誤が起きた時だけ shots/ に痕跡が増える。
保険として毎日21:00の DanUiSnapshot タスクも回る (こちらは無条件保存)。
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

POLL_INTERVAL = int(os.environ.get("DAN_UI_WATCH_INTERVAL", "300"))   # 5分
QUIET_SECONDS = 180        # 変更が止まってから撮るまでの猶予 (編集途中の姿を量産しない)
MIN_GAP = 1200             # 撮影と撮影の間は最低20分あける

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_WATCH_DIRS = [_PROJECT_ROOT / "frontend" / "src"]
_EXCLUDE_PARTS = ("artifacts", "demo", "scratch", "api")
_SNAPSHOT_SCRIPT = _PROJECT_ROOT / "scripts" / "ui_snapshot.py"
_MARKER = Path(os.environ.get("DAN_ARCHIVE_ROOT") or "D:/dan-archive") / "story" / "shots" / ".last_auto"

_started = False
_task: Optional["asyncio.Task"] = None


def _latest_mtime() -> float:
    latest = 0.0
    for root in _WATCH_DIRS:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            parts = Path(dirpath).parts
            if any(x in parts for x in _EXCLUDE_PARTS):
                dirnames[:] = []
                continue
            for f in filenames:
                try:
                    m = os.path.getmtime(os.path.join(dirpath, f))
                    if m > latest:
                        latest = m
                except OSError:
                    pass
    return latest


def _read_marker() -> float:
    try:
        return float(_MARKER.read_text().strip())
    except Exception:
        return 0.0


def _shoot_sync(mtime: float) -> None:
    try:
        r = subprocess.run(
            [sys.executable, str(_SNAPSHOT_SCRIPT), "--auto"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=600, cwd=str(_PROJECT_ROOT),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        _MARKER.parent.mkdir(parents=True, exist_ok=True)
        _MARKER.write_text(str(mtime))
        tail = (r.stdout or "").strip().splitlines()
        logger.info("ui snapshot auto: %s", tail[-1] if tail else r.returncode)
    except Exception as e:
        logger.warning("ui snapshot auto failed: %s", e)


async def watcher_loop() -> None:
    await asyncio.sleep(120)  # コア起動直後は避ける
    last_shot_at = 0.0
    while True:
        try:
            mtime = await asyncio.to_thread(_latest_mtime)
            now = time.time()
            if (mtime > _read_marker()
                    and now - mtime >= QUIET_SECONDS
                    and now - last_shot_at >= MIN_GAP):
                await asyncio.to_thread(_shoot_sync, mtime)
                last_shot_at = time.time()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("ui watcher cycle failed: %s", e)
        await asyncio.sleep(POLL_INTERVAL)


def start_watcher() -> Optional["asyncio.Task"]:
    global _started, _task
    if _started:
        return _task
    if os.environ.get("DAN_UI_WATCHER_ENABLED", "1") != "1":
        logger.info("ui watcher disabled by env")
        return None
    _started = True
    _task = asyncio.create_task(watcher_loop())
    logger.info("ui snapshot watcher started (interval=%ss)", POLL_INTERVAL)
    return _task
