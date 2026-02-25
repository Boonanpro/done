"""
Shared system prompt builder for Gemini text and voice runners.

This file keeps Gemini channels aligned with the same runtime contract template
used by CLI chat, while allowing channel-specific capability limits.
"""

import logging
from datetime import datetime
from typing import Optional

from app.agent.bootstrap_context import get_core_prompt, load_all_bootstrap_files
from app.agent.runtime_contract import render_runtime_contract
from app.agent.v2.tools import SkillRegistry, get_all_skill_tools

logger = logging.getLogger(__name__)


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

### 思考・推論の言語
- 内部の思考・推論（ツール選択の判断等）も**必ずユーザーの言語**で行うこと。
- 日本語で話しかけられた場合、思考も日本語で行う。
- 英語で考えてから翻訳するのではなく、最初から日本語で思考する。

### 禁止事項（厳守）
- [STATE: ...] 等の内部状態を声に出さない。
- ツール名を言わない（「browser_openを実行」ではなく「ページを開きますね」）。
- 同じ内容を繰り返さない。
- 英語の技術用語をそのまま使わない。
- 「スキルを確認します」「検索します」「入力します」等の操作実況をしない。
"""


def _fetch_recent_history(session_id: str, limit: int = 20) -> Optional[str]:
    """Fetch recent chat messages from DB and format as conversation history."""
    try:
        from app.services.supabase_client import get_supabase_client

        supabase = get_supabase_client().client
        result = (
            supabase.table("chat_messages")
            .select("sender_type, content")
            .eq("room_id", session_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

        rows = result.data if result.data else []
        if not rows:
            return None

        rows.reverse()  # chronological order
        lines = [
            "## Recent Conversation History",
            "Use this for continuity with prior turns in the same session.",
            "",
        ]
        for row in rows:
            role = "User" if row.get("sender_type") == "human" else "Dan"
            content = (row.get("content") or "").strip()
            if content:
                lines.append(f"**{role}**: {content}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning("Failed to fetch chat history for prompt: %s", e)
        return None


def _build_datetime_section() -> str:
    now = datetime.now()
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return (
        "## Current Date and Time\n"
        f"- Date: {now.strftime('%Y-%m-%d')} ({weekdays[now.weekday()]})\n"
        f"- Time: {now.strftime('%H:%M')}"
    )


def _build_runtime_contract_section() -> str:
    """
    Build runtime contract for Gemini channels.

    Gemini voice/text sessions do not provide CLI built-in tools directly, so
    we explicitly show that as a channel capability limit.
    """
    mcp_tool_names = sorted(
        {tool.get("name", "") for tool in get_all_skill_tools() if tool.get("name")}
    )
    skill_names = sorted({skill.name for skill in SkillRegistry.list_all()})

    return render_runtime_contract(
        cli_builtin_tools=["(none in Gemini channels)"],
        mcp_tools=mcp_tool_names,
        available_skills=skill_names,
        logger=logger,
    )


def build_system_prompt(
    include_voice_rules: bool = False,
    session_id: str | None = None,
) -> str:
    """Build the complete system prompt for Gemini runners."""
    parts = [
        get_core_prompt(),
        _build_datetime_section(),
        _build_runtime_contract_section(),
    ]

    bootstrap = load_all_bootstrap_files()
    if bootstrap:
        parts.append(bootstrap)

    if session_id:
        history = _fetch_recent_history(session_id)
        if history:
            parts.append(history)

    if include_voice_rules:
        parts.append(VOICE_SYSTEM_RULES)

    return "\n\n---\n\n".join(parts)
