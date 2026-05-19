"""
公開フロー API のリクエスト/レスポンススキーマ (Phase 3 orchestrator用)

注: create_feature 自動生成の CRUD 系スキーマは使用しない。
chat_artifact テーブル側に publish 状態 (custom_domain, publish_status等) を
持たせる設計のため、publish 単独テーブルは現状空。
"""
from __future__ import annotations

from typing import Any, Optional

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
