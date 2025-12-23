"""
Celery Application Configuration
"""
from celery import Celery
from celery.schedules import crontab

from app.config import settings

# Celeryアプリケーションを作成
celery_app = Celery(
    "ai_secretary",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.task_handlers", "app.tasks.payment_tasks"],
)

# Celery設定
celery_app.conf.update(
    # タスクのシリアライズ設定
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    
    # タイムゾーン
    timezone="Asia/Tokyo",
    enable_utc=True,
    
    # タスクの結果保持期間（1日）
    result_expires=86400,
    
    # タスクの再試行設定
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    
    # 同時実行数
    worker_concurrency=4,
    
    # タスクのタイムアウト（5分）
    task_time_limit=300,
    task_soft_time_limit=240,
    
    # 優先度キュー
    task_queues={
        "default": {
            "exchange": "default",
            "routing_key": "default",
        },
        "high_priority": {
            "exchange": "high_priority",
            "routing_key": "high_priority",
        },
        "browser_tasks": {
            "exchange": "browser_tasks",
            "routing_key": "browser_tasks",
        },
    },
    task_default_queue="default",
    
    # タスクルーティング
    task_routes={
        "app.tasks.task_handlers.execute_browser_task": {"queue": "browser_tasks"},
        "app.tasks.task_handlers.process_wish_task": {"queue": "high_priority"},
        "app.tasks.payment_tasks.execute_single_payment": {"queue": "browser_tasks"},
    },
    
    # Celery Beat スケジュール（定期実行タスク）
    beat_schedule={
        # 5分毎にスケジュールされた支払いをチェック
        "check-scheduled-payments": {
            "task": "app.tasks.payment_tasks.check_scheduled_payments",
            "schedule": crontab(minute="*/5"),  # 5分毎
        },
    },
)


# Celeryワーカー起動コマンド:
# celery -A app.tasks.celery_app worker --loglevel=info --pool=solo
#
# Windows では --pool=solo が必要
# 
# 優先度別ワーカー:
# celery -A app.tasks.celery_app worker --loglevel=info --pool=solo -Q high_priority
# celery -A app.tasks.celery_app worker --loglevel=info --pool=solo -Q browser_tasks
#
# Celery Beat（定期タスク）起動コマンド:
# celery -A app.tasks.celery_app beat --loglevel=info
#
# ワーカーとBeatを同時に起動（開発用）:
# celery -A app.tasks.celery_app worker --beat --loglevel=info --pool=solo

