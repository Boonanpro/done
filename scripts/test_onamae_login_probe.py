"""お名前.com ドライバのログイン機構を実サイトで部分検証する（口座不要）。

ダミー認証情報でログインを試み、フォーム到達→入力→送信→失敗検出までの
「機構」が動くことを確認する（成功パス/2FA/DNS設定は実口座が要るので対象外）。
期待結果: success=False, error in {login_failed, form_not_found, 2fa_required}。

usage: python scripts/test_onamae_login_probe.py
"""
from __future__ import annotations

import asyncio

from app.tools.publish_site.browser_registrars import (
    get_browser_driver,
    launch_registrar_context,
)


async def main() -> int:
    driver = get_browser_driver("gmo_onamae")
    assert driver is not None, "driver factory returned None"
    print(f"driver: {driver.label} ({driver.key})")

    async with launch_registrar_context(headless=True) as ctx:
        page = await ctx.new_page()
        result = await driver.login(
            page,
            login_id="00000000",  # ダミー（実在しないお名前ID）
            password="dummy-wrong-password-xyz",
            fetch_otp=None,
        )
        print("final url :", page.url)
        print("result    :", result)

    ok = (not result.success) and result.error in {
        "login_failed", "form_not_found", "2fa_required", "otp_unavailable",
    }
    print("\nMECHANICS OK" if ok else "\nUNEXPECTED RESULT")
    print("（フォーム到達→入力→送信→失敗検出までの機構が動作）" if ok else "")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
