"""
Main API Routes
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from app.agent.agent import AISecretaryAgent
from app.models.schemas import TaskRequest, TaskResponse, TaskStatus

router = APIRouter()

# エージェントインスタンスを共有（タスク保存のため）
_agent_instance: Optional[AISecretaryAgent] = None

def get_agent() -> AISecretaryAgent:
    """エージェントインスタンスを取得（シングルトン）"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = AISecretaryAgent()
    return _agent_instance


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
    proposal_detail: Optional[str] = None  # 【アクション】【詳細】【補足】の全内容
    requires_confirmation: bool
    search_results: list[dict] = []  # Phase 3A: 検索結果（商品情報、交通情報など）


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
        # 常に共有インスタンスを使用（タスク保存のため）
        # ツール指定がある場合は新しいインスタンスを作成するが、タスクはクラス変数で共有される
        agent = get_agent()
        result = await agent.process_wish(
            wish=request.wish,
            user_id=request.user_id,
        )
        return WishResponse(
            task_id=result["task_id"],
            message=result["message"],
            proposed_actions=result["proposed_actions"],
            proposal_detail=result.get("proposal_detail"),
            requires_confirmation=result["requires_confirmation"],
            search_results=result.get("search_results", []),  # Phase 3A
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ReviseRequest(BaseModel):
    """訂正リクエスト"""
    revision: str  # 訂正内容（例: "17時じゃなくて16時にして"）


@router.post("/task/{id}/revise", response_model=WishResponse)
async def revise_task(id: str, request: ReviseRequest):
    """
    タスクの提案を訂正
    
    既存のタスクに対して訂正リクエストを送り、新しい提案を生成します。
    例: "17時じゃなくて16時にして", "グリーン車にして", "予算は30万円で"
    """
    task_id = id
    try:
        agent = get_agent()
        result = await agent.revise_task(task_id, request.revision)
        return WishResponse(
            task_id=result["task_id"],
            message=result["message"],
            proposed_actions=result["proposed_actions"],
            proposal_detail=result.get("proposal_detail"),
            requires_confirmation=result["requires_confirmation"],
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/task/{id}/confirm")
async def confirm_task(id: str):
    """タスクの実行を確認・承認"""
    task_id = id  # パラメータ名をidからtask_idに変換
    try:
        agent = get_agent()
        result = await agent.execute_task(task_id)
        return {"status": "executing", "task_id": task_id, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/task/{id}", response_model=TaskResponse)
async def get_task_status(id: str):
    """タスクのステータスを取得"""
    task_id = id
    try:
        agent = get_agent()
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
        agent = get_agent()
        tasks = await agent.list_tasks(user_id=user_id, limit=limit)
        return {"tasks": tasks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



