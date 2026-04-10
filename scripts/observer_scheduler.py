#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Observer Scheduler — 毎日JST 02:00に整理オブザーバーを実行する常駐スクリプト。

RULES.mdとlearned/の内容を整理する:
  - スキル固有のルールをRULES.mdからlearned/に移動
  - 重複ルールの統合
  - 陳腐化ルールの削除

使い方:
  python scripts/observer_scheduler.py          # フォアグラウンド実行
  python scripts/observer_scheduler.py --once   # 即座に1回実行して終了
  python scripts/observer_scheduler.py --time 03:00  # JST 03:00に変更

停止:
  Ctrl+C または taskkill /F /PID <PID>
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

JST = timezone(timedelta(hours=9))
BACKEND_URL = "http://127.0.0.1:8000/api/v1/chat/internal/observer-cleanup"

_handlers = [logging.FileHandler("observer_scheduler.log", encoding="utf-8")]
if sys.stdout is not None:
    _handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=_handlers,
)
logger = logging.getLogger(__name__)


def run_cleanup() -> bool:
    """整理オブザーバーを実行。成功ならTrue。"""
    try:
        logger.info("Sending cleanup request to backend...")
        resp = requests.post(BACKEND_URL, timeout=300)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("changes"):
                logger.info(f"Cleanup completed with changes: {data['changes']}")
            else:
                logger.info("Cleanup completed, no changes needed")
            return True
        else:
            logger.error(f"Backend returned {resp.status_code}: {resp.text}")
            return False
    except requests.ConnectionError:
        logger.error("Backend not reachable at port 8000")
        return False
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        return False


def seconds_until(target_hour: int, target_minute: int) -> float:
    """次の target_hour:target_minute (JST) までの秒数を返す。"""
    now = datetime.now(JST)
    target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def main():
    parser = argparse.ArgumentParser(description="Observer cleanup scheduler")
    parser.add_argument("--once", action="store_true", help="Run once immediately and exit")
    parser.add_argument("--time", default="02:00", help="JST execution time (HH:MM, default 02:00)")
    args = parser.parse_args()

    # parse time
    try:
        parts = args.time.split(":")
        target_hour, target_minute = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        logger.error(f"Invalid time format: {args.time} (expected HH:MM)")
        sys.exit(1)

    if args.once:
        logger.info("Running cleanup once...")
        success = run_cleanup()
        sys.exit(0 if success else 1)

    logger.info(f"Observer scheduler started. Cleanup runs daily at JST {target_hour:02d}:{target_minute:02d}")

    while True:
        wait = seconds_until(target_hour, target_minute)
        next_run = datetime.now(JST) + timedelta(seconds=wait)
        logger.info(f"Next cleanup at {next_run.strftime('%Y-%m-%d %H:%M JST')} ({int(wait)}s from now)")

        time.sleep(wait)
        run_cleanup()


if __name__ == "__main__":
    main()
