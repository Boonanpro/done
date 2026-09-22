"""Backend parity: what Claude Code reads for free, Dan hands to every other backend.

Claude Code silently loads several things at session start or on demand:

* the project's ``CLAUDE.md`` files (``D:/done/CLAUDE.md`` when it touches D:/done)
* its auto-memory index (``MEMORY.md``, first 200 lines / 25KB)
* hooks from ``.claude/settings.json``

Codex (and any future backend) sees none of that. This module is the single
place that enumerates those sources so a non-Claude backend gets the same
knowledge through Dan's own system prompt / profile instead of relying on a
CLI-specific auto-load. Hooks are bridged by ``scripts/codex_hook_bridge.py``.

Memory lives in ``~/.dan/workspace/memory/`` (``MEMORY.md`` index + topic
files). Claude Code writes there too via ``autoMemoryDirectory`` in
``D:/dan-workspace/.claude/settings.json``, so both backends share one memory.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

WORKSPACE_DIR = Path(os.environ.get("DAN_WORKSPACE_DIR") or (Path.home() / ".dan" / "workspace"))
MEMORY_DIR = WORKSPACE_DIR / "memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"

# Same limits Claude Code applies to its auto-memory index.
MEMORY_INDEX_MAX_LINES = 200
MEMORY_INDEX_MAX_BYTES = 25 * 1024

# Native Dan instructions; legacy environment overrides remain supported.
_DEFAULT_PARITY_DOCS = str(Path(__file__).resolve().parents[2] / "AGENTS.md")

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def parity_doc_paths() -> list[Path]:
    raw = os.environ.get("DAN_PARITY_DOCS", _DEFAULT_PARITY_DOCS)
    return [Path(p.strip()) for p in raw.split(";") if p.strip()]


def load_memory_index() -> str:
    """The memory index as Claude Code would see it (first 200 lines / 25KB)."""
    if not MEMORY_INDEX.exists():
        return ""
    try:
        text = MEMORY_INDEX.read_text(encoding="utf-8")
    except OSError:
        return ""
    lines = text.splitlines()
    if len(lines) > MEMORY_INDEX_MAX_LINES:
        lines = lines[:MEMORY_INDEX_MAX_LINES]
    out = "\n".join(lines)
    if len(out.encode("utf-8")) > MEMORY_INDEX_MAX_BYTES:
        out = out.encode("utf-8")[:MEMORY_INDEX_MAX_BYTES].decode("utf-8", errors="ignore")
    return out.strip()


def load_parity_docs() -> list[tuple[Path, str]]:
    docs = []
    for p in parity_doc_paths():
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        # Claude strips block HTML comments (maintainer notes) before injection.
        text = _HTML_COMMENT_RE.sub("", text).strip()
        if text:
            docs.append((p, text))
    return docs


def parity_static(backend: str) -> str:
    """Rarely-changing project context. Goes into the backend's
    per-thread instructions; a change rotates the thread (see codex_runner)."""
    if backend == "claude":
        return ""
    parts: list[str] = []
    for path, text in load_parity_docs():
        parts.append(
            f"## コードベース規律（{path.as_posix()}）\n\n"
            "ダン自身のコード・成果物・公開の扱いに関する規律。\n\n"
            f"{text}"
        )
    return "\n\n---\n\n".join(parts)


def parity_dynamic(backend: str) -> str:
    """Per-turn context (memory index). Delivered with every user message so a
    long-lived thread always sees the current memory."""
    if backend == "claude":
        return ""
    mem = load_memory_index()
    if not mem:
        return ""
    return (
        "## 長期記憶（索引）\n\n"
        f"以下は `{MEMORY_INDEX.as_posix()}` の索引。各行の詳細は同じフォルダの"
        "リンク先ファイルを read_file で読め。新しい学び（ユーザーの好み・訂正・"
        "プロジェクトの事実）はこのフォルダに1件1ファイルで保存し、索引に1行追加しろ。\n\n"
        f"{mem}"
    )


def parity_context(backend: str) -> str:
    """Extra context for a non-Claude backend (static + dynamic). Empty for
    Claude (it already loads these itself; injecting again would duplicate)."""
    parts = [p for p in (parity_dynamic(backend), parity_static(backend)) if p]
    return "\n\n---\n\n".join(parts)


def static_fingerprint(*texts: str) -> str:
    """Short hash of the instruction pieces that are frozen per thread."""
    import hashlib

    h = hashlib.sha1()
    for t in texts:
        h.update((t or "").encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:10]


def iter_claude_hook_scripts(settings_path: Path) -> Iterable[tuple[str, str, str]]:
    """Yield (event, matcher, command) from a Claude Code settings.json."""
    import json

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    for event, groups in (data.get("hooks") or {}).items():
        for group in groups or []:
            matcher = group.get("matcher") or ""
            for hook in group.get("hooks") or []:
                if hook.get("type", "command") == "command" and hook.get("command"):
                    yield event, matcher, hook["command"]
