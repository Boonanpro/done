"""Keep the folder Dan runs from (/Users/mikihonda/done) a copy of GitHub main: only follow_github changes what git
tracks there.

Why (2026-10-17): every session wrote its unfinished work straight into the running folder. Shipping one change then
collided with seven files of other sessions' half-done work, follow_github stopped, and the shipper had to merge
strangers' work by hand; a dashboard rebuild would have published all of it. Each piece of work now lives in its own
worktree and branch (`python scripts/work.py new <name>`), where git keeps every saved step.

Two halves, one hook (2026-10-23):

1. Before a tool runs (PreToolUse), it is refused when it would write a file git tracks (or would track) in the running
   folder: Write / Edit / MultiEdit / NotebookEdit / Codex's apply_patch by their path, a shell line by the usual ways
   of writing a file (redirects, tee, cp/mv/rm/ln/rsync, sed -i, git and npm commands that change the tree, sh -c and
   eval, python -c / node -e that open a file for writing, variables, cd). This half gives the early, clear answer.
2. After it ran (PostToolUse), the folder itself is looked at: a tracked file that changed during the call, by any way
   at all (a script, a program, a path spelled some way the first half did not read), is saved on the session's branch
   wip/<date>-<session> and put back to the committed version, and the session is told. This half is the guarantee:
   reading shell text can never be complete, the folder's state is. Nothing is lost: the content is on the branch and
   the folder's copy is kept in .git/dan/rescued/.

Everything git does not track passes: user artifacts (frontend/src/app/artifacts/<slug>/, frontend/public/artifacts/),
runtime data (.data, logs, node_modules, builds) and worktrees kept inside the folder. The rule is the folder's own
.gitignore, so nothing here has to be kept in step with it.

Also refused from a worktree: `pip install` into the shared Python (it is the running Dan's); `work.py venv` gives the
worktree its own copy.

Registered for Claude Code (PreToolUse and PostToolUse, matcher Write|Edit|MultiEdit|NotebookEdit|Bash) and, through
scripts/codex_hook_bridge.py, for Codex.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from follow_github import dan_dir, live_root, status, tree_lock  # noqa: E402

LIVE = live_root()
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FOLD = sys.platform in ("darwin", "win32")          # APFS and NTFS ignore case

GIT_CHANGES_TREE = {"add", "commit", "checkout", "switch", "restore", "reset", "stash", "pull", "merge", "rebase",
                    "cherry-pick", "revert", "apply", "am", "rm", "mv", "clean"}
NPM_CHANGES_PACKAGES = {"install", "i", "add", "uninstall", "remove", "rm", "un", "update", "up", "upgrade", "ci"}
COPY_LIKE = {"cp", "copy", "copy-item", "cpi", "install", "rsync", "ditto", "ln", "scp"}
MOVE_LIKE = {"mv", "move", "move-item", "mi", "rename-item", "ren", "rni"}
REMOVE_LIKE = {"rm", "del", "erase", "remove-item", "ri", "unlink", "rmdir", "rd", "shred"}
CONTENT_LIKE = {"set-content", "sc", "add-content", "ac", "out-file", "clear-content", "clc", "tee-object", "touch",
                "new-item", "ni", "truncate"}
CD_LIKE = {"cd", "chdir", "pushd", "set-location", "sl"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
INTERPRETERS = {"python", "python3", "node", "perl", "ruby", "deno", "bun", "osascript"}
PATH_FLAGS = {"-path", "-literalpath", "-filepath", "-destination", "-lp"}
SKIP_TARGETS = {"/dev/null", "nul", "$null", "null", "/dev/stderr", "/dev/stdout", "/dev/tty"}
WRITES_IN_CODE = re.compile(
    r"""open\s*\([^)]*?,\s*(?:mode\s*=\s*)?['"][^'"]*[wax+]|\.write_(?:text|bytes)\s*\(|writeFile|appendFile|"""
    r"""createWriteStream|copyFile|\brename(?:Sync)?\s*\(|\bunlink(?:Sync)?\s*\(|\brm(?:Sync)?\s*\(|rmtree|"""
    r"""shutil\.(?:copy|move)|os\.(?:replace|rename|remove|unlink)|\.unlink\s*\(|\.rename\s*\(|\.replace\s*\(|"""
    r"""\.touch\s*\(|open\s*\(\s*['"][^'"]*['"]\s*,\s*['"]>|sysopen|File\.write|IO\.write|FileUtils""")
