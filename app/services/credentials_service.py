"""
Credentials Service for Phase 3B: Execution Engine
認証情報の保存・取得・削除を管理するサービス（Supabase永続化）
"""
from typing import Optional, Any
from datetime import datetime
import logging

from app.services.encryption import get_encryption_service
from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class CredentialsService:
    """認証情報管理サービス（Supabase永続化版）"""

    def __init__(self):
        """サービスを初期化"""
        self.encryption = get_encryption_service()
        self.supabase = get_supabase_client().client

    async def save_credential(
        self,
        user_id: str,
        service: str,
        credentials: dict[str, str],
        credential_type: str = "login",
    ) -> dict[str, Any]:
        """
        認証情報を暗号化して保存

        Args:
            user_id: ユーザーID
            service: サービス名（ex_reservation, amazon, gmail_imap等）
            credentials: 認証情報（email, passwordなど）
            credential_type: 認証タイプ（login, api_key, oauth, imap）

        Returns:
            保存結果
        """
        try:
            encrypted_data = self.encryption.encrypt_dict(credentials)
            encrypted_str = encrypted_data.decode('utf-8')  # bytesをstrに変換

            # 既存のレコードを確認
            existing = self.supabase.table("user_credentials").select("id").eq(
                "user_id", user_id
            ).eq(
                "service", service
            ).execute()

            if existing.data:
                # 更新
                self.supabase.table("user_credentials").update({
                    "encrypted_data": encrypted_str,
                    "credential_type": credential_type,
                }).eq("user_id", user_id).eq("service", service).execute()
                logger.info(f"Credentials updated for user {user_id}, service {service}")
            else:
                # 新規作成
                self.supabase.table("user_credentials").insert({
                    "user_id": user_id,
                    "service": service,
                    "credential_type": credential_type,
                    "encrypted_data": encrypted_str,
                }).execute()
                logger.info(f"Credentials saved for user {user_id}, service {service}")

            return {
                "success": True,
                "service": service,
                "message": "Credentials saved",
            }
        except Exception as e:
            logger.error(f"Failed to save credentials: {e}")
            return {
                "success": False,
                "service": service,
                "message": str(e),
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
        try:
            result = self.supabase.table("user_credentials").select("*").eq(
                "user_id", user_id
            ).eq(
                "service", service
            ).execute()

            if not result.data:
                return None

            stored = result.data[0]
            encrypted_bytes = stored["encrypted_data"].encode('utf-8')
            decrypted = self.encryption.decrypt_dict(encrypted_bytes)

            return {
                "id": stored["id"],
                "service": stored["service"],
                "credential_type": stored.get("credential_type", "login"),
                **decrypted,
            }
        except Exception as e:
            logger.error(f"Failed to get credentials: {e}")
            return None

    async def list_credentials(
        self,
        user_id: str,
    ) -> list[dict[str, Any]]:
        """
        ユーザーの保存済みサービス一覧を取得

        Args:
            user_id: ユーザーID

        Returns:
            保存済みサービス一覧（認証情報は含まない）
        """
        try:
            result = self.supabase.table("user_credentials").select(
                "id, service, credential_type, created_at, updated_at"
            ).eq("user_id", user_id).execute()

            return [
                {
                    "service": row["service"],
                    "credential_type": row.get("credential_type", "login"),
                    "created_at": row["created_at"],
                    "updated_at": row.get("updated_at"),
                }
                for row in result.data
            ]
        except Exception as e:
            logger.error(f"Failed to list credentials: {e}")
            return []

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
        try:
            result = self.supabase.table("user_credentials").delete().eq(
                "user_id", user_id
            ).eq(
                "service", service
            ).execute()

            if result.data:
                logger.info(f"Credentials deleted for user {user_id}, service {service}")
                return {
                    "success": True,
                    "service": service,
                    "message": "Credentials deleted",
                }
            else:
                return {
                    "success": False,
                    "service": service,
                    "message": "Credentials not found",
                }
        except Exception as e:
            logger.error(f"Failed to delete credentials: {e}")
            return {
                "success": False,
                "service": service,
                "message": str(e),
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
        try:
            result = self.supabase.table("user_credentials").select("id").eq(
                "user_id", user_id
            ).eq(
                "service", service
            ).execute()

            return bool(result.data)
        except Exception as e:
            logger.error(f"Failed to check credentials: {e}")
            return False


# シングルトンインスタンス
_credentials_service: Optional[CredentialsService] = None


def get_credentials_service() -> CredentialsService:
    """認証情報サービスのシングルトンインスタンスを取得"""
    global _credentials_service
    if _credentials_service is None:
        _credentials_service = CredentialsService()
    return _credentials_service
