"""
Main API Routes

Step 6: StateMachine統合 - 新しいエンドポイント追加
- POST /sm/message: StateMachineでメッセージを処理
- POST /sm/{session_id}/confirm: 提案を承認
- POST /sm/{session_id}/revise: 提案を修正
- GET /sm/{session_id}/state: 状態を取得
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from app.agent.agent import AISecretaryAgent
from app.models.schemas import (
    TaskRequest,
    TaskResponse,
    TaskStatus,
    ProvideCredentialsRequest,
    ProvideCredentialsResponse,
    ExecutionStatusResponse,
)
from app.services.execution_service import get_execution_service

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


# ==================== Phase 3B: Execution Engine APIs ====================

# デフォルトユーザーID（認証未実装のため仮）
DEFAULT_USER_ID = "default-user"


@router.post("/task/{id}/provide-credentials", response_model=ProvideCredentialsResponse)
async def provide_credentials(id: str, request: ProvideCredentialsRequest, user_id: Optional[str] = None):
    """
    タスク実行中に認証情報を提供（ログインまたは新規登録）
    
    ユーザーフロー：
    1. execution-statusで status="awaiting_credentials" の場合、auth_options が返される
    2. auth_options.login_fields でログインフォームを表示
    3. auth_options.registration_fields で新規登録フォームを表示（自動生成パスワード付き）
    4. ユーザーが選択したフローに応じて is_new_registration を設定
    
    Request（ログインの場合）:
    ```json
    {
      "service": "willer",
      "credentials": {"email": "user@example.com", "password": "secret123"},
      "save_credentials": true,
      "is_new_registration": false
    }
    ```
    
    Request（新規登録の場合）:
    ```json
    {
      "service": "willer",
      "credentials": {"email": "new@example.com", "password": "AutoGenPass123"},
      "save_credentials": true,
      "is_new_registration": true
    }
    ```
    """
    task_id = id
    uid = user_id or DEFAULT_USER_ID
    
    try:
        execution_service = get_execution_service()
        result = await execution_service.provide_credentials(
            task_id=task_id,
            user_id=uid,
            service=request.service,
            credentials=request.credentials,
            save_credentials=request.save_credentials,
            is_new_registration=request.is_new_registration,
        )
        
        # メッセージを分岐
        if request.is_new_registration:
            message = "Starting new registration."
        else:
            message = "Login credentials received. Resuming execution."
        
        return ProvideCredentialsResponse(
            task_id=task_id,
            status=result.status.value,
            message=message,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/task/{id}/execution-status", response_model=ExecutionStatusResponse)
async def get_execution_status(id: str):
    """
    実行状況をリアルタイム取得（ポーリング用）
    
    Response:
    ```json
    {
      "task_id": "uuid",
      "status": "executing",
      "progress": {
        "current_step": "logging_in",
        "steps_completed": ["opened_url", "entered_credentials"],
        "steps_remaining": ["submit_form", "confirm_booking"],
        "screenshot_url": "/screenshots/task_xxx_step2.png"
      }
    }
    ```
    """
    task_id = id
    
    try:
        execution_service = get_execution_service()
        result = await execution_service.get_execution_status(task_id=task_id)
        
        if not result:
            raise HTTPException(status_code=404, detail="Execution state not found")
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Step 6: StateMachine APIs ====================

class SMMessageRequest(BaseModel):
    """StateMachineメッセージリクエスト"""
    message: str
    session_id: Optional[str] = None  # 新規セッションの場合は省略可
    user_id: Optional[str] = None


class SMMessageResponse(BaseModel):
    """StateMachineメッセージレスポンス"""
    session_id: str
    state: str
    response: str
    reasoning_steps: list[str] = []
    needs_confirmation: bool = False
    is_chat: bool = False
    proposal: Optional[dict] = None
    error: Optional[str] = None


class SMReviseRequest(BaseModel):
    """StateMachine修正リクエスト"""
    revision: str


@router.post("/sm/message", response_model=SMMessageResponse)
async def sm_process_message(request: SMMessageRequest):
    """
    StateMachineでメッセージを処理（新しいアーキテクチャ）
    
    状態遷移:
    INTAKE → PLAN → RESEARCH → PROPOSE → CONFIRM → EXECUTE → VERIFY → REPORT
    
    特徴:
    - LLMの推論過程がreasoning_stepsで見える
    - 承認が必要な場合はneeds_confirmation=trueになる
    - 雑談はis_chat=trueで即座に応答
    
    使い方:
    1. 最初のリクエストでsession_idを省略 → 新しいセッションが開始
    2. レスポンスのsession_idを保存
    3. 続きのメッセージで同じsession_idを使用
    
    Example Request (新規セッション):
    ```json
    {
      "message": "明日18時に新大阪から博多まで新幹線で行きたい"
    }
    ```
    
    Example Response (提案待ち):
    ```json
    {
      "session_id": "uuid",
      "state": "confirm",
      "response": "**おすすめ**: のぞみ45号（新大阪駅→博多駅）\\n...",
      "reasoning_steps": ["新幹線移動と判断", "EX予約を使用", "のぞみ45号を選択"],
      "needs_confirmation": true,
      "proposal": {...}
    }
    ```
    """
    try:
        agent = get_agent()
        result = await agent.process_with_state_machine(
            message=request.message,
            session_id=request.session_id,
            user_id=request.user_id,
        )
        
        return SMMessageResponse(
            session_id=result.get("session_id", ""),
            state=result.get("state", "unknown"),
            response=result.get("response", ""),
            reasoning_steps=result.get("reasoning_steps", []),
            needs_confirmation=result.get("needs_confirmation", False),
            is_chat=result.get("is_chat", False),
            proposal=result.get("proposal"),
            error=result.get("error"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sm/{session_id}/confirm", response_model=SMMessageResponse)
async def sm_confirm(session_id: str):
    """
    StateMachineで提案を承認
    
    needs_confirmation=trueのレスポンスを受け取った後、
    このエンドポイントで承認するとExecutorが実行される。
    
    Example Response (実行完了):
    ```json
    {
      "session_id": "uuid",
      "state": "REPORT",
      "response": "## 予約完了\\n...",
      "reasoning_steps": ["承認されました", "実行中", "予約番号: XXX"],
      "needs_confirmation": false
    }
    ```
    """
    try:
        agent = get_agent()
        result = await agent.confirm_state_machine(session_id)
        
        if result.get("error"):
            raise HTTPException(status_code=404, detail=result["error"])
        
        return SMMessageResponse(
            session_id=result.get("session_id", session_id),
            state=result.get("state", "unknown"),
            response=result.get("response", ""),
            reasoning_steps=result.get("reasoning_steps", []),
            needs_confirmation=result.get("needs_confirmation", False),
            is_chat=result.get("is_chat", False),
            proposal=result.get("proposal"),
            error=result.get("error"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sm/{session_id}/revise", response_model=SMMessageResponse)
async def sm_revise(session_id: str, request: SMReviseRequest):
    """
    StateMachineで提案を修正
    
    needs_confirmation=trueのレスポンスを受け取った後、
    修正内容を送信すると再検索・再提案される。
    
    Example Request:
    ```json
    {
      "revision": "グリーン車にして"
    }
    ```
    """
    try:
        agent = get_agent()
        result = await agent.revise_state_machine(session_id, request.revision)
        
        if result.get("error"):
            raise HTTPException(status_code=404, detail=result["error"])
        
        return SMMessageResponse(
            session_id=result.get("session_id", session_id),
            state=result.get("state", "unknown"),
            response=result.get("response", ""),
            reasoning_steps=result.get("reasoning_steps", []),
            needs_confirmation=result.get("needs_confirmation", False),
            is_chat=result.get("is_chat", False),
            proposal=result.get("proposal"),
            error=result.get("error"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sm/{session_id}/state")
async def sm_get_state(session_id: str):
    """
    StateMachineの現在の状態を取得
    
    デバッグ・進捗確認用。
    """
    try:
        agent = get_agent()
        state = agent.get_state_machine_state(session_id)
        
        if not state:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        
        return state
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



