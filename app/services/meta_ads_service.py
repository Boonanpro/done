"""meta_ad_accounts のビジネスロジック（マルチテナント Meta 広告接続情報）。

設計は supabase/migrations/068_meta_ad_accounts.sql を参照。

- 運営者の Meta Developer App 設定（app_id/app_secret）は account_label='__app__' 行に保存。
  環境変数 META_APP_ID / META_APP_SECRET があればそちらを優先（DB 無しでも動く）。
- 各テナントの広告アカウント接続（access_token 等）は (user_id, account_label) で保存。
- access_token / app_secret は encrypted_data(JSON) に Fernet 暗号化。閲覧系は平文トークンを返さない。

CLI(scripts/meta_ads_cli.py) から同期で呼ぶ前提（supabase-py の .execute() は同期）。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.encryption import get_encryption_service
from app.services.supabase_client import get_supabase_client

APP_LABEL = "__app__"  # 運営者アプリ設定行の予約ラベル
TABLE = "meta_ad_accounts"


def _mask(token: Optional[str]) -> str:
    if not token:
        return ""
    if len(token) <= 10:
        return "***"
    return f"{token[:6]}…{token[-4:]}"


class MetaAdsService:
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.enc = get_encryption_service()
        self.table = TABLE

    # ---------------------------------------------------------------
    # 運営者アプリ設定（app_id / app_secret）
    # ---------------------------------------------------------------
    def save_app_config(self, user_id: str, app_id: str, app_secret: str) -> dict:
        enc_blob = self.enc.encrypt_dict({"app_id": app_id, "app_secret": app_secret}).decode("utf-8")
        return self._upsert(
            user_id=user_id,
            account_label=APP_LABEL,
            encrypted_data=enc_blob,
            display_name="Meta Developer App",
        )

    def get_app_config(self, user_id: str) -> Optional[dict]:
        """app_id/app_secret を返す。環境変数があれば最優先。"""
        env_id = os.getenv("META_APP_ID")
        env_secret = os.getenv("META_APP_SECRET")
        if env_id and env_secret:
            return {"app_id": env_id, "app_secret": env_secret, "source": "env"}

        row = self._get_row(user_id, APP_LABEL)
        if not row:
            return None
        data = self.enc.decrypt_dict(row["encrypted_data"].encode("utf-8"))
        return {"app_id": data.get("app_id"), "app_secret": data.get("app_secret"), "source": "db"}

    # ---------------------------------------------------------------
    # テナントの広告アカウント接続
    # ---------------------------------------------------------------
    def save_account(
        self,
        user_id: str,
        account_label: str,
        access_token: str,
        ad_account_id: Optional[str] = None,
        page_id: Optional[str] = None,
        ig_user_id: Optional[str] = None,
        currency: Optional[str] = None,
        token_type: str = "user",
        expires_at: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> dict:
        secret = {"access_token": access_token, "token_type": token_type}
        if expires_at:
            secret["expires_at"] = expires_at
        enc_blob = self.enc.encrypt_dict(secret).decode("utf-8")
        return self._upsert(
            user_id=user_id,
            account_label=account_label,
            encrypted_data=enc_blob,
            ad_account_id=ad_account_id,
            page_id=page_id,
            ig_user_id=ig_user_id,
            currency=currency,
            token_expires_at=expires_at,
            display_name=display_name,
        )

    def get_account(self, user_id: str, account_label: str = "default") -> Optional[dict]:
        """平文 access_token を含む完全な接続情報を返す（出稿処理時のみ呼ぶ）。"""
        row = self._get_row(user_id, account_label)
        if not row:
            return None
        secret = self.enc.decrypt_dict(row["encrypted_data"].encode("utf-8"))
        return {
            "account_label": row["account_label"],
            "access_token": secret.get("access_token"),
            "token_type": secret.get("token_type", "user"),
            "ad_account_id": row.get("ad_account_id"),
            "page_id": row.get("page_id"),
            "ig_user_id": row.get("ig_user_id"),
            "currency": row.get("currency"),
            "display_name": row.get("display_name"),
            "token_expires_at": row.get("token_expires_at"),
        }

    def list_accounts(self, user_id: str) -> list[dict]:
        """テナントの接続済みアカウント一覧（平文トークンは返さない）。"""
        result = (
            self.supabase.table(self.table)
            .select("account_label, ad_account_id, page_id, ig_user_id, currency, display_name, token_expires_at, last_used_at")
            .eq("user_id", user_id)
            .neq("account_label", APP_LABEL)
            .execute()
        )
        return result.data or []

    def delete_account(self, user_id: str, account_label: str) -> bool:
        result = (
            self.supabase.table(self.table)
            .delete()
            .eq("user_id", user_id)
            .eq("account_label", account_label)
            .execute()
        )
        return bool(result.data)

    def touch_last_used(self, user_id: str, account_label: str) -> None:
        try:
            self.supabase.table(self.table).update(
                {"last_used_at": datetime.now(timezone.utc).isoformat()}
            ).eq("user_id", user_id).eq("account_label", account_label).execute()
        except Exception:
            pass

    # ---------------------------------------------------------------
    # 内部ヘルパー
    # ---------------------------------------------------------------
    def _get_row(self, user_id: str, account_label: str) -> Optional[dict]:
        result = (
            self.supabase.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .eq("account_label", account_label)
            .execute()
        )
        return result.data[0] if result.data else None

    def _upsert(self, user_id: str, account_label: str, encrypted_data: str, **fields: Any) -> dict:
        # None のフィールドは送らない（既存値を消さない）
        payload = {k: v for k, v in fields.items() if v is not None}
        existing = (
            self.supabase.table(self.table)
            .select("id")
            .eq("user_id", user_id)
            .eq("account_label", account_label)
            .execute()
        )
        if existing.data:
            payload["encrypted_data"] = encrypted_data
            result = (
                self.supabase.table(self.table)
                .update(payload)
                .eq("user_id", user_id)
                .eq("account_label", account_label)
                .execute()
            )
        else:
            payload.update({
                "user_id": user_id,
                "account_label": account_label,
                "encrypted_data": encrypted_data,
            })
            result = self.supabase.table(self.table).insert(payload).execute()
        return result.data[0] if result.data else {}


_meta_ads_service: Optional[MetaAdsService] = None


def get_meta_ads_service() -> MetaAdsService:
    global _meta_ads_service
    if _meta_ads_service is None:
        _meta_ads_service = MetaAdsService()
    return _meta_ads_service