PATH_IN_CODE = re.compile(r"""['"]([^'"\n]{1,400})['"]""")


# --- paths -------------------------------------------------------------------------------------------------------------

def _fold(s: str) -> str:
    return s.lower() if FOLD else s


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


def _real(path: Path) -> str:
    """The path with symlinks (/tmp, /var, a link into the folder) resolved, as far as it exists."""
    return os.path.realpath(str(path))


def _rel_in_live(path: Path) -> str | None:
    """path relative to the running folder (posix form) when it is inside it, however it is spelled."""
    live = _real(LIVE)
    for cand in (_real(path), os.path.normpath(str(path))):
        if _fold(cand) == _fold(live):
            return ""
        if _fold(cand).startswith(_fold(live.rstrip("/\\") + os.sep)):
            return cand[len(live.rstrip("/\\")) + 1:].replace(os.sep, "/")
    return None


def _inside(path: Path, root: Path) -> bool:
    a, b = _fold(_real(path)), _fold(_real(root))
    return a == b or a.startswith(b.rstrip("\\/") + os.sep)


def _nested_worktree(path: Path) -> bool:
    """path is inside a worktree (or other repository) kept inside the running folder."""
    rel = _rel_in_live(path)
    if not rel:
        return False
    probe = Path(_real(LIVE))
    for part in rel.split("/")[:-1] if not Path(path).is_dir() else rel.split("/"):
        probe = probe / part
        if (probe / ".git").exists():
            return True
    return False


def live_file(path: Path) -> str | None:
    """The path relative to the running folder when git tracks it or would track it there; else None."""
    rel = _rel_in_live(path)
    if not rel or _nested_worktree(path):
        return None
    if _fold(rel) == ".git" or _fold(rel).startswith(".git/"):
        return rel
    try:
        r = subprocess.run(["git", "-C", str(LIVE), "-c", f"core.ignorecase={'true' if FOLD else 'false'}",
                            "check-ignore", "-q", "--", rel], capture_output=True, timeout=20, creationflags=NO_WINDOW)
    except Exception:  # noqa: BLE001 — a broken git must not stop every write on the machine
        return None
    return rel if r.returncode == 1 else None


def _in_worktree_of_live(cwd: str | None) -> bool:
    """cwd is inside a worktree of the running folder's repository (a piece of Dan work)."""
    if not cwd:
        return False
    probe = Path(cwd)
    for d in (probe, *probe.parents):
        dot = d / ".git"
        if dot.is_file():
            try:
                line = dot.read_text(encoding="utf-8").strip()
            except OSError:
                return False
            return line.startswith("gitdir:") and _inside(Path(line[7:].strip()), LIVE / ".git")
        if dot.is_dir():
            return False
    return False


# --- shell commands ------------------------------------------------------------------------------------------------------

_OPS = ("&&", "||", ";", "|", "\n", "&")


