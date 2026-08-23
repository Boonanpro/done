"""チャット統合音声モード（V1）のバックエンド。

  POST /api/v1/voicelog/session      — チャット用 gpt-realtime セッションの ephemeral トークン発行
  POST /api/v1/voicelog/{room_id}    — 音声会話の文字起こしを部屋の履歴に保存

音声そのものはブラウザ ↔ OpenAI の WebRTC 直結。ここはトークン発行と
「会話をチャットログに残す」だけを担う。文字起こしを chat_messages に保存する
ことで、ダン（CLI）が後のターンで音声会話を文脈として読める＝部屋が共有記憶になる。

サンドボックス側に置く理由: 反映が sandbox restart だけで済む（コアは不変の原則）。
next.config の rewrites では /api/v1/voicelog/* は既定でサンドボックス(8000)に届く。
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings
from app.services.auth_service import TokenData, decode_access_token
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voicelog", tags=["voice-mode"])

CLIENT_SECRETS_ENDPOINT = "https://api.openai.com/v1/realtime/client_secrets"
REALTIME_MODEL = "gpt-realtime-2.1"
ACCESS_TOKEN_COOKIE = "done_access_token"


def _get_user(request: Request) -> TokenData:
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    td = decode_access_token(token) if token else None
    if not td:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return td


# ---------------------------------------------------------------- session

def _chat_instructions(chat_title: Optional[str]) -> str:
    """チャット統合音声モードの指示文（OpenAI Realtime Prompting Guide の骨格準拠）。

    LP編集面（scratch実験ページ）で実測検証済みの設計を継承:
    - 肯定形中心・禁止ルールの堆積をしない
    - 挨拶には挨拶だけ / 促し尾ひれなし / 軽微な聞き間違いは意図を汲む
    - 過去対話の生引用は注入しない（混同事故の教訓）
    """
    context = f"このセッションは「{chat_title}」というチャットから起動された。" if chat_title else ""
    return f"""# 役割と目的
- あなたは、ユーザーの相棒AI「ダン」の音声モード。会話・相談・調査や作業の依頼を音声で受ける。
- 成功 = ユーザーの用件が正しく片付き、結果が短く伝わること。

# 性格とトーン
- 人柄: 気心の知れた仕事仲間。落ち着いていて頼れる。
- 口調: 自然な話し言葉。丁寧すぎず、砕けすぎず。
- 熱量: 穏やか。感情は控えめ、事実は率直に。
- ペース: ゆったり。1回の発話は1〜3文。
- バリエーション: 同じ言い回しや枕詞を続けて使わず、毎回言い方を変える。
- 挨拶には挨拶だけを返す。用件はユーザーが言うまで待つ。

# 文脈
- {context}この会話の文字起こしはチャットの履歴に残り、開発エージェント（ダン本体）も後から読める。

# ツール
- 調査・実装・ファイル操作・ブラウザ操作などの実作業: delegate_to_dan（このチャットの文脈で開発エージェントが実行する。数分かかる。委譲したら一言伝えて会話を続ける）。
- 進行確認: check_dan_status（「作業続いてる？」と聞かれたら推測せず必ずこれで確認）。
- ユーザーの画面を見る: look_at_screen（「今見えてるこれ」の共有を受けるとき。初回は共有ダイアログが出る）。
- 知識で答えられる質問・相談・雑談は、ツールを使わず自分で答える。
- ツールの結果に案内文が含まれていたら、その内容をそのまま伝える。

# ルール
- 常に日本語で話す。
- 軽微な聞き間違いは意図を汲んで進める。意味が取れないときだけ聞き返す。
- 【確認できた事実だけを「できた」と言う】。見ていないことは「まだ確認していない」と言う。

# 会話の流れ
1. 聞く。雑談・相談・質問はそのまま会話で返す。
2. 実作業の依頼は delegate_to_dan に渡し、一言伝えて待つ（進行は画面に表示される）。
3. 完了通知が来たら、要点を短く報告して、待つ。

# 安全と引き継ぎ
- 公開・削除・送信など取り返しのつきにくい操作の依頼は、委譲する前に内容を口頭で確認する。"""


_CHAT_TOOLS = [
    {
        "type": "function",
        "name": "delegate_to_dan",
        "description": (
            "調査・実装・ファイル操作・ブラウザ操作など実作業を、このチャットの文脈で"
            "開発エージェント（ダン本体）に委譲する。数分かかる。完了すると通知が届く。"
            "会話・相談・知識で答えられる質問には使わない。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "作業指示。ユーザーの依頼を具体的かつ自己完結した形で書く（要約で意図を歪めない）。",
                }
            },
            "required": ["task"],
        },
    },
    {
        "type": "function",
        "name": "check_dan_status",
        "description": "委譲した作業が進行中かどうかと直近の活動を確認する。進行を聞かれたら推測せずこれで確認する。",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "look_at_screen",
        "description": (
            "ユーザーの画面（共有されたタブ/ウィンドウ）をスクリーンショットで見る。"
            "「これ見て」の共有を受けるときに使う。初回はユーザーに共有許可ダイアログが出る。"
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
]


class VoiceSessionRequest(BaseModel):
    chat_title: Optional[str] = None
    effort: str = Field(default="high", pattern="^(minimal|low|medium|high|xhigh)$")


@router.post("/session")
async def create_chat_voice_session(request: Request, body: VoiceSessionRequest):
    _get_user(request)
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY が未設定です")

    session = {
        "type": "realtime",
        "model": REALTIME_MODEL,
        "instructions": _chat_instructions(body.chat_title),
        "audio": {
            "input": {
                "transcription": {"model": "gpt-realtime-whisper", "language": "ja"},
                "noise_reduction": {"type": "near_field"},
                "turn_detection": {"type": "semantic_vad", "eagerness": "low"},
            },
            "output": {"voice": "cedar"},
        },
        "tools": _CHAT_TOOLS,
        "reasoning": {"effort": body.effort},
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            CLIENT_SECRETS_ENDPOINT,
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"session": session},
        )
    if resp.status_code != 200:
        detail = resp.text[:500]
        logger.error("voicelog session mint failed: HTTP %s %s", resp.status_code, detail)
        raise HTTPException(status_code=502, detail=f"セッション発行に失敗 (HTTP {resp.status_code}): {detail}")
    data = resp.json()
    return {"value": data.get("value", ""), "model": REALTIME_MODEL, "expires_at": data.get("expires_at")}


# ------------------------------------------------------------- transcript

class TranscriptRequest(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=8000)


@router.post("/{room_id}")
async def add_voice_transcript(room_id: str, request: Request, body: TranscriptRequest):
    """音声会話の1発話を部屋の履歴に保存する（🎙マーク付き）。

    sender_type は human/ai を使い分けるので、チャットUIでは通常の
    ユーザー/ダンの吹き出しとして時系列に並ぶ。ダン（CLI）は後のターンで
    この履歴を読めるため、音声↔テキストの記憶が部屋単位で繋がる。
    """
    user = _get_user(request)
    sender_type = "human" if body.role == "user" else "ai"
    content = f"🎙 {body.content.strip()}"
    svc = ChatService()
    try:
        message = await svc.send_message(room_id, user.user_id, content, sender_type=sender_type)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {"ok": True, "id": message.get("id")}
