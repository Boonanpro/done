"""
Project Auto-Proposal Service

プロジェクト作成直後にバックグラウンドで自動提案を生成する。
asyncio.create_task() で呼ばれる非同期タスク。
"""

import re
import asyncio
import logging
from typing import Optional, List

logger = logging.getLogger(__name__)

# 自動提案プロンプト（構造化ブリーフ形式）
AUTO_PROPOSAL_PROMPT = """[Auto-Proposal] プロジェクトが作成されました。

## 依頼内容（概要）
- タイトル: {title}
- 説明: {description}

{user_messages_section}

## あなたのタスク
このプロジェクトの最初の提案（計画）を作成してください。

### 進め方
1. ユーザーの原文を丁寧に読み、要望・制約・好みを正確に把握する
2. 不明点は仮説で埋める（質問せず最善の推測で進める）
3. 必要に応じてweb_searchやdeep_researchで調査する（必要と判断した場合のみ）
4. 調査結果と仮説を元に、具体的な実行計画を作成する

### 出力フォーマット
#### ユーザーの要望
（原文から読み取れる具体的な要望をリスト化）

#### 制約・好み
（原文から読み取れる制約や好みをリスト化）

#### 調査結果（調査した場合のみ）

#### 実行計画

#### 見積もり・注意点
"""


def _extract_steps(proposal_text: str) -> List[dict]:
    """Markdownの実行計画セクションから番号付きステップを抽出"""
    steps = []

    # 実行計画セクションを探す
    plan_match = re.search(
        r"#+\s*実行計画\s*\n(.*?)(?=\n#+\s|\Z)",
        proposal_text,
        re.DOTALL,
    )
    if not plan_match:
        return steps

    plan_section = plan_match.group(1)

    # 番号付きリストを抽出
    for match in re.finditer(r"(\d+)\.\s+(.+)", plan_section):
        steps.append({
            "step_number": int(match.group(1)),
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
    バックグラウンドで自動提案を生成する。

    asyncio.create_task() で起動される。
    SSEレスポンス完了を待ってからrunnerを起動し、
    結果をチャットメッセージ + proposalテーブルに保存する。
    """
    try:
        # SSEレスポンス完了を待つ
        await asyncio.sleep(2)

        logger.info(f"[AutoProposal] Starting for project {project_id}")

        # origin_room_idからユーザーメッセージを取得
        user_messages_text = ""
        if origin_room_id:
            user_messages_text = _fetch_user_messages(origin_room_id)

        if user_messages_text:
            user_messages_section = (
                f"## ユーザーからのメッセージ（原文）\n{user_messages_text}"
            )
        else:
            user_messages_section = ""

        # Runnerを作成してプロンプトを送信
        from app.agent.v2.runner import create_runner

        runner = await create_runner(
            session_id=room_id,
            user_id=user_id,
        )

        prompt = AUTO_PROPOSAL_PROMPT.format(
            title=title,
            description=description or "(説明なし)",
            user_messages_section=user_messages_section,
        )

        result = await runner.process_message(prompt)
        proposal_text = result.get("response", "")

        if not proposal_text:
            logger.warning(f"[AutoProposal] Empty response for project {project_id}")
            return

        logger.info(
            f"[AutoProposal] Got response for project {project_id}: "
            f"{len(proposal_text)} chars"
        )

        # 1. チャットメッセージとして保存
        from app.services.chat_service import ChatService
        chat_service = ChatService()
        await chat_service.send_dan_ai_message(
            user_id=user_id,
            content=proposal_text,
            room_id=room_id,
        )

        # 2. proposalテーブルにも保存
        from app.services.project_service import ProjectService
        project_service = ProjectService()
        steps = _extract_steps(proposal_text)
        await project_service.create_proposal(
            project_id=project_id,
            content=proposal_text,
            proposal_type="plan",
            steps=steps,
        )

        logger.info(
            f"[AutoProposal] Completed for project {project_id} "
            f"({len(steps)} steps extracted)"
        )

    except Exception as e:
        logger.exception(f"[AutoProposal] Failed for project {project_id}: {e}")
        # バックグラウンドタスクの失敗はログのみ。ユーザーはチャットで手動対話可能。