def _tokens(cmd: str):
    """Words, redirect targets, heredoc bodies, $(...) insides and separators of a bash / PowerShell line, quotes
    respected. A $ inside single quotes is kept as \0 so that it is never expanded."""
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
            piece = cmd[i + 1:j]
            word += piece.replace("$", "\0") if c == "'" else piece   # \0 marks a $ that must not be expanded
            quoted = True
            i = j + 1
            continue
        if c == "\\" and i + 1 < n and cmd[i + 1] not in "\r\n" and os.name != "nt":
            word += cmd[i + 1]
            i += 2
            continue
        if c == "\n" and pending_heredoc:
            flush()
            for delim in pending_heredoc:              # the heredoc body belongs to the command before the newline
                body = []
                while i < n:
                    k = cmd.find("\n", i + 1)
                    line = cmd[i + 1:(n if k < 0 else k)]
                    i = n if k < 0 else k
                    if line.strip() == delim:
                        break
                    body.append(line)
                out.append(("body", "\n".join(body)))
            out.append(("op", "\n"))
            pending_heredoc = []
            continue
        if c == "<" and cmd.startswith("<<", i) and not cmd.startswith("<<<", i):
            flush()
            m = re.match(r"<<-?\s*(['\"]?)([\w.-]+)\1", cmd[i:])
            if m:
                pending_heredoc.append(m.group(2))
                i += m.end()
                continue
        if c == "<" and cmd.startswith("<<<", i):         # here-string: its text is the command's input
            flush()
            m = re.match(r"<<<\s*(\"[^\"]*\"|'[^']*'|\S+)", cmd[i:])
            if m:
                out.append(("body", m.group(1).strip("'\"")))
                i += m.end()
                continue
        if c == ">" or (c in "12*&" and cmd.startswith(">", i + 1) and not word):
            flush()
            j = i + (0 if c == ">" else 1) + 1
            if j < n and cmd[j] in ">|":
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
        if c == "$" and cmd.startswith("$(", i):        # $(...): read its inside as a command of its own
            depth, j = 1, i + 2
            while j < n and depth:
                depth += {"(": 1, ")": -1}.get(cmd[j], 0)
                j += 1
            out.append(("sub", cmd[i + 2:j - 1]))
            word += "$(...)"
            i = j
            continue
        if c == "`":
            j = cmd.find("`", i + 1)
            j = n if j < 0 else j
            out.append(("sub", cmd[i + 1:j]))
            word += "$(...)"
            i = j + 1
            continue
        word += c
        i += 1
    flush()
    return out


def _segments(cmd: str):
    """(words, redirect targets, heredoc bodies) per simple command; $(...) insides are yielded as their own."""
    seg, redirs, bodies, subs = [], [], [], []
    for kind, val in _tokens(cmd):
        if kind == "op":
            if seg or redirs or bodies:
                yield seg, redirs, bodies
            seg, redirs, bodies = [], [], []
        elif kind == "redir":
            redirs.append(val)
        elif kind == "body":
            bodies.append(val)
        elif kind == "sub":
            subs.append(val)
        else:
            seg.append(val)
    if seg or redirs or bodies:
        yield seg, redirs, bodies
    for sub in subs:
        yield from _segments(sub)


def _expand(word: str, env: dict) -> str:
    def one(m):
        name = m.group(1) or m.group(2)
        if name in env:
            return env[name]
        if name in ("HOME",):
            return str(Path.home())
        if name in ("PWD",):
            return env.get("\0cwd", "")
        return os.environ.get(name, m.group(0))
    out = re.sub(r"\$\{(\w+)\}|\$(\w+)", one, word)
    if out.startswith("~"):
        out = os.path.expanduser(out)
    return out.replace("\0", "$")


def _name(word: str) -> str:
    base = re.split(r"[\\/]", word)[-1].lower()
    base = base[:-4] if base.endswith((".exe", ".cmd", ".bat")) else base
    return re.sub(r"^(python|pip)\d+(\.\d+)?$", lambda m: m.group(1) + ("3" if m.group(1) == "python" else ""), base)


def _positionals(args: list[str]) -> list[str]:
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a.startswith("-") and a != "-":
            low = a.lower()
            if low in PATH_FLAGS:
                continue                                 # the value after it is a path: keep it as positional
            if low in ("-itemtype", "-encoding", "-value", "-type", "-e", "-f", "-t", "-message", "-m", "-s", "-o",
                       "--exclude", "--include", "--filter"):
                skip = True
            continue
        out.append(a)
    return out


