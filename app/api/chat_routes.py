"""
Chat API Routes for Done Chat
Supports both Bearer token and HttpOnly Cookie authentication
"""
from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect, Response, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from datetime import datetime, timezone
import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path

from app.config import settings

from app.services.auth_service import (
    decode_access_token, create_token_pair, refresh_tokens,
    TokenData
)
from app.services.chat_service import ChatService, parse_datetime
from app.models.chat_schemas import (
    # Auth
    RegisterRequest, LoginRequest, TokenResponse,
    UserResponse, UserUpdateRequest,
    # Invite
    InviteCreateRequest, InviteResponse, InviteInfoResponse, InviteAcceptResponse,
    # Friends
    FriendResponse, FriendsListResponse,
    # Rooms
    RoomCreateRequest, RoomUpdateRequest, RoomResponse, RoomsListResponse,
    RoomMemberResponse, RoomMembersListResponse, AddMemberRequest,
    # Messages
    MessageSendRequest, MessageResponse, MessagesListResponse, ReadMarkResponse,
    # AI
    AISettingsResponse, AISettingsUpdateRequest, AISummaryResponse,
    # Dan Page & Proposals (2E & 2G)
    DanRoomResponse, ProposalResponse, ProposalsListResponse, ProposalActionRequest,
    # Sessions
    SessionResponse, SessionsListResponse, SessionCreateResponse,
    SessionActivateResponse, SessionUpdateRequest,
)

from pydantic import BaseModel


class CancelRequest(BaseModel):
    """キャンセルリクエスト"""
    session_id: str
    cancelled_user_message_id: Optional[str] = None

router = APIRouter(prefix="/chat", tags=["chat"])
security = HTTPBearer(auto_error=False)

# Cookie names
ACCESS_TOKEN_COOKIE = "done_access_token"
REFRESH_TOKEN_COOKIE = "done_refresh_token"
WORKSPACE_DIR = Path.home() / ".dan" / "workspace"
WORKSPACE_MEMORY_DIR = WORKSPACE_DIR / "memory"
COMPACTION_SNAPSHOT_INTERVAL_MESSAGES = 40
logger = logging.getLogger(__name__)
DAN_LATENCY_LOG = Path(__file__).resolve().parents[2] / "dan_latency.log"


def _write_latency_log(message: str) -> None:
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        with DAN_LATENCY_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{timestamp} {message}\n")
    except Exception:
        logger.debug("Failed to write DAN latency log", exc_info=True)

# ==================== Observer ====================
import asyncio as _asyncio_observer

# room_id → 最後の観察時点のDBメッセージ数
_observer_last_message_index: dict[str, int] = {}
# 現在実行中の観察者タスク（room_id → asyncio.Task）
_observer_running: dict[str, "_asyncio_observer.Task"] = {}
OBSERVER_ROOM_SUFFIX = "__observer"


def _get_session_title(room_id: str) -> str:
    """room_idからセッションタイトルを取得する"""
    try:
        from app.services.supabase_client import get_supabase_client
        sb = get_supabase_client().client
        # projectsテーブルのtitleを優先（Haikuが生成した正しいタイトル）
        result = sb.table("projects").select("title").eq("room_id", room_id).limit(1).execute()
        if result.data:
            title = result.data[0].get("title", "")
            if title and title != "新しいプロジェクト":
                return title
        # フォールバック: chat_rooms.name
        result = sb.table("chat_rooms").select("name").eq("id", room_id).limit(1).execute()
        if result.data:
            name = result.data[0].get("name", "")
            if name and name != "新しいプロジェクト":
                return name
    except Exception:
        pass
    return room_id[:8]


def _fetch_messages_since(room_id: str, last_index: int) -> str:
    """last_index以降のメッセージをDBから取得してテキスト化する"""
    try:
        from app.services.supabase_client import get_supabase_client
        sb = get_supabase_client().client
        result = (
            sb.table("chat_messages")
            .select("sender_type,content,created_at")
            .eq("room_id", room_id)
            .order("created_at", desc=False)
            .execute()
        )
        messages = result.data or []
        # last_index以降のメッセージを取得
        new_messages = messages[last_index:]
        if not new_messages:
            return ""
        lines = []
        for i, msg in enumerate(new_messages, start=last_index + 1):
            sender = "ユーザー" if msg["sender_type"] == "human" else "ダン"
            content = (msg.get("content") or "")[:2000]  # 個別メッセージは2000文字で切る
            lines.append(f"[{i}] {sender}: {content}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"[Observer] Failed to fetch messages: {e}")
        return ""


async def _run_single_observer(
    room_id: str,
    user_id: str,
    observer_name: str,
    checklist_path: Path,
    conversation_text: str,
) -> dict:
    """1つの観察者を実行する。{"files": [...], "summary": "..."} を返す。"""
    if not checklist_path.exists():
        logger.info(f"[Observer:{observer_name}] {checklist_path.name} not found, skipping")
        return {"files": [], "summary": ""}

    checklist = checklist_path.read_text(encoding="utf-8")
    if conversation_text:
        prompt = (
            f"[OBSERVER MODE] これはユーザーからのメッセージではなく、システムによる自動観察リクエストです。\n"
            f"ユーザーには見えません。チャットに返答しないでください。\n\n"
            f"ROOM_ID: {room_id}\n\n"
            f"以下は直前の会話内容です:\n\n{conversation_text}\n\n"
            f"---\n\n以下のチェックリストに従い、上記の会話を振り返ってください。\n"
            f"該当があればファイルを直接編集してください。なければ何もしないでください。\n\n"
            f"---\n{checklist}\n---\n\n"
            f"何も記録しなかった場合は一切何も返答せず、空のまま終了せよ（「学びなし」「該当なし」等も返答しない）。\n"
            f"記録した場合のみ、日本語箇条書き3行以内で要約を返答。"
        )
    else:
        prompt = (
            f"[OBSERVER MODE] これはユーザーからのメッセージではなく、システムによる自動メンテナンスリクエストです。\n"
            f"ユーザーには見えません。チャットに返答しないでください。\n\n"
            f"以下のチェックリストに従い、指定されたファイルの整理を行ってください。\n"
            f"該当があればファイルを直接編集してください。なければ何もしないでください。\n\n"
            f"---\n{checklist}\n---\n\n"
            f"何も変更しなかった場合は一切何も返答せず、空のまま終了せよ（「変更なし」等も返答しない）。\n"
            f"変更した場合のみ、日本語箇条書き3行以内で要約を返答。"
        )

    edited_files: list[str] = []
    summary = ""
    observer_room_id = f"{room_id}{OBSERVER_ROOM_SUFFIX}"
    try:
        from app.agent.cli_runner import process_message_cli
        async for event in process_message_cli(
            room_id=observer_room_id,
            user_id=user_id,
            content=prompt,
            system_prompt=(
                f"あなたは観察者モード（{observer_name}）です。指示されたファイル編集を行ってください。\n"
                f"【返答ルール】\n"
                f"- 何も記録しなかった場合: 何も返答せず終了\n"
                f"- 記録した場合: 日本語で箇条書き3行以内の要約のみ返答（例:「- RULES.mdに○○を追加」「- 計画を更新: Phase 1を完了済みに変更」）\n"
                f"- 内部思考・英語・説明文は一切含めない"
            ),
            skip_save=True,
            skip_resume=True,
            cwd=str(Path(__file__).parent.parent.parent),  # D:/done
        ):
            if event["type"] == "tool_use":
                tool_name = event.get("name", "")
                if tool_name in ("Edit", "Write", "mcp__dan-tools__write_file"):
                    tool_input = event.get("input", {})
                    file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
                    if file_path and file_path not in edited_files:
                        edited_files.append(file_path)
            elif event["type"] == "result":
                summary = event.get("text", "")
                logger.info(f"[Observer:{observer_name}] Completed for room {room_id} (edited={len(edited_files)} files)")
            elif event["type"] == "error":
                logger.warning(f"[Observer:{observer_name}] Error for room {room_id}: {event.get('message')}")
    except Exception as e:
        logger.error(f"[Observer:{observer_name}] Failed for room {room_id}: {e}")
    return {"files": edited_files, "summary": summary}


async def _run_observers(room_id: str, user_id: str):
    """2つの観察者を逐次実行する（ダン回答完了後に即座に呼ばれる）"""
    last_index = _observer_last_message_index.get(room_id, 0)
    logger.info(f"[Observer] Starting for room {room_id} (last_index={last_index})")

    try:
        # DBからメッセージ取得
        conversation_text = _fetch_messages_since(room_id, last_index)
        if not conversation_text:
            logger.info(f"[Observer] No new messages for room {room_id}, skipping")
            return

        # 現在のメッセージ数を記録
        try:
            from app.services.supabase_client import get_supabase_client
            sb = get_supabase_client().client
            count_result = sb.table("chat_messages").select("id", count="exact").eq("room_id", room_id).execute()
            _observer_last_message_index[room_id] = count_result.count or 0
        except Exception:
            pass

        observer_dir = Path(__file__).parent.parent.parent / ".claude"

        # 計画 → 学び+メタ認知 の順で逐次実行
        summaries: list[str] = []
        all_edited: list[str] = []

        def _is_meaningful_summary(text: str) -> bool:
            """変更なし系のサマリーを除外する"""
            if not text.strip():
                return False
            skip_phrases = [
                "変更なし", "学びなし", "計画なし", "更新不要", "記録不要",
                "何も記録", "終了します", "該当なし", "特になし", "観察完了",
                "No update", "no change", "no new", "no learnings",
                "nothing to record", "no issues", "no errors",
                "no user feedback", "no coding", "no design",
            ]
            lower = text.lower()
            return not any(phrase.lower() in lower for phrase in skip_phrases)

        plan_result = await _run_single_observer(room_id, user_id, "計画", observer_dir / "observer_planning.md", conversation_text)
        all_edited += plan_result["files"]
        if _is_meaningful_summary(plan_result["summary"]):
            summaries.append(f"【計画】{plan_result['summary']}")

        learn_result = await _run_single_observer(room_id, user_id, "学び+メタ認知", observer_dir / "observer_learning.md", conversation_text)
        all_edited += learn_result["files"]
        if _is_meaningful_summary(learn_result["summary"]):
            summaries.append(f"【学び】{learn_result['summary']}")

        logger.info(f"[Observer] Both observers completed for room {room_id} (total edited={len(all_edited)} files)")

        # 意味のあるサマリーがある場合のみ通知を作成
        if summaries:
            await _create_observer_notification(room_id, user_id, summaries)

    except Exception as e:
        logger.error(f"[Observer] Failed for room {room_id}: {e}")
    finally:
        _observer_running.pop(room_id, None)


async def _create_observer_notification(room_id: str, user_id: str, summaries: list[str]):
    """観察者の記録内容を通知として作成する"""
    try:
        session_title = _get_session_title(room_id)
        content = f"セッション「{session_title}」\n\n" + "\n\n".join(summaries)
        title = "観察者: 記録を更新しました"

        from app.services.supabase_client import get_supabase_client
        sb = get_supabase_client().client
        # 同じルームの旧 observation を失効させ、通知タブに無限蓄積しないようにする
        # （情報通知は最新1件だけ pending で残す）
        try:
            sb.table("dan_proposals").update({"status": "expired"}).eq(
                "user_id", user_id
            ).eq("type", "observation").eq("source_room_id", room_id).eq(
                "status", "pending"
            ).execute()
        except Exception:
            logger.warning("[Observer] prior observation expire failed (non-fatal)")
        sb.table("dan_proposals").insert({
            "user_id": user_id,
            "type": "observation",
            "title": title,
            "content": content,
            "source_room_id": room_id,
            "status": "pending",
        }).execute()
        logger.info(f"[Observer] Notification created for room {room_id}")
    except Exception as e:
        logger.error(f"[Observer] Failed to create notification: {e}")


def _trigger_observer(room_id: str, user_id: str):
    """ダンの回答完了後に観察者を即座に起動する。前の観察者が実行中ならスキップ。"""
    if os.getenv("DAN_OBSERVER_ENABLED", "false").lower() in {"0", "false", "no", "off"}:
        logger.info("[Observer] Skipped because DAN_OBSERVER_ENABLED is disabled for room %s", room_id)
        return
    # 前の観察者がまだ実行中ならスキップ
    existing = _observer_running.get(room_id)
    if existing and not existing.done():
        logger.info(f"[Observer] Skipped for room {room_id}: previous observer still running")
        return

    try:
        loop = _asyncio_observer.get_running_loop()
        task = loop.create_task(_run_observers(room_id, user_id))
        _observer_running[room_id] = task
        logger.info(f"[Observer] Triggered for room {room_id}")
    except RuntimeError:
        pass


async def _notify_dan_completion(
    room_id: str,
    user_id: str,
    project_id: str | None,
    final_text: str = "",
) -> None:
    """Best-effort browser/PWA push when a Dan run finishes."""
    try:
        from app.services.push_service import get_push_service

        body = _compact_text(final_text, 120) if final_text else ""
        if not body:
            body = "Danの作業が完了しました"
        url = f"/chat/{project_id}" if project_id else "/chat"
        svc = get_push_service()
        await svc.notify_room(
            room_id=room_id,
            exclude_type="ai",
            title="Dan",
            body=body,
            url=url,
        )
        await svc.notify_room(
            room_id=f"user:{user_id}",
            exclude_type="ai",
            title="Dan",
            body=body,
            url=url,
        )
    except Exception as e:
        logger.debug("Dan completion push skipped (room=%s): %s", room_id, e)

REPLAN_KEYWORDS = (
    "やっぱり",
    "方針変更",
    "方向転換",
    "仕様変更",
    "変更したい",
    "見直し",
    "再計画",
    "再提案",
    "再調査",
    "別案",
    "ピボット",
    "change direction",
    "replan",
    "pivot",
    "revise plan",
)


def _is_replan_request(text: str) -> bool:
    """ユーザー入力が再計画リクエストかを緩く判定する。"""
    if not text:
        return False
    lowered = text.lower()
    return any(keyword in text or keyword in lowered for keyword in REPLAN_KEYWORDS)


def _extract_skill_command(text: str) -> tuple:
    """
    メッセージ先頭の /skill-name を検出。
    Returns: (skill_name or None, remaining_content)
    """
    if not text or not text.startswith("/"):
        return None, text
    match = re.match(r'^/([a-zA-Z0-9_-]+)\s*(.*)', text, re.DOTALL)
    if not match:
        return None, text
    skill_name = match.group(1)
    remaining = match.group(2).strip()
    return skill_name, remaining


def _compact_text(text: str, limit: int = 220) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = " ".join(line.strip() for line in text.split("\n") if line.strip())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def _build_content_with_media(content: str, image_urls: list, file_urls: list | None = None) -> str:
    """画像URL・ファイルURLをcontentの先頭に付加する（同期・即時）。"""
    import os
    upload_dir = os.path.join(os.path.dirname(__file__), "..", "..", "uploads")
    upload_dir = os.path.normpath(upload_dir)
    VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
    lines = []
    for url in (image_urls or []):
        filename = url.split("/")[-1]
        local_path = os.path.join(upload_dir, filename).replace("\\", "/")
        lines.append(f"[添付画像: {local_path}]")
    for f in (file_urls or []):
        name = f.get("name", "file")
        url = f.get("url", "")
        ext = os.path.splitext(name)[1].lower()
        if ext in VIDEO_EXTS:
            lines.append(f"[添付動画: {name} ({url})]")
        else:
            lines.append(f"[添付ファイル: {name} ({url})]")
    if not lines:
        return content
    prefix = "\n".join(lines)
    return f"{prefix}\n\n{content}" if content.strip() else prefix


async def _enrich_content_with_video_analysis(
    content: str, file_urls: list | None = None
) -> tuple[str, dict[str, str]]:
    """動画ファイル・動画URLがあればGemini分析を実行し、結果をコンテンツに追加する。

    対応:
    - ファイルアップロード: .mp4/.avi/.mov/.mkv/.webm
    - URL: YouTube, Loom (メッセージ本文から自動検出)

    Returns:
        (enriched_content, video_analyses) — video_analysesは {local_path: analysis_text}
        のdict。_save_media_artifactsで再利用して二重実行を防ぐ。
    """
    import os
    from app.services.video_analyzer import analyze_video, analyze_video_url, extract_video_urls

    analyses = []
    skipped = []
    video_analyses: dict[str, str] = {}  # {path: analysis_text}
    max_analysis_chars = 5000
    max_total_chars = 24000

    def _append_analysis(label: str, analysis: str | None) -> None:
        if not analysis:
            return
        used = sum(len(a) for a in analyses)
        remaining = max_total_chars - used
        if remaining <= 0:
            return
        text = analysis.strip()
        if len(text) > max_analysis_chars:
            text = text[:max_analysis_chars] + "\n...(analysis truncated; full video was processed)"
        if len(text) > remaining:
            text = text[:remaining] + "\n...(video analysis budget reached)"
        analyses.append(f"[{label}:\n{text}\n]")

    # 1. アップロードされた動画ファイル
    if file_urls:
        upload_dir = os.path.join(os.path.dirname(__file__), "..", "..", "uploads")
        upload_dir = os.path.normpath(upload_dir)
        VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
        for f in file_urls:
            name = f.get("name", "file")
            url = f.get("url", "")
            ext = os.path.splitext(name)[1].lower()
            if ext in VIDEO_EXTS:
                filename = url.split("/")[-1]
                local_path = os.path.join(upload_dir, filename)
                if not os.path.exists(local_path):
                    logger.warning("Uploaded video path missing: %s (%s)", local_path, name)
                    skipped.append(f"{name}: local file not found")
                    continue
                try:
                    analysis = await analyze_video(local_path)
                except Exception as e:
                    logger.warning("Video analysis failed for %s: %s", local_path, e, exc_info=True)
                    skipped.append(f"{name}: analysis failed")
                    continue
                if analysis:
                    used = sum(len(a) for a in analyses)
                    remaining = max_total_chars - used
                    if remaining <= 0:
                        analysis = None
                    elif len(analysis) > max_analysis_chars:
                        analysis = analysis[:max_analysis_chars] + "\n...(analysis truncated; full video was processed)"
                    if analysis and len(analysis) > remaining:
                        analysis = analysis[:remaining] + "\n...(video analysis budget reached)"
                if analysis:
                    analyses.append(f"[動画分析結果(Gemini):\n{analysis}\n]")
                    video_analyses[local_path] = analysis
                else:
                    skipped.append(f"{name}: analysis unavailable")

    # 2. メッセージ本文中の動画URL (YouTube, Loom)
    video_urls = extract_video_urls(content)
    logger.warning("Video URL detection: found %d URLs in message: %s", len(video_urls), video_urls)
    for v in video_urls:
        try:
            analysis = await analyze_video_url(v["platform"], v["video_id"], v["url"])
        except Exception as e:
            logger.warning("Video URL analysis failed for %s: %s", v["url"], e, exc_info=True)
            skipped.append(f"{v['url']}: analysis failed")
            continue
        if analysis and len(analysis) > max_analysis_chars:
            analysis = analysis[:max_analysis_chars] + "\n...(analysis truncated; full video was processed)"
        if analysis:
            analyses.append(f"[{v['platform']}動画分析結果(Gemini) {v['url']}:\n{analysis}\n]")

    if skipped:
        analyses.append(
            "[video analysis notes:\n"
            + "\n".join(f"- {item}" for item in skipped[:20])
            + ("\n- additional videos omitted from notes" if len(skipped) > 20 else "")
            + "\n]"
        )

    if not analyses:
        return content, video_analyses
    return content + "\n" + "\n".join(analyses), video_analyses


_PROPOSALS_DIR = "D:/dan-workspace/proposals"
_UPLOADS_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "uploads")) if 'os' in dir() else None

