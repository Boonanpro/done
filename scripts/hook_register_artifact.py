"""
Artifact 自動登録 hook (PostToolUse: Write / Edit / Bash)

ダンが `frontend/src/app/artifacts/{slug}/page.tsx` または
`frontend/src/app/demo/{slug}/page.tsx` を書いた時、そのパスを dan-core の
登録 API に渡す。登録も公開も core の中の 1 つの関数が行う（登録＝公開保証）。

この hook 自身は DB を触らず、公開も走らせない。hook はツール呼び出しごとに
終了する使い捨てプロセスなので、ここで裏方スレッドを起こしても終了と同時に消える
（2026-09-05 pornblocker-roadmap: 登録だけ残り公開されず 404 になった実例）。

Write/Edit は tool_input.file_path、Bash は command 文中のパスを拾うので、
ヒアドキュメントや cp で作った page.tsx も同じ経路で登録される。
DAN_ROOM_ID / DAN_PROJECT_ID 環境変数が無ければ何もしない。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0

    try:
        from app.services.chat_artifact_registration import (
            ARTIFACT_PAGE_RE,
            request_registration_via_core,
            written_paths_from_tool,
        )
    except Exception as e:  # noqa: BLE001 - a hook must never break the tool call
        sys.stderr.write(f"[artifact auto-register] unavailable: {e}\n")
        return 0

    paths = written_paths_from_tool(data.get("tool_name", ""), data.get("tool_input", {}))
    if not paths:
        return 0

    # 成果物 (artifacts のみ。demo は除外) は favicon と Tailwind の @source を配線する。
    # ルート slug 単位 (例 kittoku-careers でも kittoku の layout/icon を整える)。
    root_slugs = {m.group(1) for m in (ARTIFACT_PAGE_RE.search(p.replace("\\", "/")) for p in paths) if m}
    if root_slugs:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        try:
            from wire_artifact_icons import wire_slug

            for root_slug in sorted(root_slugs):
                sys.stderr.write(f"[artifact icon] {root_slug} -> {wire_slug(root_slug)}\n")
        except Exception as e:
            sys.stderr.write(f"[artifact icon] failed: {e}\n")
        try:
            from wire_artifact_tailwind_sources import wire as wire_tw_sources

            sys.stderr.write(f"[artifact tailwind sources] {wire_tw_sources()}\n")
        except Exception as e:
            sys.stderr.write(f"[artifact tailwind sources] failed: {e}\n")

    room_id = os.environ.get("DAN_ROOM_ID") or os.environ.get("DAN_SESSION_ID")
    project_id = os.environ.get("DAN_PROJECT_ID")
    if not room_id or not project_id:
        return 0

    reply = request_registration_via_core(paths, room_id, project_id)
    if reply is None:
        sys.stderr.write("[artifact auto-register] dan-core unreachable; the turn-end pass will register\n")
    else:
        sys.stderr.write(f"[artifact auto-register] created={reply.get('created')} paths={paths}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