def shell_writes(command: str, cwd: str | None, depth: int = 0):
    """(problem, path) pairs for writes into the running folder that a shell line would make."""
    found = []
    env: dict[str, str] = {"\0cwd": cwd or ""}

    def target(raw: str, here: str | None, must_exist=False):
        if raw.lower() in SKIP_TARGETS or "$(...)" in raw:
            return
        p = _norm(raw, here)
        if p is None:
            return
        if not (os.path.lexists(p) or (not must_exist and p.parent.is_dir())):
            return                                       # not a path (a sed script, a word in a message)
        if p.is_dir() and not p.is_symlink():
            return                                       # a folder itself (mkdir, a cp destination handled below)
        rel = live_file(p)
        if rel:
            found.append(("file", rel))

    def into(dest: str, sources: list[str], here: str | None):
        d = _norm(dest, here)
        if d is not None and d.is_dir():
            for s in sources:
                target(str(d / Path(s.rstrip("/")).name), here)
        else:
            target(dest, here)

    def in_live(here: str | None) -> bool:
        hp = _norm(here) if here else None
        return bool(hp and _rel_in_live(hp) is not None and not _nested_worktree(hp))

    here = cwd
    for words, redirs, bodies in _segments(command):
        env["\0cwd"] = here or ""
        for r in redirs:
            target(_expand(r, env), here)
        assigns = []
        while words and re.match(r"^[A-Za-z_]\w*=", words[0]):
            assigns.append(words.pop(0))
        if words[:1] in (["export"], ["local"], ["declare"], ["typeset"]):
            assigns += [w for w in words[1:] if "=" in w]
            words = []
        if not words:
            for a in assigns:
                k, v = a.split("=", 1)
                env[k] = _expand(v, env)
            continue
        while words and words[0] in ("&", "sudo", "env", "command", "exec", "time", "nohup", "nice", "xargs",
                                     "timeout", "caffeinate", "builtin"):
            words = words[1:]
            while words and (words[0].startswith("-") or re.match(r"^[A-Za-z_]\w*=", words[0]) or words[0].isdigit()):
                words = words[1:]
        if not words:
            continue
        words = [_expand(w, env) if i == 0 else w for i, w in enumerate(words)]
        name, args = _name(words[0]), words[1:]
        xargs = [_expand(a, env) for a in args]
        if name in CD_LIKE:
            pos = _positionals(xargs)
            nxt = _norm(pos[0], here) if pos else None
            here = str(nxt) if nxt else here
            continue
        if name in SHELLS or name == "eval" or name in ("pwsh", "powershell"):
            inner = None
            if name == "eval":
                inner = " ".join(xargs)
            else:
                for k, a in enumerate(xargs):
                    if a in ("-c", "-lc", "-ic", "-command", "-Command", "-c ") and k + 1 < len(xargs):
                        inner = xargs[k + 1]
                        break
                if inner is None and bodies and not _positionals(xargs):
                    inner = "\n".join(bodies)             # bash <<EOF ... EOF
            if inner and depth < 4:
                found += shell_writes(inner, here, depth + 1)
            continue
        if name == "perl" and any(re.match(r"^-[a-zA-Z]*i", a) for a in args):
            for a in xargs:                              # perl -pi -e 's/a/b/' file...: the files that exist
                if not a.startswith("-"):
                    target(a, here, must_exist=True)
            continue
        if name in INTERPRETERS:
            code = None
            for k, a in enumerate(args):
                if a in ("-c", "-e", "-E", "--eval", "-p", "-pe", "-ne", "-pi", "-i") and k + 1 < len(args):
                    code = args[k + 1]
                    break
            if code is None and bodies and (not _positionals(args) or "-" in args):
                code = "\n".join(bodies)                  # python - <<EOF ... EOF
            if code is not None:
                found += _code_writes(code, here)
            if name in ("python", "python3") and args[:2] == ["-m", "pip"]:
                found += _pip(words[0], args[2:], here)
            continue
        if name in ("pip", "pip3", "uv"):
            found += _pip(words[0], args[1:] if name == "uv" and args[:1] == ["pip"] else args, here)
            continue
        if name == "git":
            repo, k = here, 0
            while k < len(xargs) and xargs[k].startswith("-"):
                if xargs[k] == "-C" and k + 1 < len(xargs):
                    nxt = _norm(xargs[k + 1], repo)
                    repo = str(nxt) if nxt else repo
                    k += 2
                elif xargs[k] in ("-c", "--git-dir", "--work-tree"):
                    if xargs[k] == "--work-tree" and k + 1 < len(xargs):
                        nxt = _norm(xargs[k + 1], repo)
                        repo = str(nxt) if nxt else repo
                    k += 2
                else:
                    k += 1
            sub, rest = (xargs[k] if k < len(xargs) else ""), xargs[k + 1:]
            if sub in GIT_CHANGES_TREE and not _git_reads_only(sub, rest) and in_live(repo):
                found.append(("git", f"git {sub}"))
            continue
        if name in ("npm", "pnpm", "yarn"):
            pos = _positionals(xargs)
            if pos and pos[0] in NPM_CHANGES_PACKAGES and (len(pos) > 1 or pos[0] == "ci") \
                    and "--dry-run" not in xargs and in_live(here):
                found.append(("npm", f"{name} {' '.join(pos[:3])}"))
            continue
        if name == "npx" and any(a.startswith("shadcn") for a in xargs) and "add" in xargs and in_live(here):
            found.append(("npm", "npx shadcn add"))
            continue
        if name == "patch":
            d = _flag_value(xargs, "-d") or here
            if in_live(d):
                found.append(("file", "patch"))
            continue
        if name == "dd":
            for a in xargs:
                if a.startswith("of="):
                    target(a[3:], here)
            continue
        if name in ("unzip", "tar", "bsdtar") and in_live(_flag_value(xargs, "-C") or _flag_value(xargs, "-d") or here):
            if name == "unzip" or any(re.match(r"^-?[a-zA-Z]*x", a) for a in xargs[:1]):
                found.append(("file", f"{name} (extracts into the folder)"))
            continue
        pos = _positionals(xargs)
        if name in ("sed", "gsed"):
            if any(a == "--in-place" or a.startswith("--in-place=") or re.match(r"^-[a-zA-Z]*i", a) for a in xargs):
                for a in pos[1:] if not any(a in ("-e", "-f") for a in xargs) else pos:
                    target(a, here, must_exist=True)
        elif name in ("tee",):
            for a in pos:
                target(a, here)
        elif name in COPY_LIKE:
            dest = _flag_value(xargs, "-destination") or (pos[-1] if len(pos) > 1 else None)
            if name == "ln" and len(pos) == 1:
                dest = "."
            if dest:
                into(dest, pos[:-1] if len(pos) > 1 else pos, here)
        elif name in MOVE_LIKE:
            for a in pos[:-1]:
                target(a, here, must_exist=True)
            if pos:
                into(pos[-1], pos[:-1], here)
        elif name in REMOVE_LIKE:
            for a in pos:
                target(a, here, must_exist=True)
                d = _norm(a, here)
                if d is not None and d.is_dir() and _rel_in_live(d) is not None and _tracked_under(d):
                    found.append(("file", _rel_in_live(d) + "/"))
        elif name in CONTENT_LIKE:
            if name in ("new-item", "ni") and (_flag_value(args, "-itemtype") or "").lower() == "directory":
                continue
            paths = [v for v in (_flag_value(xargs, f) for f in ("-path", "-literalpath", "-filepath")) if v]
            for a in (paths or pos[:1] if name not in ("touch", "truncate") else pos):
                target(a, here)
    return found


