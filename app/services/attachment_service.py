"""
Attachment Service - Phase 5C: 添付ファイル取得・管理
"""
import os
import hashlib
import logging
from pathlib import Path
from typing import Optional, List, Tuple
from datetime import datetime

from app.config import settings
from app.services.supabase_client import get_supabase_client
from app.services.gmail_service import get_gmail_service
from app.models.detection_schemas import StorageType

logger = logging.getLogger(__name__)

# 対応するMIMEタイプ
SUPPORTED_MIME_TYPES = {
    'application/pdf': '.pdf',
    'image/png': '.png',
    'image/jpeg': '.jpg',
    'image/jpg': '.jpg',
    'image/gif': '.gif',
}

# 最大ファイルサイズ（バイト）
MAX_FILE_SIZE = settings.ATTACHMENT_MAX_SIZE_MB * 1024 * 1024


class AttachmentService:
    """添付ファイル管理サービス"""
    
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.storage_path = Path(settings.ATTACHMENT_STORAGE_PATH)
        self._ensure_storage_dir()
    
    def _ensure_storage_dir(self):
        """ストレージディレクトリを確保"""
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    def _calculate_checksum(self, data: bytes) -> str:
        """SHA256チェックサムを計算"""
        return hashlib.sha256(data).hexdigest()
    
    def _get_storage_path(self, user_id: str, filename: str, checksum: str) -> Path:
        """ストレージパスを生成"""
        # ユーザーごとにサブディレクトリを作成
        user_dir = self.storage_path / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        
        # ファイル名にチェックサムを含める（重複対策）
        ext = Path(filename).suffix or '.bin'
        safe_name = f"{checksum[:16]}_{Path(filename).stem[:50]}{ext}"
        
        return user_dir / safe_name
    
    async def save_attachment(
        self,
        detected_message_id: str,
        user_id: str,
        filename: str,
        mime_type: str,
        data: bytes,
    ) -> dict:
        """
        添付ファイルを保存
        
        Args:
            detected_message_id: 検知メッセージID
            user_id: ユーザーID
            filename: ファイル名
            mime_type: MIMEタイプ
            data: ファイルデータ
        
        Returns:
            保存された添付ファイル情報
        """
        # ファイルサイズチェック
        file_size = len(data)
        if file_size > MAX_FILE_SIZE:
            raise ValueError(f"File size exceeds limit: {file_size} > {MAX_FILE_SIZE}")
        
        # MIMEタイプチェック
        if mime_type not in SUPPORTED_MIME_TYPES:
            logger.warning(f"Unsupported MIME type: {mime_type}, saving anyway")
        
        # チェックサム計算
        checksum = self._calculate_checksum(data)
        
        # 重複チェック
        existing = self.supabase.table("message_attachments").select("id").eq(
            "checksum", checksum
        ).eq("detected_message_id", detected_message_id).execute()
        
        if existing.data:
            logger.info(f"Attachment already exists: {checksum}")
            return existing.data[0]
        
        # ストレージパスを生成
        storage_path = self._get_storage_path(user_id, filename, checksum)
        
        # ファイルを保存
        with open(storage_path, 'wb') as f:
            f.write(data)
        
        logger.info(f"Attachment saved: {storage_path}")
        
        # DBに記録
        result = self.supabase.table("message_attachments").insert({
            "detected_message_id": detected_message_id,
            "filename": filename,
            "mime_type": mime_type,
            "file_size": file_size,
            "storage_path": str(storage_path),
            "storage_type": StorageType.LOCAL.value,
            "checksum": checksum,
        }).execute()
        
        if result.data:
            return result.data[0]
        
        raise ValueError("Failed to save attachment record")
    
    async def get_attachment(self, attachment_id: str) -> Optional[dict]:
        """添付ファイル情報を取得"""
        result = self.supabase.table("message_attachments").select("*").eq("id", attachment_id).execute()
        return result.data[0] if result.data else None
    
    async def get_attachment_data(self, attachment_id: str) -> Tuple[bytes, str, str]:
        """
        添付ファイルデータを取得
        
        Returns:
            (data, filename, mime_type)
        """
        attachment = await self.get_attachment(attachment_id)
        if not attachment:
            raise ValueError("Attachment not found")
        
        storage_path = Path(attachment["storage_path"])
        
        if attachment["storage_type"] == StorageType.LOCAL.value:
            if not storage_path.exists():
                raise ValueError("Attachment file not found")
            
            with open(storage_path, 'rb') as f:
                data = f.read()
            
            return data, attachment["filename"], attachment["mime_type"]
        else:
            # Supabase Storage（将来対応）
            raise ValueError("Supabase storage not yet implemented")
    
    async def get_attachments_for_message(self, detected_message_id: str) -> List[dict]:
        """検知メッセージの添付ファイル一覧を取得"""
        result = self.supabase.table("message_attachments").select("*").eq(
            "detected_message_id", detected_message_id
        ).order("created_at").execute()
        
        return result.data or []
    
    async def download_gmail_attachments(
        self,
        user_id: str,
        detected_message_id: str,
    ) -> List[dict]:
        """
        Gmailメッセージの添付ファイルをダウンロード・保存
        
        Args:
            user_id: ユーザーID
            detected_message_id: 検知メッセージID
        
        Returns:
            保存された添付ファイル一覧
        """
        # 検知メッセージを取得
        message_result = self.supabase.table("detected_messages").select("*").eq(
            "id", detected_message_id
        ).execute()
        
        if not message_result.data:
            raise ValueError("Detected message not found")
        
        message = message_result.data[0]
        
        if message["source"] != "gmail":
            raise ValueError("Message is not from Gmail")
        
        # 添付ファイル情報を取得
        metadata = message.get("metadata", {})
        attachments_info = metadata.get("attachments", [])
        
        if not attachments_info:
            return []
        
        gmail_service = get_gmail_service()
        saved_attachments = []
        
        for att_info in attachments_info:
            try:
                # ファイルサイズチェック
                if att_info.get("size", 0) > MAX_FILE_SIZE:
                    logger.warning(f"Attachment too large: {att_info.get('filename')}")
                    continue
                
                # MIMEタイプチェック（オプショナル）
                mime_type = att_info.get("mime_type", "application/octet-stream")
                
                # ダウンロード
                data, filename, mime_type = await gmail_service.get_attachment(
                    user_id=user_id,
                    message_id=att_info["message_id"],
                    attachment_id=att_info["attachment_id"],
                )
                
                # 保存
                attachment = await self.save_attachment(
                    detected_message_id=detected_message_id,
                    user_id=user_id,
                    filename=filename,
                    mime_type=mime_type,
                    data=data,
                )
                
                saved_attachments.append(attachment)
                
            except Exception as e:
                logger.error(f"Failed to download attachment: {e}")
                continue
        
        return saved_attachments
    
    async def delete_attachment(self, attachment_id: str) -> bool:
        """添付ファイルを削除"""
        attachment = await self.get_attachment(attachment_id)
        if not attachment:
            return False
        
        # ファイルを削除
        if attachment["storage_type"] == StorageType.LOCAL.value:
            storage_path = Path(attachment["storage_path"])
            if storage_path.exists():
                storage_path.unlink()
        
        # DBから削除
        self.supabase.table("message_attachments").delete().eq("id", attachment_id).execute()
        
        return True
    
    async def cleanup_old_attachments(self, days: int = 30) -> int:
        """古い添付ファイルを削除"""
        from datetime import timedelta
        
        cutoff_date = (datetime.utcnow() - timedelta(days=days)).isoformat()
        
        # 古いレコードを取得
        result = self.supabase.table("message_attachments").select("*").lt(
            "created_at", cutoff_date
        ).execute()
        
        deleted_count = 0
        for attachment in result.data or []:
            try:
                await self.delete_attachment(attachment["id"])
                deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to delete attachment: {e}")
        
        return deleted_count


# シングルトンインスタンス
_attachment_service: Optional[AttachmentService] = None


def get_attachment_service() -> AttachmentService:
    """添付ファイルサービスのインスタンスを取得"""
    global _attachment_service
    if _attachment_service is None:
        _attachment_service = AttachmentService()
    return _attachment_service








