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


def _extract_artifact_label(md_file: Path) -> str:
    """Best-effort one-line label for an artifact file.

    Skips YAML frontmatter, prefers the first markdown heading, falls
    back to the first non-preamble line, then to the filename stem.
    """
    in_frontmatter = False
    seen_first_line = False
    first_heading = ""
    first_body = ""
    with md_file.open(encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not seen_first_line:
                seen_first_line = True
                if s == "---":
                    in_frontmatter = True
                    continue
            if in_frontmatter:
                if s == "---":
                    in_frontmatter = False
                continue
            if not s or s == "---":
                continue
            if s.startswith("#"):
                first_heading = s.lstrip("# ").strip()
                break
            if not first_body:
                first_body = s
    label = first_heading or first_body or md_file.stem
    return label[:120]


def load_artifact_descriptions(room_id: str = "") -> str:
    """Return a short index of artifact files (paths + titles only).

    The full content is intentionally NOT inlined into the system prompt:
    on Windows, the CLI command-line has a ~32K wide-char limit and
    inlining many artifacts pushes Popen over WinError 206. The agent
    should `read_file` each path on demand.
    """
    import re as _re

    if not room_id:
        return ""
    artifacts_dir = WORKSPACE_DIR / "artifacts" / room_id
    if not artifacts_dir.exists():
        return ""

    items = []
    for md_file in sorted(artifacts_dir.glob("*.md")):
        # Skip version backups (e.g., name.v1.md)
        if _re.match(r".*\.v\d+\.md$", md_file.name):
            continue
        try:
            label = _extract_artifact_label(md_file)
            items.append(f"- {label} — `{md_file}`")
        except Exception:
            continue

    if not items:
        return ""

    return (
        "## 承認済み成果物（参照のみ）\n\n"
        "以下のパスに過去に作成された成果物の詳細記述があります。\n"
        "実装・改修の際は必ず `read_file` で該当ファイルを読み込んでから着手してください。\n\n"
        + "\n".join(items)
    )


def load_active_plan(room_id: str = "") -> str:
    """Return a short summary of the active plan (path + step list).

    The full plan content is intentionally NOT inlined into the system
    prompt to keep the Windows CLI command-line under the ~32K wide-char
    limit (WinError 206). The agent should `read_file` the path on demand
    when full context is needed.
    """
    import re as _re

    plans_dir = WORKSPACE_DIR / "plans"
    plan_path = None
    if room_id:
        room_plan = plans_dir / f"{room_id}.md"
        if room_plan.exists():
            plan_path = room_plan
    # Legacy fallback
    if plan_path is None:
        active_plan = plans_dir / "active.md"
        if active_plan.exists():
            plan_path = active_plan
    if plan_path is None:
        return ""

    try:
        content = plan_path.read_text(encoding="utf-8")
    except Exception:
        return ""
    if not content.strip():
        return ""

    # Match both formats: "- ✅/⬜ Step N: ..." and "- [x]/[ ] ..."
    step_lines = [
        line for line in content.splitlines()
        if _re.match(r"^\s*-\s*(?:[✅⬜]|\[[x ]\])", line)
    ]
    # Cap to keep the summary bounded — full file is one read_file away.
    if len(step_lines) > 30:
        step_lines = step_lines[:15] + [f"- … （他 {len(step_lines) - 30} 件は計画ファイル参照）"] + step_lines[-15:]

    title = _get_project_title(room_id) if room_id else ""

    parts = ["## 承認済み計画（概要）"]
    if title:
        parts.append(f"プロジェクト名: {title}")
    parts.append(f"計画ファイル: `{plan_path}`")
    parts.append(
        "この計画に従って作業してください。逸脱する必要がある場合は、"
        "必ず理由を説明してユーザーの承認を得てください。"
    )
    if step_lines:
        parts.append("")
        parts.extend(step_lines)
    parts.append("")
    parts.append("詳細な意図・補足は `read_file` で計画ファイルを読み込んで確認してください。")

    return "\n".join(parts)


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

