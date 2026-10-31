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
    _started_at: Dict[str, float] = {}  # セッション開始時刻
    _run_ids: Dict[str, str] = {}
    _run_events: Dict[tuple, threading.Event] = {}
    _cancelled_runs: set = set()
    _lock = threading.Lock()

    @classmethod
    def register(cls, session_id: str) -> threading.Event:
        """セッションのキャンセルフラグを登録"""
        import time
        with cls._lock:
            event = threading.Event()
            cls._instances[session_id] = event
            cls._run_ids.pop(session_id, None)
            cls._started_at[session_id] = time.time()
            return event

    @classmethod
    def bind_run(cls, session_id: str, event: threading.Event, run_id: str) -> bool:
        """Bind only the registration captured by the caller, never a successor."""
        if not run_id or event is None:
            return False
        with cls._lock:
            if cls._instances.get(session_id) is not event:
                return False
            previous = cls._run_ids.get(session_id)
            if previous is not None and previous != run_id:
                return False
            cls._run_ids[session_id] = run_id
            return True

    @classmethod
    def register_run(cls, session_id: str, run_id: str) -> threading.Event:
        """An execution scope independent of a room's replaceable registration."""
        with cls._lock:
            key = (session_id, run_id)
            if key in cls._run_events:
                raise RuntimeError('この作業は既に実行中です')
            event = threading.Event()
            if key in cls._cancelled_runs:
                event.set()
            cls._run_events[key] = event
            return event

    @classmethod
    def unregister_run(cls, session_id: str, run_id: str, event: threading.Event):
        with cls._lock:
            key = (session_id, run_id)
            if cls._run_events.get(key) is event:
                cls._run_events.pop(key, None)

    @classmethod
    def cancel_run(cls, session_id: str, run_id: str) -> bool:
        """Close this run's cooperative tool gate. This is not a process-exit ack."""
        if not run_id:
            return False
        with cls._lock:
            event = cls._run_events.get((session_id, run_id))
            room_event = (cls._instances.get(session_id)
                          if cls._run_ids.get(session_id) == run_id else None)
            if event is None and room_event is None:
                return False
            if event is not None:
                event.set()
            if room_event is not None:
                room_event.set()
            cls._cancelled_runs.add((session_id, run_id))
            return True

    @classmethod
    def is_run_cancelled(cls, session_id: str, run_id: Optional[str]) -> bool:
        # Retries retain the run even when a newer room Event replaces it.
        with cls._lock:
            return bool(run_id and (session_id, run_id) in cls._cancelled_runs)

    @classmethod
    def mark_matched_run_cancelled(cls, session_id: str, run_id: str):
        """Only an execution handle which matched the run may call this.

        Keep its retry prohibition even if the room now belongs to a new run;
        never set the replacement run's cooperative cancellation Event.
        """
        if not run_id:
            return
        with cls._lock:
            cls._cancelled_runs.add((session_id, run_id))
            event = cls._run_events.get((session_id, run_id))
            if event is not None:
                event.set()
            if cls._run_ids.get(session_id) == run_id:
                event = cls._instances.get(session_id)
                if event is not None:
                    event.set()

    @classmethod
    def check_run_cancelled_raise(cls, session_id: str, run_id: Optional[str]):
        if cls.is_run_cancelled(session_id, run_id):
            raise CancelledError(session_id)

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
    def get_event(cls, session_id: str) -> Optional[threading.Event]:
        """現在のEventオブジェクト参照を返す"""
        with cls._lock:
            return cls._instances.get(session_id)

    @classmethod
    def unregister(cls, session_id: str):
        """セッションを登録解除"""
        with cls._lock:
            cls._instances.pop(session_id, None)
            cls._started_at.pop(session_id, None)
            cls._run_ids.pop(session_id, None)

    @classmethod
    def unregister_if_match(cls, session_id: str, event: threading.Event):
        """保持中のEventと一致する場合のみ登録解除（旧スレッドが新スレッドのEventを消さないようにする）"""
        with cls._lock:
            if cls._instances.get(session_id) is event:
                cls._instances.pop(session_id, None)
                cls._started_at.pop(session_id, None)
                cls._run_ids.pop(session_id, None)

    @classmethod
    def clear_all(cls):
        """全てのセッションを登録解除（テスト用）"""
        with cls._lock:
            cls._instances.clear()
            cls._started_at.clear()
            cls._run_ids.clear()
            cls._run_events.clear()
            cls._cancelled_runs.clear()

    @classmethod
    def is_active(cls, session_id: str) -> bool:
        """セッションが実行中か（登録済み かつ 未キャンセル）"""
        with cls._lock:
            if session_id not in cls._instances:
                return False
            return not cls._instances[session_id].is_set()

    @classmethod
    def get_active_info(cls, session_id: str) -> Optional[dict]:
        """セッションの実行情報を返す（非アクティブならNone）"""
        with cls._lock:
            if session_id not in cls._instances:
                return None
            if cls._instances[session_id].is_set():
                return None  # キャンセル済み
            return {
                "active": True,
                "started_at": cls._started_at.get(session_id),
            }

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
