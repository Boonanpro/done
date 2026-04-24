"""
Shadcn 自動追加 hook (PostToolUse)

Claude Code が .tsx ファイルを Write / Edit した後、
`@/components/ui/<name>` 形式の import を検出して、
`frontend/src/components/ui/<name>.tsx` が無ければ自動で `npx shadcn@latest add <name>` を実行する。

これによって「Module not found: @/components/ui/select」のような
Next.js dev server の build-error フリーズを未然に防ぐ。

stdin から JSON: { "tool_input": { "file_path": "..." } }
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(r"D:/done")
FRONTEND_DIR = PROJECT_ROOT / "frontend"
UI_DIR = FRONTEND_DIR / "src" / "components" / "ui"

# @/components/ui/<name> を拾う。name は英小文字 + ハイフン。
IMPORT_RE = re.compile(r"""['"]@/components/ui/([a-z][a-z0-9-]*)['"]""")

# 明示的に shadcn registry に存在することが確認できている名前だけ追加する
# (未知の名前で `npx shadcn add` を叩くと対話待ちで hang する恐れがある)
KNOWN_SHADCN = {
    "accordion", "alert", "alert-dialog", "aspect-ratio", "avatar", "badge",
    "breadcrumb", "button", "calendar", "card", "carousel", "chart", "checkbox",
    "collapsible", "command", "context-menu", "dialog", "drawer", "dropdown-menu",
    "form", "hover-card", "input", "input-otp", "label", "menubar",
    "navigation-menu", "pagination", "popover", "progress", "radio-group",
    "resizable", "scroll-area", "select", "separator", "sheet", "sidebar",
    "skeleton", "slider", "sonner", "switch", "table", "tabs", "textarea",
    "toast", "toggle", "toggle-group", "tooltip",
}


def extract_ui_imports(text: str) -> set[str]:
    return {m.group(1) for m in IMPORT_RE.finditer(text)}


def installed_components() -> set[str]:
    if not UI_DIR.exists():
        return set()
    return {p.stem for p in UI_DIR.glob("*.tsx")}


def install(name: str) -> tuple[bool, str]:
    """npx shadcn@latest add <name> を非対話で実行する。"""
    try:
        proc = subprocess.run(
            ["npx", "shadcn@latest", "add", name, "--yes"],
            cwd=str(FRONTEND_DIR),
            capture_output=True,
            text=True,
            timeout=180,
            shell=True,  # Windows + npx.cmd 対策
        )
    except subprocess.TimeoutExpired:
        return False, f"timeout installing {name}"
    except Exception as e:
        return False, f"install error: {e}"

    if proc.returncode == 0:
        return True, proc.stdout[-400:]
    return False, (proc.stderr or proc.stdout)[-400:]


def main() -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path or not file_path.endswith((".tsx", ".ts")):
        return 0

    # フロントエンド外のファイルはスキップ
    try:
        Path(file_path).resolve().relative_to(FRONTEND_DIR.resolve())
    except ValueError:
        return 0

    # 書き込み後の内容を読む
    p = Path(file_path)
    if not p.exists():
        return 0
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return 0

    wanted = extract_ui_imports(text)
    if not wanted:
        return 0

    have = installed_components()
    missing = [n for n in wanted if n not in have and n in KNOWN_SHADCN]
    if not missing:
        return 0

    installed, failed = [], []
    for name in missing:
        ok, msg = install(name)
        if ok:
            installed.append(name)
        else:
            failed.append((name, msg))

    parts = []
    if installed:
        parts.append(f"[shadcn auto-install] added: {', '.join(installed)}")
    if failed:
        parts.append("[shadcn auto-install] failed:")
        for name, msg in failed:
            parts.append(f"  - {name}: {msg[:200]}")
    if parts:
        # stderr に出すと Claude Code の PostToolUse で表示される
        sys.stderr.write("\n".join(parts) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
