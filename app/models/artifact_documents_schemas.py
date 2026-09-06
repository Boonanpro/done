"""
artifact_documents のデータスキーマ。

成果物ページ（ロードマップ等）の本文 = BlockNote のブロック配列。
ページ側はブロック配列をそのまま送り、サーバ側で差分を取って版と通知を作る。
"""
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class ArtifactDocumentResponse(BaseModel):
    """閲覧用: 本文と版。edit_key や通知の内部状態は含めない。"""
    artifact_slug: str
    title: str
    blocks: List[Any]
    version: int
    updated_at: Optional[datetime] = None
    last_saved_at: Optional[datetime] = None
    last_editor: Optional[str] = None


class ArtifactDocumentSave(BaseModel):
    """保存リクエスト。base_version は「この版を見て編集した」の申告（競合検出用）。"""
    blocks: List[Any] = Field(default_factory=list)
    title: Optional[str] = None
    base_version: Optional[int] = None


class ArtifactDocumentSaveResponse(BaseModel):
    version: int
    saved_at: datetime
    changed: bool
    changes: List[str] = Field(default_factory=list)


class ArtifactDocumentAccessRequest(BaseModel):
    edit_key: Optional[str] = None


class ArtifactDocumentAccessResponse(BaseModel):
    can_edit: bool
    editor: Optional[str] = None  # owner | page | None


class ArtifactDocumentRevisionResponse(BaseModel):
    version: int
    editor: Optional[str] = None
    summary: Optional[str] = None
    created_at: Optional[datetime] = None
