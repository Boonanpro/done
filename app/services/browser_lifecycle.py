"""Room browser ownership lives in Dan Core, never in a CLI's MCP job.

Only the local authenticated Core route may launch browsers. State is persisted
beside each profile so a Core restart does not forget a human handoff.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import secrets
import threading
import time
import urllib.request
import uuid

STATE_FILE = "dan_browser_state.json"
_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()
_launch_lock = threading.Lock()
_core_token: str | None = None


def profile_for_room(room_id: str) -> Path:
    from app.tools.browser import _safe_room_slug
    if not room_id or len(room_id) > 256:
        raise ValueError("A room_id of 1–256 characters is required")
    return Path.home() / ".ai_secretary" / f"browser_data--{_safe_room_slug(room_id)}"


def profile_lock(profile: Path):
    with _locks_guard:
        # resolve() can change Windows casing/short-name expansion when a path
        # changes from nonexistent to existing during the first launch.
        key = os.path.normcase(os.path.abspath(str(profile)))
        return _locks.setdefault(key, threading.RLock())


def _token_path() -> Path:
    port = int(os.environ.get("DAN_CORE_PORT", "9000"))
    return Path.home() / ".ai_secretary" / f"browser_manager_{port}.token"


def initialize_core() -> None:
    global _core_token
    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(secrets.token_urlsafe(32))
        path.chmod(0o600)
    except FileExistsError:
        pass
    _core_token = path.read_text(encoding="utf-8").strip()
    if len(_core_token) < 32:
        raise RuntimeError("Invalid browser manager token")


def authorized(token: str) -> bool:
    return bool(_core_token and secrets.compare_digest(token, _core_token))


def request_session(operation: str, room_id: str, reason: str = "") -> dict:
    """No local-launch fallback: that would reintroduce the disappearing page."""
    try:
        token = _token_path().read_text(encoding="utf-8").strip()
        port = int(os.environ.get("DAN_CORE_PORT", "9000"))
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/internal/browser/session",
            data=json.dumps({"operation": operation, "room_id": room_id, "reason": reason}).encode(),
            headers={"Content-Type": "application/json", "X-Dan-Browser-Token": token},
            method="POST",
        )
        # Local requests must never go through a configured HTTP proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=40) as response:
            return json.load(response)
    except Exception as exc:
        raise RuntimeError(
            "Dan Core browser manager is unavailable. The browser was not launched "
            "inside this CLI. Restore the Core connection before retrying."
        ) from exc


def read_state(profile: Path) -> dict:
    try:
        state = json.loads((profile / STATE_FILE).read_text(encoding="utf-8"))
        if not isinstance(state, dict) or not isinstance(state.get("holds", {}), dict):
            raise ValueError("Invalid browser state")
        return state
    except FileNotFoundError:
        return {"holds": {}}


def _save_state(profile: Path, state: dict) -> None:
    profile.mkdir(parents=True, exist_ok=True)
    temp = profile / f".{STATE_FILE}.{uuid.uuid4().hex}.tmp"
    try:
        temp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        # Windows scanners/readers can briefly hold a rename-incompatible file
        # handle. Keep the old complete state until the atomic replace succeeds.
        for attempt in range(6):
            try:
                temp.replace(profile / STATE_FILE)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(.05)
    finally:
        temp.unlink(missing_ok=True)


def is_held(profile: Path) -> bool:
    try:
        return bool(read_state(profile).get("holds"))
    except (OSError, ValueError):
        # A damaged state file is not evidence that the user finished.
        return True


def _cdp_ready(port: int) -> bool:
    if not 1024 <= port <= 65535:
        return False
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
            return bool(json.load(response).get("webSocketDebuggerUrl"))
    except Exception:
        return False


def _saved_port(profile: Path) -> int:
    from app.tools.browser import _PORT_FILE_NAME
    try:
        return int((profile / _PORT_FILE_NAME).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _owns_port(profile: Path, port: int) -> bool:
    """A recycled port must not attach to or close another room's Chrome."""
    import psutil
    marker = os.path.normcase(os.path.abspath(str(profile)))
    for process in psutil.process_iter(["name"]):
        if (process.info["name"] or "").lower() not in {"chrome.exe", "chromium.exe", "msedge.exe", "headless_shell.exe", "chrome", "chromium", "headless_shell"}:
            continue
        try:
            args = process.cmdline()
            profiles = [a.split("=", 1)[1].strip('"') for a in args if a.startswith("--user-data-dir=")]
            if f"--remote-debugging-port={port}" in args and any(
                os.path.normcase(os.path.abspath(p)) == marker for p in profiles
            ):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def _touch(profile: Path) -> None:
    from app.tools.browser import _LAST_USE_FILE_NAME, _safe_write_last_use
    _safe_write_last_use(profile / _LAST_USE_FILE_NAME, time.time())