def _get_uploads_dir():
    import os as _os
    return _os.path.normpath(_os.path.join(_os.path.dirname(__file__), "..", "..", "uploads"))

_URL_TO_LOCAL_PATTERNS = [
    # /api/v1/proposals/{filename} → D:/dan-workspace/proposals/{filename}
    (re.compile(r'https?://localhost[:\d]*/api/v1/proposals/([\w._-]+\.html?)'), lambda m: f"{_PROPOSALS_DIR}/{m.group(1)}"),
    # /api/v1/files/{filename} → D:/done/uploads/{filename}
    (re.compile(r'https?://localhost[:\d]*/api/v1/files/([\w._-]+)'), lambda m: f"{_get_uploads_dir()}/{m.group(1)}"),
    # D:/path/to/file.html (Windows absolute paths in message text)
    (re.compile(r'(?<!\w)([A-Za-z]:/[\w./_-]+\.(?:html?|png|jpe?g|gif|webp|mp4|avi|mov|mkv|webm|pdf))(?!\w)'), lambda m: m.group(1)),
]


async def _save_media_artifacts(
    image_urls: list,
    file_urls: list | None,
    message_content: str,
    room_id: str,
    video_analyses: dict[str, str] | None = None,
) -> None:
    """ユーザーが送った画像/動画/HTMLをGeminiで抽出し、永続アーティファクトとして保存する。

    CLI起動前に実行されるため、system prompt注入に間に合う。
    video_analysesを受け取ることで、_enrich_content_with_video_analysisで
    既に実行済みの動画分析を再利用し、二重実行を防ぐ。

    検知対象:
    - image_urls: フロントエンドから添付された画像
    - file_urls: フロントエンドから添付されたファイル
    - message_content内のURL: localhost URL、ローカルファイルパス
    """
    import os
    from app.services.artifact_vision import (
        extract_and_save_media_batch,
        IMAGE_EXTS, VIDEO_EXTS, HTML_EXTS,
    )

    upload_dir = os.path.join(os.path.dirname(__file__), "..", "..", "uploads")
    upload_dir = os.path.normpath(upload_dir)

    image_paths = []
    video_paths = []
    html_paths = []

    # 1. 添付画像（image_urls）
    for url in (image_urls or []):
        filename = url.split("/")[-1]
        local_path = os.path.join(upload_dir, filename)
        if os.path.exists(local_path):
            image_paths.append(local_path)

    # 2. 添付ファイル（file_urls）
    for f in (file_urls or []):
        name = f.get("name", "file")
        url = f.get("url", "")
        ext = os.path.splitext(name)[1].lower()
        filename = url.split("/")[-1]
        local_path = os.path.join(upload_dir, filename)
        if not os.path.exists(local_path):
            continue
        if ext in IMAGE_EXTS:
            image_paths.append(local_path)
        elif ext in VIDEO_EXTS:
            video_paths.append(local_path)
        elif ext in HTML_EXTS:
            html_paths.append(local_path)

    # 3. メッセージテキスト中のURL・ファイルパスを検知
    seen_paths = set(image_paths + video_paths + html_paths)
    for pattern, resolver in _URL_TO_LOCAL_PATTERNS:
        for match in pattern.finditer(message_content or ""):
            local_path = os.path.normpath(resolver(match))
            if local_path in seen_paths or not os.path.exists(local_path):
                continue
            seen_paths.add(local_path)
            ext = os.path.splitext(local_path)[1].lower()
            if ext in IMAGE_EXTS:
                image_paths.append(local_path)
            elif ext in VIDEO_EXTS:
                video_paths.append(local_path)
            elif ext in HTML_EXTS:
                html_paths.append(local_path)

    if not image_paths and not video_paths and not html_paths:
        return

    await extract_and_save_media_batch(
        image_paths=image_paths,
        video_paths=video_paths,
        html_paths=html_paths,
        video_analyses=video_analyses or {},
        room_id=room_id,
    )


async def _save_written_artifacts(written_file_paths: list[str], room_id: str) -> None:
    """CLI完了後、ダンが書き出したファイルからビジュアル成果物を検知してGemini抽出・保存する。

    対象: HTML, 画像, 動画ファイル
    """
    import os
    from app.services.artifact_vision import (
        extract_and_save_artifact, extract_and_save_image, extract_and_save_video,
        IMAGE_EXTS, VIDEO_EXTS,
    )

    HTML_EXTS = {".html", ".htm"}
    tasks = []

    for path in written_file_paths:
        if not os.path.exists(path):
            continue
        ext = os.path.splitext(path)[1].lower()
        name = os.path.splitext(os.path.basename(path))[0]

        if ext in HTML_EXTS:
            # HTML → スクショ+ソース抽出
            artifact_type = "proposal"
            if "dashboard" in path.lower():
                artifact_type = "dashboard"
            elif "hp-projects" in path.lower():
                artifact_type = "hp"
            tasks.append(extract_and_save_artifact(
                artifact_file_path=path,
                artifact_name=name,
                artifact_type=artifact_type,
                room_id=room_id,
            ))
        elif ext in IMAGE_EXTS:
            tasks.append(extract_and_save_image(path, room_id))
        elif ext in VIDEO_EXTS:
            tasks.append(extract_and_save_video(path, room_id))

    if tasks:
        import asyncio
        results = await asyncio.gather(*tasks, return_exceptions=True)
        saved = sum(1 for r in results if not isinstance(r, Exception) and r)
        logger.info("Post-CLI artifact extraction: %d/%d saved for room %s", saved, len(tasks), room_id)


async def _register_written_chat_artifacts(
    written_file_paths: list[str],
    room_id: str | None,
    project_id: str | None,
    user_id: str,
    result_text: str = "",
) -> None:
    """Register production artifacts even if the Claude Code hook missed them."""
    from app.services.chat_artifact_registration import register_written_chat_artifacts

    await register_written_chat_artifacts(
        written_file_paths,
        room_id,
        project_id,
        user_id,
    )


def _artifact_slugs_from_written_paths(written_file_paths: list[str]) -> list[str]:
    """Extract root artifact slugs from written frontend artifact paths."""
    from app.services.chat_artifact_registration import artifact_slugs_from_written_paths

    return artifact_slugs_from_written_paths(written_file_paths)


def _schedule_artifact_alias_deploy(written_file_paths: list[str]) -> None:
    """Run the stable artifact deployment flow in the background.

    This makes the alias update a harness behavior instead of relying on the LLM
    to remember a deployment command after editing an artifact.
    """
    from app.services.chat_artifact_registration import (
        schedule_artifact_alias_deploy_from_written_paths,
    )

    schedule_artifact_alias_deploy_from_written_paths(written_file_paths)


