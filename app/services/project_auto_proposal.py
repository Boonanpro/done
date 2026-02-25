"""
Project Auto-Proposal Service

プロジェクト作成直後にバックグラウンドで自動提案を生成する。
asyncio.create_task() で呼ばれる非同期タスク。

Agent Teams方式:
  リサーチャー（調査）→ クリティック（検証）→ リーダー（統合）
  の3段階で高品質な提案書を生成する。
"""

import asyncio
import logging
from typing import Optional
from pathlib import Path

from app.services.proposal_steps import extract_steps

logger = logging.getLogger(__name__)

# デバッグ用ファイルログ
_DEBUG_LOG = Path("D:/done/auto_proposal_debug.log")

def _debug(msg: str):
    """ファイルに直接書き込むデバッグログ"""
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    try:
        with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
            f.flush()
    except Exception:
        pass


def _record_proposal_failure(project_id: str, title: str, error: Exception):
    """提案生成の全体失敗をファイルに記録する"""
    from datetime import datetime
    failures_file = Path("D:/dan-workspace/failures.md")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = (
        f"\n## {timestamp} | auto_proposal | top_level_exception\n"
        f"- プロジェクト: {title}\n"
        f"- project_id: {project_id}\n"
        f"- エラー: {type(error).__name__}: {str(error)[:500]}\n"
    )
    try:
        failures_file.parent.mkdir(parents=True, exist_ok=True)
        with open(failures_file, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass


def _fetch_trigger_message(origin_room_id: str) -> str:
    """origin_room_idからプロジェクト作成のきっかけとなったユーザーの依頼文を取得する"""
    try:
        from app.services.chat_service import ChatService
        chat_service = ChatService()

        result = (
            chat_service.supabase.table("chat_messages")
            .select("content, sender_type")
            .eq("room_id", origin_room_id)
            .eq("sender_type", "user")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

        if not result.data:
            return ""

        return result.data[0].get("content", "")
    except Exception as e:
        logger.warning(f"[AutoProposal] Failed to fetch trigger message: {e}")
        return ""


async def run_project_auto_proposal(
    project_id: str,
    room_id: str,
    user_id: str,
    title: str,
    description: str,
    origin_room_id: Optional[str] = None,
    user_request: str = "",
    triage_lane: str = "",
    execution_profile: str = "",
) -> None:
    """
    バックグラウンドでリーダーCLI直接実行による自動提案を生成する。

    asyncio.create_task() で起動される。
    リーダーがプロジェクトチャットに常駐し、call_researcher / call_critic
    ツールでサブエージェントを呼び出して高品質な提案書を作成する。

    フロー:
      リーダーCLI起動 → リーダーが自律的に researcher/critic を呼ぶ → 提案書作成

    Args:
        user_request: LLMが会話コンテキストから抽出した依頼原文。
                      空の場合は origin_room_id からフォールバック取得。
    """
    try:
        # SSEレスポンス完了を待つ
        await asyncio.sleep(2)

        _debug(f"Starting leader proposal for project {project_id}")
        logger.info(f"[AutoProposal] Starting leader proposal for project {project_id}")

        # 依頼原文: LLMが抽出した user_request を優先、なければ DB フォールバック
        user_messages_text = user_request
        if not user_messages_text and origin_room_id:
            user_messages_text = _fetch_trigger_message(origin_room_id)

        from app.services.chat_service import ChatService
        from app.services.project_service import ProjectService
        chat_service = ChatService()
        project_service = ProjectService()

        # ProcessMonitor用に開始イベントを保存
        try:
            await project_service.save_execution_event(
                project_id=project_id,
                room_id=room_id,
                event_type="phase",
                content="リーダーがチームを使って提案書を作成中です...",
                metadata={"member": "leader"},
            )
        except Exception:
            pass

        # CancellationRegistryに登録（停止ボタンで終了できるように）
        from app.services.cancellation import CancellationRegistry
        CancellationRegistry.register(room_id)

        # リーダーCLI直接実行
        from app.agent.cli_runner import process_message_cli
        from app.api.project_routes import _format_tool_label, _summarize_reasoning

        triage_info = ""
        if triage_lane or execution_profile:
            triage_info = (
                f"\n## ルーティング情報\n"
                f"- triage_lane: {triage_lane or '(none)'}\n"
                f"- execution_profile: {execution_profile or '(default)'}\n"
            )

        if triage_lane == "C":
            lane_instruction = (
                "この案件は lane C（詳細調査）です。"
                "必ず最新情報を調査し、AIで実行可能な範囲を根拠付きで評価してください。"
            )
        elif triage_lane in ("A1", "B"):
            lane_instruction = (
                "この案件は実装優先です。"
                "過剰な市場調査は避け、必要最小限の検証で実行可能な計画を作成してください。"
            )
        else:
            lane_instruction = "必要に応じて調査と検証を行い、実行可能な提案書を作成してください。"

        # リーダーへの最初のメッセージ
        first_message = f"""以下のプロジェクトについて、チームを使って提案書を作成してください。

## プロジェクト
- タイトル: {title}
- 説明: {description or "(なし)"}

{f"## ユーザーの依頼文{chr(10)}{user_messages_text}" if user_messages_text else ""}
{triage_info}

## 指示
1. {lane_instruction}
2. 必要な場合は call_researcher で調査してください
3. 必要な場合は call_critic で検証してください
4. 最終提案書を作成してください（提案書フォーマットに従うこと）"""

        _debug(f"Running leader CLI for project {project_id}")

        text_parts = []
        final_text = ""
        was_cancelled = False

        try:
            async for event in process_message_cli(
                room_id=room_id,
                user_id=user_id,
                content=first_message,
                project_title=title,
                project_description=description or "",
                project_status="planning",
                user_messages=user_messages_text,
            ):
                etype = event.get("type", "")

                if etype == "cancelled":
                    was_cancelled = True
                    _debug(f"Leader proposal cancelled for project {project_id}")
                    await chat_service.send_dan_ai_message(
                        user_id=user_id,
                        content="（提案の生成が中断されました）",
                        room_id=room_id,
                    )
                    await project_service.save_execution_event(
                        project_id=project_id, room_id=room_id,
                        event_type="done", content="cancelled",
                    )
                    return

                elif etype == "reasoning":
                    text = event.get("text", "")
                    if text.strip():
                        try:
                            summary = _summarize_reasoning(text)
                            await project_service.save_execution_event(
                                project_id=project_id,
                                room_id=room_id,
                                event_type="reasoning",
                                content=summary or text[:200],
                                metadata={"member": "leader"},
                            )
                        except Exception:
                            pass

                elif etype == "tool_use":
                    tool_label = _format_tool_label(event.get("name", ""), event.get("input", {}))
                    try:
                        await project_service.save_execution_event(
                            project_id=project_id,
                            room_id=room_id,
                            event_type="tool_use",
                            tool_name=event.get("name", ""),
                            tool_label=f"[リーダー] {tool_label}",
                            metadata={"member": "leader"},
                        )
                    except Exception:
                        pass

                elif etype == "text":
                    text = event.get("text", "")
                    if text.strip():
                        text_parts.append(text)

                elif etype == "result":
                    result_text = event.get("text", "")
                    if result_text:
                        final_text = result_text
                    elif event.get("is_error"):
                        final_text = result_text

                elif etype == "error":
                    _debug(f"Leader error: {event.get('message', '')[:200]}")
                    try:
                        await project_service.save_execution_event(
                            project_id=project_id,
                            room_id=room_id,
                            event_type="error",
                            content=event.get("message", "")[:500],
                            metadata={"member": "leader"},
                        )
                    except Exception:
                        pass
        finally:
            CancellationRegistry.unregister(room_id)

        if was_cancelled:
            return

        # 最終テキスト（result 優先、なければ text_parts 結合）
        proposal_text = final_text or "\n".join(text_parts)

        _debug(f"Leader proposal completed: {len(proposal_text)} chars")

        if not proposal_text:
            logger.warning(f"[AutoProposal] Empty leader proposal for project {project_id}")
            await chat_service.send_dan_ai_message(
                user_id=user_id,
                content="提案の生成に失敗しました。プロジェクトチャットで直接指示してください。",
                room_id=room_id,
            )
            return

        _debug(f"Saving chat message ({len(proposal_text)} chars)...")

        # 1. チャットメッセージとして保存（提案書のみ）
        await chat_service.send_dan_ai_message(
            user_id=user_id,
            content=proposal_text,
            room_id=room_id,
        )
        _debug(f"Chat message saved")

        # 2. proposalテーブルにも保存
        try:
            steps = extract_steps(proposal_text)
            _debug(f"Extracted {len(steps)} steps, saving proposal...")
            await project_service.create_proposal(
                project_id=project_id,
                content=proposal_text,
                proposal_type="plan",
                steps=steps,
                metadata={
                    "team_type": "leader_resident",
                },
            )
            _debug(f"Proposal saved OK")
        except Exception as e:
            _debug(f"PROPOSAL SAVE ERROR: {type(e).__name__}: {e}")
            import traceback
            _debug(traceback.format_exc())
            await chat_service.send_dan_ai_message(
                user_id=user_id,
                content=f"[注意] 提案の保存に問題がありましたが、上記の内容を提案としてご確認ください。",
                room_id=room_id,
            )

        # done イベント保存
        try:
            await project_service.save_execution_event(
                project_id=project_id,
                room_id=room_id,
                event_type="done",
                content="completed",
            )
        except Exception:
            pass

        _debug(f"COMPLETED leader proposal for project {project_id}")

    except Exception as e:
        _debug(f"EXCEPTION: {type(e).__name__}: {e}")
        import traceback
        _debug(traceback.format_exc())
        logger.exception(f"[AutoProposal] Failed for project {project_id}: {e}")

        # 失敗をファイルに記録
        _record_proposal_failure(project_id, title, e)

        # ユーザーに通知
        try:
            from app.services.chat_service import ChatService
            cs = ChatService()
            await cs.send_dan_ai_message(
                user_id=user_id,
                content="提案の生成中にエラーが発生しました。再度お試しください。",
                room_id=room_id,
            )
        except Exception:
            pass
