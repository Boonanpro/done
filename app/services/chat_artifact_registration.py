"""Helpers for registering generated frontend artifacts.

This module is intentionally independent from the chat SSE route. The CLI
runner can finish and save an AI message even when the browser/SSE consumer is
gone, so artifact registration must be callable from the same DB-first path.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable, Optional

from app.services.chat_artifact_service import ChatArtifactService

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
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
    """Extract (card_slug, preview_url, source_path) — one entry per artifact root.

    A multi-page site lives under a single root directory as nested App Router
    routes, e.g.::

        artifacts/paina/page.tsx           -> /artifacts/paina
        artifacts/paina/business/page.tsx  -> /artifacts/paina/business
        artifacts/paina/contact/page.tsx   -> /artifacts/paina/contact

    These are pages of ONE deliverable, not three separate ones. We therefore
    collapse every written ``page.tsx`` to its root slug and register a single
    card whose ``preview_url`` is the root entry (``/artifacts/<slug>``). The
    root ``page.tsx`` is preferred as the representative source path when it is
    among the written files.
    """
    roots: dict[str, str] = {}
    order: list[str] = []
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
        is_root_page = not (match.group(2) or "").strip("/")
        if root_slug not in roots:
            order.append(root_slug)
            roots[root_slug] = normalized_path
        elif is_root_page:
            # Prefer the root page.tsx as the representative source path.
            roots[root_slug] = normalized_path
    return [(slug, f"/artifacts/{slug}", roots[slug]) for slug in order]


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


def schedule_artifact_alias_deploy_from_written_paths(written_file_paths: Iterable[str]) -> None:
    """Schedule the provisional publish for any artifact root touched by writes.

    The moment an artifact is registered it should be publicly viewable at
    ``<host>/preview/<slug>``. We achieve that by committing the artifact to the
    production branch (``main``) so Vercel builds and serves it — see
    ``app.services.artifact_git_publish``.

    Historically this assigned a ``<slug>-done.vercel.app`` Vercel alias. That
    alias path is retired (RULES.md): it created a second URL that pinned to a
    stale deployment and 404'd. The clean single URL is ``/preview/<slug>``.
    The function name is kept so existing callers (chat routes, registration)
    keep working without changes.
    """
    from app.services.artifact_git_publish import schedule_artifact_git_publish

    schedule_artifact_git_publish(artifact_slugs_from_written_paths(written_file_paths))


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
