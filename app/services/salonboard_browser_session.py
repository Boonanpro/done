"""Playwright session helpers for Salonboard automation.

The key policy is: reuse the persistent browser profile first, and only submit
the login form when Salonboard has clearly redirected us to an unauthenticated
state. CAPTCHA is a human handoff condition, not something to retry through.
"""
from __future__ import annotations

import json
import os
import asyncio
import random
import re
import socket
import subprocess
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

SALONBOARD_USER_DATA_DIR = Path.home() / ".ai_secretary" / "salonboard_data"
SALONBOARD_NORMAL_CHROME_USER_DATA_DIR = (
    Path.home() / ".ai_secretary" / "salonboard_normal_chrome_data"
)
DEFAULT_CHROME_EXE = Path(
    os.environ.get(
        "SALONBOARD_CHROME_EXE",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    )
)
LOGIN_URL = "https://salonboard.com/login/"
CLP_TOP_URL = "https://salonboard.com/CLP/bt/top/"
REFLECT_TOP_URL = "https://salonboard.com/CNB/reflect/reflectTop/"
STYLE_LIST_URL = "https://salonboard.com/CNB/draft/styleList/"


class SalonboardSessionError(RuntimeError):
    """Base error for Salonboard browser session policy failures."""


class SalonboardCaptchaDetected(SalonboardSessionError):
    """Raised when CAPTCHA or similar bot protection is visible."""


class SalonboardHumanHandoffTimeout(SalonboardSessionError):
    """Raised when a human did not complete auth handoff in time."""


class SalonboardRepeatedLoginBlocked(SalonboardSessionError):
    """Raised when code attempts to submit the login form repeatedly."""


class SalonboardProfileLocked(SalonboardSessionError):
    """Raised when another process is using the persistent profile."""


class SalonboardChromeLaunchError(SalonboardSessionError):
    """Raised when regular Chrome cannot be launched or attached over CDP."""


class SalonboardImageUploadError(SalonboardSessionError):
    """Raised when Salonboard rejects or repeatedly fails an image upload."""


@dataclass
class SalonboardLoginPolicy:
    max_login_attempts: int = 1
    login_attempts: int = 0

    def reserve_login_attempt(self) -> None:
        self.login_attempts += 1
        if self.login_attempts > self.max_login_attempts:
            raise SalonboardRepeatedLoginBlocked(
                "Repeated Salonboard login blocked by session policy."
            )


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _connect_over_cdp(
    playwright: Playwright,
    endpoint: str,
    *,
    timeout_seconds: int = 30,
) -> Browser:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return await playwright.chromium.connect_over_cdp(endpoint)
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(0.5)
    raise SalonboardChromeLaunchError(
        f"Could not connect to regular Chrome over CDP: {endpoint}"
    ) from last_error


