"""
Browser Automation Tools using Playwright
Uses a dedicated thread with its own event loop to avoid Windows asyncio issues
"""
from typing import Optional, Any
import asyncio
import json
import logging
import os
import queue
import socket
import subprocess
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)
from app.tools.browser_metrics import record_timing


class _CommandCancellation:
    def __init__(self, session_event=None):
        self.local = threading.Event()
        self.session_event = session_event

    def set(self):
        self.local.set()

    def is_set(self):
        return self.local.is_set() or bool(self.session_event and self.session_event.is_set())


# ===== Executor用: 専用スレッドでPlaywrightを実行 =====

_executor_thread: Optional[threading.Thread] = None
_executor_command_queue: queue.Queue = queue.Queue()
_executor_result_queue: queue.Queue = queue.Queue()
_executor_ready = threading.Event()
_executor_shutdown = threading.Event()
_executor_page_proxy = None
_executor_browser_alive = threading.Event()  # ブラウザ生存フラグ
_executor_start_error: Optional[str] = None
_executor_cdp_port: Optional[int] = None

# 部屋（DAN_SESSION_ID）が無いレガシー実行（scripts/tests）だけが使う固定ポート。
# 部屋付きプロセスは部屋ごとに動的ポートを割り当てるので、ここには来ない。
_LEGACY_CDP_PORT = 9223
_PORT_FILE_NAME = "dan_cdp_port.txt"
_EXECUTOR_LOCK_NAMES = (
    "lockfile",
    "SingletonLock",
    "SingletonCookie",
    "SingletonSocket",
    "DevToolsActivePort",
)


def _browser_room_id() -> str:
    """このプロセスが担当する部屋。MCPサーバは部屋ごとに別プロセスで
    DAN_SESSION_ID を env に持って起動される（cli_runner._build_mcp_config）。"""
    return (os.getenv("DAN_BROWSER_ROOM") or os.getenv("DAN_SESSION_ID") or "").strip()


def _safe_room_slug(room_id: str) -> str:
    import hashlib
    import re

    slug = re.sub(r"[^A-Za-z0-9_-]", "", room_id)[:40]
    digest = hashlib.sha1(room_id.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}" if slug else digest


def _master_profile_dir() -> Path:
    return Path.home() / ".ai_secretary" / "browser_data"


def _executor_profile_dir() -> Path:
    # 部屋ごとに独立プロファイル。`browser_data--<room>` の兄弟ディレクトリにする
    # （browser_data の下に掘ると、レガシー復旧のパス一致が全部屋を巻き込むため）。
    room = _browser_room_id()
    if room:
        return Path.home() / ".ai_secretary" / f"browser_data--{_safe_room_slug(room)}"
    return _master_profile_dir()


def _executor_port_file() -> Path:
    return _executor_profile_dir() / _PORT_FILE_NAME


def _port_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _save_executor_cdp_port(port: int) -> None:
    try:
        port_file = _executor_port_file()
        port_file.parent.mkdir(parents=True, exist_ok=True)
        port_file.write_text(str(port), encoding="utf-8")
    except OSError as exc:
        _write_browser_recovery_log("port_file_write_failed", port=port, error=str(exc))


def _resolve_executor_cdp_port() -> int:
    """この部屋のCDPポートを決める。プロセス再起動後も同じ部屋のブラウザに
    再接続できるよう、選んだポートはプロファイル内のファイルに永続化する。"""
    global _executor_cdp_port
    if _executor_cdp_port is not None:
        return _executor_cdp_port
    if not _browser_room_id():
        _executor_cdp_port = _LEGACY_CDP_PORT
        return _executor_cdp_port
    try:
        saved = int(_executor_port_file().read_text(encoding="utf-8").strip())
        if 1024 <= saved <= 65535:
            _executor_cdp_port = saved
            return _executor_cdp_port
    except (OSError, ValueError):
        pass
    _executor_cdp_port = _pick_free_port()
    _save_executor_cdp_port(_executor_cdp_port)
    return _executor_cdp_port


def _reassign_executor_cdp_port() -> int:
    """保存済みポートが無関係のプロセスに取られていた場合に新しい空きポートへ移す。"""
    global _executor_cdp_port
    _executor_cdp_port = _pick_free_port()
    _save_executor_cdp_port(_executor_cdp_port)
    return _executor_cdp_port


