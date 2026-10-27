# -*- coding: utf-8 -*-
"""Stop hook: みきさんへの返事に、言わない約束の書き方が入っていたら、一度だけ止めて書き直させる（2026-10-27）。

みきさんが叱った返事（10/16〜10/27 の19件）と叱られなかった返事（40件）、ダンの過去1週間の返事（1,040件）を
採点して作った。点検に入れたのは、言葉で確実に見つけられて、誤って止めることが少ない型だけ:
  - 英語の返事（10/22〜10/25 に並行作業の報告が23件、丸ごと英語で届いた）
  - 終わっていないことの途中の知らせ（「終わったら知らせます」「入れ替わったら効きます」「結果を足します」）
  - 試験の件数や通った報告（「試験は117個すべて通りました」）
  - PR・コミット・マージなど開発の手続き（みきさんが同じ言葉を使っていれば止めない）
  - 仕組みの中の呼び名（作る役・確かめ役・WATCH_NO_CHANGE など。返事が WATCH_NO_CHANGE だけの時は止めない）
SOUL.md の話し方は文章の決まりで、これは返事を出す直前の点検。主語が無い・本筋の答えが先に無い・何の件か無い、は
AI の判定が当たらなかった（2つのAIの一致 69〜85%、叱られた返事を見つけたのは半分）ので点検にしていない。
本人「意味分からん難しい話を長々されるのは困る」（10/25）、「WATCH_NO_CHANGE もいらん」（10/25）。

止めると、その後に書いた文だけが本人に届く返事になる（hook_artifact_verify_gate.py と同じ）。なので「直した返事の
全部をもう一度書く」よう案内する。同じ返事で止めるのは1回だけ（stop_hook_active の時は止めない）。
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
STORE = Path(os.environ.get("DAN_REPLY_CHECK_DIR") or (ROOT / ".data" / "reply_check"))
QUIET = "WATCH_NO_CHANGE"


def strip(text: str) -> str:
    """部品・コード・リンク先・添付・メールアドレスを外した、本人が読む文の部分。"""
    t = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+|\S+@\S+\.\w+", " ", t)
    t = re.sub(r"\[添付[^\]]*\]", " ", t)
    t = re.sub(r"\*\*【[^】]*】\*\*", " ", t)
    return t


def english_ratio(t: str) -> float:
    a = len(re.findall(r"[A-Za-z]", t))
    j = len(re.findall(r"[぀-ヿ一-鿿]", t))
    return a / (a + j + 1)


RULES = [
    ("interim", "終わっていないことの途中の知らせ",
     re.compile(r"終わ(ったら|り次第)[^。\n]{0,6}(お)?知らせ|済んだら[^。\n]{0,6}(お)?知らせ|まだ効いていません|効くのは次"
                r"|入れ替わ(ったら|るまで)|本体が入れ替わ|反映待ち|結果を足します"), None,
     "「始めます」「直しました」のように今の事実だけを書く。後で知らせることや、効き始めを待っていることは書かない。"),
    ("test-count", "試験の件数や通った報告",
     re.compile(r"(試験|テスト)[^。\n]{0,20}(\d+\s*(件|個|本)|全部|すべて)[^。\n]{0,10}(通|合格)"), r"試験|テスト",
     "ダンが確かめたことは書かない。確かめた結果、みきさんの使い方が変わる所だけを書く。"),
    ("dev-flow", "PR・コミット・マージなど開発の手続き",
     re.compile(r"PR\s?#?\d+|プルリク|コミット(し|を|まで|して|前|済)|マージ(し|済|前|まで)|ブランチ|main を取り込|follow_github"),
     r"PR|プルリク|コミット|マージ|ブランチ|プッシュ|push|main|GitHub",
     "みきさんが聞いていなければ書かない。本番に入れてよいかを聞く時は「本番に入れていいですか」とだけ書く。"),
    ("roles", "仕組みの中の呼び名",
     re.compile(r"作る役|確かめ(る)?役|担当のダン|部屋の担当|worktree|WATCH_[A-Z_]+|\[(artifact_seen|place_shot|place_map)\]"), r"役|担当",
     "みきさんが見て分かる言葉（「作っているダン」「確かめたダン」）にするか、書かない。"),
]


def check(reply: str, ask: str = "") -> list[dict]:
    if (reply or "").strip() == QUIET:
        return []
    body = strip(reply)
    hits = []
    if len(body) > 60 and english_ratio(body) > 0.5:
        hits.append({"id": "english", "name": "英語の返事", "at": body.strip()[:50].replace("\n", " "),
                     "fix": "日本語で書き直す。英語のエラー文は貼らず、何が止まったかと次にどうするかを日本語1文ずつで書く。"})
    for rid, name, rx, allow, fix in RULES:
        m = rx.search(body)
        if not m or (allow and re.search(allow, ask or "")) or (ask and m.group(0) in ask):
            continue
        s, e = max(0, m.start() - 20), min(len(body), m.end() + 20)
        hits.append({"id": rid, "name": name, "at": body[s:e].strip().replace("\n", " "), "fix": fix})
    return hits


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text") or "" for b in content if isinstance(b, dict) and b.get("type") in ("text", "input_text"))
    return ""


def owner_words(path: str) -> str:
    """このターンの本人の発言（ダンの包み紙の中の latest_user_message）。読めなければ空。"""
    last = ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                msg = row.get("message") if isinstance(row.get("message"), dict) else row.get("payload") or {}
                if (row.get("type") == "user" or msg.get("role") == "user") and not (
                        isinstance(msg.get("content"), list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in msg["content"])):
                    t = _text_of(msg.get("content"))
                    if t.strip():
                        last = t
    except OSError:
        return ""
    found = re.findall(r"<latest_user_message>(.*?)</latest_user_message>", last, flags=re.S)
    return (found[-1] if found else last)[-4000:]


def last_text(path: str) -> str:
    text = ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                msg = row.get("message") if isinstance(row.get("message"), dict) else {}
                if row.get("type") == "assistant" and isinstance(msg.get("content"), list):
                    t = _text_of(msg["content"])
                    if t.strip():
                        text = t
    except OSError:
        pass
    return text


def blocked_before(session: str, key: str) -> bool:
    STORE.mkdir(parents=True, exist_ok=True)
    f = STORE / (re.sub(r"[^\w-]", "_", session or "unknown")[:80] + ".json")
    try:
        seen = set(json.loads(f.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        seen = set()
    if key in seen:
        return True
    f.write_text(json.dumps(sorted(seen | {key})[-200:]), encoding="utf-8")
    return False


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except ValueError:
        return 0
    if payload.get("hook_event_name") not in (None, "Stop") or payload.get("stop_hook_active"):
        return 0
    path = payload.get("transcript_path") or ""
    message = payload.get("last_assistant_message") or (last_text(path) if path else "")
    hits = check(message, owner_words(path) if path else "")
    if not hits:
        return 0
    session = str(payload.get("session_id") or hashlib.sha1(path.encode()).hexdigest()[:16])
    if blocked_before(session, hashlib.sha1(message.encode("utf-8")).hexdigest()[:16]):
        return 0
    lines = "\n".join(f"- {h['name']}（「{h['at']}」）: {h['fix']}" for h in hits)
    sys.stdout.write(json.dumps({"decision": "block", "reason": (
        "[返事の点検] この返事には、みきさんに言わない約束の書き方が入っている（2026-10-25 本人「意味分からん難しい話を"
        "長々されるのは困る」）。\n" + lines + "\n"
        "この後に書く文だけがみきさんに届く返事になる。該当する所を直した返事の全部を、もう一度書いて終えること"
        "（「直します」「書き直します」などの前置きは書かない。返事が WATCH_NO_CHANGE だけでよい場面なら、それだけを書く）。")},
        ensure_ascii=False))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
