"""Activate the committed .githooks/ directory for this clone.

Runs ``git config core.hooksPath .githooks`` so hooks are sourced from
the tracked .githooks/ directory instead of the per-clone default
.git/hooks/. Idempotent. Safe to run on every Dan-core startup.

Also sets the executable bit on each hook file (matters on POSIX; no-op
on Windows but harmless).
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = ROOT / ".githooks"


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        out = subprocess.check_output(cmd, cwd=ROOT, text=True, encoding="utf-8")
        return 0, out.strip()
    except subprocess.CalledProcessError as e:
        return e.returncode, (e.output or "").strip()
    except FileNotFoundError:
        return 127, "git not found on PATH"


def _current_hooks_path() -> str:
    code, out = _run(["git", "config", "--get", "core.hooksPath"])
    return out if code == 0 else ""


def _set_hooks_path() -> bool:
    desired = ".githooks"
    if _current_hooks_path() == desired:
        return False
    code, _ = _run(["git", "config", "core.hooksPath", desired])
    if code != 0:
        raise RuntimeError("git config core.hooksPath .githooks failed")
    return True


def _make_executable(path: Path) -> None:
    # Windows: chmod has no effect on the FS, but git tracks executable bit
    # via the file mode in the index. Running this on Windows is a no-op
    # for the local filesystem.
    try:
        st = path.stat()
        path.chmod(st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


def main() -> int:
    if not HOOKS_DIR.is_dir():
        print(f"[install_git_hooks] no {HOOKS_DIR} dir, skipping")
        return 0

    changed = _set_hooks_path()

    for hook in HOOKS_DIR.iterdir():
        if hook.is_file() and not hook.name.startswith("."):
            _make_executable(hook)

    if changed:
        print(f"[install_git_hooks] core.hooksPath = .githooks (was empty / different)")
    else:
        print(f"[install_git_hooks] core.hooksPath already .githooks (ok)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
