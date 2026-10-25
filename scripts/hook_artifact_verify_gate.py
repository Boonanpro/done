# -*- coding: utf-8 -*-
"""Stop hook: 成果物を書き換えたら、本人の画面と裏側を確かめるまでターンを終えられない。

2026-10-18 本人: 「あなたが直して確認した画面と私が見る画面が一致し、『直した』と言われたものは
ちゃんと直っている。当たり前のことを当たり前にできるようにしてください」。ダンの確認（テスト用
アカウントのブラウザ・8001 の確認用サーバー）では直っていたのに、本人の画面では古い部品や
再起動待ちの裏側のまま動いていた、が何度も起きた。確かめ方（scripts/artifact_seen.py）は
手順書に書いてあったが、走らせずに報告できた。

止める条件:
  同じ作業の記録（transcript_path。Claude も Codex も渡す）で、動いているダン（D:/done）の
  frontend/src/app/artifacts/<slug>/ を書き換えた後に、その slug（または全部）の artifact_seen.py の
  結果「[artifact_seen] slug=… result=…」が道具の出力に出ていない。
  書き換えは Write/Edit/MultiEdit、Codex の apply_patch、シェルの書き込み（> ・write_text・sed -i・
  cp/mv など）を数える。シェルは見分けが粗いので、読むだけのコマンドでも書き込みの印があれば数える
  （確かめを1回走らせれば通る）。
このターンで確かめた結果が NG（作り直しや読み直しの途中）の時は、一度だけ止めて、待ってから確かめ直させる。
UNCHECKED（本人が開いていない）は止めない（開けば新しい版に切り替わる）。

確かめた結果は本人への返事に書かせない（2026-10-25 本人: 「本人の画面を確かめた結果を足します。パソコンで開いている
顧客管理のタブは、もう新しい版に…」は「一切いらない」「内部的な話」）。止めるとその後に書いた文だけが本人に届く返事に
なる（Claude の result も Codex の最後の文もそう）ので、止める時は「確かめる前に書いた本人への答えを、そのまま全部
もう一度書いて終える」よう案内する。10-25 はこの案内が無く、答えが捨てられて確かめた結果の1段落だけが届いた。

同じ書き換えで止めるのは3回まで（.data/artifact_gate/ に数える）。それを超えたら通して記録だけ残す。
exit 0 = 通す / stdout に {"decision":"block","reason":…} = 続けさせる（Claude と Codex で同じ形）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = Path(os.environ.get("DAN_ARTIFACT_GATE_DIR") or (Path(__file__).resolve().parent.parent / ".data" / "artifact_gate"))
LIVE = os.environ.get("DAN_ARTIFACT_GATE_LIVE", Path(__file__).resolve().parent.parent.as_posix()).replace("\\", "/").rstrip("/").lower()
MAX_BLOCKS = 3
SEEN_CMD = os.environ.get("DAN_ARTIFACT_SEEN", (Path(__file__).resolve().parent.parent / "scripts/artifact_seen.py").as_posix())

_live_abs = re.escape(LIVE) + r"/frontend/src/app/artifacts/([\w-]+)"
_live_msys = "/" + re.escape(LIVE[0]) + re.escape(LIVE[2:]) + r"/frontend/src/app/artifacts/([\w-]+)" if re.match(r"^[a-z]:/", LIVE) else None
ABS_RE = re.compile(_live_abs + (("|" + _live_msys) if _live_msys else ""), re.I)
REL_RE = re.compile(r"(?:^|[\s'\"=(])frontend/src/app/artifacts/([\w-]+)", re.I)
MENTIONS_LIVE = re.compile(re.escape(LIVE) + (("|" + "/" + re.escape(LIVE[0]) + re.escape(LIVE[2:])) if _live_msys else ""), re.I)
WRITE_MARK = re.compile(
    r"(?<![<>0-9&])>{1,2}(?![>&=])|\bwrite_text\b|\bwrite_bytes\b|\.write\(|open\([^)]*['\"][wa]b?\+?['\"]|\bsed\s+-i\b|"
    r"\b(?:cp|mv|rm|rsync|tee|touch|install)\s|\bcopy(?:file|tree|2)?\(|\bshutil\.|\bSet-Content\b|\bAdd-Content\b|"
    r"\bOut-File\b|\bCopy-Item\b|\bMove-Item\b|\bRemove-Item\b|\bNew-Item\b|writeFileSync|\bunlink\(|\brename\(|"
    r"\bos\.replace\(|apply_patch|\*\*\* (?:Add|Update|Delete) File:", re.I)
SEEN_RE = re.compile(r"\[artifact_seen\] slug=([\w*-]+) result=(OK|NG|UNCHECKED)")
PATCH_FILE = re.compile(r"\*\*\* (?:Add|Update|Delete) File: (.+)")
# `cat > 先 <<'EOF' … EOF` / `tee 先 <<EOF`: 中身は「先」に書く文章で、中に成果物のパスが出ても成果物は書き換わらない
# （10/18 試験ファイルに書いた試験用のパスを成果物の書き換えと数えた）。中身だけ除き、書き込む先は残して判定する。
# python - <<EOF のようにコマンドへ渡す中身は、そのコードが成果物を書くことがあるので除かない。
DATA_HEREDOC = re.compile(r"(\b(?:cat|tee(?:\s+-a)?)\b[^\n]*?<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n)(.*?)(\n\2\b)", re.S)
EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "write_file", "edit_file"}
SHELL_TOOLS = {"Bash", "PowerShell", "bash", "exec", "shell", "local_shell", "exec_command"}


def norm(p: str) -> str:
    return (p or "").replace("\\\\", "/").replace("\\", "/")


def slugs_in_path(path: str) -> set[str]:
    p = norm(path)
    return {a or b for a, b in ABS_RE.findall(p)} if _live_msys else set(ABS_RE.findall(p))


def slugs_in_shell(cmd: str) -> set[str]:
    c = norm(cmd)
    found = slugs_in_path(c)
    if MENTIONS_LIVE.search(c):
        found |= set(REL_RE.findall(c))
    return found


def edits_of(name: str, args) -> set[str]:
    """道具1回の呼び出しが書き換えた（かもしれない）成果物の slug。"""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {"command": args}
    if not isinstance(args, dict):
        return set()
    name = name.rsplit("__", 1)[-1]   # mcp__dan-tools__write_file → write_file
    if name in EDIT_TOOLS:
        return slugs_in_path(str(args.get("file_path") or args.get("path") or args.get("notebook_path") or ""))
    text = ""
    for key in ("command", "cmd", "input", "patch", "code"):
        v = args.get(key)
        if isinstance(v, list):
            v = " ".join(map(str, v))
        if isinstance(v, str):
            text += "\n" + v
    if not text:
        return set()
    text = DATA_HEREDOC.sub(lambda m: m.group(1) + m.group(4), text)
    out = set()
    for f in PATCH_FILE.findall(text):
        out |= slugs_in_path(f.strip())
    if name in SHELL_TOOLS or name == "apply_patch" or "apply_patch" in text:
        if "artifact_seen.py" in text and not WRITE_MARK.search(text.replace("artifact_seen.py", "")):
            return out
        if WRITE_MARK.search(text):
            out |= slugs_in_shell(text)
    return out


def _texts(obj, out: list[str]) -> None:
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _texts(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _texts(v, out)


def _is_turn_start(content) -> bool:
    """本人（または起こした仕組み）からの新しい言葉か。道具の結果と、止める仕組みからの案内は数えない。"""
    texts: list[str] = []
    if isinstance(content, str):
        texts = [content]
    elif isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return False
        texts = [b.get("text") or "" for b in content if isinstance(b, dict) and b.get("type") in ("text", "input_text")]
    joined = "\n".join(texts).lstrip()
    return bool(joined) and not joined.startswith(("Stop hook feedback", "[成果物の確認の関所]"))


def read_events(path: str) -> tuple[list[tuple], str]:
    """記録を順に (種類, …) へ。('edit', slugs) / ('seen', slug, result) / ('turn',)。最後の返事の文も返す。"""
    events: list[tuple] = []
    last_text = ""
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return events, last_text
    with f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            # Claude Code: {"type":"assistant","message":{"content":[{"type":"tool_use",...}]}} / user の tool_result
            msg = d.get("message") if isinstance(d.get("message"), dict) else None
            if msg is not None and d.get("type") == "user" and _is_turn_start(msg.get("content")):
                events.append(("turn",))
                continue
            if msg is not None and isinstance(msg.get("content"), list):
                for block in msg["content"]:
                    if not isinstance(block, dict):
                        continue
                    kind = block.get("type")
                    if kind == "tool_use":
                        s = edits_of(str(block.get("name") or ""), block.get("input") or {})
                        if s:
                            events.append(("edit", s))
                    elif kind == "tool_result":
                        texts: list[str] = []
                        _texts(block.get("content"), texts)
                        for t in texts:
                            for slug, result in SEEN_RE.findall(t):
                                events.append(("seen", slug, result))
                    elif kind == "text" and d.get("type") == "assistant":
                        last_text = block.get("text") or last_text
                continue
            # Codex rollout: {"type":"response_item","payload":{"type":"function_call"|"custom_tool_call"|..._output}}
            p = d.get("payload") if isinstance(d.get("payload"), dict) else None
            if p is None:
                continue
            ptype = p.get("type")
            if ptype in ("function_call", "custom_tool_call", "local_shell_call"):
                args = p.get("arguments") if "arguments" in p else p.get("input", p.get("action") or {})
                s = edits_of(str(p.get("name") or "exec"), args)
                if s:
                    events.append(("edit", s))
            elif ptype in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
                texts = []
                _texts(p.get("output"), texts)
                for t in texts:
                    for slug, result in SEEN_RE.findall(t):
                        events.append(("seen", slug, result))
            elif ptype == "message" and p.get("role") == "user" and _is_turn_start(p.get("content")):
                events.append(("turn",))
            elif ptype == "message" and p.get("role") == "assistant":
                texts = []
                _texts(p.get("content"), texts)
                if texts:
                    last_text = "\n".join(texts)
            elif ptype == "task_complete" and p.get("last_agent_message"):
                last_text = p["last_agent_message"]
    return events, last_text


def pending(events: list[tuple]) -> tuple[dict[str, int], dict[str, str]]:
    """書き換えた後に確かめていない slug → 最後の書き換えの位置。確かめた slug → 最後の結果。"""
    last_edit: dict[str, int] = {}
    last_seen: dict[str, tuple[int, str]] = {}
    for i, ev in enumerate(events):
        if ev[0] == "edit":
            for s in ev[1]:
                last_edit[s] = i
        elif ev[0] == "seen":
            last_seen[ev[1]] = (i, ev[2])
    unchecked, results = {}, {}
    for s, i in last_edit.items():
        hits = [v for k, v in last_seen.items() if (k == s or k == "*") and v[0] > i]
        if not hits:
            unchecked[s] = i
        else:
            results[s] = max(hits)[1]
    return unchecked, results


def count_block(session: str, key: str) -> int:
    STORE.mkdir(parents=True, exist_ok=True)
    f = STORE / (re.sub(r"[^\w-]", "_", session or "unknown")[:80] + ".json")
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[key] = data.get(key, 0) + 1
    f.write_text(json.dumps(data), encoding="utf-8")
    return data[key]


def this_turn_results(events: list[tuple]) -> dict[str, str]:
    """このターン（最後の本人の言葉の後）で確かめた slug → 最後の結果。前のターンの NG で次のターンを止めない
    （10-25 前のターンの NG のまま、次の「READY」だけのターンが止められた）。"""
    start = max((i for i, ev in enumerate(events) if ev[0] == "turn"), default=-1)
    out: dict[str, str] = {}
    for ev in events[start + 1:]:
        if ev[0] == "seen":
            out[ev[1]] = ev[2]
    return out


REWRITE = ("確かめた結果（版・画面・裏側・公開版がどうだったか）は本人への返事に書かない。本人に言う話ではない。"
           "この後に書く文が、本人に届く返事の全部になる（確かめる前に書いた文は届かない）。"
           "確かめ終えたら、確かめる前に書いた本人への答えを、言い直さずそのまま全部もう一度書いて終えること"
           "（「結果を足します」のような書き出しにしない）。")


def block(reason: str) -> int:
    sys.stdout.write(json.dumps({"decision": "block", "reason": "[成果物の確認の関所] " + reason}))
    sys.stdout.flush()
    return 0


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except ValueError:
        return 0
    if payload.get("hook_event_name") not in (None, "Stop", "SubagentStop"):
        return 0
    path = payload.get("transcript_path") or payload.get("agent_transcript_path") or ""
    if not path:
        return 0
    events, last_text = read_events(path)
    unchecked, results = pending(events)
    message = payload.get("last_assistant_message") or last_text or ""
    session = str(payload.get("session_id") or hashlib.sha1(path.encode()).hexdigest()[:16])
    if unchecked:
        key = "u:" + ",".join(f"{s}@{i}" for s, i in sorted(unchecked.items()))
        if count_block(session, key) > MAX_BLOCKS:
            return 0
        names = sorted(unchecked)
        cmds = "\n".join(f"  python {SEEN_CMD} --slug {s} --wait 90" for s in names)
        return block(
            f"この作業で成果物（{', '.join(names)}）を書き換えたが、その後に本人の画面と本番の裏側を確かめていない。"
            "ダンのブラウザ・テスト用アカウント・8001 の確認用サーバーで見えたことは、本人の画面の証拠にならない。"
            f"終える前に次を走らせること:\n{cmds}\n"
            "result=NG なら、NG の行の理由（読み直し待ち・作り直し中など）が片付くまで待って、もう一度走らせる。"
            "待っても直らない（作り直しに失敗している等）時だけ、本人の言葉で「〜はまだ直っていません」と1文書く。"
            + REWRITE)
    bad = {s: r for s, r in this_turn_results(events).items() if r == "NG"}
    if bad and not payload.get("stop_hook_active"):
        key = "r:" + ",".join(f"{s}={r}" for s, r in sorted(bad.items())) + ":" + hashlib.sha1(message.encode()).hexdigest()[:8]
        if count_block(session, key) > 1:
            return 0
        lines = ", ".join(f"{s}={r}" for s, r in sorted(bad.items()))
        cmds = "\n".join(f"  python {SEEN_CMD} --slug {s} --wait 90" for s in sorted(bad))
        return block(
            f"確かめた結果が NG のまま（{lines}）。NG の行の理由が片付くまで待って、もう一度走らせること:\n{cmds}\n"
            "待っても直らない時だけ、本人の言葉で「〜はまだ直っていません」と1文書く。" + REWRITE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
