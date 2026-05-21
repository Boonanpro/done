"""OpenAI Realtime API（gpt-realtime-2）音声レイヤーのサービス層。

音声会話レイヤーの責務:
  - ephemeral クライアントシークレットの発行（API キーをブラウザに出さない）
  - gpt-realtime-2 のセッション設定（指示文・音声・delegate_to_dan ツール）

役割分担:
  - 音声 AI（gpt-realtime-2）= 司会・聞き取り・口頭返答。speech-to-speech 用の
    低レイテンシモデルで、深い推論は得意ではない（おおむね GPT-4 クラス相当）。
  - 実作業 / 深い推論 = delegate_to_dan で Claude Code CLI（Opus/Sonnet）に委譲。
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# 2026-05-07 リリースの OpenAI Realtime（speech-to-speech）GA モデル。GPT-5 級推論を
# 音声ループ内で行う。リアルタイム系の頂点。
REALTIME_MODEL = "gpt-realtime-2"
REALTIME_VOICE = "marin"
CLIENT_SECRETS_ENDPOINT = "https://api.openai.com/v1/realtime/client_secrets"

# 推論の深さ（gpt-realtime-2 のキー機能）: minimal / low / medium / high / xhigh
#   OpenAI のデフォルトは弱め（minimal / low 相当）で、これを指定しないと speech モデルの
#   軽い応答しか返ってこない。コードの調査・要約・委譲判断などに必要な「考える音声」を
#   引き出すには high 以上を明示する必要がある（2026-05 の障害で実測判明）。
#   実用バランスとして high を default。OPENAI_REALTIME_REASONING_EFFORT で上書き可。
REALTIME_REASONING_EFFORT = os.environ.get("OPENAI_REALTIME_REASONING_EFFORT", "high")


def get_voice_instructions(*, chat_title: Optional[str] = None) -> str:
    """音声レイヤー（gpt-realtime-2）への指示文。

    方針: 役割・文脈・ツール・語彙ヒントだけ与え、振る舞いの細則は書かない。
    ネガティブ指示（「〜するな」「〜と決めつけるな」等）はモデルをその概念に
    固定するアンチパターンなので使わない。

    Args:
        chat_title: 起動元チャットのタイトル。指定があれば文脈として注入する。
    """
    base = (
        "あなたは『ダン』、ユーザーの開発を手伝う AI アシスタントの音声インタフェースです。"
        "日本語で短く自然に会話します。\n\n"
        "コード変更・ファイル操作・調査・テスト・デバッグなどの実作業は "
        "delegate_to_dan ツールで開発エージェント（Claude）に委譲し、"
        "結果が返ってきたら要点だけ口頭で伝えます。\n\n"
        "破壊的な操作（git push、デプロイ、削除など）の前は口頭で確認します。\n\n"
        # 語彙ヒント: 音声認識バイアスを開発系の単語に寄せて、短い発話の取り違いを減らす。
        "ユーザーは日本語のソフトウェア開発者。よく出る固有名詞: "
        "Claude, OpenAI, GitHub, Next.js, FastAPI, Supabase, Vercel, Stripe, "
        "Tailscale, Cloudflare, gpt-realtime, Python, TypeScript, uvicorn, Tailwind。"
    )
    if chat_title:
        base += f"\n\nこのセッションは『{chat_title}』というチャットから起動されました。"
    return base


# gpt-realtime-2 が実作業をバックグラウンドエージェントへ渡すための関数ツール
DELEGATE_TOOL = {
    "type": "function",
    "name": "delegate_to_dan",
    "description": (
        "ユーザーが実際の開発・実装・調査作業を依頼したとき、それを"
        "バックグラウンドの開発エージェント（Claude）に委譲する。"
        "コードの作成・修正、ファイル操作、テスト実行、コードベース調査など"
        "実作業はすべてこれを使う。会話・相談・確認だけのときは使わない。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": (
                    "開発エージェントに渡す作業指示。ユーザーの依頼を"
                    "具体的かつ自己完結した形で記述する（背景・対象・期待結果）。"
                ),
            }
        },
        "required": ["task"],
    },
}


def build_session_config(*, chat_title: Optional[str] = None) -> dict:
    """client_secrets に渡す gpt-realtime-2 のセッション設定。

    重要な指定:
      - `reasoning.effort`: 指定しないと OpenAI default の弱推論になるので必須。
      - `audio.input.transcription.model = gpt-realtime-whisper`: 入力音声の解釈用。
        OpenAI 公式で「Whisper v2 比 約90%、gpt-4o-transcribe 比 約70%幻覚減」。
        旧 whisper-1 のままだと日本語の短い発話で誤認しやすい（実例「おはよう→こわい」）。
      - `audio.input.transcription.language = "ja"`: 自動検出に任せず日本語ヒントを付与。
      - `audio.input.noise_reduction = near_field`: 接話マイク前提のノイズ除去で VAD と
        認識精度を改善（ラップトップ内蔵マイクや会議室は far_field の方が良い）。
    """
    return {
        "type": "realtime",
        "model": REALTIME_MODEL,
        "instructions": get_voice_instructions(chat_title=chat_title),
        "audio": {
            "input": {
                "transcription": {
                    "model": "gpt-realtime-whisper",
                    "language": "ja",
                },
                "noise_reduction": {"type": "near_field"},
            },
            "output": {"voice": REALTIME_VOICE},
        },
        "tools": [DELEGATE_TOOL],
        "reasoning": {"effort": REALTIME_REASONING_EFFORT},
    }


class RealtimeConfigError(RuntimeError):
    """OpenAI 側の設定エラー（キー未設定・Realtime 未許可・設定不正など）。"""


async def mint_client_secret(*, chat_title: Optional[str] = None) -> dict:
    """ブラウザ用の ephemeral クライアントシークレットを発行する。

    OpenAI API キーはサーバーに留め、ブラウザには短命の ek_ トークンだけ渡す。

    Args:
        chat_title: 起動元チャットのタイトル。session instructions に注入される。

    Returns:
        {"value": "ek_...", "model": REALTIME_MODEL, "expires_at": int | None}

    Raises:
        RealtimeConfigError: API キー未設定、または OpenAI が非 200 を返した場合。
    """
    if not settings.OPENAI_API_KEY:
        raise RealtimeConfigError("OPENAI_API_KEY が未設定です（.env を確認）")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            CLIENT_SECRETS_ENDPOINT,
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"session": build_session_config(chat_title=chat_title)},
        )

    if resp.status_code != 200:
        detail = resp.text[:500]
        logger.error("client_secrets failed: HTTP %s %s", resp.status_code, detail)
        raise RealtimeConfigError(
            f"OpenAI Realtime トークン発行に失敗しました（HTTP {resp.status_code}）。{detail}"
        )

    body = resp.json()
    return {
        "value": body.get("value", ""),
        "model": REALTIME_MODEL,
        "expires_at": body.get("expires_at"),
    }
