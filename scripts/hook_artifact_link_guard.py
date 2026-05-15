"""
Guard generated artifact links.

Dan artifacts live under frontend/src/app/artifacts/<slug>, but user-facing
navigation must not hard-code /artifacts/<slug> links. Use ArtifactLink, relative
links, or artifact path helpers so /preview/<slug> and custom-domain URLs keep
their visible path shape while browsing.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


ARTIFACT_FILE = re.compile(
    r"frontend[/\\]src[/\\]app[/\\]artifacts[/\\]([\w-]+)[/\\].+\.(tsx|ts|jsx|js)$"
)


def _read_payload() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}


def _file_path(payload: dict) -> str:
    return (payload.get("tool_input") or {}).get("file_path") or ""


def _is_allowed_file(path: Path) -> bool:
    normalized = str(path).replace("\\", "/")
    return normalized.endswith("/components/artifacts/artifact-link.tsx") or normalized.endswith(
        "/lib/artifact-paths.ts"
    )


def _violations(text: str, slug: str) -> list[str]:
    patterns = [
        (r"href\s*=\s*['\"]\/artifacts\/", "hard-coded Link href"),
        (r"href\s*=\s*\{`\/artifacts\/", "hard-coded template Link href"),
        (rf"['\"]\/artifacts\/{re.escape(slug)}(?:\/|['\"?#])", "hard-coded artifact URL"),
    ]
    found: list[str] = []
    for pattern, label in patterns:
        if re.search(pattern, text):
            found.append(label)
    return found


def main() -> int:
    payload = _read_payload()
    raw_path = _file_path(payload)
    if not raw_path:
        return 0

    normalized = raw_path.replace("\\", "/")
    match = ARTIFACT_FILE.search(normalized)
    if not match:
        return 0

    path = Path(raw_path)
    if _is_allowed_file(path):
        return 0
    if not path.exists():
        return 0

    slug = match.group(1)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="ignore")

    if "@/components/artifacts/artifact-link" in text:
        return 0

    violations = _violations(text, slug)
    if not violations:
        return 0

    reason = [
        f"Artifact link guard: {normalized} contains {', '.join(sorted(set(violations)))}.",
        "",
        "Generated artifacts must not hard-code /artifacts/<slug> for user navigation.",
        "Use one of these instead:",
        "  - import { ArtifactLink as Link } from '@/components/artifacts/artifact-link'",
        "  - relative URLs for simple same-artifact links",
        "  - artifactPreviewPath/artifactWorkspacePath from '@/lib/artifact-paths' for stored URLs",
        "",
        "This keeps /preview/<slug>, /artifacts/<slug>, and custom domains from mixing paths.",
    ]
    sys.stderr.write(os.linesep.join(reason) + os.linesep)
    return 2


if __name__ == "__main__":
    sys.exit(main())
