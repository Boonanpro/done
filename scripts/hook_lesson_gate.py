# -*- coding: utf-8 -*-
"""PreToolUse(Write|Edit|MultiEdit) hook: みきさんの指摘は、台帳を通してからでないと記憶や決まりに書けない。

2026-10-25 本人:「足す前に、まとめられないか探して汎化させるのは超大事」。ダンは指摘を受けるたびに
記憶の feedback を1件足していて、同じ根っこの指摘が別々の記憶に積み上がり、同じ発言が2つの記憶に
入っている物もあった。スキルの文章には hook_skill_gate.py の関所があるが、記憶と決まりごとの文書には
何も無かった。

対象:
  - ~/.dan/workspace/memory/ の feedback*.md と、書く中身に「type: feedback」がある記憶
  - 決まりごとの文書（RULES.md、USER.md、SOUL.md、dev-lead/PATROL.md、dev-lead/ROOM.md、
    dan-workspace/CLAUDE.md、~/.claude/CLAUDE.md）に、本人の言葉（本人「…」など）を書き足す時
シェル経由の書き込みは対象外（スキルの関所と同じ）。

通す条件: 同じ作業の記録（transcript_path）の道具の結果に、scripts/lessons.py の
  「[lessons] find」（同じ根っこを探した）と「[lessons] added … src=<このファイル>」（台帳に書いた）、
  または「[lessons] touch src=<このファイル>」（指摘ではない直し）が出ている。
要約(compact)の後は、要約の後に出た物だけ数える（読み方は hook_skill_gate と同じ）。
exit 0 = 許可 / exit 2 = ブロック（stderr がモデルへの返事になる）。
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_skill_gate import _read_transcript  # noqa: E402
from lessons import WORKSPACE, norm_src  # noqa: E402

LESSONS = (Path(__file__).resolve().parent / "lessons.py").as_posix()
RULE_DOCS = {"RULES.md", "USER.md", "SOUL.md", "dev-lead/PATROL.md", "dev-lead/ROOM.md",
             "dan-workspace/CLAUDE.md", ".claude/CLAUDE.md"}
OWNER_WORDS = re.compile(r"(本人|みきさん|持ち主)[^。\n]{0,24}?[「『]")


def _new_text(tool_input: dict) -> str:
    parts = [tool_input.get(k) or "" for k in ("content", "new_string", "text", "new_text")]
    for e in tool_input.get("edits") or []:
        parts.append(e.get("new_string") or "")
    return "\n".join(parts)


def target(path: str, tool_input: dict) -> str | None:
    """関所の対象なら台帳の書き方の出どころ（memory/<名前> など）を返す。"""
    key = norm_src(path)
    name = key.rsplit("/", 1)[-1]
    if key.startswith("memory/") and name.endswith(".md") and name != "MEMORY.md":
        if name.startswith("feedback") or re.search(r"^\s*type:\s*feedback\b", _new_text(tool_input), re.M):
            return key
        return None
    if key in RULE_DOCS and OWNER_WORDS.search(_new_text(tool_input)):
        return key
    return None


def _block(msg: str) -> None:
    sys.stderr.buffer.write(("[指摘の関所] " + msg).encode("utf-8"))
    sys.stderr.flush()
    sys.exit(2)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:  # noqa: BLE001
        return 0
    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("path") or ""
    if not path:
        return 0
    key = target(os.path.expanduser(path), tool_input)
    if not key:
        return 0
    results, _ = _read_transcript(payload.get("transcript_path") or "")
    if f"[lessons] touch src={key}" in results:
        return 0
    found = "[lessons] find" in results
    added = re.search(r"\[lessons\] added id=\S+ root=\S+ src=" + re.escape(key) + r"(\s|$)", results)
    if found and added:
        return 0
    steps = []
    if not found:
        steps.append(f'1. 同じ根っこを探す: python {LESSONS} find "<指摘の要点>"')
    if not added:
        steps.append(
            f"2. 台帳に書く（出どころはこのファイル）: python {LESSONS} add --root <近い根っこの id> "
            f'--quote "<元の言葉>" --saw "<何を見て言われたか>" --where "<どこで>" --src {key}\n'
            f'   近い根っこが無い時だけ: --new-root "<一般則>" --kind machine|skill|owner|spec --why-new "<近い根っこに入らない理由>"\n'
            f'   指摘ではない直し（言い回しの整理など）なら: python {LESSONS} touch --src {key} --why "<理由>"'
        )
    _block(
        f"{key} にみきさんの指摘を書く前に、指摘の台帳（{WORKSPACE.as_posix()}/lessons/ledger.json）を通してください。\n"
        "足す前に同じ根っこの指摘と点検を探し、あればそちらに足します。機械で止められる物は、文章より点検を広げます。\n"
        + "\n".join(steps)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
