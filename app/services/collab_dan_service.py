"""
Collab DAN Assist Service
Lightweight AI assist for collab rooms. Tries Anthropic first, falls back to Gemini.
"""
import logging
import re
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """あなたはDANというAIアシスタントです。コラボルーム内でオーナー（本田）をサポートします。
あなたの応答はオーナーだけに見えます。ゲストには見えません。

## 役割
- ゲストからの質問・依頼・フィードバックを分析し、オーナーが取るべきアクションを提案する
- ルームのコンテキスト（タイトル・説明・案件内容）を踏まえた具体的なアドバイスをする

## 応答ルール
- 日本語で回答する
- 簡潔に（3行以内を目安）
- 「〜してみてはいかがでしょうか」のような曖昧な提案ではなく、具体的なアクションを示す
- 返信案は生成しない（ユーザーが手動で生成する機能がある）
- カレンダー・資料管理・タスク管理など作業系の提案のみ行う

## 重要: 反応すべきでないメッセージ
以下のようなメッセージには「SKIP」とだけ返してください。分析やアドバイスは不要です:
- 挨拶（おはよう、こんにちは、お疲れ様）
- 相槌・短い返事（了解、OK、ありがとう、おっけー、はい、うん、なるほど）
- オーナー自身の発言に対するゲストの肯定（わかった、りょ）
- 会話の流れ上、オーナーが何もアクションを取る必要がないメッセージ"""

# 短すぎるメッセージや明らかな相槌をスキップ
SKIP_PATTERNS = re.compile(
    r'^(了解|ok|おk|りょ|はい|うん|ありがと|おけ|おっけ|わかった|なるほど|あ[、。]|よし|お疲れ|おはよう|こんにちは|こんばんは|おやすみ|まじ[？?]?|草|www|笑)[\s。！!？?w]*$',
    re.IGNORECASE
)


def _should_skip(content: str) -> bool:
    """Quick filter: skip messages that clearly don't need DAN assist."""
    stripped = content.strip()
    if len(stripped) <= 4 and not any(c in stripped for c in '？?'):
        return True
    if SKIP_PATTERNS.match(stripped):
        return True
    return False


def _build_prompt(room_title, room_description, recent_messages, trigger_message, owner_name):
    context = f"ルーム: {room_title}"
    if room_description:
        context += f"\n案件概要: {room_description}"

    # Build history with clear role labels
    history_text = ""
    for msg in recent_messages[-10:]:
        sender_type = msg.get("sender_type", "?")
        sender_name = msg.get("sender_name", "?")
        content = msg.get("content", "")
        if sender_type == "owner":
            role_label = f"【オーナー: {sender_name}】"
        elif sender_type == "guest":
            role_label = f"【ゲスト: {sender_name}】"
        elif sender_type.startswith("dan_"):
            continue  # DAN自身の発言は含めない
        else:
            role_label = f"【{sender_name}】"
        history_text += f"{role_label} {content}\n"

    trigger_name = trigger_message.get("sender_name", "?")
    trigger_content = trigger_message.get("content", "")

    return f"""{context}
オーナー名: {owner_name}

会話履歴（【オーナー】は本田、【ゲスト】は相手方です）:
{history_text}

ゲスト（{trigger_name}）の新しいメッセージ:
「{trigger_content}」

このメッセージに対して、オーナーが取るべきアクション（カレンダー・資料管理・タスクなど作業系）を提案してください。
返信案は不要です（ユーザーが手動で生成します）。
反応不要なメッセージの場合は「SKIP」とだけ返してください。"""


def _try_anthropic(system: str, user_prompt: str) -> Optional[str]:
    if not settings.ANTHROPIC_API_KEY:
        return None
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text if response.content else None
    except Exception as e:
        logger.warning("Anthropic failed: %s", e)
        return None


def _try_gemini(system: str, user_prompt: str) -> Optional[str]:
    if not settings.GOOGLE_GEMINI_API_KEY:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=settings.GOOGLE_GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(
            f"{system}\n\n{user_prompt}",
            generation_config=genai.GenerationConfig(max_output_tokens=300),
        )
        return response.text if response.text else None
    except Exception as e:
        logger.warning("Gemini failed: %s", e)
        return None


def get_dan_response(
    room_title: str,
    room_description: Optional[str],
    recent_messages: list[dict],
    trigger_message: dict,
    owner_name: str = "オーナー",
    system_override: Optional[str] = None,
) -> Optional[str]:
    """Generate a DAN assist response. Returns None if no response needed."""
    content = trigger_message.get("content", "").strip()

    # Quick skip filter (skip for auto-assist, not for direct @ダン calls)
    if not system_override and _should_skip(content):
        return None

    system = system_override or SYSTEM_PROMPT
    if system_override:
        # system_override already contains the full prompt with context
        user_prompt = "上記の指示に従って回答してください。"
    else:
        user_prompt = _build_prompt(
            room_title, room_description, recent_messages, trigger_message, owner_name
        )

    # Try Anthropic first, then Gemini
    result = _try_anthropic(system, user_prompt)
    if not result:
        result = _try_gemini(system, user_prompt)

    if not result:
        logger.error("All LLM providers failed for DAN assist")
        return None

    # LLM decided to skip
    if result.strip().upper() == "SKIP":
        return None

    return result
