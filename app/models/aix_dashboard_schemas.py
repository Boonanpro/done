"""AIX事業ダッシュボード — Pydanticスキーマ

7テーブル分のCreate/Update/Responseモデルを定義。
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime, date
from uuid import UUID


# ============================================================
# 1. クライアント
# ============================================================
class ClientCreate(BaseModel):
    name: str = Field(..., min_length=1)
    industry: Optional[str] = None
    region: Optional[str] = None
    size: Optional[str] = None
    website: Optional[str] = None
    contact_name: Optional[str] = None
    contact_role: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    stage: str = "research"
    health_score: int = 50
    estimated_value: Optional[int] = None
    notes: Optional[str] = None
    tags: List[str] = []


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    industry: Optional[str] = None
    region: Optional[str] = None
    size: Optional[str] = None
    website: Optional[str] = None
    contact_name: Optional[str] = None
    contact_role: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    stage: Optional[str] = None
    health_score: Optional[int] = None
    estimated_value: Optional[int] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None


class ClientResponse(BaseModel):
    id: UUID
    name: str
    industry: Optional[str] = None
    region: Optional[str] = None
    size: Optional[str] = None
    website: Optional[str] = None
    contact_name: Optional[str] = None
    contact_role: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    stage: str
    health_score: int
    estimated_value: Optional[int] = None
    notes: Optional[str] = None
    tags: List[str] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# 2. 仮説
# ============================================================
class HypothesisCreate(BaseModel):
    client_id: UUID
    title: str = Field(..., min_length=1)
    pain_point: Optional[str] = None
    proposed_solution: Optional[str] = None
    confidence: int = 50
    status: str = "draft"
    research_notes: Optional[str] = None
    sources: List[Any] = []


class HypothesisUpdate(BaseModel):
    title: Optional[str] = None
    pain_point: Optional[str] = None
    proposed_solution: Optional[str] = None
    confidence: Optional[int] = None
    status: Optional[str] = None
    research_notes: Optional[str] = None
    sources: Optional[List[Any]] = None


class HypothesisResponse(BaseModel):
    id: UUID
    client_id: UUID
    title: str
    pain_point: Optional[str] = None
    proposed_solution: Optional[str] = None
    confidence: int
    status: str
    research_notes: Optional[str] = None
    sources: List[Any] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# 3. 提案アセット
# ============================================================
class ProposalCreate(BaseModel):
    client_id: UUID
    hypothesis_id: Optional[UUID] = None
    title: str = Field(..., min_length=1)
    summary: Optional[str] = None
    proposal_html_path: Optional[str] = None
    proposal_video_path: Optional[str] = None
    prototype_url: Optional[str] = None
    deck_url: Optional[str] = None
    status: str = "draft"
    estimated_value: Optional[int] = None


class ProposalUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    proposal_html_path: Optional[str] = None
    proposal_video_path: Optional[str] = None
    prototype_url: Optional[str] = None
    deck_url: Optional[str] = None
    status: Optional[str] = None
    sent_at: Optional[datetime] = None
    viewed_at: Optional[datetime] = None
    response_summary: Optional[str] = None
    estimated_value: Optional[int] = None


class ProposalResponse(BaseModel):
    id: UUID
    client_id: UUID
    hypothesis_id: Optional[UUID] = None
    title: str
    summary: Optional[str] = None
    proposal_html_path: Optional[str] = None
    proposal_video_path: Optional[str] = None
    prototype_url: Optional[str] = None
    deck_url: Optional[str] = None
    status: str
    sent_at: Optional[datetime] = None
    viewed_at: Optional[datetime] = None
    response_summary: Optional[str] = None
    estimated_value: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# 4. 営業・商談ログ
# ============================================================
class ActivityCreate(BaseModel):
    client_id: UUID
    proposal_id: Optional[UUID] = None
    activity_type: str = Field(..., description="email_sent/email_received/call/meeting/note/task")
    subject: str = Field(..., min_length=1)
    body: Optional[str] = None
    occurred_at: Optional[datetime] = None
    next_action: Optional[str] = None
    next_action_at: Optional[datetime] = None
    metadata: dict = {}


class ActivityUpdate(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None
    next_action: Optional[str] = None
    next_action_at: Optional[datetime] = None
    metadata: Optional[dict] = None


class ActivityResponse(BaseModel):
    id: UUID
    client_id: UUID
    proposal_id: Optional[UUID] = None
    activity_type: str
    subject: str
    body: Optional[str] = None
    occurred_at: datetime
    next_action: Optional[str] = None
    next_action_at: Optional[datetime] = None
    metadata: dict = {}
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# 5. 契約
# ============================================================
class ContractCreate(BaseModel):
    client_id: UUID
    proposal_id: Optional[UUID] = None
    title: str = Field(..., min_length=1)
    contract_type: Optional[str] = None
    initial_value: Optional[int] = None
    monthly_value: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: str = "draft"
    contract_file_url: Optional[str] = None
    notes: Optional[str] = None


class ContractUpdate(BaseModel):
    title: Optional[str] = None
    contract_type: Optional[str] = None
    initial_value: Optional[int] = None
    monthly_value: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[str] = None
    contract_file_url: Optional[str] = None
    notes: Optional[str] = None


class ContractResponse(BaseModel):
    id: UUID
    client_id: UUID
    proposal_id: Optional[UUID] = None
    title: str
    contract_type: Optional[str] = None
    initial_value: Optional[int] = None
    monthly_value: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: str
    contract_file_url: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# 6. 運用エンゲージメント
# ============================================================
class EngagementCreate(BaseModel):
    client_id: UUID
    contract_id: Optional[UUID] = None
    deliverable_name: str = Field(..., min_length=1)
    deliverable_type: Optional[str] = None
    deliverable_url: Optional[str] = None
    repo_path: Optional[str] = None
    status: str = "live"
    health_score: int = 80
    kpis: dict = {}
    notes: Optional[str] = None


class EngagementUpdate(BaseModel):
    deliverable_name: Optional[str] = None
    deliverable_type: Optional[str] = None
    deliverable_url: Optional[str] = None
    repo_path: Optional[str] = None
    status: Optional[str] = None
    health_score: Optional[int] = None
    kpis: Optional[dict] = None
    last_review_at: Optional[datetime] = None
    notes: Optional[str] = None


class EngagementResponse(BaseModel):
    id: UUID
    client_id: UUID
    contract_id: Optional[UUID] = None
    deliverable_name: str
    deliverable_type: Optional[str] = None
    deliverable_url: Optional[str] = None
    repo_path: Optional[str] = None
    status: str
    health_score: int
    kpis: dict = {}
    last_review_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# 7. ダンタスクハブ
# ============================================================
class TaskCreate(BaseModel):
    client_id: Optional[UUID] = None
    proposal_id: Optional[UUID] = None
    engagement_id: Optional[UUID] = None
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    zone: str = "green"
    status: str = "todo"
    priority: str = "normal"
    requested_action: Optional[str] = None
    due_at: Optional[datetime] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    zone: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    requested_action: Optional[str] = None
    result_summary: Optional[str] = None
    artifact_urls: Optional[List[str]] = None
    due_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TaskResponse(BaseModel):
    id: UUID
    client_id: Optional[UUID] = None
    proposal_id: Optional[UUID] = None
    engagement_id: Optional[UUID] = None
    title: str
    description: Optional[str] = None
    zone: str
    status: str
    priority: str
    requested_action: Optional[str] = None
    result_summary: Optional[str] = None
    artifact_urls: List[str] = []
    due_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# パイプライン集計
# ============================================================
class PipelineKPI(BaseModel):
    """ダッシュボード上部のKPIカード用"""
    active_clients: int
    proposals_sent: int
    proposals_responded: int
    response_rate: float
    contracted: int
    monthly_estimated_value: int
    open_tasks: int


class PipelineStageBucket(BaseModel):
    stage: str
    count: int
    estimated_value_total: int
