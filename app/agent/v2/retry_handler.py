"""
セッション切れ自動再試行ハンドラ

ブラウザ自動化でセッション切れが発生した際、自動で再ログイン→元の操作を再試行する。

使用方法:
    result = await with_session_retry(
        executor=executor,
        operation=lambda: executor.search(params, credentials, user_id),
        credentials=credentials,
        user_id=user_id,
    )
"""

import logging
import asyncio
from typing import Any, Callable, Awaitable, Optional, Dict, TypeVar

from app.tools.browser import get_executor_page

logger = logging.getLogger(__name__)

# リトライ設定
MAX_RETRY_ATTEMPTS = 3
INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 10.0
BACKOFF_MULTIPLIER = 2.0

T = TypeVar("T")


async def with_session_retry(
    executor: Any,
    operation: Callable[[], Awaitable[T]],
    credentials: Optional[Dict[str, str]] = None,
    user_id: Optional[str] = None,
) -> T:
    """
    セッション切れ時に自動再ログイン→再試行を行うラッパー

    フロー:
    1. 操作を実行
    2. 結果がセッション切れ（error_type="session_expired"）の場合:
       a. DBから認証情報を取得（credentials引数が無い場合）
       b. executor.re_login() で再ログイン
       c. 元の操作を再実行（最大3回）
    3. セッション切れ以外のエラー、または再試行上限超過の場合は結果をそのまま返す

    Args:
        executor: BaseExecutorのサブクラスインスタンス
        operation: 実行する操作（async lambda）
        credentials: 認証情報（オプション）
        user_id: ユーザーID（認証情報取得・OTP用）

    Returns:
        操作の結果
    """
    # 自動再ログイン非対応のExecutorはそのまま実行
    if not executor.supports_auto_relogin():
        logger.debug(f"{executor.service_name} は自動再ログイン非対応、直接実行")
        return await operation()

    attempt = 0
    backoff = INITIAL_BACKOFF_SECONDS

    while attempt < MAX_RETRY_ATTEMPTS:
        attempt += 1
        logger.debug(f"セッションリトライ: 試行 {attempt}/{MAX_RETRY_ATTEMPTS}")

        # 操作を実行
        result = await operation()

        # 結果がセッション切れかどうか確認
        if not _is_session_expired(result):
            # セッション切れでなければ結果を返す
            return result

        logger.info(f"セッション切れを検出（試行 {attempt}/{MAX_RETRY_ATTEMPTS}）")

        # 最後の試行だった場合はリトライせず結果を返す
        if attempt >= MAX_RETRY_ATTEMPTS:
            logger.warning("セッションリトライ上限超過")
            return result

        # 再ログインを試行
        relogin_success = await _attempt_relogin(
            executor=executor,
            credentials=credentials,
            user_id=user_id,
        )

        if not relogin_success:
            logger.warning("再ログイン失敗、リトライ中止")
            return result

        logger.info("再ログイン成功、操作を再試行")

        # バックオフ待機
        await asyncio.sleep(backoff)
        backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF_SECONDS)

    return result


def _is_session_expired(result: Any) -> bool:
    """
    結果がセッション切れかどうかを判定

    Args:
        result: 操作の結果（ExecutorSearchResult, ExecutionResult, dict等）

    Returns:
        セッション切れの場合True
    """
    # dictの場合
    if isinstance(result, dict):
        return result.get("error_type") == "session_expired"

    # ExecutorSearchResult, ExecutionResult等の場合
    error_type = getattr(result, "error_type", None)
    return error_type == "session_expired"


async def _attempt_relogin(
    executor: Any,
    credentials: Optional[Dict[str, str]] = None,
    user_id: Optional[str] = None,
) -> bool:
    """
    再ログインを試行

    Args:
        executor: Executorインスタンス
        credentials: 認証情報（オプション）
        user_id: ユーザーID

    Returns:
        再ログイン成功の場合True
    """
    # 認証情報がない場合はDBから取得
    if not credentials and user_id:
        credentials = await _get_credentials_from_db(
            user_id=user_id,
            service_name=executor.service_name,
        )

    if not credentials:
        logger.warning("再ログイン用の認証情報がありません")
        return False

    try:
        page = await get_executor_page()

        # Executorの再ログインメソッドを呼び出し
        success = await executor.re_login(
            page=page,
            credentials=credentials,
            user_id=user_id,
        )

        if success:
            logger.info(f"{executor.service_name} への再ログイン成功")
        else:
            logger.warning(f"{executor.service_name} への再ログイン失敗")

        return success

    except Exception as e:
        logger.error(f"再ログイン中にエラー: {e}", exc_info=True)
        return False


async def _get_credentials_from_db(
    user_id: str,
    service_name: str,
) -> Optional[Dict[str, str]]:
    """
    DBから認証情報を取得

    Args:
        user_id: ユーザーID
        service_name: サービス名（ex_reservation, amazon等）

    Returns:
        認証情報のdict、なければNone
    """
    try:
        from app.services.credentials_service import get_credentials_service

        creds_service = get_credentials_service()
        stored_creds = await creds_service.get_credential(user_id, service_name)

        if not stored_creds:
            logger.debug(f"{service_name} の保存済み認証情報なし")
            return None

        # サービスごとに適切な形式に変換
        if "member_id" in stored_creds:
            # EX予約
            return {
                "member_id": stored_creds["member_id"],
                "password": stored_creds["password"],
            }
        elif "email" in stored_creds:
            # Amazon等
            return {
                "email": stored_creds["email"],
                "password": stored_creds["password"],
            }
        elif "username" in stored_creds:
            return {
                "username": stored_creds["username"],
                "password": stored_creds["password"],
            }

        return stored_creds

    except Exception as e:
        logger.error(f"認証情報取得エラー: {e}")
        return None
