"""
demo path guard hook (PreToolUse: Write).

frontend/src/app/demo/<id>/ 配下への新規ファイル作成を、
そのディレクトリに manifest.json がある時だけ許可する。
"""
from __future__ import annotations

import json
import os
import sys


def _project_root():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def _check(file_path):
    rel = file_path.replace(os.sep, "/")
    parts = rel.split("/")
    try:
        i = parts.index("demo")
    except ValueError:
        return None
    if i < 3 or parts[i - 3:i] != ["frontend", "src", "app"]:
        return None
    if i + 1 >= len(parts):
        return None
    demo_id = parts[i + 1]
    if not demo_id:
        return None

    root = _project_root()
    demo_dir = os.path.join(root, "frontend", "src", "app", "demo", demo_id)
    manifest = os.path.join(demo_dir, "manifest.json")

    if os.path.exists(manifest):
        return None
    lines = [
        "/demo/{}/ への新規作成はブロックされました。".format(demo_id),
        "",
        "/demo は提案動画プロトタイプ専用パスです。",
        "用途別に正しい場所を選んでください:",
        "  - クライアント納品物 -> frontend/src/app/artifacts/<slug>/",
        "  - 試作・実験         -> frontend/src/app/scratch/<name>/",
        "  - 提案動画プロトタイプ -> 先に manifest.json を作成してから",
        "      ({})".format(manifest),
        "",
    ]
    return os.linesep.join(lines)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    fp = (payload.get("tool_input") or {}).get("file_path") or ""
    if not fp:
        return 0
    reason = _check(fp)
    if reason is None:
        return 0
    sys.stderr.write(reason)
    return 2


if __name__ == "__main__":
    sys.exit(main())