def _executor_window_position(room_id: Optional[str] = None) -> tuple[int, int]:
    """部屋ごとにウィンドウ位置をずらし、複数部屋のヘッドフルChromeが
    完全に重なって見分けられなくなるのを避ける。"""
    import hashlib

    room = _browser_room_id() if room_id is None else room_id
    if not room:
        return (40, 40)
    h = int(hashlib.sha1(room.encode("utf-8")).hexdigest()[:8], 16)
    return (40 + (h % 5) * 90, 40 + ((h // 5) % 4) * 70)


# シードでCookieファイルをコピーできなかった時に立つ。起動後にマスターの
# CDP経由でCookieを注入する（マスター稼働中はファイルが排他ロックされるため）。
_pending_cookie_import = False


def _seed_profile_from_master(profile_dir: Path) -> None:
    """部屋プロファイル初回作成時にマスタープロファイルからログイン状態を引き継ぐ。

    全コピーはキャッシュ込みで数百MB級×部屋数に膨らむため、ログインに効く
    ものだけ選択コピーする。Cookie の復号には "Local State" 内のキーが必須。
    ベストエフォート：マスターのブラウザが起動中でロックされたファイルは
    スキップし、失敗しても（再ログインが必要になるだけなので）起動は続行する。
    """
    import shutil

    if profile_dir.exists():
        return
    master = _master_profile_dir()
    if not master.exists() or profile_dir == master:
        return

    seed_files = [
        "Local State",                # Cookie暗号鍵（無いとCookieが復号できない）
        "Default/Preferences",
        "Default/Secure Preferences",
        "Default/Network/Cookies",
        "Default/Network/Cookies-journal",
        "Default/Login Data",
        "Default/Login Data-journal",
        "Default/Web Data",
        "Default/Web Data-journal",
    ]
    seed_dirs = [
        "Default/Local Storage",      # localStorageにセッションを持つサイト用
        "Default/Session Storage",
    ]

    global _pending_cookie_import
    copied: list[str] = []
    try:
        for rel in seed_files:
            src = master / rel
            if not src.is_file():
                continue
            dst = profile_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, dst)
                copied.append(rel)
            except OSError:
                # 稼働中のマスターに排他ロックされている。Cookieは起動後に
                # マスターのCDPから注入してリカバーする。
                if rel == "Default/Network/Cookies":
                    _pending_cookie_import = True
        for rel in seed_dirs:
            src = master / rel
            if not src.is_dir():
                continue

            def _copy(s: str, d: str) -> None:
                try:
                    shutil.copy2(s, d)
                except OSError:
                    pass

            shutil.copytree(src, profile_dir / rel, copy_function=_copy, dirs_exist_ok=True)
            copied.append(rel)
        _write_browser_recovery_log(
            "profile_seeded_from_master", profile=str(profile_dir), copied=copied
        )
    except Exception as exc:
        _write_browser_recovery_log(
            "profile_seed_failed", profile=str(profile_dir), copied=copied, error=str(exc)
        )


def _encode_browser_screenshot(png_bytes: bytes) -> tuple[str, str]:
    """Encode a screenshot for the model's context, shrinking it so the CLI
    session transcript does not balloon. Every browser step adds an image; a
    long tool loop (e.g. fighting a CAPTCHA) can bloat the --resume prefill,
    which both slows the next turn and raises the parse-error/poison risk.

    Operations are driven by the element list (data-dan-ref / @e refs), NOT by
    pixel-reading the screenshot, so downscaling/recompressing does NOT affect
    clicking or typing — only fine visual reading (e.g. CAPTCHA, already
    unreliable at full resolution).

    Env knobs (read per call so they can be tuned without a code change):
      DAN_BROWSER_SHOT_MAX_WIDTH  downscale if wider, in px. 0 = no downscale. default 1280
      DAN_BROWSER_SHOT_FORMAT     'jpeg' (smaller, caps busy-page worst case) | 'png' (crisp UI text). default 'jpeg'
      DAN_BROWSER_SHOT_QUALITY    jpeg quality 1-95. default 82
    Tuning: for browser-heavy work (funnels, CAPTCHA loops) set MAX_WIDTH=1024
    for ~33% smaller shots (verified readable); set FORMAT=png MAX_WIDTH=0 to
    disable shrinking entirely when a task needs full-resolution reading.
    Falls back to the original PNG on any error.
    """
    import base64

    def _int_env(name: str, default: int) -> int:
        try:
            return int(os.getenv(name, str(default)))
        except (TypeError, ValueError):
            return default

    max_w = _int_env("DAN_BROWSER_SHOT_MAX_WIDTH", 1280)
    fmt = (os.getenv("DAN_BROWSER_SHOT_FORMAT", "jpeg") or "jpeg").strip().lower()
    quality = _int_env("DAN_BROWSER_SHOT_QUALITY", 82)
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(png_bytes))
        if max_w and img.width > max_w:
            new_h = max(1, round(img.height * max_w / img.width))
            img = img.resize((max_w, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        if fmt == "jpeg":
            img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
            media = "image/jpeg"
        else:
            img.save(buf, format="PNG", optimize=True)
            media = "image/png"
        data = buf.getvalue()
        # If the re-encode grew the image (e.g. a tiny flat PNG re-saved as
        # JPEG), keep the smaller original instead.
        if len(data) >= len(png_bytes):
            return base64.b64encode(png_bytes).decode("utf-8"), "image/png"
        return base64.b64encode(data).decode("utf-8"), media
    except Exception:
        return base64.b64encode(png_bytes).decode("utf-8"), "image/png"


# Ratio between the screenshot handed to the model and real CSS pixels, kept so
# coordinate-based actions can convert without the caller doing arithmetic.
# 1.0 until the first screenshot is taken.
_last_shot_scale: float = 1.0


def _measure_shot_scale(base64_str: str, viewport: Optional[dict]) -> float:
    """image_width / css_width for the screenshot just produced."""
    global _last_shot_scale
    try:
        import base64 as _b64
        import io

        from PIL import Image

        with Image.open(io.BytesIO(_b64.b64decode(base64_str))) as img:
            width = img.width
        css_w = float((viewport or {}).get("w") or 0)
        if width and css_w:
            _last_shot_scale = width / css_w
    except Exception:
        pass
    return _last_shot_scale


def get_last_shot_scale() -> float:
    """Scale of the most recent screenshot (image px per CSS px)."""
    return _last_shot_scale


def image_to_css(x: float, y: float) -> tuple[float, float]:
    """Convert a coordinate read off the screenshot into a clickable CSS point."""
    s = _last_shot_scale or 1.0
    return x / s, y / s


def _write_browser_recovery_log(event: str, **details: Any) -> None:
    """Persist browser recovery diagnostics without relying on MCP stdout."""
    try:
        log_path = Path.home() / ".ai_secretary" / "browser_recovery.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "event": event,
            **details,
        }
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        logger.exception("[EXECUTOR_BROWSER] Failed to write recovery log")


def _is_executor_cdp_available(port: Optional[int] = None) -> bool:
    return _port_listening(port if port is not None else _resolve_executor_cdp_port())


def _list_dedicated_browser_processes(
    profile_dir: Optional[Path] = None,
) -> tuple[list[dict[str, Any]], bool]:
    """
    List only browser processes that explicitly use DAN's dedicated profile.

    Child processes are terminated through taskkill /T after the verified root
    process is selected. Regular Chrome uses a different profile and is never
    returned here.

    ``profile_dir`` defaults to this process's room. The idle reaper runs inside
    dan-core, which belongs to no room, so it passes the profile explicitly.
    """
    if os.name != "nt":
        return [], False

    profile_marker = str(profile_dir or _executor_profile_dir()).lower().replace("/", "\\")
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match '^(chrome|chromium|msedge|headless_shell)\\.exe$' } | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        raw = result.stdout.strip()
        if not raw:
            return [], True
        rows = json.loads(raw)
        if isinstance(rows, dict):
            rows = [rows]
        matches = []
        for row in rows:
            command_line = str(row.get("CommandLine") or "").lower().replace("/", "\\")
            # 前方一致の巻き込み防止: `browser_data` は `browser_data--<room>` の
            # 接頭辞なので、マーカーの直後がパス継続文字でないことまで確認する。
            idx = command_line.find(profile_marker)
            is_exact = False
            while idx != -1:
                end = idx + len(profile_marker)
                if end == len(command_line) or command_line[end] in ('"', "'", " "):
                    is_exact = True
                    break
                idx = command_line.find(profile_marker, idx + 1)
            if is_exact:
                matches.append({
                    "pid": int(row["ProcessId"]),
                    "parent_pid": int(row.get("ParentProcessId") or 0),
                    "name": str(row.get("Name") or ""),
                })
        return matches, True
    except Exception as exc:
        _write_browser_recovery_log("process_scan_failed", error=str(exc))
        return [], False


def _executor_lock_paths() -> list[Path]:
    profile_dir = _executor_profile_dir()
    return [profile_dir / name for name in _EXECUTOR_LOCK_NAMES if (profile_dir / name).exists()]


def _remove_executor_locks() -> list[str]:
    removed = []
    for lock_path in _executor_lock_paths():
        try:
            lock_path.unlink()
            removed.append(lock_path.name)
        except OSError as exc:
            _write_browser_recovery_log(
                "lock_remove_failed",
                lock=lock_path.name,
                error=str(exc),
            )
    return removed


def _terminate_dedicated_browser_processes(processes: list[dict[str, Any]]) -> list[int]:
    terminated = []
    process_ids = {process["pid"] for process in processes}
    root_processes = [
        process for process in processes
        if process["parent_pid"] not in process_ids
    ]
    for process in root_processes:
        pid = process["pid"]
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            terminated.append(pid)
        except Exception as exc:
            _write_browser_recovery_log("process_terminate_failed", pid=pid, error=str(exc))
    return terminated


def _recover_stale_executor_profile() -> bool:
    """
    Recover DAN's dedicated browser profile without touching regular Chrome.

    Returns True only when it is safe to retry launching the dedicated browser.
    """
    cdp_available = _is_executor_cdp_available()
    processes, scan_ok = _list_dedicated_browser_processes()
    locks_before = [path.name for path in _executor_lock_paths()]
    _write_browser_recovery_log(
        "recovery_started",
        profile=str(_executor_profile_dir()),
        cdp_available=cdp_available,
        dedicated_processes=processes,
        locks=locks_before,
    )

    if cdp_available:
        _write_browser_recovery_log("recovery_skipped_cdp_available")
        return False
    if not scan_ok:
        _write_browser_recovery_log("recovery_aborted_process_scan_failed")
        return False

    terminated = _terminate_dedicated_browser_processes(processes)
    if terminated:
        time.sleep(1)

    remaining_processes, remaining_scan_ok = _list_dedicated_browser_processes()
    if not remaining_scan_ok or remaining_processes:
        _write_browser_recovery_log(
            "recovery_aborted_dedicated_processes_remain",
            terminated=terminated,
            remaining_processes=remaining_processes,
        )
        return False

    removed_locks = _remove_executor_locks()
    _write_browser_recovery_log(
        "recovery_completed",
        terminated=terminated,
        removed_locks=removed_locks,
    )
    return bool(terminated or removed_locks)


def _chrome_executable_path(playwright) -> str:
    """起動する実行ファイルを決める。実Chrome優先（H.264/AAC同梱）、無ければ同梱Chromium。"""
    channel = os.environ.get("DAN_BROWSER_CHANNEL", "chrome")
    if channel == "chrome":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return candidate
    return playwright.chromium.executable_path


def _spawn_detached_browser(
    executable: str,
    user_data_dir: str,
    cdp_port: int,
    window_x: int,
    window_y: int,
) -> None:
    """
    所有プロセスからブラウザをコンソール非依存で起動する。

    Playwright に起動させると、親プロセス（部屋ごとのMCPサーバ）が終了した
    瞬間にブラウザも道連れで殺される。ダンの常駐セッションは transcript 肥大
    ・パースエラー・ハングのたびに畳まれるため、そのたびにログイン途中の
    ページやOTP入力欄ごとブラウザが消え、ユーザーが渡したコードが無駄になって
    いた。DETACHED_PROCESS は Windows Job Object からは分離しない。
    部屋付きブラウザは必ず Dan Core がこの関数を呼び、CLI は CDP 接続だけ行う。
    """
    args = [
        executable,
        f"--remote-debugging-port={cdp_port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={user_data_dir}",
        "--disable-blink-features=AutomationControlled",
        f"--window-position={window_x},{window_y}",
        "--window-size=1440,900",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        "about:blank",
    ]
    creationflags = 0
    if Path(user_data_dir).name.startswith('browser_data--voice-job-'):
        args.insert(1, '--headless=new')
    if os.name == "nt":
        # Console detachment only. The caller must be the persistent owner.
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        args,
        creationflags=creationflags,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def _connect_detached_browser(playwright, cdp_port: int, timeout: float = 30.0):
    """detached 起動したブラウザの CDP が開くまで待って接続する。"""
    deadline = time.time() + timeout
    last_exc: Optional[Exception] = None
    while time.time() < deadline:
        if _port_listening(cdp_port):
            try:
                return await playwright.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{cdp_port}", timeout=5000
                )
            except Exception as exc:  # 起動直後は CDP がまだ応答しないことがある
                last_exc = exc
        await asyncio.sleep(0.25)
    raise RuntimeError(
        f"detached browser did not expose CDP on port {cdp_port} within {timeout}s"
        + (f": {last_exc}" if last_exc else "")
    )


