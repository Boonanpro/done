"""
salonboard_credentials のビジネスロジック。

ログイン情報の暗号化保存・状態確認・自動投稿時の復号を提供する。
- save: 平文を受け取り Fernet で暗号化して保存（upsert）
- get_status: 平文を返さず、設定済みかどうかとメタ情報のみ返す
- get_decrypted_for_posting: 自動投稿処理時にのみ呼び出す。平文を返す
- delete: 設定の削除
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.services.salonboard_encryption import get_salonboard_encryption_service
from app.services.supabase_client import get_supabase_client


class SalonboardCredentialsService:
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.table = "salonboard_credentials"
        self.enc = get_salonboard_encryption_service()

    async def save(
        self,
        device_id: str,
        stylist_name: str,
        login_id: str,
        password: str,
    ) -> dict:
        """設定の保存。同じ device_id があれば上書き。"""
        encrypted_id = self.enc.encrypt(login_id)
        encrypted_pw = self.enc.encrypt(password)
        consent_at = datetime.now(timezone.utc).isoformat()

        existing = (
            self.supabase.table(self.table)
            .select("id")
            .eq("device_id", device_id)
            .execute()
        )
        if existing.data:
            result = (
                self.supabase.table(self.table)
                .update(
                    {
                        "stylist_name": stylist_name,
                        "encrypted_login_id": encrypted_id,
                        "encrypted_password": encrypted_pw,
                        "consent_at": consent_at,
                    }
                )
                .eq("device_id", device_id)
                .execute()
            )
        else:
            result = (
                self.supabase.table(self.table)
                .insert(
                    {
                        "device_id": device_id,
                        "stylist_name": stylist_name,
                        "encrypted_login_id": encrypted_id,
                        "encrypted_password": encrypted_pw,
                        "consent_at": consent_at,
                    }
                )
                .execute()
            )
        return result.data[0] if result.data else {}

    async def get_status(self, device_id: str) -> dict:
        """設定済みかどうかを返す。平文は決して返さない。"""
        result = (
            self.supabase.table(self.table)
            .select("stylist_name, last_used_at, consent_at")
            .eq("device_id", device_id)
            .execute()
        )
        if not result.data:
            return {"has_credentials": False}
        row = result.data[0]
        return {
            "has_credentials": True,
            "stylist_name": row["stylist_name"],
            "last_used_at": row.get("last_used_at"),
            "consent_at": row.get("consent_at"),
        }

    async def get_decrypted_for_posting(self, device_id: str) -> Optional[dict]:
        """自動投稿処理時のみ呼ぶ。平文を返す。
        最後に使用した時刻も更新する。"""
        result = (
            self.supabase.table(self.table)
            .select("*")
            .eq("device_id", device_id)
            .execute()
        )
        if not result.data:
            return None
        row = result.data[0]
        # last_used_at を更新（同期実行で軽い update）
        self.supabase.table(self.table).update(
            {"last_used_at": datetime.now(timezone.utc).isoformat()}
        ).eq("device_id", device_id).execute()
        return {
            "stylist_name": row["stylist_name"],
            "login_id": self.enc.decrypt(row["encrypted_login_id"]),
            "password": self.enc.decrypt(row["encrypted_password"]),
        }

    async def delete(self, device_id: str) -> bool:
        result = (
            self.supabase.table(self.table)
            .delete()
            .eq("device_id", device_id)
            .execute()
        )
        return bool(result.data)
