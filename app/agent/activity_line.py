"""The one line the chat shows while Dan works (「お店のページを見ています」).

The chat no longer lists Dan's tool calls (2026-10-23, ダン開発室「返事を人の短さに」). While a turn runs it shows
moving dots and one short line that is rewritten as each tool starts. That line comes from here, is saved with the
tool_use execution event (metadata.activity) and read by the PC screen and the phone app alike, so every backend
(Claude CLI, Codex) and every screen says the same thing.

Rules for the words: plain Japanese the owner would use, no tool names, no paths or commands. Background work
(watches, memory, saved info, credentials, attaching a file) returns "" so the line keeps what it said before:
the owner is not told about it (SOUL.md, 裏の作業には触れない).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# Background work: the line does not change for these.
_SILENT = {
    "watch", "schedule_followup", "preference", "remember_personal_info", "get_personal_info", "save_credentials",
    "get_credentials", "save_totp_secret", "attach_image", "TodoWrite", "ToolSearch", "chrome_signin", "feed",
    "flow", "wait_until", "session_status", "hold", "release",
}


def _base_name(name: str) -> str:
    """mcp__dan-tools__browser / dan-tools.browser / mcp:dan-tools/browser → browser"""
    n = name or ""
    for sep in ("__", "/", ":", "."):
        if sep in n:
            n = n.rsplit(sep, 1)[-1]
    return n


def _host(url: Any) -> str:
    if not isinstance(url, str) or not url.strip():
        return ""
    try:
        host = urlparse(url.strip()).hostname or ""
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _short(text: Any, limit: int = 24) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _browser(tool_input: dict) -> str:
    action = str(tool_input.get("action") or "")
    host = _host(tool_input.get("url"))
    if action in ("open", "open_target"):
        return f"{host} を開いています" if host else "ページを開いています"
    if action in ("fill_credential", "fill_totp_code", "wait_for_otp_from_app", "wait_for_link_from_app"):
        return "ログインしています"
    if action in ("solve_captcha", "human_click", "human_drag", "puzzle_fit"):
        return "確認の画面を通っています"
    if action in ("read", "find", "content", "screenshot", "scroll", "wait_for", "evaluate"):
        return "ページを読んでいます"
    if action in ("hold", "release", "session_status", "close"):
        return ""
    return "ページを操作しています"


def activity_phrase(name: str, tool_input: dict | None = None) -> str:
    """The line for one tool call, or "" to keep the previous line."""
    n = _base_name(name)
    a = tool_input if isinstance(tool_input, dict) else {}
    if n in _SILENT:
        return ""
    if n in ("browser",):
        return _browser(a)
    if n in ("browser_plan", "browser_script", "browser_flow"):
        return "ページを操作しています"
    if n in ("web_search", "WebSearch"):
        q = _short(a.get("query"))
        return f"「{q}」を調べています" if q else "調べています"
    if n in ("read_url", "WebFetch"):
        host = _host(a.get("url"))
        return f"{host} を読んでいます" if host else "ページを読んでいます"
    if n == "places":
        return "近くのお店を探しています"
    if n == "get_location":
        return "今いる場所を確かめています"
    if n == "lookup":
        src = a.get("source")
        return {"mail": "メールを見ています", "messages": "前の会話を見ています", "message_cards": "送った連絡を見ています",
                "inquiries": "問い合わせを見ています"}.get(src, "記録を見ています")
    if n in ("Read", "Glob", "Grep", "read_file", "glob", "grep", "LS"):
        return "資料を読んでいます"
    if n in ("Edit", "Write", "MultiEdit", "NotebookEdit", "write_file", "edit_file"):
        return "書いています"
    if n in ("Bash", "bash", "command_execution", "exec_command", "shell", "execute_command", "run_command"):
        return "作業しています"
    if n == "compose_message":
        return "文面を用意しています"
    if n == "confirm_card":
        return "確認の準備をしています"
    if n in ("check_skill", "Skill"):
        return "やり方を確かめています"
    if n in ("parallel_work", "Agent", "Task", "command_center", "Workflow"):
        return "手分けして進めています"
    if n == "video" or n.startswith("studio_"):
        return "動画を見ています" if n in ("video", "studio_evaluate", "studio_extract_frame", "studio_probe") else "動画を作っています"
    if n == "phone":
        return "スマホを操作しています"
    if n == "desktop":
        return "PCのアプリを操作しています"
    if n in ("collab_thread", "split_to_new_room"):
        return "部屋を用意しています"
    if n == "progress":
        return ""
    return "作業しています"


# Dan's own words for the line (2026-10-25, 本人「何をしてるのかわからなさすぎる」「人間が見て、今何をしているのか…
# 具体的にわかるプロセスモニターに」). The words above say only what kind of tool runs; what a step is for comes from
# Dan: the progress tool (app/services/work_progress.py: done = a finished step, doing = the step now) and, on the
# Claude CLI, the description written with a command or a helper ("サーバーの記録を探しています"). Codex commands carry
# no description, so there progress is the only source. Only Japanese sentences pass; a doing line must read
# 「〜しています」, a done line 「〜しました」「〜でした」 (the owner turned down other ways of writing, 2026-10-25).
_DOING_END = re.compile(r"(?:て|で)います[。.]?$")
_LATIN = re.compile(r"[A-Za-z]")


def _japanese(s: str) -> bool:
    ja = len(_JA.findall(s))
    return ja >= 2 and len(_LATIN.findall(s)) <= ja * 3


def _clean(text: Any, limit: int) -> str:
    s = " ".join(str(text or "").split()).strip()
    # a leading mark or number (「✓」「→」「1.」「(2)」) is not part of the sentence
    s = re.sub(r"^(?:[✓✔☑→・*#\-]|\d+[.)．）]|[(（]\d+[)）])\s*", "", s)
    return s[:limit]


def own_activity(name: str, tool_input: dict | None = None) -> str:
    """The line Dan wrote for the step it is doing now (「アプリが自分の版を知らせているか確かめています」), or ""."""
    n = _base_name(name)
    a = tool_input if isinstance(tool_input, dict) else {}
    if n == "progress":
        text = a.get("doing")
    elif n in ("Bash", "bash", "Agent", "Task", "parallel_work"):
        text = a.get("description") if n != "parallel_work" else a.get("title")
    else:
        return ""
    s = _clean(text, 80)
    if n == "parallel_work":
        # a job title is a noun (「作業中の表示を具体的に」): only the shape Dan says out loud
        s = f"手分けして「{s}」を進めています" if s and _japanese(s) else ""
        return s
    if not s or not _japanese(s) or not _DOING_END.search(s):
        return ""
    return s.rstrip("。.")


def done_note(name: str, tool_input: dict | None = None) -> str:
    """A finished step in Dan's words (「サーバーの記録を見ました。…」), or ""."""
    if _base_name(name) != "progress":
        return ""
    a = tool_input if isinstance(tool_input, dict) else {}
    s = _clean(a.get("done"), 200)
    return s if s and _japanese(s) else ""


# Kana or kanji. A thinking summary without any is not shown (the owner reads Japanese; 2026-10-24).
_JA = re.compile(r"[぀-ヿ㐀-鿿]")


def thinking_text(text: Any, limit: int = 600) -> str:
    """The part of a model's thinking the work line may show, or "" (2026-10-24, 本人「考えています」だけの時間が
    超長くて遅く感じる」). Claude CLI streams thinking text only some of the time (mostly empty, sometimes a short
    Japanese summary of what it is doing); Codex streams reasoning summaries only when they are switched on. Text
    with no Japanese in it returns "" so the line never shows English thinking. The screens take its last
    sentence (frontend/src/lib/chat-shapes/live-line.ts)."""
    if not isinstance(text, str):
        return ""
    t = text.strip()
    if not t or not _JA.search(t):
        return ""
    return t[-limit:] if len(t) > limit else t