def _git_reads_only(sub: str, rest: list[str]) -> bool:
    if sub == "clean":
        return any(a in ("-n", "--dry-run") or re.match(r"^-[a-zA-Z]*n", a) for a in rest)
    if sub == "stash":
        return bool(rest) and rest[0] in ("list", "show")
    if sub == "apply":
        return any(a in ("--check", "--stat", "--numstat", "--summary") for a in rest) and "--apply" not in rest
    if sub in ("add", "rm", "mv", "commit", "checkout", "restore", "reset"):
        return any(a in ("-n", "--dry-run") for a in rest)
    return False


def _tracked_under(d: Path) -> bool:
    rel = _rel_in_live(d)
    r = subprocess.run(["git", "-C", str(LIVE), "ls-files", "--", rel], capture_output=True, timeout=20,
                       creationflags=NO_WINDOW)
    return bool(r.stdout.strip())


def _code_writes(code: str, here: str | None):
    """python -c / node -e / a heredoc fed to an interpreter: a file path into the folder in code that writes files."""
    if not WRITES_IN_CODE.search(code):
        return []
    found = []
    for raw in PATH_IN_CODE.findall(code):
        if "/" not in raw and "\\" not in raw and "." not in raw:
            continue
        p = _norm(raw.replace("\\\\", "\\"), here)
        if p is None:
            continue
        rel = live_file(p) if (os.path.lexists(p) or p.parent.is_dir()) and not p.is_dir() else None
        if rel:
            found.append(("file", rel))
        elif p.is_dir() and _rel_in_live(p) is not None and not _nested_worktree(p) and _tracked_under(p):
            found.append(("file", (_rel_in_live(p) or ".") + "/"))
    return found


