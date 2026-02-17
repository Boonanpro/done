#!/usr/bin/env python3
"""
Note投稿スケジューラーワーカー

定期的に実行し、投稿予定時刻が過ぎたスケジュールを処理する。
実行方法:
  python scripts/note_scheduler_worker.py          # 1回実行
  python scripts/note_scheduler_worker.py --loop    # 60秒間隔で繰り返し実行

投稿処理はダンのチャット経由で行う（ブラウザ操作が必要なため）。
"""

import asyncio
import logging
import sys
import os
import argparse

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.note_posting_service import NotePostingService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def process_due_schedules():
    """実行すべきスケジュールを処理"""
    service = NotePostingService()

    try:
        due_schedules = await service.get_due_schedules()
    except Exception as e:
        logger.error(f"Failed to fetch due schedules: {e}")
        return 0

    if not due_schedules:
        logger.info("No due schedules found.")
        return 0

    logger.info(f"Found {len(due_schedules)} due schedule(s).")
    processed = 0

    for schedule in due_schedules:
        schedule_id = schedule["id"]
        draft_id = schedule["draft_id"]
        title = schedule.get("draft_title", "Untitled")
        article_type = schedule.get("article_type", "free")
        price = schedule.get("price")

        logger.info(
            f"Processing schedule {schedule_id}: "
            f"'{title}' ({article_type}"
            f"{f', {price}円' if price else ''})"
        )

        try:
            # ステータスを publishing に更新
            await service.mark_schedule_publishing(schedule_id)

            # 清書済みコンテンツの確認
            user_id = schedule["user_id"]
            polished = await service.get_polished(draft_id, user_id)

            if not polished:
                # 清書がまだなら自動実行
                logger.info(f"  Auto-polishing draft {draft_id}...")
                polished = await service.execute_polish(
                    draft_id, user_id, article_type, price
                )
                logger.info(f"  Polish completed: '{polished.get('title')}'")

            # 投稿処理
            # noteにはAPIがないため、実際の投稿はブラウザ操作で行う必要がある。
            # ここではスケジュールの情報を記録し、ダンのスキルで投稿を実行させる。
            #
            # 今後の拡張: MCPツール経由でブラウザ操作を直接呼び出す
            logger.info(
                f"  Schedule {schedule_id} ready for posting. "
                f"Draft '{title}' has been polished and is waiting for browser-based posting."
            )

            # TODO: ブラウザ操作によるnote投稿を自動実行
            # 現時点ではスケジュールを failed に戻さず、publishing のままにして
            # ダンの手動トリガーを待つ
            await service.mark_schedule_failed(
                schedule_id,
                "自動投稿はブラウザ操作が必要です。ダンのチャットで投稿を依頼してください。"
            )

            processed += 1

        except Exception as e:
            logger.error(f"  Failed to process schedule {schedule_id}: {e}")
            try:
                await service.mark_schedule_failed(schedule_id, str(e))
            except Exception as e2:
                logger.error(f"  Failed to mark schedule as failed: {e2}")

    return processed


async def main(loop_mode: bool = False, interval: int = 60):
    """メイン処理"""
    if loop_mode:
        logger.info(f"Starting scheduler worker in loop mode (interval: {interval}s)")
        while True:
            try:
                processed = await process_due_schedules()
                if processed > 0:
                    logger.info(f"Processed {processed} schedule(s)")
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
            await asyncio.sleep(interval)
    else:
        processed = await process_due_schedules()
        logger.info(f"Done. Processed {processed} schedule(s).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Note Scheduler Worker")
    parser.add_argument("--loop", action="store_true", help="Run in loop mode")
    parser.add_argument("--interval", type=int, default=60, help="Loop interval in seconds")
    args = parser.parse_args()

    asyncio.run(main(loop_mode=args.loop, interval=args.interval))
