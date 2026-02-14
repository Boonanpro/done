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

### 進め方（必ずこの順番で思考・実行すること）
1. ユーザーの原文を丁寧に読み、「何を達成したいか」「何が制約か」を正確に把握する
2. 達成手段について仮説を立てる（例:「○○という方法が最適ではないか」）
3. その仮説を検証するためにweb_searchやdeep_researchで調査する
4. 調査結果から仮説が正しいか判断し、正しければ具体化、間違っていれば修正する
5. 結論と実行計画をまとめる

### 出力フォーマット（この構造に厳密に従うこと）

#### 1. 結論（最初にこれを書く。1段落で完結させる）
「何をするか」「その結果どうなるか」「社長がやることは何か」「承認してほしいこと」を1つの段落にまとめる。
例: 「○○を構築します。社長がやることは△△だけです。問題なければ承認をお願いします。」

#### 2. なぜこの提案か（一言）
この方針を選んだ理由を1-2文で簡潔に述べる。

#### 3. 仮説・調査・根拠
以下のストーリーで説明する:
- **最初の仮説**: 「〜ではないか」と考えた
- **調査したこと**: その仮説を検証するために何を調べたか
- **分かったこと**: 調査で判明した事実（数字・出典を含める）
- **結論**: だからこの方針が最適

#### 4. 実行計画
- **実行体制**: どう進めるか（例: まずアカウント開設、次に開発、最後にテスト）
- **実行ステップ**: 番号付きで具体的に
- **社長の使い方**: ユーザーが実際にどう操作するか、ステップバイステップで
- **スケジュール・見積もり**: 各フェーズの所要時間
- **注意点・リスク**: 確認が必要な事項（Red判定のもの等）
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
