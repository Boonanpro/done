"""
Invoice Management Schemas - Pydantic models for Phase 7
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class InvoiceStatus(str, Enum):
    """請求書ステータス"""
    PENDING = "pending"           # 承認待ち
    APPROVED = "approved"         # 承認済み
    SCHEDULED = "scheduled"       # 支払いスケジュール済み
    EXECUTING = "executing"       # 支払い実行中
    PAID = "paid"                 # 支払い完了
    REJECTED = "rejected"         # 却下
    FAILED = "failed"             # 支払い失敗


class InvoiceSource(str, Enum):
    """請求書ソース"""
    EMAIL = "email"               # メールから検出
    CHAT = "chat"                 # チャットから検出
    MANUAL = "manual"             # 手動入力


class PaymentType(str, Enum):
    """支払い方法タイプ"""
    BANK_TRANSFER = "bank_transfer"   # 銀行振込
    CREDIT_CARD = "credit_card"       # クレジットカード
    CONVENIENCE = "convenience"       # コンビニ払い
    AUTO_DEBIT = "auto_debit"         # 口座振替


# ==================== Bank Info Schemas ====================

class BankInfo(BaseModel):
    """振込先情報"""
    bank_name: str
    branch_name: Optional[str] = None
    branch_code: Optional[str] = None
    account_type: Optional[str] = None  # 普通, 当座
    account_number: Optional[str] = None
    account_holder: Optional[str] = None


# ==================== Invoice Extraction Schemas ====================

class InvoiceExtractionResult(BaseModel):
    """請求書情報抽出結果"""
    success: bool
    amount: Optional[int] = None
    currency: str = "JPY"
    due_date: Optional[datetime] = None
    invoice_number: Optional[str] = None
    invoice_month: Optional[str] = None
    issuer_name: Optional[str] = None
    issuer_address: Optional[str] = None
    bank_info: Optional[BankInfo] = None
    raw_extracted_data: Optional[Dict[str, Any]] = None
    confidence_score: Optional[float] = None
    error: Optional[str] = None


# ==================== Invoice API Schemas ====================

class InvoiceCreateRequest(BaseModel):
    """請求書作成リクエスト"""
    sender_name: str
    amount: int = Field(gt=0, description="請求金額（税込）")
    due_date: datetime
    invoice_number: Optional[str] = None
    invoice_month: Optional[str] = None
    source: InvoiceSource = InvoiceSource.MANUAL
    source_channel: str = "manual"
    source_url: Optional[str] = None
    raw_content: Optional[str] = None
    bank_info: Optional[BankInfo] = None
    sender_contact_type: Optional[str] = None
    sender_contact_id: Optional[str] = None
    pdf_data: Optional[str] = None
    screenshot: Optional[str] = None


class InvoiceFromContentRequest(BaseModel):
    """コンテンツから請求書作成リクエスト"""
    message_id: str
    override_amount: Optional[int] = None
    override_due_date: Optional[datetime] = None
    override_sender_name: Optional[str] = None


class InvoiceUpdateRequest(BaseModel):
    """請求書更新リクエスト"""
    sender_name: Optional[str] = None
    amount: Optional[int] = Field(default=None, gt=0)
    due_date: Optional[datetime] = None
    invoice_number: Optional[str] = None
    invoice_month: Optional[str] = None
    bank_info: Optional[BankInfo] = None
    scheduled_payment_time: Optional[datetime] = None


class InvoiceApproveRequest(BaseModel):
    """請求書承認リクエスト"""
    payment_method_id: Optional[str] = None
    payment_type: PaymentType = PaymentType.BANK_TRANSFER
    scheduled_time_override: Optional[datetime] = None


class InvoiceRejectRequest(BaseModel):
    """請求書却下リクエスト"""
    reason: Optional[str] = None


class InvoiceResponse(BaseModel):
    """請求書レスポンス"""
    id: str
    user_id: str
    sender_name: str
    sender_contact_type: Optional[str] = None
    sender_contact_id: Optional[str] = None
    amount: int
    due_date: datetime
    invoice_number: Optional[str] = None
    invoice_month: Optional[str] = None
    source: str
    source_channel: str
    source_url: Optional[str] = None
    bank_info: Optional[Dict[str, Any]] = None
    status: InvoiceStatus
    scheduled_payment_time: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    paid_at: Optional[datetime] = None
    transaction_id: Optional[str] = None
    error_message: Optional[str] = None
    is_duplicate: bool = False
    notification_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class InvoiceListResponse(BaseModel):
    """請求書一覧レスポンス"""
    invoices: List[InvoiceResponse]
    total: int
    page: int
    page_size: int


class InvoiceHistoryItem(BaseModel):
    """支払い履歴アイテム"""
    id: str
    original_invoice_id: Optional[str] = None
    sender_name: str
    amount: int
    due_date: datetime
    invoice_number: Optional[str] = None
    invoice_month: Optional[str] = None
    payment_method_display: Optional[str] = None
    payment_type: Optional[str] = None
    transaction_id: Optional[str] = None
    paid_at: datetime
    created_at: datetime


class InvoiceHistoryResponse(BaseModel):
    """支払い履歴レスポンス"""
    history: List[InvoiceHistoryItem]
    total: int


# ==================== Schedule Calculation Schemas ====================

class ScheduleCalculationRequest(BaseModel):
    """スケジュール計算リクエスト"""
    due_date: datetime
    invoice_month: Optional[str] = None
    consider_holidays: bool = False


class ScheduleCalculationResponse(BaseModel):
    """スケジュール計算レスポンス"""
    scheduled_payment_time: datetime
    due_date: datetime
    days_until_payment: int
    is_holiday_adjusted: bool = False


# ==================== Duplicate Check Schemas ====================

class DuplicateCheckResult(BaseModel):
    """重複チェック結果"""
    is_duplicate: bool
    duplicate_invoice_id: Optional[str] = None
    duplicate_hash: str
    message: Optional[str] = None


# ==================== Notification Schemas ====================

class InvoiceNotificationData(BaseModel):
    """請求書通知データ"""
    invoice_id: str
    sender_name: str
    amount: int
    due_date: datetime
    status: InvoiceStatus
    scheduled_payment_time: Optional[datetime] = None