def _pip(exe: str, args: list[str], here: str | None):
    """pip install from a worktree into the shared Python changes the running Dan's packages too."""
    if not args or args[0] not in ("install", "uninstall") or not _in_worktree_of_live(here):
        return []
    if any(a in ("--target", "-t", "--prefix", "--root", "--dry-run", "--user") or a.startswith(("--target=", "--prefix="))
           for a in args):
        return []
    if "/.venv/" in exe.replace("\\", "/") or exe.replace("\\", "/").startswith(".venv/") or os.environ.get("VIRTUAL_ENV", "").endswith(".venv"):
        return []
    return [("pip", f"pip {args[0]}")]


def _flag_value(args: list[str], flag: str) -> str | None:
    for k, a in enumerate(args):
        if a.lower() == flag and k + 1 < len(args):
            return args[k + 1]
        if a.lower().startswith(flag + ":"):
            return a.split(":", 1)[1]
    return None


# --- before: refuse ------------------------------------------------------------------------------------------------------

def check(payload: dict) -> str | None:
    """The refusal message, or None to let the tool run."""
    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or os.getcwd()
    if tool in ("Bash", "PowerShell", "shell", "exec_command", "local_shell"):
        cmd = ti.get("command") or ""
        if isinstance(cmd, list):
            cmd = " ".join(shlex.quote(str(c)) for c in cmd)
        hits = shell_writes(str(cmd), ti.get("workdir") or cwd)
        if not hits:
            return None
        kind, what = hits[0]
        return _message(what, kind)
    if tool == "apply_patch":                              # Codex without the bridge (a terminal opened in the folder)
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


def _workspace() -> str:
    return os.environ.get("DAN_WORKTREES") or ("D:\\dan-workspace" if os.name == "nt" else str(Path.home() / "dan-workspace"))


def _message(what: str, kind: str) -> str:
    work = f"python {LIVE.as_posix()}/scripts/work.py"
    lead = {
        "file": f"{LIVE / what} は動いているダン（{LIVE}）の中で、git が追うファイルです。ここには書けません。",
        "git": f"{what} は動いているダン（{LIVE}）の中身を変えるので、ここでは使えません。{LIVE} を変えるのは scripts/follow_github.py だけです。",
        "npm": f"{what} は {LIVE / 'frontend'} の package.json か node_modules を変えるので、ここでは使えません。"
               "成果物が使うパッケージは、成果物のファイルに import を書けば自動で入ります。",
        "pip": f"{what} は、動いているダンと共用の Python に入れるので、作業場所からは使えません。"
               f"`{work} venv` でこの作業場所だけの Python（.venv）を作り、`.venv/bin/python -m pip {what.split()[-1]} ...` で入れてください。"
               "本番に要るなら requirements.txt にも書いてください。",
    }[kind]
    if kind == "pip":
        return lead
    return (
        lead + "\n"
        "作業は自分専用の作業場所でしてください:\n"
        f"  {work} new <名前>     -> {_workspace()}{os.sep}<名前> に分岐を作る（続きなら --from <分岐>）\n"
        "  そこで同じファイルを直す。こまめに `work.py save`、試すのは `work.py test` と `work.py try`、本番に入れるのは `work.py ship`。\n"
        "このまま書けるもの: 成果物（frontend/src/app/artifacts/<slug>/、frontend/public/artifacts/<slug>/）と、"
        "git が追わない実行時のファイル（.data、ログ、ビルド出力など）。"
    )


# --- after: look at the folder -------------------------------------------------------------------------------------------

def _snapshot_file(payload: dict) -> Path:
    key = payload.get("tool_use_id") or payload.get("call_id") or payload.get("session_id") or "nosession"
    return dan_dir(LIVE) / "guard" / (re.sub(r"[^\w.-]", "_", str(key))[:120] + ".json")


def _dirty() -> dict[str, list]:
    """Everything uncommitted in the folder: rel -> [code, size, mtime_ns, inode] (None when gone)."""
    out = {}
    for code, rel in status(LIVE):
        try:
            st = os.lstat(LIVE / rel)
            out[rel] = [code, st.st_size, st.st_mtime_ns, st.st_ino]
        except OSError:
            out[rel] = [code, None, None, None]
    return out


