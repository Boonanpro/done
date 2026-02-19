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


def _extract_steps(proposal_text: str) -> List[dict]:
    """Markdownの実行計画セクションからステップを抽出（複数フォーマット対応）"""
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
        # テーブル行からステップを抽出: | ステップ番号 | 内容 | 担当 |
        for row in re.finditer(r"\|\s*[\d\-]+\s*\|\s*(.+?)\s*\|", phase_body):
            desc = row.group(1).strip()
            # ヘッダー行やセパレーターをスキップ
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


def _fetch_user_messages(origin_room_id: str, limit: int = 10) -> str:
    """origin_room_idから直近のユーザーメッセージを取得し、テキストとして返す"""
    try:
        from app.services.chat_service import ChatService
        chat_service = ChatService()

        result = (
            chat_service.supabase.table("chat_messages")
            .select("content, sender_type")
            .eq("room_id", origin_room_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

        if not result.data:
            return ""

        # sender_type == "user" のメッセージだけ抽出し、時系列順に並べる
        user_msgs = [
            m["content"]
            for m in reversed(result.data)
            if m.get("sender_type") == "user" and m.get("content")
        ]

        if not user_msgs:
            return ""

        # 最大5件に絞る
        user_msgs = user_msgs[-5:]

        return "\n".join(f"- {msg}" for msg in user_msgs)
    except Exception as e:
        logger.warning(f"[AutoProposal] Failed to fetch user messages: {e}")
        return ""


async def run_project_auto_proposal(
    project_id: str,
    room_id: str,
    user_id: str,
    title: str,
    description: str,
    origin_room_id: Optional[str] = None,
) -> None:
    """
    バックグラウンドでAgent Teamsによる自動提案を生成する。

    asyncio.create_task() で起動される。
    3人のエージェント（リサーチャー、クリティック、リーダー）が
    議論を経て高品質な提案書を作成する。

    フロー:
      1. リサーチャーが調査
      2. クリティックが調査結果を検証
      3. リーダーが統合して最終提案書を作成
    """
    try:
        # SSEレスポンス完了を待つ
        await asyncio.sleep(2)

        _debug(f"Starting team proposal for project {project_id}")
        logger.info(f"[AutoProposal] Starting team proposal for project {project_id}")

        # origin_room_idからユーザーメッセージを取得
        user_messages_text = ""
        if origin_room_id:
            user_messages_text = _fetch_user_messages(origin_room_id)

        from app.services.chat_service import ChatService
        chat_service = ChatService()

        # 開始メッセージを即座に送信
        await chat_service.send_dan_ai_message(
            user_id=user_id,
            content="チームで提案を作成中です。リサーチャーが調査を開始しました...",
            room_id=room_id,
        )
        logger.info(f"[AutoProposal] Sent start message for project {project_id}")

        # ステータス通知コールバック
        async def on_status(message: str):
            await chat_service.send_dan_ai_message(
                user_id=user_id,
                content=message,
                room_id=room_id,
            )

        # TeamCoordinatorでチーム提案を実行
        from app.agent.v2.team import TeamCoordinator

        coordinator = TeamCoordinator(
            project_id=project_id,
            room_id=room_id,
            user_id=user_id,
            title=title,
            description=description or "",
            user_messages=user_messages_text,
            on_status=on_status,
        )

        _debug(f"Running team coordinator for project {project_id}")
        team_result = await coordinator.run()
        proposal_text = team_result.proposal

        _debug(f"Team proposal completed: {len(proposal_text)} chars")

        if not proposal_text:
            logger.warning(f"[AutoProposal] Empty team proposal for project {project_id}")
            await chat_service.send_dan_ai_message(
                user_id=user_id,
                content="提案の生成に失敗しました。プロジェクトチャットで直接指示してください。",
                room_id=room_id,
            )
            return

        _debug(f"Saving chat message ({len(proposal_text)} chars)...")

        # 1. チャットメッセージとして保存
        await chat_service.send_dan_ai_message(
            user_id=user_id,
            content=proposal_text,
            room_id=room_id,
        )
        _debug(f"Chat message saved")

        # 2. proposalテーブルにも保存（チームメタデータ付き）
        try:
            from app.services.project_service import ProjectService
            project_service = ProjectService()
            steps = _extract_steps(proposal_text)
            _debug(f"Extracted {len(steps)} steps, saving proposal...")
            await project_service.create_proposal(
                project_id=project_id,
                content=proposal_text,
                proposal_type="plan",
                steps=steps,
                metadata={
                    "team": team_result.metadata,
                    "research_findings": team_result.research_findings[:5000],
                    "critique": team_result.critique[:5000],
                },
            )
            _debug(f"Proposal saved OK with team metadata")
        except Exception as e:
            _debug(f"PROPOSAL SAVE ERROR: {type(e).__name__}: {e}")
            import traceback
            _debug(traceback.format_exc())
            await chat_service.send_dan_ai_message(
                user_id=user_id,
                content=f"[注意] 提案の保存に問題がありましたが、上記の内容を提案としてご確認ください。",
                room_id=room_id,
            )

        _debug(f"COMPLETED team proposal for project {project_id}")

    except Exception as e:
        _debug(f"EXCEPTION: {type(e).__name__}: {e}")
        import traceback
        _debug(traceback.format_exc())
        logger.exception(f"[AutoProposal] Failed for project {project_id}: {e}")
