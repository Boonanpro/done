"""
Content Intelligence Schemas - Pydantic models for Phase 6 Content Analysis
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class ExtractionMethod(str, Enum):
    """テキスト抽出方法"""
    PDF_PDFPLUMBER = "pdf_pdfplumber"
    PDF_PYMUPDF = "pdf_pymupdf"
    OCR_GOOGLE_VISION = "ocr_google_vision"
    OCR_TESSERACT = "ocr_tesseract"
    URL_PLAYWRIGHT = "url_playwright"
    URL_REQUESTS = "url_requests"
    DIRECT_TEXT = "direct_text"


class ContentCategory(str, Enum):
    """コンテンツカテゴリ"""
    INVOICE = "invoice"           # 請求書
    RECEIPT = "receipt"           # 領収書
    NOTIFICATION = "notification" # 通知
    OTP = "otp"                   # ワンタイムパスワード
    CONFIRMATION = "confirmation" # 予約確認・注文確認
    NEWSLETTER = "newsletter"     # ニュースレター・メルマガ
    PERSONAL = "personal"         # 個人的なメッセージ
    SPAM = "spam"                 # スパム・広告
    UNKNOWN = "unknown"           # 不明


class ContentConfidence(str, Enum):
    """分類信頼度レベル"""
    HIGH = "high"       # 90%以上
    MEDIUM = "medium"   # 70-90%
    LOW = "low"         # 50-70%
    UNCERTAIN = "uncertain"  # 50%未満


# ==================== Text Extraction Schemas ====================

class TextExtractionRequest(BaseModel):
    """テキスト抽出リクエスト"""
    attachment_id: Optional[str] = None
    file_path: Optional[str] = None
    file_data: Optional[bytes] = None
    mime_type: Optional[str] = None
    url: Optional[str] = None


class TextExtractionResult(BaseModel):
    """テキスト抽出結果"""
    success: bool
    text: Optional[str] = None
    method: ExtractionMethod
    page_count: Optional[int] = None
    confidence: Optional[float] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    processing_time_ms: Optional[int] = None


class PDFExtractionResult(TextExtractionResult):
    """PDF抽出結果"""
    pages: Optional[List[str]] = None  # ページごとのテキスト
    tables: Optional[List[Dict[str, Any]]] = None  # 抽出されたテーブル


class OCRExtractionResult(TextExtractionResult):
    """OCR抽出結果"""
    language: Optional[str] = None
    words: Optional[List[Dict[str, Any]]] = None  # 単語位置情報


class URLExtractionResult(TextExtractionResult):
    """URL先コンテンツ抽出結果"""
    title: Optional[str] = None
    url: str
    final_url: Optional[str] = None  # リダイレクト後のURL


# ==================== Content Classification Schemas ====================

class ClassificationRequest(BaseModel):
    """コンテンツ分類リクエスト"""
    text: str
    subject: Optional[str] = None
    sender: Optional[str] = None
    additional_context: Optional[Dict[str, Any]] = None


class ClassificationResult(BaseModel):
    """コンテンツ分類結果"""
    category: ContentCategory
    confidence: ContentConfidence
    confidence_score: float = Field(ge=0.0, le=1.0)
    reasoning: Optional[str] = None
    extracted_data: Optional[Dict[str, Any]] = None
    secondary_categories: Optional[List[ContentCategory]] = None


class InvoiceData(BaseModel):
    """請求書から抽出されたデータ"""
    amount: Optional[float] = None
    currency: str = "JPY"
    due_date: Optional[datetime] = None
    invoice_number: Optional[str] = None
    issuer_name: Optional[str] = None
    issuer_address: Optional[str] = None
    bank_info: Optional[Dict[str, str]] = None  # 振込先情報
    items: Optional[List[Dict[str, Any]]] = None  # 明細


class OTPData(BaseModel):
    """OTPから抽出されたデータ"""
    code: str
    service_name: Optional[str] = None
    expires_in: Optional[int] = None  # 有効期限（秒）
    purpose: Optional[str] = None  # 認証目的


class ConfirmationData(BaseModel):
    """確認メールから抽出されたデータ"""
    confirmation_type: str  # reservation, order, registration, etc.
    confirmation_number: Optional[str] = None
    service_name: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


# ==================== API Request/Response Schemas ====================

class AnalyzeContentRequest(BaseModel):
    """コンテンツ解析APIリクエスト"""
    detected_message_id: Optional[str] = None
    attachment_id: Optional[str] = None
    text: Optional[str] = None
    url: Optional[str] = None
    include_classification: bool = True


class AnalyzeContentResponse(BaseModel):
    """コンテンツ解析APIレスポンス"""
    success: bool
    extraction_result: Optional[TextExtractionResult] = None
    classification_result: Optional[ClassificationResult] = None
    error: Optional[str] = None
    processing_time_ms: int


class ExtractTextFromURLRequest(BaseModel):
    """URL先テキスト抽出リクエスト"""
    url: str
    wait_for_selector: Optional[str] = None
    timeout_ms: int = 30000


class ExtractTextFromURLResponse(BaseModel):
    """URL先テキスト抽出レスポンス"""
    success: bool
    result: Optional[URLExtractionResult] = None
    error: Optional[str] = None


class ClassifyContentRequest(BaseModel):
    """コンテンツ分類APIリクエスト"""
    text: str
    subject: Optional[str] = None
    sender: Optional[str] = None


class ClassifyContentResponse(BaseModel):
    """コンテンツ分類APIレスポンス"""
    success: bool
    result: Optional[ClassificationResult] = None
    error: Optional[str] = None


class BatchAnalyzeRequest(BaseModel):
    """バッチ解析リクエスト"""
    message_ids: List[str]


class BatchAnalyzeResponse(BaseModel):
    """バッチ解析レスポンス"""
    success: bool
    total: int
    processed: int
    failed: int
    results: List[Dict[str, Any]]







