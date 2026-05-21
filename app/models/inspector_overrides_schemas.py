"""
inspector_overrides のデータスキーマ

Runtime overrides は JSX ファイルには書き戻さず、この表に保存し、
デモページ起動時に <InspectorRuntime /> がフェッチ→ DOM 要素に適用する。

attrs は v2 で nested 構造（model_v2 = JSON 文字列、blockStyle = dict 等）を
持つため Dict[str, Any]。
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID


class OverrideUpsert(BaseModel):
    artifact_slug: str = Field(..., min_length=1)
    element_key: str = Field(..., min_length=1)
    styles: Optional[Dict[str, str]] = None
    attrs: Optional[Dict[str, Any]] = None
    project_id: Optional[UUID] = None
    # True なら attrs を全置換（v1 残骸を消す）。False なら従来通り merge。
    replace_attrs: bool = False


class DeleteElementRequest(BaseModel):
    """Inspector からの「要素まるごと削除」リクエスト。"""
    artifact_slug: str = Field(..., min_length=1)
    element_key: str = Field(..., min_length=1)
    project_id: Optional[UUID] = None


class RestoreFileRequest(BaseModel):
    """Undo: artifact 配下のファイルを指定内容で完全置換するリクエスト。"""
    artifact_slug: str = Field(..., min_length=1)
    file_path: str = Field(..., min_length=1, description="PROJECT_ROOT からの相対パス")
    content: str = Field(..., description="書き戻すファイル内容")


class OverrideResponse(BaseModel):
    id: UUID
    project_id: Optional[UUID] = None
    artifact_slug: str
    element_key: str
    styles: Dict[str, str]
    attrs: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
