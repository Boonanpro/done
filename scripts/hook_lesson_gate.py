# -*- coding: utf-8 -*-
"""PreToolUse(Write|Edit|MultiEdit) hook: みきさんの指摘は、台帳を通してからでないと記憶や決まりに書けない。

2026-10-25 本人:「足す前に、まとめられないか探して汎化させるのは超大事」。ダンは指摘を受けるたびに
記憶の feedback を1件足していて、同じ根っこの指摘が別々の記憶に積み上がり、同じ発言が2つの記憶に
入っている物もあった。スキルの文章には hook_skill_gate.py の関所があるが、記憶と決まりごとの文書には
何も無かった。

対象（今回書き足す中身で見る。Edit でもファイルの今の中身を読み直して判定する）:
  - ~/.dan/workspace/memory/ の feedback*.md と、ヘッダーか書く中身に「type: feedback」がある記憶
  - 決まりごとの文書（RULES.md、USER.md、SOUL.md、dev-lead/PATROL.md、dev-lead/ROOM.md、
    dan-workspace/CLAUDE.md、~/.claude/CLAUDE.md）に、本人の言葉（本人「…」など）を書き足す時
消すだけの直しと、シェル経由の書き込みは対象外（スキルの関所と同じ）。

通す条件: 今回書き足す中身に、前の中身に無かった発言の印「(lessons:S110)」があり、その発言が
  - 台帳にあって、出どころがこのファイルで、決まりにした（status=rule）根っこに付いていて、
  - 同じ作業の記録に「[lessons] find」（同じ根っこを探した）と「[lessons] added id=S110」が出ている。
  指摘ではない直しは「[lessons] touch id=T…」1つで1回だけ通す（関所が使った印を台帳に付ける）。
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
import lessons  # noqa: E402

LESSONS = (Path(__file__).resolve().parent / "lessons.py").as_posix()
RULE_DOCS = {"RULES.md", "USER.md", "SOUL.md", "dev-lead/PATROL.md", "dev-lead/ROOM.md",
             "dan-workspace/CLAUDE.md", ".claude/CLAUDE.md"}
OWNER_WORDS = re.compile(r"(本人|みきさん|持ち主)[^。\n]{0,24}?[「『]")
FEEDBACK_TYPE = re.compile(r"^\s*type:\s*feedback\b", re.M)


def _old_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def added_text(tool_input: dict, old: str) -> str:
    """今回の書き込みで新しく入る行だけ（前の中身や、置き換える前の文に無かった行）。"""
    pairs = []
    if "content" in tool_input or "text" in tool_input:
        pairs.append((old, tool_input.get("content") if "content" in tool_input else tool_input.get("text")))
    if "new_string" in tool_input:
        pairs.append((tool_input.get("old_string") or "", tool_input.get("new_string") or ""))
    for e in tool_input.get("edits") or []:
        pairs.append((e.get("old_string") or "", e.get("new_string") or ""))
    out = []
    for before, after in pairs:
        seen = {l.strip() for l in (before or "").splitlines()}
        out += [l for l in (after or "").splitlines() if l.strip() and l.strip() not in seen]
    return "\n".join(out)


def target(key: str, old: str, new: str) -> bool:
    name = key.rsplit("/", 1)[-1]
    if key.startswith("memory/") and name.endswith(".md") and name != "MEMORY.md":
        return bool(new) and (name.startswith("feedback") or bool(FEEDBACK_TYPE.search(old)) or bool(FEEDBACK_TYPE.search(new)))
    return key in RULE_DOCS and bool(OWNER_WORDS.search(new))


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
    path = os.path.expanduser(tool_input.get("file_path") or tool_input.get("path") or "")
    if not path:
        return 0
    key = lessons.norm_src(path)
    old = _old_text(path)
    new = added_text(tool_input, old)
    if not target(key, old, new):
        return 0
    results, _ = _read_transcript(payload.get("transcript_path") or "")
    ids = [i for i in dict.fromkeys(lessons.REF.findall(new)) if f"lessons:{i}" not in old]

    if not ids:
        for tid in re.findall(r"\[lessons\] touch id=(T\d+) src=" + re.escape(key) + r"(?:\s|$)", results):
            if lessons.use_touch(tid, key):
                return 0
        _block(
            f"{key} に書き足す中身に、台帳の発言の印がありません。みきさんの指摘を書く前に、"
            f"指摘の台帳（{lessons.LEDGER.as_posix()}）を通してください。\n"
            "足す前に同じ根っこの指摘と点検を探し、あればそちらに足します。機械で止められる物は、文章より点検を直します。\n"
            f'1. 同じ根っこを探す: python {LESSONS} find "<指摘の要点>"\n'
            f'2. 台帳に書く: python {LESSONS} add --root <近い根っこの id> --quote "<元の言葉>" --saw "<何を見て言われたか>" '
            f'--where "<どこで>" --src {key}\n'
            f'   近い根っこが無い時だけ: --new-root "<一般則>" --kind machine|skill|owner --why-new "<近い根っこに入らない理由>"\n'
            "3. 返ってきた発言の id を、書く所に (lessons:S…) の形で入れて書き直す。\n"
            f'指摘ではない直し（言い回しの整理など）なら: python {LESSONS} touch --src {key} --why "<理由>"（1回の書き込みだけ通ります）'
        )
    try:
        st = lessons.statements(lessons.load())
        linked = {i for r in lessons.load()["roots"] for i in r["statements"]}
    except Exception:  # noqa: BLE001
        _block(f"指摘の台帳 {lessons.LEDGER.as_posix()} を読めなかったため止めました。")
    problems = []
    if "[lessons] find" not in results:
        problems.append(f'同じ根っこを探していません: python {LESSONS} find "<指摘の要点>"')
    for i in ids:
        s = st.get(i)
        if s is None:
            problems.append(f"{i} は台帳にありません。")
        elif s["src"] != key:
            problems.append(f"{i} の出どころは {s['src']} で、このファイル（{key}）ではありません。")
        elif s["status"] == "unsure":
            problems.append(f"{i} は確かめたい物です。決まりにせず、みきさんに確かめてください: {s.get('question', '')}")
        elif s["status"] != "rule" or i not in linked:
            problems.append(f"{i} はどの根っこにも付いていません。")
        elif not re.search(r"\[lessons\] added id=" + i + r" ", results):
            problems.append(f"{i} を、この作業で台帳に書いていません（要約の後なら add をもう一度。同じ発言は二重には入りません）。")
    if problems:
        _block(f"{key} に書く前に直してください。\n" + "\n".join(f"- {p}" for p in problems))
    return 0


if __name__ == "__main__":
    sys.exit(main())