def _ensure_browser(room_id: str, profile: Path) -> int:
    # Reserve/launch under one lock so two different rooms cannot choose the
    # same temporarily free port before either browser starts listening.
    with _launch_lock:
        return _ensure_browser_locked(room_id, profile)


def _ensure_browser_locked(room_id: str, profile: Path) -> int:
    from app.tools import browser
    port = _saved_port(profile)
    if _cdp_ready(port) and _owns_port(profile, port):
        _touch(profile)
        return port
    if not 1024 <= port <= 65535 or browser._port_listening(port):
        port = browser._pick_free_port()
    profile.mkdir(parents=True, exist_ok=True)
    (profile / browser._PORT_FILE_NAME).write_text(str(port), encoding="utf-8")
    # Playwright is used only to locate its bundled executable if Chrome is absent.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        executable = browser._chrome_executable_path(pw)
    x, y = browser._executor_window_position(room_id)
    browser._spawn_detached_browser(executable, str(profile), port, x, y)
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if _cdp_ready(port):
            _touch(profile)
            browser._write_browser_recovery_log("core_browser_ready", profile=profile.name, port=port)
            return port
        time.sleep(0.1)
    raise RuntimeError("Core-owned browser did not expose CDP; no CLI fallback was used")


def _close_profile(profile: Path, port: int) -> tuple[bool, bool]:
    from playwright.async_api import async_playwright
    from app.tools import browser
    if not browser._port_listening(port):
        return True, True
    if not _owns_port(profile, port):
        # This profile's browser is gone and its old port has been reused.
        return True, True
    ok = asyncio.run(browser._graceful_close_cdp(async_playwright, port))
    graceful = ok
    if not ok:
        processes, scan_ok = browser._list_dedicated_browser_processes(profile)
        if scan_ok and processes:
            browser._terminate_dedicated_browser_processes(processes)
        deadline = time.monotonic() + 5
        while browser._port_listening(port) and time.monotonic() < deadline:
            time.sleep(.1)
        ok = not browser._port_listening(port)
    return ok, graceful


def manage_session(operation: str, room_id: str, reason: str = "") -> dict:
    """Called in a Core worker thread. Never set process-global room env vars."""
    if _core_token is None:
        raise RuntimeError("Browser manager must be initialized in the owning process")
    profile = profile_for_room(room_id)
    with profile_lock(profile):
        state = read_state(profile)
        holds = state.setdefault("holds", {})
        if operation == "ensure":
            port = _ensure_browser(room_id, profile)
        elif operation in {"hold", "hold_auth"}:
            port = _saved_port(profile)
            if not (_cdp_ready(port) and _owns_port(profile, port)):
                raise RuntimeError("No live browser to hold; open it before handing it to the user")
            holds["user" if operation == "hold" else "authentication"] = reason or "Waiting for user/authentication"
        elif operation in {"release", "release_auth"}:
            if operation == "release":
                holds.clear()
            else:
                holds.pop("authentication", None)
            port = _saved_port(profile)
        elif operation == "close":
            port = _saved_port(profile)
            if port and not _close_profile(profile, port)[0]:
                raise RuntimeError("Browser could not be closed; its hold state was preserved")
            holds.clear()
        elif operation == "status":
            port = _saved_port(profile)
        else:
            raise ValueError("Unknown browser lifecycle operation")
        if operation != "status":
            state["updated_at"] = time.time()
            _save_state(profile, state)
            _touch(profile)
        alive = _cdp_ready(port) and _owns_port(profile, port)
        return {"success": True, "room_id": room_id, "port": port,
                "alive": alive, "state": "held" if alive and holds else "open" if alive else "closed",
                "holds": holds, "owner": "dan-core"}


def reap_idle(idle_seconds: int, held_profiles: set[str]) -> list[dict]:
    """Serialize cleanup with ensure/hold/release, rechecking activity under lock."""
    from app.tools import browser
    if idle_seconds <= 0:
        return []
    closed = []
    for profile in sorted((Path.home() / ".ai_secretary").glob("browser_data--*")):
        with profile_lock(profile):
            if profile.name in held_profiles or is_held(profile):
                continue
            port = _saved_port(profile)
            if not port or not browser._port_listening(port) or not _owns_port(profile, port):
                continue
            try:
                last_use = float((profile / browser._LAST_USE_FILE_NAME).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _touch(profile)
                continue
            idle = time.time() - last_use
            if idle < idle_seconds:
                continue
            ok, graceful = _close_profile(profile, port)
            if not ok:
                continue
            row = {"profile": profile.name, "port": port, "idle_minutes": round(idle / 60, 1), "graceful": graceful}
            closed.append(row)
            browser._write_browser_recovery_log("idle_browser_closed", **row)
    return closed
