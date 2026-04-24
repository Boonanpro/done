"""
public_chat のビジネスロジック
無認証のクライアントHPから叩かれるチャットエンドポイント。
デフォルトで Gemini 2.5 Flash を使う（コスト最優先、無料枠あり）。
"""
import asyncio
import logging
from typing import List

from app.config import settings
from app.models.public_chat_schemas import PublicChatMessage

logger = logging.getLogger(__name__)

MODEL_ID = "gemini-2.5-flash"
MAX_OUTPUT_TOKENS = 600


DEFAULT_SYSTEM = (
    "あなたはクライアントHPに埋め込まれたAIアシスタント。"
    "訪問者の質問に簡潔に、敬体で、2〜4文以内で答えます。"
    "不明な点は素直に「わかりません」と答え、必要に応じて問い合わせフォームを案内します。"
    "営業トークや誇張はしません。"
)


class PublicChatService:
    def _get_client(self):
        from google import genai
        api_key = settings.GOOGLE_GEMINI_API_KEY
        if not api_key:
            raise RuntimeError("GOOGLE_GEMINI_API_KEY is not set")
        return genai.Client(api_key=api_key)

    async def respond(
        self,
        scope: str,
        messages: List[PublicChatMessage],
        system_context: str | None = None,
    ) -> dict:
        from google.genai import types as genai_types

        client = self._get_client()
        system = DEFAULT_SYSTEM
        if system_context:
            system = f"{DEFAULT_SYSTEM}\n\n# このサイトの文脈\n{system_context.strip()}"
        system = f"{system}\n\n# スコープ\nこのチャットは「{scope}」に関する質問のみに答えてください。"

        contents = [
            genai_types.Content(
                role="user" if m.role == "user" else "model",
                parts=[genai_types.Part(text=m.content)],
            )
            for m in messages
        ]

        def _call():
            return client.models.generate_content(
                model=MODEL_ID,
                contents=contents,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    temperature=0.4,
                ),
            )

        response = await asyncio.to_thread(_call)
        text = getattr(response, "text", "") or ""
        return {
            "content": text.strip(),
            "model": MODEL_ID,
        }
