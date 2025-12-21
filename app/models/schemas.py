"""
Pydantic Schemas for Data Models
"""
from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from enum import Enum
import uuid


class TaskStatus(str, Enum):
    """タスクのステータス"""
    PENDING = "pending"
    ANALYZING = "analyzing"
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(str, Enum):
    """タスクの種類"""
    EMAIL = "email"
    LINE = "line"
    PURCHASE = "purchase"
    PAYMENT = "payment"
    RESEARCH = "research"
    TRAVEL = "travel"
    OTHER = "other"


class SearchResultCategory(str, Enum):
    """検索結果のカテゴリ"""
    TRAIN = "train"
    BUS = "bus"
    FLIGHT = "flight"
    PRODUCT = "product"
    RESTAURANT = "restaurant"
    PROFESSIONAL = "professional"
    GENERAL = "general"


class User(BaseModel):
    """ユーザーモデル"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: Optional[str] = None
    line_user_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        from_attributes = True


class TaskRequest(BaseModel):
    """タスクリクエスト"""
    wish: str
    user_id: Optional[str] = None
    context: Optional[dict[str, Any]] = None


class TaskResponse(BaseModel):
    """タスクレスポンス"""
    id: str
    user_id: Optional[str]
    type: TaskType
    status: TaskStatus
    original_wish: str
    proposed_actions: list[str] = []
    execution_result: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class Credential(BaseModel):
    """認証情報モデル（暗号化用）"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    service_name: str
    encrypted_data: bytes
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        from_attributes = True


class Message(BaseModel):
    """メッセージモデル"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    channel: str  # "email", "line", etc.
    direction: str  # "inbound", "outbound"
    content: str
    metadata: Optional[dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        from_attributes = True


class EmailMessage(BaseModel):
    """メールメッセージ"""
    to: list[str]
    subject: str
    body: str
    cc: Optional[list[str]] = None
    bcc: Optional[list[str]] = None
    attachments: Optional[list[str]] = None


class LineMessage(BaseModel):
    """LINEメッセージ"""
    to: str  # LINE user ID or group ID
    message: str
    reply_token: Optional[str] = None


class PurchaseRequest(BaseModel):
    """購入リクエスト"""
    item_name: str
    item_url: Optional[str] = None
    quantity: int = 1
    max_price: Optional[float] = None
    preferred_shop: Optional[str] = None


class PaymentRequest(BaseModel):
    """支払いリクエスト"""
    payee: str
    amount: float
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    payment_method: Optional[str] = None


class SearchResult(BaseModel):
    """検索結果（Phase 3A: Smart Proposal用）"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    category: SearchResultCategory
    title: str
    url: Optional[str] = None
    price: Optional[int] = None
    status: Optional[str] = None  # "available", "limited", "sold_out"
    details: dict[str, Any] = Field(default_factory=dict)
    execution_params: dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        from_attributes = True


# ==================== Phase 3B: Execution Engine ====================

class ExecutionStatus(str, Enum):
    """実行状態"""
    PENDING = "pending"
    EXECUTING = "executing"
    AWAITING_CREDENTIALS = "awaiting_credentials"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionStep(str, Enum):
    """実行ステップ"""
    OPENED_URL = "opened_url"
    LOGGED_IN = "logged_in"
    ENTERED_DETAILS = "entered_details"
    SELECTED_ITEM = "selected_item"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"


class ServiceType(str, Enum):
    """サービス種別"""
    EX_RESERVATION = "ex_reservation"  # EX予約/スマートEX
    AMAZON = "amazon"
    RAKUTEN = "rakuten"
    HIGHWAY_BUS = "highway_bus"  # 高速バスネット
    JAL = "jal"
    ANA = "ana"
    GENERIC = "generic"  # 汎用フォーム


class CredentialRequest(BaseModel):
    """認証情報保存リクエスト"""
    service: str
    credentials: dict[str, str]  # {"email": "xxx", "password": "xxx"}


class CredentialResponse(BaseModel):
    """認証情報レスポンス"""
    success: bool
    service: str
    message: str


class CredentialListItem(BaseModel):
    """保存済み認証情報一覧の項目"""
    service: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class CredentialListResponse(BaseModel):
    """保存済み認証情報一覧レスポンス"""
    services: list[CredentialListItem]


class ProvideCredentialsRequest(BaseModel):
    """タスク実行中の認証情報提供リクエスト"""
    service: str
    credentials: dict[str, str]
    save_credentials: bool = False  # 認証情報を保存するか


class ProvideCredentialsResponse(BaseModel):
    """認証情報提供レスポンス"""
    task_id: str
    status: str
    message: str


class ExecutionProgress(BaseModel):
    """実行進捗"""
    current_step: Optional[str] = None
    steps_completed: list[str] = Field(default_factory=list)
    steps_remaining: list[str] = Field(default_factory=list)
    screenshot_url: Optional[str] = None


class ExecutionStatusResponse(BaseModel):
    """実行状況レスポンス"""
    task_id: str
    status: ExecutionStatus
    progress: Optional[ExecutionProgress] = None
    required_service: Optional[str] = None  # 認証が必要なサービス
    execution_result: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None


class ExecutionResult(BaseModel):
    """実行結果"""
    success: bool
    confirmation_number: Optional[str] = None  # 予約番号など
    message: str
    details: dict[str, Any] = Field(default_factory=dict)

