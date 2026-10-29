# -*- coding: utf-8 -*-
"""PreToolUse(Write|Edit|MultiEdit) hook: スキルの文章はスキルクリエイターを読んでからしか書けない。

2026-10-16 本人の依頼: 「ルールとして書いて読むことを祈るんじゃなくて、使わないと
スキルファイルが触れないようにする」。

2026-10-29: スキルクリエイターを Anthropic 公式の版に戻した。公式とダンの書き直し版で同じ材料から
台本スキルを直し、伏せて読み比べた3本で、ダン版が勝った物が無かったため（本人の判断）。
それまでの汎化の記録（sources/generalization-log.md）と別の AI の判定は、ダン版の手順にだけあった物なので外した。

対象: `.claude/skills/` の下の .md（examples/ は除く）と、どこにあっても SKILL.md という名前のファイル。
シェル経由の書き込みは対象外（本人了承）。

通す条件: 同じ作業の記録（transcript_path。Claude も Codex も渡す）の道具の結果に、
skill-creator の SKILL.md の見出しが全部出ている（= 読んだ）。要約(compact)の後は、要約の後に読み直したものだけ数える。
exit 0 = 許可 / exit 2 = ブロック（stderr がモデルへの返事になる）。
"""
import json
import os
import sys
from pathlib import Path

CREATOR_DIR = (Path(__file__).resolve().parent.parent / ".claude/skills/skill-creator").as_posix()


def _norm(p: str) -> str:
    return os.path.normpath(p).replace("\\", "/")


def _target(path: str):
    """スキルの文章なら (スキルのフォルダ, フォルダからの相対パス) を返す。対象外は None。"""
    p = _norm(path)
    low = p.lower()
    name = low.rsplit("/", 1)[-1]
    marker = "/.claude/skills/"
    if marker in low:
        i = low.index(marker) + len(marker)
        rest = p[i:].split("/")
        if len(rest) < 2:
            return None
        root = p[:i] + rest[0]
        rel = "/".join(rest[1:])
        rl = rel.lower()
        if not rl.endswith(".md") or rl.startswith("examples/") or "/examples/" in rl:
            return None
        return root, rel
    if name == "skill.md":
        return p.rsplit("/", 1)[0], p.rsplit("/", 1)[1]
    return None


def _block(msg: str) -> None:
    sys.stderr.buffer.write(("[スキルの関所] " + msg).encode("utf-8"))
    sys.stderr.flush()
    sys.exit(2)


def _strings(obj, out):
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _strings(v, out)


def _read_transcript(path: str):
    """(道具の結果の文字, 書き込みに使った文字) を、最後の要約より後の分だけ返す。"""
    results, writes = [], []
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return "", ""
    with f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            t = d.get("type")
            payload = d.get("payload") if isinstance(d.get("payload"), dict) else {}
            pt = payload.get("type")
            # 要約で前の会話が消えた所。ここより前に読んだ物は手元に残っていない。
            if (t == "system" and d.get("subtype") == "compact_boundary") or t == "compacted":
                results, writes = [], []
                continue
            if t == "user":  # Claude: 道具の結果
                msg = d.get("message") or {}
                content = msg.get("content")
                if isinstance(content, list) and any(
                    isinstance(c, dict) and c.get("type") == "tool_result" for c in content
                ):
                    _strings(content, results)
            elif t == "assistant":  # Claude: 道具の呼び出し（書いた文）
                for c in (d.get("message") or {}).get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        _strings(c.get("input"), writes)
            elif t == "response_item" and pt in ("custom_tool_call_output", "function_call_output"):
                _strings(payload.get("output"), results)  # Codex: 道具の結果
            elif t == "response_item" and pt in ("custom_tool_call", "function_call"):
                _strings(payload.get("input") or payload.get("arguments"), writes)
            elif t == "event_msg" and pt == "item_completed":
                item = payload.get("item") or {}
                if item.get("type") == "FileChange":
                    _strings(item.get("changes"), writes)
    return "\n".join(results), "\n".join(writes)


def _headings(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return [l.strip() for l in f if l.startswith("## ")]
    except OSError:
        return []


def _missing_reads(result_text: str):
    missing = []
    for rel in ("SKILL.md",):
        hs = _headings(f"{CREATOR_DIR}/{rel}")
        if not hs or any(h not in result_text for h in hs):
            missing.append(f"{CREATOR_DIR}/{rel}")
    return missing


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:  # noqa: BLE001
        return 0
    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not path:
        return 0
    hit = _target(path)
    if not hit:
        return 0
    result_text, _ = _read_transcript(payload.get("transcript_path") or "")
    missing = _missing_reads(result_text)
    if missing:
        _block(
            "スキルの文章は、スキルクリエイターの手順を読んでからでないと書けません。\n"
            "先に次を全部読んでください（Read か check_skill skill-creator）:\n"
            + "\n".join(f"- {m}" for m in missing)
            + "\n読んだ後、もう一度書き込んでください。"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
