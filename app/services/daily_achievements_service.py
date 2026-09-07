# -*- coding: utf-8 -*-
"""「今日やったこと」台帳 — 証拠収集 + LLM判定 + 台帳更新 + イラスト生成。

証拠源 (全部「差分だけ」読む。読んだ位置は achievement_cursors に保存):
  - dan  : chat_messages (ダンの各部屋の人/AI発言)
  - cli  : ~/.claude/projects/*/*.jsonl (ターミナルの claude code セッション)
  - git  : D:/done, D:/done-artifacts, ~/.dan/workspace の新規 commit + 作業ツリー状態
  - watch: pending_followups の完了

取りこぼし防止: 1回に読む量には上限があるが、上限に当たったら読み位置は
「実際に読めた最後の証拠」までしか進めない (次のサイクルで続きを読む)。
再判定 (force) は上限に当たらなくなるまで同じ日を何回かに分けて回す。

判定は ~/.dan/workspace/ACHIEVEMENT_RULES.md を基準に run_oneshot_cli (定額CLI) が行い、
当日の台帳に対して add / update の操作 JSON を返す。ここでは判断せず、LLM に丸ごと渡す。
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
ILLUST_DIR = _PROJECT_ROOT / "data" / "today_illust"
GPT_IMAGE_SCRIPT = _PROJECT_ROOT / "scripts" / "gpt_image.py"

# 1回の判定に渡す証拠の上限 (プロンプト肥大防止)。超えた分は次サイクルへ持ち越す。
MAX_MSG_CHARS = 1200
MAX_MSGS = 60
MAX_CLI_LINES = 80
MAX_CLI_CHARS = 800
MAX_COMMITS = 40
MAX_LEDGER = 60
MAX_FORCE_ROUNDS = 8

CURSOR_KEY = "achievement_poller"

ICONS = ("mail", "publish", "fix", "build", "research", "money", "doc", "talk", "design", "video", "login", "other")


# ---------------------------------------------------------------------------
# 日付
# ---------------------------------------------------------------------------

def today_jst() -> date:
    return datetime.now(JST).date()


def day_bounds_utc(day: date) -> Tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=JST)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def _sb():
    from app.services.supabase_client import get_supabase_client
    return get_supabase_client().client


def _to_jst(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(JST).strftime("%H:%M")
    except Exception:
        return iso


def _at_to_iso(day: date, hhmm: Any) -> Optional[str]:
    """LLM が返す JST の HH:MM を当日の UTC ISO に。不正なら None。"""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(hhmm or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h < 24 and 0 <= mi < 60):
        return None
    return datetime(day.year, day.month, day.day, h, mi, tzinfo=JST).astimezone(timezone.utc).isoformat()


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


def get_row(row_id: str) -> Optional[Dict[str, Any]]:
    r = _sb().table("daily_achievements").select("*").eq("id", row_id).limit(1).execute()
    return r.data[0] if r.data else None


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


def collect_dan(since_iso: str, until_iso: str) -> Tuple[List[Dict[str, Any]], Optional[str], bool]:
    """ダンの各部屋の発言 (人+AI) を since 以降で取得。
    戻り値: (証拠, 読めた最後の created_at, 上限で切れたか)"""
    try:
        r = (
            _sb().table("chat_messages")
            .select("id,room_id,sender_type,content,created_at")
            .gt("created_at", since_iso).lte("created_at", until_iso)
            .order("created_at").limit(MAX_MSGS + 1).execute()
        )
    except Exception as e:
        logger.warning("chat_messages fetch failed: %s", e)
        return [], None, False
    rows = r.data or []
    truncated = len(rows) > MAX_MSGS
    rows = rows[:MAX_MSGS]
    last_at = rows[-1]["created_at"] if rows else None
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
    return out, last_at, truncated


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
    return sorted(files, key=lambda p: p.stat().st_mtime)


def _short_path(p: str) -> str:
    p = p.replace("\\", "/")
    for root in ("D:/done/", "D:/done-artifacts/"):
        if p.startswith(root):
            return p[len(root):]
    return p.split("/")[-1]


def _cli_record_to_item(rec: Dict[str, Any], t: datetime, label: str) -> Optional[Dict[str, Any]]:
    typ = rec.get("type")
    msg = rec.get("message") or {}
    at = t.astimezone(JST).strftime("%H:%M")
    if typ == "user" and (rec.get("origin") or {}).get("kind") == "human":
        c = msg.get("content")
        if isinstance(c, list):
            c = " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
        if c and str(c).strip():
            return {"at": at, "session": label, "who": "user", "text": _trunc(c, MAX_CLI_CHARS)}
    elif typ == "assistant":
        c = msg.get("content") or []
        texts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
        tools = [b.get("name") for b in c if isinstance(b, dict) and b.get("type") == "tool_use"]
        text = " ".join(x for x in texts if x).strip()
        if text and not tools:  # ツール呼び出しの合間の短文は捨て、ユーザー向けの本文だけ
            return {"at": at, "session": label, "who": "claude", "text": _trunc(text, MAX_CLI_CHARS)}
    elif typ == "file-history-delta":
        files = list((rec.get("trackedFileBackups") or {}).keys())
        if files:
            return {"at": at, "session": label, "who": "edited_files",
                    "text": ", ".join(_short_path(p) for p in files[:12])}
    return None


def collect_cli(offsets: Dict[str, int], since_utc: datetime, until_utc: datetime) -> Tuple[List[Dict[str, Any]], Dict[str, int], bool]:
    """claude code のセッション jsonl を前回のバイト位置から読む。
    上限 (MAX_CLI_LINES) に当たったらそのファイルの読み位置は「読めた行の直後」で止め、
    残りのファイルは触らない (次サイクルで続きを読む)。戻り値: (証拠, 新しい読み位置, 切れたか)"""
    new_offsets = dict(offsets)
    out: List[Dict[str, Any]] = []
    truncated = False
    for path in _iter_cli_files():
        if truncated:
            break
        try:
            st = path.stat()
        except OSError:
            continue
        key = str(path)
        if datetime.fromtimestamp(st.st_mtime, tz=timezone.utc) < since_utc:
            new_offsets.setdefault(key, st.st_size)
            continue
        start = offsets.get(key, 0)
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
        label = f"{path.parent.name}/{path.stem[:8]}"
        end = start + len(blob)
        pos = start
        consumed = start
        for raw in blob.split(b"\n"):
            line_len = len(raw) + 1
            if pos + line_len > end:  # 末尾の改行無し断片 (書き込み途中) は次回へ
                break
            if len(out) >= MAX_CLI_LINES:
                truncated = True
                break
            pos += line_len
            consumed = pos
            try:
                rec = json.loads(raw)
            except Exception:
                continue
            ts = rec.get("timestamp")
            if not ts or rec.get("isSidechain"):
                continue
            try:
                t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
            if t < since_utc or t > until_utc:
                continue
            item = _cli_record_to_item(rec, t, label)
            if item:
                out.append(item)
        new_offsets[key] = consumed if truncated else max(consumed, start)
    return out, new_offsets, truncated


CODEX_SESSIONS = Path.home() / ".codex" / "sessions"
MAX_CODEX_LINES = 60


def collect_codex(offsets: Dict[str, int], since_utc: datetime, until_utc: datetime) -> Tuple[List[Dict[str, Any]], Dict[str, int], bool]:
    """ターミナル Codex CLI (GPT-6) の rollout jsonl。source=cli (本人対話) のみ。
    codex_exec (ダン内部) は chat_messages 側で拾うので除外 (offset=サイズにして再読しない)。"""
    new_offsets = dict(offsets)
    out: List[Dict[str, Any]] = []
    truncated = False
    if not CODEX_SESSIONS.exists():
        return out, new_offsets, truncated
    for path in sorted(CODEX_SESSIONS.glob("*/*/*/rollout-*.jsonl"), key=lambda p: p.stat().st_mtime):
        if truncated:
            break
        try:
            st = path.stat()
        except OSError:
            continue
        key = str(path)
        if datetime.fromtimestamp(st.st_mtime, tz=timezone.utc) < since_utc:
            new_offsets.setdefault(key, st.st_size)
            continue
        start = offsets.get(key, 0)
        if start > st.st_size:
            start = 0
        try:
            with open(path, "rb") as f:
                if start == 0:
                    first = f.readline()
                    try:
                        if (json.loads(first).get("payload") or {}).get("source") != "cli":
                            new_offsets[key] = st.st_size  # ダン内部実行: 以後読まない
                            continue
                    except Exception:
                        pass
                    start = f.tell()
                f.seek(start)
                blob = f.read()
        except OSError:
            continue
        pos = start
        consumed = start
        end = start + len(blob)
        for raw in blob.split(b"\n"):
            line_len = len(raw) + 1
            if pos + line_len > end:
                break
            if len(out) >= MAX_CODEX_LINES:
                truncated = True
                break
            pos += line_len
            consumed = pos
            try:
                r = json.loads(raw)
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
                continue
            try:
                t = datetime.fromisoformat(str(r.get("timestamp")).replace("Z", "+00:00"))
            except Exception:
                continue
            if t < since_utc or t > until_utc:
                continue
            out.append({"at": t.astimezone(JST).strftime("%H:%M"), "session": f"gpt6/{path.stem[-12:]}",
                        "who": "user" if pl["role"] == "user" else "gpt6", "text": _trunc(text, MAX_CLI_CHARS)})
        new_offsets[key] = consumed if truncated else st.st_size
    return out, new_offsets, truncated


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


def collect_git(seen_shas: List[str], since_utc: datetime) -> Tuple[List[Dict[str, Any]], List[str]]:
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
            if len(commits) >= MAX_COMMITS:
                break  # 残りは次サイクル (seen に入れないので拾い直す)
            seen.add(sha)
            new_seen.append(sha)
            in_origin = "origin/" in _git(repo, "branch", "-r", "--contains", sha)
            stat = _trunc(_git(repo, "show", "--stat", "--format=", sha), 300)
            commits.append({
                "repo": name, "sha": sha, "at": _to_jst(at), "subject": _trunc(subj, 160),
                "pushed": in_origin, "files": stat,
            })
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
         "at": _to_jst(r.get("done_at") or r.get("first_seen") or ""), "icon": r.get("icon") or "other",
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
        '  {"op":"add","title":"…","detail":"…","status":"done|in_progress","at":"HH:MM","icon":"種別",'
        '"tags":["未コミット"],"evidence":[{"kind":"commit|room|cli|watch|url","label":"表示名","ref":"sha / project_id / session / url"}]},\n'
        '  {"op":"update","id":"既存行id","status":"done","at":"HH:MM","icon":"種別","title":"(変更時のみ)","detail":"(変更時のみ)","tags":["…"],"evidence_add":[…]}\n'
        "]}\n"
        "at は証拠から読み取れる「その作業が完了(done)または最後に動いた」JST時刻 HH:MM。"
        "既存行の at が明らかに実作業時刻とずれていれば update で at を直してよい。"
        "既存行の icon が other なら、内容に合う種別へ update で直すこと。\n"
        f"icon は次から1つ: {', '.join(ICONS)} "
        "(mail=送受信/連絡, publish=公開/デプロイ/提出, fix=不具合修正, build=機能実装, research=調査/検証, "
        "money=会計/決済/銀行, doc=書類/資料, talk=打合せ/相談, design=デザイン/LP, video=動画/画像制作, login=認証/アカウント設定)。\n"
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


def _clean_icon(v: Any) -> Optional[str]:
    v = str(v or "").strip().lower()
    return v if v in ICONS else None


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
            ev = _clean_evidence(op.get("evidence"))
            at = _at_to_iso(day, op.get("at")) or now
            row = {
                "day": day.isoformat(), "title": title, "detail": _trunc(op.get("detail"), 400) or None,
                "status": status, "tags": [str(t) for t in op.get("tags") or []][:6],
                "sources": _infer_sources(op.get("sources"), ev), "evidence": ev,
                "icon": _clean_icon(op.get("icon")) or "other",
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
            at = _at_to_iso(day, op.get("at"))
            new_status = op.get("status") if op.get("status") in ("done", "in_progress") else None
            if new_status and new_status != cur["status"]:
                patch["status"] = new_status
                if new_status == "done":
                    patch["done_at"] = at or now
            elif at:
                # 時刻の訂正 (状態は変わらない)
                if cur["status"] == "done" and at != cur.get("done_at"):
                    patch["done_at"] = at
                elif cur["status"] != "done" and at != cur.get("first_seen"):
                    patch["first_seen"] = at
            if op.get("title"):
                patch["title"] = _trunc(op["title"], 120)
            if op.get("detail"):
                patch["detail"] = _trunc(op["detail"], 400)
            if isinstance(op.get("tags"), list):
                patch["tags"] = [str(t) for t in op["tags"]][:6]
            icon = _clean_icon(op.get("icon"))
            if icon and icon != cur.get("icon"):
                patch["icon"] = icon
            add = _clean_evidence(op.get("evidence_add"))
            if add:
                existing = cur.get("evidence") or []
                keys = {(e.get("kind"), e.get("ref")) for e in existing}
                merged = existing + [e for e in add if (e.get("kind"), e.get("ref")) not in keys]
                if len(merged) != len(existing):
                    patch["evidence"] = merged[:12]
                    patch["sources"] = _infer_sources(cur.get("sources"), merged)
            if len(patch) > 1:
                try:
                    sb.table("daily_achievements").update(patch).eq("id", rid).execute()
                    changed += 1
                except Exception as e:
                    logger.warning("achievement update failed: %s", e)
    return changed


# ---------------------------------------------------------------------------
# 1サイクル (同期。ポーラーから to_thread で呼ぶ)
# ---------------------------------------------------------------------------

def _judge_batch(day: date, evidence: Dict[str, Any], model: str) -> Tuple[bool, int]:
    """1回分の証拠を LLM に渡して台帳に反映。戻り値: (LLM成功, 変更数)"""
    from app.agent.cli_runner import run_oneshot_cli
    ledger = list_for_day(day)
    text = run_oneshot_cli(build_prompt(day, ledger, evidence), model=model, timeout=180)
    if text is None:
        return False, 0
    return True, apply_ops(day, ledger, _parse_ops(text))


def run_cycle(force: bool = False, model: str = "sonnet") -> Dict[str, Any]:
    """差分証拠を集めて判定し台帳を更新。戻り値は統計。
    force=True は当日 0時から全部読み直す (上限に当たる限り複数回に分けて判定)。"""
    day = today_jst()
    day_start, _ = day_bounds_utc(day)
    now_utc = datetime.now(timezone.utc)
    until_iso = now_utc.isoformat()
    cursor = load_cursor()

    if force or cursor.get("day") != day.isoformat():
        # 日付が変わった / 再判定: 読み位置を今日の 0時に戻す
        cursor = {"day": day.isoformat(), "since": day_start.isoformat(), "cli_offsets": {}, "git_seen": []}

    stats: Dict[str, Any] = {"day": day.isoformat(), "dan": 0, "cli": 0, "commits": 0, "watch": 0,
                             "judged": False, "changed": 0, "rounds": 0}
    rounds_limit = MAX_FORCE_ROUNDS if force else 1
    for _ in range(rounds_limit):
        since_iso = cursor.get("since") or day_start.isoformat()
        since_utc = max(datetime.fromisoformat(since_iso), day_start)

        dan, dan_last, dan_trunc = collect_dan(since_iso, until_iso)
        watch = collect_watch(since_iso, until_iso)
        cli, cli_offsets, cli_trunc = collect_cli(cursor.get("cli_offsets", {}), since_utc, now_utc)
        codex, codex_offsets, codex_trunc = collect_codex(cursor.get("codex_offsets", {}), max(since_utc, day_start), now_utc)
        cli = cli + codex
        cli_trunc = cli_trunc or codex_trunc
        git, git_seen = collect_git(cursor.get("git_seen", []), day_start)
        commits = git[0]["commits"]

        stats["dan"] += len(dan); stats["cli"] += len(cli); stats["commits"] += len(commits); stats["watch"] += len(watch)
        has_new = bool(dan or watch or cli or commits)
        if not has_new:
            # 判定する材料は無いが、読み終えた位置は保存する (同じ行を毎回読み直さない)
            cursor.update({"day": day.isoformat(), "since": until_iso, "cli_offsets": cli_offsets, "codex_offsets": codex_offsets, "git_seen": git_seen})
            save_cursor(cursor)
            break

        stats["rounds"] += 1
        ok, changed = _judge_batch(day, {"dan": dan, "cli": cli, "git": git, "watch": watch}, model)
        if not ok:
            # CLI 失敗: 読み位置を進めず次回に同じ証拠で再挑戦する
            stats["error"] = "oneshot_cli_failed"
            break
        stats["judged"] = True
        stats["changed"] += changed

        # 読み位置は「実際に読めたところ」まで。dan が切れたら最後の発言時刻で止める。
        next_since = dan_last if (dan_trunc and dan_last) else until_iso
        cursor.update({"day": day.isoformat(), "since": next_since, "cli_offsets": cli_offsets, "codex_offsets": codex_offsets,
                       "git_seen": git_seen, "last_run": until_iso})
        save_cursor(cursor)
        stats["carry_over"] = bool(dan_trunc or cli_trunc)
        if not (dan_trunc or cli_trunc):
            break
    return stats


# ---------------------------------------------------------------------------
# イラスト生成 (成果行だけ、判定とは別の後追い処理)
# ---------------------------------------------------------------------------

def illustration_path(row_id: str) -> Path:
    return ILLUST_DIR / f"{row_id}.png"


def generate_illustration(row_id: str, force: bool = False) -> bool:
    """gpt_image.py で 1024x768 low の挿絵を1枚生成して data/today_illust に保存。"""
    row = get_row(row_id)
    if not row:
        return False
    out = illustration_path(row_id)
    if out.exists() and not force:
        return True
    ILLUST_DIR.mkdir(parents=True, exist_ok=True)
    _sb().table("daily_achievements").update({"illustration_status": "pending"}).eq("id", row_id).execute()
    prompt = (
        f"{row['title']}。{row.get('detail') or ''}\n"
        "この出来事を表す挿絵。文字は入れない。"
    )
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE",)}
    try:
        proc = subprocess.run(
            [sys.executable, str(GPT_IMAGE_SCRIPT), "--out", str(out), "--size", "1024x768", "--quality", "low"],
            input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180, cwd=str(_PROJECT_ROOT), env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        ok = proc.returncode == 0 and out.exists()
        if not ok:
            logger.warning("illustration failed for %s: %s", row_id, _trunc(proc.stderr or proc.stdout, 300))
    except Exception as e:
        logger.warning("illustration error for %s: %s", row_id, e)
        ok = False
    _sb().table("daily_achievements").update({
        "illustration_status": "done" if ok else "failed",
        "illustration_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", row_id).execute()
    return ok


def generate_missing_illustrations(day: date, limit: int = 3) -> int:
    """当日の成果行でイラスト未生成のものを最大 limit 件生成。"""
    rows = [r for r in list_for_day(day)
            if r["status"] == "done" and r.get("illustration_status") in (None, "none")]
    n = 0
    for r in rows[:limit]:
        if generate_illustration(r["id"]):
            n += 1
    return n
