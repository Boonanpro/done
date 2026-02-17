"""
キャンセル状態を管理するレジストリ

セッションIDに紐づくキャンセルフラグをグローバルに管理し、
各レイヤー（SSE、Runner、Browser、Executor）でチェックする。

使用方法:
1. セッション開始時: CancellationRegistry.register(session_id)
2. 現在のセッションを設定: CancellationRegistry.set_current_session(session_id)
3. 各処理ステップで: CancellationRegistry.check_cancelled() または check_cancelled_raise()
4. キャンセル実行: CancellationRegistry.cancel(session_id)
5. セッション終了時: CancellationRegistry.unregister(session_id)
"""

import logging
import threading
import contextvars
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# コンテキスト変数で現在のセッションIDを追跡（async対応）
_current_session_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    'current_session_id', default=None
)


class CancelledError(Exception):
    """キャンセルされた時に発生する例外"""
    def __init__(self, session_id: str, message: str = "処理がキャンセルされました"):
        self.session_id = session_id
        self.message = message
        super().__init__(message)


class CancellationRegistry:
    """キャンセル状態を管理するレジストリ"""

    _instances: Dict[str, threading.Event] = {}
    _lock = threading.Lock()

    @classmethod
    def register(cls, session_id: str) -> threading.Event:
        """セッションのキャンセルフラグを登録"""
        with cls._lock:
            event = threading.Event()
            cls._instances[session_id] = event
            return event

    @classmethod
    def cancel(cls, session_id: str) -> bool:
        """セッションをキャンセル"""
        with cls._lock:
            if session_id in cls._instances:
                cls._instances[session_id].set()
                logger.info("Session %s cancelled", session_id)
                return True
            logger.warning("Session %s not found in registry", session_id)
            return False

    @classmethod
    def is_cancelled(cls, session_id: str) -> bool:
        """キャンセル状態をチェック"""
        with cls._lock:
            if session_id in cls._instances:
                return cls._instances[session_id].is_set()
            return False

    @classmethod
    def unregister(cls, session_id: str):
        """セッションを登録解除"""
        with cls._lock:
            cls._instances.pop(session_id, None)

    @classmethod
    def clear_all(cls):
        """全てのセッションを登録解除（テスト用）"""
        with cls._lock:
            cls._instances.clear()

    # ========================================
    # 現在のセッション追跡（async対応）
    # ========================================

    @classmethod
    def set_current_session(cls, session_id: Optional[str]):
        """
        現在のセッションIDを設定（コンテキスト変数）

        これにより、深い呼び出し階層からでもセッションIDを取得可能。
        asyncio対応のためcontextvarsを使用。
        """
        _current_session_id.set(session_id)

    @classmethod
    def get_current_session(cls) -> Optional[str]:
        """現在のセッションIDを取得"""
        return _current_session_id.get()

    @classmethod
    def check_cancelled(cls, session_id: Optional[str] = None) -> bool:
        """
        キャンセル状態をチェック（便利メソッド）

        session_idが指定されていない場合、現在のセッションをチェック。
        """
        if session_id is None:
            session_id = cls.get_current_session()
        if session_id is None:
            return False
        return cls.is_cancelled(session_id)

    @classmethod
    def check_cancelled_raise(cls, session_id: Optional[str] = None):
        """
        キャンセル状態をチェックし、キャンセルされていたら例外を発生

        Executor内の各ステップで呼び出すことで、キャンセル時に即座に中断。
        """
        if session_id is None:
            session_id = cls.get_current_session()
        if session_id is None:
            return
        if cls.is_cancelled(session_id):
            raise CancelledError(session_id)
