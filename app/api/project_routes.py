"""
Project API Routes - プロジェクト管理
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional

from app.api.chat_routes import get_current_user, TokenData
from app.services.project_service import ProjectService
from app.models.project_schemas import (
    ProjectCreateRequest,
    ProjectUpdateRequest,
    ProjectResponse,
    ProjectListResponse,
    ProjectProposalCreateRequest,
    ProjectProposalResponse,
    ProjectProposalActionRequest,
)

router = APIRouter(prefix="/projects", tags=["projects"])


def get_project_service() -> ProjectService:
    return ProjectService()


# ==================== Projects ====================

@router.get("", response_model=ProjectListResponse)
async def list_projects(
    status: Optional[str] = None,
    current_user: TokenData = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """プロジェクト一覧を取得"""
    projects = await service.list_projects(current_user.user_id, status=status)
    return ProjectListResponse(projects=projects)


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    request: ProjectCreateRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """プロジェクトを作成"""
    project = await service.create_project(
        user_id=current_user.user_id,
        title=request.title,
        description=request.description,
        origin_room_id=request.origin_room_id,
    )
    return project


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """プロジェクトを取得"""
    project = await service.get_project(project_id, current_user.user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    request: ProjectUpdateRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """プロジェクトを更新"""
    updates = request.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    project = await service.update_project(
        project_id, current_user.user_id, **updates
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """プロジェクトを削除"""
    deleted = await service.delete_project(project_id, current_user.user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")


# ==================== Proposals ====================

@router.get("/{project_id}/proposals", response_model=list[ProjectProposalResponse])
async def list_proposals(
    project_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """プロジェクトの提案一覧"""
    # 所有者チェック
    project = await service.get_project(project_id, current_user.user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return await service.get_proposals(project_id)


@router.post("/{project_id}/proposals", response_model=ProjectProposalResponse, status_code=201)
async def create_proposal(
    project_id: str,
    request: ProjectProposalCreateRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """プロジェクトに提案を作成"""
    project = await service.get_project(project_id, current_user.user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return await service.create_proposal(
        project_id=project_id,
        content=request.content,
        proposal_type=request.proposal_type,
        steps=request.steps,
    )


@router.post("/{project_id}/proposals/{proposal_id}/action", response_model=ProjectProposalResponse)
async def proposal_action(
    project_id: str,
    proposal_id: str,
    request: ProjectProposalActionRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """提案を承認または却下"""
    project = await service.get_project(project_id, current_user.user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if request.action == "approve":
        result = await service.approve_proposal(proposal_id, project_id)
        if result:
            # 承認成功 → ステータスをin_progressに更新
            await service.update_project(
                project_id, current_user.user_id, status="in_progress"
            )

            # SDK実行をバックグラウンドで開始
            import asyncio
            asyncio.create_task(_start_project_execution(
                project=project,
                proposal=result,
                user_id=current_user.user_id,
            ))
    else:
        result = await service.reject_proposal(proposal_id, project_id)

    if not result:
        raise HTTPException(status_code=404, detail="Proposal not found or already actioned")
    return result


async def _start_project_execution(project: dict, proposal: dict, user_id: str):
    """承認された提案をSDK Runnerで実行開始"""
    import logging
    logger = logging.getLogger(__name__)

    room_id = project["room_id"]
    proposal_content = proposal.get("content", "")

    execution_prompt = f"""以下の計画が承認されました。実行を開始してください。

## 承認された計画
{proposal_content}

## 実行指示
- 上記の実行計画のステップを順番に実行してください
- 各ステップの完了時に進捗を報告してください
- Redゾーン操作（決済、個人情報入力等）は必ずユーザーに確認してください
"""

    try:
        from app.agent.sdk_runner import process_message_sdk
        from app.services.chat_service import ChatService

        final_text = ""
        async for event in process_message_sdk(
            room_id=room_id,
            user_id=user_id,
            content=execution_prompt,
            project_title=project.get("title", ""),
            project_description=project.get("description", ""),
            project_status="in_progress",
        ):
            if event["type"] == "text":
                final_text = event["text"]
            elif event["type"] == "result":
                final_text = event.get("text", final_text)
            elif event["type"] == "error":
                final_text = f"エラーが発生しました: {event['message']}"

        # 実行結果をチャットメッセージとして保存
        if final_text:
            chat_service = ChatService()
            await chat_service.send_dan_ai_message(
                user_id=user_id,
                content=final_text,
                room_id=room_id,
            )

    except Exception as e:
        logger.exception(f"[ProjectExecution] Failed for project {project.get('id')}: {e}")
