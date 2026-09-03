"""
Project API Routes - プロジェクト管理
"""
import asyncio
import json
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import StreamingResponse
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

# タイトル生成の指示（ChatGPT/Geminiの会話一覧レベルの品質を狙う）
_TITLE_SYSTEM = (
    "あなたはチャット履歴の一覧に表示する会話タイトルを付ける専門家です。"
    "ChatGPTやGeminiの会話一覧のように、その会話が何の話だったか一目で分かる"
    "自然で具体的な日本語タイトルを1つだけ作ります。\n"
    "ルール:\n"
    "- 12〜20文字程度。長くても25文字以内。\n"
    "- 会話の核心（依頼内容・対象・成果物・調べ物）を表す。\n"
    "- 体言止めでも自然な句でもよいが、内容が伝わることを最優先する。\n"
    "- 「新しいプロジェクト」「会話」「質問」「相談」「お願い」のような中身のない語だけのタイトルは禁止。\n"
    "- 固有名詞（クライアント名・サイト名・サービス名・技術名）があれば優先的に入れる。\n"
    "- あいさつ・雑談・内容の薄い会話は「あいさつ」「雑談」など短い語1つでよい（この場合だけ一般語を許可）。\n"
    "- どんな入力でも必ず短いタイトルを返す。「タイトルを作成できません」のような説明文・断り文は絶対に返さない。\n"
    "- 引用符・カギカッコ・絵文字・末尾の句点は付けない。\n"
    "- タイトルだけを返す。説明や前置き・「タイトル:」などのラベルは一切付けない。"
)

_TITLE_EXAMPLES = (
    "例:\n"
    "会話: 吉川特装のホームページのトップ画像を新しいものに差し替えたい\n"
    "タイトル: 吉川特装HPのトップ画像差し替え\n"
    "---\n"
    "会話: iTunesの課金って経費だとどの勘定科目で仕訳するのが正しい？\n"
    "タイトル: iTunes課金の経費仕訳\n"
    "---\n"
    "会話: ReactのuseEffectがマウント時に2回走るんだけど原因と直し方を教えて\n"
    "タイトル: useEffectが2回走る原因の調査\n"
    "---\n"
    "会話: 小学生向けの野球の練習メニューを1時間分組んでほしい\n"
    "タイトル: 小学生向け野球練習メニュー作成\n"
    "---\n"
    "会話: おはよう\n"
    "タイトル: あいさつ\n"
)

# LLM がタイトルではなく断り文・説明文を返したときに弾くための語
_REFUSAL_MARKERS = (
    "できません", "ありません", "申し訳", "わかりません", "不明",
    "具体的な", "判断できません", "情報が不足",
)


def _is_valid_title(title: str) -> bool:
    """タイトルとして妥当か（断り文・説明文・長すぎる文を排除）。"""
    if not title:
        return False
    # タイトルは短い。文章・断り文は長くなりがち
    if len(title) > 26:
        return False
    # 句点を含む＝文章として返ってきている
    if "。" in title:
        return False
    if any(marker in title for marker in _REFUSAL_MARKERS):
        return False
    return True


def _clean_title(text: str) -> str:
    """LLM出力からタイトルとして使える文字列を整形する。"""
    title = (text or "").strip()
    # モデルが付けがちなラベルを除去
    for prefix in ("タイトル:", "タイトル：", "Title:", "件名:", "件名："):
        if title.startswith(prefix):
            title = title[len(prefix):].strip()
    # 複数行で返ってきたら1行目だけ
    title = title.split("\n")[0].strip()
    # 引用符・カギカッコ・末尾句点を除去
    title = title.strip("「」『』｢｣“”\"'").strip()
    title = title.rstrip("。.").strip()
    if len(title) > 30:
        title = title[:30]
    return title


