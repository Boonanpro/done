"""Persistent job state for Salonboard style posting."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.supabase_client import get_supabase_client


TERMINAL_STATUSES = {"done", "error"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SalonboardPostJobService:
    def __init__(self) -> None:
        self.supabase = get_supabase_client().client
        self.table = "salonboard_post_jobs"

    async def create(
        self,
        *,
        job_id: str,
        device_id: str,
        fields: dict[str, Any],
        images_meta: list[dict[str, Any]] | list[Any],
        photo_count: int,
    ) -> dict[str, Any]:
        data = {
            "id": job_id,
            "device_id": device_id,
            "status": "pending",
            "message": "投稿を受け付けました",
            "fields": fields,
            "images_meta": images_meta,
            "photo_count": photo_count,
        }
        result = self.supabase.table(self.table).insert(data).execute()
        return result.data[0] if result.data else data

    async def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        message: str | None = None,
        style_name: str | None = None,
        style_id: str | None = None,
        registered: bool | None = None,
        published: bool | None = None,
        result_data: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        updates: dict[str, Any] = {}
        if status is not None:
            updates["status"] = status
            if status == "running":
                updates["started_at"] = _now()
            if status in TERMINAL_STATUSES:
                updates["completed_at"] = _now()
        if message is not None:
            updates["message"] = message
        if style_name is not None:
            updates["style_name"] = style_name
        if style_id is not None:
            updates["style_id"] = style_id
        if registered is not None:
            updates["registered"] = registered
        if published is not None:
            updates["published"] = published
        if result_data is not None:
            updates["result"] = result_data
        if error is not None:
            updates["error"] = error
        if not updates:
            return await self.get(job_id)

        result = (
            self.supabase.table(self.table)
            .update(updates)
            .eq("id", job_id)
            .execute()
        )
        return result.data[0] if result.data else None

    async def get(self, job_id: str) -> dict[str, Any] | None:
        result = (
            self.supabase.table(self.table)
            .select("*")
            .eq("id", job_id)
            .execute()
        )
        return result.data[0] if result.data else None


def normalize_job_for_api(job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    """Return the compact shape expected by the current mobile/web client."""
    return {
        "job_id": job_id,
        "status": job.get("status", "pending"),
        "message": job.get("message"),
        "style_name": job.get("style_name"),
        "style_id": job.get("style_id"),
        "registered": job.get("registered"),
        "published": job.get("published"),
    }
