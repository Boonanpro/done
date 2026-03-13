"""
Shared bootstrap context loader for active runtimes.

This module is intentionally independent from v2 runner implementation so
CLI/Gemini paths can evolve without importing legacy runner code.
"""

from __future__ import annotations

from pathlib import Path

# Core prompt used by active runtimes.
CORE_PROMPT = "You are Dan, a personal AI assistant."

# Workspace bootstrap root.
WORKSPACE_DIR = Path.home() / ".dan" / "workspace"


def get_core_prompt() -> str:
    """Return immutable core prompt."""
    return CORE_PROMPT


def load_bootstrap_file(filename: str) -> str:
    """Load one bootstrap file from ~/.dan/workspace."""
    filepath = WORKSPACE_DIR / filename
    if filepath.exists():
        try:
            return filepath.read_text(encoding="utf-8")
        except Exception:
            return ""
    return ""


def load_all_bootstrap_files() -> str:
    """
    Load bootstrap context in deterministic order.

    Order (important):
    1. USER.md
    2. SOUL.md
    3. RULES.md (placed last for recency)

    MEMORY.md is NOT injected into system prompt (too large, dilutes built-in instructions).
    Dan can read ~/.dan/workspace/MEMORY.md on demand via read_file.
    """
    parts = []

    user = load_bootstrap_file("USER.md")
    if user:
        parts.append(f"## ユーザー情報\n\n{user}")

    # MEMORY.md: on-demand only. Read via read_file when needed.

    soul = load_bootstrap_file("SOUL.md")
    if soul:
        parts.append(f"## ペルソナ\n\n{soul}")

    rules = load_bootstrap_file("RULES.md")
    if rules:
        parts.append(rules)

    if parts:
        return "\n\n---\n\n".join(parts)
    return ""


def load_active_plan(project_id: str | None = None) -> str:
    """Load approved plan for a specific project from DB.

    Returns formatted plan text, or empty string if no approved plan exists.
    If project_id is None, returns empty string (no global plan injection).
    """
    if not project_id:
        return ""

    try:
        from app.services.supabase_client import get_supabase_client
        supabase = get_supabase_client().client
        result = (
            supabase.table("project_proposals")
            .select("content, steps, status")
            .eq("project_id", project_id)
            .eq("status", "approved")
            .order("approved_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return ""

        proposal = result.data[0]
        steps = proposal.get("steps") or []
        content = proposal.get("content") or ""

        lines = [
            "## 承認済み計画",
            "",
            "以下はユーザーと合意済みの計画です。この計画に従って作業してください。",
            "計画から逸脱する必要がある場合は、必ず理由を説明してユーザーの承認を得てください。",
            "",
        ]

        if steps:
            for step in steps:
                num = step.get("step_number", "?")
                desc = step.get("description", step.get("title", ""))
                status = step.get("status", "pending")
                icon = "✅" if status == "completed" else "⬜"
                lines.append(f"- {icon} Step {num}: {desc}")
        elif content:
            lines.append(content[:2000])

        return "\n".join(lines)
    except Exception:
        return ""

