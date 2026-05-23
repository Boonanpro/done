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
_VOLUME = {"設定しない": "99", "少ない": "1", "普通": "2", "多い": "3"}
_QUALITY = {"設定しない": "99", "柔らかい": "1", "柔かい": "1", "普通": "2", "硬い": "3"}
_THICK = {"設定しない": "99", "細い": "1", "普通": "2", "太い": "3"}
_CURLY = {"設定しない": "99", "なし": "1", "少し": "2", "強い": "3"}
_FACE = {"設定しない": "99", "丸型": "1", "卵型": "2", "四角": "3",
         "逆三角": "4", "ベース": "5", "面長": "6"}
_AGE = {"設定しない": "99", "キッズ": "0", "10代": "1", "20代": "2",
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
        "volume": _VOLUME.get(_field_value(fields, "hair_amount"), "99"),
        "quality": _QUALITY.get(_field_value(fields, "hair_quality"), "99"),
        "thickness": _THICK.get(_field_value(fields, "hair_thickness"), "99"),
        "curly": _CURLY.get(_field_value(fields, "hair_curl"), "99"),
        "face": _FACE.get(_field_value(fields, "face"), "99"),
        "age": _AGE.get(_field_value(fields, "age"), "99"),
        "hashtags": [str(t).lstrip("#").strip()[:40] for t in tags if str(t).strip()][:8],
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
    for _attempt in range(2):
        try:
            await page.evaluate(
                "() => { try { wnsLoading.show(); } catch (e) {} ; file_upload(); }"
            )
        except Exception:
            pass
        for _ in range(40):
            await page.wait_for_timeout(1000)
            val = await page.evaluate(
                f"() => {{ const e = document.getElementById('{field}'); return e ? e.value : ''; }}"
            )
            if val:
                break
        if val:
            break
        await page.wait_for_timeout(1500)
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
            report("running", "サロンボードにログイン中")
            await ensure_logged_in(
                page,
                creds,
                policy=SalonboardLoginPolicy(max_login_attempts=1),
                handoff_timeout_seconds=handoff_timeout_seconds,
            )
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
            front_ok = False
            for slot in ("FRONT", "SIDE", "BACK"):
                if slot in slots:
                    okimg = await _upload_one_photo(page, slot, slots[slot])
                    if slot == "FRONT":
                        front_ok = okimg
            try:
                await page.check("#agrFlgStyleImgId")
            except Exception:
                pass
            if not front_ok:
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
            return {
                "ok": True,
                "registered": done,
                "style_name": fv["style_name"],
                "message": "サロンボードに登録しました（公開には反映申請が必要です）",
            }