async def _fetch_master_cookies_raw() -> list[dict]:
    """稼働中マスターブラウザから生CDPでCookie一覧を取得する。

    Playwrightのconnect_over_cdpはブラウザ内の全ページへのアタッチを伴い、
    ビジー状態のマスターではハングするため使わない（実測でtimeout）。
    Storage.getCookiesはブラウザレベルの読み取りのみでタブに一切触れない。
    """
    import urllib.request

    import websockets

    with urllib.request.urlopen(
        f"http://127.0.0.1:{_LEGACY_CDP_PORT}/json/version", timeout=3
    ) as resp:
        ws_url = json.loads(resp.read())["webSocketDebuggerUrl"]
    async with websockets.connect(
        ws_url, max_size=64 * 1024 * 1024, open_timeout=5, close_timeout=2
    ) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Storage.getCookies"}))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if msg.get("id") == 1:
                return msg.get("result", {}).get("cookies", [])


def _cdp_cookie_to_playwright(cookie: dict) -> dict:
    out = {
        "name": cookie["name"],
        "value": cookie["value"],
        "domain": cookie["domain"],
        "path": cookie.get("path", "/"),
        "httpOnly": bool(cookie.get("httpOnly")),
        "secure": bool(cookie.get("secure")),
    }
    expires = cookie.get("expires")
    if isinstance(expires, (int, float)) and expires > 0:
        out["expires"] = expires
    if cookie.get("sameSite") in ("Strict", "Lax", "None"):
        out["sameSite"] = cookie["sameSite"]
    return out


async def _import_master_cookies(context) -> None:
    """稼働中マスターブラウザからCookieを取得して部屋コンテキストへ注入する。
    失敗しても（再ログインが必要になるだけなので）起動は続行。"""
    global _pending_cookie_import
    if not _port_listening(_LEGACY_CDP_PORT):
        _write_browser_recovery_log("cookie_import_skipped_master_offline")
        _pending_cookie_import = False
        return
    try:
        cookies = await _fetch_master_cookies_raw()
        added = 0
        for cookie in cookies:
            try:
                await context.add_cookies([_cdp_cookie_to_playwright(cookie)])
                added += 1
            except Exception:
                continue  # 変換できない特殊Cookieはスキップ
        _write_browser_recovery_log(
            "cookie_import_from_master", total=len(cookies), added=added
        )
        _pending_cookie_import = False
    except Exception as exc:
        _write_browser_recovery_log("cookie_import_failed", error=str(exc))


def _executor_thread_main():
    """Executor用Playwright専用スレッド"""
    # Windows用のProactorEventLoopを設定
    if hasattr(asyncio, 'WindowsProactorEventLoopPolicy'):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(_executor_worker())
    finally:
        loop.close()


async def _executor_worker():
    """Executor用ブラウザワーカー"""
    from playwright.async_api import async_playwright

    global _executor_start_error

    playwright = None
    browser = None
    context = None
    attached_to_existing_browser = False
    page = None

    # ページ状態を管理（複数タブ対応）
    pages_state = {
        "current": None,  # 現在アクティブなページ
        "all_pages": [],  # 全てのページ
    }

    def on_new_page(new_page):
        """新しいタブ/ページが開かれた時のハンドラ"""
        print(f"[EXECUTOR_BROWSER] New tab opened: {new_page.url}")
        pages_state["all_pages"].append(new_page)

    try:
        print("[EXECUTOR_BROWSER] Starting Playwright...")
        playwright = await async_playwright().start()

        profile_dir = _executor_profile_dir()
        _seed_profile_from_master(profile_dir)
        user_data_dir = str(profile_dir)
        os.makedirs(user_data_dir, exist_ok=True)

        if _browser_room_id():
            # A Codex MCP job kills *all* descendants on a normal turn exit,
            # including DETACHED_PROCESS children. Only Core may launch them.
            from app.services.browser_lifecycle import request_session
            session = await asyncio.to_thread(request_session, "ensure", _browser_room_id())
            cdp_port = session["port"]
            global _executor_cdp_port
            _executor_cdp_port = cdp_port
            try:
                browser = await playwright.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{cdp_port}", timeout=20000,
                )
            except Exception as exc:
                # A browser left by an earlier job can refuse the CDP handshake (2026-09-22: "Timeout 5000ms exceeded"
                # after the WebSocket had connected, twice in a row). A job must not die on that: the room's browser is
                # closed and reopened, and the job goes on with a fresh window (what was on screen is lost, nothing else).
                print(f"[EXECUTOR_BROWSER] Reconnect to the room's browser failed ({type(exc).__name__}); reopening it")
                _write_browser_recovery_log("core_browser_reconnect_failed", port=cdp_port, error=str(exc)[:200])
                await asyncio.to_thread(request_session, "close", _browser_room_id(), "reconnect failed; reopening")
                session = await asyncio.to_thread(request_session, "ensure", _browser_room_id())
                cdp_port = session["port"]
                _executor_cdp_port = cdp_port
                browser = await playwright.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{cdp_port}", timeout=20000,
                )
            context = browser.contexts[0]
            attached_to_existing_browser = True
            if _pending_cookie_import:
                await _import_master_cookies(context)
        else:
            cdp_port = _resolve_executor_cdp_port()

        # 再接続は「この部屋のポート」が実際に開いている時だけ試す。
        # 以前は 9223 固定で、別部屋が立てたブラウザに相乗りしてタブを
        # 奪い合っていた。ポートが部屋ごとに違う今、ここで繋がるのは
        # 自室のブラウザだけ。
        connect_exc: Optional[Exception] = None
        if not attached_to_existing_browser and _port_listening(cdp_port):
            try:
                browser = await playwright.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{cdp_port}",
                    timeout=1000,
                )
                context = browser.contexts[0]
                attached_to_existing_browser = True
                print(f"[EXECUTOR_BROWSER] Reconnected to existing browser (port {cdp_port})")
            except Exception as exc:
                connect_exc = exc

        if not attached_to_existing_browser:
            if connect_exc is not None and _browser_room_id():
                # ポートは開いているのにCDP接続できない＝無関係のプロセスが
                # 使っている。この部屋のポートを取り直す。
                cdp_port = _reassign_executor_cdp_port()
                _write_browser_recovery_log("cdp_port_reassigned", port=cdp_port, error=str(connect_exc))

            window_x, window_y = _executor_window_position()

            # ブラウザは detached で起動して CDP で「外から」繋ぐ。Playwright に
            # 起動させるとこのプロセス（部屋ごとのMCPサーバ）の子になり、常駐
            # セッションが畳まれるたびにブラウザごと道連れで死ぬ。ログイン途中の
            # ページやOTP入力欄が消える主因だった。詳細は _spawn_detached_browser。
            executable = _chrome_executable_path(playwright)

            async def launch_detached_and_connect():
                _spawn_detached_browser(
                    executable, user_data_dir, cdp_port, window_x, window_y
                )
                return await _connect_detached_browser(playwright, cdp_port)

            try:
                browser = await launch_detached_and_connect()
            except Exception as launch_exc:
                _write_browser_recovery_log(
                    "launch_failed",
                    profile=user_data_dir,
                    cdp_available=_is_executor_cdp_available(),
                    connect_error=str(connect_exc),
                    launch_error=str(launch_exc),
                )
                if not _recover_stale_executor_profile():
                    raise
                _write_browser_recovery_log("launch_retry_started", profile=user_data_dir)
                browser = await launch_detached_and_connect()
                _write_browser_recovery_log("launch_retry_succeeded", profile=user_data_dir)

            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            # 自前起動＝このプロセスの所有物ではない。終了時に閉じてはいけない
            # （閉じると元の「毎ターン消える」問題に戻る）。
            attached_to_existing_browser = True

            if _pending_cookie_import:
                await _import_master_cookies(context)

        # 新しいタブを検知するリスナーを登録
        context.on("page", on_new_page)

        # 再接続時は最後に使っていたタブを優先する
        if context.pages:
            pages_state["all_pages"].extend(context.pages)
            page = context.pages[-1]
        else:
            page = await context.new_page()
            pages_state["all_pages"].append(page)
        pages_state["current"] = page

        print("[EXECUTOR_BROWSER] Browser ready")
        _executor_start_error = None
        _executor_ready.set()
        _executor_browser_alive.set()  # ブラウザ生存フラグをセット

        # コマンドループ
        while not _executor_shutdown.is_set():
            try:
                cmd, args, request = _executor_command_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            reply = request["reply"] if request else _executor_result_queue
            if request and request["cancelled"].is_set():
                continue
            started = time.perf_counter()
            outcome = "error"
            try:
                if request:
                    args = {**args, "_cancelled": request["cancelled"]}
                result = await _execute_page_command(pages_state, context, cmd, args)
                outcome = "failed" if isinstance(result, dict) and result.get("success") is False else "success"
                reply.put(("success", result))
            except Exception as e:
                error_str = str(e).lower()
                # ブラウザクローズエラーを検出
                if "closed" in error_str or "target" in error_str or "disposed" in error_str:
                    print(f"[EXECUTOR_BROWSER] Browser has been closed: {e}")
                    _executor_browser_alive.clear()  # ブラウザ死亡をマーク
                    reply.put(("browser_closed", str(e)))
                    break  # ワーカーループを終了してスレッドを終了させる
                reply.put(("error", str(e)))
            finally:
                # No URLs, form contents, selectors, screenshots or credentials.
                logger.info("BROWSER_TIMING command=%s execution_ms=%.2f", cmd,
                            (time.perf_counter() - started) * 1000)
                record_timing("execution", cmd, (time.perf_counter() - started) * 1000, outcome)

    except Exception as exc:
        _executor_start_error = str(exc)
        _write_browser_recovery_log("worker_start_failed", error=str(exc))
        _executor_ready.set()
        raise
    finally:
        _executor_browser_alive.clear()  # ブラウザ死亡をマーク
        if not attached_to_existing_browser:
            try:
                if page:
                    await page.close()
            except Exception:
                pass
            try:
                if context:
                    await context.close()
            except Exception:
                pass
            try:
                if browser:
                    await browser.close()
            except Exception:
                pass
        try:
            if playwright:
                await playwright.stop()
        except Exception:
            pass
        print("[EXECUTOR_BROWSER] Browser closed")


