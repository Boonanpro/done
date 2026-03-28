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


def _get_project_title(room_id: str) -> str:
    """DBからプロジェクトタイトルを取得する。"""
    try:
        from app.services.supabase_client import get_supabase_client
        sb = get_supabase_client().client
        result = sb.table("projects").select("title").eq("room_id", room_id).limit(1).execute()
        if result.data:
            title = result.data[0].get("title", "")
            if title and title != "新しいプロジェクト":
                return title
    except Exception:
        pass
    return ""


def load_active_plan(room_id: str = "") -> str:
    """Load active plan if one exists. Returns empty string if none.

    If room_id is given, tries plans/{room_id}.md first.
    Falls back to plans/active.md for legacy compatibility.
    Project title is fetched from DB at load time (not stored in file).
    """
    plans_dir = WORKSPACE_DIR / "plans"
    content = ""
    if room_id:
        room_plan = plans_dir / f"{room_id}.md"
        if room_plan.exists():
            try:
                content = room_plan.read_text(encoding="utf-8")
            except Exception:
                pass
    # Legacy fallback
    if not content:
        active_plan = plans_dir / "active.md"
        if active_plan.exists():
            try:
                content = active_plan.read_text(encoding="utf-8")
            except Exception:
                return ""
    if not content:
        return ""
    # Inject current project title from DB
    if room_id:
        title = _get_project_title(room_id)
        if title:
            content = f"プロジェクト名: {title}\n\n{content}"
    return content


def save_active_plan(project_title: str, steps: list, content: str = "") -> None:
    """Save approved plan for system prompt injection."""
    plans_dir = WORKSPACE_DIR / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "## 承認済み計画",
        "",
        f"プロジェクト: {project_title}",
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

    (plans_dir / "active.md").write_text("\n".join(lines), encoding="utf-8")


def clear_active_plan() -> None:
    """Remove active plan."""
    plan_path = WORKSPACE_DIR / "plans" / "active.md"
    if plan_path.exists():
        plan_path.unlink()

