"""
Base Executor for Phase 3B: Execution Engine
共通実行ロジックの基底クラス
"""
from abc import ABC, abstractmethod
from typing import Optional, Any
from datetime import datetime
import asyncio

from app.models.schemas import (
    ExecutionStatus,
    ExecutionStep,
    ExecutionResult,
    SearchResult,
)
from app.services.execution_service import get_execution_service
from app.services.credentials_service import get_credentials_service


class BaseExecutor(ABC):
    """実行ロジックの基底クラス"""
    
    # サービス名（サブクラスでオーバーライド）
    service_name: str = "generic"
    
    # 必要なステップ（サブクラスでオーバーライド可能）
    required_steps: list[str] = [
        ExecutionStep.OPENED_URL.value,
        ExecutionStep.LOGGED_IN.value,
        ExecutionStep.ENTERED_DETAILS.value,
        ExecutionStep.CONFIRMED.value,
        ExecutionStep.COMPLETED.value,
    ]
    
    def __init__(self):
        """実行エンジンを初期化"""
        self.execution_service = get_execution_service()
        self.credentials_service = get_credentials_service()
    
    async def execute(
        self,
        task_id: str,
        user_id: str,
        search_result: SearchResult,
        credentials: Optional[dict[str, str]] = None,
    ) -> ExecutionResult:
        """
        タスクを実行
        
        Args:
            task_id: タスクID
            user_id: ユーザーID
            search_result: 検索結果（実行対象）
            credentials: 認証情報（オプション）
            
        Returns:
            実行結果
        """
        try:
            # 1. 実行開始
            await self.execution_service.start_execution(
                task_id=task_id,
                user_id=user_id,
                required_service=self.service_name if self._requires_login() else None,
            )
            
            # 2. 認証情報を取得
            if self._requires_login() and not credentials:
                creds = await self.credentials_service.get_credential(
                    user_id=user_id,
                    service=self.service_name,
                )
                if creds:
                    credentials = {
                        "email": creds.get("email", creds.get("username", "")),
                        "password": creds.get("password", ""),
                    }
            
            # 3. 実行ロジック（サブクラスで実装）
            result = await self._do_execute(
                task_id=task_id,
                search_result=search_result,
                credentials=credentials,
            )
            
            # 4. 完了を記録
            await self.execution_service.complete_execution(
                task_id=task_id,
                result=result,
            )
            
            return result
            
        except Exception as e:
            # エラーを記録
            error_result = ExecutionResult(
                success=False,
                message=f"実行中にエラーが発生しました: {str(e)}",
            )
            await self.execution_service.complete_execution(
                task_id=task_id,
                result=error_result,
            )
            return error_result
    
    @abstractmethod
    async def _do_execute(
        self,
        task_id: str,
        search_result: SearchResult,
        credentials: Optional[dict[str, str]] = None,
    ) -> ExecutionResult:
        """
        実際の実行ロジック（サブクラスで実装）
        
        Args:
            task_id: タスクID
            search_result: 検索結果
            credentials: 認証情報
            
        Returns:
            実行結果
        """
        pass
    
    def _requires_login(self) -> bool:
        """ログインが必要かどうか"""
        return True
    
    async def _update_progress(
        self,
        task_id: str,
        step: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """進捗を更新"""
        await self.execution_service.update_progress(
            task_id=task_id,
            step=step,
            status="success",
            details=details,
        )


class GenericExecutor(BaseExecutor):
    """汎用実行ロジック（フォーム入力など）"""
    
    service_name = "generic"
    
    async def _do_execute(
        self,
        task_id: str,
        search_result: SearchResult,
        credentials: Optional[dict[str, str]] = None,
    ) -> ExecutionResult:
        """汎用実行ロジック"""
        # ステップを順番に更新（シミュレーション）
        for step in self.required_steps[:-1]:  # COMPLETEDは除く
            await self._update_progress(
                task_id=task_id,
                step=step,
                details={"simulated": True},
            )
            await asyncio.sleep(0.1)  # シミュレーション用の遅延
        
        # 完了
        await self._update_progress(
            task_id=task_id,
            step=ExecutionStep.COMPLETED.value,
            details={"url": search_result.url},
        )
        
        return ExecutionResult(
            success=True,
            message="実行が完了しました",
            details={
                "url": search_result.url,
                "title": search_result.title,
            },
        )
    
    def _requires_login(self) -> bool:
        """汎用はログイン不要"""
        return False


class TrainExecutor(BaseExecutor):
    """新幹線予約実行ロジック"""
    
    service_name = "ex_reservation"
    
    async def _do_execute(
        self,
        task_id: str,
        search_result: SearchResult,
        credentials: Optional[dict[str, str]] = None,
    ) -> ExecutionResult:
        """新幹線予約実行"""
        # Step 1: URLにアクセス
        await self._update_progress(
            task_id=task_id,
            step=ExecutionStep.OPENED_URL.value,
            details={"url": search_result.url},
        )
        
        # Step 2: ログイン
        if credentials:
            await self._update_progress(
                task_id=task_id,
                step=ExecutionStep.LOGGED_IN.value,
                details={"email": credentials.get("email", "")[:3] + "***"},
            )
        
        # Step 3: 詳細入力
        details = search_result.details
        await self._update_progress(
            task_id=task_id,
            step=ExecutionStep.ENTERED_DETAILS.value,
            details={
                "departure": details.get("departure"),
                "arrival": details.get("arrival"),
                "date": details.get("date"),
                "time": details.get("time"),
            },
        )
        
        # Step 4: 確認
        await self._update_progress(
            task_id=task_id,
            step=ExecutionStep.CONFIRMED.value,
        )
        
        # Step 5: 完了
        # 実際の実装ではPlaywrightで予約番号を取得
        confirmation_number = f"EX-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        await self._update_progress(
            task_id=task_id,
            step=ExecutionStep.COMPLETED.value,
            details={"confirmation_number": confirmation_number},
        )
        
        return ExecutionResult(
            success=True,
            confirmation_number=confirmation_number,
            message=f"予約が完了しました。予約番号: {confirmation_number}",
            details={
                "train_name": details.get("train_name"),
                "departure": details.get("departure"),
                "arrival": details.get("arrival"),
                "date": details.get("date"),
                "time": details.get("time"),
            },
        )


