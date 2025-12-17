"""
Celery Tasks Package
"""
from app.tasks.celery_app import celery_app
from app.tasks.task_handlers import (
    process_wish_task,
    execute_browser_task,
    send_email_task,
    send_line_task,
)

__all__ = [
    "celery_app",
    "process_wish_task",
    "execute_browser_task",
    "send_email_task",
    "send_line_task",
]

