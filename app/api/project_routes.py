"""
Project API Routes - プロジェクト管理
"""
from fastapi import APIRouter, HTTPException, Depends, Query
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
    ExecutionEventResponse,
)

router = APIRouter(prefix="/projects", tags=["projects"])

# バックグラウンドタスクの参照を保持（GC防止）
_background_tasks: set = set()


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
            task = asyncio.create_task(_start_project_execution(
                project=project,
                proposal=result,
                user_id=current_user.user_id,
            ))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
    else:
        result = await service.reject_proposal(proposal_id, project_id)

    if not result:
        raise HTTPException(status_code=404, detail="Proposal not found or already actioned")
    return result


# ==================== Execution Events ====================

@router.get("/{project_id}/execution-events", response_model=list[ExecutionEventResponse])
async def get_execution_events(
    project_id: str,
    limit: int = Query(default=100, le=500),
    after: Optional[str] = Query(default=None),
    since_seq: Optional[int] = Query(default=None),
    current_user: TokenData = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """プロジェクトの実行イベント一覧（since_seqで差分取得可能）"""
    project = await service.get_project(project_id, current_user.user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return await service.get_execution_events(project_id, limit=limit, after=after, since_seq=since_seq)


def _summarize_reasoning(text: str, max_len: int = 120) -> str:
    """思考テキストを1文に要約（先頭の意味のある文を抽出）"""
    if not text or not text.strip():
        return ""
    # 改行で分割して空行でない最初の行を取得
    lines = [ln.strip() for ln in text.strip().split("\n") if ln.strip()]
    if not lines:
        return ""
    first = lines[0]
    # 句点で区切って最初の文を取得
    for sep in ("。", "．", ". "):
        if sep in first:
            first = first[: first.index(sep) + len(sep)]
            break
    if len(first) > max_len:
        first = first[: max_len - 1] + "…"
    return first


def _format_tool_label(name: str, tool_input: dict) -> str:
    """SDK ツール名 + input から人間向けラベルを生成"""
    # MCP ツール（ブラウザ操作系）
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
        return f"コマンド実行: {cmd[:40]}" if cmd else "コマンド実行"

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
        return f"コマンド実行: {cmd[:40]}" if cmd else "コマンド実行"
    if name == "Glob":
        pattern = tool_input.get("pattern", "")
        return f"ファイル検索: {pattern}" if pattern else "ファイル検索"
    if name == "Grep":
        pattern = tool_input.get("pattern", "")
        return f"コード検索: {pattern[:30]}" if pattern else "コード検索"
    if name == "TodoWrite":
        return "タスクリスト更新"
    if name == "Task":
        desc = tool_input.get("description", "")
        return f"サブタスク: {desc[:30]}" if desc else "サブタスク実行"

    return name


async def _start_project_execution(project: dict, proposal: dict, user_id: str):
    """承認された提案をCLI Runnerで実行開始"""
    import logging
    logger = logging.getLogger(__name__)

    project_id = project["id"]
    room_id = project["room_id"]
    proposal_content = proposal.get("content", "")
    had_error = False

    # チーム議論のメタデータ（リサーチャー調査結果・クリティック検証）を取得
    proposal_metadata = proposal.get("metadata") or {}
    team_meta = proposal_metadata.get("team", {})
    research_findings = proposal_metadata.get("research_findings", "")
    critique = proposal_metadata.get("critique", "")

    # チーム議論セクションの構築（情報がある場合のみ）
    team_context = ""
    if research_findings or critique:
        team_context = "\n\n## チーム議論の参考情報（計画時の調査・検証結果）\n"
        if research_findings:
            team_context += f"\n### リサーチャーの調査結果\n{research_findings}\n"
        if critique:
            team_context += f"\n### クリティックの検証結果\n{critique}\n"
        team_context += "\n上記を踏まえて、指摘されたリスクに注意しながら実行してください。\n"

    execution_prompt = f"""以下の計画が承認されました。実行を開始してください。

## 承認された計画
{proposal_content}
{team_context}
## 実行ルール

### ステップ実行
1. ステップを順番に1つずつ実行する
2. 各ステップの開始時に「## ステップ N: ○○ を開始します」と宣言する
3. 各ステップの完了時に結果を報告する
4. 失敗した場合は理由を説明し、後続ステップへの影響を判断してから次に進む
5. 全ステップ完了後に「## 完了報告」として全体をまとめる

### ゾーン判断（各操作の実行前に必ず判定）
- **Green（即実行）**: 検索、閲覧、ツール作成、bashコマンド、ファイル操作、パッケージインストール
- **Yellow（実行→報告）**: フォーム入力（非個人情報）、カート追加、設定変更
- **Red（確認→実行）**: 個人情報入力、購入確定、取消不可操作 → 必ずユーザーに内容を示して確認を待つ

### 障害対応
- エラー → まず自分のツール（bash, browser, exec_code等）で解決を試みる
- ツール不足 → 必要なスクリプトを書いて実行する
- OTP/2段階認証 → メールアプリやSMSをブラウザで開いてコードを自力取得する。取得できない場合のみユーザーに聞く
- CAPTCHA → ユーザーにスクリーンショットを見せて「この画像の文字を教えてください」と聞く
- 「できません」と止まることは禁止。必ず代替案を提示するか、ユーザーに助けを求める
"""

    try:
        from app.agent.cli_runner import process_message_cli
        from app.services.chat_service import ChatService

        chat_service = ChatService()
        service = ProjectService()
        final_text = ""

        # 開始メッセージ
        await chat_service.send_dan_ai_message(
            user_id=user_id,
            content="承認された計画の実行を開始します...",
            room_id=room_id,
        )

        async for event in process_message_cli(
            room_id=room_id,
            user_id=user_id,
            content=execution_prompt,
            project_title=project.get("title", ""),
            project_description=project.get("description", ""),
            project_status="in_progress",
        ):
            etype = event["type"]

            if etype == "text":
                # ユーザー向けメッセージ → chat_messagesに保存
                final_text = event["text"]
                if event["text"].strip():
                    await chat_service.send_dan_ai_message(
                        user_id=user_id,
                        content=event["text"],
                        room_id=room_id,
                    )

            elif etype == "tool_use":
                # 内部実行 → execution_eventsに保存
                label = _format_tool_label(event.get("name", ""), event.get("input", {}))
                await service.save_execution_event(
                    project_id=project_id,
                    room_id=room_id,
                    event_type="tool_use",
                    tool_name=event.get("name", ""),
                    tool_label=label,
                )

            elif etype == "reasoning":
                # 内部思考 → execution_eventsに保存
                text = event.get("text", "")
                if text.strip():
                    summary = _summarize_reasoning(text)
                    await service.save_execution_event(
                        project_id=project_id,
                        room_id=room_id,
                        event_type="reasoning",
                        content=summary or text[:200],
                    )

            elif etype == "result":
                final_text = event.get("text", final_text)

            elif etype == "error":
                had_error = True
                final_text = f"エラーが発生しました: {event['message']}"
                await service.save_execution_event(
                    project_id=project_id,
                    room_id=room_id,
                    event_type="error",
                    content=event["message"][:500],
                )

        # エラー時のみ最終メッセージを送信（正常時はtextイベントで既に送信済み）
        if had_error and final_text:
            await chat_service.send_dan_ai_message(
                user_id=user_id,
                content=final_text,
                room_id=room_id,
            )

    except Exception as e:
        had_error = True
        logger.exception(f"[ProjectExecution] Failed for project {project_id}: {e}")
        try:
            from app.services.chat_service import ChatService
            chat_service = ChatService()
            await chat_service.send_dan_ai_message(
                user_id=user_id,
                content=f"実行中にエラーが発生しました: {e}",
                room_id=room_id,
            )
        except Exception:
            pass
    finally:
        # 実行完了後、プロジェクトステータスを更新
        try:
            service = ProjectService()
            new_status = "paused" if had_error else "completed"
            await service.update_project(project_id, user_id, status=new_status)
            logger.info(f"[ProjectExecution] Project {project_id} status → {new_status}")
        except Exception as e:
            logger.error(f"[ProjectExecution] Failed to update status for {project_id}: {e}")
