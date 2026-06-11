"""お名前.com (GMO Internet) の代理ログインドライバ（第一弾）。

セレクタは 2026-06-11 に実画面 https://navi.onamae.com/login を調査して焼き込み
（scripts/recon_onamae_login.py の調査結果）:
  - お名前ID    : input[name="loginId"]
  - パスワード  : input[name="loginPassword"]
  - ログイン    : button[type="submit"]（テキスト「ログイン」）
  - 2FAコード   : input#authCodeInput（ログイン後に表示されることがある）

ログインは本ファイルで実装済み・検証可能。DNS/ネームサーバー設定は設定画面の実DOM調査
（要・テスト口座＋ドメイン）後に実装する。
"""
from __future__ import annotations

from typing import Any, Optional

from app.tools.publish_site.browser_registrars.base import (
    BrowserRegistrarDriver,
    DnsRecord,
    LoginResult,
    OtpFetcher,
)

LOGIN_URL = "https://navi.onamae.com/login"
# ログイン失敗メッセージが出る代表的な箇所（保守的に複数試す）。
_ERROR_SELECTORS = [
    ".error",
    ".errorArea",
    ".p-alert",
    "[class*='error']",
    "[role='alert']",
]


class OnamaeDriver(BrowserRegistrarDriver):
    key = "gmo_onamae"
    label = "お名前.com (GMO Internet)"
    login_url = LOGIN_URL

    async def _submit_login(self, page: Any) -> None:
        """ログイン送信。汎用 button[type=submit]（検索ボタン等）を避け、
        可視の「ログイン」ボタンを優先。無ければパスワード欄で Enter。"""
        candidates = page.locator(
            "button:has-text('ログイン'), input[type=submit][value*='ログイン']"
        )
        try:
            n = await candidates.count()
        except Exception:  # noqa: BLE001
            n = 0
        for i in range(n):
            el = candidates.nth(i)
            try:
                if await el.is_visible():
                    await el.click()
                    return
            except Exception:  # noqa: BLE001
                continue
        # フォールバック: パスワード欄で Enter（フォーム送信）。
        await page.locator('input[name="loginPassword"]').first.press("Enter")

    async def _error_text(self, page: Any) -> str:
        for sel in _ERROR_SELECTORS:
            try:
                loc = page.locator(sel).first
                if await loc.count() and await loc.is_visible():
                    txt = (await loc.inner_text()).strip()
                    if txt:
                        return txt[:200]
            except Exception:  # noqa: BLE001
                continue
        return ""

    async def login(
        self,
        page: Any,
        *,
        login_id: str,
        password: str,
        fetch_otp: Optional[OtpFetcher] = None,
    ) -> LoginResult:
        from playwright.async_api import TimeoutError as PWTimeout

        await page.goto(self.login_url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(1500)

        try:
            await page.locator('input[name="loginId"]').first.fill(login_id, timeout=10000)
            await page.locator('input[name="loginPassword"]').first.fill(password, timeout=10000)
        except PWTimeout:
            return LoginResult(
                success=False, error="form_not_found",
                detail="ログインフォームが見つかりません（ページ構造変更の可能性）",
            )

        await page.wait_for_timeout(300)
        await self._submit_login(page)
        await page.wait_for_timeout(4000)

        # 2FA: authCodeInput が出たら確認コードを取得して入力する。
        auth = page.locator("#authCodeInput")
        try:
            if await auth.is_visible(timeout=3000):
                if fetch_otp is None:
                    return LoginResult(
                        success=False, requires_2fa=True, error="2fa_required",
                        detail="2FAが要求されましたが確認コードの自動取得手段が未設定です",
                    )
                code = await fetch_otp()
                if not code:
                    return LoginResult(
                        success=False, requires_2fa=True, error="otp_unavailable",
                        detail="確認コードを取得できませんでした",
                    )
                await auth.fill(code)
                # 2FA送信もログインボタン特定方式（無ければコード欄でEnter）。
                try:
                    await self._submit_login(page)
                except Exception:  # noqa: BLE001
                    await auth.press("Enter")
                await page.wait_for_timeout(4000)
        except PWTimeout:
            pass  # 2FA欄が出なければ通常ログイン

        # 成功判定: ログインURLから離れていれば成功。
        if "login" not in (page.url or "").lower():
            return LoginResult(success=True, detail=f"logged in: {page.url}")

        err = await self._error_text(page)
        return LoginResult(
            success=False, error="login_failed",
            detail=err or "ログイン後もログイン画面のまま（ID/パスワード誤り or 追加認証）",
        )

    async def set_dns_records(
        self, page: Any, domain: str, records: list[DnsRecord]
    ) -> None:
        raise NotImplementedError(
            "お名前.com の DNS設定画面の実DOM調査が未実施（要・テスト口座＋ドメイン）。"
            "調査後に navi.onamae.com のDNS設定フローを焼き込む。"
        )

    async def set_nameservers(
        self, page: Any, domain: str, nameservers: list[str]
    ) -> None:
        raise NotImplementedError(
            "お名前.com のネームサーバー設定画面の実DOM調査が未実施（要・テスト口座）。"
        )
