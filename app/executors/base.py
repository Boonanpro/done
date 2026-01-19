"""
Base Executor for Architecture v2: 推論ファースト・Executor実行フロー
共通実行ロジックの基底クラス

新アーキテクチャでは以下のフローで動作：
1. 推論 + Web検索で最適解を導出
2. ExecutorRegistryで最適解を実現できるExecutorを探す
3. Executor.search() で予約可能かを確認
4. 予約可能なら提案を生成、ユーザー承認を待つ
5. Executor.execute() で実際に予約を確定
"""
from abc import ABC, abstractmethod
from typing import Optional, Any, List, Dict
from datetime import datetime
from dataclasses import dataclass
import asyncio

from app.models.schemas import (
    ExecutionStatus,
    ExecutionStep,
    ExecutionResult,
    SearchResult,
)
from app.services.execution_service import get_execution_service
from app.services.credentials_service import get_credentials_service


@dataclass
class SearchOption:
    """検索結果の1つの選択肢"""
    id: str
    title: str
    description: str
    price: Optional[int] = None
    price_currency: str = "JPY"
    available: bool = True
    details: Optional[Dict[str, Any]] = None
    url: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "price": self.price,
            "price_currency": self.price_currency,
            "available": self.available,
            "details": self.details or {},
            "url": self.url,
        }


@dataclass
class ExecutorSearchResult:
    """Executor検索結果"""
    success: bool
    options: List[SearchOption]
    message: str = ""
    service_name: str = ""
    service_display_name: str = ""
    search_url: Optional[str] = None
    screenshot_path: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "options": [opt.to_dict() for opt in self.options],
            "message": self.message,
            "service_name": self.service_name,
            "service_display_name": self.service_display_name,
            "search_url": self.search_url,
            "screenshot_path": self.screenshot_path,
        }