def _fetch_latest_user_message_from_room(service: ChatService, room_id: str) -> str:
    """指定ルームの最新ユーザーメッセージを取得する（旧データ互換を含む）。"""
    if not room_id:
        return ""
    try:
        result = (
            service.supabase.table("chat_messages")
            .select("content, sender_type")
            .eq("room_id", room_id)
            .in_("sender_type", ["human", "user"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return ""
        return result.data[0].get("content", "") or ""
    except Exception as e:
        logger.warning("Failed to fetch latest user message (room=%s): %s", room_id, e)
        return ""


def _build_session_memory_summary_entry(
    *,
    archive_type: str,
    room_id: str,
    messages: list[dict],
    project_title: str = "",
    project_status: str = "",
    message_count: Optional[int] = None,
) -> Optional[str]:
    if not messages:
        return None

    chronological = list(reversed(messages))
    created_values = []
    for msg in chronological:
        dt = parse_datetime(msg.get("created_at"))
        if dt:
            created_values.append(dt)

    period_label = "-"
    if created_values:
        period_label = (
            f"{created_values[0].strftime('%Y-%m-%d %H:%M:%S')} -> "
            f"{created_values[-1].strftime('%Y-%m-%d %H:%M:%S')}"
        )

    user_msgs = [m for m in chronological if m.get("sender_type") == "human"]
    ai_msgs = [m for m in chronological if m.get("sender_type") == "ai"]
    last_user = _compact_text(user_msgs[-1]["content"]) if user_msgs else "-"
    last_ai = _compact_text(ai_msgs[-1]["content"]) if ai_msgs else "-"

    recent = chronological[-8:]
    excerpt_lines = []
    for m in recent:
        role = "User" if m.get("sender_type") == "human" else "Assistant"
        excerpt_lines.append(f"- {role}: {_compact_text(m.get('content', ''), limit=160)}")

    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    project_label = project_title.strip() if project_title else "-"
    status_label = project_status.strip() if project_status else "-"
    total_count = message_count if message_count is not None else len(messages)

    return (
        f"### {ts} [{archive_type}] room={room_id}\n"
        f"- mode: chat\n"
        f"- project_title: {project_label}\n"
        f"- project_status: {status_label}\n"
        f"- total_messages: {total_count}\n"
        f"- sampled_messages: {len(messages)}\n"
        f"- period: {period_label}\n\n"
        f"#### Last User Intent\n{last_user}\n\n"
        f"#### Last Assistant Response\n{last_ai}\n\n"
        f"#### Recent Excerpts\n" + ("\n".join(excerpt_lines) if excerpt_lines else "- (none)") + "\n\n"
    )


def _append_memory_entry(entry: str) -> None:
    if not entry:
        return

    try:
        WORKSPACE_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        log_path = WORKSPACE_MEMORY_DIR / f"{date_str}.md"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        logger.warning("Failed to append memory entry: %s", e)


async def _archive_session_summary(
    *,
    service: ChatService,
    user_id: str,
    room_id: str,
    archive_type: str,
    project_title: str = "",
    project_status: str = "",
    force: bool = False,
) -> None:
    try:
        count_result = (
            service.supabase.table("chat_messages")
            .select("id", count="exact")
            .eq("room_id", room_id)
            .execute()
        )
        total_messages = count_result.count or 0
        if total_messages == 0:
            return

        # force=True（削除時）はLLM要約を使用
        if force:
            await _archive_session_with_llm(
                service=service,
                user_id=user_id,
                room_id=room_id,
            )
            return

        # 定期アーカイブ（force=False）は従来通り
        if total_messages < COMPACTION_SNAPSHOT_INTERVAL_MESSAGES:
            return
        if total_messages % COMPACTION_SNAPSHOT_INTERVAL_MESSAGES != 0:
            return

        sample_limit = min(120, total_messages)
        messages = await service.get_messages(room_id, user_id, limit=sample_limit)
        entry = _build_session_memory_summary_entry(
            archive_type=archive_type,
            room_id=room_id,
            messages=messages,
            project_title=project_title,
            project_status=project_status,
            message_count=total_messages,
        )
        _append_memory_entry(entry or "")
    except Exception as e:
        logger.warning("Failed to archive session summary (%s): %s", archive_type, e)


async def _collect_messages_for_archive(
    *,
    service: ChatService,
    user_id: str,
    room_id: str,
) -> list[dict] | None:
    """
    アーカイブ用のメッセージをDBから収集（高速）。
    LLM呼び出しは行わない。削除前に呼び出すこと。
    """
    try:
        count_result = (
            service.supabase.table("chat_messages")
            .select("id", count="exact")
            .eq("room_id", room_id)
            .execute()
        )
        total_messages = count_result.count or 0
        if total_messages == 0:
            return None

        # last_compacted_at を取得
        last_compacted_at = None
        try:
            from app.agent.v2.session import get_session_store
            store = get_session_store()
            session = await store.get_or_create(room_id, user_id)
            last_compacted_at_str = session.get_context("last_compacted_at")
            if last_compacted_at_str:
                last_compacted_at = parse_datetime(last_compacted_at_str)
        except Exception as e:
            logger.warning(f"Failed to get session context for {room_id}: {e}")

        # メッセージ取得
        query = (
            service.supabase.table("chat_messages")
            .select("sender_type, content, created_at")
            .eq("room_id", room_id)
            .order("created_at", desc=False)
        )
        if last_compacted_at:
            query = query.gt("created_at", last_compacted_at.isoformat())

        result = query.execute()
        return result.data or None
    except Exception as e:
        logger.warning("Failed to collect messages for archive: %s", e)
        return None


async def _run_archive_in_background(room_id: str, messages: list[dict]) -> None:
    """
    収集済みメッセージからLLM要約を生成してファイルに書き込む（バックグラウンド用）。
    """
    try:
        await _archive_messages_with_llm(room_id=room_id, messages=messages)
    except Exception as e:
        logger.warning("Background archive failed for session %s: %s", room_id, e)


async def _archive_messages_with_llm(
    *,
    room_id: str,
    messages: list[dict],
) -> None:
    """収集済みメッセージからLLM要約を生成してファイルに追記する。"""
    import anthropic
    from datetime import timedelta

    # LLM用フォーマットに変換
    llm_messages = []
    for msg in messages:
        role = "user" if msg.get("sender_type") in ("human", "user") else "assistant"
        content = msg.get("content", "")
        if not content:
            continue
        llm_messages.append({"role": role, "content": content})

    if not llm_messages:
        return

    # 隣接する同一roleのメッセージをマージ
    merged = []
    for msg in llm_messages:
        if merged and merged[-1]["role"] == msg["role"]:
            merged[-1]["content"] += "\n\n" + msg["content"]
        else:
            merged.append(dict(msg))
    llm_messages = merged

    if llm_messages and llm_messages[0]["role"] == "assistant":
        llm_messages.insert(0, {"role": "user", "content": "(会話の続き)"})

    # 文字数制限
    total_chars = sum(len(m["content"]) for m in llm_messages)
    if total_chars > 80000:
        trimmed = []
        char_count = 0
        for msg in reversed(llm_messages):
            char_count += len(msg["content"])
            trimmed.append(msg)
            if char_count > 80000:
                break
        llm_messages = list(reversed(trimmed))
        if llm_messages and llm_messages[0]["role"] == "assistant":
            llm_messages.insert(0, {"role": "user", "content": "(会話の続き)"})

    flush_system = """あなたは会話ログの圧縮係です。

以下の会話の全内容を箇条書きで要約してください。

ルール:
- 全てのトピック・やり取りを漏れなく含める。省略禁止。
- 各トピックは1-2行で簡潔に。
- ユーザーの質問・相談内容、それに対する回答・結果を両方含める。
- 具体的な固有名詞（店名、商品名、URL、金額等）は省略せず残す。
- 「重要かどうか」の判断はしない。全て記録する。
- テキスト出力のみ。ツールは使わない。
"""

    llm_messages.append({
        "role": "user",
        "content": "上記の会話の全内容を箇条書きで要約してください。省略禁止。"
    })

    model = "MiniMax-M2.5"
    if settings.MINIMAX_API_KEY:
        client = anthropic.AsyncAnthropic(
            api_key=settings.MINIMAX_API_KEY,
            base_url="https://api.minimax.io/anthropic",
        )
    elif settings.ANTHROPIC_API_KEY:
        client = anthropic.AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY,
        )
    else:
        logger.warning("No LLM API key available for archive")
        return

    response = await client.messages.create(
        model=model,
        max_tokens=4000,
        system=flush_system,
        messages=llm_messages,
    )

    text_parts = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text.strip())
    summary = "\n\n".join(text_parts) if text_parts else ""

    if not summary:
        logger.warning(f"LLM summary generation failed for session {room_id}")
        return

    jst = timezone(timedelta(hours=9))
    last_msg_created_at = messages[-1].get("created_at")
    if last_msg_created_at:
        msg_date = parse_datetime(last_msg_created_at).astimezone(jst)
    else:
        msg_date = datetime.now(jst)
    date_str = msg_date.strftime("%Y-%m-%d")
    time_str = msg_date.strftime("%H:%M")

    WORKSPACE_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    filepath = WORKSPACE_MEMORY_DIR / f"{date_str}.md"

    entry = f"\n\n## {time_str} session={room_id} [delete-archive]\n\n{summary}\n"
    with filepath.open("a", encoding="utf-8") as f:
        f.write(entry)
    logger.info(f"Delete archive (LLM summary) saved to {filepath}")

    await _update_long_term_memory_standalone(client, model, summary)


async def _archive_session_with_llm(
    *,
    service: ChatService,
    user_id: str,
    room_id: str,
) -> None:
    """
    セッション削除時のLLM要約アーカイブ。

    1. agent_sessions_v2 から last_compacted_at を確認
    2. last_compacted_at 以降のメッセージだけを抽出（コンパクション済み分を除外）
    3. LLMで要約して日付ファイルに追記
    4. MEMORY.md（長期記憶）も更新
    """
    import anthropic
    from datetime import timedelta

    # 1. セッションから last_compacted_at を取得
    last_compacted_at = None
    try:
        from app.agent.v2.session import get_session_store
        store = get_session_store()
        session = await store.get_or_create(room_id, user_id)
        last_compacted_at_str = session.get_context("last_compacted_at")
        if last_compacted_at_str:
            last_compacted_at = parse_datetime(last_compacted_at_str)
            logger.info(f"Session {room_id} last_compacted_at: {last_compacted_at_str}")
    except Exception as e:
        logger.warning(f"Failed to get session context for {room_id}: {e}")

    # 2. メッセージ取得（last_compacted_at以降、または全件）
    query = (
        service.supabase.table("chat_messages")
        .select("sender_type, content, created_at")
        .eq("room_id", room_id)
        .order("created_at", desc=False)
    )
    if last_compacted_at:
        query = query.gt("created_at", last_compacted_at.isoformat())

    result = query.execute()
    messages = result.data or []

    if not messages:
        logger.info(f"No uncompacted messages for session {room_id}, skipping archive")
        return

    # 3. LLM用フォーマットに変換（sender_type → role）
    llm_messages = []
    for msg in messages:
        role = "user" if msg.get("sender_type") in ("human", "user") else "assistant"
        content = msg.get("content", "")
        if not content:
            continue
        llm_messages.append({"role": "user" if role == "user" else "assistant", "content": content})

    if not llm_messages:
        return

    # 隣接する同一roleのメッセージをマージ（Anthropic APIの制約対応）
    merged = []
    for msg in llm_messages:
        if merged and merged[-1]["role"] == msg["role"]:
            merged[-1]["content"] += "\n\n" + msg["content"]
        else:
            merged.append(dict(msg))
    llm_messages = merged

    # 先頭がassistantの場合、空のuserメッセージを挿入
    if llm_messages and llm_messages[0]["role"] == "assistant":
        llm_messages.insert(0, {"role": "user", "content": "(会話の続き)"})

    # 文字数制限（80K超の場合は直近分に制限）
    total_chars = sum(len(m["content"]) for m in llm_messages)
    if total_chars > 80000:
        trimmed = []
        char_count = 0
        for msg in reversed(llm_messages):
            char_count += len(msg["content"])
            trimmed.append(msg)
            if char_count > 80000:
                break
        llm_messages = list(reversed(trimmed))
        # 先頭がassistantの場合の再チェック
        if llm_messages and llm_messages[0]["role"] == "assistant":
            llm_messages.insert(0, {"role": "user", "content": "(会話の続き)"})

    # 4. LLM呼び出し（runner.pyと同じプロンプト）
    flush_system = """あなたは会話ログの圧縮係です。

以下の会話の全内容を箇条書きで要約してください。

ルール:
- 全てのトピック・やり取りを漏れなく含める。省略禁止。
- 各トピックは1-2行で簡潔に。
- ユーザーの質問・相談内容、それに対する回答・結果を両方含める。
- 具体的な固有名詞（店名、商品名、URL、金額等）は省略せず残す。
- 「重要かどうか」の判断はしない。全て記録する。
- テキスト出力のみ。ツールは使わない。
"""

    llm_messages.append({
        "role": "user",
        "content": "上記の会話の全内容を箇条書きで要約してください。省略禁止。"
    })

    model = "MiniMax-M2.5"
    if settings.MINIMAX_API_KEY:
        client = anthropic.AsyncAnthropic(
            api_key=settings.MINIMAX_API_KEY,
            base_url="https://api.minimax.io/anthropic",
        )
    elif settings.ANTHROPIC_API_KEY:
        client = anthropic.AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY,
        )
    else:
        logger.warning("No LLM API key available, falling back to excerpt archive")
        return

    response = await client.messages.create(
        model=model,
        max_tokens=4000,
        system=flush_system,
        messages=llm_messages,
    )

    summary = ""
    text_parts = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text.strip())
    if text_parts:
        summary = "\n\n".join(text_parts)

    if not summary:
        logger.warning(f"LLM summary generation failed for session {room_id}")
        return

    # 5. メッセージの実際の日付でファイルに追記
    jst = timezone(timedelta(hours=9))
    last_msg_created_at = messages[-1].get("created_at")
    if last_msg_created_at:
        msg_date = parse_datetime(last_msg_created_at).astimezone(jst)
    else:
        msg_date = datetime.now(jst)
    date_str = msg_date.strftime("%Y-%m-%d")
    time_str = msg_date.strftime("%H:%M")

    WORKSPACE_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    filepath = WORKSPACE_MEMORY_DIR / f"{date_str}.md"

    entry = f"\n\n## {time_str} session={room_id} [delete-archive]\n\n{summary}\n"
    with filepath.open("a", encoding="utf-8") as f:
        f.write(entry)
    logger.info(f"Delete archive (LLM summary) saved to {filepath}")

    # 6. MEMORY.md（長期記憶）の更新
    await _update_long_term_memory_standalone(client, model, summary)


