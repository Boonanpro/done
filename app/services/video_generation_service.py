"""
video_generation のビジネスロジック
Kling 3.0 Pro (Kuaishou) で動画を生成し、Supabase Storage に保存。

変更履歴:
- 2026-04-24: Veo 3.1 Fast から Kling 3.0 Pro に切替。品質・コスト・
  最大尺・4K 対応すべての面で上位互換。fal.ai 経由で API アクセス。
"""
import os
import uuid
import asyncio
import logging
from typing import Optional, List

import httpx

from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

BUCKET = "generated-videos"
MODEL_ID = "kling-3.0-pro"
FAL_T2V_ENDPOINT = "fal-ai/kling-video/v3/pro/text-to-video"
FAL_I2V_ENDPOINT = "fal-ai/kling-video/v3/pro/image-to-video"

SUPPORTED_DURATIONS = {"5", "10"}  # 秒。Kling 3.0 Pro は 5/10 秒が標準 (15 秒は一部)


class VideoGenerationService:
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.table = "generated_videos"

    def _ensure_fal_key(self):
        from app.config import settings
        key = settings.FAL_KEY or os.environ.get("FAL_KEY", "")
        if not key:
            raise RuntimeError(
                "FAL_KEY が未設定。https://fal.ai/dashboard/keys で API キーを取得し "
                ".env に FAL_KEY=... を追加してください。"
            )
        # fal_client は環境変数から読むので export
        os.environ["FAL_KEY"] = key

    async def _ensure_bucket(self):
        def _do():
            try:
                self.supabase.storage.create_bucket(BUCKET, options={"public": True})
                logger.info(f"Created Supabase Storage bucket: {BUCKET}")
            except Exception as e:
                msg = str(e).lower()
                if "already exists" not in msg and "duplicate" not in msg and "resource already exists" not in msg:
                    logger.warning(f"bucket create (ignored if exists): {e}")
        await asyncio.to_thread(_do)

    async def _upload_to_storage(self, data: bytes, kind: str) -> tuple[str, str]:
        await self._ensure_bucket()
        path = f"{kind}/{uuid.uuid4()}.mp4"

        def _upload():
            self.supabase.storage.from_(BUCKET).upload(
                path=path,
                file=data,
                file_options={"content-type": "video/mp4", "upsert": "false"},
            )
            return self.supabase.storage.from_(BUCKET).get_public_url(path)

        url = await asyncio.to_thread(_upload)
        if url.endswith("?"):
            url = url[:-1]
        return url, path

    async def _download_video(self, url: str) -> bytes:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.content

    async def _run_fal(self, endpoint: str, arguments: dict) -> dict:
        """fal.ai の非同期ジョブを投げて結果 URL を取得。"""
        self._ensure_fal_key()
        import fal_client

        def _submit():
            # subscribe は内部で poll して完了まで待つ同期 API
            return fal_client.subscribe(
                endpoint,
                arguments=arguments,
                with_logs=False,
            )

        result = await asyncio.to_thread(_submit)
        if not result or "video" not in result:
            raise RuntimeError(f"fal 応答に video フィールド無し: {str(result)[:300]}")
        return result

    async def generate(
        self,
        prompt: str,
        user_id: str,
        project_id: Optional[str] = None,
        message_id: Optional[str] = None,
        aspect_ratio: str = "16:9",
        duration: str = "5",
        reference_image_url: Optional[str] = None,
    ) -> dict:
        """動画を生成する。reference_image_url 指定時は image-to-video、無ければ text-to-video。

        Args:
            prompt: 動画プロンプト (日本語でも英語でも可、英語推奨)
            aspect_ratio: "16:9" | "9:16" | "1:1"
            duration: "5" or "10" (秒、文字列)
            reference_image_url: 参照画像 (image-to-video モードで使用)
        """
        if duration not in SUPPORTED_DURATIONS:
            duration = "5"

        if reference_image_url:
            endpoint = FAL_I2V_ENDPOINT
            kind = "image-to-video"
            arguments = {
                "prompt": prompt,
                "image_url": reference_image_url,
                "duration": duration,
                "aspect_ratio": aspect_ratio,
            }
        else:
            endpoint = FAL_T2V_ENDPOINT
            kind = "text-to-video"
            arguments = {
                "prompt": prompt,
                "duration": duration,
                "aspect_ratio": aspect_ratio,
            }

        result = await self._run_fal(endpoint, arguments)
        video_url = result["video"].get("url")
        if not video_url:
            raise RuntimeError(f"fal 応答の video.url が空: {str(result)[:300]}")

        # fal のホストから直接公開もできるが、既存バケットに保存して URL 統一
        video_bytes = await self._download_video(video_url)
        url, path = await self._upload_to_storage(video_bytes, kind)

        row = {
            "prompt": prompt,
            "url": url,
            "storage_path": path,
            "model": MODEL_ID,
            "kind": kind,
            "mime_type": "video/mp4",
            "aspect_ratio": aspect_ratio,
            "created_by": user_id,
        }
        if project_id:
            row["project_id"] = str(project_id)
        if message_id:
            row["message_id"] = str(message_id)
        if reference_image_url:
            row["reference_url"] = reference_image_url

        result = self.supabase.table(self.table).insert(row).execute()
        return result.data[0] if result.data else row

    async def list(
        self,
        user_id: str,
        project_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        query = (
            self.supabase.table(self.table)
            .select("*")
            .eq("created_by", user_id)
        )
        if project_id:
            query = query.eq("project_id", project_id)
        result = query.order("created_at", desc=True).limit(limit).execute()
        return result.data or []