class ProductExecutor(BaseExecutor):
    """商品購入実行ロジック（Amazon/楽天等）"""
    
    service_name = "amazon"  # デフォルトはAmazon
    
    def __init__(self, service_name: str = "amazon"):
        super().__init__()
        self.service_name = service_name
    
    async def _do_execute(
        self,
        task_id: str,
        search_result: SearchResult,
        credentials: Optional[dict[str, str]] = None,
    ) -> ExecutionResult:
        """商品購入実行"""
        # Step 1: 商品ページにアクセス
        await self._update_progress(
            task_id=task_id,
            step=ExecutionStep.OPENED_URL.value,
            details={"url": search_result.url},
        )
        
        # Step 2: ログイン
        if credentials:
            await self._update_progress(
                task_id=task_id,
                step=ExecutionStep.LOGGED_IN.value,
            )
        
        # Step 3: カートに追加
        await self._update_progress(
            task_id=task_id,
            step=ExecutionStep.ENTERED_DETAILS.value,
            details={"action": "added_to_cart"},
        )
        
        # Step 4: 購入確認
        await self._update_progress(
            task_id=task_id,
            step=ExecutionStep.CONFIRMED.value,
        )
        
        # Step 5: 完了
        order_number = f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        await self._update_progress(
            task_id=task_id,
            step=ExecutionStep.COMPLETED.value,
            details={"order_number": order_number},
        )
        
        return ExecutionResult(
            success=True,
            confirmation_number=order_number,
            message=f"購入が完了しました。注文番号: {order_number}",
            details={
                "product_name": search_result.title,
                "price": search_result.price,
                "url": search_result.url,
            },
        )


class ExecutorFactory:
    """Executorのファクトリークラス"""
    
    @staticmethod
    def get_executor(category: str, service_name: Optional[str] = None) -> BaseExecutor:
        """
        カテゴリに応じたExecutorを取得
        
        Args:
            category: カテゴリ（train, bus, flight, product等）
            service_name: サービス名（amazon, rakuten等）
            
        Returns:
            適切なExecutor
        """
        if category == "train":
            return TrainExecutor()
        elif category == "bus":
            # 将来的にBusExecutorを実装
            return GenericExecutor()
        elif category == "flight":
            # 将来的にFlightExecutorを実装
            return GenericExecutor()
        elif category == "product":
            # サービスに応じたExecutorを返す
            if service_name == "amazon":
                from app.executors.amazon_executor import AmazonExecutor
                return AmazonExecutor()
            elif service_name == "rakuten":
                from app.executors.rakuten_executor import RakutenExecutor
                return RakutenExecutor()
            else:
                return ProductExecutor(service_name=service_name or "amazon")
        else:
            return GenericExecutor()