class BrowserProfileLock:
    """Cooperative lock for a Playwright persistent profile directory."""

    def __init__(self, user_data_dir: Path | str):
        self.user_data_dir = Path(user_data_dir)
        self.lock_path = self.user_data_dir.with_suffix(
            self.user_data_dir.suffix + ".lock"
        )
        self._fd: int | None = None

    def __enter__(self) -> "BrowserProfileLock":
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self._remove_stale_lock_if_needed()
        payload = {
            "pid": os.getpid(),
            "created_at": int(time.time()),
            "user_data_dir": str(self.user_data_dir),
        }
        try:
            self._fd = os.open(
                self.lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            raise SalonboardProfileLocked(
                f"Salonboard profile is already locked: {self.lock_path}"
            ) from exc
        os.write(self._fd, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass

    def _remove_stale_lock_if_needed(self) -> None:
        if not self.lock_path.exists():
            return
        try:
            data = json.loads(self.lock_path.read_text(encoding="utf-8"))
            pid = int(data.get("pid", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return
        if not _pid_is_running(pid):
            self.lock_path.unlink(missing_ok=True)


@asynccontextmanager
async def launch_salonboard_context(
    playwright: Playwright,
    *,
    user_data_dir: Path | str = SALONBOARD_NORMAL_CHROME_USER_DATA_DIR,
    headless: bool = False,
    viewport: dict[str, int] | None = None,
) -> AsyncIterator[BrowserContext]:
    """Launch regular Google Chrome and attach Playwright over CDP.

    Salonboard image upload succeeds in a normal Chrome profile but fails in
    Playwright's bundled/persistent Chromium. Keep the public helper name stable
    so all Salonboard automation goes through this policy module.
    """
    if headless:
        raise SalonboardChromeLaunchError("Salonboard regular Chrome must be headed.")
    chrome_exe = DEFAULT_CHROME_EXE
    if not chrome_exe.exists():
        raise SalonboardChromeLaunchError(f"Chrome executable not found: {chrome_exe}")

    port = _pick_free_port()
    user_data_dir = Path(user_data_dir)
    with BrowserProfileLock(user_data_dir):
        proc = subprocess.Popen(
            [
                str(chrome_exe),
                f"--remote-debugging-port={port}",
                f"--user-data-dir={user_data_dir}",
                "--no-first-run",
                "--new-window",
                CLP_TOP_URL,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        browser: Browser | None = None
        try:
            browser = await _connect_over_cdp(
                playwright,
                f"http://127.0.0.1:{port}",
            )
            context = browser.contexts[0] if browser.contexts else await browser.new_context(
                locale="ja-JP",
                viewport=viewport or {"width": 1280, "height": 1000},
            )
            yield context
        finally:
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()


async def get_or_create_page(context: BrowserContext) -> Page:
    return context.pages[0] if context.pages else await context.new_page()


async def is_captcha_visible(page: Page) -> bool:
    captcha_selectors = [
        'iframe[src*="captcha"]',
        'iframe[src*="recaptcha"]',
        'iframe[src*="hcaptcha"]',
        'iframe[src*="turnstile"]',
        'text="私はロボットではありません"',
        'text="画像認証"',
        'text="認証してください"',
    ]
    for selector in captcha_selectors:
        try:
            if await page.locator(selector).count() > 0:
                return True
        except Exception:
            continue
    return False


async def _is_login_form_visible(page: Page) -> bool:
    try:
        return (
            await page.locator('input[type="text"]').first.is_visible(timeout=1500)
            and await page.locator('input[type="password"]').first.is_visible(
                timeout=1500
            )
        )
    except Exception:
        return False


async def is_logged_in(page: Page) -> bool:
    logged_in_selectors = [
        "#cmsForwardForm",
        "#addStyleForm",
        "#stylistCheckCd",
        'a:has-text("ログアウト")',
    ]
    for selector in logged_in_selectors:
        try:
            if await page.locator(selector).count() > 0:
                return True
        except Exception:
            continue
    if "salonboard.com/CNB/" in page.url and not await _is_login_form_visible(page):
        # CNB の「認証エラー」ページは未ログイン扱い（CMSセッション未確立）。
        try:
            body = await page.locator("body").inner_text(timeout=2000)
        except Exception:
            body = ""
        if "認証エラー" in body or "ログインしなおして" in body:
            return False
        return True
    return False


async def click_salonboard_login_button(page: Page) -> None:
    selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("ログイン")',
        'a:has-text("ログイン")',
        "a.commonBtn",
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector)
            for i in range(await loc.count()):
                el = loc.nth(i)
                if not await el.is_visible():
                    continue
                text = ""
                try:
                    text = (await el.inner_text()).strip()
                except Exception:
                    pass
                if text and ("できない" in text or "採用" in text):
                    continue
                await el.click()
                return
        except Exception:
            continue
    await page.locator('input[type="password"]').first.press("Enter")


async def wait_for_human_auth_completion(
    page: Page,
    *,
    target_url: str = STYLE_LIST_URL,
    timeout_seconds: int = 900,
    poll_seconds: int = 5,
    return_when_login_form_visible: bool = False,
) -> None:
    """Keep the same browser open while a human completes CAPTCHA or 2FA."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        await page.wait_for_timeout(poll_seconds * 1000)
        if await is_logged_in(page):
            return
        if await is_captcha_visible(page):
            continue
        if await _is_login_form_visible(page):
            if return_when_login_form_visible:
                return
            continue
        if "login" not in page.url.lower():
            try:
                await page.goto(
                    target_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
            except Exception:
                continue
            await page.wait_for_timeout(1500)
            if await is_logged_in(page):
                return
    raise SalonboardHumanHandoffTimeout(
        "Human auth handoff did not complete before timeout."
    )


async def login_once(
    page: Page,
    creds: dict[str, str],
    *,
    policy: SalonboardLoginPolicy,
    allow_human_handoff: bool = True,
    handoff_timeout_seconds: int = 900,
) -> None:
    policy.reserve_login_attempt()
    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(1500)
    if await is_captcha_visible(page):
        if not allow_human_handoff:
            raise SalonboardCaptchaDetected("CAPTCHA detected before login.")
        await wait_for_human_auth_completion(
            page,
            timeout_seconds=handoff_timeout_seconds,
            return_when_login_form_visible=True,
        )
        if await is_logged_in(page):
            return

    await page.locator('input[type="text"]').first.fill(creds["login_id"])
    await page.locator('input[type="password"]').first.fill(creds["password"])
    await page.wait_for_timeout(300)
    await click_salonboard_login_button(page)
    await page.wait_for_timeout(6000)

    if await is_captcha_visible(page):
        if not allow_human_handoff:
            raise SalonboardCaptchaDetected("CAPTCHA detected after login.")
        await wait_for_human_auth_completion(
            page,
            timeout_seconds=handoff_timeout_seconds,
        )


async def ensure_logged_in(
    page: Page,
    creds: dict[str, str],
    *,
    policy: SalonboardLoginPolicy | None = None,
    target_url: str = CLP_TOP_URL,
    allow_human_handoff: bool = True,
    handoff_timeout_seconds: int = 900,
) -> str:
    """Reuse the existing session when possible, logging in at most once.

    ログイン判定は CLP TOP（cmsForwardForm が見える認証後ページ）で行う。
    CNB 系 URL を直接叩くと CMS セッション未確立で「認証エラー」になり
    誤判定するため、ログイン後の遷移は open_style_edit_form に委ねる。
    """
    policy = policy or SalonboardLoginPolicy()

    await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(2000)
    if await is_captcha_visible(page):
        if not allow_human_handoff:
            raise SalonboardCaptchaDetected(
                "CAPTCHA detected while checking session."
            )
        await wait_for_human_auth_completion(
            page,
            target_url=target_url,
            timeout_seconds=handoff_timeout_seconds,
        )
        return "human_handoff_completed"
    if await is_logged_in(page):
        return "already_logged_in"

    if not await _is_login_form_visible(page) and "login" not in page.url.lower():
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(1500)

    await login_once(
        page,
        creds,
        policy=policy,
        allow_human_handoff=allow_human_handoff,
        handoff_timeout_seconds=handoff_timeout_seconds,
    )

    await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(2000)
    if await is_captcha_visible(page):
        if not allow_human_handoff:
            raise SalonboardCaptchaDetected("CAPTCHA detected after session check.")
        await wait_for_human_auth_completion(
            page,
            target_url=target_url,
            timeout_seconds=handoff_timeout_seconds,
        )
        return "human_handoff_completed"
    if not await is_logged_in(page):
        raise SalonboardSessionError("Salonboard login did not establish a session.")
    return "logged_in"


async def open_style_edit_form(page: Page) -> bool:
    """Open the new style edit form from an authenticated session.

    掲載管理(CNB)は CLP TOP の cmsForwardForm を POST して
    CMS セッション(KMAGIC)を確立しないと「認証エラー」になる。
    そのため毎回 TOP からハンドオフしてから styleList を開く。
    """
    if "styleEdit" in page.url:
        return True

    # CMS セッション確立: cmsForwardForm は CLP TOP にしか無いので TOP へ行く。
    if await page.locator("#cmsForwardForm").count() == 0:
        await page.goto(CLP_TOP_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(1500)
        if await is_captcha_visible(page):
            raise SalonboardCaptchaDetected("CAPTCHA detected on CLP top.")

    if await page.locator("#cmsForwardForm").count() > 0:
        await page.evaluate(
            """() => {
                const f = document.getElementById('cmsForwardForm');
                f.setAttribute('action', 'https://salonboard.com/CNB/reflect/reflectTop/');
                f.submit();
            }"""
        )
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

    # CMS セッション確立後に styleList を開く。
    await page.goto(STYLE_LIST_URL, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(2000)

    if await is_captcha_visible(page):
        raise SalonboardCaptchaDetected("CAPTCHA detected before opening style form.")
    if await page.locator("#addStyleForm").count() == 0:
        # 認証エラー等で addStyleForm が無い。
        return False

    await page.evaluate("() => document.getElementById('addStyleForm').submit()")
    await page.wait_for_load_state("domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)
    return "styleEdit" in page.url


async def open_reflect_top(page: Page) -> bool:
    """Open CNB reflect top through the CLP KMAGIC handoff."""
    if await page.locator("#cmsForwardForm").count() == 0:
        await page.goto(CLP_TOP_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(1500)
        if await is_captcha_visible(page):
            raise SalonboardCaptchaDetected("CAPTCHA detected on CLP top.")

    if await page.locator("#cmsForwardForm").count() > 0:
        await page.evaluate(
            """() => {
                const f = document.getElementById('cmsForwardForm');
                f.setAttribute('action', 'https://salonboard.com/CNB/reflect/reflectTop/');
                f.submit();
            }"""
        )
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

    if "reflectTop" not in page.url:
        await page.goto(REFLECT_TOP_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2000)

    return "reflectTop" in page.url or "reflect" in page.url.lower()


async def _style_reflect_rows(page: Page) -> list[str]:
    return await page.eval_on_selector_all(
        "table tr",
        """trs => trs
            .map(t => (t.innerText || '').replace(/\\s+/g, ' ').trim())
            .filter(Boolean)""",
    )


async def _extract_style_id(page: Page) -> str | None:
    try:
        html = await page.content()
    except Exception:
        return None
    match = re.search(r"\bL\d{9,}\b", html)
    return match.group(0) if match else None


async def _find_registered_style(page: Page, style_name: str) -> dict | None:
    """Find a registered style by title in the draft style list."""
    title = (style_name or "").strip()
    if not title:
        return None
    await open_reflect_top(page)
    await page.goto(STYLE_LIST_URL, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(1500)
    for page_no in range(1, 90):
        rows = await page.evaluate(
            """
            (pageNo) => {
              const trs = [...document.querySelectorAll('tr')];
              const out = [];
              for (let i = 0; i < trs.length; i++) {
                const tr = trs[i];
                const html = tr.innerHTML || '';
                const ids = [...html.matchAll(/L\\d{9}/g)].map(m => m[0]);
                if (!ids.length) continue;
                const styleId = [...new Set(ids)][0];
                const update = ([...html.matchAll(/20\\d{15}/g)].map(m => m[0])[0]) || '';
                const rowTitle = (tr.innerText || '').replace(/\\s+/g, ' ').replace(/^No\\.\\s*/, '').trim();
                const next = trs[i + 1];
                const cells = next ? [...next.querySelectorAll('td,th')].map(td => (td.innerText || '').replace(/\\s+/g, ' ').trim()) : [];
                out.push({ page: pageNo, styleId, update, title: rowTitle, check: cells[2] || '' });
              }
              return out;
            }
            """,
            page_no,
        )
        matches = [r for r in rows if r.get("title") == title or title in r.get("title", "")]
        if matches:
            matches.sort(key=lambda r: r.get("update", ""), reverse=True)
            return matches[0]
        next_link = page.locator("a", has_text="次へ")
        if await next_link.count() == 0:
            return None
        await next_link.first.click()
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(300)
    return None


async def _apply_reflect_request(page: Page) -> dict:
    """Submit the style reflect request so the registered style becomes public."""
    if not await open_reflect_top(page):
        return {"ok": False, "message": "反映申請画面を開けませんでした"}

    rows = await _style_reflect_rows(page)
    ng_rows = [row for row in rows if "NG" in row]
    if ng_rows:
        return {
            "ok": False,
            "message": "掲載チェックNGのスタイルがあるため、反映申請できません",
            "ng_rows": ng_rows[:5],
        }

    btn = page.locator("#reflectedButton")
    if await btn.count() == 0:
        return {"ok": False, "message": "反映申請ボタンが見つかりませんでした"}
    try:
        cls = await btn.first.get_attribute("class") or ""
        if "disabled" in cls or not await btn.first.is_enabled():
            return {"ok": False, "message": "反映申請ボタンが押せない状態です"}
    except Exception:
        pass

    page.on("dialog", lambda d: asyncio.create_task(d.accept()))
    try:
        await btn.first.click(force=True, timeout=8000, no_wait_after=True)
    except PlaywrightTimeoutError as exc:
        # Salonboard's reflect button can submit through legacy JS without a
        # clean navigation signal. Treat the click as best-effort and verify
        # the resulting page state below instead of failing immediately.
        if "click action done" not in str(exc):
            raise
    await page.wait_for_timeout(5000)

    confirm = page.locator(
        'button:has-text("反映する"), a:has-text("反映する"), input[value*="反映する"], '
        'button:has-text("申請する"), a:has-text("申請する"), input[value*="申請"], '
        'button:has-text("実行"), input[value*="実行"], button:has-text("OK"), a:has-text("はい")'
    )
    for i in range(await confirm.count()):
        try:
            if await confirm.nth(i).is_visible():
                await confirm.nth(i).click(force=True, timeout=6000)
                break
        except Exception:
            continue

    await page.wait_for_timeout(6000)
    try:
        body = await page.locator("body").inner_text()
    except Exception:
        body = ""
    success_tokens = (
        "反映済",
        "反映済み",
        "反映されました",
        "反映申請予約",
        "反映申請を予約",
        "申請予約",
        "申請しました",
        "予約しました",
        "受け付けました",
        "完了しました",
    )
    if any(token in body for token in success_tokens):
        return {"ok": True, "message": "サロンボードに登録し、反映申請まで完了しました"}

    rows_after = await _style_reflect_rows(page)
    style_rows = [row for row in rows_after if "スタイル掲載情報" in row]
    if any(any(token in row for token in success_tokens) for row in style_rows):
        return {"ok": True, "message": "サロンボードに登録し、反映申請まで完了しました"}

    return {"ok": False, "message": "反映申請後の完了状態を確認できませんでした"}


# =====================================================================
# スタイル投稿（項目入力 → 写真アップロード → 登録）
# AI解析結果(fields)をサロンボードのフォーム値に変換して入力する。
# 写真アップロードの確定(doUpload)は本物Chromeでのみ通る（Akamai対策）。
# =====================================================================

_CATEGORY_MAP = {"レディース": "SG01", "メンズ": "SG02"}
_LADIES_LEN = {"ベリーショート": "HL05", "ショート": "HL04", "ボブ": "HL04",
               "ミディアム": "HL03", "セミロング": "HL02", "ロング": "HL01"}
_MENS_LEN = {"ベリーショート": "HL10", "ショート": "HL11", "ボブ": "HL11",
             "ミディアム": "HL12", "セミロング": "HL12", "ロング": "HL13"}
_MENU_MAP = {"パーマ": "MC01", "ストレートパーマ・縮毛矯正": "MC02",
             "エクステ": "MC03", "ブリーチ": "MC04"}
_VOLUME = {"設定しない": "2", "少ない": "1", "普通": "2", "多い": "3"}
_QUALITY = {"設定しない": "2", "柔らかい": "1", "柔かい": "1", "普通": "2", "硬い": "3"}
_THICK = {"設定しない": "2", "細い": "1", "普通": "2", "太い": "3"}
_CURLY = {"設定しない": "1", "なし": "1", "少し": "2", "強い": "3"}
_FACE = {"設定しない": "2", "丸型": "1", "卵型": "2", "四角": "3",
         "逆三角": "4", "ベース": "5", "面長": "6"}
_AGE = {"設定しない": "2", "キッズ": "0", "10代": "1", "20代": "2",
        "30代": "3", "40代": "4", "50代": "5", "60代以上": "6"}
_ANGLE_SLOT = {"front": "FRONT", "side": "SIDE", "back": "BACK"}
_SLOT_CLASS = {"FRONT": "SV01", "SIDE": "SV02", "BACK": "SV03"}
_SLOT_SELECT = {"FRONT": "styleClassCd01", "SIDE": "styleClassCd02", "BACK": "styleClassCd03"}


def _field_value(fields: dict, key: str) -> Any:
    """analyze の {value:..} 構造でも素の値でも取り出す。"""
    x = fields.get(key)
    if isinstance(x, dict) and "value" in x:
        return x["value"]
    return x


def build_form_values(fields: dict) -> dict:
    """AI解析結果 → サロンボード投稿フォーム値。"""
    cat = _field_value(fields, "category")
    length = _field_value(fields, "length")
    is_ladies = cat != "メンズ"
    menu_labels = _field_value(fields, "menu") or []
    if not isinstance(menu_labels, list):
        menu_labels = []
    menu_text = (_field_value(fields, "menu_text") or "").strip()
    if not menu_text:
        # メニュー内容は必須。空ならメニュー4択 or 既定値から組み立てる。
        parts = ["カット"] + [m for m in menu_labels]
        menu_text = "＋".join(dict.fromkeys(parts)) if parts else "カット"
    tags = _field_value(fields, "hashtags") or []
    if not isinstance(tags, list):
        tags = []
    return {
        "category": _CATEGORY_MAP.get(cat, "SG01"),
        "is_ladies": is_ladies,
        "length": (_LADIES_LEN if is_ladies else _MENS_LEN).get(length, ""),
        "style_name": (_field_value(fields, "style_name") or "").strip(),
        "comment": (_field_value(fields, "comment") or "").strip(),
        "menu_text": menu_text[:1000],
        "menu_codes": [_MENU_MAP[m] for m in menu_labels if m in _MENU_MAP],
        "volume": _VOLUME.get(_field_value(fields, "hair_amount"), "2"),
        "quality": _QUALITY.get(_field_value(fields, "hair_quality"), "2"),
        "thickness": _THICK.get(_field_value(fields, "hair_thickness"), "2"),
        "curly": _CURLY.get(_field_value(fields, "hair_curl"), "1"),
        "face": _FACE.get(_field_value(fields, "face"), "2"),
        "age": _AGE.get(_field_value(fields, "age"), "2"),
        "hashtags": [str(t).lstrip("#").strip()[:40] for t in tags if str(t).strip()][:10],
    }


def assign_photo_slots(photo_paths: list[str], images_meta: list[dict] | None) -> dict:
    """写真をFRONT/SIDE/BACKスロットへ割り当てる（AI角度判定を優先）。"""
    images_meta = images_meta or []
    assign: dict[str, str] = {}
    for i, path in enumerate(photo_paths):
        meta = images_meta[i] if i < len(images_meta) else {}
        angle = (meta or {}).get("angle", "front")
        slot = _ANGLE_SLOT.get(angle, "FRONT")
        if slot in assign:
            for s in ("FRONT", "SIDE", "BACK"):
                if s not in assign:
                    slot = s
                    break
        assign[slot] = path
    if "FRONT" not in assign and photo_paths:
        assign["FRONT"] = photo_paths[0]
    return assign


async def _upload_one_photo(page: Page, slot: str, img_path: str) -> bool:
    """1スロット分の写真をアップロード。本物Chromeで doUpload が通る。"""
    field = f"{slot}_IMG_ID"
    basename = Path(img_path).name
    # 前スロットのモーダル/保持ファイルをクリア
    for sel in (".imageUploaderModalTopCloseButton", ".imageUploaderModalBottomCloseButton"):
        try:
            loc = page.locator(sel)
            for i in range(await loc.count()):
                if await loc.nth(i).is_visible():
                    await loc.nth(i).click()
                    await page.wait_for_timeout(700)
                    break
        except Exception:
            continue
    await page.evaluate("() => { try { window.waitImgeFile = null; } catch (e) {} }")
    await page.dispatch_event(f"#{field}_PC_NEW_NO_PHOTO", "click")
    await page.wait_for_selector("#formFile", state="attached", timeout=15000)
    await page.wait_for_timeout(1500)
    await page.set_input_files("#formFile", img_path)
    # 写真が画面内に保持される(prepareFileInfo実行)まで待つ
    staged = False
    for _ in range(12):
        await page.wait_for_timeout(700)
        if await page.evaluate(
            "(n) => !!(window.waitImgeFile) && window.waitImgeFile.name === n", basename
        ):
            staged = True
            break
    if not staged:
        return False
    try:
        await page.wait_for_selector(".jscImageUploaderModalThumbnail", state="visible", timeout=10000)
    except Exception:
        pass
    await page.wait_for_timeout(2500)
    # 確定: グローバル file_upload() → doUpload。*_IMG_ID が入るまで待つ。
    val = ""
    transient_error = ""
    for attempt in range(4):
        try:
            await page.evaluate(
                "() => { try { wnsLoading.show(); } catch (e) {} ; file_upload(); }"
            )
        except Exception:
            pass
        for _ in range(50):
            await page.wait_for_timeout(1000)
            val = await page.evaluate(
                f"() => {{ const e = document.getElementById('{field}'); return e ? e.value : ''; }}"
            )
            if val:
                break
            try:
                text = await page.locator("body").inner_text(timeout=1500)
            except Exception:
                text = ""
            if "横長" in text:
                raise SalonboardImageUploadError(
                    "横長の画像はサロンボードにアップロードできません。縦長の画像に差し替えてください。"
                )
            if (
                "アクセスが集中" in text
                or "通信に失敗" in text
                or "しばらくしてから" in text
            ):
                transient_error = "画像アップロード機能が一時的に制限されています"
                break
        if val:
            break
        await page.wait_for_timeout(8000 * (attempt + 1))
    if not val and transient_error:
        raise SalonboardImageUploadError(
            f"{transient_error}。少し時間を置いてから再投稿してください。"
        )
    try:
        await page.select_option(
            f'select[name="frmStyleEditStyleInfoDto.{_SLOT_SELECT[slot]}"]',
            value=_SLOT_CLASS[slot],
        )
    except Exception:
        pass
    await page.wait_for_timeout(800)
    return bool(val)


async def _fill_style_form(page: Page, stylist_name: str, fv: dict) -> None:
    """スタイル投稿フォームの各項目を入力する。"""
    await page.select_option("#stylistCheckCd", label=stylist_name)
    await page.fill("#stylistCommentTxt", fv["comment"])
    await page.fill("#styleNameTxt", fv["style_name"])
    await page.check(
        f'input[name="frmStyleEditStyleDto.styleCategoryCd"][value="{fv["category"]}"]'
    )
    await page.wait_for_timeout(600)
    len_sel = "#ladiesHairLengthCd" if fv["is_ladies"] else "#mensHairLengthCd"
    if fv["length"]:
        try:
            await page.select_option(len_sel, value=fv["length"])
        except Exception:
            pass
    # メニュー内容(必須): テキスト + 該当する4択
    try:
        await page.fill("#menuDetailTxt", fv["menu_text"])
    except Exception:
        pass
    for mc in fv["menu_codes"]:
        try:
            await page.check(
                f'input[name="frmStyleEditStyleDto.menuContentsCdList"][value="{mc}"]'
            )
        except Exception:
            pass
    # 任意: モデル属性
    for name, val in [
        ("modelHairVolumeKbn", fv["volume"]), ("modelHairTypeKbn", fv["quality"]),
        ("modelHairThicknessKbn", fv["thickness"]), ("modelHairCurlyKbn", fv["curly"]),
        ("modelFaceTypeKbn", fv["face"]), ("modelAgeKbn", fv["age"]),
    ]:
        try:
            await page.check(
                f'input[name="frmStyleEditStyleModelDto.{name}"][value="{val}"]'
            )
        except Exception:
            pass
    # ハッシュタグ（hashTagTxt + 追加ボタン）ベストエフォート
    for tag in fv["hashtags"]:
        try:
            await page.fill("#hashTagTxt", tag)
            await page.wait_for_timeout(300)
            btn = page.locator(
                'button:has-text("ハッシュタグを追加"), a:has-text("ハッシュタグを追加")'
            )
            if await btn.count() > 0:
                await btn.first.click(force=True, timeout=4000)
                await page.wait_for_timeout(400)
        except Exception:
            break


async def _click_register(page: Page) -> None:
    btn = page.locator('a[onclick^="doRegister"]')
    for i in range(await btn.count()):
        if await btn.nth(i).is_visible():
            await btn.nth(i).click(force=True)
            return
    await page.evaluate("() => doRegister(new Event('click'))")


async def run_style_post(
    *,
    device_id: str,
    photo_paths: list[str],
    fields: dict,
    images_meta: list[dict] | None = None,
    stylist_name: str | None = None,
    status_cb: Callable[[str, str], None] | None = None,
    handoff_timeout_seconds: int = 900,
) -> dict:
    """スタイルアップ投稿のエンドツーエンド実行（本物Chrome/CDP）。
    ログイン状態を再利用し、フォーム入力→写真アップロード→登録まで行う。
    公開(反映申請)は美容師が任意で行うため、ここでは登録(下書き保存)までとする。
    返り値: {ok, style_name, message}
    """
    from app.services.salonboard_credentials_service import SalonboardCredentialsService

    def report(status: str, message: str) -> None:
        if status_cb:
            try:
                status_cb(status, message)
            except Exception:
                pass

    creds = await SalonboardCredentialsService().get_decrypted_for_posting(device_id)
    if not creds:
        return {"ok": False, "message": "ログイン情報が登録されていません"}
    stylist = stylist_name or creds.get("stylist_name") or ""
    fv = build_form_values(fields)
    slots = assign_photo_slots(photo_paths, images_meta)

    async with async_playwright() as p:
        async with launch_salonboard_context(p) as ctx:
            page = await get_or_create_page(ctx)
            report("running", "ログイン済みセッションを確認しています")
            login_status = await ensure_logged_in(
                page,
                creds,
                policy=SalonboardLoginPolicy(max_login_attempts=1),
                handoff_timeout_seconds=handoff_timeout_seconds,
            )
            if login_status == "already_logged_in":
                report("running", "ログイン済みセッションを再利用しています")
            elif login_status == "logged_in":
                report("running", "ログインしました")
            else:
                report("running", "認証状態を確認しました")
            report("running", "投稿フォームを開いています")
            try:
                ok = await open_style_edit_form(page)
            except SalonboardCaptchaDetected:
                report("needs_human", "画像認証が出ました。開いたChromeで解いてください")
                await wait_for_human_auth_completion(page, timeout_seconds=handoff_timeout_seconds)
                ok = await open_style_edit_form(page)
            if not ok:
                return {"ok": False, "message": "投稿フォームを開けませんでした"}

            report("running", "項目を入力しています")
            await _fill_style_form(page, stylist, fv)

            report("running", "写真をアップロードしています")
            uploaded_slots: list[str] = []
            for slot in ("FRONT", "SIDE", "BACK"):
                if slot in slots:
                    okimg = await _upload_one_photo(page, slot, slots[slot])
                    if okimg:
                        uploaded_slots.append(slot)
            try:
                await page.check("#agrFlgStyleImgId")
            except Exception:
                pass
            missing_slots = [slot for slot in slots if slot not in uploaded_slots]
            if missing_slots:
                return {"ok": False, "message": "写真のアップロードに失敗しました"}

            report("running", "登録しています")
            await _click_register(page)
            await page.wait_for_timeout(7000)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=20000)
            except Exception:
                pass
            await page.wait_for_timeout(2000)
            body = ""
            try:
                body = await page.locator("body").inner_text()
            except Exception:
                pass
            done = ("登録が完了" in body) or ("登録しました" in body) or ("完了しました" in body)
            style_id = await _extract_style_id(page)
            if not done:
                registered = await _find_registered_style(page, fv["style_name"])
                if registered:
                    done = True
                    style_id = registered.get("styleId") or style_id
                else:
                    return {
                        "ok": False,
                        "registered": False,
                        "style_name": fv["style_name"],
                        "style_id": style_id,
                        "message": "サロンボード登録の完了を確認できませんでした",
                    }

            report("running", "公開反映を申請しています")
            reflect = await _apply_reflect_request(page)
            if not reflect.get("ok"):
                return {
                    "ok": False,
                    "registered": True,
                    "published": False,
                    "style_name": fv["style_name"],
                    "style_id": style_id,
                    "message": reflect.get("message", "反映申請に失敗しました"),
                }
            return {
                "ok": True,
                "registered": done,
                "published": True,
                "style_name": fv["style_name"],
                "style_id": style_id,
                "message": reflect.get("message", "サロンボードに登録し、反映申請まで完了しました"),
            }
