"""
Message Detection Service - Phase 5A: Doneチャット検知
"""
from typing import Optional, List
from datetime import datetime
import logging

from app.services.supabase_client import get_supabase_client
from app.models.detection_schemas import (
    MessageSource,
    DetectionStatus,
    ContentType,
    DetectedMessageCreate,
)

logger = logging.getLogger(__name__)


class MessageDetectionService:
    """メッセージ検知サービス"""
    
    def __init__(self):
        self.supabase = get_supabase_client().client
    
    async def detect_message(
        self,
        user_id: str,
        source: MessageSource,
        content: str,
        source_id: Optional[str] = None,
        subject: Optional[str] = None,
        sender_info: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        メッセージを検知して保存する
        
        Args:
            user_id: ユーザーID
            source: メッセージソース（done_chat, gmail, line）
            content: メッセージ本文
            source_id: ソースでのメッセージID
            subject: 件名（メールの場合）
            sender_info: 送信者情報
            metadata: 追加メタデータ
        
        Returns:
            保存された検知メッセージ
        """
        # 重複チェック（source_idがある場合）
        if source_id:
            existing = self.supabase.table("detected_messages").select("id").eq(
                "source", source.value
            ).eq("source_id", source_id).execute()
            
            if existing.data:
                logger.info(f"Message already detected: {source.value}/{source_id}")
                return existing.data[0]
        
        # 検知メッセージを保存
        result = self.supabase.table("detected_messages").insert({
            "user_id": user_id,
            "source": source.value,
            "source_id": source_id,
            "content": content,
            "subject": subject,
            "sender_info": sender_info,
            "metadata": metadata,
            "status": DetectionStatus.PENDING.value,
        }).execute()
        
        if result.data:
            logger.info(f"Message detected: {source.value}/{source_id or result.data[0]['id']}")
            return result.data[0]
        
        raise ValueError("Failed to save detected message")
    
    async def get_detected_message(self, message_id: str) -> Optional[dict]:
        """検知メッセージを取得"""
        result = self.supabase.table("detected_messages").select(
            "*, attachments:message_attachments(*)"
        ).eq("id", message_id).execute()
        
        return result.data[0] if result.data else None
    
    async def get_detected_messages(
        self,
        user_id: str,
        source: Optional[MessageSource] = None,
        status: Optional[DetectionStatus] = None,
        content_type: Optional[ContentType] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[dict]:
        """検知メッセージ一覧を取得"""
        query = self.supabase.table("detected_messages").select(
            "*, attachments:message_attachments(*)"
        ).eq("user_id", user_id)
        
        if source:
            query = query.eq("source", source.value)
        if status:
            query = query.eq("status", status.value)
        if content_type:
            query = query.eq("content_type", content_type.value)
        
        query = query.order("created_at", desc=True).limit(limit).offset(offset)
        result = query.execute()
        
        return result.data or []
    
    async def update_message_status(
        self,
        message_id: str,
        status: DetectionStatus,
        content_type: Optional[ContentType] = None,
        processing_result: Optional[dict] = None,
    ) -> Optional[dict]:
        """検知メッセージのステータスを更新"""
        update_data = {"status": status.value}
        
        if content_type:
            update_data["content_type"] = content_type.value
        if processing_result:
            update_data["processing_result"] = processing_result
        if status == DetectionStatus.PROCESSED:
            update_data["processed_at"] = datetime.utcnow().isoformat()
        
        result = self.supabase.table("detected_messages").update(
            update_data
        ).eq("id", message_id).execute()
        
        return result.data[0] if result.data else None
    
    async def get_pending_messages(self, limit: int = 100) -> List[dict]:
        """未処理のメッセージを取得（バックグラウンド処理用）"""
        result = self.supabase.table("detected_messages").select(
            "*, attachments:message_attachments(*)"
        ).eq("status", DetectionStatus.PENDING.value).order(
            "created_at", desc=False
        ).limit(limit).execute()
        
        return result.data or []
    
    async def count_messages(
        self,
        user_id: str,
        source: Optional[MessageSource] = None,
        status: Optional[DetectionStatus] = None,
    ) -> int:
        """メッセージ数をカウント"""
        query = self.supabase.table("detected_messages").select(
            "id", count="exact"
        ).eq("user_id", user_id)
        
        if source:
            query = query.eq("source", source.value)
        if status:
            query = query.eq("status", status.value)
        
        result = query.execute()
        return result.count or 0


# シングルトンインスタンス
_detection_service: Optional[MessageDetectionService] = None


def get_detection_service() -> MessageDetectionService:
    """検知サービスのインスタンスを取得"""
    global _detection_service
    if _detection_service is None:
        _detection_service = MessageDetectionService()
    return _detection_service
