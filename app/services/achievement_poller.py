# -*- coding: utf-8 -*-
"""「今日やったこと」ポーラー (ダンコア常駐)。

既定 5 分おきに daily_achievements_service.run_cycle() を回す。
ダンのターン完了時 (cli_runner の result 処理) に notify_activity() が呼ばれると
次の周期を待たずに数秒後に判定する = ダンの部屋はほぼリアルタイム、CLI/git は最大5分遅れ。
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

POLL_INTERVAL = int(os.environ.get("DAN_ACHIEVEMENT_POLL_INTERVAL", "300"))
WAKE_DEBOUNCE = 8  # ターン完了通知から判定までの猶予 (メッセージ保存を待つ)
ILLUST_ENABLED = os.environ.get("DAN_ACHIEVEMENT_ILLUST", "1") == "1"
ILLUST_PER_CYCLE = int(os.environ.get("DAN_ACHIEVEMENT_ILLUST_PER_CYCLE", "3"))

_started = False
_task: Optional["asyncio.Task"] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_wake: Optional[asyncio.Event] = None
_lock: Optional[asyncio.Lock] = None
_last_stats: Optional[dict] = None
_last_error: Optional[str] = None
_cycles = 0


def status() -> dict:
    return {"started": _started, "interval": POLL_INTERVAL, "cycles": _cycles,
            "last_stats": _last_stats, "last_error": _last_error}


def notify_activity() -> None:
    """スレッドからも呼べる: 次サイクルを前倒しする。"""
    if _loop is None or _wake is None:
        return
    try:
        _loop.call_soon_threadsafe(_wake.set)
    except Exception:
        pass


async def run_once(force: bool = False) -> dict:
    """1サイクル実行 (API の手動再判定からも使う)。同時実行はロックで直列化。"""
    global _last_stats, _last_error, _cycles
    from app.services.daily_achievements_service import run_cycle
    lock = _lock or asyncio.Lock()
    async with lock:
        _cycles += 1
        try:
            _last_stats = await asyncio.to_thread(run_cycle, force)
            _last_error = _last_stats.get("error")
            if ILLUST_ENABLED:
                # 成果行の挿絵は判定とは別の後追い (失敗しても判定結果には影響しない)
                try:
                    from app.services.daily_achievements_service import generate_missing_illustrations, today_jst
                    _last_stats["illustrated"] = await asyncio.to_thread(
                        generate_missing_illustrations, today_jst(), ILLUST_PER_CYCLE)
                except Exception as e:
                    logger.warning("illustration step failed: %s", e)
            return _last_stats
        except Exception as e:
            _last_error = f"{type(e).__name__}: {e}"
            raise


async def poller_loop() -> None:
    global _wake
    assert _wake is not None
    await asyncio.sleep(20)  # コア起動直後の負荷を避ける
    while True:
        try:
            try:
                await asyncio.wait_for(_wake.wait(), timeout=POLL_INTERVAL)
                _wake.clear()
                await asyncio.sleep(WAKE_DEBOUNCE)
                _wake.clear()
            except asyncio.TimeoutError:
                pass
            stats = await run_once()
            if stats.get("judged"):
                logger.info("achievement cycle: %s", stats)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("achievement poller cycle failed: %s", e)
            await asyncio.sleep(30)


def start_poller() -> Optional["asyncio.Task"]:
    global _started, _task, _loop, _wake, _lock
    if _started:
        return _task
    if os.environ.get("DAN_ACHIEVEMENT_POLLER_ENABLED", "1") != "1":
        logger.info("achievement poller disabled by env")
        return None
    _started = True
    _loop = asyncio.get_event_loop()
    _wake = asyncio.Event()
    _lock = asyncio.Lock()
    _task = asyncio.create_task(poller_loop())
    logger.info("achievement poller started (interval=%ss)", POLL_INTERVAL)
    return _task