_EVAL_BLOCKED_MARKERS = (
    "eval is disabled",
    "unsafe-eval",
    "Content Security Policy",
    "call to eval() blocked",
    "EvalError",
)


async def _cdp_evaluate(page, expression: str, arg=None):
    """CSPやサイト側のパッチで window.eval が殺されたページ用の迂回路。

    Playwright の page.evaluate は注入したユーティリティを eval で実行する。
    American Express のように window.eval を自前で潰すサイトでは、要素一覧も
    スクリーンショットの縮小率計算も全部落ちて、ページが一切操作できなくなる。
    CDP の Runtime.evaluate は V8 インスペクタ側で走るのでその影響を受けない。
    """
    arg_js = json.dumps(arg) if arg is not None else "undefined"
    wrapped = (
        "(() => { const __danFn = ("
        + expression
        + "); return (typeof __danFn === 'function') ? __danFn("
        + arg_js
        + ") : __danFn; })()"
    )
    session = await page.context.new_cdp_session(page)
    try:
        res = await session.send(
            "Runtime.evaluate",
            {
                "expression": wrapped,
                "returnByValue": True,
                "awaitPromise": True,
                "userGesture": True,
            },
        )
    finally:
        try:
            await session.detach()
        except Exception:
            pass
    if res.get("exceptionDetails"):
        detail = res["exceptionDetails"]
        raise RuntimeError(detail.get("text") or str(detail))
    return res.get("result", {}).get("value")


async def _page_evaluate(page, expression: str, arg=None):
    """通常は page.evaluate。eval が禁止されたページだけ CDP に落とす。"""
    try:
        if arg is not None:
            return await page.evaluate(expression, arg)
        return await page.evaluate(expression)
    except Exception as exc:
        message = str(exc)
        if not any(marker in message for marker in _EVAL_BLOCKED_MARKERS):
            raise
        return await _cdp_evaluate(page, expression, arg)


