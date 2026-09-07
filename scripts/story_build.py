# -*- coding: utf-8 -*-
"""ダン開発の物語 — 週ごとの日記を証拠から生成し、静的HTMLにまとめる。

  python scripts/story_build.py                  # 未生成の週を全部 + 今週(暫定) → 章 → HTML
  python scripts/story_build.py --weeks 2026-W34 # その週だけ作り直す
  python scripts/story_build.py --render         # JSON から HTML だけ再生成
  python scripts/story_build.py --chapters       # 章(あらすじ)だけ作り直す
  python scripts/story_build.py --dry 2026-W34   # 証拠を集めてプロンプトを表示するだけ (LLM を呼ばない)

出力 (ダンの外):
  D:/dan-archive/story/weeks/<YYYY-Www>.json   一度書いたら固定 (--weeks で指定した時だけ作り直す)
  D:/dan-archive/story/chapters.json
  D:/dan-archive/story/index.html               ブラウザで開くだけ

証拠源 (週ごと):
  git    D:/done, D:/done-artifacts, ~/.dan/workspace + ダン以前のリポジトリ (prehistory の bundle を展開)
  chat   chat_messages (ダンとの会話、部屋名つき)
  cursor prehistory/cursor/state.vscdb (Cursor の会話 2025-12-12〜2026-02)
  edits  prehistory/cursor/History (Cursor の編集履歴 2025-11〜)
  memory ~/.dan/workspace/memory/YYYY-MM-DD.md
  today  daily_achievements (2026-08-26〜)
  cli    ~/.claude/history.jsonl (ターミナルで打った指示 2026-01〜)
規則: ~/.dan/workspace/STORY_RULES.md
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

JST = timezone(timedelta(hours=9))
HOME = Path.home()
WORKSPACE = Path(os.environ.get("DAN_WORKSPACE_DIR") or (HOME / ".dan" / "workspace"))
RULES_PATH = WORKSPACE / "STORY_RULES.md"
ARCHIVE = Path(os.environ.get("DAN_ARCHIVE_ROOT") or "D:/dan-archive")
STORY_DIR = ARCHIVE / "story"
WEEKS_DIR = STORY_DIR / "weeks"
PREHISTORY = ARCHIVE / "prehistory"
CURSOR_DB = PREHISTORY / "cursor" / "state.vscdb"
CURSOR_HISTORY = PREHISTORY / "cursor" / "History"
BUNDLE_CHECKOUT = PREHISTORY / "checkout"

FIRST_WEEK_START = date(2025, 11, 3)  # 月曜。bugsnap-ai-v2 (10/30) を含む最初の週
MODEL = os.environ.get("DAN_STORY_MODEL", "sonnet")

REPOS: Dict[str, Path] = {
    "done": Path("D:/done"),
    "done-artifacts": Path("D:/done-artifacts"),
    "dan-workspace": WORKSPACE,
}

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# 1週間ぶんのプロンプトに入れる上限
MAX_COMMITS = 120
MAX_CHAT = 160
MAX_CURSOR = 160
MAX_CLI = 120
CHAT_USER_CHARS = 400
CHAT_AI_CHARS = 220
MEMORY_CHARS = 2500


def log(msg: str) -> None:
    print(f"[story] {datetime.now():%H:%M:%S} {msg}", flush=True)


# ---------------------------------------------------------------------------
# 週
# ---------------------------------------------------------------------------

def week_key(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_bounds(key: str) -> tuple[date, date]:
    y, w = key.split("-W")
    start = date.fromisocalendar(int(y), int(w), 1)
    return start, start + timedelta(days=6)


def all_weeks(until: Optional[date] = None) -> List[str]:
    until = until or datetime.now(JST).date()
    out, d = [], FIRST_WEEK_START
    while d <= until:
        out.append(week_key(d))
        d += timedelta(days=7)
    return out


def current_week() -> str:
    return week_key(datetime.now(JST).date())


def bounds_utc(key: str) -> tuple[datetime, datetime]:
    s, e = week_bounds(key)
    start = datetime(s.year, s.month, s.day, tzinfo=JST)
    return start.astimezone(timezone.utc), (start + timedelta(days=7)).astimezone(timezone.utc)


def _parse_iso(v: str) -> datetime:
    """Python 3.10 の fromisoformat は小数秒 6 桁固定なので桁を揃える。"""
    v = str(v).replace("Z", "+00:00")
    m = re.match(r"^(.*?\.)(\d+)(.*)$", v)
    if m and len(m.group(2)) != 6:
        v = m.group(1) + m.group(2)[:6].ljust(6, "0") + m.group(3)
    return datetime.fromisoformat(v)


def _jst(dt: datetime) -> str:
    return dt.astimezone(JST).strftime("%m/%d %H:%M")


def _trunc(s: Any, n: int) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n] + "…"


# ---------------------------------------------------------------------------
# 証拠: git
# ---------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120, creationflags=NO_WINDOW)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def prehistory_repos() -> Dict[str, Path]:
    """prehistory の bundle を一度だけ展開して git log できるようにする。"""
    out: Dict[str, Path] = {}
    bundles = sorted((PREHISTORY / "repos").glob("*.bundle")) if (PREHISTORY / "repos").exists() else []
    for b in bundles:
        name = b.stem
        dst = BUNDLE_CHECKOUT / name
        if not (dst / ".git").exists():
            BUNDLE_CHECKOUT.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", "-q", str(b), str(dst)], capture_output=True, creationflags=NO_WINDOW)
        if (dst / ".git").exists():
            out[name] = dst
    return out


def collect_git(key: str) -> List[Dict[str, Any]]:
    s, e = bounds_utc(key)
    repos = dict(REPOS)
    repos.update(prehistory_repos())
    commits: List[Dict[str, Any]] = []
    for name, repo in repos.items():
        if not (repo / ".git").exists():
            continue
        log_out = _git(repo, "log", "--all", f"--since={s.isoformat()}", f"--until={e.isoformat()}",
                       "--format=%h%x1f%aI%x1f%s", "--shortstat", "--no-merges")
        cur: Optional[Dict[str, Any]] = None
        for line in log_out.splitlines():
            if "\x1f" in line:
                sha, at, subj = line.split("\x1f", 2)
                try:
                    at_s = _jst(_parse_iso(at))
                except Exception:
                    at_s = at
                cur = {"repo": name, "sha": sha, "at": at_s, "subject": _trunc(subj, 140)}
                commits.append(cur)
            elif cur and "changed" in line:
                cur["stat"] = line.strip()
    commits.sort(key=lambda c: c["at"])
    if len(commits) > MAX_COMMITS:
        step = len(commits) / MAX_COMMITS
        commits = [commits[int(i * step)] for i in range(MAX_COMMITS)]
        commits[0]["note"] = f"(この週は commit が多いため {MAX_COMMITS} 件に間引き)"
    return commits


# ---------------------------------------------------------------------------
# 証拠: ダンとのチャット / 今日の台帳
# ---------------------------------------------------------------------------

def _sb():
    from app.services.supabase_client import get_supabase_client
    return get_supabase_client().client


def collect_chat(key: str) -> List[Dict[str, Any]]:
    s, e = bounds_utc(key)
    try:
        rows: List[Dict[str, Any]] = []
        page = 0
        while True:
            r = (_sb().table("chat_messages").select("room_id,sender_type,content,created_at")
                 .gte("created_at", s.isoformat()).lt("created_at", e.isoformat())
                 .order("created_at").range(page * 1000, page * 1000 + 999).execute())
            rows.extend(r.data or [])
            if len(r.data or []) < 1000:
                break
            page += 1
    except Exception as ex:
        log(f"chat fetch failed {key}: {ex}")
        return []
    rows = [m for m in rows if (m.get("content") or "").strip() and "WATCH_NO_CHANGE" not in (m.get("content") or "")]
    if not rows:
        return []
    room_ids = sorted({m["room_id"] for m in rows})
    titles: Dict[str, str] = {}
    try:
        for i in range(0, len(room_ids), 100):
            pr = _sb().table("projects").select("room_id,title").in_("room_id", room_ids[i:i + 100]).execute()
            for p in pr.data or []:
                titles[p["room_id"]] = p.get("title") or ""
    except Exception:
        pass
    users = [m for m in rows if m.get("sender_type") == "human"]
    ais = [m for m in rows if m.get("sender_type") != "human"]

    def sample(lst: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
        if len(lst) <= n:
            return lst
        step = len(lst) / n
        return [lst[int(i * step)] for i in range(n)]

    picked = sample(users, int(MAX_CHAT * 0.65)) + sample(ais, MAX_CHAT - int(MAX_CHAT * 0.65))
    picked.sort(key=lambda m: m["created_at"])
    out = []
    for m in picked:
        who = "user" if m.get("sender_type") == "human" else "dan"
        out.append({"at": _jst(_parse_iso(m["created_at"])),
                    "room": titles.get(m["room_id"]) or m["room_id"][:8], "who": who,
                    "text": _trunc(m["content"], CHAT_USER_CHARS if who == "user" else CHAT_AI_CHARS)})
    return [{"total_messages": len(rows), "user_messages": len(users), "rooms": len(room_ids), "sample": out}]


def collect_today(key: str) -> List[Dict[str, Any]]:
    s, e = week_bounds(key)
    try:
        r = (_sb().table("daily_achievements").select("day,title,status,detail,tags")
             .gte("day", s.isoformat()).lte("day", e.isoformat()).neq("status", "dismissed")
             .order("day").execute())
        return [{"day": x["day"], "status": x["status"], "title": x["title"], "detail": _trunc(x.get("detail"), 200), "tags": x.get("tags") or []}
                for x in r.data or []]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# 証拠: Cursor (会話 / 編集履歴)
# ---------------------------------------------------------------------------

def collect_cursor(key: str) -> List[Dict[str, Any]]:
    if not CURSOR_DB.exists():
        return []
    s, e = bounds_utc(key)
    try:
        con = sqlite3.connect(f"file:{CURSOR_DB.as_posix()}?mode=ro&immutable=1", uri=True)
    except Exception:
        return []
    names: Dict[str, str] = {}
    for (k, v) in con.execute("select key,value from cursorDiskKV where key like 'composerData:%'"):
        try:
            d = json.loads(v)
            names[d.get("composerId") or k.split(":")[1]] = d.get("name") or ""
        except Exception:
            pass
    rows = []
    for (k, v) in con.execute("select key,value from cursorDiskKV where key like 'bubbleId:%'"):
        if '"createdAt"' not in v:
            continue
        try:
            b = json.loads(v)
        except Exception:
            continue
        ts = b.get("createdAt")
        text = (b.get("text") or "").strip()
        if not ts or not text:
            continue
        try:
            t = _parse_iso(ts)
        except Exception:
            continue
        if not (s <= t < e):
            continue
        comp = k.split(":")[1] if k.count(":") >= 2 else ""
        who = "user" if b.get("type") == 1 else "ai"
        rows.append({"t": t, "at": _jst(t), "conv": names.get(comp) or comp[:8], "who": who,
                     "text": _trunc(text, CHAT_USER_CHARS if who == "user" else CHAT_AI_CHARS)})
    con.close()
    if not rows:
        return []
    rows.sort(key=lambda r: r["t"])
    users = [r for r in rows if r["who"] == "user"]
    ais = [r for r in rows if r["who"] == "ai"]

    def sample(lst, n):
        if len(lst) <= n:
            return lst
        step = len(lst) / n
        return [lst[int(i * step)] for i in range(n)]

    picked = sample(users, int(MAX_CURSOR * 0.7)) + sample(ais, MAX_CURSOR - int(MAX_CURSOR * 0.7))
    picked.sort(key=lambda r: r["t"])
    for r in picked:
        r.pop("t", None)
    return [{"total_messages": len(rows), "user_messages": len(users), "conversations": sorted({r["conv"] for r in rows}), "sample": picked}]


def collect_cursor_edits(key: str) -> List[Dict[str, Any]]:
    if not CURSOR_HISTORY.exists():
        return []
    s, e = bounds_utc(key)
    s_ms, e_ms = s.timestamp() * 1000, e.timestamp() * 1000
    per_day: Dict[str, Dict[str, int]] = {}
    for ent in CURSOR_HISTORY.glob("*/entries.json"):
        try:
            d = json.loads(ent.read_text(encoding="utf-8"))
        except Exception:
            continue
        res = unquote(d.get("resource", "")).replace("file:///", "")
        for it in d.get("entries") or []:
            ts = it.get("timestamp") or 0
            if s_ms <= ts < e_ms:
                day = datetime.fromtimestamp(ts / 1000, JST).strftime("%m/%d")
                per_day.setdefault(day, {})
                per_day[day][res] = per_day[day].get(res, 0) + 1
    out = []
    for day in sorted(per_day):
        files = sorted(per_day[day].items(), key=lambda x: -x[1])
        out.append({"day": day, "edits": sum(n for _, n in files), "top_files": [f for f, _ in files[:8]]})
    return out


# ---------------------------------------------------------------------------
# 証拠: 運用メモ / ターミナル指示
# ---------------------------------------------------------------------------

def collect_memory(key: str) -> List[Dict[str, Any]]:
    s, e = week_bounds(key)
    out = []
    mem = WORKSPACE / "memory"
    if not mem.exists():
        return out
    d = s
    while d <= e:
        p = mem / f"{d.isoformat()}.md"
        if p.exists():
            try:
                out.append({"day": d.isoformat(), "text": _trunc(p.read_text(encoding="utf-8"), MEMORY_CHARS)})
            except Exception:
                pass
        d += timedelta(days=1)
    return out


def collect_cli(key: str) -> List[Dict[str, Any]]:
    p = HOME / ".claude" / "history.jsonl"
    if not p.exists():
        return []
    s, e = bounds_utc(key)
    s_ms, e_ms = s.timestamp() * 1000, e.timestamp() * 1000
    rows = []
    with open(p, encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            ts = r.get("timestamp") or 0
            if s_ms <= ts < e_ms and (r.get("display") or "").strip():
                rows.append({"at": datetime.fromtimestamp(ts / 1000, JST).strftime("%m/%d %H:%M"),
                             "project": os.path.basename(r.get("project") or ""), "text": _trunc(r["display"], CHAT_USER_CHARS)})
    if len(rows) > MAX_CLI:
        step = len(rows) / MAX_CLI
        rows = [rows[int(i * step)] for i in range(MAX_CLI)]
    return rows


CODEX_SESSIONS = HOME / ".codex" / "sessions"
MAX_CODEX = 120


def collect_codex(key: str) -> List[Dict[str, Any]]:
    """ターミナルの Codex CLI (GPT-6) セッション。source=cli (本人が対話) のみ。
    codex_exec (ダン内部実行) は chat_messages 側で拾えるので除外して二重計上を防ぐ。"""
    if not CODEX_SESSIONS.exists():
        return []
    s, e = week_bounds(key)
    rows: List[Dict[str, Any]] = []
    files = 0
    d = s
    while d <= e:
        day_dir = CODEX_SESSIONS / f"{d.year}" / f"{d.month:02d}" / f"{d.day:02d}"
        for f in sorted(day_dir.glob("rollout-*.jsonl")) if day_dir.exists() else []:
            try:
                fh = open(f, encoding="utf-8", errors="ignore")
                meta = json.loads(fh.readline())
                if (meta.get("payload") or {}).get("source") != "cli":
                    continue
                files += 1
                for line in fh:
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    if r.get("type") != "response_item":
                        continue
                    pl = r.get("payload") or {}
                    if pl.get("type") != "message" or pl.get("role") not in ("user", "assistant"):
                        continue
                    texts = [b.get("text", "") for b in pl.get("content") or []
                             if isinstance(b, dict) and b.get("type") in ("input_text", "output_text", "text")]
                    text = " ".join(x for x in texts if x).strip()
                    if not text or (pl["role"] == "user" and text.startswith("<")):
                        continue  # 環境注入 (<recommended_plugins> 等) は捨てる
                    at = str(r.get("timestamp", ""))[:19]
                    try:
                        at = _jst(_parse_iso(r["timestamp"]))
                    except Exception:
                        pass
                    rows.append({"at": at, "who": pl["role"], "text": _trunc(text, CHAT_USER_CHARS if pl["role"] == "user" else CHAT_AI_CHARS)})
            except Exception:
                continue
        d += timedelta(days=1)
    if not rows:
        return []
    users = [r for r in rows if r["who"] == "user"]
    ais = [r for r in rows if r["who"] == "assistant"]

    def sample(lst, n):
        if len(lst) <= n:
            return lst
        step = len(lst) / n
        return [lst[int(i * step)] for i in range(n)]

    picked = sample(users, int(MAX_CODEX * 0.65)) + sample(ais, MAX_CODEX - int(MAX_CODEX * 0.65))
    picked.sort(key=lambda r: r["at"])
    return [{"total_messages": len(rows), "user_messages": len(users), "sessions": files, "sample": picked}]


def collect_all(key: str) -> Dict[str, Any]:
    ev = {
        "git": collect_git(key),
        "chat": collect_chat(key),
        "cursor": collect_cursor(key),
        "cursor_edits": collect_cursor_edits(key),
        "memory": collect_memory(key),
        "today": collect_today(key),
        "cli": collect_cli(key),
        "codex": collect_codex(key),
    }
    ev["stats"] = {
        "commits": len(ev["git"]),
        "chat_messages": ev["chat"][0]["total_messages"] if ev["chat"] else 0,
        "cursor_messages": ev["cursor"][0]["total_messages"] if ev["cursor"] else 0,
        "cursor_edit_days": len(ev["cursor_edits"]),
        "cli_prompts": len(ev["cli"]),
        "codex_messages": ev["codex"][0]["total_messages"] if ev["codex"] else 0,
        "memory_days": len(ev["memory"]),
    }
    return ev


def has_evidence(ev: Dict[str, Any]) -> bool:
    st = ev["stats"]
    return any(st[k] for k in ("commits", "chat_messages", "cursor_messages", "cursor_edit_days", "cli_prompts", "codex_messages", "memory_days"))


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

def load_rules() -> str:
    try:
        return RULES_PATH.read_text(encoding="utf-8")
    except Exception:
        return "本人の一人称・日記風・300〜500字。JSONだけ出力。"


def build_prompt(key: str, ev: Dict[str, Any], prev: Optional[Dict[str, Any]]) -> str:
    s, e = week_bounds(key)
    prev_txt = ""
    if prev:
        prev_txt = f"## 前の週 ({prev.get('week')}) の要約 (文脈用。繰り返さない)\n{prev.get('title')}: {_trunc(prev.get('body'), 400)}\n\n"
        unresolved = [t for t in prev.get("tried") or [] if t.get("result") in ("未決着", "放置")]
        if unresolved:
            prev_txt += "### 前週の未決着 (今週どうなったか必ず判定し tried に入れる。動きが無ければ result:放置 で再掲)" + chr(10) + json.dumps(unresolved, ensure_ascii=False) + chr(10)
    return (
        "あなたは開発者本人の代わりに「ダン（自分専用AIエージェント）開発の物語」の1週間ぶんの日記を書く係です。\n\n"
        f"## 書き方の規則\n{load_rules()}\n\n"
        f"## 対象週\n{key}（{s.isoformat()} 月曜 〜 {e.isoformat()} 日曜、JST）\n\n"
        f"{prev_txt}"
        "## この週の証拠\n"
        "- git: commit (repo/sha/日時/要旨/変更量)。repo 名 jarvis-ui 等はダン以前のプロジェクト\n"
        "- chat: ダンとの会話 (who=user が本人, dan がAI)。sample は間引き済み、total が実数\n"
        "- cursor: Cursor エディタでの会話 (who=user が本人)。conversations は会話名\n"
        "- cursor_edits: Cursor での編集ファイル数 (日別)\n"
        "- memory: ダンの運用メモ (日別)\n"
        "- today: 「今日やったこと」台帳 (本人が納得済みの成果)\n"
        "- cli: ターミナルの Claude Code に本人が打った指示\n"
        f"{json.dumps({k: v for k, v in ev.items() if k != 'stats'}, ensure_ascii=False)}\n\n"
        f"## 統計\n{json.dumps(ev['stats'], ensure_ascii=False)}\n\n"
        "## 出力\nJSON オブジェクトだけを出力 (前後に説明・コードフェンス禁止)。キー: title, body, stumbles(配列), turning_point(文字列, 無ければ空), tried(配列: {what, why, result: 成功|失敗|未決着|放置, note}), ability_delta(文字列), evidence(配列)。"
    )


def _parse_json(text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    m = re.search(r"\{.*\}", s, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def judge_week(key: str, ev: Dict[str, Any], prev: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    from app.agent.cli_runner import run_oneshot_cli
    prompt = build_prompt(key, ev, prev)
    text = run_oneshot_cli(prompt, model=MODEL, timeout=420)
    obj = _parse_json(text)
    if not obj or not obj.get("title"):
        log(f"judge failed {key}: {_trunc(text, 200)}")
        return None
    tried = []
    for t in obj.get("tried") or []:
        if isinstance(t, dict) and str(t.get("what") or "").strip():
            tried.append({"what": _trunc(t.get("what"), 90), "why": _trunc(t.get("why"), 160),
                          "result": t.get("result") if t.get("result") in ("成功", "失敗", "未決着", "放置") else "未決着",
                          "note": _trunc(t.get("note"), 160)})
    return {
        "title": _trunc(obj.get("title"), 60),
        "body": str(obj.get("body") or "").strip(),
        "stumbles": [str(x) for x in obj.get("stumbles") or [] if str(x).strip()],
        "turning_point": str(obj.get("turning_point") or "").strip(),
        "tried": tried[:24],
        "ability_delta": _trunc(obj.get("ability_delta"), 240),
        "evidence": [e for e in obj.get("evidence") or [] if isinstance(e, dict)][:16],
    }


# ---------------------------------------------------------------------------
# 週ファイル
# ---------------------------------------------------------------------------

def week_path(key: str) -> Path:
    return WEEKS_DIR / f"{key}.json"


def load_week(key: str) -> Optional[Dict[str, Any]]:
    p = week_path(key)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_week(key: str, force: bool = False, dry: bool = False) -> Optional[Dict[str, Any]]:
    existing = load_week(key)
    provisional = key == current_week()
    if existing and not force and not existing.get("provisional"):
        return existing
    ev = collect_all(key)
    s, e = week_bounds(key)
    if not has_evidence(ev):
        rec = {"week": key, "start": s.isoformat(), "end": e.isoformat(), "empty": True,
               "title": "動いていない週", "body": "", "stumbles": [], "turning_point": "", "tried": [], "ability_delta": "", "evidence": [],
               "stats": ev["stats"], "provisional": provisional, "generated_at": datetime.now(JST).isoformat()}
        if not dry:
            WEEKS_DIR.mkdir(parents=True, exist_ok=True)
            week_path(key).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"{key}: no evidence")
        return rec
    prev_key = week_key(s - timedelta(days=7))
    prev = load_week(prev_key) if prev_key >= week_key(FIRST_WEEK_START) else None
    if dry:
        print(build_prompt(key, ev, prev))
        print("\n[prompt chars]", len(build_prompt(key, ev, prev)))
        return None
    log(f"{key}: judging (commits={ev['stats']['commits']} chat={ev['stats']['chat_messages']} cursor={ev['stats']['cursor_messages']} cli={ev['stats']['cli_prompts']})")
    j = judge_week(key, ev, prev)
    if not j:
        return existing
    rec = {"week": key, "start": s.isoformat(), "end": e.isoformat(), "empty": False, **j,
           "stats": ev["stats"], "provisional": provisional, "generated_at": datetime.now(JST).isoformat()}
    WEEKS_DIR.mkdir(parents=True, exist_ok=True)
    week_path(key).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"{key}: {rec['title']}")
    return rec


# ---------------------------------------------------------------------------
# 章 (あらすじ)
# ---------------------------------------------------------------------------

def build_chapters(weeks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    from app.agent.cli_runner import run_oneshot_cli
    items = [{"week": w["week"], "start": w["start"], "title": w["title"], "summary": _trunc(w.get("body"), 260),
              "turning_point": w.get("turning_point") or "",
              "ability_delta": w.get("ability_delta") or "",
              "tried": [{"what": t.get("what"), "result": t.get("result")} for t in w.get("tried") or []]}
             for w in weeks if not w.get("empty")]
    if not items:
        return None
    prompt = (
        "以下は「ダン（自分専用AIエージェント）開発」の週ごとの日記の要約です（本人の一人称）。"
        "これを 4〜9 個の「章」に区切り、章ごとに題名と 2〜3 文のあらすじを本人の一人称で書いてください。"
        "章の区切りは方針転換・新しい柱の着手・大きな事故など、物語として意味のある節目に。"
        "全体を通した「これまでのあらすじ」も 5〜8 文で。証拠に無いことは書かない。"
        "各章に加えて abilities: その章が終わった時点で本当にダンにできること (3〜8個、ability_delta と本文の積み上げから)。faded: その章の間に始まったが以降語られなくなった/放置になった構想・機能 ({name, why_started, last_week})。tried の result=放置 や後の週に現れない what が候補。無ければ空配列。\n\n"
        f"{json.dumps(items, ensure_ascii=False)}\n\n"
        "JSON だけを出力 (コードフェンス禁止):\n"
        '{"synopsis":"…","chapters":[{"title":"…","from_week":"2025-W45","to_week":"2025-W50","summary":"…","abilities":["…"],"faded":[{"name":"…","why_started":"…","last_week":"…"}]}]}'
    )
    obj = _parse_json(run_oneshot_cli(prompt, model=MODEL, timeout=420))
    if not obj or not obj.get("chapters"):
        log("chapters failed")
        return None
    obj["generated_at"] = datetime.now(JST).isoformat()
    (STORY_DIR / "chapters.json").write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"chapters: {len(obj['chapters'])}")
    return obj


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_CSS = """
:root{--bg:#0f1115;--card:#171a21;--fg:#e8eaf0;--mut:#8b92a5;--line:#262a35;--acc:#3ddc97;--warn:#f5b342;--red:#ff6b6b}
@media (prefers-color-scheme: light){:root{--bg:#f7f7f9;--card:#fff;--fg:#1a1c22;--mut:#6b7180;--line:#e3e5ea}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.75 system-ui,-apple-system,"Segoe UI","Hiragino Sans","Noto Sans JP",sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:40px 22px 80px}
h1{font-size:26px;margin:0 0 4px}.sub{color:var(--mut);font-size:13px;margin-bottom:28px}
.syn{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px 22px;margin-bottom:28px;white-space:pre-wrap}
.toc{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:34px}.toc a{font-size:12px;color:var(--mut);border:1px solid var(--line);border-radius:999px;padding:3px 10px;text-decoration:none}.toc a:hover{color:var(--fg)}
h2.ch{font-size:20px;margin:44px 0 6px;padding-top:18px;border-top:2px solid var(--line)}
.chsum{color:var(--mut);margin:0 0 18px;white-space:pre-wrap}
.week{position:relative;padding-left:26px;margin:0 0 26px;border-left:2px solid var(--line)}
.week:before{content:"";position:absolute;left:-7px;top:10px;width:12px;height:12px;border-radius:50%;background:var(--acc);border:2px solid var(--bg)}
.week.empty:before{background:var(--line)}.week.prov:before{background:var(--warn)}
.wk{font-size:12px;color:var(--mut)}.wt{font-size:18px;font-weight:600;margin:2px 0 8px}
.body{white-space:pre-wrap}.st{margin:10px 0 0;padding:10px 14px;border-left:3px solid var(--red);background:color-mix(in srgb,var(--red) 8%,transparent);border-radius:6px;font-size:14px}
.tp{margin:10px 0 0;padding:10px 14px;border-left:3px solid var(--acc);background:color-mix(in srgb,var(--acc) 8%,transparent);border-radius:6px;font-size:14px}
.ev{margin-top:10px;font-size:12px;color:var(--mut)}.ev span{display:inline-block;border:1px solid var(--line);border-radius:6px;padding:1px 7px;margin:2px 4px 2px 0}
.tried{margin-top:10px;font-size:13px}.tried li{margin:2px 0;color:var(--mut)}.tried .r{display:inline-block;width:4.2em;font-size:11px;border-radius:5px;text-align:center;padding:0 4px;margin-right:6px}.r-ok{background:color-mix(in srgb,var(--acc) 18%,transparent);color:var(--acc)}.r-ng{background:color-mix(in srgb,var(--red) 16%,transparent);color:var(--red)}.r-wip{background:color-mix(in srgb,var(--warn) 18%,transparent);color:var(--warn)}.r-drop{background:var(--line);color:var(--mut)}.tried .why{opacity:.8}.abil{margin:10px 0 0;padding:10px 14px;border-left:3px solid #7aa2ff;background:color-mix(in srgb,#7aa2ff 8%,transparent);border-radius:6px;font-size:14px}.chmeta{font-size:13px;color:var(--mut);margin:0 0 14px}.chmeta b{color:var(--fg)}.chmeta .faded-x{color:var(--red)}.shots{margin-top:10px}.shotrow{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}.shotrow img{width:220px;border:1px solid var(--line);border-radius:8px;display:block}.stats{font-size:11px;color:var(--mut);margin-top:6px}.foot{color:var(--mut);font-size:12px;margin-top:50px}
"""


def collect_shots(key: str) -> List[str]:
    """その週に撮ったUIスクショの相対パス (story/index.html から見た "shots/日付/名前.png")。"""
    shots_dir = STORY_DIR / "shots"
    if not shots_dir.exists():
        return []
    s, e = week_bounds(key)
    out: List[str] = []
    d = s
    while d <= e:
        day_dir = shots_dir / d.isoformat()
        if day_dir.exists():
            out.extend(f"shots/{d.isoformat()}/{f.name}" for f in sorted(day_dir.glob("*.png")))
        d += timedelta(days=1)
    return out


def render(weeks: List[Dict[str, Any]], chapters: Optional[Dict[str, Any]]) -> Path:
    def esc(x: Any) -> str:
        return html.escape(str(x or ""))

    def week_html(w: Dict[str, Any]) -> str:
        cls = "week" + (" empty" if w.get("empty") else "") + (" prov" if w.get("provisional") else "")
        st = w.get("stats") or {}
        stats = f"commit {st.get('commits', 0)} ・ ダン会話 {st.get('chat_messages', 0)} ・ Cursor {st.get('cursor_messages', 0)} ・ CLI {st.get('cli_prompts', 0)}"
        parts = [f'<article class="{cls}" id="{esc(w["week"])}">',
                 f'<div class="wk">{esc(w["week"])} ・ {esc(w["start"])} 〜 {esc(w["end"])}{" ・ 今週（暫定）" if w.get("provisional") else ""}</div>',
                 f'<div class="wt">{esc(w.get("title"))}</div>']
        if w.get("body"):
            parts.append(f'<div class="body">{esc(w["body"])}</div>')
        if w.get("stumbles"):
            parts.append('<div class="st">つまずき: ' + " ／ ".join(esc(x) for x in w["stumbles"]) + "</div>")
        if w.get("turning_point"):
            parts.append(f'<div class="tp">転機: {esc(w["turning_point"])}</div>')
        if w.get("tried"):
            rmap = {"成功": "r-ok", "失敗": "r-ng", "未決着": "r-wip", "放置": "r-drop"}
            lis = []
            for t in w["tried"]:
                why = f' <span class="why">— {esc(t.get("why"))}</span>' if t.get("why") else ""
                note = f' <span class="why">({esc(t.get("note"))})</span>' if t.get("note") else ""
                lis.append(f'<li><span class="r {rmap.get(t.get("result"), "r-wip")}">{esc(t.get("result"))}</span>{esc(t.get("what"))}{why}{note}</li>')
            parts.append('<details class="tried"><summary style="cursor:pointer;color:var(--mut);font-size:12px">やろうとしたこと ' + str(len(lis)) + ' 件</summary><ul style="margin:6px 0 0;padding-left:18px">' + "".join(lis) + "</ul></details>")
        if w.get("ability_delta"):
            parts.append(f'<div class="abil">この週の変化: {esc(w["ability_delta"])}</div>')
        shots = collect_shots(w["week"])
        if shots:
            imgs = "".join(f'<a href="{esc(u)}" target="_blank"><img src="{esc(u)}" loading="lazy" alt="" title="{esc(u.split(chr(47))[-1])}"></a>' for u in shots)
            parts.append('<details class="shots"><summary style="cursor:pointer;color:var(--mut);font-size:12px">当時のUIスクショ ' + str(len(shots)) + ' 枚</summary><div class="shotrow">' + imgs + "</div></details>")
        if w.get("evidence"):
            parts.append('<div class="ev">' + "".join(f'<span title="{esc(e.get("ref"))}">{esc(e.get("kind"))}: {esc(e.get("label") or e.get("ref"))}</span>' for e in w["evidence"]) + "</div>")
        parts.append(f'<div class="stats">{stats}</div></article>')
        return "\n".join(parts)

    by_key = {w["week"]: w for w in weeks}
    keys = sorted(by_key)
    out = ['<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
           "<title>ダン開発の物語</title>", f"<style>{_CSS}</style></head><body><div class=\"wrap\">",
           "<h1>ダン開発の物語</h1>",
           f'<div class="sub">{esc(keys[0] if keys else "")} 〜 {esc(keys[-1] if keys else "")} ・ {len([w for w in weeks if not w.get("empty")])} 週 ・ 生成 {datetime.now(JST):%Y-%m-%d %H:%M}（証拠: git / ダンとの会話 / Cursor / 運用メモ / 今日の台帳）</div>']
    if chapters and chapters.get("synopsis"):
        out.append(f'<div class="syn"><strong>これまでのあらすじ</strong>\n{esc(chapters["synopsis"])}</div>')
    chs = (chapters or {}).get("chapters") or []
    if chs:
        out.append('<div class="toc">' + "".join(f'<a href="#ch{i}">{esc(c.get("title"))}</a>' for i, c in enumerate(chs)) + "</div>")
        covered = set()
        for i, c in enumerate(chs):
            out.append(f'<h2 class="ch" id="ch{i}">{esc(c.get("title"))} <small style="font-weight:400;color:var(--mut);font-size:12px">{esc(c.get("from_week"))} 〜 {esc(c.get("to_week"))}</small></h2>')
            out.append(f'<p class="chsum">{esc(c.get("summary"))}</p>')
            meta = []
            if c.get("abilities"):
                meta.append("<b>この時点のダンにできること:</b> " + " ／ ".join(esc(a) for a in c["abilities"]))
            if c.get("faded"):
                meta.append('<span class="faded-x"><b>立ち消えたもの:</b> ' + " ／ ".join(
                    esc(f.get("name")) + (f"（{esc(f.get('why_started'))}）" if f.get("why_started") else "") for f in c["faded"]) + "</span>")
            if meta:
                out.append('<p class="chmeta">' + "<br>".join(meta) + "</p>")
            for k in keys:
                if c.get("from_week", "") <= k <= c.get("to_week", "") and k not in covered:
                    covered.add(k)
                    out.append(week_html(by_key[k]))
        rest = [k for k in keys if k not in covered]
        if rest:
            out.append('<h2 class="ch">（章未分類）</h2>')
            out.extend(week_html(by_key[k]) for k in rest)
    else:
        out.extend(week_html(by_key[k]) for k in keys)
    out.append(f'<div class="foot">書き方の規則: {esc(RULES_PATH)} ／ 週の作り直し: python scripts/story_build.py --weeks 2026-W34 ／ 週ごとの JSON: {esc(WEEKS_DIR)}</div>')
    out.append("</div></body></html>")
    STORY_DIR.mkdir(parents=True, exist_ok=True)
    p = STORY_DIR / "index.html"
    p.write_text("\n".join(out), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", nargs="*", help="作り直す週 (例: 2026-W34)。省略時は未生成の週 + 今週")
    ap.add_argument("--chapters", action="store_true", help="章(あらすじ)を作り直す")
    ap.add_argument("--render", action="store_true", help="HTML だけ再生成")
    ap.add_argument("--dry", help="この週の証拠とプロンプトを表示するだけ")
    ap.add_argument("--limit", type=int, default=0, help="この回で判定する週数の上限 (0=無制限)")
    args = ap.parse_args()

    if args.dry:
        build_week(args.dry, force=True, dry=True)
        return 0

    made = 0
    if not args.render:
        targets = args.weeks if args.weeks else [k for k in all_weeks() if not load_week(k) or load_week(k).get("provisional")]
        for k in targets:
            if args.limit and made >= args.limit:
                log(f"limit {args.limit} reached; stopping")
                break
            before = load_week(k)
            rec = build_week(k, force=bool(args.weeks))
            if rec and rec is not before:
                made += 1
    weeks = [w for w in (load_week(k) for k in all_weeks()) if w]
    chapters = None
    if (args.chapters or (made and not args.weeks)) and not args.render:
        chapters = build_chapters(weeks)
    if chapters is None and (STORY_DIR / "chapters.json").exists():
        try:
            chapters = json.loads((STORY_DIR / "chapters.json").read_text(encoding="utf-8"))
        except Exception:
            chapters = None
    p = render(weeks, chapters)
    log(f"rendered {p} ({len(weeks)} weeks, made {made})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
