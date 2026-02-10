"""
Shared system prompt builder for Gemini text and voice runners.

Consolidates the duplicated prompt construction logic from:
- app/agent/v2/runner.py (AgentRunner._build_system_prompt)
- app/agent/gemini/live_runner.py (GeminiLiveRunner._build_system_prompt)
"""

import logging
from datetime import datetime
from typing import Optional

from app.agent.v2.tools import get_all_skill_tools, SkillRegistry
from app.agent.v2.runner import get_core_prompt, load_all_bootstrap_files

logger = logging.getLogger(__name__)

def _fetch_recent_history(session_id: str, limit: int = 20) -> Optional[str]:
    """Fetch recent chat messages from DB and format as conversation history.

    This enables voice sessions to pick up context from prior text conversations.
    """
    try:
        from app.services.supabase_client import get_supabase_client
        supabase = get_supabase_client().client

        result = supabase.table("chat_messages") \
            .select("sender_type, content") \
            .eq("room_id", session_id) \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()

        rows = result.data if result.data else []
        if not rows:
            return None

        # Reverse to chronological order
        rows.reverse()

        lines = ["## 直近の会話履歴", "以下はこのセッションの直近の会話です。文脈を引き継いでください。", ""]
        for row in rows:
            role = "ユーザー" if row["sender_type"] == "human" else "ダン"
            content = (row.get("content") or "").strip()
            if content:
                lines.append(f"**{role}**: {content}")

        return "\n".join(lines)
    except Exception as e:
        logger.warning("Failed to fetch chat history for prompt: %s", e)
        return None


VOICE_SYSTEM_RULES = """
## 音声会話ルール

### 基本
- 応答は簡潔に。自然な会話調で話す。
- ユーザーの言語に合わせる（日本語で話しかけられたら日本語で返す）。

### ツール実行時（最重要ルール）
- ユーザーから依頼を受けたら、**一言だけ**返事してすぐツールを実行する。
  - 良い例: 「わかりました、調べますね」「探してみます」
  - 悪い例: 「Amazonのスキルを確認します」「検索バーに入力します」「結果を見てみます」
- **ツール実行中は一切喋らない。** 途中経過をいちいち声に出さないこと。
- 全ての作業が完了してから、結果だけをまとめて報告する。
- ツール名、パラメータ、内部処理の説明は絶対にしない。
- 何回ツールを呼んでも、声を出すのは「最初の一言」と「最後の結果報告」だけ。

### 結果報告
- 結果は要点だけ簡潔に伝える。HTMLやURLは読み上げない。
- 長い結果は要約する。「詳しく聞きたいですか？」と聞く。

### 確認が必要な操作
- 購入・予約・支払い等の前は必ず確認を取る。

### 禁止事項（厳守）
- [STATE: ...] 等の内部状態を声に出さない。
- ツール名を言わない（「browser_openを実行」ではなく「ページを開きますね」）。
- 同じ内容を繰り返さない。
- 英語の技術用語をそのまま使わない。
- 「スキルを確認します」「検索します」「入力します」等の操作実況をしない。
"""


def build_system_prompt(include_voice_rules: bool = False, session_id: str | None = None) -> str:
    """Build the complete system prompt.

    Args:
        include_voice_rules: If True, append voice conversation rules at the end.
        session_id: If provided, inject recent chat history from DB for context continuity.

    Returns:
        Complete system prompt string.
    """
    parts = []

    # 1. Core prompt
    parts.append(get_core_prompt())

    # 2. Current datetime
    now = datetime.now()
    weekdays = ['月', '火', '水', '木', '金', '土', '日']
    parts.append(f"""## 現在の日時
- 今日: {now.strftime('%Y年%m月%d日')}（{weekdays[now.weekday()]}曜日）
- 現在時刻: {now.strftime('%H:%M')}""")

    # 3. Available tools list
    tools = get_all_skill_tools()
    tool_lines = ["## 利用可能なツール"]
    for tool in tools:
        name = tool.get("name", "")
        desc = tool.get("description", "").split("\n")[0]
        tool_lines.append(f"- `{name}`: {desc}")
    tool_lines.append("- `google_search`: Web検索（自動実行）")
    parts.append("\n".join(tool_lines))

    # 4. Available skills list
    skills = SkillRegistry.list_all()
    if skills:
        skill_lines = ["## 利用可能なスキル", ""]
        for skill in skills:
            skill_lines.append(f"- `{skill.name}`: {skill.description}")
        skill_lines.append("")
        skill_lines.append("### スキル使用ルール（必須）")
        skill_lines.append("")
        skill_lines.append(
            "1. ユーザーの依頼が上記スキルに該当する場合、**必ず最初に `check_skill` ツールで手順書を取得すること**。"
            "手順書なしで自己流で操作してはいけない。"
        )
        skill_lines.append(
            "2. 手順書を取得したら、その手順に従って `browser_open`/`browser_click`/`browser_type` 等で操作する。"
        )
        skill_lines.append(
            "3. 該当するスキルがない場合は、自分の判断でブラウザ操作して構わない。"
        )
        parts.append("\n".join(skill_lines))

    # 5. Bootstrap files (USER → MEMORY → daily → SOUL → RULES)
    bootstrap = load_all_bootstrap_files()
    if bootstrap:
        parts.append(bootstrap)

    # 6. Recent conversation history from DB (for cross-channel context)
    if session_id:
        history = _fetch_recent_history(session_id)
        if history:
            parts.append(history)

    # 7. Voice-specific rules (last for recency bias)
    if include_voice_rules:
        parts.append(VOICE_SYSTEM_RULES)

    return "\n\n---\n\n".join(parts)
