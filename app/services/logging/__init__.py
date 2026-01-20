"""
Logging Service - エラー追跡とログ管理

ダンが自身の実行ログを追跡するための共通基盤。
"""

from app.services.logging.error_tracker import (
    ErrorTracker,
    LogEntry,
    capture_error,
    get_recent_errors,
    get_error_tracker,
    format_errors_for_diagnosis,
)

__all__ = [
    "ErrorTracker",
    "LogEntry",
    "capture_error",
    "get_recent_errors",
    "get_error_tracker",
    "format_errors_for_diagnosis",
]
