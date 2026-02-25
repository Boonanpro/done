"""
Shared bootstrap context loader for active runtimes.

This module is intentionally independent from v2 runner implementation so
CLI/Gemini paths can evolve without importing legacy runner code.
"""

from __future__ import annotations

from datetime import datetime, timedelta
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
    2. MEMORY.md
    3. recent daily memory (yesterday, today)
    4. SOUL.md
    5. RULES.md (placed last for recency)
    """
    parts = []

    user = load_bootstrap_file("USER.md")
    if user:
        parts.append(f"## ユーザー情報\n\n{user}")

    memory = load_bootstrap_file("MEMORY.md")
    if memory:
        parts.append(f"## 長期記憶\n\n{memory}")

    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    for date_str in [yesterday, today]:
        daily = load_bootstrap_file(f"memory/{date_str}.md")
        if daily:
            if len(daily) > 4000:
                daily = daily[-4000:]
            parts.append(f"## 会話ログ ({date_str})\n\n{daily}")

    soul = load_bootstrap_file("SOUL.md")
    if soul:
        parts.append(f"## ペルソナ\n\n{soul}")

    rules = load_bootstrap_file("RULES.md")
    if rules:
        parts.append(rules)

    if parts:
        return "\n\n---\n\n".join(parts)
    return ""

