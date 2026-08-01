"""
公開フロー API のリクエスト/レスポンススキーマ (Phase 3 orchestrator用)

注: create_feature 自動生成の CRUD 系スキーマは使用しない。
chat_artifact テーブル側に publish 状態 (custom_domain, publish_status等) を
持たせる設計のため、publish 単独テーブルは現状空。
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class DomainCheckRequest(BaseModel):
    query: str = Field(..., min_length=3, description="検索/確認したいドメイン名 (FQDN)")
    include_suggestions: bool = True


class DomainCheckCandidate(BaseModel):
    name: str
    registrable: bool
    tier: Optional[str] = None
    pricing: Optional[dict[str, Any]] = None
    reason: Optional[str] = None  # available | taken | unsupported


class DomainCheckResponse(BaseModel):
    exact: Optional[DomainCheckCandidate] = None
    suggestions: list[DomainCheckCandidate] = []


class PublishRequest(BaseModel):
    artifact_id: str
    domain: str = Field(..., min_length=3)
    # Deprecated browser input. The server resolves the delivery project from
    # the publication ledger; this remains optional for older callers.
    vercel_project: Optional[str] = None
    artifact_dir: Optional[str] = Field(
        None, description="リポジトリ相対 (例: 'frontend/src/app/artifacts/kittoku')"
    )
    write_seo_files: bool = True
    business_info: Optional[dict[str, Any]] = None
    contact: Optional[dict[str, Any]] = None
    years: int = Field(1, ge=1, le=10)
    auto_renew: bool = True
    dry_run: bool = False
    payment_responsibility: Literal["owner_pays", "client_pays"] = "owner_pays"


class ConnectDomainRequest(BaseModel):
    """既に所有しているドメインを接続する（購入なし）リクエスト。"""

    artifact_id: str
    domain: str = Field(..., min_length=3)
    vercel_project: Optional[str] = None
    replace: bool = False  # 別成果物が使用中でも差し替えるか


class DeliveryUrlRequest(BaseModel):
    artifact_id: str
    slug: str = Field(..., min_length=1)
    vercel_project: Optional[str] = None


class PublishStepDTO(BaseModel):
    name: str
    status: str
    detail: str = ""
    duration_ms: int = 0


class PublishResponse(BaseModel):
    success: bool
    artifact_id: str
    domain: str
    deploy_url: Optional[str] = None
    steps: list[PublishStepDTO] = []
    error: Optional[str] = None
    pricing: Optional[dict[str, Any]] = None
    dns_instructions: Optional[dict[str, Any]] = None  # 外部DNS時の手動設定レコード
    conflict_label: Optional[str] = None  # 同じドメインを使用中の別成果物名
    verified: bool = True  # 外部DNSが反映済みか（false=本番URL未確定）


class DeliveryUrlResponse(BaseModel):
    success: bool
    artifact_id: str
    url: Optional[str] = None
    alias: Optional[str] = None
    error: Optional[str] = None


# ============================================
# クライアント所有ドメインの案内フロー
# ============================================


class DomainSetupCreateRequest(BaseModel):
    """オーナーが「クライアントが用意する」を選んだ時の案内URL発行リクエスト"""

    artifact_id: str
    domain: str = Field(..., min_length=3, description="クライアントに取得を案内するドメイン")
    vercel_project: Optional[str] = None


class DomainSetupResponse(BaseModel):
    """案内フローの状態 (create / get / confirm で共通)。"""

    success: bool
    token: Optional[str] = None
    setup_path: Optional[str] = None  # /domain-setup/<token>
    setup_url: Optional[str] = None   # canonical client-facing URL
    artifact_id: Optional[str] = None
    artifact_label: Optional[str] = None
    domain: Optional[str] = None
    status: Optional[str] = None  # pending / registering / live / failed
    price: Optional[str] = None  # ドメイン取得費用 (USD)
    currency: str = "usd"
    test_mode: bool = False  # Stripe テストモードでの実行か
    production_url: Optional[str] = None
    detail: Optional[str] = None  # 補足・エラーメッセージ
    error: Optional[str] = None


class DomainCheckoutRequest(BaseModel):
    return_origin: str = Field(..., description="決済後に戻るフロントエンドのオリジン")


class DomainCheckoutResponse(BaseModel):
    success: bool
    checkout_url: Optional[str] = None
    error: Optional[str] = None
    registrant_saved: bool = False


class DomainRegistrantRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    organization: str = Field("", max_length=200)
    email: str = Field(..., min_length=5, max_length=254)
    phone: str = Field(..., min_length=6, max_length=40)
    street: str = Field(..., min_length=3, max_length=300)
    city: str = Field(..., min_length=1, max_length=120)
    state: str = Field(..., min_length=1, max_length=120)
    postal_code: str = Field(..., min_length=3, max_length=30)
    country_code: str = Field(..., min_length=2, max_length=2)


class PaymentConfirmRequest(BaseModel):
    session_id: str = Field(..., min_length=1, description="Stripe Checkout セッションID")