async def _execute_page_command(pages_state: dict, context, cmd: str, args: dict):
    """ページコマンドを実行"""
    page = pages_state["current"]

    if cmd == "fill_form":
        from app.tools.browser_actions import fill_form
        return await fill_form(page, args["fields"], args["expected_url"], args.get("_cancelled"))
    if cmd == "guarded_click":
        from app.tools.browser_actions import guarded_click
        return await guarded_click(page, args["ref"], args.get("timeout", 10000), args.get("_cancelled"))
    if cmd == "wait_for_condition":
        from app.tools.browser_actions import wait_for_condition
        return await wait_for_condition(page, args["condition"])
    if cmd == "check_condition_before_action":
        from app.tools.browser_actions import check_condition_before_action
        return await check_condition_before_action(page, args["condition"])

    # タブ管理コマンド
    if cmd == "switch_to_latest_tab":
        # 最新のタブに切り替え
        all_pages = pages_state["all_pages"]
        if len(all_pages) > 1:
            # 閉じられたページを除外
            valid_pages = [p for p in all_pages if not p.is_closed()]
            pages_state["all_pages"] = valid_pages

            if valid_pages:
                latest = valid_pages[-1]
                if latest != pages_state["current"]:
                    pages_state["current"] = latest
                    await latest.bring_to_front()
                    await latest.wait_for_load_state("domcontentloaded")
                    print(f"[EXECUTOR_BROWSER] Switched to tab: {latest.url}")
                    return {"switched": True, "url": latest.url, "tab_count": len(valid_pages)}
        return {"switched": False, "url": page.url, "tab_count": len(pages_state["all_pages"])}

    elif cmd == "get_tab_count":
        # 有効なタブ数を取得
        valid_pages = [p for p in pages_state["all_pages"] if not p.is_closed()]
        pages_state["all_pages"] = valid_pages
        return {"count": len(valid_pages), "current_url": page.url}

    elif cmd == "close_current_tab":
        # 現在のタブを閉じて前のタブに切り替え
        all_pages = pages_state["all_pages"]
        if len(all_pages) > 1:
            current = pages_state["current"]
            all_pages.remove(current)
            await current.close()
            pages_state["current"] = all_pages[-1]
            await pages_state["current"].bring_to_front()
            return {"closed": True, "url": pages_state["current"].url}
        return {"closed": False, "url": page.url}

    elif cmd == "goto":
        await page.goto(args["url"], wait_until=args.get("wait_until", "domcontentloaded"))
        return {"url": page.url}

    elif cmd == "get_url":
        return {"url": page.url}

    elif cmd == "save_image":
        # URLから画像をダウンロードしてファイルに保存
        url = args["url"]
        save_path = args["path"]
        response = await context.request.get(url)
        body = await response.body()
        import pathlib
        pathlib.Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(body)
        return {"saved": save_path, "size": len(body)}

    elif cmd == "upload_file":
        # ローカルファイルをページのアップロード欄に渡す。
        # 1) 既に input[type=file] があればそこへ直接セット
        # 2) 無ければ「アップロード」ボタンをクリックしてファイル選択ダイアログを捕まえる
        files = args["files"]
        if isinstance(files, str):
            files = [files]
        ref = args.get("ref")
        selector = args.get("selector")
        timeout = args.get("timeout", 20000)

        file_inputs = page.locator("input[type=file]")
        if not ref and not selector:
            if await file_inputs.count() == 0:
                raise RuntimeError("input[type=file] が見つかりません。ref か selector でアップロードボタンを指定してください")
            await file_inputs.last.set_input_files(files)
            return {"uploaded": files, "via": "input"}

        if selector:
            target = page.locator(selector)
        else:
            target = page.locator(f'[data-dan-ref="{str(ref).replace("@", "")}"]').last

        async with page.expect_file_chooser(timeout=timeout) as fc_info:
            await target.click()
        chooser = await fc_info.value
        await chooser.set_files(files)
        return {"uploaded": files, "via": "file_chooser"}

    elif cmd == "locator_count":
        count = await page.locator(args["selector"]).count()
        return {"count": count}

    elif cmd == "locator_fill":
        await page.locator(args["selector"]).fill(args["value"])
        return {}

    elif cmd == "locator_click":
        await page.locator(args["selector"]).click(force=args.get("force", False))
        return {}

    elif cmd == "locator_select_option":
        await page.locator(args["selector"]).select_option(value=args.get("value"))
        return {}

    elif cmd == "wait_for_load_state":
        timeout = args.get("timeout")
        if timeout:
            await page.wait_for_load_state(args.get("state", "domcontentloaded"), timeout=timeout)
        else:
            await page.wait_for_load_state(args.get("state", "domcontentloaded"))
        return {}

    elif cmd == "wait_for_timeout":
        await page.wait_for_timeout(args["timeout"])
        return {}

    elif cmd == "keyboard_press":
        await page.keyboard.press(args["key"])
        return {}

    elif cmd == "keyboard_type":
        # テキストを入力（一文字ずつではなく一括）
        await page.keyboard.type(args["text"], delay=args.get("delay", 50))
        return {}

    elif cmd == "screenshot":
        await page.screenshot(path=args["path"], full_page=args.get("full_page", True))
        return {"path": args["path"]}

    elif cmd == "screenshot_base64":
        screenshot_bytes = await page.screenshot(full_page=args.get("full_page", False))
        base64_str, media_type = _encode_browser_screenshot(screenshot_bytes)
        # The image handed to the model is downscaled, but clicks are taken in CSS
        # pixels. Reading a coordinate off the picture and clicking it therefore
        # lands short of the target — the piece is never grabbed and the puzzle
        # "does not move". Ship the ratio with the image so nobody has to
        # remember or re-derive it.
        scale = _measure_shot_scale(base64_str, await _page_evaluate(
            page, "() => ({w: window.innerWidth, h: window.innerHeight})"
        ))
        return {
            "base64": base64_str,
            "media_type": media_type,
            "shot_scale": scale,
        }

    elif cmd == "mouse_click":
        await page.mouse.click(args["x"], args["y"])
        return {}

    elif cmd == "mouse_move":
        await page.mouse.move(args["x"], args["y"], steps=args.get("steps", 1))
        return {}

    elif cmd == "mouse_down":
        await page.mouse.down()
        return {}

    elif cmd == "mouse_up":
        await page.mouse.up()
        return {}

    elif cmd == "go_back":
        await page.go_back()
        return {"url": page.url}

    elif cmd == "go_forward":
        await page.go_forward()
        return {"url": page.url}

    elif cmd == "reload":
        await page.reload()
        return {"url": page.url}

    elif cmd == "content":
        html = await page.content()
        return {"content": html}

    elif cmd == "evaluate":
        # arg を渡せるようにする（captcha_solver のトークン注入等で使用）。
        # arg=None の従来呼び出しは引数なし evaluate にフォールバックして後方互換。
        if args.get("arg") is not None:
            result = await _page_evaluate(page, args["expression"], args["arg"])
        else:
            result = await _page_evaluate(page, args["expression"])
        return {"result": result}

    elif cmd == "list_frames":
        # captcha等がiframe内にある場合に、中のドキュメントへ届くようにする。
        out = []
        for i, f in enumerate(page.frames):
            try:
                out.append({"index": i, "url": f.url or "", "name": f.name or ""})
            except Exception:
                continue
        return {"frames": out}

    elif cmd == "frame_evaluate":
        frames = page.frames
        target = None
        frame_url = args.get("frame_url")
        idx = args.get("frame_index")
        if isinstance(idx, int) and 0 <= idx < len(frames):
            target = frames[idx]
        # インデックスがずれている場合はURLで引き直す
        if frame_url and (target is None or (target.url or "") != frame_url):
            for f in frames:
                if (f.url or "") == frame_url:
                    target = f
                    break
        if target is None:
            return {"result": None, "error": "frame not found"}
        if args.get("arg") is not None:
            result = await target.evaluate(args["expression"], args["arg"])
        else:
            result = await target.evaluate(args["expression"])
        return {"result": result}

    elif cmd == "wait_for_selector":
        try:
            element = await page.wait_for_selector(
                args["selector"],
                timeout=args.get("timeout", 30000),
                state=args.get("state", "visible")
            )
            return {"found": element is not None}
        except Exception:
            return {"found": False}

    elif cmd == "query_selector":
        element = await page.query_selector(args["selector"])
        return {"found": element is not None}

    elif cmd == "query_selector_all":
        elements = await page.query_selector_all(args["selector"])
        return {"count": len(elements)}

    elif cmd == "locator_is_visible":
        locator = page.locator(args["selector"])
        if args.get("index") is not None:
            locator = locator.nth(args["index"])
        visible = await locator.is_visible()
        return {"visible": visible}

    elif cmd == "locator_text_content":
        locator = page.locator(args["selector"])
        if args.get("index") is not None:
            locator = locator.nth(args["index"])
        text = await locator.text_content()
        return {"text": text or ""}

    elif cmd == "locator_get_attribute":
        locator = page.locator(args["selector"])
        if args.get("index") is not None:
            locator = locator.nth(args["index"])
        value = await locator.get_attribute(args["name"])
        return {"value": value}

    elif cmd == "locator_evaluate":
        locator = page.locator(args["selector"])
        if args.get("index") is not None:
            locator = locator.nth(args["index"])
        result = await locator.evaluate(args["expression"])
        return {"result": result}

    elif cmd == "locator_is_enabled":
        locator = page.locator(args["selector"])
        if args.get("index") is not None:
            locator = locator.nth(args["index"])
        enabled = await locator.is_enabled()
        return {"enabled": enabled}

    elif cmd == "locator_click_nth":
        await page.locator(args["selector"]).nth(args["index"]).click(force=args.get("force", False))
        return {}

    elif cmd == "aria_snapshot":
        # Playwrightのアクセシビリティツリーを取得
        snapshot = await page.accessibility.snapshot()
        return {"snapshot": snapshot}

    elif cmd == "get_interactive_elements":
        # インタラクティブ要素のリストを取得（ダンの視覚用）
        # JavaScriptで要素を列挙し、ref IDを振る
        script = """
        () => {
            const interactiveSelectors = [
                'a[href]', 'button', 'input', 'select', 'textarea',
                '[role="button"]', '[role="link"]', '[role="checkbox"]',
                '[role="radio"]', '[role="combobox"]', '[role="textbox"]',
                '[role="searchbox"]', '[role="listbox"]', '[role="option"]',
                '[tabindex]:not([tabindex="-1"])', '[onclick]'
            ];

            const elements = [];
            const seen = new Set();
            // Open shadow roots are part of what the user sees (consent/campaign
            // modals often live there). document.querySelectorAll stops at the host.
            window.__danDeep = (selector) => {
                const out = [];
                const walk = (root) => {
                    out.push(...root.querySelectorAll(selector));
                    for (const host of root.querySelectorAll('*')) if (host.shadowRoot) walk(host.shadowRoot);
                };
                walk(document);
                return out;
            };
            // Keep references attached to DOM identity. Re-numbering from e1
            // on every observation can silently redirect a previously seen ref.
            if (!window.__danRefState || window.__danRefState.version !== 2) {
                const bytes = crypto.getRandomValues(new Uint8Array(6));
                const prefix = btoa(String.fromCharCode(...bytes)).replaceAll('+','-').replaceAll('/','_');
                window.__danDeep('[data-dan-ref]').forEach(el => el.removeAttribute('data-dan-ref'));
                window.__danRefState = {version: 2, prefix, next: 1, nodes: new WeakMap()};
            }
            const refState = window.__danRefState;

            for (const selector of interactiveSelectors) {
                for (const el of window.__danDeep(selector)) {
                    if (seen.has(el)) continue;
                    seen.add(el);

                    // 表示されている要素のみ
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) continue;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') continue;

                    // data-ref属性を付与
                    let ref = refState.nodes.get(el);
                    if (!ref) {
                        ref = `${refState.prefix}:${(refState.next++).toString(36)}`;
                        refState.nodes.set(el, ref);
                    }
                    el.setAttribute('data-dan-ref', ref);

                    // 要素情報を収集
                    const tagName = el.tagName.toLowerCase();
                    const type = el.getAttribute('type') || '';
                    const role = el.getAttribute('role') || tagName;
                    const text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().slice(0, 50);
                    const name = el.getAttribute('name') || '';
                    const id = el.id || '';

                    // ARIA状態を収集
                    const states = [];
                    if (el.disabled || el.getAttribute('aria-disabled') === 'true') states.push('disabled');
                    if (el.getAttribute('aria-checked') === 'true') states.push('checked');
                    if (el.getAttribute('aria-expanded') === 'true') states.push('expanded');
                    if (el.getAttribute('aria-expanded') === 'false') states.push('collapsed');
                    if (el.getAttribute('aria-selected') === 'true') states.push('selected');
                    if (el.required || el.getAttribute('aria-required') === 'true') states.push('required');

                    elements.push({
                        ref: '@' + ref,
                        tag: tagName,
                        role: role,
                        type: type,
                        text: text,
                        name: name,
                        id: id,
                        states: states,
                        rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) }
                    });
                }
            }

            return elements;
        }
        """
        elements = await _page_evaluate(page, script)
        return {"elements": elements, "count": len(elements)}

    elif cmd == "click_by_ref":
        # data-dan-ref属性でクリック
        ref = args["ref"].replace("@", "")
        timeout = args.get("timeout", 30000)
        await page.locator(f'[data-dan-ref="{ref}"]').click(force=args.get("force", False), timeout=timeout)
        return {}

    elif cmd == "fill_by_ref":
        # data-dan-ref属性で入力
        ref = args["ref"].replace("@", "")
        await page.locator(f'[data-dan-ref="{ref}"]').fill(args["value"])
        return {}

    elif cmd == "get_page_summary":
        # ページの要約情報を取得（タイトル、URL、主要なテキスト）
        title = await page.title()
        url = page.url

        # 主要なテキストを取得
        main_text_script = """
        () => {
            const mainSelectors = ['main', 'article', '#content', '.content', '#main', '.main'];
            for (const sel of mainSelectors) {
                const el = document.querySelector(sel);
                if (el) return el.innerText.slice(0, 1000);
            }
            return document.body.innerText.slice(0, 1000);
        }
        """
        main_text = await _page_evaluate(page, main_text_script)

        return {
            "title": title,
            "url": url,
            "main_text": main_text
        }

    elif cmd == "get_page_context":
        # ページ状態の汎用スナップショット（OpenClaw方式）
        script = """
        () => {
            const ctx = {};

            // 1. 見出し（ページの文脈理解）
            ctx.headings = [...document.querySelectorAll('h1, h2, h3')]
                .slice(0, 5)
                .map(el => ({ level: el.tagName, text: el.innerText.trim().slice(0, 80) }))
                .filter(h => h.text);

            // 2. フィードバックメッセージ（成功/エラー/警告/情報）
            const feedbackSelectors = [
                '[role="alert"]', '[role="status"]',
                '[class*="error"]', '[class*="success"]', '[class*="warning"]', '[class*="info"]',
                '[class*="notification"]', '[class*="toast"]', '[class*="banner"]', '[class*="message"]'
            ];
            const feedbackEls = document.querySelectorAll(feedbackSelectors.join(','));
            const seen = new Set();
            ctx.feedback = [];
            feedbackEls.forEach(el => {
                const text = (el.innerText || '').trim().slice(0, 120);
                if (text && !seen.has(text) && text.length > 2) {
                    seen.add(text);
                    ctx.feedback.push(text);
                }
            });
            ctx.feedback = ctx.feedback.slice(0, 5);

            // 3. モーダル/ダイアログの有無と内容
            const modal = document.querySelector('dialog[open], [role="dialog"], [class*="modal"][class*="show"]');
            if (modal) {
                ctx.modal = (modal.innerText || '').trim().slice(0, 200);
            } else {
                ctx.modal = null;
            }

            // 4. ローディング状態
            ctx.isLoading = document.querySelectorAll(
                '[class*="spinner"], [class*="loading"], [aria-busy="true"], [class*="skeleton"]'
            ).length > 0;

            // 5. バッジ/カウンター
            const badges = [];
            document.querySelectorAll('[class*="badge"], [class*="count"], [class*="cart-count"]')
                .forEach(el => {
                    const text = (el.innerText || '').trim();
                    const parent = el.closest('a, button, [role="link"]');
                    const context = parent ? (parent.getAttribute('aria-label') || parent.innerText || '').trim().slice(0, 30) : '';
                    if (text && /^\\d+$/.test(text)) {
                        badges.push({ value: text, context: context || 'unknown' });
                    }
                });
            ctx.badges = badges.slice(0, 5);

            // 6. 入力済みフォーム値（パスワードは除外）
            const filledInputs = [];
            document.querySelectorAll('input, textarea, select').forEach(el => {
                if (el.type === 'password' || el.type === 'hidden') return;
                const val = el.value || '';
                if (!val) return;
                const label = el.getAttribute('aria-label') || el.placeholder
                    || (el.labels && el.labels[0] ? el.labels[0].innerText : '') || el.name || '';
                filledInputs.push({ label: label.trim().slice(0, 40), value: val.trim().slice(0, 50) });
            });
            ctx.filledInputs = filledInputs.slice(0, 10);

            return ctx;
        }
        """
        result = await _page_evaluate(page, script)
        return {"context": result}

    else:
        raise ValueError(f"Unknown command: {cmd}")