async def _update_long_term_memory_standalone(client, model: str, conversation_summary: str) -> None:
    """
    MEMORY.mdを自動更新する（スタンドアロン版）。
    runner.py の _update_long_term_memory と同じロジック。
    """
    memory_file = WORKSPACE_DIR / "MEMORY.md"
    current_memory = ""
    if memory_file.exists():
        current_memory = memory_file.read_text(encoding="utf-8")

    system = """あなたは長期記憶の管理係です。

「現在の長期記憶」と「今回の会話要約」を見て、長期記憶の更新版を出力してください。

長期記憶に残すべき情報:
- ユーザーの好み・習慣（よく使うサービス、好きなブランド等）
- アカウント情報（メールアドレス、住所、ユーザー名等）
- 繰り返し参照される事実（家族構成、仕事、定期的な予定等）
- 重要な決定事項（購入したもの、契約したサービス等）
- Danの動作に関するフィードバック（こうしてほしい、これはやめて等）

ルール:
- 現在の長期記憶にある情報は保持する（消さない）
- 新しい情報があれば追加する
- 古い情報が更新された場合は最新に書き換える
- 一時的な話題（天気、一回きりの質問等）は含めない
- Markdown形式で、セクション分けして整理する
- テキスト出力のみ。ツールは使わない。
"""

    messages = [
        {
            "role": "user",
            "content": f"## 現在の長期記憶\n\n{current_memory}\n\n---\n\n## 今回の会話要約\n\n{conversation_summary}\n\n---\n\n上記を統合した、更新版の長期記憶をMarkdownで出力してください。",
        }
    ]

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=2000,
            system=system,
            messages=messages,
        )

        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text.strip())

        if text_parts:
            updated_memory = "\n\n".join(text_parts)
            memory_file.write_text(updated_memory, encoding="utf-8")
            logger.info("MEMORY.md updated with long-term memory (delete archive)")
    except Exception as e:
        logger.warning(f"Failed to update MEMORY.md during delete archive: {e}")


def set_auth_cookies(response: Response, access_token: str, refresh_token: str, remember_me: bool = False):
    """Set HttpOnly cookies for authentication"""
    # Access token cookie (shorter lived)
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=access_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN or None,
        max_age=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    
    # Refresh token cookie (longer lived)
    refresh_max_age = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60 if remember_me else 24 * 60 * 60
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN or None,
        max_age=refresh_max_age,
        path="/api/v1/chat/refresh",  # Only sent to refresh endpoint
    )


def clear_auth_cookies(response: Response):
    """Clear authentication cookies"""
    response.delete_cookie(
        key=ACCESS_TOKEN_COOKIE,
        domain=settings.COOKIE_DOMAIN or None,
    )
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE,
        domain=settings.COOKIE_DOMAIN or None,
        path="/api/v1/chat/refresh",
    )

# Base URL for invite links (should be configured in settings)
INVITE_BASE_URL = "https://done.app/i/"


def get_chat_service() -> ChatService:
    """Get ChatService instance"""
    return ChatService()


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> TokenData:
    """Get current authenticated user from JWT token (Cookie or Bearer header)"""
    token = None
    
    # First, try to get token from cookie
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    
    # If no cookie, try Bearer header
    if not token and credentials:
        token = credentials.credentials
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    token_data = decode_access_token(token)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    return token_data


async def get_optional_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[TokenData]:
    """Get current user if authenticated, None otherwise"""
    token = None
    
    # First, try to get token from cookie
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    
    # If no cookie, try Bearer header
    if not token and credentials:
        token = credentials.credentials
    
    if not token:
        return None
    return decode_access_token(token)


# ==================== Auth Routes ====================

