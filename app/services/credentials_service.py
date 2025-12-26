"""
Credentials Service for Phase 3B: Execution Engine
認証情報の保存・取得・削除を管理するサービス
"""
from typing import Optional, Any
from datetime import datetime
import uuid

from app.services.encryption import get_encryption_service


class CredentialsService:
    """認証情報管理サービス（メモリストレージ版）"""
    
    # クラス変数でメモリストレージを共有
    _credentials_store: dict[str, dict[str, Any]] = {}
    
    def __init__(self):
        """サービスを初期化"""
        self.encryption = get_encryption_service()
    
    def _get_key(self, user_id: str, service: str) -> str:
        """ストレージキーを生成"""
        return f"{user_id}:{service}"
    
    async def save_credential(
        self,
        user_id: str,
        service: str,
        credentials: dict[str, str],
    ) -> dict[str, Any]:
        """
        認証情報を暗号化して保存
        
        Args:
            user_id: ユーザーID
            service: サービス名（ex_reservation, amazon, etc.）
            credentials: 認証情報（email, passwordなど）
            
        Returns:
            保存結果
        """
        encrypted_data = self.encryption.encrypt_dict(credentials)
        
        key = self._get_key(user_id, service)
        now = datetime.utcnow()
        
        # 既存のエントリがあるか確認
        existing = self._credentials_store.get(key)
        
        self._credentials_store[key] = {
            "id": existing["id"] if existing else str(uuid.uuid4()),
            "user_id": user_id,
            "service": service,
            "encrypted_data": encrypted_data,
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        }
        
        return {
            "success": True,
            "service": service,
            "message": "Credentials saved",
        }
    
    async def get_credential(
        self,
        user_id: str,
        service: str,
    ) -> Optional[dict[str, Any]]:
        """
        認証情報を取得して復号
        
        Args:
            user_id: ユーザーID
            service: サービス名
            
        Returns:
            復号された認証情報、なければNone
        """
        key = self._get_key(user_id, service)
        stored = self._credentials_store.get(key)
        
        if not stored:
            return None
        
        decrypted = self.encryption.decrypt_dict(stored["encrypted_data"])
        
        return {
            "id": stored["id"],
            "service": stored["service"],
            **decrypted,
        }
    
    async def list_credentials(
        self,
        user_id: str,
    ) -> list[dict[str, Any]]:
        """
        ユーザーの保存済みサービス一覧を取得
        
        Args:
            user_id: ユーザーID
            
        Returns:
            保存済みサービス一覧
        """
        result = []
        prefix = f"{user_id}:"
        
        for key, value in self._credentials_store.items():
            if key.startswith(prefix):
                result.append({
                    "service": value["service"],
                    "created_at": value["created_at"],
                    "updated_at": value.get("updated_at"),
                })
        
        return result
    
    async def delete_credential(
        self,
        user_id: str,
        service: str,
    ) -> dict[str, Any]:
        """
        認証情報を削除
        
        Args:
            user_id: ユーザーID
            service: サービス名
            
        Returns:
            削除結果
        """
        key = self._get_key(user_id, service)
        
        if key not in self._credentials_store:
            return {
                "success": False,
                "service": service,
                "message": "Credentials not found",
            }
        
        del self._credentials_store[key]
        
        return {
            "success": True,
            "service": service,
            "message": "Credentials deleted",
        }
    
    async def has_credential(
        self,
        user_id: str,
        service: str,
    ) -> bool:
        """
        認証情報が存在するかチェック
        
        Args:
            user_id: ユーザーID
            service: サービス名
            
        Returns:
            存在する場合True
        """
        key = self._get_key(user_id, service)
        return key in self._credentials_store


# シングルトンインスタンス
_credentials_service: Optional[CredentialsService] = None


def get_credentials_service() -> CredentialsService:
    """認証情報サービスのシングルトンインスタンスを取得"""
    global _credentials_service
    if _credentials_service is None:
        _credentials_service = CredentialsService()
    return _credentials_service
