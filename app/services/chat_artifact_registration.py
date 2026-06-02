"""Helpers for registering generated frontend artifacts.

This module is intentionally independent from the chat SSE route. The CLI
runner can finish and save an AI message even when the browser/SSE consumer is
gone, so artifact registration must be callable from the same DB-first path.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, Optional

from app.services.chat_artifact_service import ChatArtifactService

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALIAS_DEPLOY_LOG = PROJECT_ROOT / "artifact_alias_deploy.log"
ALIAS_DEPLOY_DEBOUNCE_SECONDS = 30
WRITE_TOOL_NAMES = {
    "write_file",
    "edit_file",
    "Write",
    "Edit",
    "mcp__dan-tools__write_file",
}

ARTIFACT_PAGE_RE = re.compile(
    r"frontend[/\\]src[/\\]app[/\\]artifacts[/\\]([\w-]+)(?:[/\\]([^:]*?))?[/\\]page\.tsx$"
)
ARTIFACT_SLUG_RE = re.compile(r"frontend[/\\]src[/\\]app[/\\]artifacts[/\\]([\w-]+)[/\\]")


def written_path_from_tool(tool_name: str, tool_input: object) -> Optional[str]:
    """Return the written path from a write/edit tool event, if any."""
    if tool_name not in WRITE_TOOL_NAMES or not isinstance(tool_input, dict):
        return None
    value = tool_input.get("path") or tool_input.get("file_path")
    return value if isinstance(value, str) and value.strip() else None


def add_written_path(paths: list[str], path: Optional[str]) -> None:
    """Append a path once, preserving first-seen order."""
    if path and path not in paths:
        paths.append(path)


def artifact_candidates_from_written_paths(
    written_file_paths: Iterable[str],
) -> list[tuple[str, str, str]]:
    """Extract (card_slug, preview_url, source_path) for artifact entry pages."""
    candidates: list[tuple[str, str, str]] = []
    for raw_path in written_file_paths:
        normalized_path = (raw_path or "").replace("\\", "/")
        match = ARTIFACT_PAGE_RE.search(normalized_path)
        if not match:
            logger.info(
                "Skipping chat artifact auto-registration for non-entry artifact file: %s",
                normalized_path,
            )
            continue
        root_slug = match.group(1)
        rest = (match.group(2) or "").strip("/")
        preview_url = f"/artifacts/{root_slug}" + (f"/{rest}" if rest else "")
        card_slug = (
            root_slug
            if not rest
            else f"{root_slug}-{'-'.join(part for part in rest.split('/') if part)}"
        )
        candidates.append((card_slug, preview_url, normalized_path))
    return candidates


def artifact_slugs_from_written_paths(written_file_paths: Iterable[str]) -> list[str]:
    """Extract root artifact slugs from written frontend artifact paths."""
    slugs: list[str] = []
    seen: set[str] = set()
    for raw_path in written_file_paths:
        match = ARTIFACT_SLUG_RE.search((raw_path or "").replace("\\", "/"))
        if not match:
            continue
        slug = match.group(1)
        if slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    return slugs


def schedule_artifact_alias_deploy(slugs: Iterable[str]) -> None:
    """Start a background Vercel deploy that assigns stable delivery aliases."""
    unique_slugs: list[str] = []
    seen: set[str] = set()
    for raw_slug in slugs:
        slug = (raw_slug or "").strip()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        unique_slugs.append(slug)

    if not unique_slugs:
        return

    try:
        lock_name = "artifact_alias_deploy_" + "_".join(unique_slugs) + ".lock"
        lock_path = PROJECT_ROOT / ".tmp" / re.sub(r"[^a-zA-Z0-9_.-]", "_", lock_name)
        lock_path.parent.mkdir(exist_ok=True)
        now = time.time()
        if lock_path.exists() and now - lock_path.stat().st_mtime < ALIAS_DEPLOY_DEBOUNCE_SECONDS:
            logger.info("Skipping duplicate artifact alias deploy for slugs=%s", ",".join(unique_slugs))
            return
        lock_path.write_text(str(now), encoding="utf-8")

        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        with ALIAS_DEPLOY_LOG.open("ab") as log_file:
            subprocess.Popen(
                [sys.executable, "scripts/deploy_frontend_artifacts.py", *unique_slugs],
                cwd=str(PROJECT_ROOT),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
        logger.info("Scheduled artifact alias deploy for slugs=%s", ",".join(unique_slugs))
    except Exception as e:  # noqa: BLE001 - publishing must not break chat completion
        logger.warning("Failed to schedule artifact alias deploy: %s", e)


def schedule_artifact_alias_deploy_from_written_paths(written_file_paths: Iterable[str]) -> None:
    """Schedule public alias deployment for any artifact root touched by writes."""
    schedule_artifact_alias_deploy(artifact_slugs_from_written_paths(written_file_paths))


def _page_exists(preview_url: str) -> bool:
    route_parts = preview_url.strip("/").split("/")
    page_path = PROJECT_ROOT / "frontend" / "src" / "app" / Path(*route_parts) / "page.tsx"
    return page_path.exists()


def _artifact_exists(service: ChatArtifactService, room_id: str, preview_url: str) -> bool:
    existing = (
        service.supabase.table("chat_artifact")
        .select("id")
        .eq("room_id", room_id)
        .eq("preview_url", preview_url)
        .limit(1)
        .execute()
    )
    return bool(existing.data)


def _payload_for_candidate(
    *,
    service: ChatArtifactService,
    room_id: str,
    project_id: Optional[str],
    slug: str,
    preview_url: str,
    source_path: str,
) -> dict:
    return {
        "room_id": room_id,
        "project_id": project_id,
        "slug": slug,
        "kind": "production",
        "artifact_type": service.infer_artifact_type(slug=slug, path=source_path),
        "label": slug.replace("-", " ").replace("_", " "),
        "preview_url": preview_url,
        "publish_status": "preview_live",
    }


def register_written_chat_artifacts_sync(
    written_file_paths: Iterable[str],
    room_id: Optional[str],
    project_id: Optional[str],
    user_id: str,
) -> list[dict]:
    """Register artifact cards from written files, returning created rows.

    This is best-effort: one bad candidate should not fail the whole turn.
    """
    if not room_id:
        return []

    written_paths = list(written_file_paths)
    service = ChatArtifactService()
    created: list[dict] = []
    seen: set[str] = set()

    for slug, preview_url, source_path in artifact_candidates_from_written_paths(written_paths):
        if slug in seen:
            continue
        seen.add(slug)
        try:
            if not _page_exists(preview_url):
                logger.info("Skipping chat artifact registration for %s: page.tsx not found", slug)
                continue
            if _artifact_exists(service, room_id, preview_url):
                continue
            artifact = service.create_sync(
                _payload_for_candidate(
                    service=service,
                    room_id=room_id,
                    project_id=project_id,
                    slug=slug,
                    preview_url=preview_url,
                    source_path=source_path,
                ),
                user_id,
            )
            if artifact:
                created.append(artifact)
        except Exception as e:  # noqa: BLE001 - registration must not break chat completion
            logger.warning("Chat artifact auto-register failed for %s: %s", slug, e)

    schedule_artifact_alias_deploy_from_written_paths(written_paths)
    return created


async def register_written_chat_artifacts(
    written_file_paths: Iterable[str],
    room_id: Optional[str],
    project_id: Optional[str],
    user_id: str,
) -> list[dict]:
    """Async wrapper for API routes."""
    if not room_id:
        return []

    written_paths = list(written_file_paths)
    service = ChatArtifactService()
    created: list[dict] = []
    seen: set[str] = set()

    for slug, preview_url, source_path in artifact_candidates_from_written_paths(written_paths):
        if slug in seen:
            continue
        seen.add(slug)
        try:
            if not _page_exists(preview_url):
                logger.info("Skipping chat artifact registration for %s: page.tsx not found", slug)
                continue
            if _artifact_exists(service, room_id, preview_url):
                continue
            artifact = await service.create(
                _payload_for_candidate(
                    service=service,
                    room_id=room_id,
                    project_id=project_id,
                    slug=slug,
                    preview_url=preview_url,
                    source_path=source_path,
                ),
                user_id,
            )
            if artifact:
                created.append(artifact)
        except Exception as e:  # noqa: BLE001 - registration must not break chat completion
            logger.warning("Chat artifact auto-register failed for %s: %s", slug, e)

    schedule_artifact_alias_deploy_from_written_paths(written_paths)
    return created