@router.get("/suggest-title")
async def suggest_project_title(
    room_id: Optional[str] = Query(default=None),
    current_user: TokenData = Depends(get_current_user),
):
    """チャット内容からプロジェクトタイトルを自動生成（初回のみ）

    タイトルは最初の1回だけAIが付ける。既にタイトルが付いている部屋には
    現在のタイトルをそのまま返す（LLM生成もしない）。会話が進むたびに
    名前がころころ変わると目的のチャットを見失う、というユーザー要望による。
    クライアント側（Web/モバイル）にも同種のガードはあるが、キャッシュ未取得の
    タイミングですり抜けて改名される事故が実際に起きたため、サーバー側で確実に守る。
    """
    from app.services.chat_service import ChatService

    service = ChatService()
    raw_messages: list[dict] = []

    if room_id:
        try:
            proj = (
                service.supabase.table("projects")
                .select("title")
                .eq("room_id", room_id)
                .limit(1)
                .execute()
            )
            current_title = (proj.data[0].get("title") or "").strip() if proj.data else ""
            if current_title and current_title != "新しいプロジェクト":
                return {"title": current_title}
        except Exception:
            pass
        try:
            raw = await service.get_messages(room_id, current_user.user_id, limit=20)
            # 古い→新しい順に並べ替え、空メッセージは除外
            raw_messages = [m for m in reversed(raw) if (m.get("content") or "").strip()]
        except Exception:
            pass

    if not raw_messages:
        return {"title": "新しいプロジェクト"}

    # 最初のユーザー発言はタイトルの最重要シグナルなので確実に拾う
    first_user = next(
        (m for m in raw_messages if m.get("sender_type") == "human"),
        raw_messages[0],
    )
    first_user_text = (first_user.get("content") or "").strip()

    # 直近のやり取りを文脈として連結（合計約2500文字まで）
    lines: list[str] = []
    budget = 2500
    for m in raw_messages[-12:]:
        role = "ユーザー" if m.get("sender_type") == "human" else "ダン"
        content = (m.get("content") or "").strip()
        if not content:
            continue
        entry = f"{role}: {content[:600]}"
        lines.append(entry)
        budget -= len(entry)
        if budget <= 0:
            break
    context = "\n".join(lines)

    # 従量課金API（残高切れで死んでいた）ではなく Max 定額の Claude CLI ワンショットで生成。
    # システム指示 + few-shot + 会話を1プロンプトにまとめて渡す。
    full_prompt = (
        f"{_TITLE_SYSTEM}\n\n"
        f"{_TITLE_EXAMPLES}\n"
        "では次の会話のタイトルを作ってください。タイトルの文字列だけを返してください。\n\n"
        f"会話:\n{context}\n\n"
        "タイトル:"
    )

    try:
        from app.agent.cli_runner import run_oneshot_cli

        raw_title = await asyncio.to_thread(run_oneshot_cli, full_prompt, "haiku", 60)
        title = _clean_title(raw_title or "")
        if _is_valid_title(title):
            return {"title": title}
    except Exception:
        pass

    # フォールバック: 最初のユーザー発言を短く整形
    fallback = first_user_text.split("\n")[0].split("。")[0].split("、")[0]
    fallback = _clean_title(fallback)[:24]
    return {"title": fallback or "新しいプロジェクト"}


@router.post("/generate-icon")
async def generate_icon(
    request: dict,
    current_user: TokenData = Depends(get_current_user),
):
    """タイトルからアイコン絵文字を生成"""
    title = request.get("title", "")
    if not title:
        return {"icon": "📁"}
    # 定額CLIワンショット（ブロッキング）はスレッドに逃がす
    icon = await asyncio.to_thread(generate_icon_for_title, title)
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
    # 新チャットで選んだモデルを projects.metadata.model に保存する。
    # 値の正当性（許可リスト照合）は CLI 起動時の _resolve_cli_model 側で行う。
    metadata = None
    if request.model:
        metadata = {"model": request.model.strip().lower()}
    project = await service.create_project(
        user_id=current_user.user_id,
        title=request.title,
        description=request.description,
        origin_room_id=request.origin_room_id,
        metadata=metadata,
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


# ==================== Room Board（部屋ボード） ====================

@router.get("/{project_id}/board")
async def get_room_board(
    project_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """部屋ボード（現在地ドキュメント）を取得"""
    project = await service.get_project(project_id, current_user.user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    from app.services.room_board_service import get_board
    return await asyncio.to_thread(get_board, project_id)


@router.post("/{project_id}/board/refresh")
async def refresh_room_board(
    project_id: str,
    force: bool = Query(default=False),
    current_user: TokenData = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """部屋ボードを即時消化（テスト・手動更新用）。force=true でカーソル無視で再消化"""
    project = await service.get_project(project_id, current_user.user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    from app.services.room_board_service import digest_project, get_project_with_board
    row = await asyncio.to_thread(get_project_with_board, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    result = await asyncio.to_thread(digest_project, row, force)
    return result


@router.get("/{project_id}/board/stream")
async def stream_room_board(
    project_id: str,
    request: Request,
    current_user: TokenData = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """ボード更新のSSE購読。接続時に現状スナップショット、以降は書き込みの度に即時プッシュ。

    消化・外部イベントによる書き込みは room_board_service._write_board → _publish_board
    で同一プロセス内の購読キューに流れる。25秒ごとに ping を打って接続を保つ。
    """
    project = await service.get_project(project_id, current_user.user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    from app.services.room_board_service import get_board, subscribe_board, unsubscribe_board

    q = await subscribe_board(project_id)

    async def gen():
        try:
            snapshot = await asyncio.to_thread(get_board, project_id)
            yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    board = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {json.dumps({'enabled': True, 'board': board}, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            unsubscribe_board(project_id, q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
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


