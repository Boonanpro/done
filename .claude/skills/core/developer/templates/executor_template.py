"""
[ServiceName] Executor

[サービスの説明]
"""

import logging
from typing import Dict, Any, Optional

from app.executors.base import BaseExecutor, ExecutorSearchResult, SearchOption
from app.models.schemas import ExecutionResult, SearchResult as TaskSearchResult

logger = logging.getLogger(__name__)


class [ServiceName]Executor(BaseExecutor):
    """
    [サービス名]実行ロジック

    [詳細な説明]
    """

    service_type = "[service_type]"  # train, product, bus, etc.
    service_name = "[service_name]"  # ex_reservation, amazon, etc.
    service_display_name = "[表示名]"  # 日本語表示名

    async def _do_search(
        self,
        params: Dict[str, Any],
        credentials: Optional[Dict[str, str]] = None,
    ) -> ExecutorSearchResult:
        """
        検索モード

        Args:
            params: 検索パラメータ
            credentials: 認証情報

        Returns:
            ExecutorSearchResult: 検索結果
        """
        try:
            # パラメータ取得
            param1 = params.get("param1")
            param2 = params.get("param2")

            if not param1:
                return ExecutorSearchResult(
                    success=False,
                    options=[],
                    message="param1 パラメータが必要です",
                )

            logger.info(f"検索開始: {param1}")

            # 検索ロジック
            # TODO: 実装

            # 結果を返す
            options = [
                SearchOption(
                    id="result_1",
                    title="検索結果1",
                    description="説明",
                    price=1000,
                    available=True,
                    details={
                        "key": "value",
                    },
                )
            ]

            return ExecutorSearchResult(
                success=True,
                options=options,
                message=f"{len(options)}件見つかりました",
            )

        except Exception as e:
            logger.error(f"検索エラー: {e}", exc_info=True)
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=f"検索エラー: {str(e)}",
            )

    async def _do_execute(
        self,
        task_id: str,
        search_result: TaskSearchResult,
        credentials: Optional[Dict[str, str]] = None,
    ) -> ExecutionResult:
        """
        実行モード

        Args:
            task_id: タスクID
            search_result: 検索結果
            credentials: 認証情報

        Returns:
            ExecutionResult: 実行結果
        """
        try:
            # 実行ロジック
            # TODO: 実装

            await self._update_progress(
                task_id=task_id,
                step="completed",
                details={"message": "完了"},
            )

            return ExecutionResult(
                success=True,
                message="実行完了",
                confirmation_number="ABC123",
            )

        except Exception as e:
            logger.error(f"実行エラー: {e}", exc_info=True)
            return ExecutionResult(
                success=False,
                message=f"実行エラー: {str(e)}",
            )

    def _requires_login(self) -> bool:
        """ログインが必要かどうか"""
        return True  # 必要に応じて変更


# ===========================================
# レジストリ登録用（registry.pyに追加）
# ===========================================
# from app.executors.[module_name] import [ServiceName]Executor
# ExecutorRegistry.register(
#     executor_class=[ServiceName]Executor,
#     service_type="[service_type]",
#     service_name="[service_name]",
#     display_name="[表示名]",
#     url_patterns=["example.com"],
#     capabilities=["search", "execute"],
# )