@router.post("/register", response_model=UserResponse)
async def register(
    request: RegisterRequest,
    service: ChatService = Depends(get_chat_service),
):
    """Register a new user"""
    try:
        user = await service.create_user(
            email=request.email,
            password=request.password,
            display_name=request.display_name,
        )
        # Link guest invites via guest tokens
        if request.guest_tokens:
            try:
                from app.services.collab_service import CollabService
                collab = CollabService()
                await collab.link_user_by_tokens(user["id"], request.guest_tokens)
            except Exception:
                pass  # Non-critical
        return UserResponse(**user)
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(status_code=400, detail="Email already registered")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    response: Response,
    service: ChatService = Depends(get_chat_service),
):
    """Login and get JWT token"""
    user = await service.authenticate_user(request.email, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Link guest invites via guest tokens
    if request.guest_tokens:
        try:
            from app.services.collab_service import CollabService
            collab = CollabService()
            await collab.link_user_by_tokens(user["id"], request.guest_tokens)
        except Exception:
            pass  # Non-critical

    token_pair = create_token_pair(user_id=user["id"], email=user["email"])
    set_auth_cookies(response, token_pair.access_token, token_pair.refresh_token)
    return TokenResponse(access_token=token_pair.access_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token_endpoint(
    request: Request,
    response: Response,
):
    """Refresh access token using refresh token from cookie"""
    refresh_token_value = request.cookies.get(REFRESH_TOKEN_COOKIE)
    if not refresh_token_value:
        raise HTTPException(status_code=401, detail="Refresh token not found")
    
    token_pair = refresh_tokens(refresh_token_value)
    if not token_pair:
        clear_auth_cookies(response)
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    
    set_auth_cookies(response, token_pair.access_token, token_pair.refresh_token)
    return TokenResponse(access_token=token_pair.access_token)


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Get current user profile"""
    user = await service.get_user_by_id(current_user.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**user)


@router.patch("/me", response_model=UserResponse)
async def update_me(
    request: UserUpdateRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Update current user profile"""
    user = await service.update_user(
        user_id=current_user.user_id,
        display_name=request.display_name,
        avatar_url=request.avatar_url,
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**user)


# ==================== Invite Routes ====================

@router.post("/invite", response_model=InviteResponse)
async def create_invite(
    request: InviteCreateRequest = InviteCreateRequest(),
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Create an invite link"""
    invite = await service.create_invite(
        creator_id=current_user.user_id,
        max_uses=request.max_uses,
        expires_in_hours=request.expires_in_hours,
    )
    return InviteResponse(
        id=invite["id"],
        code=invite["code"],
        invite_url=f"{INVITE_BASE_URL}{invite['code']}",
        max_uses=invite["max_uses"],
        use_count=invite["use_count"],
        expires_at=invite.get("expires_at"),
        created_at=invite["created_at"],
    )


@router.get("/invite/{code}", response_model=InviteInfoResponse)
async def get_invite(
    code: str,
    service: ChatService = Depends(get_chat_service),
):
    """Get invite information"""
    invite = await service.get_invite_by_code(code)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    
    # Check if valid
    is_valid = True
    if invite.get("expires_at"):
        expires_at = parse_datetime(invite["expires_at"])
        if datetime.now(timezone.utc).replace(tzinfo=expires_at.tzinfo) > expires_at:
            is_valid = False
    if invite["use_count"] >= invite["max_uses"]:
        is_valid = False
    
    creator = invite.get("creator", {})
    return InviteInfoResponse(
        code=invite["code"],
        creator_name=creator.get("display_name", "Unknown"),
        creator_avatar_url=creator.get("avatar_url"),
        expires_at=invite.get("expires_at"),
        is_valid=is_valid,
    )


@router.post("/invite/{code}/accept", response_model=InviteAcceptResponse)
async def accept_invite(
    code: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Accept an invite and become friends"""
    try:
        result = await service.accept_invite(code, current_user.user_id)
        return InviteAcceptResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== Friends Routes ====================

@router.get("/friends", response_model=FriendsListResponse)
async def get_friends(
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Get friends list"""
    friends = await service.get_friends(current_user.user_id)
    return FriendsListResponse(friends=[FriendResponse(**f) for f in friends])


@router.delete("/friends/{friend_id}")
async def delete_friend(
    friend_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Delete a friend"""
    await service.delete_friend(current_user.user_id, friend_id)
    return {"message": "Friend deleted successfully"}


# ==================== Room Routes ====================

@router.get("/rooms", response_model=RoomsListResponse)
async def get_rooms(
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Get chat rooms"""
    rooms = await service.get_rooms(current_user.user_id)
    return RoomsListResponse(rooms=[RoomResponse(**r) for r in rooms])


@router.post("/rooms", response_model=RoomResponse)
async def create_room(
    request: RoomCreateRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Create a group chat room"""
    room = await service.create_room(
        creator_id=current_user.user_id,
        name=request.name,
        member_ids=request.member_ids,
    )
    return RoomResponse(**room)


@router.get("/rooms/{room_id}", response_model=RoomResponse)
async def get_room(
    room_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Get room details"""
    room = await service.get_room(room_id, current_user.user_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return RoomResponse(**room)


@router.patch("/rooms/{room_id}", response_model=RoomResponse)
async def update_room(
    room_id: str,
    request: RoomUpdateRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Update room settings"""
    try:
        room = await service.update_room(room_id, current_user.user_id, name=request.name)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        return RoomResponse(**room)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/rooms/{room_id}/members", response_model=RoomMembersListResponse)
async def get_room_members(
    room_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Get room members"""
    try:
        members = await service.get_room_members(room_id, current_user.user_id)
        return RoomMembersListResponse(members=[RoomMemberResponse(**m) for m in members])
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/rooms/{room_id}/members", response_model=RoomMemberResponse)
async def add_room_member(
    room_id: str,
    request: AddMemberRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Add a member to the room"""
    try:
        member = await service.add_room_member(room_id, current_user.user_id, request.user_id)
        # Get full member info
        members = await service.get_room_members(room_id, current_user.user_id)
        for m in members:
            if m["user_id"] == request.user_id:
                return RoomMemberResponse(**m)
        return member
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ==================== Message Routes ====================

@router.get("/rooms/{room_id}/messages/search", response_model=MessagesListResponse)
async def search_messages(
    room_id: str,
    q: str,
    limit: int = 50,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Keyword-search a room's full message history (content match, newest first)."""
    try:
        if not q or not q.strip():
            return MessagesListResponse(messages=[])
        messages = await service.search_messages(room_id, current_user.user_id, q, limit=min(limit, 100))
        return MessagesListResponse(messages=[MessageResponse(**m) for m in messages])
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.warning("Temporary failure in search_messages (room=%s): %s", room_id, e)
        raise HTTPException(status_code=503, detail="Temporary backend error. Please retry.")


@router.get("/rooms/{room_id}/messages", response_model=MessagesListResponse)
async def get_messages(
    room_id: str,
    limit: int = 50,
    before: Optional[str] = None,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Get messages from a room"""
    try:
        messages = await service.get_messages(room_id, current_user.user_id, limit=limit, before=before)
        return MessagesListResponse(messages=[MessageResponse(**m) for m in messages])
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.warning("Temporary failure in get_messages (room=%s): %s", room_id, e)
        raise HTTPException(status_code=503, detail="Temporary backend error. Please retry.")


@router.post("/rooms/{room_id}/messages", response_model=MessageResponse)
async def send_message(
    room_id: str,
    request: MessageSendRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Send a message to a room"""
    try:
        message = await service.send_message(room_id, current_user.user_id, request.content, reply_to_id=request.reply_to_id)

        # プロジェクトチャットの場合、プロジェクトのupdated_atを更新（リスト繰り上げ）
        try:
            from app.services.project_service import ProjectService
            ps = ProjectService()
            project = await ps.get_project_by_room_id(room_id)
            if project:
                await ps.update_project(project["id"], current_user.user_id, summary=project.get("summary"))
        except Exception:
            pass  # プロジェクト更新失敗はメッセージ送信に影響させない

        # Get sender info
        user = await service.get_user_by_id(current_user.user_id)
        return MessageResponse(
            id=message["id"],
            room_id=message["room_id"],
            sender_id=message["sender_id"],
            sender_name=user["display_name"] if user else "Unknown",
            sender_type=message["sender_type"],
            content=message["content"],
            created_at=message["created_at"],
        )
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/rooms/{room_id}/dry-run")
async def dry_run_message(
    room_id: str,
    request: MessageSendRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    Dry-run: 認証・ルーム存在・メンバーシップを検証するが、DBには何も書き込まない。
    事業部CLIのデバッグ用。履歴を汚さずに接続テストができる。
    """
    # ルーム存在 & メンバーシップ確認
    room = await service.get_room(room_id, current_user.user_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found or not a member")

    return {
        "status": "ok",
        "room_id": room_id,
        "content_received": request.content,
    }


@router.post("/rooms/{room_id}/read", response_model=ReadMarkResponse)
async def mark_as_read(
    room_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Mark messages as read"""
    success = await service.mark_as_read(room_id, current_user.user_id)
    return ReadMarkResponse(success=success, read_at=datetime.now(timezone.utc))


# ==================== AI Settings Routes ====================

@router.get("/rooms/{room_id}/ai", response_model=AISettingsResponse)
async def get_ai_settings(
    room_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Get AI settings for a room"""
    try:
        settings = await service.get_ai_settings(room_id, current_user.user_id)
        if not settings:
            raise HTTPException(status_code=404, detail="AI settings not found")
        return AISettingsResponse(**settings)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.patch("/rooms/{room_id}/ai", response_model=AISettingsResponse)
async def update_ai_settings(
    room_id: str,
    request: AISettingsUpdateRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Update AI settings for a room"""
    try:
        settings = await service.update_ai_settings(
            room_id,
            current_user.user_id,
            enabled=request.enabled,
            mode=request.mode,
            personality=request.personality,
            auto_reply_delay_ms=request.auto_reply_delay_ms,
        )
        if not settings:
            raise HTTPException(status_code=404, detail="AI settings not found")
        return AISettingsResponse(**settings)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/rooms/{room_id}/ai/summary", response_model=AISummaryResponse)
async def get_ai_summary(
    room_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Get AI summary of recent conversation"""
    try:
        summary = await service.get_ai_summary(room_id, current_user.user_id)
        return AISummaryResponse(**summary)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ==================== Dan Page Routes (2E) ====================

@router.get("/dan", response_model=DanRoomResponse)
async def get_dan_room(
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    ダンページ（ユーザーとダンの1対1ルーム）を取得
    
    - ルームが存在しない場合は自動作成
    - 未読メッセージ数と保留中の提案数も返す
    """
    try:
        dan_room = await service.get_or_create_dan_room(current_user.user_id)
        return DanRoomResponse(**dan_room)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dan/messages", response_model=MessagesListResponse)
async def get_dan_messages(
    limit: int = 50,
    before: Optional[str] = None,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """ダンページのメッセージを取得"""
    try:
        dan_room = await service.get_or_create_dan_room(current_user.user_id)
        messages = await service.get_messages(dan_room["id"], current_user.user_id, limit=limit, before=before)
        return MessagesListResponse(messages=[MessageResponse(**m) for m in messages])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dan/skills")
async def list_dan_skills(current_user: TokenData = Depends(get_current_user)):
    """スラッシュコマンド候補用のスキル一覧"""
    from app.agent.v2.tools import SkillRegistry
    skills = SkillRegistry.list_all()
    return {
        "skills": [
            {"name": s.name, "display_name": s.display_name, "description": s.description}
            for s in skills
        ]
    }


@router.post("/dan/skills/reload")
async def reload_dan_skills():
    """SkillRegistry をディスクから再読込する（ダンコア再起動なしでスキル変更を反映）。

    SkillRegistry はプロセス内シングルトンで起動時に一度だけロードされるため、
    `.claude/skills/**` を追加・変更してもダンコアを再起動するまで反映されない。
    このエンドポイントは `.claude/skills/*/SKILL.md` をディスクから読み直すだけで、
    実行中のチャットセッションには一切触れない。auto_deploy.py が git pull 時に叩く。

    /sandbox/restart と同様、localhost 運用エンドポイントなので認証は不要。
    """
    from app.agent.v2.tools import SkillRegistry
    SkillRegistry.reload()
    skills = SkillRegistry.list_all()
    return {"reloaded": True, "count": len(skills), "names": [s.name for s in skills]}


async def _prepend_first_event(first_task, agen):
    """Yield an already-primed first event, then the remainder of an async generator.

    Used by the parallel-save fast path: process_message_cli's cold start is kicked
    off (its first __anext__) before the user message is saved, so the DB save
    overlaps the CLI cold start. The first event is awaited via ``first_task``;
    this wrapper splices it back in front of the rest of the stream so the
    consumer loop below stays unchanged.
    """
    try:
        first = await first_task
    except StopAsyncIteration:
        return
    yield first
    async for ev in agen:
        yield ev


# --- 早期キャンセルの完全形 --------------------------------------------------
# フロントが送信の瞬間に本物のUUIDを発行し、それがそのままDBの行IDになる
# （send_message の message_id）。よってキャンセルはいつ来てもIDで確実に削除
# できる。唯一残るのは到着順レース（キャンセル→削除が空振り→その後に保存が
# 完了して行が残る）で、これは「墓標」= 空振りした削除のIDを短時間覚えておき、
# 保存直後に照合して即取り消すことで塞ぐ。対応表・仮IDは存在しない。
_CANCEL_TOMBSTONE_TTL = 180.0
_cancel_tombstones: dict = {}  # (room_id, message_id) -> armed-at epoch


def _tombstone_prune() -> None:
    import time as _t
    now = _t.time()
    for k in [k for k, ts in _cancel_tombstones.items() if now - ts > _CANCEL_TOMBSTONE_TTL]:
        _cancel_tombstones.pop(k, None)


def _check_cancel_tombstone(room_id: str, message_id: str | None, service) -> bool:
    """保存完了直後に呼ぶ。削除が先に空振りしていたら行を即取り消して True。"""
    if not message_id:
        return False
    _tombstone_prune()
    if _cancel_tombstones.pop((room_id, message_id), None) is None:
        return False
    try:
        service.supabase.table("chat_messages").delete().eq("id", message_id).eq("sender_type", "human").execute()
        logger.warning("early-cancelled user message deleted on save: %s", message_id[:8])
        # 一覧サムネの巻き戻し: 保存時に焼き込まれたプレビューを実際の最新で書き直す
        from app.services.chat_service import refresh_room_preview_sync
        refresh_room_preview_sync(service.supabase, room_id)
    except Exception as e:
        logger.warning("early-cancel delete failed for %s: %s", message_id, e)
    return True


@router.post("/dan/messages/stream")
async def send_dan_message_stream(
    request: MessageSendRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """ダンにメッセージを送信（SSEストリーミング版）- Agent v2を使用"""
    from starlette.responses import StreamingResponse
    from app.services.progress_callback import (
        ProgressCallbackRegistry,
        set_current_request_id,
    )
    import uuid
    import asyncio
    
    # 挨拶のハードコード返答は廃止。必ずAgent v2に渡す。
    
    async def generate_stream():
        latency_start = time.perf_counter()
        latency_marks: list[tuple[str, float]] = []

        def mark_latency(label: str) -> None:
            latency_marks.append((label, time.perf_counter() - latency_start))

        def log_latency(room_id: str = "") -> None:
            if not latency_marks:
                return
            timeline = " ".join(f"{label}={elapsed:.3f}s" for label, elapsed in latency_marks)
            message = f"[DAN_LATENCY] room={room_id or '-'} {timeline}"
            logger.info(message)
            _write_latency_log(message)

        mark_latency("request_start")
        # リクエスト到着時刻。並列保存パス（DAN_PARALLEL_SEND）はユーザーメッセージの
        # insert を run 作成・CLI起動の後に行うため、DBの now() に任せると
        # 「runがメッセージより先」に時刻が逆転し、フロントの時系列表示が崩れる。
        # 到着時刻を created_at として明示し、保存順に関係なく実時刻を保つ。
        from datetime import datetime as _dt, timezone as _tz
        request_arrival_iso = _dt.now(_tz.utc).isoformat()
        # リクエストIDを生成（プログレスコールバック用）
        request_id = str(uuid.uuid4())
        progress_queue = ProgressCallbackRegistry.create_queue(request_id)
        set_current_request_id(request_id)

        # キャンセルフラグを登録
        from app.services.cancellation import CancellationRegistry
        room_id_for_cancel = None  # 後で設定
        done_sent = False  # done イベント送信済みフラグ
        result_saved = False  # AI回答DB保存済みフラグ
        cli_saved_ai_message = False  # CLIスレッドがAI応答をDB保存済みか
        replan_requested = _is_replan_request(request.content)
        # スラッシュコマンド検出: /skill-name でスキルを明示起動
        skill_name, skill_remaining = _extract_skill_command(request.content)
        skill_injection = None
        if skill_name:
            from app.agent.v2.tools import SkillRegistry
            skill = SkillRegistry.get(skill_name)
            if skill:
                skill_content = skill.markdown_content or skill.raw_content or ""
                skill_injection = f"## スキル指示: {skill.display_name}\n\n以下のスキルのルールに必ず従って作業すること。\n\n{skill_content}"
        # スキル検出時はコンテンツから /skill-name を除去
        effective_content = skill_remaining if skill_injection else request.content
        run_id = None

        async def _save_project_event_safe(project_service, **kwargs):
            """Best-effort event write; avoid blocking chat execution on log writes."""
            try:
                await asyncio.wait_for(
                    project_service.save_execution_event(**kwargs),
                    timeout=5,
                )
            except Exception as event_err:
                logger.debug(
                    "Skipped execution_event write (room=%s, type=%s): %s",
                    kwargs.get("room_id"),
                    kwargs.get("event_type"),
                    event_err,
                )

        try:
            project_info = {}
            current_project_run = None
            should_supersede_existing_run = False
            if request.session_id:
                try:
                    from app.services.project_service import ProjectService
                    from app.services.run_service import RunService

                    preload_project_service = ProjectService()
                    proj_result = (
                        preload_project_service.supabase.table("projects")
                        .select("id, title, description, status, room_id")
                        .eq("room_id", request.session_id)
                        .execute()
                    )
                    if proj_result.data:
                        project_info = proj_result.data[0]
                        current_project_run = await RunService().get_current_run(
                            project_info["id"]
                        )
                        should_supersede_existing_run = bool(
                            current_project_run
                            and current_project_run.get("state")
                            not in {"completed", "failed", "superseded"}
                        )
                        if CancellationRegistry.is_active(request.session_id):
                            should_supersede_existing_run = True
                except Exception:
                    pass
            # 観察者はダンの回答完了後に起動する（1807行目付近）

            # Step 1: ユーザーメッセージを保存（or 既存メッセージを上書き）
            mark_latency("project_preload")
            media_content = _build_content_with_media(request.content, request.image_urls or [], request.file_urls or [])
            # 並列保存の判定: 一番多い「既存セッションへのプレーンな新規メッセージ」だけ、
            # ユーザーメッセージのDB保存(send_message ~1.27s)を CLI cold start の裏で実行する。
            # replace(上書き)/新規ルーム/常駐ストリーミングは従来どおり逐次保存する。
            # DAN_PARALLEL_SEND=0 で即座に従来挙動へ戻せる。
            import os as _os
            _parallel_send_enabled = _os.getenv("DAN_PARALLEL_SEND", "1").strip().lower() not in ("0", "false", "no", "off")
            try:
                from app.agent.streaming_session import streaming_enabled as _streaming_enabled
                _streaming_on = _streaming_enabled()
            except Exception:
                _streaming_on = False
            _parallel_save = (
                _parallel_send_enabled
                and bool(request.session_id)
                and not request.replace_message_id
                and not _streaming_on
            )
            if request.replace_message_id:
                # キャンセル後の再送信: 既存メッセージの内容を上書き（INSERTしない）
                room_id = request.session_id
                try:
                    service.supabase.table("chat_messages").update(
                        {"content": media_content}
                    ).eq("id", request.replace_message_id).eq("sender_type", "human").execute()
                    # 更新後のメッセージを取得
                    updated = service.supabase.table("chat_messages").select("*").eq("id", request.replace_message_id).execute()
                    message = updated.data[0] if updated.data else {"id": request.replace_message_id, "sender_id": current_user.user_id, "sender_type": "human", "room_id": room_id, "content": media_content}
                except Exception as e:
                    logger.warning("Failed to update message %s, falling back to insert: %s", request.replace_message_id, e)
                    message = await service.send_message(room_id, current_user.user_id, media_content, sender_type="human", reply_to_id=request.reply_to_id)
            elif _parallel_save:
                # 並列保存パス: ここでは保存せず room_id だけ確定する。実際の send_message は
                # process_message_cli の cold start を起動した直後（裏で並走）に実行する。
                room_id = request.session_id
                message = None
            elif request.session_id:
                room_id = request.session_id
                message = await service.send_message(room_id, current_user.user_id, media_content, sender_type="human", reply_to_id=request.reply_to_id, message_id=request.client_message_id)
                _check_cancel_tombstone(room_id, message["id"], service)
            else:
                message = await service.send_dan_message(current_user.user_id, media_content)
                room_id = message["room_id"]
                _check_cancel_tombstone(room_id, message["id"], service)
            # 送信者名は send_message の戻り値（sender_name）を再利用する。
            # 従来はここで users を再度引いており、send_message 内の get_sender と
            # 二重の往復になっていた。上書き(replace)経路は raw 行で sender_name を
            # 持たないため、その時だけフォールバックで取得する。
            # 並列保存パス(message is None)では保存時に解決するため、ここはスキップ。
            if message is not None:
                sender_display_name = message.get("sender_name")
                if not sender_display_name:
                    _u = await service.get_user_by_id(current_user.user_id)
                    sender_display_name = _u["display_name"] if _u else "You"
                mark_latency("message_saved")
            else:
                sender_display_name = None

            # 返信先メッセージの内容を取得（ダンのコンテキスト注入 + SSEレスポンス用）
            reply_context_prefix = ""
            _reply_msg_data = None
            if request.reply_to_id:
                try:
                    reply_msg_result = service.supabase.table("chat_messages").select(
                        "id, sender_type, content, created_at, sender:users!sender_id(display_name)"
                    ).eq("id", request.reply_to_id).execute()
                    if reply_msg_result.data:
                        _reply_msg_data = reply_msg_result.data[0]
                        rm_sender = _reply_msg_data.get("sender", {}).get("display_name", "Unknown") if _reply_msg_data.get("sender") else "Unknown"
                        rm_type = "ダン" if _reply_msg_data["sender_type"] == "ai" else rm_sender
                        reply_context_prefix = f"[返信先メッセージ（{rm_type}）: {_reply_msg_data['content'][:500]}]\n\n"
                except Exception:
                    pass

            # 追い連絡（DAN_STREAMING_INPUT）: すでに常駐セッションでターン実行中なら、
            # この新規メッセージは「割り込んで止める」のではなく、次のステップ境界で
            # 反映する追い連絡として扱う。→ supersede(kill) はスキップする。
            _followup_session = None
            try:
                from app.agent.streaming_session import streaming_enabled, get_session
                if streaming_enabled():
                    _sess = get_session(room_id)
                    if _sess is not None and _sess.is_turn_active():
                        _followup_session = _sess
            except Exception:
                _followup_session = None

            # 方針変更要求時は、既存の同一ルーム実行を先に止める（追い連絡経路では止めない）
            if (replan_requested or should_supersede_existing_run) and _followup_session is None:
                try:
                    CancellationRegistry.cancel(room_id)
                    from app.agent.cli_runner import kill_cli_process
                    # allow_arm_pending=False は必須。ここは「今走っている残骸を
                    # 止める」内部掃除であり、「次に始まるターンを殺す予約」を
                    # 武装すると、その“次のターン”はこの送信自身のターンなので
                    # 自爆する（2026-07-24 吉川ルームで実測: 送るたびに無視される
                    # 呪われた部屋になる）。予約を武装してよいのはキャンセルAPIが
                    # 取消対象メッセージIDを受け取った場合だけ。
                    kill_cli_process(room_id, allow_arm_pending=False)
                except Exception:
                    pass

            # キャンセルフラグを登録（room_idが確定してから）
            room_id_for_cancel = room_id
            CancellationRegistry.register(room_id)

            # ユーザーメッセージのエコー（即時保存パスのみ即送出。並列保存は cold start 起動後に送出）
            if message is not None:
                user_message = {
                    "id": message["id"],
                    "room_id": room_id,
                    "sender_id": message["sender_id"],
                    "sender_name": sender_display_name or "You",
                    "sender_type": message["sender_type"],
                    "content": message["content"],
                    "created_at": message["created_at"].isoformat() if hasattr(message["created_at"], 'isoformat') else str(message["created_at"]),
                }
                if request.reply_to_id:
                    user_message["reply_to_id"] = request.reply_to_id
                    if _reply_msg_data:
                        user_message["reply_to_message"] = {
                            "id": _reply_msg_data["id"],
                            "sender_name": _reply_msg_data["sender"]["display_name"] if _reply_msg_data.get("sender") else "Unknown",
                            "sender_type": _reply_msg_data["sender_type"],
                            "content": _reply_msg_data["content"][:200],
                            "created_at": _reply_msg_data["created_at"],
                        }

                # ユーザーメッセージを送信（session_id付き）
                yield f"data: {json.dumps({'type': 'user_message', 'session_id': room_id, 'message': user_message})}\n\n"
                mark_latency("user_sse_sent")

            # 追い連絡を常駐セッションへ注入し、即ackして本リクエストは終了する。
            # 本ターンの回答（次の境界以降）は、継続中の最初のSSEストリームが描画する。
            if _followup_session is not None:
                try:
                    followup_content = _build_content_with_media(
                        effective_content, request.image_urls or [], request.file_urls or []
                    )
                    _followup_session.submit_followup(followup_content)
                    logger.info("[STREAMING] follow-up queued for room=%s msg=%s", room_id, message["id"])
                    yield f"data: {json.dumps({'type': 'followup_queued', 'session_id': room_id, 'message_id': message['id']})}\n\n"
                except Exception as e:
                    logger.warning("submit_followup failed (room=%s): %s", room_id, e)
                    yield f"data: {json.dumps({'type': 'error', 'session_id': room_id, 'message': '追い連絡の注入に失敗しました'})}\n\n"
                result_saved = True
                done_sent = True
                yield f"data: {json.dumps({'type': 'done', 'session_id': room_id})}\n\n"
                return

            # Update project's updated_at on user message
            try:
                from datetime import datetime, timezone
                project_service.supabase.table("projects").update({
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", project_info["id"]).execute()
            except Exception:
                pass

            # Step 1.5（廃止）: ここで毎ターン get_messages（直近11件＋返信先取得で
            # 約0.28sの往復）を実行していたが、conversation_history はどこからも
            # 参照されない死にコードだった。CLI は --resume と DB reseed で文脈を
            # 持つため不要。往復を削除して TTFT を短縮する。
            mark_latency("history_loaded")
            
            # ========================================
            # CLI Runner でメッセージ処理
            # （全チャットがプロジェクトなので分岐不要。インデント維持のためif True）
            # ========================================
            if True:
                from app.agent.cli_runner import process_message_cli
                from app.api.project_routes import _format_tool_label
                from app.services.run_service import RunService

                project_service = ProjectService()
                run_service = RunService()
                final_text = ""
                reasoning_steps = []   # 短いラベル（プロセスモニター表示用）
                reasoning_full = []    # 全文（DB保存用、フロントで展開表示）
                step_counter = 0
                written_file_paths = []  # CLIが書き出したファイルパスを収集
                run_state = None
                if current_project_run is None and should_supersede_existing_run:
                    try:
                        current_project_run = await run_service.get_current_run(project_info["id"])
                    except Exception:
                        current_project_run = None
                try:
                    run_metadata = {}
                    if should_supersede_existing_run and current_project_run:
                        run_metadata["started_by"] = "follow_up"
                        run_metadata["superseded_run_id"] = current_project_run["id"]
                        if current_project_run.get("active_proposal_id"):
                            run_metadata["superseded_proposal_id"] = current_project_run["active_proposal_id"]
                    if replan_requested:
                        run_metadata["direction_changed"] = True
                    run = await run_service.create_run(
                        project_id=project_info["id"],
                        room_id=room_id,
                        parent_run_id=current_project_run["id"] if current_project_run else None,
                        metadata=run_metadata or None,
                    )
                    run_id = run["id"]
                    if should_supersede_existing_run and current_project_run:
                        await run_service.supersede_run(current_project_run["id"], run_id)
                        active_proposal_id = current_project_run.get("active_proposal_id")
                        if active_proposal_id:
                            await project_service.supersede_proposal(
                                active_proposal_id,
                                project_info["id"],
                            )
                            await project_service.update_project(
                                project_info["id"],
                                current_user.user_id,
                                status="planning",
                            )
                        await _save_project_event_safe(
                            project_service,
                            project_id=project_info["id"],
                            room_id=room_id,
                            run_id=run_id,
                            event_type="phase",
                            content="previous run superseded by user follow-up",
                        )
                except Exception as run_error:
                    logger.warning(
                        "Failed to create agent run (project=%s, room=%s): %s",
                        project_info.get("id"),
                        room_id,
                        run_error,
                    )
                mark_latency("run_created")

                # 方針変更要求が来たら、現在ステータスに関係なく planning へ戻して再計画
                if replan_requested and project_info.get("status") != "planning":
                    try:
                        updated = await project_service.update_project(
                            project_info["id"],
                            current_user.user_id,
                            status="planning",
                        )
                        if updated:
                            project_info["status"] = updated.get("status", "planning")
                        else:
                            project_info["status"] = "planning"
                        await _save_project_event_safe(project_service,
                            project_id=project_info["id"],
                            room_id=room_id,
                            run_id=run_id,
                            event_type="phase",
                            content="user requested direction change; switched to planning",
                        )
                        yield f"data: {json.dumps({'type': 'process', 'session_id': room_id, 'step': {'id': 'replan-switch', 'label': '方針変更を受け、再計画モードに切り替えました', 'status': 'running'}})}\n\n"
                    except Exception as e:
                        logger.warning(
                            "Failed to switch project to planning for replan "
                            "(project=%s, room=%s): %s",
                            project_info.get("id"),
                            room_id,
                            e,
                        )

                # planning ステータスの場合、origin_room_id から依頼文を取得
                user_messages_for_cli = ""
                if project_info.get("status") == "planning":
                    # 方針変更時は、直近のユーザー依頼を優先して計画に使う
                    if replan_requested and request.content.strip():
                        user_messages_for_cli = request.content
                    try:
                        if not user_messages_for_cli:
                            origin_room_id = project_info.get("origin_room_id", "")
                            if not origin_room_id:
                                # プロジェクトテーブルから origin_room_id を取得
                                proj_full = (
                                    project_service.supabase.table("projects")
                                    .select("origin_room_id")
                                    .eq("id", project_info["id"])
                                    .execute()
                                )
                                if proj_full.data:
                                    origin_room_id = proj_full.data[0].get("origin_room_id", "")
                            if origin_room_id:
                                user_messages_for_cli = _fetch_latest_user_message_from_room(
                                    service, origin_room_id
                                )
                    except Exception:
                        pass

                cli_content = _build_content_with_media(effective_content, request.image_urls or [], request.file_urls or [])
                cli_content, video_analyses = await _enrich_content_with_video_analysis(cli_content, request.file_urls or [])
                if reply_context_prefix:
                    cli_content = reply_context_prefix + cli_content
                mark_latency("content_enriched")

                # ── メディア永続化: CLI起動前に画像/動画をGeminiで抽出・保存 ──
                # system promptに注入されるため、ダンは最初のターンから参照可能
                # video_analysesを渡すことで動画分析の二重実行を防ぐ
                try:
                    await _save_media_artifacts(
                        image_urls=request.image_urls or [],
                        file_urls=request.file_urls or [],
                        message_content=effective_content,
                        room_id=room_id,
                        video_analyses=video_analyses,
                    )
                except Exception as media_err:
                    logger.warning("Media artifact extraction failed (non-blocking): %s", media_err)
                mark_latency("media_artifacts_saved")

                _cli_agen = process_message_cli(
                    room_id=room_id,
                    user_id=current_user.user_id,
                    content=cli_content,
                    project_title=project_info.get("title", ""),
                    project_description=project_info.get("description", ""),
                    project_status=project_info.get("status", "in_progress"),
                    user_messages=user_messages_for_cli,
                    project_id=project_info.get("id"),
                    run_id=run_id,
                    skill_injection=skill_injection,
                    timeline_refs=request.timeline_refs or [],
                )
                if message is None:
                    # 並列保存パス: 先に cold start を起動し（最初の __anext__ でCLIスレッド開始）、
                    # その裏で send_message(~1.27s) を実行して TTFT を短縮する。
                    _gen_first = asyncio.ensure_future(_cli_agen.__anext__())
                    await asyncio.sleep(0)  # CLIスレッド(cold start)を先に走らせてから保存する
                    try:
                        message = await service.send_message(
                            room_id, current_user.user_id, media_content,
                            sender_type="human", reply_to_id=request.reply_to_id,
                            created_at=request_arrival_iso,
                            message_id=request.client_message_id,
                        )
                        _check_cancel_tombstone(room_id, message["id"], service)
                    except Exception:
                        _gen_first.cancel()
                        try:
                            from app.agent.cli_runner import kill_cli_process
                            kill_cli_process(room_id)
                        except Exception:
                            pass
                        raise
                    sender_display_name = message.get("sender_name") or "You"
                    mark_latency("message_saved")
                    # ユーザーメッセージのエコー（最初のAIイベントより前に送出）
                    user_message = {
                        "id": message["id"],
                        "room_id": room_id,
                        "sender_id": message["sender_id"],
                        "sender_name": sender_display_name,
                        "sender_type": message["sender_type"],
                        "content": message["content"],
                        "created_at": message["created_at"].isoformat() if hasattr(message["created_at"], 'isoformat') else str(message["created_at"]),
                    }
                    if request.reply_to_id:
                        user_message["reply_to_id"] = request.reply_to_id
                        if _reply_msg_data:
                            user_message["reply_to_message"] = {
                                "id": _reply_msg_data["id"],
                                "sender_name": _reply_msg_data["sender"]["display_name"] if _reply_msg_data.get("sender") else "Unknown",
                                "sender_type": _reply_msg_data["sender_type"],
                                "content": _reply_msg_data["content"][:200],
                                "created_at": _reply_msg_data["created_at"],
                            }
                    yield f"data: {json.dumps({'type': 'user_message', 'session_id': room_id, 'message': user_message})}\n\n"
                    mark_latency("user_sse_sent")
                    _cli_iter = _prepend_first_event(_gen_first, _cli_agen)
                else:
                    _cli_iter = _cli_agen

                first_cli_event_logged = False
                async for event in _cli_iter:
                    if not first_cli_event_logged:
                        mark_latency(f"first_cli_event:{event.get('type', 'unknown')}")
                        log_latency(room_id)
                        first_cli_event_logged = True
                    if event["type"] == "keepalive":
                        # SSEコメント: クライアントのEventSourceパーサーは無視するが接続は維持される
                        yield ": keepalive\n\n"
                        continue

                    if event["type"] == "cancelled":
                        # Escパリティ: キャンセルされたターンはチャットに何も残さない。
                        # 「（中断されました）」のAIメッセージ保存はゴミ吹き出しの
                        # もう一つの発生源だった（2026-07-24 実測）。UI状態の後始末
                        # （done イベント・run pause・SSE通知）だけ行う。
                        await _save_project_event_safe(project_service,
                            project_id=project_info["id"], room_id=room_id,
                            run_id=run_id,
                            event_type="done", content="cancelled",
                        )
                        if run_id:
                            await run_service.update_run(run_id, state="paused")
                        run_state = "paused"
                        yield f"data: {json.dumps({'type': 'cancelled', 'session_id': room_id})}\n\n"
                        done_sent = True
                        result_saved = True
                        break

                    elif event["type"] == "reasoning":
                        text = event.get("text", "")
                        label = text
                        reasoning_steps.append(label)
                        if text.strip():
                            reasoning_full.append(text)
                        yield f"data: {json.dumps({'type': 'process', 'session_id': room_id, 'step': {'id': f'cli-{step_counter}', 'label': label, 'status': 'running'}})}\n\n"
                        step_counter += 1
                        # DB保存はCLIスレッドが実行済み（DB-first）

                    elif event["type"] == "tool_use":
                        tool_label = _format_tool_label(event.get("name", ""), event.get("input", {}))
                        reasoning_steps.append(f"🔧 {tool_label}")
                        yield f"data: {json.dumps({'type': 'process', 'session_id': room_id, 'step': {'id': f'cli-{step_counter}', 'label': f'🔧 {tool_label}', 'status': 'running'}})}\n\n"
                        step_counter += 1
                        # DB保存はCLIスレッドが実行済み（DB-first）

                        # ファイル書き出しを追跡（CLI完了後のartifact保存用）
                        tool_name = event.get("name", "")
                        tool_input = event.get("input", {})
                        from app.services.chat_artifact_registration import (
                            add_written_path,
                            written_path_from_tool,
                        )
                        add_written_path(
                            written_file_paths,
                            written_path_from_tool(tool_name, tool_input),
                        )

                    elif event["type"] == "text":
                        # textイベントは暫定的に記録（最終回答はresultイベントで確定する）
                        final_text = event["text"]
                        text_preview = event["text"].strip()
                        if text_preview and len(text_preview) > 10:
                            # Use full text preview without truncation.
                            label = text_preview
                            reasoning_steps.append(label)
                            reasoning_full.append(text_preview)
                            yield f"data: {json.dumps({'type': 'process', 'session_id': room_id, 'step': {'id': f'cli-{step_counter}', 'label': label, 'status': 'running'}})}\n\n"
                            step_counter += 1

                    elif event["type"] == "result":
                        result_text = event.get("text", "")
                        cli_saved_ai_message = event.get("cli_saved", False)
                        # 追い連絡で中断されたターン（後続ターンが続く=継続中）。この場合は
                        # done を送らず run も完了扱いにしない → フロントのライブ表示が
                        # ターン境界で一瞬畳まれて再表示される「チラつき」(#1)を防ぐ。
                        # 最後のターンの result（continuation=False）でだけ done を送る。
                        is_continuation = bool(event.get("continuation", False))
                        if run_id and event.get("session_id"):
                            await run_service.attach_claude_session(run_id, event["session_id"])
                        run_state = "failed" if event.get("is_error") else "completed"
                        if result_text:
                            final_text = result_text
                        elif event.get("is_error"):
                            final_text = result_text

                        # resultイベント到着時に即座にai_message+doneを送信
                        # （ループ終了を待つとCLIプロセスの後処理分だけ遅延する）
                        ai_response_content = final_text or "応答を生成できませんでした。もう一度お試しください。"
                        if cli_saved_ai_message:
                            ai_context = {"turn_id": event.get("turn_id")} if event.get("turn_id") else None
                            ai_message = {
                                "id": f"cli-saved-{event.get('turn_id') or 'latest'}",
                                "room_id": room_id,
                                "sender_id": None,
                                "sender_name": "ダン",
                                "sender_type": "ai",
                                "content": ai_response_content,
                                # ストリーミング経路はターン開始時刻を返す（DB行と一致させ、
                                # 追い連絡で割り込まれたターンが時系列で正しく並ぶように）。
                                "created_at": event.get("created_at") or datetime.now(timezone.utc).isoformat(),
                            }
                            if ai_context:
                                ai_message["ai_context"] = ai_context
                            yield f"data: {json.dumps({'type': 'ai_message', 'session_id': room_id, 'message': ai_message})}\n\n"
                        else:
                            ai_message_data = await service.send_dan_ai_message(
                                current_user.user_id, ai_response_content, reasoning_steps,
                                room_id=room_id, reasoning_full=reasoning_full,
                            )
                            if ai_message_data:
                                ai_message = {
                                    "id": ai_message_data["id"],
                                    "room_id": ai_message_data["room_id"],
                                    "sender_id": ai_message_data.get("sender_id"),
                                    "sender_name": "ダン",
                                    "sender_type": "ai",
                                    "content": ai_message_data["content"],
                                    "created_at": ai_message_data["created_at"].isoformat() if hasattr(ai_message_data["created_at"], 'isoformat') else str(ai_message_data["created_at"]),
                                }
                                yield f"data: {json.dumps({'type': 'ai_message', 'session_id': room_id, 'message': ai_message})}\n\n"
                        if is_continuation:
                            # 後続ターンあり。done を送らずライブ表示を維持。run も running のまま。
                            result_saved = True  # この中間ターンの回答は保存済み（DB-first）
                        else:
                            if run_id and run_state:
                                await run_service.update_run(run_id, state=run_state)
                            result_saved = True
                            yield f"data: {json.dumps({'type': 'done', 'session_id': room_id})}\n\n"
                            done_sent = True

                        # Update project's updated_at to bubble it up in sidebar
                        try:
                            from datetime import datetime, timezone
                            project_service.supabase.table("projects").update({
                                "updated_at": datetime.now(timezone.utc).isoformat()
                            }).eq("id", project_info["id"]).execute()
                        except Exception:
                            pass

                    elif event["type"] == "error":
                        if run_id:
                            await run_service.update_run(run_id, state="failed")
                        run_state = "failed"
                        yield f"data: {json.dumps({'type': 'error', 'session_id': room_id, 'message': event['message']})}\n\n"
                        # DB保存はCLIスレッドが実行済み（DB-first）

                # ダンの回答完了 → 観察者を即座にバックグラウンド起動
                if result_saved and run_state != "paused":
                    await _notify_dan_completion(
                        room_id,
                        current_user.user_id,
                        project_info.get("id"),
                        final_text,
                    )
                    _trigger_observer(room_id, current_user.user_id)

                    # ダンが書き出したビジュアル成果物を検知 → Gemini抽出 → 永続保存
                    try:
                        await _register_written_chat_artifacts(
                            written_file_paths,
                            room_id,
                            project_info.get("id"),
                            current_user.user_id,
                            final_text,
                        )
                        if written_file_paths:
                            await _save_written_artifacts(written_file_paths, room_id)
                    except Exception as e:
                        logger.warning("Post-CLI artifact extraction failed (non-blocking): %s", e)

            # NOTE: 全チャットは統一済み。非プロジェクト分岐は削除済み (2026-03-06)
        except Exception as e:
            import logging
            import traceback
            logging.error(f"Failed to stream dan message: {e}\n{traceback.format_exc()}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            # CLI Runner 方式ではプロセスは別スレッドで完結しており、
            # SSE切断時には async for ループが自然に終了して result_saved が
            # 正常パスで設定される。ここでは UI の確実な停止だけ保証する。
            if not result_saved and room_id_for_cancel:
                # SSE切断等で正常パスを通れなかった場合のログ
                logger.info(
                    "[SSE-DISCONNECT] Stream ended without saving result (room=%s)",
                    room_id_for_cancel,
                )

            # done 未送信の場合のみ送信（フロントエンドのスピナー停止保証）
            if not done_sent:
                try:
                    yield f"data: {json.dumps({'type': 'done', 'session_id': room_id_for_cancel or ''})}\n\n"
                except Exception:
                    pass
            # クリーンアップ: リクエストIDとコールバックを解除
            ProgressCallbackRegistry.unregister(request_id)
            set_current_request_id(None)
            # キャンセルフラグを解除（CLIがまだ動いていたらスキップ → cli_runner.pyのfinally任せ）
            if room_id_for_cancel:
                from app.agent.cli_runner import is_cli_active
                if not is_cli_active(room_id_for_cancel):
                    CancellationRegistry.unregister(room_id_for_cancel)
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.post("/dan/read", response_model=ReadMarkResponse)
async def mark_dan_as_read(
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """ダンページを既読にする"""
    try:
        dan_room = await service.get_or_create_dan_room(current_user.user_id)
        success = await service.mark_as_read(dan_room["id"], current_user.user_id)
        return ReadMarkResponse(success=success, read_at=datetime.now(timezone.utc))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Session Routes ====================

@router.get("/dan/sessions", response_model=SessionsListResponse)
async def get_dan_sessions(
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    ダンのセッション一覧を取得
    
    - 全てのセッション（チャット履歴）を返す
    - 現在アクティブなセッションIDも含む
    """
    try:
        result = await service.get_dan_sessions(current_user.user_id)
        # heartbeatセッションを除外
        sessions = [
            s for s in result["sessions"]
            if not s["id"].startswith("heartbeat-")
        ]
        return SessionsListResponse(
            sessions=[SessionResponse(**s) for s in sessions],
            current_session_id=result["current_session_id"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dan/sessions/active-list")
async def list_active_sessions(
    current_user: TokenData = Depends(get_current_user),
):
    """
    全アクティブセッション一覧（ドレインパターン用）

    self-devスキルがデプロイ前に他セッションの実行状態を確認するために使用。
    """
    from app.agent.cli_runner import _active_processes, _process_lock
    with _process_lock:
        active_ids = list(_active_processes.keys())
    return {"active_session_ids": active_ids}


@router.post("/dan/sessions", response_model=SessionCreateResponse)
async def create_dan_session(
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    新しいダンセッションを作成
    
    - 新規セッションを作成し、アクティブに設定
    - 既存のセッションは保持される
    """
    try:
        session = await service.create_dan_session(current_user.user_id)
        return SessionCreateResponse(**session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dan/sessions/{session_id}/activate", response_model=SessionActivateResponse)
async def activate_dan_session(
    session_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    セッションをアクティブにする（切り替え）
    
    - 指定したセッションをアクティブに設定
    - 次回の /dan/messages はこのセッションのメッセージを返す
    """
    try:
        result = await service.activate_dan_session(current_user.user_id, session_id)
        return SessionActivateResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Optimized Session Switch Route ====================

class SessionSwitchResponse(SessionActivateResponse):
    """セッション切り替えレスポンス（メッセージ含む）"""
    room: Optional[DanRoomResponse] = None
    messages: Optional[MessagesListResponse] = None


@router.post("/dan/sessions/{session_id}/switch")
async def switch_dan_session(
    session_id: str,
    limit: int = 50,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    セッションを切り替え、ルーム情報とメッセージを一度に取得（最適化版）
    
    - セッションをアクティブに設定
    - ルーム情報を取得
    - メッセージを取得
    - 1回のAPIコールで全データを返す
    """
    try:
        # セッションをアクティブ化
        result = await service.activate_dan_session(current_user.user_id, session_id)
        
        # ルーム情報を取得
        dan_room = await service.get_or_create_dan_room(current_user.user_id)
        
        # メッセージを取得
        messages = await service.get_messages(dan_room["id"], current_user.user_id, limit=limit)
        
        return {
            "success": result["success"],
            "session_id": result["session_id"],
            "room": dan_room,
            "messages": {"messages": [MessageResponse(**m) for m in messages]},
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/dan/sessions/{session_id}", response_model=SessionResponse)
async def update_dan_session(
    session_id: str,
    request: SessionUpdateRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """セッションのタイトルを更新"""
    try:
        result = await service.update_dan_session_title(
            current_user.user_id, 
            session_id, 
            request.title
        )
        # 完全なセッション情報を返すために再取得
        sessions = await service.get_dan_sessions(current_user.user_id)
        for s in sessions["sessions"]:
            if s["id"] == session_id:
                return SessionResponse(**s)
        return SessionResponse(
            id=result["id"],
            title=result["title"],
            message_count=0,
            created_at=datetime.now(timezone.utc),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/dan/sessions/{session_id}")
async def delete_dan_session(
    session_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    セッションを削除

    - アクティブなセッションを削除した場合、別のセッションに自動切り替え
    - 関連するメッセージも全て削除される
    - 実行中の処理とブラウザ操作もキャンセルされる
    - アーカイブ（LLM要約）はバックグラウンドで実行
    """
    import asyncio

    try:
        # キャンセル処理: 実行中のタスクとブラウザ操作を停止
        from app.services.cancellation import CancellationRegistry
        from app.tools.browser import abort_executor_session

        CancellationRegistry.cancel(session_id)
        abort_executor_session()

        # メッセージをDBから先に取得（高速）してからバックグラウンドでLLM要約
        messages_for_archive = await _collect_messages_for_archive(
            service=service,
            user_id=current_user.user_id,
            room_id=session_id,
        )

        # 即座に削除を実行
        result = await service.delete_dan_session(current_user.user_id, session_id)

        # LLM要約をバックグラウンドで実行（削除完了後）
        if messages_for_archive:
            asyncio.create_task(
                _run_archive_in_background(session_id, messages_for_archive)
            )

        return {
            "message": "Session deleted successfully",
            "new_active_session_id": result.get("new_active_session_id"),
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Cancel Route ====================

@router.get("/dan/sessions/{session_id}/execution-events")
async def get_session_execution_events(
    session_id: str,
    limit: int = 100,
    since_seq: Optional[int] = None,
    current_only: bool = False,
    current_user: TokenData = Depends(get_current_user),
):
    """
    セッション（room_id）の実行イベントを取得。

    since_seq を指定すると、そのseq番号より後のイベントのみ返す。
    current_only=True で最後のdoneイベント以降のみ返す（現在の実行分のみ）。
    フロントエンドのポーリング復帰時に差分取得に使う。
    """
    from app.services.project_service import ProjectService
    service = ProjectService()
    events = await service.get_execution_events_by_room(
        room_id=session_id,
        limit=limit,
        since_seq=since_seq,
        current_only=current_only,
    )
    return events


@router.get("/dan/sessions/{session_id}/active")
async def get_active_session_status(
    session_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    """
    セッションがバックエンドで実行中かどうかを返す。

    フロントエンドがページ読み込み時やタブ復帰時に呼び出し、
    実行中ならポーリングモードに切り替える。
    """
    from app.services.cancellation import CancellationRegistry
    from app.agent.cli_runner import is_cli_active

    info = CancellationRegistry.get_active_info(session_id)
    if info:
        return {
            "active": True,
            "session_id": session_id,
            "started_at": info["started_at"],
        }

    # Registry にないが CLI プロセスがまだ動いている場合
    if is_cli_active(session_id):
        return {
            "active": True,
            "session_id": session_id,
            "started_at": None,
        }

    # 常駐ストリーミングセッション（追い連絡経路）のターン実行中。
    # この経路は CancellationRegistry にも _active_processes にも載らないため、
    # 送信元のSSEが切れる（=チャットを閉じる）と上の2チェックは false になるが、
    # 処理は sink スレッドで続いている。ここを見ないと「開き直すと止まって見える」。
    try:
        from app.agent.streaming_session import streaming_enabled, get_session
        if streaming_enabled():
            _sess = get_session(session_id)
            if _sess is not None and _sess.is_turn_active():
                return {
                    "active": True,
                    "session_id": session_id,
                    "started_at": None,
                }
    except Exception:
        pass

    return {
        "active": False,
        "session_id": session_id,
        "started_at": None,
    }


@router.post("/dan/cancel")
async def cancel_dan_session(
    request: CancelRequest,
    current_user: TokenData = Depends(get_current_user),
):
    """
    実行中のセッションをキャンセル

    - CancellationRegistryにキャンセルフラグをセット
    - ブラウザのコマンドキューをクリア
    - 実行中のツールは次のチェックポイントで停止
    """
    from app.services.cancellation import CancellationRegistry
    from app.tools.browser import abort_executor_session
    from app.agent.cli_runner import kill_cli_process
    from app.services.run_service import RunService

    success = CancellationRegistry.cancel(request.session_id)
    # 「次に始まるターンを殺す予約」は、実際に送信を取り消している場合
    # （取消対象メッセージIDあり）のみ許可。空撃ちキャンセルでの武装は
    # 直後の正当な送信を闇討ちする地雷になる（2026-07-24 実測）。
    cli_killed = kill_cli_process(
        request.session_id,
        allow_arm_pending=bool(request.cancelled_user_message_id),
    )
    paused_runs = await RunService().pause_active_runs_for_room(request.session_id)
    deleted_user_message = False
    if request.cancelled_user_message_id:
        # 完全形: フロント発行のUUIDがそのまま行IDなので、IDで直接削除する。
        # まだ保存されていなければ削除は空振りする——その場合は墓標を残し、
        # 保存完了直後に照合して取り消す（到着順レースの唯一の残り）。
        _mid = request.cancelled_user_message_id
        try:
            # 【順序が本質】墓標を先に武装してから削除する。
            # 逆順（削除→空振り→武装）だと、削除(await)と武装の間の隙間に
            # 保存＋墓標照合が割り込んだ場合、照合時点では未武装なので素通りし、
            # 手遅れの武装だけが残って行が生き残る（2026-07-25 実測レース）。
            # 先に武装しておけば、削除が空振りしても保存直後の照合が必ず拾う。
            # 削除が成功したら墓標は用済みなので取り下げる。
            import time as _t
            _tombstone_prune()
            _cancel_tombstones[(request.session_id, _mid)] = _t.time()
            delete_result = await asyncio.to_thread(
                lambda: ChatService()
                .supabase.table("chat_messages")
                .delete()
                .eq("id", _mid)
                .eq("room_id", request.session_id)
                .eq("sender_id", current_user.user_id)
                .eq("sender_type", "human")
                .execute()
            )
            deleted_user_message = bool(delete_result.data)
            logger.warning(
                "user-cancel delete: room=%s id=%s deleted=%s",
                request.session_id[:8], _mid[:8], deleted_user_message,
            )
            if deleted_user_message:
                # 行を消せた＝墓標は用済み。残すと同じUUIDの再保存（replace系）を
                # 誤って取り消しうるので取り下げる。
                _cancel_tombstones.pop((request.session_id, _mid), None)
                # 一覧サムネの巻き戻し: プレビューは保存時の焼き込みコピーで、
                # 行削除では戻らない（取り消した文言が一覧に残り続ける）。
                # 実際に残っている本当の最新メッセージで書き直す。
                from app.services.chat_service import refresh_room_preview_sync
                await asyncio.to_thread(
                    refresh_room_preview_sync, ChatService().supabase, request.session_id
                )
            # 空振り時は事前武装済みの墓標が保存直後の照合で行を取り消す
        except Exception:
            logger.warning(
                "Failed to delete cancelled user message %s",
                request.cancelled_user_message_id,
                exc_info=True,
            )

    # ブラウザセッションも停止
    abort_executor_session()

    return {
        "success": success or cli_killed or paused_runs > 0 or deleted_user_message,
        "session_id": request.session_id,
        "paused_runs": paused_runs,
        "deleted_user_message": deleted_user_message,
    }


# ==================== Proposal Routes (2G) ====================

@router.get("/proposals", response_model=ProposalsListResponse)
async def get_proposals(
    status: Optional[str] = None,
    limit: int = 50,
    types: Optional[str] = None,
    exclude_types: Optional[str] = None,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    ダンからの提案一覧を取得

    - status: フィルター（pending, approved, rejected, expired）
    - limit: 取得件数（デフォルト50）
    - types: この type のみ（カンマ区切り。例: reply,action）
    - exclude_types: この type を除外（カンマ区切り。例: observation で情報通知を除く）
    """
    try:
        type_list = [t.strip() for t in types.split(",") if t.strip()] if types else None
        exclude_list = [t.strip() for t in exclude_types.split(",") if t.strip()] if exclude_types else None
        proposals = await service.get_proposals(
            current_user.user_id, status=status, limit=limit,
            types=type_list, exclude_types=exclude_list,
        )
        pending_count = await service.get_pending_proposals_count(
            current_user.user_id, exclude_types=exclude_list,
        )
        return ProposalsListResponse(
            proposals=[ProposalResponse(**p) for p in proposals],
            total_count=len(proposals),
            pending_count=pending_count,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """提案の詳細を取得。.htmlファイルはHTMLとして直接サーブ"""
    if proposal_id.endswith(".html"):
        proposals_dir = Path("D:/dan-workspace/proposals")
        html_path = proposals_dir / proposal_id
        if html_path.exists() and html_path.is_file():
            return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
        raise HTTPException(status_code=404, detail="HTML file not found")
    proposal = await service.get_proposal(proposal_id, current_user.user_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return ProposalResponse(**proposal)


@router.post("/proposals/{proposal_id}/respond", response_model=ProposalResponse)
async def respond_to_proposal(
    proposal_id: str,
    request: ProposalActionRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    提案に対応する

    - action: approve（承認）, reject（却下）, edit（編集して承認）
    - edited_content: action=editの場合、編集後の内容
    """
    try:
        proposal = await service.respond_to_proposal(
            proposal_id,
            current_user.user_id,
            request.action,
            request.edited_content,
        )
        return ProposalResponse(**proposal)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class InstructRequest(BaseModel):
    """提案へのユーザー自由指示"""
    instruction: str


@router.post("/proposals/{proposal_id}/instruct")
async def instruct_proposal(
    proposal_id: str,
    request: InstructRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    提案にユーザーが自由な指示を出す。
    - 「もっと丁寧に」「料金表を添えて」等 → 返信案を書き換えて返す(mode=revise)
    - 「○○さんにこの件でメールして」等 → ダンのメインチャットで実行(mode=delegate)
    - 質問 → その場で回答(mode=answer)
    """
    try:
        return await service.instruct_proposal(
            proposal_id, current_user.user_id, request.instruction.strip(),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== WebSocket ====================

class ConnectionManager:
    """WebSocket接続マネージャー"""
    
    def __init__(self):
        # room_id -> {user_id -> WebSocket}
        self.active_connections: dict[str, dict[str, WebSocket]] = {}
    
    def add_connection(self, room_id: str, user_id: str, websocket: WebSocket):
        """WebSocket接続を追加する"""
        if room_id not in self.active_connections:
            self.active_connections[room_id] = {}
        self.active_connections[room_id][user_id] = websocket
    
    def disconnect(self, room_id: str, user_id: str):
        """WebSocket接続を解除する"""
        if room_id in self.active_connections:
            self.active_connections[room_id].pop(user_id, None)
            if not self.active_connections[room_id]:
                del self.active_connections[room_id]
    
    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """特定のWebSocketにメッセージを送信"""
        await websocket.send_json(message)

    def get_connection(self, room_id: str, user_id: str) -> Optional[WebSocket]:
        """指定ユーザーの接続を取得"""
        return self.active_connections.get(room_id, {}).get(user_id)

    def is_connected(self, room_id: str, user_id: str) -> bool:
        """ユーザーが接続中か確認"""
        return self.get_connection(room_id, user_id) is not None
    
    async def broadcast_to_room(self, room_id: str, message: dict, exclude_user_id: str = None):
        """ルーム内の全員にメッセージをブロードキャスト"""
        if room_id in self.active_connections:
            for user_id, connection in self.active_connections[room_id].items():
                if exclude_user_id and user_id == exclude_user_id:
                    continue
                try:
                    await connection.send_json(message)
                except Exception:
                    pass  # 接続が切れている場合は無視


# ==================== 整理オブザーバー（スケジューラー用） ====================

@router.post("/internal/observer-cleanup")
async def run_observer_cleanup(request: Request):
    """整理オブザーバーを実行する内部エンドポイント。localhostからのみ呼び出し可。"""
    # localhostチェック
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Internal only")

    # オーナーのuser_idを取得
    try:
        from app.services.supabase_client import get_supabase_client
        sb = get_supabase_client().client
        result = sb.table("users").select("id").limit(1).execute()
        if not result.data:
            raise HTTPException(status_code=500, detail="No user found")
        user_id = result.data[0]["id"]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    observer_dir = Path(__file__).parent.parent.parent / ".claude"
    checklist_path = observer_dir / "observer_cleanup.md"

    if not checklist_path.exists():
        return {"status": "skipped", "reason": "observer_cleanup.md not found"}

    logger.info("[Observer:整理] Starting scheduled cleanup")
    cleanup_result = await _run_single_observer(
        room_id="__cleanup",
        user_id=user_id,
        observer_name="整理",
        checklist_path=checklist_path,
        conversation_text="",
    )

    # 変更があれば通知
    summary = cleanup_result["summary"]

    def _is_meaningful(text: str) -> bool:
        if not text.strip():
            return False
        skip = ["変更なし", "該当なし", "特になし", "no change", "nothing"]
        return not any(s in text.lower() for s in skip)

    if _is_meaningful(summary):
        try:
            sb.table("dan_proposals").insert({
                "user_id": user_id,
                "type": "observation",
                "title": "観察者: 記録を整理しました",
                "content": f"【整理】{summary}",
                "status": "pending",
            }).execute()
        except Exception as e:
            logger.error(f"[Observer:整理] Failed to create notification: {e}")
        logger.info(f"[Observer:整理] Completed with changes: {summary}")
        return {"status": "completed", "changes": summary, "files": cleanup_result["files"]}
    else:
        logger.info("[Observer:整理] Completed with no changes")
        return {"status": "completed", "changes": None}


# グローバルな接続マネージャー
manager = ConnectionManager()


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocketチャットエンドポイント
    
    接続時: { "type": "auth", "token": "JWT_TOKEN" }
    ルーム参加: { "type": "join", "room_id": "..." }
    メッセージ送信: { "type": "message", "room_id": "...", "content": "..." }
    退出: { "type": "leave", "room_id": "..." }
    """
    user_id = None
    current_room_id = None
    service = None
    
    try:
        # まず接続を受け入れる
        await websocket.accept()
        
        # サービスを初期化
        service = ChatService()
        
        # 認証を待つ
        auth_data = await websocket.receive_json()
        if auth_data.get("type") != "auth" or "token" not in auth_data:
            await websocket.send_json({"type": "error", "message": "Authentication required"})
            await websocket.close()
            return
        
        # トークン検証
        token_data = decode_access_token(auth_data["token"])
        if not token_data:
            await websocket.send_json({"type": "error", "message": "Invalid or expired token"})
            await websocket.close()
            return
        
        user_id = token_data.user_id
        await websocket.send_json({"type": "auth_success", "user_id": user_id})
        
        # メッセージループ
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            
            if msg_type == "join":
                # ルームに参加
                room_id = data.get("room_id")
                if not room_id:
                    await websocket.send_json({"type": "error", "message": "room_id required"})
                    continue
                
                # ルームメンバーか確認
                is_member = await service.is_room_member(room_id, user_id)
                if not is_member:
                    await websocket.send_json({"type": "error", "message": "Not a member of this room"})
                    continue
                
                # 以前のルームから退出
                if current_room_id:
                    manager.disconnect(current_room_id, user_id)
                
                # 新しいルームに参加
                current_room_id = room_id
                manager.add_connection(room_id, user_id, websocket)
                
                await websocket.send_json({"type": "joined", "room_id": room_id})
                
                # 他のメンバーに通知
                await manager.broadcast_to_room(
                    room_id,
                    {"type": "user_joined", "user_id": user_id, "room_id": room_id},
                    exclude_user_id=user_id
                )
            
            elif msg_type == "message":
                # メッセージ送信
                room_id = data.get("room_id") or current_room_id
                content = data.get("content")

                if not room_id or not content:
                    await websocket.send_json({"type": "error", "message": "room_id and content required"})
                    continue

                # メッセージをDBに保存
                try:
                    message = await service.send_message(room_id, user_id, content)

                    # ルーム内の全員にブロードキャスト
                    await manager.broadcast_to_room(
                        room_id,
                        {
                            "type": "new_message",
                            "message": {
                                "id": message["id"],
                                "room_id": message["room_id"],
                                "sender_id": message["sender_id"],
                                "sender_name": message["sender_name"],
                                "sender_type": message["sender_type"],
                                "content": message["content"],
                                "created_at": message["created_at"],
                            }
                        }
                    )
                except ValueError as e:
                    await websocket.send_json({"type": "error", "message": str(e)})
                except Exception as e:
                    await websocket.send_json({"type": "error", "message": f"Server error: {str(e)}"})
            
            elif msg_type == "leave":
                # ルームから退出
                room_id = data.get("room_id") or current_room_id
                if room_id:
                    manager.disconnect(room_id, user_id)
                    await manager.broadcast_to_room(
                        room_id,
                        {"type": "user_left", "user_id": user_id, "room_id": room_id}
                    )
                    if current_room_id == room_id:
                        current_room_id = None
                    await websocket.send_json({"type": "left", "room_id": room_id})
            
            elif msg_type == "ping":
                # キープアライブ
                await websocket.send_json({"type": "pong"})
    
    except WebSocketDisconnect:
        # 接続切断時の処理
        if current_room_id and user_id:
            manager.disconnect(current_room_id, user_id)
            await manager.broadcast_to_room(
                current_room_id,
                {"type": "user_left", "user_id": user_id, "room_id": current_room_id}
            )
    except Exception as e:
        # エラー時の処理
        if current_room_id and user_id:
            manager.disconnect(current_room_id, user_id)
