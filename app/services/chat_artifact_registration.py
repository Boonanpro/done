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

# Shell tools can create page.tsx just as well as the write tools (heredoc,
# cp, generator scripts).  Their command text is scanned for artifact pages so
# the registration path does not depend on which tool wrote the file.
SHELL_TOOL_NAMES = {"Bash", "bash", "run_command", "mcp__dan-tools__run_command"}
ARTIFACT_PAGE_IN_TEXT_RE = re.compile(
    r"frontend[/\\]src[/\\]app[/\\](?:artifacts|demo)[/\\][\w-]+(?:[/\\][\w./-]*?)?[/\\]page\.tsx"
)
WRITE_TOOL_NAMES = {
    "write_file",
    "edit_file",
    "Write",
    "Edit",
    "MultiEdit",
    "mcp__dan-tools__write_file",
    # edit_file は MCP 経由だとこの名前でイベントに乗る。ここに無かったせいで
    # 「既存成果物の編集→専用デプロイ再実行」が発火しない実事故が起きた（2026-08-31）。
    "mcp__dan-tools__edit_file",
}

ARTIFACT_PAGE_RE = re.compile(
    r"frontend[/\\]src[/\\]app[/\\]artifacts[/\\]([\w-]+)(?:[/\\]([^:]*?))?[/\\]page\.tsx$"
)
ARTIFACT_SLUG_RE = re.compile(r"frontend[/\\]src[/\\]app[/\\]artifacts[/\\]([\w-]+)[/\\]")


def written_paths_from_tool(tool_name: str, tool_input: object) -> list[str]:
    """Return artifact-relevant paths written by one tool event.

    Write/Edit tools report the path directly.  Shell tools are scanned for
    artifact page paths mentioned in the command so a heredoc-written page is
    registered exactly like a Write-tool page.
    """
    if not isinstance(tool_input, dict):
        return []
    if tool_name in WRITE_TOOL_NAMES:
        value = tool_input.get("path") or tool_input.get("file_path")
        return [value] if isinstance(value, str) and value.strip() else []
    if tool_name in SHELL_TOOL_NAMES:
        command = tool_input.get("command")
        if not isinstance(command, str):
            return []
        # The command may cd into the artifact directory first; resolve the
        # page against it so a bare ``cat > page.tsx`` is attributed correctly.
        found = ARTIFACT_PAGE_IN_TEXT_RE.findall(command)
        if not found and re.search(r"(^|[\s;&|])cat\s*>\s*page\.tsx", command):
            cd = re.search(r"cd\s+(\S*frontend[/\\]src[/\\]app[/\\](?:artifacts|demo)[/\\][\w-]+(?:[/\\][\w-]+)*)", command)
            if cd:
                found = [cd.group(1).rstrip("/\\") + "/page.tsx"]
        return list(dict.fromkeys(found))
    return []


def written_path_from_tool(tool_name: str, tool_input: object) -> Optional[str]:
    """Compatibility wrapper: first path from ``written_paths_from_tool``."""
    paths = written_paths_from_tool(tool_name, tool_input)
    return paths[0] if paths else None


def add_written_path(paths: list[str], path: Optional[str]) -> None:
    """Append a path once, preserving first-seen order."""
    if path and path not in paths:
        paths.append(path)


def request_registration_via_core(
    written_file_paths: Iterable[str],
    room_id: Optional[str],
    project_id: Optional[str],
    *,
    timeout: float = 15.0,
) -> Optional[dict]:
    """Ask dan-core to register (and publish) artifacts for these paths.

    Short-lived processes (Claude Code hooks, CLI helper scripts) must not run
    the publication themselves: a daemon thread dies with its process.  Every
    such caller hands the paths to the core, where the one registration
    function runs inside the process that never restarts.
    Returns the core's JSON reply, or None when the core is unreachable.
    """
    import json
    import os
    import urllib.request

    paths = [p for p in written_file_paths if p]
    if not (paths and room_id and project_id):
        return None
    port = os.environ.get("DAN_CORE_PORT", "9000")
    body = json.dumps(
        {"room_id": room_id, "project_id": project_id, "written_paths": paths}
    ).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/v1/chat/internal/artifacts/register",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except Exception as exc:  # noqa: BLE001 - the caller reports, never crashes
        logger.warning("artifact registration via core failed: %s", exc)
        return None


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


def schedule_artifact_delivery(artifacts: Iterable[dict], user_id: str) -> None:
    """Send newly registered artifacts to their own Vercel delivery projects.

    There is intentionally no shared repository, shared Vercel project, or
    alias rewrite in this path. A publish for site A cannot alter site B.
    """
    from app.services.artifact_publication_service import schedule_dedicated_deploy

    for artifact in artifacts:
        artifact_id = str(artifact.get("id") or "")
        if artifact_id:
            schedule_dedicated_deploy(artifact_id, user_id)


def _page_exists(preview_url: str) -> bool:
    route_parts = preview_url.strip("/").split("/")
    page_path = PROJECT_ROOT / "frontend" / "src" / "app" / Path(*route_parts) / "page.tsx"
    return page_path.exists()


def _existing_artifact(service: ChatArtifactService, room_id: str, preview_url: str) -> Optional[dict]:
    """Return the artifact card already registered for this route, if any."""
    existing = (
        service.supabase.table("chat_artifact")
        .select("id")
        .eq("room_id", room_id)
        .eq("preview_url", preview_url)
        .limit(1)
        .execute()
    )
    return existing.data[0] if existing.data else None


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
        "publish_status": "created",
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
    touched: list[dict] = []
    seen: set[str] = set()

    for slug, preview_url, source_path in artifact_candidates_from_written_paths(written_paths):
        if slug in seen:
            continue
        seen.add(slug)
        try:
            if not _page_exists(preview_url):
                logger.info("Skipping chat artifact registration for %s: page.tsx not found", slug)
                continue
            existing = _existing_artifact(service, room_id, preview_url)
            if existing:
                # A rewrite of an already-registered site still has to reach its
                # dedicated delivery project, otherwise the public URL keeps
                # serving the previous build.
                touched.append(existing)
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

    schedule_artifact_delivery(created + touched, user_id)
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
    touched: list[dict] = []
    seen: set[str] = set()

    for slug, preview_url, source_path in artifact_candidates_from_written_paths(written_paths):
        if slug in seen:
            continue
        seen.add(slug)
        try:
            if not _page_exists(preview_url):
                logger.info("Skipping chat artifact registration for %s: page.tsx not found", slug)
                continue
            existing = _existing_artifact(service, room_id, preview_url)
            if existing:
                # A rewrite of an already-registered site still has to reach its
                # dedicated delivery project, otherwise the public URL keeps
                # serving the previous build.
                touched.append(existing)
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

    schedule_artifact_delivery(created + touched, user_id)
    return created
