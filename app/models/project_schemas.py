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
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class AgentRunState(str, Enum):
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
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
    icon: Optional[str] = Field(None, max_length=10)


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
    icon: Optional[str] = None
    metadata: Optional[dict] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class ProjectListResponse(BaseModel):
    """プロジェクト一覧レスポンス"""
    projects: list[ProjectResponse]


class ProjectResumeRequest(BaseModel):
    """実行再開リクエスト（Red操作確認後）"""
    action: str = Field(
        default="confirm",
        pattern="^(confirm|cancel)$",
        description="confirm=続行, cancel=中止",
    )


# ==================== Execution Event Schemas ====================

class ExecutionEventResponse(BaseModel):
    """実行イベントレスポンス"""
    id: str
    project_id: Optional[str] = None
    run_id: Optional[str] = None
    room_id: str
    event_type: str  # 'tool_use', 'reasoning', 'phase', 'error', 'text', 'done'
    tool_name: Optional[str] = None
    tool_label: Optional[str] = None
    content: Optional[str] = None
    metadata: Optional[dict] = None
    seq: Optional[int] = None
    created_at: datetime


class AgentRunResponse(BaseModel):
    """繧ｨ繝ｼ繧ｸ繧ｧ繝ｳ繝医Λ繝ｳ縺ｮ蠑墓焚"""
    id: str
    project_id: str
    room_id: str
    claude_session_id: Optional[str] = None
    parent_run_id: Optional[str] = None
    state: AgentRunState
    active_proposal_id: Optional[str] = None
    superseded_by_run_id: Optional[str] = None
    metadata: Optional[dict] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
