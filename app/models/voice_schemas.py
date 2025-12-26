"""
Phase 10: Voice Communication Schemas
音声通話関連のPydanticモデル
"""
from datetime import datetime
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field


# ========================================
# Enums
# ========================================

class CallDirection(str, Enum):
    """通話方向"""
    INBOUND = "inbound"   # 受電
    OUTBOUND = "outbound"  # 架電


class CallStatus(str, Enum):
    """通話状態"""
    INITIATED = "initiated"       # 発信開始
    RINGING = "ringing"           # 呼び出し中
    IN_PROGRESS = "in_progress"   # 通話中
    COMPLETED = "completed"       # 正常終了
    BUSY = "busy"                 # 話し中
    NO_ANSWER = "no_answer"       # 応答なし
    FAILED = "failed"             # 失敗
    CANCELED = "canceled"         # キャンセル


class CallPurpose(str, Enum):
    """通話目的"""
    RESERVATION = "reservation"          # 予約
    INQUIRY = "inquiry"                  # 問い合わせ
    OTP_VERIFICATION = "otp_verification"  # OTP認証
    CONFIRMATION = "confirmation"        # 確認
    CANCELLATION = "cancellation"        # キャンセル
    OTHER = "other"                      # その他


class PhoneRuleType(str, Enum):
    """電話番号ルールタイプ"""
    WHITELIST = "whitelist"
    BLACKLIST = "blacklist"


class MessageRole(str, Enum):
    """メッセージの発言者"""
    USER = "user"        # 相手（電話の相手）
    ASSISTANT = "assistant"  # AI


# ========================================
# Voice Call Schemas
# ========================================

class VoiceCallBase(BaseModel):
    """通話の基本情報"""
    direction: CallDirection
    from_number: str
    to_number: str
    purpose: Optional[CallPurpose] = None


class VoiceCallCreate(BaseModel):
    """架電開始リクエスト"""
    to_number: str = Field(..., description="発信先電話番号（E.164形式）")
    purpose: CallPurpose = Field(default=CallPurpose.OTHER, description="通話目的")
    context: Optional[dict] = Field(default=None, description="会話コンテキスト（予約詳細など）")
    task_id: Optional[str] = Field(default=None, description="関連タスクID")


class VoiceCallResponse(BaseModel):
    """通話情報レスポンス"""
    id: str
    call_sid: str
    direction: CallDirection
    status: CallStatus
    from_number: str
    to_number: str
    started_at: datetime
    answered_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    transcription: Optional[str] = None
    summary: Optional[str] = None
    purpose: Optional[CallPurpose] = None
    task_id: Optional[str] = None

    class Config:
        from_attributes = True


class VoiceCallListResponse(BaseModel):
    """通話履歴一覧レスポンス"""
    calls: List[VoiceCallResponse]
    total: int


# ========================================
# Voice Call Messages
# ========================================

class VoiceCallMessageCreate(BaseModel):
    """通話メッセージ作成"""
    role: MessageRole
    content: str


class VoiceCallMessageResponse(BaseModel):
    """通話メッセージレスポンス"""
    id: str
    call_id: str
    role: MessageRole
    content: str
    timestamp: datetime

    class Config:
        from_attributes = True


# ========================================
# Phone Number Rules
# ========================================

class PhoneNumberRuleCreate(BaseModel):
    """電話番号ルール作成"""
    phone_number: str = Field(..., description="電話番号（E.164形式）")
    rule_type: PhoneRuleType = Field(..., description="ルールタイプ")
    label: Optional[str] = Field(default=None, description="相手の名前・会社名")
    notes: Optional[str] = Field(default=None, description="備考")


class PhoneNumberRuleResponse(BaseModel):
    """電話番号ルールレスポンス"""
    id: str
    phone_number: str
    rule_type: PhoneRuleType
    label: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PhoneNumberRuleListResponse(BaseModel):
    """電話番号ルール一覧レスポンス"""
    rules: List[PhoneNumberRuleResponse]


# ========================================
# Voice Settings
# ========================================

class VoiceSettingsUpdate(BaseModel):
    """音声設定更新"""
    inbound_enabled: Optional[bool] = Field(default=None, description="受電を受けるかどうか")
    default_greeting: Optional[str] = Field(default=None, description="デフォルトの挨拶")
    auto_answer_whitelist: Optional[bool] = Field(default=None, description="ホワイトリストは自動応答")
    record_calls: Optional[bool] = Field(default=None, description="通話を録音するか")
    notify_via_chat: Optional[bool] = Field(default=None, description="チャットに通知するか")
    elevenlabs_voice_id: Optional[str] = Field(default=None, description="ElevenLabsの音声ID")


class VoiceSettingsResponse(BaseModel):
    """音声設定レスポンス"""
    id: str
    user_id: str
    inbound_enabled: bool = False
    default_greeting: Optional[str] = None
    auto_answer_whitelist: bool = False
    record_calls: bool = False
    notify_via_chat: bool = True
    elevenlabs_voice_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ========================================
# Webhook Schemas (Twilio)
# ========================================

class TwilioVoiceWebhook(BaseModel):
    """Twilio Voice Webhook"""
    CallSid: str
    CallStatus: Optional[str] = None
    From: Optional[str] = None
    To: Optional[str] = None
    Direction: Optional[str] = None
    CallerName: Optional[str] = None
    CallDuration: Optional[str] = None


# ========================================
# API Response Wrappers
# ========================================

class VoiceCallStartResponse(BaseModel):
    """架電開始レスポンス"""
    success: bool
    call: VoiceCallResponse


class VoiceCallEndResponse(BaseModel):
    """通話終了レスポンス"""
    success: bool
    call: VoiceCallResponse


class InboundToggleRequest(BaseModel):
    """受電オン/オフ切り替えリクエスト"""
    enabled: bool


class InboundToggleResponse(BaseModel):
    """受電オン/オフ切り替えレスポンス"""
    success: bool
    inbound_enabled: bool



