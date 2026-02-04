"""
Credentials Service for Phase 3B: Execution Engine
認証情報の保存・取得・削除を管理するサービス（Supabase永続化）

統一スキーマ（2026/01リファクタリング）:
    全サービス共通で {"id": "...", "password": "..."} の形式を使用。
    保存時・取得時に自動で正規化される。
"""
from typing import Optional, Any, Dict
from datetime import datetime
import logging

from app.services.encryption import get_encryption_service
from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


# ============================================
# 認証情報の正規化（統一スキーマ）
# ============================================

# IDとして認識するキー（優先順）
ID_KEYS = ["id", "email", "member_id", "username", "login_id", "user_id"]
# パスワードとして認識するキー（優先順）
PASSWORD_KEYS = ["password", "pass", "pw"]


def _normalize_credentials(credentials: Dict[str, Any]) -> Dict[str, Any]:
    """
    認証情報のキー名を統一スキーマに正規化

    入力例:
        {"email": "user@example.com", "password": "xxx"}
        {"member_id": "12345678", "pass": "xxx"}
        {"username": "john", "pw": "xxx"}

    出力（統一形式）:
        {"id": "...", "password": "..."}

    Args:
        credentials: 様々なキー名の認証情報

    Returns:
        正規化された認証情報（id, password のみ）
    """
    normalized: Dict[str, Any] = {}

    # IDを抽出（優先順で最初に見つかったものを使用）
    for key in ID_KEYS:
        if key in credentials and credentials[key]:
            normalized["id"] = credentials[key]
            break

    # パスワードを抽出
    for key in PASSWORD_KEYS:
        if key in credentials and credentials[key]:
            normalized["password"] = credentials[key]
            break

    # _credential_type があればそのまま保持（内部用）
    if "_credential_type" in credentials:
        normalized["_credential_type"] = credentials["_credential_type"]

    return normalized


class CredentialsService:
    """認証情報管理サービス（Supabase永続化版）"""

    # 使用するテーブル名（既存のcredentialsテーブルを使用）
    TABLE_NAME = "credentials"

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

        保存前に正規化を行い、統一スキーマ（id, password）に変換する。

        Args:
            user_id: ユーザーID
            service: サービス名（ex_reservation, amazon, gmail_imap等）
            credentials: 認証情報（email/member_id/username/id, password/pass/pw）
            credential_type: 認証タイプ（login, api_key, oauth, imap）

        Returns:
            保存結果
        """
        try:
            # 認証情報を正規化（統一スキーマに変換）
            normalized = _normalize_credentials(credentials)

            # credential_typeを追加
            normalized["_credential_type"] = credential_type

            encrypted_data = self.encryption.encrypt_dict(normalized)
            encrypted_str = encrypted_data.decode('utf-8')  # bytesをstrに変換

            # 既存のレコードを確認
            existing = self.supabase.table(self.TABLE_NAME).select("id").eq(
                "user_id", user_id
            ).eq(
                "service_name", service
            ).execute()

            if existing.data:
                # 更新
                self.supabase.table(self.TABLE_NAME).update({
                    "encrypted_data": encrypted_str,
                }).eq("user_id", user_id).eq("service_name", service).execute()
                logger.info(f"Credentials updated for user {user_id}, service {service}")
            else:
                # 新規作成
                self.supabase.table(self.TABLE_NAME).insert({
                    "user_id": user_id,
                    "service_name": service,
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

        取得時も正規化を行い、統一スキーマ（id, password）で返す。
        マイグレーション前の旧データにも対応。

        Args:
            user_id: ユーザーID
            service: サービス名

        Returns:
            正規化された認証情報（id, password）、なければNone
        """
        try:
            result = self.supabase.table(self.TABLE_NAME).select("*").eq(
                "user_id", user_id
            ).eq(
                "service_name", service
            ).execute()

            if not result.data:
                return None

            stored = result.data[0]
            encrypted_bytes = stored["encrypted_data"].encode('utf-8')
            decrypted = self.encryption.decrypt_dict(encrypted_bytes)

            # _credential_typeを取り出してトップレベルに
            credential_type = decrypted.pop("_credential_type", "login")

            # 正規化して統一スキーマに変換（旧データ対応）
            normalized = _normalize_credentials(decrypted)

            return {
                "id": normalized.get("id"),
                "password": normalized.get("password"),
                "service": stored["service_name"],
                "credential_type": credential_type,
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
            result = self.supabase.table(self.TABLE_NAME).select(
                "id, service_name, created_at, updated_at"
            ).eq("user_id", user_id).execute()

            return [
                {
                    "service": row["service_name"],
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
            result = self.supabase.table(self.TABLE_NAME).delete().eq(
                "user_id", user_id
            ).eq(
                "service_name", service
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
            result = self.supabase.table(self.TABLE_NAME).select("id").eq(
                "user_id", user_id
            ).eq(
                "service_name", service
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
