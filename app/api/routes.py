"""
Main API Routes
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import uuid

from app.agent.agent import AISecretaryAgent
from app.models.schemas import TaskRequest, TaskResponse, TaskStatus

router = APIRouter()


class WishRequest(BaseModel):
    """ユーザーの願望リクエスト"""
    wish: str
    user_id: Optional[str] = None
    tools: Optional[list[str]] = None  # 使用するツール名のリスト（例: ["search_web", "browse_website"]）


class WishResponse(BaseModel):
    """願望に対するレスポンス"""
    task_id: str
    message: str
    proposed_actions: list[str]
    requires_confirmation: bool


@router.post("/wish", response_model=WishResponse)
async def process_wish(request: WishRequest):
    """
    ユーザーの「○○したい」という願望を処理
    AIエージェントが提案を生成し、必要に応じて実行
    
    toolsパラメータで使用するツールを明示的に指定できます:
    - browse_website: Webサイトの閲覧
    - fill_form: フォームの入力
    - click_element: Web要素のクリック
    - take_screenshot: スクリーンショット取得
    - send_email: メール送信
    - search_email: メール検索
    - read_email: メール読み取り
    - send_line_message: LINEメッセージ送信
    - search_web: Web検索
    """
    try:
        agent = AISecretaryAgent(tool_names=request.tools)
        result = await agent.process_wish(
            wish=request.wish,
            user_id=request.user_id,
        )
        return WishResponse(
            task_id=result["task_id"],
            message=result["message"],
            proposed_actions=result["proposed_actions"],
            requires_confirmation=result["requires_confirmation"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/task/{task_id}/confirm")
async def confirm_task(task_id: str):
    """タスクの実行を確認・承認"""
    try:
        agent = AISecretaryAgent()
        result = await agent.execute_task(task_id)
        return {"status": "executing", "task_id": task_id, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/task/{task_id}", response_model=TaskResponse)
async def get_task_status(task_id: str):
    """タスクのステータスを取得"""
    try:
        agent = AISecretaryAgent()
        task = await agent.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks")
async def list_tasks(user_id: Optional[str] = None, limit: int = 10):
    """タスク一覧を取得"""
    try:
        agent = AISecretaryAgent()
        tasks = await agent.list_tasks(user_id=user_id, limit=limit)
        return {"tasks": tasks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

