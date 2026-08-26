# -*- coding: utf-8 -*-
"""「今日やったこと」台帳 — 証拠収集 + LLM判定 + 台帳更新。

証拠源 (全部「差分だけ」読む。読んだ位置は achievement_cursors に保存):
  - dan  : chat_messages (ダンの各部屋の人/AI発言) + agent_runs の完了
  - cli  : ~/.claude/projects/*/*.jsonl (ターミナルの claude code セッション)
  - git  : D:/done, D:/done-artifacts, ~/.dan/workspace の新規 commit + 作業ツリー状態
  - watch: pending_followups の完了

判定は ~/.dan/workspace/ACHIEVEMENT_RULES.md を基準に run_oneshot_cli (定額CLI) が行い、
当日の台帳に対して add / update の操作 JSON を返す。ここでは判断せず、LLM に丸ごと渡す。
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

WORKSPACE_DIR = Path(os.environ.get("DAN_WORKSPACE_DIR") or (Path.home() / ".dan" / "workspace"))
RULES_PATH = WORKSPACE_DIR / "ACHIEVEMENT_RULES.md"
CLI_PROJECTS_DIR = Path.home() / ".claude" / "projects"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
GIT_REPOS: List[Path] = [
    _PROJECT_ROOT,
    Path(os.environ.get("DAN_DONE_ARTIFACTS_DIR") or "D:/done-artifacts"),
    WORKSPACE_DIR,
]

# 1回の判定に渡す証拠の上限 (プロンプト肥大防止)
MAX_MSG_CHARS = 1200
MAX_MSGS = 60
MAX_CLI_LINES = 80
MAX_CLI_CHARS = 800
MAX_COMMITS = 40
MAX_LEDGER = 60

CURSOR_KEY = "achievement_poller"


# ---------------------------------------------------------------------------
# 日付
# ---------------------------------------------------------------------------

def today_jst() -> date:
    return datetime.now(JST).date()


def day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=JST)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def _sb():
    from app.services.supabase_client import get_supabase_client
    return get_supabase_client().client


# ---------------------------------------------------------------------------
# 台帳 CRUD
# ---------------------------------------------------------------------------

def list_for_day(day: date) -> List[Dict[str, Any]]:
    r = (
        _sb().table("daily_achievements").select("*")
        .eq("day", day.isoformat()).neq("status", "dismissed")
        .order("first_seen").execute()
    )
    return r.data or []


def list_days(limit: int = 30) -> List[str]:
    r = (
        _sb().table("daily_achievements").select("day")
        .order("day", desc=True).limit(500).execute()
    )
    seen: List[str] = []
    for row in r.data or []:
        d = row["day"]
        if d not in seen:
            seen.append(d)
        if len(seen) >= limit:
            break
    return seen


def update_row(row_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    patch = dict(patch)
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    if patch.get("status") == "done":
        patch.setdefault("done_at", patch["updated_at"])
    r = _sb().table("daily_achievements").update(patch).eq("id", row_id).execute()
    return r.data[0] if r.data else None


# ---------------------------------------------------------------------------
# カーソル
# ---------------------------------------------------------------------------

def load_cursor() -> Dict[str, Any]:
    try:
        r = _sb().table("achievement_cursors").select("value").eq("key", CURSOR_KEY).limit(1).execute()
        return dict(r.data[0]["value"]) if r.data else {}
    except Exception as e:
        logger.warning("achievement cursor load failed: %s", e)
        return {}


def save_cursor(value: Dict[str, Any]) -> None:
    try:
        _sb().table("achievement_cursors").upsert({
            "key": CURSOR_KEY, "value": value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        logger.warning("achievement cursor save failed: %s", e)


# ---------------------------------------------------------------------------
# 証拠収集
# ---------------------------------------------------------------------------

def _trunc(s: Any, n: int) -> str:
    s = "" if s is None else str(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n] + "…"


def _room_titles(room_ids: List[str]) -> Dict[str, Dict[str, str]]:
    """room_id → {title, project_id}。/chat/<project_id> が部屋のURL。"""
    if not room_ids:
        return {}
    out: Dict[str, Dict[str, str]] = {}
    try:
        r = _sb().table("projects").select("id,room_id,title").in_("room_id", room_ids).execute()
        for p in r.data or []:
            out[p["room_id"]] = {"title": p.get("title") or "", "project_id": p["id"]}
    except Exception as e:
        logger.warning("room title lookup failed: %s", e)
    return out


def collect_dan(since_iso: str, until_iso: str) -> List[Dict[str, Any]]:
    """ダンの各部屋の発言 (人+AI) を since 以降で取得。"""
    try:
        r = (
            _sb().table("chat_messages")
            .select("id,room_id,sender_type,content,created_at")
            .gt("created_at", since_iso).lte("created_at", until_iso)
            .order("created_at").limit(MAX_MSGS).execute()
        )
    except Exception as e:
        logger.warning("chat_messages fetch failed: %s", e)
        return []
    rows = r.data or []
    rooms = _room_titles(sorted({m["room_id"] for m in rows}))
    out = []
    for m in rows:
        content = m.get("content") or ""
        if not content.strip() or "WATCH_NO_CHANGE" in content:
            continue
        info = rooms.get(m["room_id"], {})
        out.append({
            "at": _to_jst(m["created_at"]),
            "room": info.get("title") or m["room_id"][:8],
            "project_id": info.get("project_id"),
            "who": "user" if m.get("sender_type") == "human" else "dan",
            "text": _trunc(content, MAX_MSG_CHARS),
        })
    return out


def collect_watch(since_iso: str, until_iso: str) -> List[Dict[str, Any]]:
    try:
        r = (
            _sb().table("pending_followups").select("id,room_id,note,status,updated_at")
            .eq("status", "done").gt("updated_at", since_iso).lte("updated_at", until_iso)
            .order("updated_at").limit(20).execute()
        )
    except Exception as e:
        logger.warning("pending_followups fetch failed: %s", e)
        return []
    return [{"at": _to_jst(w["updated_at"]), "id": w["id"], "note": _trunc(w.get("note"), 300)} for w in r.data or []]


def _to_jst(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(JST).strftime("%H:%M")
    except Exception:
        return iso


def _iter_cli_files() -> List[Path]:
    if not CLI_PROJECTS_DIR.exists():
        return []
    files: List[Path] = []
    for proj in CLI_PROJECTS_DIR.iterdir():
        if not proj.is_dir():
            continue
        # oneshot 用の cwd (自分自身の判定プロンプト) は除外
        if "oneshot" in proj.name.lower():
            continue
        files.extend(p for p in proj.glob("*.jsonl") if p.is_file())
    return files


def collect_cli(offsets: Dict[str, int], since_utc: datetime, until_utc: datetime) -> tuple[List[Dict[str, Any]], Dict[str, int]]:
    """claude code のセッション jsonl を前回のバイト位置から読み、人の発言/最終テキスト/編集ファイルを抜く。"""
    new_offsets = dict(offsets)
    out: List[Dict[str, Any]] = []
    for path in _iter_cli_files():
        try:
            st = path.stat()
        except OSError:
            continue
        # 今日触られていないファイルは読まない
        if datetime.fromtimestamp(st.st_mtime, tz=timezone.utc) < since_utc:
            new_offsets.setdefault(str(path), st.st_size)
            continue
        start = offsets.get(str(path), 0)
        if start > st.st_size:  # 切り詰め/新規
            start = 0
        if start == 0 and st.st_size > 2_000_000:
            # 初回に巨大セッションを丸ごと読まない: 末尾 1MB だけ
            start = st.st_size - 1_000_000
        try:
            with open(path, "rb") as f:
                f.seek(start)
                blob = f.read()
        except OSError:
            continue
        new_offsets[str(path)] = st.st_size
        proj = path.parent.name
        session = path.stem[:8]
        for raw in blob.splitlines():
            if len(out) >= MAX_CLI_LINES * 4:
                break
            try:
                rec = json.loads(raw)
            except Exception:
                continue
            ts = rec.get("timestamp")
            if not ts:
                continue
            try:
                t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
            if t < since_utc or t > until_utc:
                continue
            if rec.get("isSidechain"):
                continue
            typ = rec.get("type")
            msg = rec.get("message") or {}
            if typ == "user" and (rec.get("origin") or {}).get("kind") == "human":
                c = msg.get("content")
                if isinstance(c, list):
                    c = " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
                if c and str(c).strip():
                    out.append({"at": t.astimezone(JST).strftime("%H:%M"), "session": f"{proj}/{session}",
                                "who": "user", "text": _trunc(c, MAX_CLI_CHARS)})
            elif typ == "assistant":
                c = msg.get("content") or []
                texts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
                tools = [b.get("name") for b in c if isinstance(b, dict) and b.get("type") == "tool_use"]
                text = " ".join(x for x in texts if x).strip()
                if text and not tools:  # ツール呼び出しの合間の短文は捨て、ユーザー向けの本文だけ
                    out.append({"at": t.astimezone(JST).strftime("%H:%M"), "session": f"{proj}/{session}",
                                "who": "claude", "text": _trunc(text, MAX_CLI_CHARS)})
            elif typ == "file-history-delta":
                files = list((rec.get("trackedFileBackups") or {}).keys())
                if files:
                    out.append({"at": t.astimezone(JST).strftime("%H:%M"), "session": f"{proj}/{session}",
                                "who": "edited_files", "text": ", ".join(_short_path(p) for p in files[:12])})
    # 人の発言と本文を優先して上限に丸める
    if len(out) > MAX_CLI_LINES:
        pri = [o for o in out if o["who"] == "user"]
        rest = [o for o in out if o["who"] != "user"]
        out = (pri + rest)[:MAX_CLI_LINES]
        out.sort(key=lambda o: o["at"])
    return out, new_offsets


def _short_path(p: str) -> str:
    p = p.replace("\\", "/")
    for root in ("D:/done/", "D:/done-artifacts/"):
        if p.startswith(root):
            return p[len(root):]
    return p.split("/")[-1]


def _git(repo: Path, *args: str, timeout: int = 20) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def collect_git(seen_shas: List[str], since_utc: datetime) -> tuple[List[Dict[str, Any]], List[str]]:
    commits: List[Dict[str, Any]] = []
    seen = set(seen_shas)
    new_seen = list(seen_shas)
    for repo in GIT_REPOS:
        if not (repo / ".git").exists():
            continue
        name = repo.name
        log = _git(repo, "log", "--all", f"--since={since_utc.isoformat()}", "--format=%h%x1f%aI%x1f%s", "-n", "60")
        for line in log.splitlines():
            parts = line.split("\x1f")
            if len(parts) != 3:
                continue
            sha, at, subj = parts
            if sha in seen:
                continue
            seen.add(sha)
            new_seen.append(sha)
            # main に入っているか (push/merge 済みかの目安)
            on_main = bool(_git(repo, "branch", "--contains", sha, "--format=%(refname:short)").strip())
            in_origin = "origin/" in _git(repo, "branch", "-r", "--contains", sha)
            stat = _trunc(_git(repo, "show", "--stat", "--format=", sha), 300)
            commits.append({
                "repo": name, "sha": sha, "at": _to_jst(at), "subject": _trunc(subj, 160),
                "pushed": in_origin, "on_branch": on_main, "files": stat,
            })
        if len(commits) >= MAX_COMMITS:
            break
    # 作業ツリーの現在状態 (未コミットの規模を伝える)
    wt: List[Dict[str, Any]] = []
    for repo in GIT_REPOS:
        if not (repo / ".git").exists():
            continue
        status = _git(repo, "status", "--porcelain")
        lines = [l for l in status.splitlines() if l.strip()]
        if lines:
            wt.append({"repo": repo.name, "uncommitted_files": len(lines),
                       "sample": [_short_path(l[3:]) for l in lines[:10]]})
    return [{"commits": commits, "working_tree": wt}], new_seen[-500:]


# ---------------------------------------------------------------------------
# LLM 判定
# ---------------------------------------------------------------------------

_DEFAULT_RULES = "成果=本番/公開に届いた・動いた・相手に届いた。未コミットでも完了なら成果(tagに未コミット)。"


def load_rules() -> str:
    try:
        return RULES_PATH.read_text(encoding="utf-8")
    except Exception:
        return _DEFAULT_RULES


def build_prompt(day: date, ledger: List[Dict[str, Any]], evidence: Dict[str, Any]) -> str:
    ledger_view = [
        {"id": r["id"], "title": r["title"], "status": r["status"], "tags": r.get("tags") or [],
         "detail": r.get("detail") or "", "evidence": r.get("evidence") or []}
        for r in ledger[:MAX_LEDGER]
    ]
    return (
        "あなたは開発者本人の「今日やったこと」台帳を更新する係です。判断は必ず下の判定基準に従い、"
        "証拠に裏付けの無い『完了』を成果にしないでください。\n\n"
        f"## 判定基準\n{load_rules()}\n\n"
        f"## 対象日 (JST)\n{day.isoformat()}\n\n"
        "## 現在の台帳 (この日の既存行。同じ件は新規追加せず update すること)\n"
        f"{json.dumps(ledger_view, ensure_ascii=False)}\n\n"
        "## 新しく観測された証拠 (前回判定以降の差分のみ)\n"
        "- dan: ダンの各部屋のチャット (who=user が本人, dan がAI)。project_id は部屋URL用\n"
        "- cli: ターミナルの claude code セッション (who=user が本人, claude がAI, edited_files は編集ファイル)\n"
        "- git: 新規コミット (pushed=origin に到達済み) と作業ツリーの未コミット状況\n"
        "- watch: 完了した見張り(予約タスク)\n"
        f"{json.dumps(evidence, ensure_ascii=False)}\n\n"
        "## 出力\n"
        "JSON オブジェクトだけを出力 (前後に説明・コードフェンス禁止):\n"
        '{"ops":[\n'
        '  {"op":"add","title":"…","detail":"…","status":"done|in_progress","at":"HH:MM","tags":["未コミット"],'
        '"sources":["dan","cli","git","watch"],"evidence":[{"kind":"commit|room|cli|watch|url","label":"表示名","ref":"sha / project_id / session / url"}]},\n'
        '  {"op":"update","id":"既存行id","status":"done","at":"HH:MM","title":"(変更時のみ)","detail":"(変更時のみ)","tags":["…"],"evidence_add":[…]}\n'
        "]}\n"
        "at は証拠から読み取れる「その作業が完了(done)または最後に動いた」JST時刻 HH:MM (不明なら省略)。"
        "何も追加/更新する価値が無ければ {\"ops\":[]} を返す。evidence の room は ref に project_id、"
        "commit は ref に sha、cli は ref に session を入れる。title/detail は日本語。"
    )


def _parse_ops(text: Optional[str]) -> List[Dict[str, Any]]:
    if not text:
        return []
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.S)
    m = re.search(r"\{.*\}", s, flags=re.S)
    if not m:
        return []
    try:
        obj = json.loads(m.group(0))
    except Exception:
        logger.warning("achievement judge returned non-JSON: %s", _trunc(s, 200))
        return []
    ops = obj.get("ops") if isinstance(obj, dict) else None
    return [o for o in ops or [] if isinstance(o, dict)]


def apply_ops(day: date, ledger: List[Dict[str, Any]], ops: List[Dict[str, Any]]) -> int:
    by_id = {r["id"]: r for r in ledger}
    now = datetime.now(timezone.utc).isoformat()
    changed = 0
    sb = _sb()
    for op in ops:
        kind = op.get("op")
        if kind == "add":
            title = _trunc(op.get("title"), 120)
            if not title:
                continue
            status = op.get("status") if op.get("status") in ("done", "in_progress") else "in_progress"
            at = _at_to_iso(day, op.get("at")) or now
            row = {
                "day": day.isoformat(), "title": title, "detail": _trunc(op.get("detail"), 400) or None,
                "status": status, "tags": [str(t) for t in op.get("tags") or []][:6],
                "sources": _infer_sources(op.get("sources"), _clean_evidence(op.get("evidence"))),
                "evidence": _clean_evidence(op.get("evidence")),
                "first_seen": at, "updated_at": now, "done_at": at if status == "done" else None,
            }
            try:
                sb.table("daily_achievements").insert(row).execute()
                changed += 1
            except Exception as e:
                logger.warning("achievement insert failed: %s", e)
        elif kind == "update":
            rid = op.get("id")
            cur = by_id.get(rid)
            if not cur:
                continue
            patch: Dict[str, Any] = {"updated_at": now}
            if op.get("status") in ("done", "in_progress") and op["status"] != cur["status"]:
                patch["status"] = op["status"]
                if op["status"] == "done":
                    patch["done_at"] = _at_to_iso(day, op.get("at")) or now
            if op.get("title"):
                patch["title"] = _trunc(op["title"], 120)
            if op.get("detail"):
                patch["detail"] = _trunc(op["detail"], 400)
            if isinstance(op.get("tags"), list):
                patch["tags"] = [str(t) for t in op["tags"]][:6]
            add = _clean_evidence(op.get("evidence_add"))
            if add:
                existing = cur.get("evidence") or []
                keys = {(e.get("kind"), e.get("ref")) for e in existing}
                merged = existing + [e for e in add if (e.get("kind"), e.get("ref")) not in keys]
                patch["evidence"] = merged[:12]
            if len(patch) > 1:
                try:
                    sb.table("daily_achievements").update(patch).eq("id", rid).execute()
                    changed += 1
                except Exception as e:
                    logger.warning("achievement update failed: %s", e)
    return changed


def _at_to_iso(day: date, hhmm: Any) -> Optional[str]:
    """LLM が返す JST の HH:MM を当日の UTC ISO に。不正なら None。"""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(hhmm or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h < 24 and 0 <= mi < 60):
        return None
    return datetime(day.year, day.month, day.day, h, mi, tzinfo=JST).astimezone(timezone.utc).isoformat()


_EVIDENCE_TO_SOURCE = {"commit": "git", "room": "dan", "cli": "cli", "watch": "watch"}


def _infer_sources(given: Any, evidence: List[Dict[str, str]]) -> List[str]:
    out = [s for s in (given or []) if s in ("dan", "cli", "git", "watch")]
    for e in evidence:
        src = _EVIDENCE_TO_SOURCE.get(e.get("kind", ""))
        if src and src not in out:
            out.append(src)
    return out


def _clean_evidence(items: Any) -> List[Dict[str, str]]:
    out = []
    for e in items or []:
        if not isinstance(e, dict):
            continue
        kind = str(e.get("kind") or "url")
        if kind not in ("commit", "room", "cli", "watch", "url", "mail"):
            kind = "url"
        out.append({"kind": kind, "label": _trunc(e.get("label"), 80), "ref": _trunc(e.get("ref"), 300)})
    return out[:12]


# ---------------------------------------------------------------------------
# 1サイクル (同期。ポーラーから to_thread で呼ぶ)
# ---------------------------------------------------------------------------

def run_cycle(force: bool = False, model: str = "sonnet") -> Dict[str, Any]:
    """差分証拠を集めて判定し台帳を更新。戻り値は統計。"""
    day = today_jst()
    day_start, day_end = day_bounds_utc(day)
    now_utc = datetime.now(timezone.utc)
    cursor = load_cursor()

    # 日付が変わったら差分位置は「今日の0時」に戻す (前日の残りは前日分として確定済み扱い)
    if cursor.get("day") != day.isoformat():
        cursor = {"day": day.isoformat(), "since": day_start.isoformat(), "cli_offsets": cursor.get("cli_offsets", {}), "git_seen": []}
    since_iso = cursor.get("since") or day_start.isoformat()
    since_utc = datetime.fromisoformat(since_iso)
    until_iso = now_utc.isoformat()

    if force:
        # 再判定: 今日の証拠を全部読み直す (判定基準を直した後など)
        since_iso, since_utc = day_start.isoformat(), day_start
        dan = collect_dan(since_iso, until_iso)
        watch = collect_watch(since_iso, until_iso)
        cli, cli_offsets = collect_cli({}, day_start, now_utc)
        git, git_seen = collect_git([], day_start)
    else:
        dan = collect_dan(since_iso, until_iso)
        watch = collect_watch(since_iso, until_iso)
        cli, cli_offsets = collect_cli(cursor.get("cli_offsets", {}), max(since_utc, day_start), now_utc)
        git, git_seen = collect_git(cursor.get("git_seen", []), day_start)

    has_new = bool(dan or watch or cli or git[0]["commits"])
    stats = {"day": day.isoformat(), "dan": len(dan), "cli": len(cli), "commits": len(git[0]["commits"]),
             "watch": len(watch), "judged": False, "changed": 0}
    if not has_new and not force:
        return stats

    ledger = list_for_day(day)
    evidence = {"dan": dan, "cli": cli, "git": git, "watch": watch}
    prompt = build_prompt(day, ledger, evidence)

    from app.agent.cli_runner import run_oneshot_cli
    text = run_oneshot_cli(prompt, model=model, timeout=180)
    if text is None:
        # CLI 失敗: カーソルを進めず次回に同じ証拠で再挑戦する
        stats["error"] = "oneshot_cli_failed"
        return stats
    ops = _parse_ops(text)
    stats["judged"] = True
    stats["changed"] = apply_ops(day, ledger, ops)

    cursor.update({"day": day.isoformat(), "since": until_iso, "cli_offsets": cli_offsets,
                   "git_seen": git_seen, "last_run": until_iso})
    save_cursor(cursor)
    return stats