class BaseExecutor(ABC):
    """実行ロジックの基底クラス"""
    
    # サービス情報（サブクラスでオーバーライド）
    service_type: str = "generic"  # airline, train, bus, hotel, product, voice
    service_name: str = "generic"  # jal, ex_reservation, willer, amazon等
    service_display_name: str = "汎用"  # 表示名（日本語）
    
    # 必要なステップ（サブクラスでオーバーライド可能）
    required_steps: list[str] = [
        ExecutionStep.OPENED_URL.value,
        ExecutionStep.LOGGED_IN.value,
        ExecutionStep.ENTERED_DETAILS.value,
        ExecutionStep.CONFIRMED.value,
        ExecutionStep.COMPLETED.value,
    ]
    
    # プログレスコールバック用
    _request_id: Optional[str] = None
    
    def __init__(self):
        """実行エンジンを初期化"""
        self.execution_service = get_execution_service()
        self.credentials_service = get_credentials_service()
    
    def set_request_id(self, request_id: str) -> None:
        """プログレス通知用のrequest_idを設定"""
        self._request_id = request_id
    
    async def _notify_progress(self, step_id: str, label: str, status: str = "running") -> None:
        """プログレスを通知"""
        if self._request_id:
            from app.services.progress_callback import notify_progress
            await notify_progress(self._request_id, step_id, label, status)
    
    # ========================================
    # 探索モード（search）
    # ========================================
    
    async def search(
        self,
        params: Dict[str, Any],
        credentials: Optional[Dict[str, str]] = None,
        user_id: Optional[str] = None,
    ) -> ExecutorSearchResult:
        """
        探索モード: 予約可能な選択肢を検索

        実際のサイトにPlaywrightでアクセスし、
        空席・在庫・価格を確認して予約可能なものだけ返す。

        Args:
            params: 検索パラメータ（出発地、到着地、日時など）
            credentials: 認証情報（オプション）
            user_id: ユーザーID（OTP取得等に使用）

        Returns:
            ExecutorSearchResult: 検索結果
        """
        # user_idをインスタンス変数として保持
        self._user_id = user_id

        try:
            await self._notify_progress(
                "executor_start",
                f"{self.service_display_name}で検索を開始します...",
            )

            # サブクラスの実装を呼び出し
            result = await self._do_search(params, credentials)
            
            # サービス情報を付加
            result.service_name = self.service_name
            result.service_display_name = self.service_display_name
            
            if result.success and result.options:
                await self._notify_progress(
                    "executor_complete",
                    f"{self.service_display_name}から{len(result.options)}件取得しました",
                    "completed",
                )
            else:
                await self._notify_progress(
                    "executor_no_results",
                    f"{self.service_display_name}で該当なし",
                    "completed",
                )
            
            return result
            
        except Exception as e:
            await self._notify_progress(
                "executor_error",
                f"{self.service_display_name}でエラー: {str(e)}",
                "error",
            )
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=f"検索エラー: {str(e)}",
                service_name=self.service_name,
                service_display_name=self.service_display_name,
            )
    
    async def _do_search(
        self,
        params: Dict[str, Any],
        credentials: Optional[Dict[str, str]] = None,
    ) -> ExecutorSearchResult:
        """
        実際の検索ロジック（サブクラスで実装）
        
        デフォルト実装は検索非対応を返す。
        search機能を持つExecutorはこのメソッドをオーバーライドする。
        """
        return ExecutorSearchResult(
            success=False,
            options=[],
            message=f"{self.service_display_name}は検索機能に対応していません",
        )
    
    # ========================================
    # 検証モード（validate）
    # ========================================
    
    async def validate(
        self,
        selection: Dict[str, Any],
        credentials: Optional[Dict[str, str]] = None,
    ) -> ExecutorSearchResult:
        """
        検証モード: 選択した便/商品がまだ予約可能か再確認
        
        提案から時間が経っている場合に使用。
        デフォルトはsearch()を再実行。
        
        Args:
            selection: 選択された選択肢
            credentials: 認証情報
            
        Returns:
            ExecutorSearchResult: 検証結果
        """
        # デフォルトは同じパラメータで再検索
        return await self.search(selection, credentials)
    
    # ========================================
    # 実行モード（execute）
    # ========================================
    
    async def execute(
        self,
        task_id: str,
        user_id: str,
        search_result: SearchResult,
        credentials: Optional[dict[str, str]] = None,
    ) -> ExecutionResult:
        """
        実行モード: 実際に予約/購入を確定
        
        ユーザーが承認した後に呼び出される。
        
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
            # エラーを記録（詳細なトレースバック付き）
            import traceback
            error_details = traceback.format_exc()
            print(f"[EXECUTOR ERROR] {task_id}: {str(e)}\n{error_details}")
            
            error_result = ExecutionResult(
                success=False,
                message=f"Execution error: {str(e)}",
                details={"traceback": error_details},
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
    
    async def _handle_otp_challenge(
        self,
        page,
        task_id: str,
        user_id: str,
        service: str,
        otp_source: str = "email",
        timeout_seconds: int = 60,
    ) -> Optional[str]:
        """
        OTP入力が必要な場合の処理
        
        1. OTP入力フィールドを検知
        2. OTPServiceからコードを取得
        3. フィールドに入力
        
        Args:
            page: Playwrightページ
            task_id: タスクID
            user_id: ユーザーID
            service: サービス名（amazon, ex_reservation等）
            otp_source: OTPソース（email/sms）
            timeout_seconds: タイムアウト秒数
            
        Returns:
            OTPコード、取得できなかった場合はNone
        """
        from app.services.otp_service import get_otp_service
        from app.models.otp_schemas import OTP_FIELD_SELECTORS, OTP_PAGE_INDICATORS
        
        # OTP入力画面かどうか確認
        page_text = await page.inner_text("body")
        is_otp_page = any(indicator in page_text for indicator in OTP_PAGE_INDICATORS)
        
        if not is_otp_page:
            return None
        
        # OTP入力フィールドを検索
        otp_field = None
        for selector in OTP_FIELD_SELECTORS:
            try:
                otp_field = await page.wait_for_selector(selector, timeout=3000)
                if otp_field:
                    break
            except Exception:
                continue
        
        if not otp_field:
            return None
        
        await self._update_progress(
            task_id=task_id,
            step="otp_required",
            details={"source": otp_source, "service": service},
        )
        
        # OTPを待機・取得
        otp_service = get_otp_service()
        otp_code = await otp_service.wait_for_otp(
            user_id=user_id,
            service=service,
            source=otp_source,
            timeout_seconds=timeout_seconds,
        )
        
        if otp_code:
            await self._update_progress(
                task_id=task_id,
                step="otp_received",
                details={"source": otp_source},
            )
            
            # OTPを入力
            await otp_field.fill(otp_code)
            
            return otp_code
        
        await self._update_progress(
            task_id=task_id,
            step="otp_timeout",
            details={"message": "OTP retrieval timed out"},
        )
        return None
    
    # ========================================
    # キャンセルモード（cancel）
    # ========================================

    async def cancel(
        self,
        params: Dict[str, Any],
        credentials: Optional[Dict[str, str]] = None,
        user_id: Optional[str] = None,
    ) -> ExecutionResult:
        """
        キャンセルモード: 予約をキャンセル（払戻）

        Args:
            params: キャンセルパラメータ（reservation_id等）
            credentials: 認証情報（オプション）
            user_id: ユーザーID

        Returns:
            ExecutionResult: キャンセル結果
        """
        self._user_id = user_id

        try:
            await self._notify_progress(
                "cancel_start",
                f"{self.service_display_name}でキャンセルを開始します...",
            )

            # サブクラスの実装を呼び出し
            result = await self._do_cancel(params, credentials)

            if result.success:
                await self._notify_progress(
                    "cancel_complete",
                    f"{self.service_display_name}でキャンセルが完了しました",
                    "completed",
                )
            else:
                await self._notify_progress(
                    "cancel_failed",
                    f"{self.service_display_name}でキャンセル失敗: {result.message}",
                    "error",
                )

            return result

        except Exception as e:
            await self._notify_progress(
                "cancel_error",
                f"{self.service_display_name}でエラー: {str(e)}",
                "error",
            )
            return ExecutionResult(
                success=False,
                message=f"キャンセルエラー: {str(e)}",
            )

    async def _do_cancel(
        self,
        params: Dict[str, Any],
        credentials: Optional[Dict[str, str]] = None,
    ) -> ExecutionResult:
        """
        実際のキャンセルロジック（サブクラスで実装）

        デフォルト実装はキャンセル非対応を返す。
        cancel機能を持つExecutorはこのメソッドをオーバーライドする。
        """
        return ExecutionResult(
            success=False,
            message=f"{self.service_display_name}はキャンセル機能に対応していません",
        )

    async def _detect_otp_page(self, page) -> bool:
        """
        現在のページがOTP入力画面かどうかを検知
        
        Args:
            page: Playwrightページ
            
        Returns:
            OTP入力画面の場合True
        """
        from app.models.otp_schemas import OTP_PAGE_INDICATORS
        
        try:
            page_text = await page.inner_text("body")
            return any(indicator in page_text for indicator in OTP_PAGE_INDICATORS)
        except Exception:
            return False
    
    async def _find_otp_field(self, page):
        """
        OTP入力フィールドを検索
        
        Args:
            page: Playwrightページ
            
        Returns:
            OTP入力フィールド（見つからない場合はNone）
        """
        from app.models.otp_schemas import OTP_FIELD_SELECTORS
        
        for selector in OTP_FIELD_SELECTORS:
            try:
                field = await page.wait_for_selector(selector, timeout=2000)
                if field:
                    return field
            except Exception:
                continue
        return None


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
            message="Execution completed",
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
            message=f"Reservation completed. Confirmation number: {confirmation_number}",
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
            message=f"Purchase completed. Order number: {order_number}",
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
            from app.executors.ex_reservation import EXReservationExecutor
            return EXReservationExecutor()
        elif category == "bus":
            from app.executors.highway_bus_executor import HighwayBusExecutor
            return HighwayBusExecutor()
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
        elif category in ("voice", "phone", "call"):
            # 電話タスク用Executor
            from app.executors.voice_executor import VoiceExecutor
            return VoiceExecutor()
        else:
            return GenericExecutor()
