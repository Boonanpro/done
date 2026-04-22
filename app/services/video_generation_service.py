"""
video_generation のビジネスロジック
Veo 3.1 Fast で動画を生成し、Supabase Storage に保存。
"""
import os
import uuid
import asyncio
import logging
import time
from typing import Optional, List

import httpx

from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

BUCKET = "generated-videos"
MODEL_ID = "veo-3.1-fast-generate-preview"
POLL_INTERVAL = 10
MAX_WAIT = 300


class VideoGenerationService:
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.table = "generated_videos"

    def _get_client(self):
        from google import genai
        from app.config import settings
        api_key = settings.GOOGLE_GEMINI_API_KEY or os.environ.get("GOOGLE_GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError("GOOGLE_GEMINI_API_KEY is not set")
        return genai.Client(api_key=api_key)

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

    async def _fetch_image_bytes(self, url: str) -> tuple[bytes, str]:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            mime = r.headers.get("content-type", "image/png").split(";")[0].strip()
            return r.content, mime

    async def _wait_for_operation(self, client, operation):
        start = time.time()
        while not operation.done:
            await asyncio.sleep(POLL_INTERVAL)
            if time.time() - start > MAX_WAIT:
                raise TimeoutError(f"Video generation timed out after {MAX_WAIT}s")
            operation = await asyncio.to_thread(client.operations.get, operation)
        return operation

    async def _download_video_bytes(self, client, video) -> bytes:
        def _download():
            if hasattr(video, "video_bytes") and video.video_bytes:
                return video.video_bytes
            buf = client.files.download(file=video)
            if isinstance(buf, bytes):
                return buf
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
                tmp_path = tf.name
            try:
                if hasattr(video, "save"):
                    video.save(tmp_path)
                with open(tmp_path, "rb") as f:
                    return f.read()
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        return await asyncio.to_thread(_download)

    async def generate(
        self,
        prompt: str,
        user_id: str,
        project_id: Optional[str] = None,
        message_id: Optional[str] = None,
        aspect_ratio: str = "16:9",
        reference_image_url: Optional[str] = None,
    ) -> dict:
        from google.genai import types
        client = self._get_client()

        image_arg = None
        kind = "text-to-video"
        if reference_image_url:
            ref_bytes, ref_mime = await self._fetch_image_bytes(reference_image_url)
            image_arg = types.Image(image_bytes=ref_bytes, mime_type=ref_mime)
            kind = "image-to-video"

        def _start():
            config = types.GenerateVideosConfig(aspect_ratio=aspect_ratio) if aspect_ratio else None
            return client.models.generate_videos(
                model=MODEL_ID,
                prompt=prompt,
                image=image_arg,
                config=config,
            )

        operation = await asyncio.to_thread(_start)
        operation = await self._wait_for_operation(client, operation)

        response = operation.response
        if not response or not getattr(response, "generated_videos", None):
            raise RuntimeError("Veo 応答に生成動画が含まれていません")

        gen_video = response.generated_videos[0]
        video_obj = gen_video.video
        video_bytes = await self._download_video_bytes(client, video_obj)

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
