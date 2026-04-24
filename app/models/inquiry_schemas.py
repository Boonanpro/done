"""
inquiry のデータスキーマ
クライアントHPの問い合わせフォーム送信先。
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class InquiryCreate(BaseModel):
    scope: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=120)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=40)
    company: Optional[str] = Field(None, max_length=200)
    message: str = Field(..., min_length=1, max_length=4000)
    source_url: Optional[str] = Field(None, max_length=500)


class InquiryResponse(BaseModel):
    id: UUID
    scope: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    message: str
    source_url: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
