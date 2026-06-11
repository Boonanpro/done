"""ブラウザ代理ログインでDNSを設定するレジストラドライバの共通基盤。

APIトークンを持たない外部レジストラ（お名前.com / Gandi / Porkbun ...）について、
ユーザーのログイン情報を使ってダンが代理ログインし、DNS/ネームサーバーを設定する。

各レジストラは ``BrowserRegistrarDriver`` を継承し、**実画面で調査した焼き込みセレクタ**で
``login`` / ``set_dns_records`` / ``set_nameservers`` を実装する（CLAUDE.md のセレクタ規律）。
接続フローは ``registrar_key`` でドライバを選ぶだけ＝レジストラ非依存を保つ。

Windows + uvicorn(SelectorEventLoop) では async Playwright の subprocess 起動が不安定なため、
``run_in_proactor_loop`` で専用 ProactorEventLoop のスレッドに逃がして実行する
（salonboard と同じ Windows 対策の方針）。
"""
from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

# 2FAコードを取りに行く非同期コールバック（メールIMAP / SMS転送APK を裏で使う）。
OtpFetcher = Callable[[], Awaitable[Optional[str]]]

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class LoginResult:
    success: bool
    requires_2fa: bool = False
    error: Optional[str] = None
    detail: str = ""


@dataclass
class DnsRecord:
    type: str  # "A" | "CNAME" など
    host: str  # "@" / "www"
    value: str


class BrowserRegistrarDriver:
    """ブラウザ代理ログイン型レジストラドライバの共通インターフェース。"""

    key: str = ""
    label: str = ""
    login_url: str = ""

    async def login(
        self,
        page: Any,
        *,
        login_id: str,
        password: str,
        fetch_otp: Optional[OtpFetcher] = None,
    ) -> LoginResult:
        """代理ログインする。2FA が出たら ``fetch_otp`` でコードを取得して入力する。"""
        raise NotImplementedError

    async def set_dns_records(
        self, page: Any, domain: str, records: list[DnsRecord]
    ) -> None:
        """DNS レコード（A/CNAME 等）を設定する。"""
        raise NotImplementedError

    async def set_nameservers(
        self, page: Any, domain: str, nameservers: list[str]
    ) -> None:
        """ネームサーバーを書き換える（移管式フルオート用）。"""
        raise NotImplementedError


@asynccontextmanager
async def launch_registrar_context(*, headless: bool = True):
    """レジストラ操作用のブラウザコンテキストを起動する（バンドルChromium）。"""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        ctx = await browser.new_context(locale="ja-JP", user_agent=_UA)
        try:
            yield ctx
        finally:
            try:
                await browser.close()
            except Exception:  # noqa: BLE001
                pass


def run_in_proactor_loop(coro_factory: Callable[[], Awaitable[Any]]) -> Any:
    """専用 ProactorEventLoop で coroutine を実行する（Windowsのsubprocess対策）。

    uvicorn の SelectorEventLoop 上から呼ぶ場合は ``await asyncio.to_thread(
    run_in_proactor_loop, factory)`` で別スレッドに逃がして使う。
    ``coro_factory`` は「呼ぶと coroutine を返す」ファクトリ（ループ生成後に生成するため）。
    """
    if sys.platform.startswith("win"):
        loop = asyncio.ProactorEventLoop()  # type: ignore[attr-defined]
    else:
        loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro_factory())
    finally:
        try:
            loop.close()
        finally:
            asyncio.set_event_loop(None)
