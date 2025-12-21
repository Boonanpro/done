"""
Detection Schemas - Pydantic models for Phase 5 Message Detection
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class MessageSource(str, Enum):
    """メッセージのソース"""
    DONE_CHAT = "done_chat"
    GMAIL = "gmail"
    LINE = "line"


class DetectionStatus(str, Enum):
    """検知メッセージの処理状態"""
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class ContentType(str, Enum):
    """コンテンツの分類"""
    INVOICE = "invoice"       # 請求書
    OTP = "otp"               # ワンタイムパスワード
    NOTIFICATION = "notification"  # 通知
    GENERAL = "general"       # 一般メッセージ


class StorageType(str, Enum):
    """ストレージタイプ"""
    LOCAL = "local"
    SUPABASE = "supabase"


# ==================== Detected Message Schemas ====================

class DetectedMessageBase(BaseModel):
    """検知メッセージの基本スキーマ"""
    source: MessageSource
    source_id: Optional[str] = None
    content: Optional[str] = None
    subject: Optional[str] = None
    sender_info: Optional[dict] = None
    metadata: Optional[dict] = None


class DetectedMessageCreate(DetectedMessageBase):
    """検知メッセージ作成用スキーマ"""
    user_id: str


class DetectedMessageResponse(DetectedMessageBase):
    """検知メッセージレスポンス"""
    id: str
    user_id: str
    status: DetectionStatus = DetectionStatus.PENDING
    content_type: Optional[ContentType] = None
    processing_result: Optional[dict] = None
    processed_at: Optional[datetime] = None
    created_at: datetime
    attachments: List["AttachmentResponse"] = []

    class Config:
        from_attributes = True


class DetectedMessagesListResponse(BaseModel):
    """検知メッセージ一覧レスポンス"""
    messages: List[DetectedMessageResponse]
    total: int


# ==================== Attachment Schemas ====================

class AttachmentBase(BaseModel):
    """添付ファイルの基本スキーマ"""
    filename: str
    mime_type: str
    file_size: Optional[int] = None


class AttachmentCreate(AttachmentBase):
    """添付ファイル作成用スキーマ"""
    detected_message_id: str
    storage_path: str
    storage_type: StorageType = StorageType.LOCAL
    checksum: Optional[str] = None


class AttachmentResponse(AttachmentBase):
    """添付ファイルレスポンス"""
    id: str
    detected_message_id: str
    storage_type: StorageType
    checksum: Optional[str] = None
    extracted_text: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AttachmentsListResponse(BaseModel):
    """添付ファイル一覧レスポンス"""
    attachments: List[AttachmentResponse]


# ==================== Gmail Connection Schemas ====================

class GmailSetupResponse(BaseModel):
    """Gmail OAuth設定開始レスポンス"""
    auth_url: str
    message: str = "Please visit this URL to authorize Gmail access"


class GmailCallbackRequest(BaseModel):
    """Gmail OAuthコールバックリクエスト"""
    code: str


class GmailCallbackResponse(BaseModel):
    """Gmail OAuthコールバックレスポンス"""
    success: bool
    email: Optional[str] = None
    message: str


class GmailStatusResponse(BaseModel):
    """Gmail連携状態レスポンス"""
    connected: bool
    email: Optional[str] = None
    last_sync: Optional[datetime] = None
    is_active: bool = False


class GmailSyncResponse(BaseModel):
    """Gmail手動同期レスポンス"""
    success: bool
    new_messages: int
    message_ids: List[str] = []


class GmailDisconnectResponse(BaseModel):
    """Gmail連携解除レスポンス"""
    success: bool
    message: str


# Update forward references
DetectedMessageResponse.model_rebuild()
