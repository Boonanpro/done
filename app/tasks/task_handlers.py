"""
Celery Task Handlers
"""
from celery import shared_task
from typing import Optional, Any
import asyncio

from app.tasks.celery_app import celery_app


def run_async(coro):
    """非同期関数を同期的に実行するヘルパー"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, max_retries=3)
def process_wish_task(
    self,
    wish: str,
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    ユーザーの願望を非同期で処理するタスク
    
    Args:
        wish: ユーザーの願望
        user_id: ユーザーID
        
    Returns:
        処理結果
    """
    try:
        from app.agent.agent import AISecretaryAgent
        
        agent = AISecretaryAgent()
        result = run_async(agent.process_wish(wish=wish, user_id=user_id))
        
        return {
            "status": "success",
            "task_id": result["task_id"],
            "message": result["message"],
            "proposed_actions": result["proposed_actions"],
            "requires_confirmation": result["requires_confirmation"],
        }
    except Exception as e:
        # リトライ
        self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=2)
def execute_browser_task(
    self,
    action: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """
    ブラウザ操作タスク
    
    Args:
        action: 実行するアクション（browse, fill, click, screenshot）
        params: アクションのパラメータ
        
    Returns:
        実行結果
    """
    try:
        from app.tools.browser import (
            browse_website,
            fill_form,
            click_element,
            take_screenshot,
        )
        
        actions = {
            "browse": browse_website,
            "fill": fill_form,
            "click": click_element,
            "screenshot": take_screenshot,
        }
        
        if action not in actions:
            return {"status": "error", "message": f"Unknown action: {action}"}
        
        tool = actions[action]
        result = run_async(tool.ainvoke(params))
        
        return {"status": "success", "result": result}
    except Exception as e:
        self.retry(exc=e, countdown=30)


@celery_app.task(bind=True, max_retries=3)
def send_email_task(
    self,
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
) -> dict[str, Any]:
    """
    メール送信タスク
    
    Args:
        to: 宛先
        subject: 件名
        body: 本文
        cc: CC
        
    Returns:
        送信結果
    """
    try:
        from app.tools.email_tool import send_email
        
        result = run_async(send_email.ainvoke({
            "to": to,
            "subject": subject,
            "body": body,
            "cc": cc,
        }))
        
        return {"status": "success", "result": result}
    except Exception as e:
        self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def send_line_task(
    self,
    user_id: str,
    message: str,
) -> dict[str, Any]:
    """
    LINEメッセージ送信タスク
    
    Args:
        user_id: LINE ユーザーID
        message: メッセージ
        
    Returns:
        送信結果
    """
    try:
        from app.tools.line_tool import send_line_message
        
        result = run_async(send_line_message.ainvoke({
            "user_id": user_id,
            "message": message,
        }))
        
        return {"status": "success", "result": result}
    except Exception as e:
        self.retry(exc=e, countdown=30)


@celery_app.task
def cleanup_old_tasks() -> dict[str, Any]:
    """
    古いタスクをクリーンアップする定期タスク
    """
    # TODO: 古いタスクの削除処理
    return {"status": "success", "message": "Cleanup completed"}


# Celery Beatスケジュール（定期タスク）を追加
celery_app.conf.beat_schedule = celery_app.conf.beat_schedule or {}
celery_app.conf.beat_schedule.update({
    "cleanup-old-tasks-daily": {
        "task": "app.tasks.task_handlers.cleanup_old_tasks",
        "schedule": 86400.0,  # 24時間ごと
    },
})