def _ensure_executor_thread():
    """Executor用スレッドを確保（ブラウザ生存チェック付き）"""
    global _executor_thread, _executor_command_queue, _executor_result_queue
    global _executor_start_error

    # スレッドが生きていてもブラウザが死んでいれば再起動が必要
    need_restart = (
        _executor_thread is None or
        not _executor_thread.is_alive() or
        not _executor_browser_alive.is_set()  # ブラウザ死亡チェック
    )

    if need_restart:
        # 既存スレッドが生きている場合はシャットダウンを待つ
        if _executor_thread is not None and _executor_thread.is_alive():
            print("[EXECUTOR_BROWSER] Browser died, shutting down old thread...")
            _executor_shutdown.set()
            _executor_thread.join(timeout=5)

        _executor_ready.clear()
        _executor_shutdown.clear()
        _executor_browser_alive.clear()
        _executor_start_error = None

        # キューをクリア（古いセッションのゴミを除去）
        _executor_command_queue = queue.Queue()
        _executor_result_queue = queue.Queue()

        _executor_thread = threading.Thread(target=_executor_thread_main, daemon=True)
        _executor_thread.start()

        print("[EXECUTOR_BROWSER] Waiting for browser to be ready...")

        # 準備完了を待機
        if not _executor_ready.wait(timeout=45 if _browser_room_id() else 30):
            _write_browser_recovery_log(
                "worker_ready_timeout",
                profile=str(_executor_profile_dir()),
                cdp_available=_is_executor_cdp_available(),
            )
            raise RuntimeError("Executor browser failed to start")
        if _executor_start_error:
            raise RuntimeError(f"Executor browser failed to start: {_executor_start_error}")


_LAST_USE_FILE_NAME = "dan_last_use.txt"


def _touch_browser_activity() -> None:
    """この部屋のブラウザを「今使った」と記録する。

    ブラウザは detached で動くのでプロセスが終わっても生き残る（それが狙い）。
    その代わり誰も片付けないと部屋の数だけ Chrome が積み上がるため、常駐する
    ダンコアが最終使用時刻を見て放置分を閉じる。時刻はプロセスをまたぐので
    メモリではなくプロファイル内のファイルに置く。
    """
    try:
        path = _executor_profile_dir() / _LAST_USE_FILE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(time.time()), encoding="utf-8")
    except Exception:
        # 掃除のための補助情報。書けなくてもブラウザ操作は止めない。
        pass


