"""
Progress Callback Service
検索・実行中のプログレスをリアルタイムで通知するためのコールバック管理
"""
from typing import Callable, Optional, Awaitable
from dataclasses import dataclass
import asyncio
import logging

logger = logging.getLogger(__name__)


@dataclass
class ProgressUpdate:
    """プログレス更新の情報"""
    step: str           # ステップ識別子（例: "connecting", "loading", "extracting"）
    label: str          # 表示用ラベル（例: "スカイスキャナーに接続中..."）
    status: str         # ステータス（"running", "completed", "error"）
    details: Optional[dict] = None  # 追加情報


# コールバック関数の型
ProgressCallback = Callable[[ProgressUpdate], Awaitable[None]]


class ProgressCallbackRegistry:
    """
    プログレスコールバックのレジストリ
    
    タスクID（またはリクエストID）をキーにしてコールバック関数を管理
    """
    
    _callbacks: dict[str, ProgressCallback] = {}
    _queues: dict[str, asyncio.Queue] = {}
    
    @classmethod
    def register(cls, request_id: str, callback: ProgressCallback) -> None:
        """コールバック関数を登録"""
        cls._callbacks[request_id] = callback
        logger.debug(f"Registered callback for request: {request_id}")
    
    @classmethod
    def unregister(cls, request_id: str) -> None:
        """コールバック関数を解除"""
        cls._callbacks.pop(request_id, None)
        cls._queues.pop(request_id, None)
        logger.debug(f"Unregistered callback for request: {request_id}")
    
    @classmethod
    async def notify(cls, request_id: str, update: ProgressUpdate) -> None:
        """プログレス更新を通知"""
        callback = cls._callbacks.get(request_id)
        if callback:
            try:
                await callback(update)
            except Exception as e:
                logger.warning(f"Callback error for {request_id}: {e}")
        
        # キューにも追加（ポーリング用）
        queue = cls._queues.get(request_id)
        if queue:
            await queue.put(update)
    
    @classmethod
    def create_queue(cls, request_id: str) -> asyncio.Queue:
        """プログレス用のキューを作成"""
        queue = asyncio.Queue()
        cls._queues[request_id] = queue
        return queue
    
    @classmethod
    def get_queue(cls, request_id: str) -> Optional[asyncio.Queue]:
        """プログレス用のキューを取得"""
        return cls._queues.get(request_id)


# コンテキスト変数（現在のリクエストIDを保持）
_current_request_id: Optional[str] = None


def set_current_request_id(request_id: Optional[str]) -> None:
    """現在のリクエストIDを設定"""
    global _current_request_id
    _current_request_id = request_id


def get_current_request_id() -> Optional[str]:
    """現在のリクエストIDを取得"""
    return _current_request_id


async def notify_progress(step: str, label: str, status: str = "running", details: Optional[dict] = None) -> None:
    """
    プログレスを通知するヘルパー関数
    
    検索ツールなどから呼び出す
    
    Args:
        step: ステップ識別子
        label: 表示用ラベル
        status: ステータス
        details: 追加情報
    """
    request_id = get_current_request_id()
    if request_id:
        update = ProgressUpdate(step=step, label=label, status=status, details=details)
        await ProgressCallbackRegistry.notify(request_id, update)

