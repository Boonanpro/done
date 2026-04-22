"""
inspector のデータスキーマ
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict


class InspectorApplyRequest(BaseModel):
    file_path: str = Field(..., min_length=1)
    line_number: int = Field(..., ge=1)
    column_number: Optional[int] = None
    element_tag: Optional[str] = None
    # CSS プロパティ → 値（単位まで含む文字列）
    styles: Optional[Dict[str, str]] = None
    # HTML attributes（src, alt, poster 等）
    attrs: Optional[Dict[str, str]] = None


class InspectorApplyResponse(BaseModel):
    success: bool
    file_path: str
    line_number: int
    patched_tag: Optional[str] = None
    error: Optional[str] = None
