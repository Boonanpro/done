"""
inspector_overrides のデータスキーマ

Runtime overrides は JSX ファイルには書き戻さず、この表に保存し、
デモページ起動時に <InspectorRuntime /> がフェッチ→ DOM 要素に適用する。
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict
from datetime import datetime
from uuid import UUID


class OverrideUpsert(BaseModel):
    artifact_slug: str = Field(..., min_length=1)
    element_key: str = Field(..., min_length=1)
    styles: Optional[Dict[str, str]] = None
    attrs: Optional[Dict[str, str]] = None
    project_id: Optional[UUID] = None


class OverrideResponse(BaseModel):
    id: UUID
    project_id: Optional[UUID] = None
    artifact_slug: str
    element_key: str
    styles: Dict[str, str]
    attrs: Dict[str, str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