def before(payload: dict) -> None:
    f = _snapshot_file(payload)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"at": time.time(), "dirty": _dirty()}), encoding="utf-8")
    os.replace(tmp, f)
    if time.time() % 50 < 1:                                # now and then: snapshots of calls that never ended
        for old in f.parent.glob("*.json"):
            try:
                if time.time() - old.stat().st_mtime > 86400:
                    old.unlink()
            except OSError:
                pass


def after(payload: dict) -> str | None:
    """Tracked files that changed in the folder while the tool ran: saved on the session's branch, put back.
    Returns what to tell the session, or None."""
    f = _snapshot_file(payload)
    try:
        snap = json.loads(f.read_text(encoding="utf-8"))
        f.unlink()
    except (OSError, ValueError):
        return None
    with tree_lock(LIVE, wait=30) as held:
        if not held:
            return None
        now = _dirty()
        changed = sorted(rel for rel, st in now.items() if snap["dirty"].get(rel) != st)
        if not changed:
            return None
        import rescue_wip                                  # noqa: E402  (only when something slipped through)
        session = str(payload.get("session_id") or "unknown")
        tool = payload.get("tool_name") or ""
        what = (payload.get("tool_input") or {}).get("command") or (payload.get("tool_input") or {}).get("file_path") or ""
        group = {"branch": f"wip/{datetime.now():%Y%m%d}-{session[:8]}", "session": session,
                 "label": f"関所が見つけた書き込み（{tool}: {str(what)[:120]}）",
                 "files": [{"path": rel, "code": now[rel][0]} for rel in changed]}
        try:
            branch, commit, saved = rescue_wip.save(LIVE, group, append=True)
            where = rescue_wip.keep_dir(LIVE)
            order = sorted(saved, key=lambda rel: (rescue_wip._entry(str(LIVE), "HEAD", rel) is not None, rel))
            back = [rel for rel in order if rescue_wip.restore(LIVE, rel, saved[rel], where) == "restored"]
            rescue_wip._write_journal(str(LIVE), {"at": datetime.now().isoformat(timespec="seconds"), "branch": branch,
                                                  "commit": commit, "session": session, "label": group["label"],
                                                  "saved": saved, "by": "hook_live_tree_guard"})
        except Exception as exc:  # noqa: BLE001 — say it; the files stay as they are
            return (f"このツールの実行中に、動いているダン（{LIVE}）の git が追うファイルが変わりました: {', '.join(changed)}。"
                    f"分岐へ移せませんでした（{type(exc).__name__}: {exc}）。`python {LIVE.as_posix()}/scripts/rescue_wip.py` で確かめてください。")
    left = [rel for rel in changed if rel not in back]
    return (
        f"このツールの実行中に、動いているダン（{LIVE}）の git が追うファイルが変わりました: {', '.join(changed)}。\n"
        f"中身は分岐 {branch} に保存し、{LIVE} のファイルは GitHub の版に戻しました（戻す前のファイルの写しは {where}）。"
        + (f" 次のファイルは保存の後にまた変わったので、そのまま残しています: {', '.join(left)}。" if left else "")
        + f"\n続けるなら作業場所で: `python {LIVE.as_posix()}/scripts/work.py new <名前> --from {branch}`（続きの場所があるなら"
          f" そこで `git merge {branch}`）。{LIVE} には書かないでください。"
    )


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except Exception:  # noqa: BLE001
        return 0
    event = payload.get("hook_event_name") or (sys.argv[1] if len(sys.argv) > 1 else "PreToolUse")
    try:
        if event == "PostToolUse":
            said = after(payload)
            if said:
                print(json.dumps({"decision": "block", "reason": said,
                                  "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": said}}))
            return 0
        reason = check(payload)
        if reason:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                     "permissionDecisionReason": reason}}))   # ASCII escapes
            return 0
        before(payload)
    except Exception as exc:  # noqa: BLE001 — a broken guard must not stop every tool on the machine
        sys.stderr.write(f"hook_live_tree_guard: {type(exc).__name__}: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
