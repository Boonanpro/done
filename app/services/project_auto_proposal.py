"""
Project Auto-Proposal Service

プロジェクト作成直後にバックグラウンドで自動提案を生成する。
asyncio.create_task() で呼ばれる非同期タスク。
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
    with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
        f.flush()

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
- **実行ステップ**: どう進めるかを番号付きで具体的に
- **社長の使い方**: ユーザーが実際にどう操作するか、ステップバイステップで
- **スケジュール・見積もり**: 各フェーズの所要時間
- **注意点・リスク**: 確認が必要な事項（Red判定のもの等）
"""


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
    バックグラウンドで自動提案を生成する。

    asyncio.create_task() で起動される。
    SSEレスポンス完了を待ってからrunnerを起動し、
    結果をチャットメッセージ + proposalテーブルに保存する。
    """
    try:
        # SSEレスポンス完了を待つ
        await asyncio.sleep(2)

        _debug(f"Starting for project {project_id}")
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

        # CLI Runner（定額）で提案を生成
        from app.agent.cli_runner import process_message_cli
        from app.services.chat_service import ChatService

        prompt = AUTO_PROPOSAL_PROMPT.format(
            title=title,
            description=description or "(説明なし)",
            user_messages_section=user_messages_section,
        )

        chat_service = ChatService()
        proposal_text = ""

        # 開始メッセージを即座に送信
        await chat_service.send_dan_ai_message(
            user_id=user_id,
            content=f"提案を作成中です。調査・分析を行っています...",
            room_id=room_id,
        )
        logger.info(f"[AutoProposal] Sent start message for project {project_id}")

        event_count = 0
        _debug(f"Starting CLI loop for project {project_id}")
        async for event in process_message_cli(
            room_id=room_id,
            user_id=user_id,
            content=prompt,
            project_title=title,
            project_description=description or "",
            project_status="planning",
        ):
            event_count += 1
            etype = event["type"]
            if etype == "text":
                proposal_text = event["text"]
                _debug(f"TEXT event: {len(proposal_text)} chars")
            elif etype == "tool_use":
                tool_name = event.get("name", "")
                _debug(f"TOOL_USE: {tool_name}")
                # ツール実行メッセージは個別送信しない（チャットが汚れるため）
            elif etype == "text_delta":
                pass
            elif etype == "result":
                proposal_text = event.get("text", proposal_text)
                _debug(f"RESULT: cost={event.get('cost')}, turns={event.get('turns')}, error={event.get('is_error')}, text_len={len(proposal_text)}")
            elif etype == "error":
                _debug(f"ERROR: {event['message'][:500]}")
                await chat_service.send_dan_ai_message(
                    user_id=user_id,
                    content=f"提案生成中にエラーが発生しました。プロジェクトチャットで直接指示してください。",
                    room_id=room_id,
                )
                return

        _debug(f"SDK loop ended. events={event_count}, text_len={len(proposal_text)}")

        if not proposal_text:
            logger.warning(f"[AutoProposal] Empty response for project {project_id}")
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

        # 2. proposalテーブルにも保存
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

        _debug(f"COMPLETED for project {project_id}")

    except Exception as e:
        _debug(f"EXCEPTION: {type(e).__name__}: {e}")
        import traceback
        _debug(traceback.format_exc())
        logger.exception(f"[AutoProposal] Failed for project {project_id}: {e}")
