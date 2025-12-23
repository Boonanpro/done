"""
Gmail Tasks - Phase 5B: 定期メール同期タスク
"""
import logging
import asyncio
from typing import List

from app.tasks.celery_app import celery_app
from app.services.supabase_client import get_supabase_client
from app.services.gmail_service import get_gmail_service
from app.services.attachment_service import get_attachment_service
from app.config import settings

logger = logging.getLogger(__name__)


@celery_app.task(name="gmail.sync_all_users")
def sync_all_users_gmail():
    """
    全ユーザーのGmailを同期
    
    Celery Beatで定期実行（5分毎）
    """
    logger.info("Starting Gmail sync for all users")
    
    # 非同期関数をCeleryタスクから呼び出す
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(_sync_all_users_gmail_async())
        return result
    finally:
        loop.close()


async def _sync_all_users_gmail_async() -> dict:
    """
    全ユーザーのGmail同期（非同期）
    """
    supabase = get_supabase_client().client
    gmail_service = get_gmail_service()
    
    # アクティブなGmail接続を取得
    connections = supabase.table("gmail_connections").select(
        "user_id, email"
    ).eq("is_active", True).execute()
    
    if not connections.data:
        logger.info("No active Gmail connections")
        return {"synced_users": 0, "new_messages": 0}
    
    total_new_messages = 0
    synced_users = 0
    errors = []
    
    for conn in connections.data:
        try:
            user_id = conn["user_id"]
            new_count, _ = await gmail_service.sync_emails(user_id, max_results=50)
            total_new_messages += new_count
            synced_users += 1
            
            if new_count > 0:
                logger.info(f"Synced {new_count} new messages for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to sync Gmail for user {conn['user_id']}: {e}")
            errors.append({"user_id": conn["user_id"], "error": str(e)})
    
    logger.info(f"Gmail sync completed: {synced_users} users, {total_new_messages} new messages")
    
    return {
        "synced_users": synced_users,
        "new_messages": total_new_messages,
        "errors": errors,
    }


@celery_app.task(name="gmail.sync_user")
def sync_user_gmail(user_id: str, max_results: int = 50):
    """
    特定ユーザーのGmailを同期
    """
    logger.info(f"Starting Gmail sync for user {user_id}")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(_sync_user_gmail_async(user_id, max_results))
        return result
    finally:
        loop.close()


async def _sync_user_gmail_async(user_id: str, max_results: int) -> dict:
    """
    特定ユーザーのGmail同期（非同期）
    """
    gmail_service = get_gmail_service()
    
    try:
        new_count, message_ids = await gmail_service.sync_emails(user_id, max_results)
        return {
            "success": True,
            "new_messages": new_count,
            "message_ids": message_ids,
        }
    except Exception as e:
        logger.error(f"Failed to sync Gmail for user {user_id}: {e}")
        return {
            "success": False,
            "error": str(e),
        }


@celery_app.task(name="gmail.download_attachments")
def download_attachments(user_id: str, detected_message_id: str):
    """
    検知メッセージの添付ファイルをダウンロード
    """
    logger.info(f"Downloading attachments for message {detected_message_id}")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            _download_attachments_async(user_id, detected_message_id)
        )
        return result
    finally:
        loop.close()


async def _download_attachments_async(user_id: str, detected_message_id: str) -> dict:
    """
    添付ファイルダウンロード（非同期）
    """
    attachment_service = get_attachment_service()
    
    try:
        attachments = await attachment_service.download_gmail_attachments(
            user_id=user_id,
            detected_message_id=detected_message_id,
        )
        return {
            "success": True,
            "downloaded_count": len(attachments),
            "attachment_ids": [a["id"] for a in attachments],
        }
    except Exception as e:
        logger.error(f"Failed to download attachments: {e}")
        return {
            "success": False,
            "error": str(e),
        }


@celery_app.task(name="gmail.cleanup_old_attachments")
def cleanup_old_attachments(days: int = 30):
    """
    古い添付ファイルを削除
    """
    logger.info(f"Cleaning up attachments older than {days} days")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(_cleanup_old_attachments_async(days))
        return result
    finally:
        loop.close()


async def _cleanup_old_attachments_async(days: int) -> dict:
    """
    古い添付ファイル削除（非同期）
    """
    attachment_service = get_attachment_service()
    
    try:
        deleted_count = await attachment_service.cleanup_old_attachments(days)
        logger.info(f"Deleted {deleted_count} old attachments")
        return {
            "success": True,
            "deleted_count": deleted_count,
        }
    except Exception as e:
        logger.error(f"Failed to cleanup attachments: {e}")
        return {
            "success": False,
            "error": str(e),
        }


# Celery Beat スケジュール設定
celery_app.conf.beat_schedule = celery_app.conf.beat_schedule or {}
celery_app.conf.beat_schedule.update({
    'gmail-sync-every-5-minutes': {
        'task': 'gmail.sync_all_users',
        'schedule': settings.GMAIL_POLL_INTERVAL_SECONDS,  # デフォルト5分
    },
    'cleanup-attachments-daily': {
        'task': 'gmail.cleanup_old_attachments',
        'schedule': 86400,  # 24時間
        'args': (30,),  # 30日以上古いファイルを削除
    },
})







