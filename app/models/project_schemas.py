"""
Pydantic Schemas for Projects
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


# ==================== Enums ====================

class ProjectStatus(str, Enum):
    PLANNING = "planning"
    PROPOSED = "proposed"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class ProposalType(str, Enum):
    PLAN = "plan"
    REVISION = "revision"
    HEARTBEAT = "heartbeat"


class ProposalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


# ==================== Project Schemas ====================

class ProjectCreateRequest(BaseModel):
    """プロジェクト作成リクエスト"""
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    origin_room_id: Optional[str] = None


class ProjectUpdateRequest(BaseModel):
    """プロジェクト更新リクエスト"""
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    status: Optional[ProjectStatus] = None
    summary: Optional[str] = None


class ProjectResponse(BaseModel):
    """プロジェクトレスポンス"""
    id: str
    user_id: str
    title: str
    description: Optional[str] = None
    status: ProjectStatus
    room_id: Optional[str] = None
    origin_room_id: Optional[str] = None
    summary: Optional[str] = None
    metadata: Optional[dict] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class ProjectListResponse(BaseModel):
    """プロジェクト一覧レスポンス"""
    projects: list[ProjectResponse]


# ==================== Proposal Schemas ====================

class ProjectProposalCreateRequest(BaseModel):
    """提案作成リクエスト（内部用 - ダンが作成）"""
    content: str = Field(..., min_length=1)
    proposal_type: ProposalType = ProposalType.PLAN
    steps: Optional[list[dict]] = None


class ProjectProposalResponse(BaseModel):
    """提案レスポンス"""
    id: str
    project_id: str
    content: str
    proposal_type: ProposalType
    status: ProposalStatus
    steps: Optional[list[dict]] = None
    metadata: Optional[dict] = None
    approved_at: Optional[datetime] = None
    created_at: datetime


class ProjectProposalActionRequest(BaseModel):
    """提案承認/却下リクエスト"""
    action: str = Field(..., pattern="^(approve|reject)$")
