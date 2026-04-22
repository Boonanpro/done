"""
image_generation のビジネスロジック
Nano Banana (Gemini 2.5 Flash Image) で画像を生成し、Supabase Storage に保存。
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
MODEL_ID = "gemini-2.5-flash-image"


class ImageGenerationService:
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.table = "generated_images"

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

    def _extract_image_from_response(self, response) -> Optional[bytes]:
        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            if not content:
                continue
            for part in getattr(content, "parts", []) or []:
                inline_data = getattr(part, "inline_data", None)
                if inline_data and getattr(inline_data, "data", None):
                    data = inline_data.data
                    if isinstance(data, str):
                        return base64.b64decode(data)
                    return data
        return None

    def _extract_text_from_response(self, response) -> str:
        parts_text: List[str] = []
        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            if not content:
                continue
            for part in getattr(content, "parts", []) or []:
                t = getattr(part, "text", None)
                if t:
                    parts_text.append(t)
        return " ".join(parts_text).strip()

    async def generate(
        self,
        prompt: str,
        user_id: str,
        project_id: Optional[str] = None,
        message_id: Optional[str] = None,
        size: str = "1024x1024",
    ) -> dict:
        client = self._get_client()

        def _call():
            return client.models.generate_content(
                model=MODEL_ID,
                contents=[prompt],
            )

        response = await asyncio.to_thread(_call)
        img_bytes = self._extract_image_from_response(response)
        if not img_bytes:
            text = self._extract_text_from_response(response)
            raise RuntimeError(
                f"画像データが返ってきませんでした。応答テキスト: {text[:300]}" if text
                else "画像データが返ってきませんでした"
            )

        url, path = await self._upload_to_storage(img_bytes, "generate")

        row = {
            "prompt": prompt,
            "url": url,
            "storage_path": path,
            "model": MODEL_ID,
            "kind": "generate",
            "mime_type": "image/png",
            "size": size,
            "created_by": user_id,
        }
        if project_id:
            row["project_id"] = str(project_id)
        if message_id:
            row["message_id"] = str(message_id)

        result = self.supabase.table(self.table).insert(row).execute()
        return result.data[0] if result.data else row

    async def edit(
        self,
        prompt: str,
        reference_url: str,
        user_id: str,
        project_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> dict:
        from google.genai import types
        client = self._get_client()
        ref_bytes = await self._fetch_image_bytes(reference_url)

        def _call():
            return client.models.generate_content(
                model=MODEL_ID,
                contents=[
                    prompt,
                    types.Part.from_bytes(data=ref_bytes, mime_type="image/png"),
                ],
            )

        response = await asyncio.to_thread(_call)
        img_bytes = self._extract_image_from_response(response)
        if not img_bytes:
            text = self._extract_text_from_response(response)
            raise RuntimeError(
                f"画像データが返ってきませんでした。応答テキスト: {text[:300]}" if text
                else "画像データが返ってきませんでした"
            )

        url, path = await self._upload_to_storage(img_bytes, "edit")

        row = {
            "prompt": prompt,
            "url": url,
            "storage_path": path,
            "model": MODEL_ID,
            "kind": "edit",
            "reference_url": reference_url,
            "mime_type": "image/png",
            "created_by": user_id,
        }
        if project_id:
            row["project_id"] = str(project_id)
        if message_id:
            row["message_id"] = str(message_id)

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
