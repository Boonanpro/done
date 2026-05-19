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


class DomainCheckResponse(BaseModel):
    exact: Optional[DomainCheckCandidate] = None
    suggestions: list[DomainCheckCandidate] = []


class PublishRequest(BaseModel):
    artifact_id: str
    domain: str = Field(..., min_length=3)
    vercel_project: str = Field(..., description="Vercel project id または name")
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


class DeliveryUrlRequest(BaseModel):
    artifact_id: str
    slug: str = Field(..., min_length=1)
    vercel_project: str = "frontend"


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
    vercel_project: str = "frontend"


class DnsRecordDTO(BaseModel):
    type: str  # A / CNAME / TXT
    name: str  # @ / www など
    value: str
    purpose: str = ""  # 何のためのレコードかをクライアントに説明する


class RegistrarLinkDTO(BaseModel):
    label: str
    url: str


class DomainSetupResponse(BaseModel):
    """案内フローの状態。create / get / verify で共通利用する。"""

    success: bool
    token: Optional[str] = None
    setup_path: Optional[str] = None  # /domain-setup/<token>
    artifact_id: Optional[str] = None
    artifact_label: Optional[str] = None
    domain: Optional[str] = None
    status: Optional[str] = None  # pending / dns_pending / live / failed
    availability: Optional[dict[str, Any]] = None
    registrar_links: list[RegistrarLinkDTO] = []
    dns_records: list[DnsRecordDTO] = []
    production_url: Optional[str] = None
    verified: bool = False
    detail: Optional[str] = None
    error: Optional[str] = None
