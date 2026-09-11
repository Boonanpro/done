"""
Supabase Client Service
"""
from typing import Optional, Any
import os
from supabase import create_client, Client, ClientOptions
from datetime import datetime, timezone
import uuid

import httpx

from app.config import settings
from app.services.encryption import get_encryption_service


# 同期クライアントはイベントループ上で呼ばれる箇所が多い。既定の 120 秒待ちだと
# 死んだ接続の上で core 全体が数分固まる（2026-09-11: 部屋オープンが画面側で 7 分、
# サーバー処理は 0.5 秒）。1 呼び出しの上限を短くし、古い keep-alive 接続は
# 再利用前に捨てて「Server disconnected」を減らす。
DB_TIMEOUT_S = float(os.environ.get("DAN_DB_TIMEOUT_S", "15"))
DB_CONNECT_TIMEOUT_S = float(os.environ.get("DAN_DB_CONNECT_TIMEOUT_S", "5"))
DB_KEEPALIVE_EXPIRY_S = float(os.environ.get("DAN_DB_KEEPALIVE_EXPIRY_S", "20"))


def build_client_options() -> ClientOptions:
    http_client = httpx.Client(
        timeout=httpx.Timeout(DB_TIMEOUT_S, connect=DB_CONNECT_TIMEOUT_S),
        limits=httpx.Limits(
            max_connections=50,
            max_keepalive_connections=20,
            keepalive_expiry=DB_KEEPALIVE_EXPIRY_S,
        ),
        follow_redirects=True,
        http2=True,
    )
    return ClientOptions(
        postgrest_client_timeout=DB_TIMEOUT_S,
        storage_client_timeout=max(DB_TIMEOUT_S, 60),
        httpx_client=http_client,
    )


class SupabaseClient:
    """Supabaseクライアント"""

    def __init__(self):
        """クライアントを初期化"""
        if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
            raise ValueError("Supabase URLとKeyを設定してください")

        # バックエンド処理ではservice_roleキーを優先使用（RLSバイパス）
        key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_KEY

        self.client: Client = create_client(
            settings.SUPABASE_URL,
            key,
            options=build_client_options(),
        )
        self.encryption = get_encryption_service()
    
    # ==================== User Operations ====================
    
    async def create_user(
        self,
        email: Optional[str] = None,
        line_user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """ユーザーを作成"""
        user_id = str(uuid.uuid4())
        data = {
            "id": user_id,
            "email": email,
            "line_user_id": line_user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        result = self.client.table("users").insert(data).execute()
        return result.data[0] if result.data else None
    
    async def get_user(self, user_id: str) -> Optional[dict[str, Any]]:
        """ユーザーを取得"""
        result = self.client.table("users").select("*").eq("id", user_id).execute()
        return result.data[0] if result.data else None
    
    async def get_user_by_line_id(self, line_user_id: str) -> Optional[dict[str, Any]]:
        """LINE IDでユーザーを取得"""
        result = self.client.table("users").select("*").eq("line_user_id", line_user_id).execute()
        return result.data[0] if result.data else None
    
    # ==================== Task Operations ====================
    
    async def create_task(
        self,
        user_id: Optional[str],
        task_type: str,
        original_wish: str,
        proposed_actions: list[str] = None,
    ) -> dict[str, Any]:
        """タスクを作成"""
        task_id = str(uuid.uuid4())
        data = {
            "id": task_id,
            "user_id": user_id,
            "type": task_type,
            "status": "pending",
            "original_wish": original_wish,
            "proposed_actions": proposed_actions or [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        result = self.client.table("tasks").insert(data).execute()
        return result.data[0] if result.data else None
    
    async def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        """タスクを取得"""
        result = self.client.table("tasks").select("*").eq("id", task_id).execute()
        return result.data[0] if result.data else None
    
    async def update_task(
        self,
        task_id: str,
        **updates,
    ) -> Optional[dict[str, Any]]:
        """タスクを更新"""
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        result = self.client.table("tasks").update(updates).eq("id", task_id).execute()
        return result.data[0] if result.data else None
    
    async def list_tasks(
        self,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """タスク一覧を取得"""
        query = self.client.table("tasks").select("*")
        
        if user_id:
            query = query.eq("user_id", user_id)
        if status:
            query = query.eq("status", status)
        
        query = query.order("created_at", desc=True).limit(limit)
        result = query.execute()
        
        return result.data or []
    
    # ==================== Credential Operations ====================
    
    async def save_credential(
        self,
        user_id: str,
        service_name: str,
        username: str,
        password: str,
        extra: dict[str, Any] = None,
    ) -> dict[str, Any]:
        """認証情報を暗号化して保存"""
        encrypted_data = self.encryption.encrypt_credential(
            username=username,
            password=password,
            extra=extra,
        )
        
        credential_id = str(uuid.uuid4())
        data = {
            "id": credential_id,
            "user_id": user_id,
            "service_name": service_name,
            "encrypted_data": encrypted_data.decode(),  # Base64文字列として保存
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        result = self.client.table("credentials").insert(data).execute()
        return result.data[0] if result.data else None
    
    async def get_credential(
        self,
        user_id: str,
        service_name: str,
    ) -> Optional[dict[str, Any]]:
        """認証情報を取得して復号"""
        result = (
            self.client.table("credentials")
            .select("*")
            .eq("user_id", user_id)
            .eq("service_name", service_name)
            .execute()
        )
        
        if not result.data:
            return None
        
        credential = result.data[0]
        encrypted_data = credential["encrypted_data"].encode()
        decrypted = self.encryption.decrypt_credential(encrypted_data)
        
        return {
            "id": credential["id"],
            "service_name": credential["service_name"],
            **decrypted,
        }
    
    # ==================== Message Operations ====================
    
    async def save_message(
        self,
        task_id: str,
        channel: str,
        direction: str,
        content: str,
        metadata: dict[str, Any] = None,
    ) -> dict[str, Any]:
        """メッセージを保存"""
        message_id = str(uuid.uuid4())
        data = {
            "id": message_id,
            "task_id": task_id,
            "channel": channel,
            "direction": direction,
            "content": content,
            "metadata": metadata,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        result = self.client.table("messages").insert(data).execute()
        return result.data[0] if result.data else None
    
    async def get_messages(
        self,
        task_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """タスクに関連するメッセージを取得"""
        result = (
            self.client.table("messages")
            .select("*")
            .eq("task_id", task_id)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        
        return result.data or []


# シングルトンインスタンス
_supabase_client: SupabaseClient = None


def get_supabase_client() -> SupabaseClient:
    """Supabaseクライアントのシングルトンインスタンスを取得"""
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = SupabaseClient()
    return _supabase_client