def _send_executor_command(cmd: str, **args) -> dict:
    """Executorスレッドにコマンドを送信（ブラウザクローズ時は自動再起動、キャンセル対応）"""
    from app.services.cancellation import CancellationRegistry, CancelledError

    _touch_browser_activity()

    max_retries = 2  # ブラウザクローズ時のリトライ回数

    # コマンド送信前にキャンセルチェック
    if CancellationRegistry.check_cancelled():
        session_id = CancellationRegistry.get_current_session()
        print(f"[EXECUTOR_BROWSER] Command cancelled before execution: {cmd}")
        raise CancelledError(session_id or "unknown", "ブラウザ操作がキャンセルされました")

    for attempt in range(max_retries):
        _ensure_executor_thread()

        # Per-request replies prevent a timed-out command's late result from
        # being mistaken for the next command's success.
        request = {"reply": queue.Queue(), "cancelled": _CommandCancellation(
            CancellationRegistry.get_event(CancellationRegistry.get_current_session()))}
        _executor_command_queue.put((cmd, args, request))
        started = time.perf_counter()

        # 結果を待機（短いタイムアウトでループし、キャンセルをチェック）
        wait_timeout = 2.0  # 2秒ごとにキャンセルチェック
        total_timeout = 60.0  # 全体のタイムアウト
        elapsed = 0.0

        while elapsed < total_timeout:
            # キャンセルチェック
            if CancellationRegistry.check_cancelled():
                request["cancelled"].set()
                session_id = CancellationRegistry.get_current_session()
                print(f"[EXECUTOR_BROWSER] Command cancelled during execution: {cmd}")
                raise CancelledError(session_id or "unknown", "ブラウザ操作がキャンセルされました")

            try:
                status, result = request["reply"].get(timeout=wait_timeout)
                logger.info("BROWSER_TIMING command=%s roundtrip_ms=%.2f status=%s", cmd,
                            (time.perf_counter() - started) * 1000, status)
                record_timing("roundtrip", cmd, (time.perf_counter() - started) * 1000, status)
                if status == "error":
                    raise RuntimeError(result)
                elif status == "browser_closed":
                    # A click/input may already have happened. Never replay it.
                    if cmd not in {"get_url", "get_tab_count", "screenshot_base64", "get_interactive_elements", "get_page_context"}:
                        raise RuntimeError("Browser closed; action outcome is unknown. Inspect before retrying.")
                    # ブラウザが閉じられた - 再起動してリトライ
                    if attempt < max_retries - 1:
                        print(f"[EXECUTOR_BROWSER] Browser was closed, restarting... (attempt {attempt + 1})")
                        _executor_browser_alive.clear()  # 再起動をトリガー
                        break  # 内側ループを抜けてリトライ
                    else:
                        raise RuntimeError(f"Browser was closed and failed to recover: {result}")
                return result
            except queue.Empty:
                elapsed += wait_timeout
                continue

        # ここに来たらタイムアウト（browser_closedでbreakした場合は除く）
        if elapsed >= total_timeout:
            request["cancelled"].set()
            raise RuntimeError("Executor command timed out")


class ExecutorPageProxy:
    """
    Executor用のPage Proxy

    本物のPlaywright Pageと同じインターフェースを提供するが、
    実際の操作は専用スレッドで実行される。
    """

    def __init__(self):
        _ensure_executor_thread()

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 30000):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("goto", url=url, wait_until=wait_until)
        )

    @property
    def url(self) -> str:
        result = _send_executor_command("get_url")
        return result.get("url", "")

    def locator(self, selector: str):
        return ExecutorLocatorProxy(selector)

    async def wait_for_load_state(self, state: str = "domcontentloaded", timeout: int = None):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("wait_for_load_state", state=state, timeout=timeout)
        )

    async def wait_for_timeout(self, timeout: int):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("wait_for_timeout", timeout=timeout)
        )

    async def screenshot(self, path: str, full_page: bool = True):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("screenshot", path=path, full_page=full_page)
        )

    async def screenshot_base64(self, full_page: bool = False) -> dict:
        """スクリーンショットをbase64で取得（Vision API用）"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("screenshot_base64", full_page=full_page)
        )
        return result  # {"base64": "...", "media_type": "image/png"}

    async def content(self) -> str:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("content")
        )
        return result.get("content", "")

    async def evaluate(self, expression: str, arg=None):
        """JavaScriptを実行"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("evaluate", expression=expression, arg=arg)
        )
        return result.get("result")

    async def get_frames(self) -> list:
        """ページ内の全フレーム（iframe含む）をプロキシとして返す。

        captcha_solver がiframe内のcaptchaを検出・突破するために使う。
        メインフレームも含まれ、先頭がメインフレーム。
        """
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("list_frames")
        )
        return [
            ExecutorFrameProxy(f.get("index", i), f.get("url", ""))
            for i, f in enumerate(result.get("frames", []))
        ]

    async def save_image(self, url: str, path: str):
        """URLから画像をダウンロードしてファイルに保存"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("save_image", url=url, path=path)
        )

    async def upload_file(self, files, ref: str = None, selector: str = None, timeout: int = 20000):
        """ローカルファイルをページのアップロード欄に渡す"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: _send_executor_command(
                "upload_file", files=files, ref=ref, selector=selector, timeout=timeout
            ),
        )

    async def wait_for_selector(self, selector: str, timeout: int = 30000, state: str = "visible"):
        """セレクタが表示されるまで待機"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("wait_for_selector", selector=selector, timeout=timeout, state=state)
        )
        return ExecutorLocatorProxy(selector) if result.get("found") else None

    async def query_selector(self, selector: str):
        """セレクタで要素を取得"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("query_selector", selector=selector)
        )
        return ExecutorLocatorProxy(selector) if result.get("found") else None

    async def query_selector_all(self, selector: str):
        """セレクタで全要素を取得"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("query_selector_all", selector=selector)
        )
        count = result.get("count", 0)
        return [ExecutorLocatorProxy(selector, i) for i in range(count)]

    async def go_back(self):
        """ブラウザの戻るボタン"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("go_back")
        )
        return result

    async def inner_text(self, selector: str) -> str:
        """要素のテキストを取得"""
        result = await self.evaluate(f'document.querySelector("{selector}")?.innerText || ""')
        return result or ""

    async def go_forward(self):
        """ブラウザの進むボタン"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("go_forward")
        )
        return result

    async def reload(self):
        """ページを再読み込み"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("reload")
        )
        return result

    @property
    def keyboard(self):
        return ExecutorKeyboardProxy()

    @property
    def mouse(self):
        return ExecutorMouseProxy()

    # ========================================
    # タブ管理
    # ========================================

    async def switch_to_latest_tab(self) -> dict:
        """
        最新のタブ（新しく開いたタブ）に切り替え

        Returns:
            {"switched": bool, "url": str, "tab_count": int}
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("switch_to_latest_tab")
        )

    async def get_tab_count(self) -> dict:
        """
        開いているタブ数を取得

        Returns:
            {"count": int, "current_url": str}
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("get_tab_count")
        )

    async def close_current_tab(self) -> dict:
        """
        現在のタブを閉じて前のタブに切り替え

        Returns:
            {"closed": bool, "url": str}
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("close_current_tab")
        )

    # ========================================
    # ダン視覚機能（Vision for Dan）
    # ========================================

    async def get_aria_snapshot(self) -> dict:
        """
        ページのアクセシビリティスナップショットを取得

        Returns:
            dict: Playwrightのアクセシビリティツリー
        """
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("aria_snapshot")
        )
        return result.get("snapshot", {})

    async def fill_form(self, fields: list, expected_url: str) -> dict:
        return await asyncio.to_thread(_send_executor_command, "fill_form", fields=fields, expected_url=expected_url)

    async def guarded_click(self, ref: str, timeout: int = 10000) -> dict:
        return await asyncio.to_thread(_send_executor_command, "guarded_click", ref=ref, timeout=timeout)

    async def wait_for_condition(self, condition: dict) -> dict:
        return await asyncio.to_thread(_send_executor_command, "wait_for_condition", condition=condition)

    async def check_condition_before_action(self, condition: dict) -> dict:
        return await asyncio.to_thread(_send_executor_command, "check_condition_before_action", condition=condition)

    async def get_interactive_elements(self) -> list:
        """
        インタラクティブ要素のリストを取得（data-dan-ref属性付き）

        各要素には @e1, @e2 のような参照IDが振られる。
        click_by_ref(), fill_by_ref() でこの参照を使って操作可能。

        Returns:
            list: [{"ref": "@e1", "tag": "button", "role": "button", "text": "カートに入れる", ...}, ...]
        """
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("get_interactive_elements")
        )
        return result.get("elements", [])

    async def click_by_ref(self, ref: str, force: bool = False, timeout: int = 30000):
        """
        data-dan-ref属性でクリック

        Args:
            ref: 参照ID（@e1 形式）
            force: 強制クリック
            timeout: タイムアウト（ミリ秒）
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("click_by_ref", ref=ref, force=force, timeout=timeout)
        )

    async def fill_by_ref(self, ref: str, value: str):
        """
        data-dan-ref属性で入力

        Args:
            ref: 参照ID（@e1 形式）
            value: 入力値
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("fill_by_ref", ref=ref, value=value)
        )

    async def get_page_summary(self) -> dict:
        """
        ページの要約情報を取得

        Returns:
            dict: {"title": "...", "url": "...", "main_text": "..."}
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("get_page_summary")
        )

    async def get_page_context(self) -> dict:
        """
        ページ状態の汎用スナップショット（OpenClaw方式）

        見出し、フィードバックメッセージ、モーダル、ローディング状態、
        バッジ、入力済みフォーム値を収集する。

        Returns:
            dict: {headings, feedback, modal, isLoading, badges, filledInputs}
        """
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("get_page_context")
        )
        return result.get("context", {})

    async def get_page_state(self) -> dict:
        """
        ダンがページ状態を理解するための包括的な情報を取得

        Returns:
            dict: {
                "summary": {"title": "...", "url": "...", "main_text": "..."},
                "interactive_elements": [...],
                "element_count": N
            }
        """
        summary = await self.get_page_summary()
        elements = await self.get_interactive_elements()

        return {
            "summary": summary,
            "interactive_elements": elements[:50],  # 最大50要素
            "element_count": len(elements),
        }


