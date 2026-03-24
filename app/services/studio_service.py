"""
Studio Service - AI Vlog Production
Handles Kling O3 video generation and ElevenLabs voice generation
"""
import httpx
import logging
import json
from datetime import datetime, timezone
from typing import Optional
from app.config import settings
from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class StudioService:
    def __init__(self):
        self.supabase = get_supabase_client().client

    # ==================== Channels ====================

    async def create_channel(self, user_id: str, data: dict) -> dict:
        result = self.supabase.table("studio_channels").insert({
            "user_id": user_id,
            **data,
        }).execute()
        return result.data[0]

    async def list_channels(self, user_id: str) -> list:
        result = self.supabase.table("studio_channels") \
            .select("*") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .execute()
        return result.data

    async def get_channel(self, channel_id: str, user_id: str) -> Optional[dict]:
        result = self.supabase.table("studio_channels") \
            .select("*") \
            .eq("id", channel_id) \
            .eq("user_id", user_id) \
            .single() \
            .execute()
        return result.data

    async def update_channel(self, channel_id: str, user_id: str, data: dict) -> dict:
        result = self.supabase.table("studio_channels") \
            .update({**data, "updated_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("id", channel_id) \
            .eq("user_id", user_id) \
            .execute()
        return result.data[0]

    # ==================== Episodes ====================

    async def create_episode(self, user_id: str, data: dict) -> dict:
        result = self.supabase.table("studio_episodes").insert({
            "user_id": user_id,
            **data,
        }).execute()
        return result.data[0]

    async def list_episodes(self, channel_id: str, user_id: str) -> list:
        result = self.supabase.table("studio_episodes") \
            .select("*") \
            .eq("channel_id", channel_id) \
            .eq("user_id", user_id) \
            .order("episode_number", desc=False) \
            .execute()
        return result.data

    async def get_episode(self, episode_id: str, user_id: str) -> Optional[dict]:
        result = self.supabase.table("studio_episodes") \
            .select("*") \
            .eq("id", episode_id) \
            .eq("user_id", user_id) \
            .single() \
            .execute()
        return result.data

    async def update_episode(self, episode_id: str, user_id: str, data: dict) -> dict:
        result = self.supabase.table("studio_episodes") \
            .update({**data, "updated_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("id", episode_id) \
            .eq("user_id", user_id) \
            .execute()
        return result.data[0]

    # ==================== Script Chat ====================

    async def chat_script(self, episode_id: str, user_id: str, message: str) -> str:
        """Claudeとシナリオ壁打ち"""
        episode = await self.get_episode(episode_id, user_id)
        if not episode:
            raise ValueError("Episode not found")

        history = episode.get("script_messages", []) or []

        import anthropic
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        system_prompt = """あなたはAI Vlog「一人ゴールドマン計画」の脚本家アシスタントです。
このVlogは、25歳の男性AIキャラクターが金融素人から一人で投資ビジネスを立ち上げ、年商10億円を目指す実録風エンターテインメントです。

脚本作成のルール：
- テンポよく面白い展開を意識する（ウルフ・オブ・ウォールストリート的なエネルギー）
- 金融の一般知識・仕組みは説明してよいが、特定銘柄の具体的な購入推奨はしない
- 視聴者が「自分もやってみたい」と感じる内容にする
- 5〜10分の動画を想定（約1,500〜3,000文字の台本）
- シーン分けを明確に（[シーン1: 場面説明]のフォーマット）

現在のエピソード: """ + episode.get("title", "")

        messages = history + [{"role": "user", "content": message}]

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=system_prompt,
            messages=messages,
        )
        assistant_message = response.content[0].text

        # 履歴を更新
        new_history = messages + [{"role": "assistant", "content": assistant_message}]
        # 最大50メッセージを保持
        if len(new_history) > 50:
            new_history = new_history[-50:]

        await self.update_episode(episode_id, user_id, {
            "script_messages": new_history,
        })

        return assistant_message

    # ==================== Voice Generation ====================

    async def generate_voice(self, episode_id: str, user_id: str,
                              text: str, label: str,
                              voice_id: Optional[str] = None) -> dict:
        """ElevenLabsで音声生成してSupabaseに保存"""
        api_key = settings.ELEVENLABS_API_KEY
        if not api_key:
            raise ValueError("ELEVENLABS_API_KEY is not set")

        vid = voice_id or settings.ELEVENLABS_VOICE_ID
        model_id = "eleven_multilingual_v2"

        # ElevenLabs API呼び出し
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{vid}",
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": model_id,
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                    },
                },
            )

        if response.status_code != 200:
            raise ValueError(f"ElevenLabs API error: {response.status_code} {response.text}")

        # 音声ファイルをSupabase Storageに保存
        import uuid
        file_name = f"studio/voice/{episode_id}/{uuid.uuid4()}.mp3"
        audio_bytes = response.content

        storage = get_supabase_client().client.storage
        try:
            storage.from_("attachments").upload(
                path=file_name,
                file=audio_bytes,
                file_options={"content-type": "audio/mpeg"},
            )
            file_url = storage.from_("attachments").get_public_url(file_name)
        except Exception as e:
            logger.warning(f"Storage upload failed: {e}. Saving without URL.")
            file_url = None

        # DBに保存
        result = self.supabase.table("studio_voice_tracks").insert({
            "episode_id": episode_id,
            "user_id": user_id,
            "label": label or text[:50],
            "text_content": text,
            "voice_id": vid,
            "model_id": model_id,
            "file_url": file_url,
            "status": "done" if file_url else "error",
        }).execute()

        return result.data[0]

    async def list_voice_tracks(self, episode_id: str, user_id: str) -> list:
        result = self.supabase.table("studio_voice_tracks") \
            .select("*") \
            .eq("episode_id", episode_id) \
            .eq("user_id", user_id) \
            .order("created_at") \
            .execute()
        return result.data

    # ==================== Video Generation (Kling O3 via fal.ai) ====================

    async def generate_video(self, episode_id: str, user_id: str,
                              prompt: str, duration: int = 5,
                              mode: str = "std",
                              label: str = "",
                              negative_prompt: str = "") -> dict:
        """Kling O3で映像生成（fal.ai経由）"""
        fal_api_key = settings.FAL_API_KEY
        if not fal_api_key:
            raise ValueError("FAL_API_KEY is not set. Get it at fal.ai")

        # DBにpendingレコードを作成
        result = self.supabase.table("studio_video_clips").insert({
            "episode_id": episode_id,
            "user_id": user_id,
            "label": label or prompt[:50],
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "duration": duration,
            "mode": mode,
            "kling_status": "pending",
        }).execute()
        clip = result.data[0]
        clip_id = clip["id"]

        # fal.ai Kling O3 API
        kling_model = "fal-ai/kling-video/v1.6/standard/text-to-video"
        if mode == "pro":
            kling_model = "fal-ai/kling-video/v1.6/pro/text-to-video"

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"https://queue.fal.run/{kling_model}",
                headers={
                    "Authorization": f"Key {fal_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "prompt": prompt,
                    "negative_prompt": negative_prompt or "",
                    "duration": str(duration),
                    "aspect_ratio": "16:9",
                },
            )

        if resp.status_code not in (200, 201):
            self.supabase.table("studio_video_clips") \
                .update({"kling_status": "error"}) \
                .eq("id", clip_id) \
                .execute()
            raise ValueError(f"fal.ai API error: {resp.status_code} {resp.text}")

        task_data = resp.json()
        task_id = task_data.get("request_id", "")

        # task_idを保存
        self.supabase.table("studio_video_clips") \
            .update({
                "kling_task_id": task_id,
                "kling_status": "processing",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }) \
            .eq("id", clip_id) \
            .execute()

        return {**clip, "kling_task_id": task_id, "kling_status": "processing"}

    async def check_video_status(self, clip_id: str, user_id: str) -> dict:
        """映像生成ステータス確認・完了時にURL更新"""
        result = self.supabase.table("studio_video_clips") \
            .select("*") \
            .eq("id", clip_id) \
            .eq("user_id", user_id) \
            .single() \
            .execute()
        clip = result.data
        if not clip:
            raise ValueError("Clip not found")

        if clip["kling_status"] in ("done", "error"):
            return clip

        task_id = clip.get("kling_task_id")
        if not task_id:
            return clip

        fal_api_key = settings.FAL_API_KEY
        kling_model = "fal-ai/kling-video/v1.6/standard/text-to-video"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"https://queue.fal.run/{kling_model}/requests/{task_id}",
                headers={"Authorization": f"Key {fal_api_key}"},
            )

        if resp.status_code != 200:
            return clip

        data = resp.json()
        status = data.get("status", "")

        if status == "COMPLETED":
            video_url = data.get("video", {}).get("url", "")
            self.supabase.table("studio_video_clips") \
                .update({
                    "kling_status": "done",
                    "file_url": video_url,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }) \
                .eq("id", clip_id) \
                .execute()
            return {**clip, "kling_status": "done", "file_url": video_url}
        elif status in ("FAILED", "CANCELLED"):
            self.supabase.table("studio_video_clips") \
                .update({"kling_status": "error"}) \
                .eq("id", clip_id) \
                .execute()
            return {**clip, "kling_status": "error"}

        return clip

    async def list_video_clips(self, episode_id: str, user_id: str) -> list:
        result = self.supabase.table("studio_video_clips") \
            .select("*") \
            .eq("episode_id", episode_id) \
            .eq("user_id", user_id) \
            .order("sort_order") \
            .execute()
        return result.data
