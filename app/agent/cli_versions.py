"""Keep Claude Code and Codex CLI current, and say which model each Claude alias really runs.

2026-11-10: Fable 5.2 was in Anthropic's model list and the pickers said "Claude Fable 5.2", but the
installed Claude Code (2.1.303) only knew claude-fable-5-1, so every room and job still ran 5.1. The
CLI had not been updated since it was installed, and long-lived room sessions kept the old binary.

* ``ensure_current_in_background(force)`` updates both CLIs from npm at most once a day, or right away
  when a provider shows a model the installed CLI does not know yet (model_catalog calls it).
* ``claude_cli_models()`` reads the model ids built into the installed Claude Code (an alias such as
  ``fable`` runs the newest of its family the binary knows), so the label can show the version the next
  turn will actually run.
* ``fingerprint(path)`` identifies the binary a process was started from; a room's live session started
  on an older binary is restarted (with --resume) at its next turn (streaming_session).
"""

from __future__ import annotations

import fcntl
import json
import logging
import mmap
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STATE = _PROJECT_ROOT / ".data" / "model_catalog" / "cli_update.json"
_LOCK = _PROJECT_ROOT / ".data" / "model_catalog" / "cli_update.lock"
_DAILY_SECONDS = 24 * 3600
_RETRY_SECONDS = 6 * 3600          # a model the CLI does not know yet: look again at most this often
_PACKAGES = (("claude", "@anthropic-ai/claude-code"), ("codex", "@openai/codex"))

_ID = re.compile(rb"claude-(fable|opus|sonnet|haiku)-(\d)(?:-(\d{1,2}))?(?!\d)")


def fingerprint(path: Optional[str]) -> Optional[tuple]:
    """(real path, inode, mtime, size) of an executable; None when it cannot be read."""
    if not path:
        return None
    try:
        real = os.path.realpath(shutil.which(path) or path)
        st = os.stat(real)
        return (real, st.st_ino, st.st_mtime_ns, st.st_size)
    except OSError:
        return None


_scan_lock = threading.Lock()
_scan_cache: dict = {"fp": None, "models": {}}


def claude_cli_models() -> dict[str, tuple[tuple[int, int], str]]:
    """family → ((major, minor), id) of the newest model the installed Claude Code knows. {} if unknown."""
    fp = fingerprint("claude")
    if fp is None:
        return {}
    with _scan_lock:
        if _scan_cache["fp"] == fp:
            return dict(_scan_cache["models"])
        best: dict[str, tuple[tuple[int, int], str]] = {}
        try:
            with open(fp[0], "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
                for fam, major, minor in set(_ID.findall(m)):
                    family = fam.decode()
                    version = (int(major), int(minor or 0))
                    mid = f"claude-{family}-{int(major)}" + (f"-{int(minor)}" if minor else "")
                    if family not in best or version > best[family][0]:
                        best[family] = (version, mid)
        except (OSError, ValueError) as e:
            logger.info("[CLI] Claude Code model ids not read: %s", e)
            best = {}
        _scan_cache.update(fp=fp, models=best)
        return dict(best)


def label_for_id(model_id: str) -> str:
    """claude-fable-5-1 → Claude Fable 5.1"""
    m = re.match(r"^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?$", model_id or "")
    if not m:
        return model_id
    return f"Claude {m.group(1).capitalize()} {m.group(2)}" + (f".{m.group(3)}" if m.group(3) else "")


# ---------------------------------------------------------------------------
# Updating
# ---------------------------------------------------------------------------

def _npm() -> Optional[str]:
    return shutil.which("npm") or next((p for p in ("/opt/homebrew/bin/npm", "/usr/local/bin/npm") if os.path.exists(p)), None)


def _installed_version(npm: str, package: str) -> str:
    try:
        root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True, timeout=30).stdout.strip()
        data = json.loads((Path(root) / package / "package.json").read_text(encoding="utf-8"))
        return str(data.get("version") or "")
    except Exception:  # noqa: BLE001
        return ""


def _latest_version(npm: str, package: str) -> str:
    out = subprocess.run([npm, "view", package, "version"], capture_output=True, text=True, timeout=60)
    return out.stdout.strip() if out.returncode == 0 else ""


def _read_state() -> dict:
    try:
        return json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _write_state(state: dict) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_STATE)


def update_clis(reason: str = "") -> dict:
    """Install the newest Claude Code and Codex CLI when npm has a newer one. Returns what happened.

    Running sessions keep their binary (the file is replaced, not edited); new processes start on the
    new one. Only one process on this machine updates at a time (file lock)."""
    npm = _npm()
    if not npm:
        return {"error": "npm not found"}
    _LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(_LOCK, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return {"skipped": "another update is running"}
        result: dict = {"checked_at": time.time(), "reason": reason, "packages": {}}
        for name, package in _PACKAGES:
            before = _installed_version(npm, package)
            entry = {"before": before}
            try:
                latest = _latest_version(npm, package)
                entry["latest"] = latest
                if latest and latest != before:
                    out = subprocess.run([npm, "install", "-g", f"{package}@{latest}"],
                                         capture_output=True, text=True, timeout=600)
                    entry["after"] = _installed_version(npm, package)
                    if out.returncode != 0:
                        entry["error"] = (out.stderr or out.stdout)[-500:]
                    logger.info("[CLI] %s %s → %s (%s)", name, before, entry["after"], reason or "daily")
            except Exception as e:  # noqa: BLE001
                entry["error"] = str(e)[:500]
            result["packages"][name] = entry
        _write_state(result)
        return result


def cli_behind(api_families: dict) -> bool:
    """True when Anthropic lists a newer model of an offered family than the installed Claude Code knows."""
    known = claude_cli_models()
    if not known:
        return False
    for family, entry in (api_families or {}).items():
        hit = re.match(r"^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?", str((entry or {}).get("id") or ""))
        if not hit or family not in known:
            continue
        if (int(hit.group(2)), int(hit.group(3) or 0)) > known[family][0]:
            return True
    return False


_bg_lock = threading.Lock()
_bg_running = False


def due(force: bool = False, now: Optional[float] = None) -> bool:
    last = float(_read_state().get("checked_at") or 0)
    now = time.time() if now is None else now
    return now - last >= (_RETRY_SECONDS if force else _DAILY_SECONDS)


def ensure_current_in_background(force: bool = False, reason: str = "") -> bool:
    """Start an update in a background thread when one is due. ``force`` (a provider shows a model the
    CLI does not know) shortens the wait from a day to a few hours. Returns whether one was started."""
    global _bg_running
    if os.environ.get("DAN_CLI_AUTO_UPDATE", "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    if not due(force):
        return False
    with _bg_lock:
        if _bg_running:
            return False
        _bg_running = True

    def _run() -> None:
        global _bg_running
        try:
            update_clis(reason or ("new model" if force else "daily"))
        except Exception as e:  # noqa: BLE001
            logger.info("[CLI] update failed: %s", e)
        finally:
            with _bg_lock:
                _bg_running = False

    threading.Thread(target=_run, name="cli-auto-update", daemon=True).start()
    return True
