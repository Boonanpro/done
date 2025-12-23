"""
Bank Transfer Executor - Phase 8A: 銀行振込実行
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Dict, Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class BankTransferResult:
    """振込実行結果"""
    
    def __init__(
        self,
        success: bool,
        message: str,
        transaction_id: Optional[str] = None,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.success = success
        self.message = message
        self.transaction_id = transaction_id
        self.error_code = error_code
        self.details = details or {}


class BaseBankHandler(ABC):
    """銀行別ハンドラの基底クラス"""
    
    bank_type: str = "base"
    
    @abstractmethod
    async def execute_transfer(
        self,
        invoice: Dict[str, Any],
        credentials: Optional[Dict[str, str]] = None,
        progress_callback: Optional[callable] = None,
    ) -> BankTransferResult:
        """
        振込を実行
        
        Args:
            invoice: 請求書情報
            credentials: ネットバンキングの認証情報
            progress_callback: 進捗コールバック関数
        
        Returns:
            振込実行結果
        """
        pass


class SimulationBankHandler(BaseBankHandler):
    """シミュレーション用ハンドラ（テスト・開発用）"""
    
    bank_type = "simulation"
    
    async def execute_transfer(
        self,
        invoice: Dict[str, Any],
        credentials: Optional[Dict[str, str]] = None,
        progress_callback: Optional[callable] = None,
    ) -> BankTransferResult:
        """シミュレーション振込"""
        try:
            # Step 1: URLにアクセス
            if progress_callback:
                await progress_callback("opened_url")
            await asyncio.sleep(0.5)  # シミュレーション遅延
            
            # Step 2: ログイン
            if progress_callback:
                await progress_callback("logged_in")
            await asyncio.sleep(0.5)
            
            # Step 3: 振込ページを開く
            if progress_callback:
                await progress_callback("opened_transfer_page")
            await asyncio.sleep(0.3)
            
            # Step 4: 振込先情報を入力
            if progress_callback:
                await progress_callback("entering_recipient")
            await asyncio.sleep(0.5)
            
            # Step 5: 金額を入力
            if progress_callback:
                await progress_callback("entering_amount")
            await asyncio.sleep(0.3)
            
            # Step 6: 確認
            if progress_callback:
                await progress_callback("confirming")
            await asyncio.sleep(0.5)
            
            # Step 7: 完了
            transaction_id = f"SIM-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            if progress_callback:
                await progress_callback("completed")
            
            return BankTransferResult(
                success=True,
                message="シミュレーション振込が完了しました",
                transaction_id=transaction_id,
                details={
                    "bank_type": self.bank_type,
                    "amount": invoice.get("amount"),
                    "recipient": invoice.get("bank_info", {}).get("account_holder", "不明"),
                    "simulated": True,
                },
            )
            
        except Exception as e:
            logger.error(f"Simulation transfer failed: {e}")
            return BankTransferResult(
                success=False,
                message=f"シミュレーション振込に失敗しました: {str(e)}",
                error_code="SIMULATION_ERROR",
            )


class SBIBankHandler(BaseBankHandler):
    """住信SBIネット銀行ハンドラ（将来実装用）"""
    
    bank_type = "sbi"
    
    async def execute_transfer(
        self,
        invoice: Dict[str, Any],
        credentials: Optional[Dict[str, str]] = None,
        progress_callback: Optional[callable] = None,
    ) -> BankTransferResult:
        """SBI銀行振込（将来実装）"""
        # TODO: Playwrightを使用して実際の銀行サイトを操作
        return BankTransferResult(
            success=False,
            message="SBI銀行振込は未実装です",
            error_code="NOT_IMPLEMENTED",
        )


class BankTransferExecutor:
    """銀行振込Executor"""
    
    # 振込ステップ
    REQUIRED_STEPS = [
        "opened_url",
        "logged_in",
        "opened_transfer_page",
        "entering_recipient",
        "entering_amount",
        "confirming",
        "completed",
    ]
    
    def __init__(self):
        """初期化"""
        from app.services.supabase_client import get_supabase_client
        supabase_client = get_supabase_client()
        self.db = supabase_client.client
        
        # 銀行ハンドラを登録
        self.handlers: Dict[str, BaseBankHandler] = {
            "simulation": SimulationBankHandler(),
            "sbi": SBIBankHandler(),
        }
    
    def _get_handler(self, bank_type: str) -> BaseBankHandler:
        """銀行タイプに応じたハンドラを取得"""
        handler = self.handlers.get(bank_type)
        if not handler:
            # デフォルトはシミュレーション
            handler = self.handlers.get("simulation")
        return handler
    
    async def execute(
        self,
        invoice_id: str,
        user_id: str,
        bank_type: str = "simulation",
        credentials: Optional[Dict[str, str]] = None,
    ) -> BankTransferResult:
        """
        振込を実行
        
        Args:
            invoice_id: 請求書ID
            user_id: ユーザーID
            bank_type: 銀行タイプ（simulation, sbi等）
            credentials: ネットバンキングの認証情報
        
        Returns:
            振込実行結果
        """
        execution_log_id = None
        
        try:
            # 1. 請求書を取得
            invoice = await self._get_invoice(invoice_id, user_id)
            if not invoice:
                return BankTransferResult(
                    success=False,
                    message="請求書が見つかりません",
                    error_code="INVOICE_NOT_FOUND",
                )
            
            # 2. ステータス確認（approvedのみ実行可能）
            if invoice.get("status") != "approved":
                return BankTransferResult(
                    success=False,
                    message=f"請求書のステータスが承認済みではありません: {invoice.get('status')}",
                    error_code="INVALID_STATUS",
                )
            
            # 3. 実行ログを作成
            execution_log_id = await self._create_execution_log(
                invoice_id=invoice_id,
                user_id=user_id,
                bank_type=bank_type,
                amount=invoice.get("amount"),
                recipient_info=invoice.get("bank_info"),
            )
            
            # 4. ハンドラを取得して実行
            handler = self._get_handler(bank_type)
            
            # 進捗コールバック
            async def progress_callback(step: str):
                await self._update_execution_log(
                    execution_log_id=execution_log_id,
                    current_step=step,
                )
            
            result = await handler.execute_transfer(
                invoice=invoice,
                credentials=credentials,
                progress_callback=progress_callback,
            )
            
            # 5. 結果を記録
            await self._complete_execution(
                execution_log_id=execution_log_id,
                invoice_id=invoice_id,
                result=result,
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Bank transfer execution failed: {e}")
            
            # エラーを記録
            if execution_log_id:
                await self._fail_execution(
                    execution_log_id=execution_log_id,
                    error_message=str(e),
                )
            
            return BankTransferResult(
                success=False,
                message=f"振込実行中にエラーが発生しました: {str(e)}",
                error_code="EXECUTION_ERROR",
            )
    
    async def get_execution_status(
        self,
        invoice_id: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        実行状況を取得
        
        Args:
            invoice_id: 請求書ID
            user_id: ユーザーID
        
        Returns:
            実行状況
        """
        result = self.db.table("payment_execution_logs").select("*").eq(
            "invoice_id", invoice_id
        ).eq(
            "user_id", user_id
        ).order(
            "created_at", desc=True
        ).limit(1).execute()
        
        if result.data and len(result.data) > 0:
            log = result.data[0]
            current_step = log.get("current_step")
            steps_completed = log.get("steps_completed", [])
            
            # 残りのステップを計算
            if current_step and current_step in self.REQUIRED_STEPS:
                current_idx = self.REQUIRED_STEPS.index(current_step)
                steps_remaining = self.REQUIRED_STEPS[current_idx + 1:]
            else:
                steps_remaining = self.REQUIRED_STEPS
            
            return {
                "execution_id": log["id"],
                "invoice_id": invoice_id,
                "status": log["execution_status"],
                "current_step": current_step,
                "steps_completed": steps_completed,
                "steps_remaining": steps_remaining,
                "bank_type": log.get("bank_type"),
                "transaction_id": log.get("transaction_id"),
                "requires_otp": log.get("requires_otp", False),
                "error_message": log.get("error_message"),
                "started_at": log.get("started_at"),
                "completed_at": log.get("completed_at"),
            }
        
        return None
    
    async def _get_invoice(
        self,
        invoice_id: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """請求書を取得"""
        result = self.db.table("invoices").select("*").eq(
            "id", invoice_id
        ).eq(
            "user_id", user_id
        ).execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    
    async def _create_execution_log(
        self,
        invoice_id: str,
        user_id: str,
        bank_type: str,
        amount: int,
        recipient_info: Optional[Dict[str, Any]] = None,
    ) -> str:
        """実行ログを作成"""
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        
        log_data = {
            "invoice_id": invoice_id,
            "user_id": user_id,
            "execution_status": "executing",
            "bank_type": bank_type,
            "payment_type": "bank_transfer",  # 既存スキーマとの互換性
            "success": False,  # 既存スキーマとの互換性
            "transfer_amount": amount,
            "recipient_info": recipient_info,
            "steps_completed": [],
            "steps_remaining": self.REQUIRED_STEPS,
            "started_at": now.isoformat(),
        }
        
        result = self.db.table("payment_execution_logs").insert(log_data).execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]["id"]
        raise Exception("Failed to create execution log")
    
    async def _update_execution_log(
        self,
        execution_log_id: str,
        current_step: str,
        requires_otp: bool = False,
    ) -> None:
        """実行ログを更新"""
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        
        # 現在のログを取得
        current = self.db.table("payment_execution_logs").select(
            "steps_completed"
        ).eq("id", execution_log_id).execute()
        
        steps_completed = []
        if current.data and len(current.data) > 0:
            steps_completed = current.data[0].get("steps_completed", [])
        
        # ステップを追加
        if current_step not in steps_completed:
            steps_completed.append(current_step)
        
        # 残りのステップを計算
        if current_step in self.REQUIRED_STEPS:
            current_idx = self.REQUIRED_STEPS.index(current_step)
            steps_remaining = self.REQUIRED_STEPS[current_idx + 1:]
        else:
            steps_remaining = []
        
        update_data = {
            "current_step": current_step,
            "steps_completed": steps_completed,
            "steps_remaining": steps_remaining,
            "requires_otp": requires_otp,
            "updated_at": now.isoformat(),
        }
        
        if requires_otp:
            update_data["otp_requested_at"] = now.isoformat()
        
        self.db.table("payment_execution_logs").update(update_data).eq(
            "id", execution_log_id
        ).execute()
    
    async def _complete_execution(
        self,
        execution_log_id: str,
        invoice_id: str,
        result: BankTransferResult,
    ) -> None:
        """実行を完了"""
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        
        # 実行ログを更新
        log_update = {
            "execution_status": "completed" if result.success else "failed",
            "success": result.success,  # 既存スキーマとの互換性
            "transaction_id": result.transaction_id,
            "error_message": None if result.success else result.message,
            "completed_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        
        self.db.table("payment_execution_logs").update(log_update).eq(
            "id", execution_log_id
        ).execute()
        
        # 請求書を更新
        if result.success:
            invoice_update = {
                "status": "paid",
                "paid_at": now.isoformat(),
                "transaction_id": result.transaction_id,
                "execution_log_id": execution_log_id,
                "updated_at": now.isoformat(),
            }
        else:
            invoice_update = {
                "status": "failed",
                "error_message": result.message,
                "execution_log_id": execution_log_id,
                "updated_at": now.isoformat(),
            }
        
        self.db.table("invoices").update(invoice_update).eq(
            "id", invoice_id
        ).execute()
    
    async def _fail_execution(
        self,
        execution_log_id: str,
        error_message: str,
    ) -> None:
        """実行を失敗としてマーク"""
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        
        self.db.table("payment_execution_logs").update({
            "execution_status": "failed",
            "error_message": error_message,
            "completed_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }).eq(
            "id", execution_log_id
        ).execute()


# シングルトンインスタンス
_bank_transfer_executor: Optional[BankTransferExecutor] = None


def get_bank_transfer_executor() -> BankTransferExecutor:
    """BankTransferExecutorのインスタンスを取得"""
    global _bank_transfer_executor
    if _bank_transfer_executor is None:
        _bank_transfer_executor = BankTransferExecutor()
    return _bank_transfer_executor

