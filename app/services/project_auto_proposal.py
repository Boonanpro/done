"""
Project Auto-Proposal Service

プロジェクト作成直後にバックグラウンドで自動提案を生成する。
asyncio.create_task() で呼ばれる非同期タスク。

Agent Teams方式:
  リサーチャー（調査）→ クリティック（検証）→ リーダー（統合）
  の3段階で高品質な提案書を生成する。
"""

import re
import asyncio
import logging
from typing import Optional, List
from pathlib import Path

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


def _extract_steps(proposal_text: str) -> List[dict]:
    """
    Markdownの実行計画セクションからステップを抽出。

    抽出順序:
      1. Regex（3パターンフォールバック）
      2. Regex全滅 → LLM（Haiku）で構造化抽出
    """
    steps = _extract_steps_regex(proposal_text)
    if steps:
        return steps

    # Regex全滅 → LLMフォールバック
    logger.warning("[AutoProposal] Regex step extraction failed, trying LLM fallback")
    return _extract_steps_llm(proposal_text)


def _extract_steps_regex(proposal_text: str) -> List[dict]:
    """Regexベースのステップ抽出（3パターンフォールバック）"""
    steps = []
    step_num = 0

    # パターン1: 「実行計画」セクション内の番号リスト
    plan_match = re.search(
        r"#+\s*実行計画\s*\n(.*?)(?=\n#+\s|\Z)",
        proposal_text,
        re.DOTALL,
    )
    if plan_match:
        plan_section = plan_match.group(1)
        for match in re.finditer(r"(\d+)\.\s+(.+)", plan_section):
            step_num += 1
            steps.append({
                "step_number": step_num,
                "description": match.group(2).strip(),
                "status": "pending",
            })
        if steps:
            return steps

    # パターン2: フェーズ見出し(### フェーズN: ...) + テーブル行(| N-M | 内容 | ...)
    phase_matches = re.finditer(
        r"#+\s*フェーズ\s*\d+[：:]\s*(.+?)(?:\s*[（(].+?[）)])?\s*\n(.*?)(?=\n#+\s*フェーズ|\n#+\s*[^#]|\Z)",
        proposal_text,
        re.DOTALL,
    )
    for phase_match in phase_matches:
        phase_name = phase_match.group(1).strip()
        phase_body = phase_match.group(2)
        for row in re.finditer(r"\|\s*[\d\-]+\s*\|\s*(.+?)\s*\|", phase_body):
            desc = row.group(1).strip()
            if desc.startswith('-') or desc in ('内容', 'ステップ', '説明'):
                continue
            step_num += 1
            steps.append({
                "step_number": step_num,
                "description": f"{phase_name}: {desc}",
                "status": "pending",
            })
    if steps:
        return steps

    # パターン3: 番号付きリスト（セクション見出しなし、テキスト全体から）
    for match in re.finditer(r"^(\d+)\.\s+(.+)", proposal_text, re.MULTILINE):
        step_num += 1
        steps.append({
            "step_number": step_num,
            "description": match.group(2).strip(),
            "status": "pending",
        })

    return steps


def _extract_steps_llm(proposal_text: str) -> List[dict]:
    """LLM（Haiku）でステップを構造化抽出する（Regexフォールバック）"""
    import json
    try:
        import anthropic
        from app.config import settings

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": f"""以下の提案書から実行ステップを抽出してJSON配列で返してください。

提案書:
{proposal_text[:4000]}

出力形式（これだけを返すこと。説明は不要）:
[
  {{"step_number": 1, "description": "ステップの内容"}},
  {{"step_number": 2, "description": "ステップの内容"}}
]""",
            }],
        )

        raw = response.content[0].text.strip()
        # JSON部分を抽出（```json ... ``` で囲まれている可能性）
        json_match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not json_match:
            logger.warning(f"[AutoProposal] LLM step extraction: no JSON array found")
            return []

        parsed = json.loads(json_match.group())
        steps = []
        for i, item in enumerate(parsed, 1):
            desc = item.get("description", "").strip()
            if desc:
                steps.append({
                    "step_number": i,
                    "description": desc,
                    "status": "pending",
                })

        logger.info(f"[AutoProposal] LLM extracted {len(steps)} steps")
        return steps

    except Exception as e:
        logger.warning(f"[AutoProposal] LLM step extraction failed: {e}")
        return []


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

        # リーダーCLI直接実行
        from app.agent.cli_runner import process_message_cli
        from app.api.project_routes import _format_tool_label, _summarize_reasoning

        # リーダーへの最初のメッセージ
        first_message = f"""以下のプロジェクトについて、チームを使って提案書を作成してください。

## プロジェクト
- タイトル: {title}
- 説明: {description or "(なし)"}

{f"## ユーザーの依頼文{chr(10)}{user_messages_text}" if user_messages_text else ""}

## 指示
1. まず call_researcher で調査を依頼してください
2. 調査結果を call_critic で検証してください
3. 必要に応じて追加調査を行ってください
4. 最終提案書を作成してください（提案書フォーマットに従うこと）"""

        _debug(f"Running leader CLI for project {project_id}")

        text_parts = []
        final_text = ""

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

            if etype == "reasoning":
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
            steps = _extract_steps(proposal_text)
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
