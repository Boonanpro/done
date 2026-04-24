"""
public_chat のデータスキーマ
クライアントHPに埋め込んだ AIChatPanel (Mode B) から叩かれる無認証チャットAPI。
"""
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class PublicChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000)


class PublicChatRequest(BaseModel):
    scope: str = Field(..., min_length=1, max_length=64)
    system_context: Optional[str] = Field(None, max_length=8000)
    messages: List[PublicChatMessage] = Field(..., min_length=1, max_length=20)


class PublicChatResponse(BaseModel):
    content: str
    model: str
