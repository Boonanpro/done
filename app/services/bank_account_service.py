"""
Bank Account Service - Phase 8B: 振込先管理
"""
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class BankAccountService:
    """振込先管理サービス"""
    
    def __init__(self):
        from app.services.supabase_client import get_supabase_client
        supabase_client = get_supabase_client()
        self.db = supabase_client.client
    
    def _mask_account_number(self, account_number: str) -> str:
        """口座番号をマスク（末尾3桁のみ表示）"""
        if len(account_number) <= 3:
            return account_number
        return "*" * (len(account_number) - 3) + account_number[-3:]
    
    async def create_bank_account(
        self,
        user_id: str,
        display_name: str,
        bank_name: str,
        branch_name: str,
        account_type: str,
        account_number: str,
        account_holder: str,
        bank_code: Optional[str] = None,
        branch_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        振込先を作成
        
        Returns:
            作成された振込先データ
        """
        # 重複チェック（同じ口座情報が既に登録されていないか）
        existing = self.db.table("saved_bank_accounts").select("id").eq(
            "user_id", user_id
        ).eq(
            "bank_name", bank_name
        ).eq(
            "branch_name", branch_name
        ).eq(
            "account_number", account_number
        ).execute()
        
        if existing.data and len(existing.data) > 0:
            raise ValueError("この振込先は既に登録されています")
        
        # データを構築
        bank_account_data = {
            "user_id": user_id,
            "display_name": display_name,
            "bank_name": bank_name,
            "bank_code": bank_code,
            "branch_name": branch_name,
            "branch_code": branch_code,
            "account_type": account_type,
            "account_number": account_number,
            "account_holder": account_holder,
            "is_verified": False,
            "use_count": 0,
        }
        
        # DBに保存
        result = self.db.table("saved_bank_accounts").insert(bank_account_data).execute()
        
        if not result.data or len(result.data) == 0:
            raise Exception("Failed to create bank account")
        
        return result.data[0]
    
    async def get_bank_account(
        self,
        bank_account_id: str,
        user_id: str,
        include_full_number: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        振込先を取得
        
        Args:
            bank_account_id: 振込先ID
            user_id: ユーザーID
            include_full_number: 口座番号を完全に表示するか
        
        Returns:
            振込先データ（マスク済み）
        """
        result = self.db.table("saved_bank_accounts").select("*").eq(
            "id", bank_account_id
        ).eq(
            "user_id", user_id
        ).execute()
        
        if result.data and len(result.data) > 0:
            account = result.data[0]
            # 口座番号をマスク
            full_number = account["account_number"]
            account["account_number"] = self._mask_account_number(full_number)
            if include_full_number:
                account["account_number_full"] = full_number
            return account
        return None
    
    async def list_bank_accounts(
        self,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        振込先一覧を取得
        
        Returns:
            (bank_accounts, total_count)
        """
        # カウント取得
        count_result = self.db.table("saved_bank_accounts").select(
            "id", count="exact"
        ).eq("user_id", user_id).execute()
        
        total = count_result.count if hasattr(count_result, 'count') and count_result.count else 0
        
        # データ取得
        offset = (page - 1) * page_size
        result = self.db.table("saved_bank_accounts").select("*").eq(
            "user_id", user_id
        ).order(
            "last_used_at", desc=True, nullsfirst=False
        ).order(
            "created_at", desc=True
        ).range(offset, offset + page_size - 1).execute()
        
        accounts = []
        for account in result.data or []:
            # 口座番号をマスク
            account["account_number"] = self._mask_account_number(account["account_number"])
            accounts.append(account)
        
        return accounts, total
    
    async def update_bank_account(
        self,
        bank_account_id: str,
        user_id: str,
        **updates: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        振込先を更新
        
        Returns:
            更新された振込先データ
        """
        # 対象の振込先を確認
        existing = await self.get_bank_account(bank_account_id, user_id)
        if not existing:
            return None
        
        # 更新データを構築
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        update_data = {"updated_at": now.isoformat()}
        
        allowed_fields = [
            "display_name", "bank_name", "bank_code", "branch_name",
            "branch_code", "account_type", "account_number", "account_holder"
        ]
        
        for field in allowed_fields:
            if field in updates and updates[field] is not None:
                update_data[field] = updates[field]
        
        # DBを更新
        result = self.db.table("saved_bank_accounts").update(update_data).eq(
            "id", bank_account_id
        ).eq(
            "user_id", user_id
        ).execute()
        
        if result.data and len(result.data) > 0:
            account = result.data[0]
            account["account_number"] = self._mask_account_number(account["account_number"])
            return account
        return None
    
    async def delete_bank_account(
        self,
        bank_account_id: str,
        user_id: str,
    ) -> bool:
        """
        振込先を削除
        
        Returns:
            削除成功したか
        """
        result = self.db.table("saved_bank_accounts").delete().eq(
            "id", bank_account_id
        ).eq(
            "user_id", user_id
        ).execute()
        
        return result.data is not None and len(result.data) > 0
    
    async def mark_as_used(
        self,
        bank_account_id: str,
        user_id: str,
    ) -> None:
        """振込先を使用済みとしてマーク（last_used_at, use_count更新）"""
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        
        # 現在のuse_countを取得
        current = self.db.table("saved_bank_accounts").select("use_count").eq(
            "id", bank_account_id
        ).eq(
            "user_id", user_id
        ).execute()
        
        current_count = 0
        if current.data and len(current.data) > 0:
            current_count = current.data[0].get("use_count", 0) or 0
        
        self.db.table("saved_bank_accounts").update({
            "last_used_at": now.isoformat(),
            "use_count": current_count + 1,
            "updated_at": now.isoformat(),
        }).eq(
            "id", bank_account_id
        ).eq(
            "user_id", user_id
        ).execute()
    
    async def verify_bank_account(
        self,
        bank_account_id: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """振込先を検証済みとしてマーク"""
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        
        result = self.db.table("saved_bank_accounts").update({
            "is_verified": True,
            "updated_at": now.isoformat(),
        }).eq(
            "id", bank_account_id
        ).eq(
            "user_id", user_id
        ).execute()
        
        if result.data and len(result.data) > 0:
            account = result.data[0]
            account["account_number"] = self._mask_account_number(account["account_number"])
            return account
        return None


# シングルトンインスタンス
_bank_account_service: Optional[BankAccountService] = None


def get_bank_account_service() -> BankAccountService:
    """BankAccountServiceのインスタンスを取得"""
    global _bank_account_service
    if _bank_account_service is None:
        _bank_account_service = BankAccountService()
    return _bank_account_service

