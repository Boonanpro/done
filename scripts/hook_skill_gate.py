# -*- coding: utf-8 -*-
"""PreToolUse(Write|Edit|MultiEdit) hook: スキルの文章はスキルクリエイターを通してしか書けない。

2026-10-16 本人の依頼: 「ルールとして書いて読むことを祈るんじゃなくて、使わないと
スキルファイルが触れないようにする」。指摘を写しただけの修正案を、手順を通さずに
出したことがきっかけ。

対象: `.claude/skills/` の下の .md（examples/ と汎化の記録は除く）と、どこにあっても
SKILL.md という名前のファイル。シェル経由の書き込みは対象外（本人了承）。

通す条件（全部満たした時だけ書ける）:
  1. 同じ作業の記録（transcript_path。Claude も Codex も渡す）の道具の結果に、
     skill-creator の SKILL.md と references/generalization.md の見出しが全部出ている
     （= 2つを読んだ）。要約(compact)の後は、要約の後に読み直したものだけ数える。
  2. 変更するスキルの sources/generalization-log.md に、この作業で書いた項目があり、
     その「変更するファイル」に今のファイルが入っていて、種類ごとの欄がそろっている。
  3. その項目を別の AI（Claude CLI・定額）が generalization.md の C の基準で判定して合格。
     同じ文の項目は一度だけ判定して覚えておく。判定できない時は止める。

汎化の記録そのものは条件1だけで書ける（書けないと先へ進めないため）。
exit 0 = 許可 / exit 2 = ブロック（stderr がモデルへの返事になる）。
"""
import json
import os
import sys

LOG_NAME = "generalization-log.md"
CREATOR_DIR = "D:/done/.claude/skills/skill-creator"
CACHE = "D:/done/.data/skill_gate/judged.json"
JUDGE_TIMEOUT = int(os.environ.get("DAN_SKILL_GATE_TIMEOUT", "90"))
JUDGE_VERSION = "1"

FIELDS = {
    "指摘": ["具体の指摘", "受け手に起きていなかったこと", "一般則", "技", "別テーマでの例"],
    "実例": ["実例と区切り", "次へ進む理由", "出どころ", "技", "別テーマでの例"],
    "操作": ["何を直したか", "確かめたこと"],
}


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
    for rel in ("SKILL.md", "references/generalization.md"):
        hs = _headings(f"{CREATOR_DIR}/{rel}")
        if not hs or any(h not in result_text for h in hs):
            missing.append(f"{CREATOR_DIR}/{rel}")
    return missing


def _parse_entries(text: str):
    entries, cur = [], None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = {"heading": line.strip(), "lines": [line]}
            entries.append(cur)
        elif cur is not None:
            cur["lines"].append(line)
    for e in entries:
        body = "\n".join(e["lines"]).strip()
        e["text"] = body
        fields, key = {}, None
        for line in e["lines"][1:]:
            s = line.strip()
            if s.startswith("- ") and ":" in s[2:].replace("：", ":"):
                k, v = s[2:].replace("：", ":", 1).split(":", 1)
                key = k.strip()
                fields[key] = v.strip()
            elif key and s:
                fields[key] = (fields[key] + "\n" + s).strip()
        e["fields"] = fields
    return entries


def _field_problems(e):
    f = e["fields"]
    kind = f.get("種類", "").strip()
    if kind not in FIELDS:
        return [f"「種類」が「指摘・実例・操作」のどれでもない（今: {kind or '空'}）"]
    return [f"「{k}」が空" for k in FIELDS[kind] if not f.get(k, "").strip()]


def _load_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _save_cache(cache):
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        tmp = CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1)
        os.replace(tmp, CACHE)
    except OSError:
        pass


