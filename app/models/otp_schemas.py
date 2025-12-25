"""
OTP Schemas - Pydantic models for Phase 9 OTP Automation
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class OTPSource(str, Enum):
    """OTPのソース"""
    EMAIL = "email"
    SMS = "sms"
    VOICE = "voice"  # Phase 10で実装


class OTPStatus(str, Enum):
    """OTPの状態"""
    PENDING = "pending"         # 抽出待ち
    EXTRACTED = "extracted"     # 抽出済み
    USED = "used"               # 使用済み
    EXPIRED = "expired"         # 期限切れ


# ==================== OTP Extraction Schemas ====================

class OTPExtractionRequest(BaseModel):
    """OTP抽出リクエスト"""
    service: Optional[str] = Field(None, description="対象サービス（amazon, ex_reservation等）")
    max_age_minutes: int = Field(5, description="最大経過時間（分）", ge=1, le=30)
    sender_filter: Optional[str] = Field(None, description="送信元フィルタ（ドメイン等）")


class OTPResult(BaseModel):
    """OTP抽出結果"""
    id: str
    code: str
    source: OTPSource
    sender: Optional[str] = None
    subject: Optional[str] = None
    service: Optional[str] = None
    extracted_at: datetime
    expires_at: Optional[datetime] = None
    is_used: bool = False

    class Config:
        from_attributes = True


class OTPExtractionResponse(BaseModel):
    """OTP抽出レスポンス"""
    success: bool
    otp: Optional[OTPResult] = None
    message: Optional[str] = None


class OTPLatestResponse(BaseModel):
    """最新OTP取得レスポンス"""
    otp: Optional[OTPResult] = None


class OTPMarkUsedResponse(BaseModel):
    """OTP使用済みマークレスポンス"""
    success: bool
    message: str


class OTPHistoryResponse(BaseModel):
    """OTP履歴レスポンス"""
    extractions: List[OTPResult]
    total: int


# ==================== SMS Schemas ====================

class SMSStatusResponse(BaseModel):
    """SMS受信設定状態レスポンス"""
    configured: bool
    phone_number: Optional[str] = None
    webhook_url: Optional[str] = None
    is_active: bool = False


class SMSWebhookRequest(BaseModel):
    """Twilio SMS Webhookリクエスト（フォームデータから変換）"""
    from_number: str = Field(..., alias="From")
    to_number: str = Field(..., alias="To")
    body: str = Field(..., alias="Body")
    message_sid: Optional[str] = Field(None, alias="MessageSid")


# ==================== Service-specific OTP Patterns ====================

# 送信元ドメインのホワイトリスト（サービス別）
OTP_SENDER_DOMAINS = {
    "amazon": ["amazon.co.jp", "amazon.com", "amazon.jp"],
    "ex_reservation": ["expy.jp", "jr-central.co.jp", "smartex.jp"],
    "rakuten": ["rakuten.co.jp", "rakuten.jp"],
    "line": ["line.me", "line.biz"],
    "google": ["google.com", "google.co.jp"],
    "microsoft": ["microsoft.com", "live.com", "outlook.com"],
    "yahoo": ["yahoo.co.jp", "yahoo.com"],
    "apple": ["apple.com", "icloud.com"],
}

# OTP抽出パターン（優先順位順）
OTP_PATTERNS = [
    # 明示的なラベル付きパターン
    r'(?:認証コード|確認コード|ワンタイムパスワード|OTP|verification code|passcode|セキュリティコード)[：:\s]*[「\[]?(\d{4,8})[」\]]?',
    r'(?:コード|code)[：:\s]*[「\[]?(\d{4,8})[」\]]?',
    # 「コードは」パターン
    r'(?:コードは|code is)[：:\s]*[「\[]?(\d{4,8})[」\]]?',
    # 独立した6桁の数字（最も一般的）
    r'(?<!\d)(\d{6})(?!\d)',
]

# OTP入力フィールドの検知セレクタ（Playwright用）
OTP_FIELD_SELECTORS = [
    'input[name*="otp"]',
    'input[name*="code"]',
    'input[name*="verification"]',
    'input[name*="token"]',
    'input[placeholder*="認証コード"]',
    'input[placeholder*="確認コード"]',
    'input[placeholder*="ワンタイム"]',
    'input[aria-label*="認証コード"]',
    'input[aria-label*="verification"]',
    '#otp',
    '#verificationCode',
    '#authCode',
    '#mfaCode',
]

# OTP入力画面の検知テキスト
OTP_PAGE_INDICATORS = [
    "認証コード",
    "確認コード",
    "ワンタイムパスワード",
    "セキュリティコード",
    "Enter OTP",
    "Enter verification code",
    "Two-factor authentication",
    "2段階認証",
    "2要素認証",
    "SMS認証",
    "メール認証",
]


