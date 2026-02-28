"""note投稿システムのAPIルート

下書きCRUD、AI清書、投稿記録、統計のエンドポイント。
"""

import logging

from fastapi import APIRouter, HTTPException, Depends

from app.api.chat_routes import get_current_user, TokenData
from app.services.note_posting_service import NotePostingService
from app.models.note_schemas import (
    DraftCreateRequest,
    DraftUpdateRequest,
    DraftResponse,
    DraftListResponse,
    PolishRequest,
    PolishExecuteRequest,
    PolishPromptResponse,
    PolishSaveRequest,
    PolishedResponse,
    PostRecordRequest,
    PostResponse,
    PostListResponse,
    ScheduleCreateRequest,
    ScheduleUpdateRequest,
    ScheduleResponse,
    ScheduleListResponse,
    ScheduleDueResponse,
    StatsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notes", tags=["notes"])


def get_note_service() -> NotePostingService:
    return NotePostingService()


# ==================== Drafts ====================


@router.get("/drafts", response_model=DraftListResponse)
async def list_drafts(
    current_user: TokenData = Depends(get_current_user),
    service: NotePostingService = Depends(get_note_service),
):
    """下書き一覧を取得"""
    drafts = await service.list_drafts(current_user.user_id)
    return DraftListResponse(
        drafts=[DraftResponse(**d) for d in drafts]
    )


@router.post("/drafts", response_model=DraftResponse)
async def create_draft(
    req: DraftCreateRequest,
    current_user: TokenData = Depends(get_current_user),
    service: NotePostingService = Depends(get_note_service),
):
    """下書きを作成"""
    draft = await service.create_draft(
        user_id=current_user.user_id,
        title=req.title,
        content=req.content,
        tags=req.tags,
    )
    return DraftResponse(**draft)


@router.get("/drafts/{draft_id}", response_model=DraftResponse)
async def get_draft(
    draft_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: NotePostingService = Depends(get_note_service),
):
    """下書きを取得"""
    draft = await service.get_draft(draft_id, current_user.user_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return DraftResponse(**draft)


@router.patch("/drafts/{draft_id}", response_model=DraftResponse)
async def update_draft(
    draft_id: str,
    req: DraftUpdateRequest,
    current_user: TokenData = Depends(get_current_user),
    service: NotePostingService = Depends(get_note_service),
):
    """下書きを更新"""
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    draft = await service.update_draft(
        draft_id=draft_id,
        user_id=current_user.user_id,
        **updates,
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return DraftResponse(**draft)


@router.delete("/drafts/{draft_id}")
async def delete_draft(
    draft_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: NotePostingService = Depends(get_note_service),
):
    """下書きを削除"""
    deleted = await service.delete_draft(draft_id, current_user.user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"ok": True}


# ==================== Polish ====================


@router.post("/polish", response_model=PolishPromptResponse)
async def get_polish_prompt(
    req: PolishRequest,
    current_user: TokenData = Depends(get_current_user),
    service: NotePostingService = Depends(get_note_service),
):
    """AI清書用プロンプトを取得"""
    draft = await service.get_draft(req.draft_id, current_user.user_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    prompt = service.get_polish_prompt(
        draft["title"],
        draft["content"],
        article_type=getattr(req, "article_type", "free") or "free",
        price=getattr(req, "price", None),
    )
    return PolishPromptResponse(
        draft_id=req.draft_id,
        prompt=prompt,
        draft_title=draft["title"],
        draft_content=draft["content"],
    )


@router.post("/polish/{draft_id}/execute", response_model=PolishedResponse)
async def execute_polish(
    draft_id: str,
    req: PolishExecuteRequest = PolishExecuteRequest(),
    current_user: TokenData = Depends(get_current_user),
    service: NotePostingService = Depends(get_note_service),
):
    """AI清書を実行（Claude APIで自動清書）

    article_type: "free"（無料記事、デフォルト）or "paid"（有料記事）
    price: 有料記事の場合の価格（100〜50000円）
    """
    try:
        polished = await service.execute_polish(
            draft_id,
            current_user.user_id,
            article_type=req.article_type.value,
            price=req.price,
        )
        return PolishedResponse(**polished)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Polish execution failed: {e}")
        raise HTTPException(status_code=500, detail=f"AI清書に失敗しました: {str(e)}")


@router.post("/polish/{draft_id}", response_model=PolishedResponse)
async def save_polished(
    draft_id: str,
    req: PolishSaveRequest,
    current_user: TokenData = Depends(get_current_user),
    service: NotePostingService = Depends(get_note_service),
):
    """清書結果を手動で保存"""
    polished = await service.save_polished(
        draft_id=draft_id,
        user_id=current_user.user_id,
        title=req.title,
        full_text=req.full_text,
        tags=req.tags,
        hook=req.hook,
        summary=req.summary,
    )
    return PolishedResponse(**polished)


@router.get("/polish/{draft_id}", response_model=PolishedResponse)
async def get_polished(
    draft_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: NotePostingService = Depends(get_note_service),
):
    """清書結果を取得"""
    polished = await service.get_polished(draft_id, current_user.user_id)
    if not polished:
        raise HTTPException(status_code=404, detail="Polished content not found")
    return PolishedResponse(**polished)


# ==================== Posts ====================


@router.post("/posts", response_model=PostResponse)
async def record_post(
    req: PostRecordRequest,
    current_user: TokenData = Depends(get_current_user),
    service: NotePostingService = Depends(get_note_service),
):
    """投稿記録を保存"""
    post = await service.record_post(
        draft_id=req.draft_id,
        user_id=current_user.user_id,
        note_url=req.note_url,
        published=req.published,
    )
    return PostResponse(**post)


@router.get("/posts", response_model=PostListResponse)
async def list_posts(
    current_user: TokenData = Depends(get_current_user),
    service: NotePostingService = Depends(get_note_service),
):
    """投稿一覧を取得"""
    posts = await service.list_posts(current_user.user_id)
    return PostListResponse(
        posts=[PostResponse(**p) for p in posts]
    )


# ==================== Schedules ====================


@router.post("/schedules", response_model=ScheduleResponse)
async def create_schedule(
    req: ScheduleCreateRequest,
    current_user: TokenData = Depends(get_current_user),
    service: NotePostingService = Depends(get_note_service),
):
    """投稿スケジュールを作成"""
    try:
        schedule = await service.create_schedule(
            draft_id=req.draft_id,
            user_id=current_user.user_id,
            scheduled_at=req.scheduled_at.isoformat(),
            article_type=req.article_type.value,
            price=req.price,
        )
        return ScheduleResponse(**schedule)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/schedules", response_model=ScheduleListResponse)
async def list_schedules(
    current_user: TokenData = Depends(get_current_user),
    service: NotePostingService = Depends(get_note_service),
):
    """スケジュール一覧を取得"""
    schedules = await service.list_schedules(current_user.user_id)
    return ScheduleListResponse(
        schedules=[ScheduleResponse(**s) for s in schedules]
    )


@router.get("/schedules/due", response_model=ScheduleDueResponse)
async def get_due_schedules(
    service: NotePostingService = Depends(get_note_service),
):
    """実行すべきスケジュールを取得（ワーカー用）"""
    schedules = await service.get_due_schedules()
    return ScheduleDueResponse(
        schedules=[ScheduleResponse(**s) for s in schedules]
    )


@router.get("/schedules/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: NotePostingService = Depends(get_note_service),
):
    """スケジュールを取得"""
    schedule = await service.get_schedule(schedule_id, current_user.user_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return ScheduleResponse(**schedule)


@router.patch("/schedules/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: str,
    req: ScheduleUpdateRequest,
    current_user: TokenData = Depends(get_current_user),
    service: NotePostingService = Depends(get_note_service),
):
    """スケジュールを更新"""
    updates = {}
    if req.scheduled_at is not None:
        updates["scheduled_at"] = req.scheduled_at.isoformat()
    if req.article_type is not None:
        updates["article_type"] = req.article_type.value
    if req.price is not None:
        updates["price"] = req.price

    try:
        schedule = await service.update_schedule(
            schedule_id=schedule_id,
            user_id=current_user.user_id,
            **updates,
        )
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return ScheduleResponse(**schedule)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/schedules/{schedule_id}", response_model=ScheduleResponse)
async def cancel_schedule(
    schedule_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: NotePostingService = Depends(get_note_service),
):
    """スケジュールをキャンセル"""
    try:
        schedule = await service.cancel_schedule(schedule_id, current_user.user_id)
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return ScheduleResponse(**schedule)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== Stats ====================


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    current_user: TokenData = Depends(get_current_user),
    service: NotePostingService = Depends(get_note_service),
):
    """統計情報を取得"""
    stats = await service.get_stats(current_user.user_id)
    return StatsResponse(**stats)