def _section_c() -> str:
    try:
        with open(f"{CREATOR_DIR}/references/generalization.md", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return ""
    return text


JUDGE_PROMPT = """あなたはスキルの文章の検査役です。書いた本人とは別の目で、汎化の記録が「写し」になっていないかを判定します。
基準は次の手順書です（特に C の3つの確認と表）。

<手順書>
{guide}
</手順書>

<記録の項目>
{entry}
</記録の項目>

判定のしかた:
- 種類が「指摘」「実例」なら、C の3つを確かめる。
  1. 元の指摘・実例を知らない人が「技」だけを読んで、別のテーマで手を動かせるか（何を・どこに・どういう形で が分かるか）。
  2. 「別テーマでの例」が材料と本当に違うテーマで、その「技」を使った例になっているか。
  3. 「技」が具体すぎ（指摘や実例の言い換え・その案件の固有の物でしか成り立たない）でも、抽象すぎ（目標だけで手の動かし方が無い）でもないか。
- 種類が「操作」なら、変更が本当に壊れやすい仕様・正確な手順・確かめ方（操作の知識）で、腕の技（書き方・見せ方・判断のこつ）を「操作」と偽っていないか。「確かめたこと」が実際に動かした結果になっているか。
- 本人の好み（使わない言葉など）や案件の事実（URL・数字）を事実としてそのまま書くのは写しではない。

出力は JSON 1つだけ（前後に何も書かない）:
{{"pass": true か false, "problems": [{{"field": "欄の名前", "quote": "問題の箇所の抜き出し", "reason": "なぜ写し・抽象すぎ・不足なのか、どう直せばよいか（1〜2文）"}}]}}
合格なら problems は空の配列。"""


def _judge(entry_text: str):
    """(合格か, 問題の説明, 覚えてよいか)。判定できなければ不合格・覚えない。"""
    import shutil
    import subprocess
    import tempfile

    exe = shutil.which("claude") or shutil.which("claude.cmd")
    if not exe:
        return False, "判定役の Claude CLI が見つからないため止めました。", False
    prompt = JUDGE_PROMPT.format(guide=_section_c(), entry=entry_text)
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)  # 定額のログインで動かす（従量課金にしない）
    env.pop("CLAUDECODE", None)
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [exe, "-p", "--model", os.environ.get("DAN_SKILL_GATE_MODEL", "sonnet"),
           "--output-format", "json", "--tools", "", "--strict-mcp-config",
           "--no-session-persistence"]
    try:
        with tempfile.TemporaryDirectory() as tmp:  # 判定役に関所や他の設定を読ませない
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=JUDGE_TIMEOUT, cwd=tmp, env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    except subprocess.TimeoutExpired:
        return False, f"判定が {JUDGE_TIMEOUT} 秒で終わらなかったため止めました。もう一度書き込めば判定し直します。", False
    except Exception as e:  # noqa: BLE001
        return False, f"判定役を起動できなかったため止めました（{e}）。", False
    out = (proc.stdout or "").strip()
    try:
        result = json.loads(out).get("result", "")
    except Exception:  # noqa: BLE001
        result = out
    s, e = result.find("{"), result.rfind("}")
    try:
        verdict = json.loads(result[s:e + 1])
    except Exception:  # noqa: BLE001
        tail = (proc.stderr or out)[-300:]
        return False, f"判定役の答えを読めなかったため止めました（{tail}）。もう一度書き込めば判定し直します。", False
    if verdict.get("pass") is True:
        return True, "", True
    lines = []
    for p in verdict.get("problems") or []:
        lines.append(f"- {p.get('field', '')}: 「{p.get('quote', '')}」→ {p.get('reason', '')}")
    return False, "\n".join(lines) or "不合格（理由なし）", True


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
    root, rel = hit
    log_path = f"{root}/sources/{LOG_NAME}"
    is_log = _norm(path).lower() == log_path.lower()

    result_text, write_text = _read_transcript(payload.get("transcript_path") or "")
    missing = _missing_reads(result_text)
    if missing:
        _block(
            "スキルの文章は、スキルクリエイターの手順を読んでからでないと書けません。\n"
            "先に次を全部読んでください（Read か check_skill skill-creator＋generalization.md）:\n"
            + "\n".join(f"- {m}" for m in missing)
            + "\nシェルで読むなら文字コードを指定する（PowerShell: Get-Content -Encoding UTF8 <パス>）。"
            "指定しないと日本語が文字化けし、読んだことになりません。"
            + "\n読んだ後、変更の理由を汎化の記録 " + log_path + " に書いてから、もう一度書き込んでください。"
        )
    if is_log:
        return 0

    try:
        with open(log_path, encoding="utf-8") as f:
            entries = _parse_entries(f.read())
    except OSError:
        entries = []
    mine = [e for e in entries if e["heading"] in write_text]
    fmt = (
        "形式（種類ごとに欄を全部書く）:\n"
        "## 2026-10-16 〈技の名前〉\n- 種類: 指摘 / 実例 / 操作\n- 変更するファイル: title-cover.md\n"
        "- （指摘）具体の指摘 / 受け手に起きていなかったこと / 一般則 / 技 / 別テーマでの例\n"
        "- （実例）実例と区切り / 次へ進む理由 / 出どころ / 技 / 別テーマでの例\n"
        "- （操作）何を直したか / 確かめたこと"
    )
    if not mine:
        _block(
            f"この作業で書いた汎化の記録が {log_path} にありません。\n"
            "generalization.md の手順で、今回の変更の理由を記録に書いてから書き込んでください。\n" + fmt
        )
    target_names = {rel.lower(), rel.lower().rsplit("/", 1)[-1]}
    covering = [
        e for e in mine
        if any(n in e["fields"].get("変更するファイル", "").lower() for n in target_names)
    ]
    if not covering:
        _block(
            f"この作業の汎化の記録に、{rel} を変える項目がありません。"
            "今回の項目の「変更するファイル」に、このファイルの名前を書いてください。\n" + fmt
        )

    cache = _load_cache()
    import hashlib

    failures = []
    for e in covering:
        probs = _field_problems(e)
        if probs:
            failures.append(f"{e['heading']}\n" + "\n".join(f"- {p}" for p in probs))
            continue
        key = hashlib.sha256((JUDGE_VERSION + "\n" + e["text"]).encode("utf-8")).hexdigest()
        hit_cache = cache.get(key)
        if hit_cache is None:
            ok, why, keep = _judge(e["text"])
            if keep:
                cache[key] = {"pass": ok, "why": why, "heading": e["heading"]}
                _save_cache(cache)
        else:
            ok, why = hit_cache["pass"], hit_cache["why"]
        if not ok:
            failures.append(f"{e['heading']}\n{why}")
    if failures:
        _block(
            "汎化の記録が、別の AI の判定（generalization.md の C の基準）で通りませんでした。"
            "記録を直してから、もう一度書き込んでください。\n\n" + "\n\n".join(failures)
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
