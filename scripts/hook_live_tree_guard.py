"""Keep the folder Dan runs from (D:\\done) out of everyone's hands: only follow_github changes what git tracks there.

Why (2026-10-17): every session wrote its unfinished work straight into the running folder. Shipping one change then
collided with seven files of other sessions' half-done work, follow_github stopped, and the shipper had to merge
strangers' work by hand; a dashboard rebuild would have published all of it. Each piece of work now lives in its own
worktree and branch (`python scripts/work.py new <name>`), where git keeps every saved step.

PreToolUse hook for Claude Code (Write / Edit / MultiEdit / NotebookEdit / Bash / PowerShell) and, through
scripts/codex_hook_bridge.py, for Codex (apply_patch, shell). A write is refused when its file is inside the running
folder and git tracks it or would track it. Everything git does not track passes: user artifacts
(frontend/src/app/artifacts/<slug>/, frontend/public/artifacts/), runtime data (.data, logs, node_modules, builds) and
worktrees kept inside the folder (.tmp/..., _codex_worktrees/...). The rule is the folder's own .gitignore, so nothing
here has to be kept in step with it.

Shell commands are read for the usual ways of writing a file (redirects, tee, sed -i, cp/mv/rm, Set-Content and the
like, git commands that change the work tree, npm install <pkg>). A program that writes files by itself is not seen;
follow_github names whatever is left uncommitted, and scripts/rescue_wip.py moves it to a branch.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

LIVE = Path(os.environ.get("DAN_LIVE_TREE") or Path(__file__).resolve().parents[1])
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

GIT_CHANGES_TREE = {"add", "commit", "checkout", "switch", "restore", "reset", "stash", "pull", "merge", "rebase",
                    "cherry-pick", "revert", "apply", "am", "rm", "mv", "clean"}
NPM_CHANGES_PACKAGES = {"install", "i", "add", "uninstall", "remove", "rm", "un", "update", "up", "upgrade"}
COPY_LIKE = {"cp", "copy", "copy-item", "cpi", "install"}
MOVE_LIKE = {"mv", "move", "move-item", "mi", "rename-item", "ren", "rni"}
REMOVE_LIKE = {"rm", "del", "erase", "remove-item", "ri", "unlink", "rmdir", "rd"}
CONTENT_LIKE = {"set-content", "sc", "add-content", "ac", "out-file", "clear-content", "clc", "tee-object", "touch",
                "new-item", "ni"}
CD_LIKE = {"cd", "chdir", "pushd", "set-location", "sl"}
PATH_FLAGS = {"-path", "-literalpath", "-filepath", "-destination", "-lp"}
SKIP_TARGETS = {"/dev/null", "nul", "$null", "null", "/dev/stderr", "/dev/stdout"}


# --- paths -------------------------------------------------------------------------------------------------------------

def _norm(path: str | os.PathLike, cwd: str | None = None) -> Path | None:
    s = str(path).strip().strip('"').strip("'")
    if not s or s.startswith(("$", "%", "-")) or "://" in s:
        return None
    if s.startswith("\\\\?\\"):
        s = s[4:]
    m = re.match(r"^/([a-zA-Z])(/.*)?$", s)            # Git Bash: /d/done/x -> D:/done/x
    if m and os.name == "nt":
        s = f"{m.group(1).upper()}:{m.group(2) or '/'}"
    s = os.path.expanduser(s)
    p = Path(s)
    if not p.is_absolute():
        if not cwd:
            return None
        p = Path(cwd) / p
    return Path(os.path.normpath(str(p)))


def _inside(path: Path, root: Path) -> bool:
    a, b = os.path.normcase(str(path)), os.path.normcase(str(root))
    return a == b or a.startswith(b.rstrip("\\/") + os.sep)


def live_file(path: Path) -> str | None:
    """The path relative to the running folder when git tracks it or would track it there; else None."""
    if not _inside(path, LIVE) or os.path.normcase(str(path)) == os.path.normcase(str(LIVE)):
        return None
    rel = Path(os.path.relpath(path, LIVE))
    probe = path.parent
    while _inside(probe, LIVE) and os.path.normcase(str(probe)) != os.path.normcase(str(LIVE)):
        if (probe / ".git").exists():                   # another worktree kept inside the folder
            return None
        probe = probe.parent
    rel_s = rel.as_posix()
    if rel_s == ".git" or rel_s.startswith(".git/"):
        return rel_s
    try:
        r = subprocess.run(["git", "-C", str(LIVE), "check-ignore", "-q", "--", rel_s], capture_output=True,
                           timeout=20, creationflags=NO_WINDOW)
    except Exception:  # noqa: BLE001 — a broken git must not stop every write on the machine
        return None
    return rel_s if r.returncode == 1 else None


# --- shell commands ------------------------------------------------------------------------------------------------------

_OPS = ("&&", "||", ";", "|", "\n", "&")


def _tokens(cmd: str):
    """Words, redirect targets and command separators of a bash / PowerShell line, quotes and heredocs respected."""
    out, i, n = [], 0, len(cmd)
    word, quoted = "", False
    pending_heredoc: list[str] = []

    def flush():
        nonlocal word, quoted
        if word or quoted:
            out.append(("w", word))
        word, quoted = "", False

    while i < n:
        c = cmd[i]
        if c in "'\"":
            j = cmd.find(c, i + 1)
            j = n if j < 0 else j
            word += cmd[i + 1:j]
            quoted = True
            i = j + 1
            continue
        if c == "\\" and i + 1 < n and cmd[i + 1] not in "\r\n" and os.name != "nt":
            word += cmd[i + 1]
            i += 2
            continue
        if c == "\n" and pending_heredoc:
            flush()
            out.append(("op", "\n"))
            for delim in pending_heredoc:              # skip the heredoc body
                while i < n:
                    k = cmd.find("\n", i + 1)
                    line = cmd[i + 1:(n if k < 0 else k)].strip()
                    i = n if k < 0 else k
                    if line == delim:
                        break
            pending_heredoc = []
            continue
        if c == "<" and cmd.startswith("<<", i) and not cmd.startswith("<<<", i):
            flush()
            m = re.match(r"<<-?\s*(['\"]?)([\w.-]+)\1", cmd[i:])
            if m:
                pending_heredoc.append(m.group(2))
                i += m.end()
                continue
        if c == ">" or (c in "12*&" and cmd.startswith(">", i + 1) and not word):
            flush()
            j = i + (0 if c == ">" else 1) + 1
            if j < n and cmd[j] == ">":
                j += 1
            while j < n and cmd[j] in " \t":
                j += 1
            if j < n and cmd[j] == "&":                  # 2>&1
                j += 1
                while j < n and (cmd[j].isdigit() or cmd[j] == "-"):
                    j += 1
                i = j
                continue
            m = re.match(r"\"([^\"]*)\"|'([^']*)'|([^\s;&|<>()]+)", cmd[j:])
            if m:
                out.append(("redir", next(g for g in m.groups() if g is not None)))
                j += m.end()
            i = j
            continue
        if c in " \t\r":
            flush()
            i += 1
            continue
        op = next((o for o in _OPS if cmd.startswith(o, i)), None)
        if op:
            flush()
            out.append(("op", op))
            i += len(op)
            continue
        if c in "()" and not word:
            flush()
            out.append(("op", ";"))
            i += 1
            continue
        word += c
        i += 1
    flush()
    return out


def _segments(cmd: str):
    seg, redirs = [], []
    for kind, val in _tokens(cmd):
        if kind == "op":
            if seg or redirs:
                yield seg, redirs
            seg, redirs = [], []
        elif kind == "redir":
            redirs.append(val)
        else:
            seg.append(val)
    if seg or redirs:
        yield seg, redirs


def _name(word: str) -> str:
    base = re.split(r"[\\/]", word)[-1].lower()
    return base[:-4] if base.endswith((".exe", ".cmd", ".bat")) else base


def _positionals(args: list[str]) -> list[str]:
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a.startswith("-"):
            low = a.lower()
            if low in PATH_FLAGS:
                continue                                 # the value after it is a path: keep it as positional
            if low in ("-itemtype", "-encoding", "-value", "-type", "-e", "-f", "-t", "-message", "-m"):
                skip = True
            continue
        out.append(a)
    return out


def shell_writes(command: str, cwd: str | None):
    """(problem, path) pairs for writes into the running folder that a shell line would make."""
    found = []

    def target(raw: str, here: str | None, must_exist=False):
        if raw.lower() in SKIP_TARGETS:
            return
        p = _norm(raw, here)
        if p is None:
            return
        if not (p.exists() or (not must_exist and p.parent.is_dir())):
            return                                       # not a path (a sed script, a word in a message)
        rel = live_file(p)
        if rel:
            found.append(("file", rel))

    here = cwd
    for words, redirs in _segments(command):
        for r in redirs:
            target(r, here)
        while words and (re.match(r"^\w+=", words[0]) or words[0] in ("&", "sudo", "env", "command", "exec", "time")):
            words = words[1:]
        if not words:
            continue
        name, args = _name(words[0]), words[1:]
        if name in CD_LIKE:
            pos = _positionals(args)
            if pos:
                nxt = _norm(pos[0], here)
                here = str(nxt) if nxt else here
            continue
        if name == "git":
            repo, k = here, 0
            while k < len(args) and args[k].startswith("-"):
                if args[k] == "-C" and k + 1 < len(args):
                    nxt = _norm(args[k + 1], here)
                    repo = str(nxt) if nxt else repo
                    k += 2
                elif args[k] in ("-c", "--git-dir", "--work-tree"):
                    k += 2
                else:
                    k += 1
            sub = args[k] if k < len(args) else ""
            if sub in GIT_CHANGES_TREE and repo:
                rp = _norm(repo)
                if rp and _inside(rp, LIVE) and not _nested_worktree(rp):
                    found.append(("git", f"git {sub}"))
            continue
        if name in ("npm", "pnpm", "yarn"):
            pos = _positionals(args)
            if pos and pos[0] in NPM_CHANGES_PACKAGES and len(pos) > 1 and here:
                hp = _norm(here)
                if hp and _inside(hp, LIVE) and not _nested_worktree(hp):
                    found.append(("npm", f"{name} {' '.join(pos[:3])}"))
            continue
        if name == "npx" and any(a.startswith("shadcn") for a in args) and "add" in args and here:
            hp = _norm(here)
            if hp and _inside(hp, LIVE) and not _nested_worktree(hp):
                found.append(("npm", "npx shadcn add"))
            continue
        pos = _positionals(args)
        if name in ("sed", "perl"):
            if any(a == "--in-place" or re.match(r"^-[a-zA-Z]*i", a) for a in args):
                for a in pos:
                    target(a, here, must_exist=True)
        elif name in ("tee",):
            for a in pos:
                target(a, here)
        elif name in COPY_LIKE:
            dest = _flag_value(args, "-destination") or (pos[-1] if len(pos) > 1 else None)
            if dest:
                target(dest, here)
        elif name in MOVE_LIKE:
            for a in pos:
                target(a, here)
        elif name in REMOVE_LIKE:
            for a in pos:
                target(a, here, must_exist=True)
        elif name in CONTENT_LIKE:
            if name in ("new-item", "ni") and (_flag_value(args, "-itemtype") or "").lower() == "directory":
                continue
            paths = [v for v in (_flag_value(args, f) for f in ("-path", "-literalpath", "-filepath")) if v]
            for a in (paths or pos[:1] if name not in ("touch",) else pos):
                target(a, here)
    return found


def _flag_value(args: list[str], flag: str) -> str | None:
    for k, a in enumerate(args):
        if a.lower() == flag and k + 1 < len(args):
            return args[k + 1]
        if a.lower().startswith(flag + ":"):
            return a.split(":", 1)[1]
    return None


def _nested_worktree(path: Path) -> bool:
    probe = path
    while _inside(probe, LIVE) and os.path.normcase(str(probe)) != os.path.normcase(str(LIVE)):
        if (probe / ".git").exists():
            return True
        probe = probe.parent
    return False


# --- hook ----------------------------------------------------------------------------------------------------------------

def check(payload: dict) -> str | None:
    """The refusal message, or None to let the tool run."""
    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or os.getcwd()
    if tool in ("Bash", "PowerShell", "shell", "exec_command"):
        cmd = ti.get("command") or ""
        if isinstance(cmd, list):
            cmd = " ".join(str(c) for c in cmd)
        hits = shell_writes(str(cmd), cwd)
        if not hits:
            return None
        kind, what = hits[0]
        return _message(what, kind)
    if tool == "apply_patch":                              # Codex without the bridge (a terminal opened in D:\done)
        patch = ti.get("command") or ti.get("patch") or ti.get("input") or ""
        paths = _PATCH_FILE.findall(patch if isinstance(patch, str) else json.dumps(patch))
    else:
        paths = [ti.get("file_path") or ti.get("notebook_path") or ti.get("path")]
    for path in filter(None, paths):
        p = _norm(path.strip(), cwd)
        rel = live_file(p) if p else None
        if rel:
            return _message(rel, "file")
    return None


_PATCH_FILE = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*$", re.MULTILINE)


def _message(what: str, kind: str) -> str:
    lead = {
        "file": f"{LIVE}\\{what.replace('/', os.sep)} は動いているダン（{LIVE}）の中で、git が追うファイルです。ここには書けません。",
        "git": f"{what} は動いているダン（{LIVE}）の中身を変えるので、ここでは使えません。{LIVE} を変えるのは scripts/follow_github.py だけです。",
        "npm": f"{what} は {LIVE}\\frontend の package.json を変えるので、ここでは使えません。",
    }[kind]
    return (
        lead + "\n"
        "作業は自分専用の作業場所（worktree）でしてください:\n"
        f"  python {LIVE.as_posix()}/scripts/work.py new <名前>     -> D:\\dan-workspace\\<名前> に分岐を作る（続きなら --from <分岐>）\n"
        "  そこで同じファイルを直す。こまめに `work.py save`、試すのは `work.py try`、本番に入れるのは `work.py ship`。\n"
        "このまま書けるもの: 成果物（frontend/src/app/artifacts/<slug>/、frontend/public/artifacts/<slug>/）と、"
        "git が追わない実行時のファイル（.data、ログ、ビルド出力など）。"
    )


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except Exception:  # noqa: BLE001
        return 0
    reason = check(payload)
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason}}))   # ASCII escapes
    return 0


if __name__ == "__main__":
    sys.exit(main())
