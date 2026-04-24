"""
Project API Routes - プロジェクト管理
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional

from app.api.chat_routes import get_current_user, TokenData
from app.services.project_service import ProjectService, generate_icon_for_title
from app.services.run_service import RunService
from app.models.project_schemas import (
    AgentRunResponse,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    ProjectResponse,
    ProjectListResponse,
    ExecutionEventResponse,
)

router = APIRouter(prefix="/projects", tags=["projects"])

@router.get("/suggest-title")
async def suggest_project_title(
    room_id: Optional[str] = Query(default=None),
    current_user: TokenData = Depends(get_current_user),
):
    """チャット内容からプロジェクトタイトルを自動生成"""
    from app.services.chat_service import ChatService

    service = ChatService()
    messages = []

    if room_id:
        try:
            raw = await service.get_messages(room_id, current_user.user_id, limit=20)
            messages = [
                m.get("content", "")
                for m in reversed(raw)
                if m.get("sender_type") == "human" and m.get("content")
            ]
        except Exception:
            pass

    if not messages:
        return {"title": "新しいプロジェクト"}

    context = "\n".join(messages[:5])

    try:
        import anthropic
        from app.config import settings

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=60,
            messages=[{
                "role": "user",
                "content": (
                    "以下の会話内容から、プロジェクトのタイトルを日本語で1つ生成してください。\n"
                    "タイトルは20文字以内の簡潔な名詞句にしてください。タイトルだけを返してください。\n\n"
                    f"会話内容:\n{context[:800]}"
                ),
            }],
        )
        title = resp.content[0].text.strip().strip("「」『』")
        if len(title) > 50:
            title = title[:50]
        return {"title": title}
    except Exception:
        # フォールバック: 最初のメッセージを短く切る
        first = messages[0]
        title = first.split("。")[0].split("、")[0].split("\n")[0][:30].strip()
        return {"title": title or "新しいプロジェクト"}


@router.post("/generate-icon")
async def generate_icon(
    request: dict,
    current_user: TokenData = Depends(get_current_user),
):
    """タイトルからアイコン絵文字を生成"""
    title = request.get("title", "")
    if not title:
        return {"icon": "📁"}
    icon = generate_icon_for_title(title)
    return {"icon": icon}


def get_project_service() -> ProjectService:
    return ProjectService()


def get_run_service() -> RunService:
    return RunService()


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
    """プロジェクトを削除（LLMアーカイブはバックグラウンドで実行）"""
    import asyncio

    project = await service.get_project(project_id, current_user.user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 削除前にメッセージを収集（DB読み取りのみ、高速）
    messages_for_archive = None
    room_id = project.get("room_id")
    if room_id:
        from app.api.chat_routes import _collect_messages_for_archive
        from app.services.chat_service import ChatService
        chat_service = ChatService()
        messages_for_archive = await _collect_messages_for_archive(
            service=chat_service,
            user_id=current_user.user_id,
            room_id=room_id,
        )

    # 即座に削除
    deleted = await service.delete_project(project_id, current_user.user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")

    # 承認済み計画をクリア
    from app.agent.bootstrap_context import clear_active_plan
    clear_active_plan()

    # LLMアーカイブをバックグラウンドで実行
    if room_id and messages_for_archive:
        from app.api.chat_routes import _run_archive_in_background
        asyncio.create_task(
            _run_archive_in_background(room_id, messages_for_archive)
        )


# ==================== Execution Events ====================

@router.get("/{project_id}/execution-events", response_model=list[ExecutionEventResponse])
async def get_execution_events(
    project_id: str,
    limit: int = Query(default=100, le=500),
    after: Optional[str] = Query(default=None),
    since_seq: Optional[int] = Query(default=None),
    run_id: Optional[str] = Query(default=None),
    current_user: TokenData = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """プロジェクトの実行イベント一覧（since_seqで差分取得可能）"""
    project = await service.get_project(project_id, current_user.user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return await service.get_execution_events(
        project_id,
        limit=limit,
        after=after,
        since_seq=since_seq,
        run_id=run_id,
    )


@router.get("/{project_id}/current-run", response_model=AgentRunResponse)
async def get_current_run(
    project_id: str,
    current_user: TokenData = Depends(get_current_user),
    project_service: ProjectService = Depends(get_project_service),
    run_service: RunService = Depends(get_run_service),
):
    """Return the current authoritative run for a project chat."""
    project = await project_service.get_project(project_id, current_user.user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    run = await run_service.get_current_run(project_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


# ==================== Helpers ====================


def _format_tool_label(name: str, tool_input: dict) -> str:
    """SDK ツール名 + input から人間向けラベルを生成"""
    # MCP ツール（統合 browser ツール）
    if "browser" in name and "browser_" not in name:
        action = tool_input.get("action", "")
        if action == "open":
            url = tool_input.get("url", "")
            domain = url.split("//")[-1].split("/")[0] if "//" in url else url[:40]
            return f"ブラウザで {domain} を開く"
        if action == "click":
            ref = tool_input.get("ref", "")
            return f"要素 {ref} をクリック"
        if action == "type":
            return "テキスト入力"
        if action == "screenshot":
            return "画面を確認"
        if action == "scroll":
            return "スクロール"
        if action == "select":
            return "選択操作"
        if action == "back":
            return "ページを戻る"
        return f"ブラウザ操作: {action}"
    # Legacy fallback: browser_* (in-flight sessions)
    if "browser_open" in name:
        url = tool_input.get("url", "")
        domain = url.split("//")[-1].split("/")[0] if "//" in url else url[:40]
        return f"ブラウザで {domain} を開く"
    if "browser_click" in name:
        ref = tool_input.get("ref", "")
        return f"要素 {ref} をクリック"
    if "browser_type" in name:
        return "テキスト入力"
    if "browser_screenshot" in name:
        return "画面を確認"
    if "browser_scroll" in name:
        return "スクロール"
    if "browser_select" in name:
        return "選択操作"
    if "get_credentials" in name:
        return "認証情報を取得"
    if "update_workspace" in name:
        return "ワークスペース更新"
    if "write_file" in name:
        path = tool_input.get("path", tool_input.get("file_path", ""))
        filename = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if path else ""
        return f"ファイル書き込み: {filename}" if filename else "ファイル書き込み"
    if "read_file" in name:
        path = tool_input.get("path", tool_input.get("file_path", ""))
        filename = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if path else ""
        return f"ファイル読み取り: {filename}" if filename else "ファイル読み取り"
    if "execute_command" in name or "run_command" in name:
        cmd = tool_input.get("command", "")
        return f"コマンド実行: {cmd}" if cmd else "コマンド実行"
    if "check_skill" in name:
        skill_name = tool_input.get("skill_name") or tool_input.get("name", "")
        return f"スキル確認: {skill_name}" if skill_name else "スキル確認"

    # Claude Code SDK 内部ツール
    if name == "Read":
        path = tool_input.get("file_path", "")
        filename = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if path else ""
        return f"ファイル読み取り: {filename}" if filename else "ファイル読み取り"
    if name == "Write":
        path = tool_input.get("file_path", "")
        filename = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if path else ""
        return f"ファイル作成: {filename}" if filename else "ファイル作成"
    if name == "Edit":
        path = tool_input.get("file_path", "")
        filename = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if path else ""
        return f"ファイル編集: {filename}" if filename else "ファイル編集"
    if name == "Bash":
        cmd = tool_input.get("command", "")
        return f"コマンド実行: {cmd}" if cmd else "コマンド実行"
    if name == "Glob":
        pattern = tool_input.get("pattern", "")
        return f"ファイル検索: {pattern}" if pattern else "ファイル検索"
    if name == "Grep":
        pattern = tool_input.get("pattern", "")
        return f"コード検索: {pattern}" if pattern else "コード検索"
    if name == "TodoWrite":
        return "タスクリスト更新"
    if name == "Task":
        desc = tool_input.get("description", "")
        return f"サブタスク: {desc}" if desc else "サブタスク実行"
    if name == "WebSearch":
        query = tool_input.get("query", "")
        return f"WebSearch: {query}" if query else "WebSearch"
    if name == "WebFetch":
        url = tool_input.get("url", "")
        return f"WebFetch: {url}" if url else "WebFetch"

    return name


