"""
image_generation のビジネスロジック
GPT Image 2 (OpenAI) で画像を生成/編集し、Supabase Storage に保存。

変更履歴:
- 2026-04-22: Nano Banana から GPT Image 2 へ切替試行 → verification 待ちで一時ロールバック
- 2026-04-24: OpenAI org verification 完了、GPT Image 2 に本切替
"""
import os
import uuid
import base64
import asyncio
import logging
from typing import Optional, List

import httpx

from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

BUCKET = "generated-images"
MODEL_ID = "gpt-image-2"

SUPPORTED_SIZES = {"1024x1024", "1792x1024", "1024x1792", "auto"}


class ImageGenerationService:
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.table = "generated_images"

    def _get_client(self):
        from openai import OpenAI
        from app.config import settings
        api_key = settings.OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        return OpenAI(api_key=api_key)

    async def _ensure_bucket(self):
        def _do():
            try:
                self.supabase.storage.create_bucket(
                    BUCKET, options={"public": True}
                )
                logger.info(f"Created Supabase Storage bucket: {BUCKET}")
            except Exception as e:
                msg = str(e).lower()
                if "already exists" not in msg and "duplicate" not in msg and "resource already exists" not in msg:
                    logger.warning(f"bucket create error (ignored if exists): {e}")
        await asyncio.to_thread(_do)

    async def _upload_to_storage(self, data: bytes, kind: str) -> tuple[str, str]:
        await self._ensure_bucket()
        path = f"{kind}/{uuid.uuid4()}.png"

        def _upload():
            self.supabase.storage.from_(BUCKET).upload(
                path=path,
                file=data,
                file_options={"content-type": "image/png", "upsert": "false"},
            )
            return self.supabase.storage.from_(BUCKET).get_public_url(path)

        url = await asyncio.to_thread(_upload)
        if url.endswith("?"):
            url = url[:-1]
        return url, path

    async def _fetch_image_bytes(self, url: str) -> bytes:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.content

    def _normalize_size(self, size: str) -> str:
        if size in SUPPORTED_SIZES:
            return size
        # 旧 Nano Banana 互換: 1024x1536 等が来たら近い OpenAI サイズに寄せる
        mapping = {
            "1024x1536": "1024x1792",
            "1536x1024": "1792x1024",
        }
        return mapping.get(size, "1024x1024")

    async def generate(
        self,
        prompt: str,
        user_id: str,
        project_id: Optional[str] = None,
        message_id: Optional[str] = None,
        size: str = "1024x1024",
        quality: str = "high",
    ) -> dict:
        client = self._get_client()
        normalized_size = self._normalize_size(size)

        def _call():
            return client.images.generate(
                model=MODEL_ID,
                prompt=prompt,
                size=normalized_size,
                quality=quality,
                n=1,
            )

        response = await asyncio.to_thread(_call)
        if not response.data or not response.data[0].b64_json:
            raise RuntimeError("OpenAI 応答に画像データが含まれていません")
        img_bytes = base64.b64decode(response.data[0].b64_json)

        url, path = await self._upload_to_storage(img_bytes, "generate")

        row = {
            "prompt": prompt,
            "url": url,
            "storage_path": path,
            "model": MODEL_ID,
            "kind": "generate",
            "mime_type": "image/png",
            "size": normalized_size,
            "created_by": user_id,
        }
        if project_id:
            row["project_id"] = str(project_id)
        if message_id:
            row["message_id"] = str(message_id)

        result = self.supabase.table(self.table).insert(row).execute()
        record = result.data[0] if result.data else row
        # dan-notion 自動整理（best-effort）
        if project_id and record.get("id"):
            try:
                from app.services.dan_notion_service import get_dan_notion_service
                pr = self.supabase.table("projects").select("title").eq("id", str(project_id)).limit(1).execute()
                title = pr.data[0]["title"] if pr.data else None
                get_dan_notion_service().add_asset_block_to_project(
                    user_id=user_id, project_id=str(project_id),
                    project_title=title, asset=record,
                    asset_type="image", source_id=record["id"],
                )
            except Exception:
                logger.exception("dan-notion sync failed for image %s", record.get("id"))
        return record

    async def edit(
        self,
        prompt: str,
        reference_url: str,
        user_id: str,
        project_id: Optional[str] = None,
        message_id: Optional[str] = None,
        size: str = "1024x1024",
        quality: str = "high",
    ) -> dict:
        client = self._get_client()
        normalized_size = self._normalize_size(size)
        ref_bytes = await self._fetch_image_bytes(reference_url)

        def _call():
            import io
            file_obj = io.BytesIO(ref_bytes)
            file_obj.name = "reference.png"
            return client.images.edit(
                model=MODEL_ID,
                image=file_obj,
                prompt=prompt,
                size=normalized_size,
                quality=quality,
                n=1,
            )

        response = await asyncio.to_thread(_call)
        if not response.data or not response.data[0].b64_json:
            raise RuntimeError("OpenAI 応答に画像データが含まれていません")
        img_bytes = base64.b64decode(response.data[0].b64_json)

        url, path = await self._upload_to_storage(img_bytes, "edit")

        row = {
            "prompt": prompt,
            "url": url,
            "storage_path": path,
            "model": MODEL_ID,
            "kind": "edit",
            "reference_url": reference_url,
            "mime_type": "image/png",
            "size": normalized_size,
            "created_by": user_id,
        }
        if project_id:
            row["project_id"] = str(project_id)
        if message_id:
            row["message_id"] = str(message_id)

        result = self.supabase.table(self.table).insert(row).execute()
        record = result.data[0] if result.data else row
        if project_id and record.get("id"):
            try:
                from app.services.dan_notion_service import get_dan_notion_service
                pr = self.supabase.table("projects").select("title").eq("id", str(project_id)).limit(1).execute()
                title = pr.data[0]["title"] if pr.data else None
                get_dan_notion_service().add_asset_block_to_project(
                    user_id=user_id, project_id=str(project_id),
                    project_title=title, asset=record,
                    asset_type="image", source_id=record["id"],
                )
            except Exception:
                logger.exception("dan-notion sync failed for image %s", record.get("id"))
        return record

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
