# -*- coding: utf-8 -*-
"""Stop hook: 編集した動画を渡すターンは、動画の手順書を読み、前の版への本人の言葉を記録してからでないと終われない。

2026-11-09 本人:「フィードバックを返すたびにスキルが良くなっていっているか。言われた所だけ直すのでなく汎用化して
スキルに積み、まだ指摘していない所も自分で直す挙動になっているか」。調べると、中村さんの特典動画を作った担当は
11/4〜11/9 に talking-demo-editing を一度も開かず、11月の指摘は手順書に1つも入っていなかった。本人は 11/9 に
「触れてない先の部分も共通の改善点があれば改善して」と自分で言う必要があった。手順書に書くだけでは読まれない。

このターンで、30秒以上の動画をチャットに貼った（attach_image の [添付動画: …]、または返事の中の印）なら、次の2つが要る。
  1. 動画の手順書のどれか（talking-demo-editing・post-production など）の SKILL.md を、この作業の中で読んだ
     （要約の後なら要約の後に読み直した）。読んだかは見出しが道具の結果に全部出たかで見る（hook_skill_gate と同じ）。
  2. その部屋で前に動画を渡した後の本人の発言が、全部 `video_learning.py record` で記録されている（指摘か、ほかの話か）。
     指摘を記録する時は、同じ決まりを全編のどこに当てはめたかを書く。記録すると、裏で手順書を育てる仕事が起きる。
部屋が分からない（DAN_ROOM_ID が無い）・発言を読めない時は通す。同じ理由で止めるのは2回まで。
exit 0 = 通す / stdout に {"decision":"block","reason":…} = 続けさせる（Claude と Codex で同じ形）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from hook_artifact_verify_gate import _is_turn_start, _texts  # noqa: E402

SKILLS = ROOT / ".claude" / "skills"
VIDEO_SKILLS = ("talking-demo-editing", "post-production", "explainer-video", "video-draft", "studio",
                "creative-studio", "popout", "video-direction")
UPLOADS = Path(os.environ.get("DAN_UPLOADS_DIR") or (ROOT / "uploads"))
STORE = Path(os.environ.get("DAN_VIDEO_GATE_DIR") or (ROOT / ".data" / "video_gate"))
MIN_SECONDS = 30
MAX_BLOCKS = 2
VIDEO_RE = re.compile(r"\[添付動画[:：][^\]]*?\((/api/v1/files/[^)\s]+)\)\s*\]")
ATTACH_TOOL = re.compile(r"attach_image$")
TOOL = "python /Users/mikihonda/done/scripts/video_learning.py"


def read_transcript(path: str) -> tuple[str, list[str]]:
    """(この作業で読んだ道具の結果の文字（最後の要約より後）, このターンで渡した動画の URL)。"""
    results: list[str] = []
    delivered: list[str] = []
    names: dict[str, str] = {}
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return "", []
    with f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            t = d.get("type")
            p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
            pt = p.get("type")
            if (t == "system" and d.get("subtype") == "compact_boundary") or t == "compacted":
                results = []
                continue
            msg = d.get("message") if isinstance(d.get("message"), dict) else None
            if msg is not None and t == "user":
                content = msg.get("content")
                # 画像を読んだ時の添え書き（isMeta）と、裏の仕事の知らせは、同じターンの途中に入る。ターンの始まりにしない
                companion = d.get("isMeta") or d.get("turnCompanion") or (d.get("origin") or {}).get("kind") == "task-notification"
                if not companion and _is_turn_start(content):
                    delivered = []
                    continue
                for b in content if isinstance(content, list) else []:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        texts: list[str] = []
                        _texts(b.get("content"), texts)
                        results += texts
                        if ATTACH_TOOL.search(names.get(str(b.get("tool_use_id")), "")):
                            delivered += VIDEO_RE.findall("\n".join(texts))
                continue
            if msg is not None and t == "assistant":
                for b in msg.get("content") or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        names[str(b.get("id"))] = str(b.get("name") or "")
                    elif b.get("type") == "text":
                        delivered += VIDEO_RE.findall(b.get("text") or "")
                continue
            if pt in ("function_call", "custom_tool_call"):
                names[str(p.get("call_id"))] = str(p.get("name") or "")
            elif pt in ("function_call_output", "custom_tool_call_output"):
                texts = []
                _texts(p.get("output"), texts)
                results += texts
                if ATTACH_TOOL.search(names.get(str(p.get("call_id")), "")):
                    delivered += VIDEO_RE.findall("\n".join(texts))
            elif pt == "message" and p.get("role") == "user" and _is_turn_start(p.get("content")):
                delivered = []
            elif pt == "message" and p.get("role") == "assistant":
                texts = []
                _texts(p.get("content"), texts)
                delivered += VIDEO_RE.findall("\n".join(texts))
    return "\n".join(results), delivered


def seconds(url: str) -> float | None:
    path = UPLOADS / url.rsplit("/", 1)[-1]
    if not path.is_file():
        return None
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=15).stdout.strip()
        return float(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def edited_videos(urls: list[str]) -> list[str]:
    """30秒より短い物（録音の切り抜き・効果音の見本）は編集した動画として数えない。長さが分からない物は数える。"""
    out = []
    for u in dict.fromkeys(urls):
        s = seconds(u)
        if s is None or s >= MIN_SECONDS:
            out.append(u)
    return out


def skill_read(results: str) -> bool:
    for name in VIDEO_SKILLS:
        try:
            heads = [l.strip() for l in (SKILLS / name / "SKILL.md").read_text(encoding="utf-8").splitlines()
                     if l.startswith("## ")]
        except OSError:
            continue
        if heads and all(h in results for h in heads):
            return True
    return False


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


REWRITE = ("この確かめと記録のことは本人への返事に書かない。この後に書く文が、本人に届く返事の全部になる"
           "（止められる前に書いた文は届かない）。済んだら、渡す動画の印 [添付動画: …] と本人への説明を、もう一度全部書いて終えること。")


def block(reason: str) -> int:
    sys.stdout.write(json.dumps({"decision": "block", "reason": "[動画の関所] " + reason}, ensure_ascii=False))
    sys.stdout.flush()
    return 0


def open_feedback(room: str) -> list[dict] | None:
    try:
        from app.services import video_learning as V
        return V.pending(room)
    except Exception:  # noqa: BLE001 — 発言を読めない時は止めない
        return None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except ValueError:
        return 0
    if payload.get("hook_event_name") not in (None, "Stop", "SubagentStop"):
        return 0
    room = os.environ.get("DAN_ROOM_ID") or ""
    path = payload.get("transcript_path") or payload.get("agent_transcript_path") or ""
    if not room or not path:
        return 0
    results, delivered = read_transcript(path)
    delivered += VIDEO_RE.findall(payload.get("last_assistant_message") or "")
    videos = edited_videos(delivered)
    if not videos:
        return 0
    session = str(payload.get("session_id") or hashlib.sha1(path.encode()).hexdigest()[:16])
    if not skill_read(results):
        if count_block(session, "skill:" + ",".join(videos)) <= MAX_BLOCKS:
            return block(
                "編集した動画を渡す前に、その種類の動画の手順書を読むこと。話す人（本人・お客さん・声を当てた人物）と、"
                "実画面・実物・図・イラストで見せる動画は /Users/mikihonda/done/.claude/skills/talking-demo-editing/SKILL.md"
                "（今作っている案件の決まりの references も）。ほかの種類なら post-production・explainer-video など合う物。"
                "読んだら、手順書の「渡す前の点検」と、本人の指摘の後なら「指摘を受けた時」に照らして動画を見直し、"
                "合わない所を直してから渡す。" + REWRITE)
    rows = open_feedback(room)
    if rows:
        ids = [m["id"] for m in rows]
        if count_block(session, "fb:" + ",".join(ids)) <= MAX_BLOCKS:
            lines = "\n".join(f"  {m['id']}  {str(m.get('created_at', ''))[:16]}  {' '.join((m.get('content') or '').split())[:120]}"
                              for m in rows[:20])
            return block(
                "この部屋で前に動画を渡した後の本人の発言が、まだ記録されていない:\n" + lines + "\n"
                "動画への指摘なら、言われた所だけでなく、その指摘から作った決まり（見る人に何が起きていたか）で全編を見直し、"
                "まだ言われていない所にも当てはめて直す（本人が決めた条件は変えない・頼まれていない加工は足さない）。"
                "その上で記録する:\n"
                f"  {TOOL} record --feedback <指摘のid …> --other <ほかの話のid …> "
                "--applied \"<当てはめた所を納品版の分・秒で。無ければ理由>\" --video \"<版>\"\n"
                "（ほかの話が多い時は --rest-other で、指摘以外を全部ほかの話にできる）。"
                "記録すると、裏で動画の手順書を育てる仕事が起きる。" + REWRITE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
