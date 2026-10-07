"""The room's work list: parallel jobs of a project's room (parallel_job_runner), for the web chat and the app."""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.chat_routes import get_current_user, TokenData
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["parallel-jobs"])


class StartRequest(BaseModel):
    task: str
    model: Optional[str] = None


class ControlRequest(BaseModel):
    operation: str
    text: Optional[str] = None
    model: Optional[str] = None


async def _room(project_id: str, user_id: str) -> str:
    project = await ProjectService().get_project(project_id, user_id)
    if not project or not project.get("room_id"):
        raise HTTPException(status_code=404, detail="プロジェクトが見つかりません")
    return project["room_id"]


@router.get("/{project_id}/parallel-jobs")
async def list_jobs(project_id: str, current_user: TokenData = Depends(get_current_user)):
    from app.services import parallel_job_runner as runner
    room_id = await _room(project_id, current_user.user_id)
    rows = await asyncio.to_thread(runner.room_jobs, current_user.user_id, room_id)
    return {"jobs": [runner.public(s) for s in rows],
            "models": [{"id": key, "label": label} for key, label in runner.LABELS.items()],
            "default_model": await asyncio.to_thread(runner.room_model, room_id)}


@router.post("/{project_id}/parallel-jobs")
async def start_job(project_id: str, body: StartRequest, current_user: TokenData = Depends(get_current_user)):
    from app.services import parallel_job_runner as runner
    room_id = await _room(project_id, current_user.user_id)
    task = (body.task or "").strip()
    if not task:
        raise HTTPException(status_code=400, detail="作業の内容を書いてください")
    try:
        job = await runner.start(room_id, current_user.user_id, task, body.model or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job": runner.public(job)}


@router.post("/{project_id}/parallel-jobs/{job_id}/control")
async def control_job(project_id: str, job_id: str, body: ControlRequest,
                      current_user: TokenData = Depends(get_current_user)):
    from app.services import parallel_job_runner as runner
    room_id = await _room(project_id, current_user.user_id)
    try:
        job = await runner.control(room_id, current_user.user_id, job_id, body.operation, body.text or "", body.model or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job": runner.public(job)}
