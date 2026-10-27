# -*- coding: utf-8 -*-
"""Stop hook: 画面を書き換えたら、確かめるまでターンを終えられない。

確かめは2つあり、対象が違う。

1. 本人の画面（2026-10-18）: 動いているダン（D:/done）の frontend/src/app/artifacts/<slug>/ を書き換えた後に、
   artifact_seen.py の結果「[artifact_seen] slug=… result=…」が要る。本人「あなたが直して確認した画面と私が見る画面が
   一致し、『直した』と言われたものはちゃんと直っている」。ダンの確認では直っていたのに、本人の画面では古い部品や
   再起動待ちの裏側のまま動いていた、が何度も起きた。
   このターンで確かめた結果が NG（作り直しや読み直しの途中）の時は、一度だけ止めて、待ってから確かめ直させる。
   UNCHECKED（本人が開いていない）は止めない（開けば新しい版に切り替わる）。

2. 場所の地図と画面の見え方（2026-10-25）: 動いているダンでも作業場所（<dan-workspace>/<名前>）でも、画面のファイル
   （成果物の _server・MAP.md・PRODUCT.md・*.gen.json 以外、と共通の場所の地図の watches に書いたファイル）を
   このターンで書き換えたら、その場所ごとに、同じフォルダで次の3つが要る。
     - 書き換えの前に撮った「[place_shot] … tag=before …」
     - 最後の書き換えの後に撮った「[place_shot] … tag=after … result=OK」（NG なら一度止めて直させる）
     - 最後の書き換えの後の、いちばん新しい「[place_map] place=… result=FRESH」（後で STALE が出たら通さない）
   撮った結果は covers に書かれた場所すべてに数える（dev-lead-room を撮れば artifact:dev-lead にも数える）。
   ローレン・タンさんの講演（機能の地図）から。地図が古いと、次に直すダンが画面にたどり着けず、話すダンは画面に無い物を
   案内する。10-25 開発室の話し合いで番号が消えていたのに、ダンは自分の返事の見え方を一度も見ていなかった。

確かめた結果は本人への返事に書かせない（2026-10-25 本人: 「本人の画面を確かめた結果を足します。パソコンで開いている
顧客管理のタブは、もう新しい版に…」は「一切いらない」「内部的な話」）。止めるとその後に書いた文だけが本人に届く返事に
なる（Claude の result も Codex の最後の文もそう）ので、止める時は「確かめる前に書いた本人への答えを、そのまま全部
もう一度書いて終える」よう案内する。10-25 はこの案内が無く、答えが捨てられて確かめた結果の1段落だけが届いた。

書き換えは Write/Edit/MultiEdit、ダンの write_file/edit_file（Codex の exec の中の tools.mcp__…__edit_file も）、
apply_patch、シェルの書き込み（> ・write_text・sed -i・cp/mv など）を数える。シェルは見分けが粗いので、読むだけの
コマンドでも書き込みの印があれば数える（確かめを1回走らせれば通る）。相対パスは記録の cwd か、コマンドの cd 先で読む。

3. 不具合の知らせ（2026-10-27 付箋「不具合を先に再現する」）: みきさんの言葉が「動かない」「開けない」「番号が出ていない」
   「画面の写真だけ」のような不具合の知らせで、このターンにダンが画面やアプリのコードを書き換えたか、返事で「直しました」と
   言ったら、次が要る。
     - 直す前に、みきさんの言う物を --expect-… で書いて撮った place_shot（repro=YES|NO）か、スマホのアプリなら phone で
       見た画面。コードを読んで見当で直さない。
     - 再現した（YES）のに画面を直したなら、最後の書き換えの後に同じく --expect-… を付けた after が OK。
     - 再現しなかった（NO）なら artifact_seen.py でみきさんの画面の版を確かめる（「こちらでは出ません」の根拠）。
     - 返事に前と後（再現しなかった時はこちらの画面）の絵を attach_image で貼る（[添付画像: …]）。
   10/18 X運用室の表紙の×は、ダンの画面では出ていたのに本人の画面で出ず、ダンは見当で直して「直しました」と何度も返した。
   10/25 番号と点が出ていない件も、ダンは自分の返事の見え方を見ずに直した。

同じ書き換えで止めるのは3回まで（.data/artifact_gate/ に数える）。それを超えたら通して記録だけ残す。
直す前を撮っていなかった時は、後から撮れないので1回だけ止めて、次からは先に撮るよう伝える。
exit 0 = 通す / stdout に {"decision":"block","reason":…} = 続けさせる（Claude と Codex で同じ形）。
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = Path(os.environ.get("DAN_ARTIFACT_GATE_DIR") or (ROOT / ".data" / "artifact_gate"))
LIVE = os.environ.get("DAN_ARTIFACT_GATE_LIVE", ROOT.as_posix()).replace("\\", "/").rstrip("/").lower()
WORKTREES = os.environ.get("DAN_ARTIFACT_GATE_WORKTREES", LIVE.rsplit("/", 1)[0] + "/dan-workspace").replace("\\", "/").rstrip("/").lower()
MAX_BLOCKS = 3
SEEN_CMD = os.environ.get("DAN_ARTIFACT_SEEN", (ROOT / "scripts/artifact_seen.py").as_posix())


def _alt(root: str) -> str:
    """D:/done → D:/done と /d/done（Git Bash）の両方に当たる正規表現。"""
    if re.match(r"^[a-z]:/", root):
        return "(?:" + re.escape(root) + "|/" + re.escape(root[0]) + re.escape(root[2:]) + ")"
    return re.escape(root)


# 木（動いているダンか作業場所の1つ）の中のパス: (木, 木からの相対パス)
TREE_RE = re.compile("(" + _alt(LIVE) + "|" + _alt(WORKTREES) + r"/[\w.-]+)(/[^\s'\"`;|&<>(),{}\]]*)", re.I)
REL_RE = re.compile(r"(?:^|[\s'\"=(:])((?:frontend|mobile|app|docs|scripts)/[^\s'\"`;|&<>(),{}\]]+)")
CD_RE = re.compile(r"(?:^|[;&|]\s*|\n\s*)cd\s+(?:/d\s+)?['\"]?([^\s'\";&|]+)")
ART_RE = re.compile(r"^frontend/src/app/artifacts/([\w-]+)(/.*)?$", re.I)
NOT_SCREEN_TAIL = re.compile(r"^/(?:_server/.*|MAP\.md|PRODUCT\.md|[^/]*\.gen\.json)$", re.I)
WRITE_MARK = re.compile(
    r"(?<![<>0-9&])>{1,2}(?![>&=])|\bwrite_text\b|\bwrite_bytes\b|\.write\(|open\([^)]*['\"][wa]b?\+?['\"]|\bsed\s+-i\b|"
    r"\b(?:cp|mv|rm|rsync|tee|touch|install)\s|\bcopy(?:file|tree|2)?\(|\bshutil\.|\bSet-Content\b|\bAdd-Content\b|"
    r"\bOut-File\b|\bCopy-Item\b|\bMove-Item\b|\bRemove-Item\b|\bNew-Item\b|writeFileSync|\bunlink\(|\brename\(|"
    r"\bos\.replace\(|apply_patch|\*\*\* (?:Add|Update|Delete) File:|(?:write|edit)_file\s*\(", re.I)
SEEN_RE = re.compile(r"\[artifact_seen\] slug=([\w*-]+) result=(OK|NG|UNCHECKED)")
MAP_RE = re.compile(r"\[place_map\] (?:place|slug)=([\w:-]+) result=(FRESH|STALE|DRAFT|MISSING)(?: root=(\S+))?")
SHOT_RE = re.compile(r"\[place_shot\] place=([\w:-]+)(?: covers=([\w:,-]*))? tag=(\w+) result=(OK|NG|UNREACHABLE)(?: root=(\S+))?"
                     r"(?: expect=(\d+) repro=(YES|NO))?")
PATCH_FILE = re.compile(r"\*\*\* (?:Add|Update|Delete) File: (.+)")
# `cat > 先 <<'EOF' … EOF` / `tee 先 <<EOF`: 中身は「先」に書く文章で、中に成果物のパスが出ても成果物は書き換わらない
# （10/18 試験ファイルに書いた試験用のパスを成果物の書き換えと数えた）。中身だけ除き、書き込む先は残して判定する。
# python - <<EOF のようにコマンドへ渡す中身は、そのコードが成果物を書くことがあるので除かない。
DATA_HEREDOC = re.compile(r"(\b(?:cat|tee(?:\s+-a)?)\b[^\n]*?<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n)(.*?)(\n\2\b)", re.S)
EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "write_file", "edit_file"}
SHELL_TOOLS = {"Bash", "PowerShell", "bash", "exec", "shell", "local_shell", "exec_command"}
CHECK_TOOLS = ("artifact_seen.py", "place_map.py", "place_shot.py")


def norm(p: str) -> str:
    return (p or "").replace("\\\\", "/").replace("\\", "/")


def _tree(p: str) -> str:
    """木のパスを小文字・/区切り・D:/ 形式にそろえる（/d/done → d:/done）。"""
    p = norm(p).rstrip("/").lower()
    m = re.match(r"^/([a-z])(/.*)$", p)
    if m and re.match(r"^[a-z]:/", LIVE) and p.startswith("/" + LIVE[0]):
        p = m.group(1) + ":" + m.group(2)
    return p


def paths_in(text: str, cwd: str = "") -> list[tuple[str, str]]:
    """文の中の、木の中のパス → [(木, 相対パス)]。相対パスは cwd かコマンドの cd 先の木で読む。"""
    t = norm(text)
    out = [(_tree(root), rel.lstrip("/")) for root, rel in TREE_RE.findall(t)]
    base = ""
    for d in [cwd] + CD_RE.findall(t):
        for root, _ in TREE_RE.findall(norm(d) + "/"):
            base = _tree(root)
    if base:
        out += [(base, rel) for rel in REL_RE.findall(t)]
    return out


def edits_of(name: str, args, cwd: str = "") -> list[tuple[str, str]]:
    """道具1回の呼び出しが書き換えた（かもしれない）ファイル → [(木, 相対パス)]。"""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {"command": args}
    if not isinstance(args, dict):
        return []
    name = name.rsplit("__", 1)[-1]   # mcp__dan-tools__write_file → write_file
    if name in EDIT_TOOLS:
        return paths_in(str(args.get("file_path") or args.get("path") or args.get("notebook_path") or ""), cwd)
    text = ""
    for key in ("command", "cmd", "input", "patch", "code"):
        v = args.get(key)
        if isinstance(v, list):
            v = " ".join(map(str, v))
        if isinstance(v, str):
            text += "\n" + v
    if not text:
        return []
    text = DATA_HEREDOC.sub(lambda m: m.group(1) + m.group(4), text)
    out = []
    for f in PATCH_FILE.findall(text):
        out += paths_in(f.strip(), cwd)
    if name in SHELL_TOOLS or name == "apply_patch" or "apply_patch" in text:
        rest = text
        for tool in CHECK_TOOLS:
            rest = rest.replace(tool, "")
        if any(t in text for t in CHECK_TOOLS) and not WRITE_MARK.search(rest):
            return out
        if WRITE_MARK.search(text):
            out += paths_in(text, cwd)
    return out


# --- 共通の場所の地図が見張るファイル（docs/places/<id>.md の watches） ---------------------------------------

_watch_cache: dict[str, dict[str, list[str]]] = {}


def watches(tree: str) -> dict[str, list[str]]:
    if tree not in _watch_cache:
        found: dict[str, list[str]] = {}
        for f in sorted(Path(tree).glob("docs/places/*.md")):
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            m = re.search(r"^watches:\s*\n((?:\s+-\s+.+\n)+)", text, re.M)
            if m:
                found[f.stem] = [x.strip().strip("'\"") for x in re.findall(r"-\s+(.+)", m.group(1))]
        _watch_cache[tree] = found
    return _watch_cache[tree]


def places_of(tree: str, rel: str) -> set[str]:
    """書き換えたファイルを見せる場所（artifact:<slug> と、watches に当たる共通の場所）。"""
    out = set()
    m = ART_RE.match(rel)
    if m and not NOT_SCREEN_TAIL.match(m.group(2) or "/"):
        out.add(f"artifact:{m.group(1).lower()}")
    for place, globs in watches(tree).items():
        if any(fnmatch.fnmatch(rel, g) for g in globs):
            out.add(place)
    return out


def live_slugs(edits: list[tuple[str, str]]) -> set[str]:
    out = set()
    for tree, rel in edits:
        m = ART_RE.match(rel)
        if tree == LIVE and m:
            out.add(m.group(1).lower())
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


def _results(texts: list[str], events: list[tuple]) -> None:
    for t in texts:
        for slug, result in SEEN_RE.findall(t):
            events.append(("seen", slug, result))
        for place, result, root in MAP_RE.findall(t):
            events.append(("map", _tree(root) if root else "*", _place(place), result))
        for place, covers, tag, result, root, expect, repro in SHOT_RE.findall(t):
            cov = {_place(place)} | {_place(c) for c in covers.split(",") if c}
            events.append(("shot", _tree(root) if root else "*", cov, tag, result, repro if expect else ""))


def _place(p: str) -> str:
    """古い形の slug=x は artifact:x。共通の場所の id（chat など）はそのまま。"""
    common = {"chat", "artifact-tab", "dev-lead-room", "mobile"}
    return p if ":" in p or p in common else f"artifact:{p}"


LATEST_RE = re.compile(r"<latest_user_message>((?:(?!<latest_user_message>).)*?)</latest_user_message>", re.S)
# 仕組みが起こしたターン（文脈の読み込み・見張りの起床・ボードからの知らせ）は本人の言葉ではない
SYSTEM_TURN = re.compile(r"\[CONTEXT PRELOAD\]|WATCH_NO_CHANGE|schedule_followup|（ここから並行作業）|^【.{1,40}からの(?:報告|知らせ)】")
BUG_WORDS = re.compile(
    r"動かな|動いてな|開けな|開かな|ひらけな|ひらかな|出(?:て)?(?:こ)?な(?:い|く)|出てな|表示されな|見えな|映らな|消え(?:た|て)|"
    r"壊れ|崩れ|押せな|反応しな|効かな|できな(?:い|く)|エラー|おかしい|バグ|直ってな|なおってな|治ってな|真っ白|白紙|"
    r"ずれ(?:て|た|る)|はみ出|重なって|切れて|読めな|固ま(?:る|った|って)|落ちる|落ちた|止まる|止まった|？？|\?\?")
ATTACH_RE = re.compile(r"\[添付(?:画像|動画|ファイル)[:：]")
FIX_CLAIM = re.compile(r"直しました|直りました|直してあります|直っています|直った|修正しました|修正済|解消しました|出るようにしました|"
                       r"開けるようにしました|動くようにしました|表示されるようにしました")
CODE_DIRS = ("frontend/", "mobile/")


def owner_words(content) -> str:
    """ターンの始まりの言葉のうち、本人が書いた所（ダンの部屋では <latest_user_message> の中）。仕組みの起床なら空。"""
    texts: list[str] = []
    if isinstance(content, str):
        texts = [content]
    elif isinstance(content, list):
        texts = [b.get("text") or "" for b in content if isinstance(b, dict) and b.get("type") in ("text", "input_text")]
    text = "\n".join(texts)
    found = LATEST_RE.findall(text)
    if found:
        text = found[-1]
    elif "<" in text and len(text) > 1500:   # 前置きの付いた長い言葉で、本人の所が分からない
        return ""
    text = re.sub(r"<place>.*?</place>|<room_state>.*?</room_state>", "", text, flags=re.S).strip()
    return "" if SYSTEM_TURN.search(text) else text


def is_bug_report(text: str) -> bool:
    if not text:
        return False
    if BUG_WORDS.search(ATTACH_RE.sub("", text)):
        return True
    # 画面の写真だけ（字がほとんど無い）も不具合の知らせとして扱う
    rest = re.sub(r"\[添付(?:画像|動画|ファイル)[:：][^\]]*\]", "", text).strip()
    return bool(ATTACH_RE.search(text)) and len(re.sub(r"[\s?？!！。、]", "", rest)) <= 4


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
    """記録を順に (種類, …) へ。('edit', [(木, 相対パス)]) / ('seen', slug, result) / ('map', 木, 場所, result) /
    ('shot', 木, {場所}, tag, result) / ('turn',)。最後の返事の文も返す。"""
    events: list[tuple] = []
    last_text = ""
    codex_cwd = ""
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
            cwd = str(d.get("cwd") or "")
            # Claude Code: {"type":"assistant","message":{"content":[{"type":"tool_use",...}]}} / user の tool_result
            msg = d.get("message") if isinstance(d.get("message"), dict) else None
            if msg is not None and d.get("type") == "user" and _is_turn_start(msg.get("content")):
                events.append(("turn", owner_words(msg.get("content"))))
                continue
            if msg is not None and isinstance(msg.get("content"), list):
                for block in msg["content"]:
                    if not isinstance(block, dict):
                        continue
                    kind = block.get("type")
                    if kind == "tool_use":
                        e = edits_of(str(block.get("name") or ""), block.get("input") or {}, cwd)
                        if e:
                            events.append(("edit", e))
                        if _phone_look(str(block.get("name") or ""), block.get("input")):
                            events.append(("phone",))
                    elif kind == "tool_result":
                        texts: list[str] = []
                        _texts(block.get("content"), texts)
                        _results(texts, events)
                    elif kind == "text" and d.get("type") == "assistant":
                        last_text = block.get("text") or last_text
                continue
            # Codex rollout: {"type":"response_item","payload":{"type":"function_call"|"custom_tool_call"|..._output}}
            p = d.get("payload") if isinstance(d.get("payload"), dict) else None
            if p is None:
                continue
            if d.get("type") in ("turn_context", "session_meta") and p.get("cwd"):
                codex_cwd = str(p["cwd"])
                continue
            ptype = p.get("type")
            if ptype in ("function_call", "custom_tool_call", "local_shell_call"):
                args = p.get("arguments") if "arguments" in p else p.get("input", p.get("action") or {})
                e = edits_of(str(p.get("name") or "exec"), args, codex_cwd)
                if e:
                    events.append(("edit", e))
                if _phone_look(str(p.get("name") or ""), args):
                    events.append(("phone",))
            elif ptype in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
                texts = []
                _texts(p.get("output"), texts)
                _results(texts, events)
            elif ptype == "message" and p.get("role") == "user" and _is_turn_start(p.get("content")):
                events.append(("turn", owner_words(p.get("content"))))
            elif ptype == "message" and p.get("role") == "assistant":
                texts = []
                _texts(p.get("content"), texts)
                if texts:
                    last_text = "\n".join(texts)
            elif ptype == "task_complete" and p.get("last_agent_message"):
                last_text = p["last_agent_message"]
    return events, last_text


def _phone_look(name: str, args) -> bool:
    """スマホ（開発用の Galaxy）の画面を見た呼び出しか。スマホのアプリの不具合は place_shot で開けないので、これを再現の証拠に数える。"""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {"command": args}
    if not isinstance(args, dict):
        return False
    if name.rsplit("__", 1)[-1] == "phone":
        return args.get("action") in ("screenshot", "read")
    text = " ".join(str(args.get(k) or "") for k in ("command", "cmd", "input", "code"))
    return bool(re.search(r"\badb\b[^\n]*\b(?:screencap|exec-out\s+screencap)", text))


# --- 1. 本人の画面 ------------------------------------------------------------------------------------------------

def pending(events: list[tuple]) -> tuple[dict[str, int], dict[str, str]]:
    """動いているダンの成果物を書き換えた後に確かめていない slug → 最後の書き換えの位置。確かめた slug → 最後の結果。"""
    last_edit: dict[str, int] = {}
    last_seen: dict[str, tuple[int, str]] = {}
    for i, ev in enumerate(events):
        if ev[0] == "edit":
            for s in live_slugs(ev[1]):
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


def this_turn_start(events: list[tuple]) -> int:
    return max((i for i, ev in enumerate(events) if ev[0] == "turn"), default=-1)


def this_turn_results(events: list[tuple]) -> dict[str, str]:
    """このターン（最後の本人の言葉の後）で確かめた slug → 最後の結果。前のターンの NG で次のターンを止めない
    （10-25 前のターンの NG のまま、次の「READY」だけのターンが止められた）。"""
    out: dict[str, str] = {}
    for ev in events[this_turn_start(events) + 1:]:
        if ev[0] == "seen":
            out[ev[1]] = ev[2]
    return out


# --- 2. 場所の地図と画面の見え方 ----------------------------------------------------------------------------------

def place_needs(events: list[tuple]) -> dict[tuple[str, str], dict]:
    """このターンで書き換えた (木, 場所) → {first, last, need: [...], shot: 最後の after の結果}。足りている物は返さない。"""
    start = this_turn_start(events)
    span: dict[tuple[str, str], list[int]] = {}
    for i, ev in enumerate(events):
        if i > start and ev[0] == "edit":
            for tree, rel in ev[1]:
                for place in places_of(tree, rel):
                    span.setdefault((tree, place), [i, i])[1] = i
    out = {}
    for (tree, place), (first, last) in span.items():
        # 作業場所に一時的に写して、もう消した成果物の写しは数えない（確かめる画面が無い。10-26 写しを消しただけで止め続けた）
        if place.startswith("artifact:") and tree != LIVE and Path(tree).is_dir() \
                and not (Path(tree) / "frontend/src/app/artifacts" / place.split(":", 1)[1]).is_dir():
            continue
        here = lambda ev: ev[1] in ("*", tree)  # noqa: E731
        shots = [(i, ev) for i, ev in enumerate(events) if ev[0] == "shot" and here(ev) and place in ev[2]]
        maps = [(i, ev) for i, ev in enumerate(events) if ev[0] == "map" and here(ev) and ev[2] == place]
        need = []
        if not any(i < first and ev[3] == "before" for i, ev in shots):
            need.append("before")
        after = [ev for i, ev in shots if i > last and ev[3] in ("after", "now")]
        if not after:
            need.append("after")
        latest_map = [ev for i, ev in maps if i > last]
        if not latest_map or latest_map[-1][3] != "FRESH":
            need.append("map")
        shot = after[-1][4] if after else ""
        if need or shot != "OK":
            out[(tree, place)] = {"first": first, "last": last, "need": need, "shot": shot}
    return out


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


REWRITE = ("確かめた結果（版・画面・裏側・公開版・地図・撮った絵がどうだったか）は本人への返事に書かない。本人に言う話ではない。"
           "この後に書く文が、本人に届く返事の全部になる（確かめる前に書いた文は届かない）。"
           "確かめ終えたら、確かめる前に書いた本人への答えを、言い直さずそのまま全部もう一度書いて終えること"
           "（「結果を足します」のような書き出しにしない）。")


def block(reason: str) -> int:
    sys.stdout.write(json.dumps({"decision": "block", "reason": "[成果物の確認の関所] " + reason}))
    sys.stdout.flush()
    return 0


def place_block(session: str, needs: dict) -> int | None:
    """場所の地図と撮影の足りない所で止める。止めない時は None。"""
    lines, keys, only_before = [], [], True
    for (tree, place), n in sorted(needs.items()):
        scripts = f"{tree}/scripts"
        name = place.split(":", 1)[1] if place.startswith("artifact:") else place
        todo = []
        if "map" in n["need"]:
            todo.append(f"  python {scripts}/place_map.py check {place}   # STALE なら、変わった画面に合わせて地図の説明を直してから "
                        f"stamp {place}（説明が変わらない直しなら --unchanged \"理由\"）。無ければ draft {name}")
        if "after" in n["need"] or n["shot"] not in ("OK", ""):
            todo.append(f"  python {scripts}/place_shot.py {place} --tag after   # 画面のサーバーはその木の物を --base で")
        if "before" in n["need"]:
            todo.append(f"  （直す前の {place} を撮っていない。後からは撮れないので、次に画面を直す時は先に --tag before を撮る）")
        if todo:
            lines.append(f"- {place}（{tree}）\n" + "\n".join(todo))
            keys.append(f"{tree}|{place}|{n['last']}|{'+'.join(n['need'])}|{n['shot']}")
            only_before = only_before and n["need"] == ["before"] and n["shot"] in ("OK", "")
    if not lines:
        return None
    key = "p:" + ";".join(keys)
    if count_block(session, key) > (1 if only_before else MAX_BLOCKS):
        return None
    ng = [p for (t, p), n in needs.items() if n["shot"] == "NG"]
    return block(
        "この作業で画面のファイルを書き換えたが、その場所の地図を今の画面に合わせて直していないか、直す前と後を撮って"
        "見え方を確かめていない。地図が古いと、次に直すダンがその画面にたどり着けず、話すダンは画面に無い物を案内する。"
        "終える前に次を走らせること（地図の形は docs/places/README.md）:\n" + "\n".join(lines) + "\n"
        + (f"撮った結果が NG の場所（{', '.join(sorted(ng))}）は、見えなかった物を直してから撮り直す。"
           "直せない時だけ、本人の言葉で「〜はまだ直っていません」と1文書く。" if ng else "")
        + REWRITE)


# --- 3. 不具合の知らせ ------------------------------------------------------------------------------------------

def _app_code(rel: str) -> bool:
    """画面やアプリのコードか。成果物の地図・説明・作った記録（MAP.md など）は数えない（10-27 試しで地図を直しただけで撮り直させた）。"""
    m = ART_RE.match(rel)
    if m and NOT_SCREEN_TAIL.match(m.group(2) or "/") and not (m.group(2) or "").startswith("/_server/"):
        return False
    return rel.startswith(CODE_DIRS)


def bug_needs(events: list[tuple], message: str) -> dict | None:
    """このターンが不具合の知らせで、直した・直したと言ったのに足りない物 → {need: [...], places, edited}。足りていれば None。"""
    start = this_turn_start(events)
    if start < 0 or len(events[start]) < 2 or not is_bug_report(events[start][1]):
        return None
    turn = list(enumerate(events))[start + 1:]
    edits = [(i, tree, rel) for i, ev in turn if ev[0] == "edit" for tree, rel in ev[1]]
    screen = [(i, tree, rel) for i, tree, rel in edits if places_of(tree, rel) or _app_code(rel)]
    claimed = bool(FIX_CLAIM.search(message or ""))
    if not screen and not claimed:
        return None   # 答えただけ・調べただけ・画面と関係の無い直し
    first = min((i for i, _, _ in screen), default=len(events))
    last = max((i for i, _, _ in screen), default=-1)
    repro = [(i, ev) for i, ev in turn if ev[0] == "shot" and len(ev) > 5 and ev[5] and i < first and ev[3] in ("before", "now")]
    phone = [i for i, ev in turn if ev[0] == "phone" and i < first]
    seen = [i for i, ev in turn if ev[0] == "seen"]
    places = sorted({p for _, tree, rel in screen for p in places_of(tree, rel)})
    need = []
    if not repro and not phone:
        need.append("repro")
    reproduced = any(ev[5] == "YES" for _, ev in repro)
    if repro and not reproduced and not seen:
        need.append("seen")
    if screen and (reproduced or not repro):
        if not any(ev[0] == "shot" and len(ev) > 5 and ev[5] == "NO" and ev[4] == "OK" and ev[3] == "after" for i, ev in turn if i > last) \
                and not (phone and any(i > last for i, ev in turn if ev[0] == "phone")):
            need.append("after")
    if not ATTACH_RE.search(message or ""):
        need.append("picture")
    if not need:
        return None
    return {"need": need, "places": places, "edited": bool(screen), "first": first}


def bug_block(session: str, events: list[tuple], message: str) -> int | None:
    n = bug_needs(events, message)
    if not n:
        return None
    key = "b:" + str(n["first"]) + ":" + "+".join(n["need"])
    # 再現が足りない時は1回だけ止める（直した後は直す前を撮れない。画面の無い直しでは再現の道具が合わないこともある）
    limit = 1 if "repro" in n["need"] else MAX_BLOCKS
    if count_block(session, key) > limit:
        return None
    where = "、".join(n["places"]) or "<場所>（docs/places/ と各成果物の MAP.md）"
    todo = []
    if "repro" in n["need"]:
        if n["edited"]:
            todo.append("- 直す前に、みきさんの言う崩れをこちらで出していない。コードを読んで見当で直した形になっている。"
                        "直す前の画面はもう撮れないので、次の不具合の知らせからは、書き換える前に必ず撮る。今回は直した後を下のとおり撮って確かめる。")
        else:
            todo.append(f"- 直したと言う前に、みきさんの言う崩れをこちらで出す: python scripts/place_shot.py {where} --tag before "
                        "[--phone]（スマホで見た話なら）--expect-shows 番号の並び / --expect-visible 'CSS' / --expect-text 字 / "
                        "--expect-no-text 字（みきさんが見えないと言った物を書く）。スマホのアプリの話なら phone で同じ画面を開いて見る。")
    if "seen" in n["need"]:
        todo.append("- こちらでは再現しなかった（repro=NO）。直す前に、みきさんの画面が古い版のままでないかを確かめる: "
                    "python scripts/artifact_seen.py --slug <slug> --wait 90。古ければ、そう返す（みきさんに再読み込みを頼む前に、まず記録で確かめる）。")
    if "after" in n["need"]:
        todo.append(f"- 直した後に、直す前と同じ --expect-… を付けて撮り、OK を確かめる: python scripts/place_shot.py {where} --tag after "
                    "[--phone] --expect-…（作業場所の画面は --base）。前と後を並べた絵（compare.png）ができる。")
    if "picture" in n["need"]:
        todo.append("- 返事に絵を貼る。直したなら前と後を並べた絵（.data/place_shots/<場所>/compare.png）、再現しなかったなら"
                    "こちらで見えている画面（before.png）を attach_image で貼り、返ってきた [添付画像: …] を本文に入れる。")
    return block(
        "みきさんの不具合の知らせ（動かない・出ていない・画面の写真）に、同じ崩れをこちらで出して確かめないまま、直した・直したと"
        "言っている。ダンの「直しました」がみきさんの画面で直っていないこと（10/18 の表紙の×、10/25 の番号）を繰り返さないため、"
        "終える前に次をすること:\n" + "\n".join(todo) + "\n"
        "返事は、絵と一緒に、何が崩れていて何を直したか（再現しなかった時は「こちらでは出ています」と、みきさんの画面の版）を"
        "人に話す短さで書く。撮った手順・道具・測った結果の字は書かない。")


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
    unchecked, _ = pending(events)
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
        if count_block(session, key) <= 1:
            lines = ", ".join(f"{s}={r}" for s, r in sorted(bad.items()))
            cmds = "\n".join(f"  python {SEEN_CMD} --slug {s} --wait 90" for s in sorted(bad))
            return block(
                f"確かめた結果が NG のまま（{lines}）。NG の行の理由が片付くまで待って、もう一度走らせること:\n{cmds}\n"
                "待っても直らない時だけ、本人の言葉で「〜はまだ直っていません」と1文書く。" + REWRITE)
    stopped = bug_block(session, events, message)
    if stopped is not None:
        return stopped
    stopped = place_block(session, place_needs(events))
    return 0 if stopped is None else stopped


if __name__ == "__main__":
    sys.exit(main())
