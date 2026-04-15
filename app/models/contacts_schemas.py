from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID


class ContactCreate(BaseModel):
    name: str = Field(..., min_length=1)
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    memo: Optional[str] = None


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    memo: Optional[str] = None


class ContactResponse(BaseModel):
    id: UUID
    name: str
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    memo: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