class ExecutorFrameProxy:
    """1つのフレーム（メインドキュメント or iframe）へのProxy。

    Playwright の Frame と同じく `.url` と `evaluate()` を持つので、
    captcha_solver からは実フレームと同じように扱える。
    """

    def __init__(self, index: int, url: str = ""):
        self.index = index
        self.url = url

    async def evaluate(self, expression: str, arg=None):
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: _send_executor_command(
                "frame_evaluate",
                frame_index=self.index,
                frame_url=self.url,
                expression=expression,
                arg=arg,
            ),
        )
        if result.get("error"):
            raise RuntimeError(f"frame_evaluate failed: {result['error']}")
        return result.get("result")


class ExecutorLocatorProxy:
    """Locator Proxy"""

    def __init__(self, selector: str, index: int = None):
        self._selector = selector
        self._index = index  # nth element index (0-based)

    async def count(self) -> int:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("locator_count", selector=self._selector)
        )
        return result.get("count", 0)

    async def fill(self, value: str):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("locator_fill", selector=self._selector, value=value)
        )

    async def click(self, force: bool = False, timeout: int = 30000):
        loop = asyncio.get_event_loop()
        if self._index is not None:
            return await loop.run_in_executor(
                None, lambda: _send_executor_command("locator_click_nth", selector=self._selector, index=self._index, force=force)
            )
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("locator_click", selector=self._selector, force=force)
        )

    async def select_option(self, value: str = None, label: str = None):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("locator_select_option", selector=self._selector, value=value)
        )

    async def all(self):
        """全要素をリストで取得"""
        count = await self.count()
        # 各要素用のLocatorProxyを返す（indexを使用）
        return [ExecutorLocatorProxy(self._selector, index=i) for i in range(count)]

    async def is_visible(self) -> bool:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("locator_is_visible", selector=self._selector, index=self._index)
        )
        return result.get("visible", False)

    async def text_content(self) -> str:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("locator_text_content", selector=self._selector, index=self._index)
        )
        return result.get("text", "")

    async def get_attribute(self, name: str) -> Optional[str]:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("locator_get_attribute", selector=self._selector, name=name, index=self._index)
        )
        return result.get("value")

    async def evaluate(self, expression: str):
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("locator_evaluate", selector=self._selector, expression=expression, index=self._index)
        )
        return result.get("result")

    async def is_enabled(self) -> bool:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("locator_is_enabled", selector=self._selector, index=self._index)
        )
        return result.get("enabled", False)

    @property
    def first(self):
        return ExecutorLocatorProxy(self._selector, index=0)

    def nth(self, index: int):
        """n番目の要素を取得（0-based）"""
        return ExecutorLocatorProxy(self._selector, index=index)


class ExecutorKeyboardProxy:
    """Keyboard Proxy"""

    async def press(self, key: str):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("keyboard_press", key=key)
        )

    async def type(self, text: str, delay: int = 50):
        """テキストを入力（一括）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("keyboard_type", text=text, delay=delay)
        )


class ExecutorMouseProxy:
    """Mouse Proxy for coordinate-based clicks"""

    async def click(self, x: float, y: float):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("mouse_click", x=x, y=y)
        )

    async def move(self, x: float, y: float, steps: int = 1):
        """マウスを指定座標に移動（ホバー用 / ドラッグの経路用）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("mouse_move", x=x, y=y, steps=steps)
        )

    async def down(self):
        """ボタンを押し下げたままにする（ドラッグ開始）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("mouse_down")
        )

    async def up(self):
        """ボタンを離す（ドラッグ終了）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("mouse_up")
        )


async def get_executor_page():
    """Executor用のPage Proxyを返す"""
    return ExecutorPageProxy()


async def close_executor_browser():
    """Executor用ブラウザを閉じる。

    ブラウザは detached 起動なのでワーカーを畳んでも生き残る（それが狙い）。
    このAPIは「本当に閉じる」契約なので、この部屋のプロファイルを使っている
    ブラウザプロセスを明示的に終了させる。
    """
    global _executor_thread
    if _browser_room_id():
        from app.services.browser_lifecycle import request_session
        await asyncio.to_thread(request_session, "close", _browser_room_id())
        _executor_browser_alive.clear()
        return
    _executor_shutdown.set()
    if _executor_thread and _executor_thread.is_alive():
        _executor_thread.join(timeout=10)
    _executor_thread = None

    processes, scan_ok = _list_dedicated_browser_processes()
    if scan_ok and processes:
        terminated = _terminate_dedicated_browser_processes(processes)
        _write_browser_recovery_log("executor_browser_closed", terminated=terminated)


async def close_idle_browsers(idle_seconds: int = 1800) -> list[dict]:
    """Core cleanup respects durable human/auth holds and scheduled watches."""
    from app.services.browser_lifecycle import reap_idle
    try:
        from app.services.followups import held_room_ids
        rooms = await asyncio.to_thread(held_room_ids, strict=True)
        held_profiles = {f"browser_data--{_safe_room_slug(r)}" for r in rooms}
    except Exception:
        # Cannot prove a watch is finished when its DB is unavailable.
        logger.warning("Browser cleanup skipped: watch holds could not be read", exc_info=True)
        return []
    return await asyncio.to_thread(reap_idle, idle_seconds, held_profiles)


def _safe_write_last_use(path: Path, value: float) -> None:
    try:
        path.write_text(str(value), encoding="utf-8")
    except Exception:
        pass


async def _graceful_close_cdp(async_playwright, port: int, wait_seconds: float = 10.0) -> bool:
    """CDP に繋いで正常終了させる。Cookie を書き切らせるのが目的。

    connect_over_cdp の browser.close() は接続を切るだけなので、Chrome 自体へ
    Browser.close を送る。全ページを閉じるだけでは headless/background mode の
    Chrome が残るため、終了は必ずポートが閉じるまで確認する。

    戻り値は「本当に終了したか」。ポートが閉じるまで確認し、閉じなければ False を
    返して呼び出し側の強制終了にフォールバックさせる。
    """
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(
                f"http://127.0.0.1:{port}", timeout=5000
            )
            session = await browser.new_browser_cdp_session()
            try:
                await session.send("Browser.close")
            except Exception:
                # Chrome can disconnect before the command reply is delivered.
                # The port check below decides whether shutdown succeeded.
                pass
            try:
                await browser.close()
            except Exception:
                pass
    except Exception as exc:
        logger.warning("[EXECUTOR_BROWSER] graceful close failed on port %s: %s", port, exc)
        return False

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if not _port_listening(port):
            return True
        await asyncio.sleep(0.5)
    return False


def abort_executor_session():
    """
    実行中のブラウザセッションを中断

    - コマンドキューをクリアして待機中のコマンドを破棄
    - 結果キューもクリア
    - ブラウザ自体は閉じない（次回再利用可能）

    重要: 進行中のPlaywrightコマンドは完了まで待つ必要がある。
    ただし、_send_executor_command内のキャンセルチェックにより、
    次のコマンドは実行されない。
    """
    global _executor_command_queue, _executor_result_queue

    cleared_commands = 0
    cleared_results = 0

    # コマンドキューをクリア
    while not _executor_command_queue.empty():
        try:
            _executor_command_queue.get_nowait()
            cleared_commands += 1
        except queue.Empty:
            break

    # 結果キューもクリア
    while not _executor_result_queue.empty():
        try:
            _executor_result_queue.get_nowait()
            cleared_results += 1
        except queue.Empty:
            break

    logger.info("[EXECUTOR_BROWSER] Session aborted - cleared %d commands, %d results", cleared_commands, cleared_results)
