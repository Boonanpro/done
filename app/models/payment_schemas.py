"""
Payment Execution Schemas - Pydantic models for Phase 8
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class BankType(str, Enum):
    """銀行タイプ"""
    SIMULATION = "simulation"    # シミュレーション（テスト用）
    SBI = "sbi"                  # 住信SBIネット銀行
    MUFG = "mufg"                # 三菱UFJ銀行
    SMBC = "smbc"                # 三井住友銀行
    MIZUHO = "mizuho"            # みずほ銀行
    RAKUTEN = "rakuten"          # 楽天銀行


class PaymentExecutionStatus(str, Enum):
    """支払い実行ステータス"""
    PENDING = "pending"
    EXECUTING = "executing"
    AWAITING_OTP = "awaiting_otp"
    COMPLETED = "completed"
    FAILED = "failed"


# ==================== Saved Bank Account Schemas ====================

class SavedBankAccountCreate(BaseModel):
    """振込先作成リクエスト"""
    display_name: str = Field(..., max_length=100, description="表示名（会社名など）")
    bank_name: str = Field(..., max_length=100, description="銀行名")
    bank_code: Optional[str] = Field(None, max_length=4, description="銀行コード（4桁）")
    branch_name: str = Field(..., max_length=100, description="支店名")
    branch_code: Optional[str] = Field(None, max_length=3, description="支店コード（3桁）")
    account_type: str = Field(..., pattern=r'^(普通|当座)$', description="口座種別: 普通 or 当座")
    account_number: str = Field(..., max_length=7, description="口座番号（最大7桁）")
    account_holder: str = Field(..., max_length=100, description="口座名義（カタカナ）")


class SavedBankAccountUpdate(BaseModel):
    """振込先更新リクエスト"""
    display_name: Optional[str] = Field(None, max_length=100)
    bank_name: Optional[str] = Field(None, max_length=100)
    bank_code: Optional[str] = Field(None, max_length=4)
    branch_name: Optional[str] = Field(None, max_length=100)
    branch_code: Optional[str] = Field(None, max_length=3)
    account_type: Optional[str] = Field(None, pattern=r'^(普通|当座)$')
    account_number: Optional[str] = Field(None, max_length=7)
    account_holder: Optional[str] = Field(None, max_length=100)


class SavedBankAccountResponse(BaseModel):
    """振込先レスポンス"""
    id: str
    user_id: str
    display_name: str
    bank_name: str
    bank_code: Optional[str] = None
    branch_name: str
    branch_code: Optional[str] = None
    account_type: str
    account_number: str  # マスク済み表示用
    account_number_full: Optional[str] = None  # 詳細表示用（オプション）
    account_holder: str
    is_verified: bool = False
    last_used_at: Optional[datetime] = None
    use_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SavedBankAccountListResponse(BaseModel):
    """振込先一覧レスポンス"""
    bank_accounts: List[SavedBankAccountResponse]
    total: int


# ==================== Payment Execution Schemas ====================

class PaymentExecuteRequest(BaseModel):
    """支払い実行リクエスト"""
    bank_type: BankType = BankType.SIMULATION
    saved_recipient_id: Optional[str] = None  # 保存済み振込先を使用する場合
    use_invoice_bank_info: bool = True  # 請求書の振込先情報を使用


class PaymentExecuteResponse(BaseModel):
    """支払い実行開始レスポンス"""
    invoice_id: str
    execution_id: str
    status: PaymentExecutionStatus
    message: str


class PaymentStatusResponse(BaseModel):
    """支払い実行状況レスポンス"""
    invoice_id: str
    execution_id: Optional[str] = None
    status: PaymentExecutionStatus
    current_step: Optional[str] = None
    steps_completed: List[str] = []
    steps_remaining: List[str] = []
    requires_otp: bool = False
    transaction_id: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class OTPSubmitRequest(BaseModel):
    """OTP送信リクエスト"""
    otp_code: str = Field(..., description="ワンタイムパスワード")


class OTPSubmitResponse(BaseModel):
    """OTP送信レスポンス"""
    success: bool
    message: str
    status: PaymentExecutionStatus


# ==================== Payment Execution Log Schemas ====================

class PaymentExecutionLogResponse(BaseModel):
    """支払い実行ログレスポンス"""
    id: str
    invoice_id: str
    payment_type: str
    success: bool
    transaction_id: Optional[str] = None
    error_message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True

