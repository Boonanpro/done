# -*- coding: utf-8 -*-
"""インスタ巡回用プロファイルに「人が1回だけ」ログインするためのスクリプト。

なぜ手動か:
    自動ログイン(認証情報の自動入力)は Instagram の reCAPTCHA チャレンジに
    誘導されることを実測で確認した(2026-08-07)。captcha を機械で突破すると
    「自動操作」の心証が強まり凍結リスクが上がる。ログインは人が1回やり、
    以降ボットは読むだけ — が最も安全。

使い方:
    python scripts/ig_login_once.py instagram_styleup

    ブラウザが開くので、いつも通り手でログインする(2FAもその場で)。
    ログインが成立したら自動で検知して、プロファイルを保存して終了する。
    以降 instagram_poller はこのプロファイルを読み取り専用で使う。
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.services.instagram_inbox import (  # noqa: E402
    IG_UA,
    fetch_inbox_json,
    profile_dir_for,
)

# 人の作業を待つので長め。Facebook経由やパスワード再設定を挟むと15分では足りない。
WAIT_SECONDS = int(os.getenv("IG_LOGIN_WAIT", "2700"))  # 既定45分


async def main() -> int:
    account = sys.argv[1] if len(sys.argv) > 1 else "instagram_styleup"
    profile = profile_dir_for(account)
    profile.mkdir(parents=True, exist_ok=True)

    print(f"アカウント: {account}")
    print(f"プロファイル: {profile}")
    print("ブラウザを開きます。手でログインしてください（2FAもそのまま進めてOK）。")
    print(f"最大 {WAIT_SECONDS // 60} 分待ちます。ログインを検知したら自動で終了します。\n")

    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--window-position=100,60"],
            viewport={"width": 1280, "height": 900},
            user_agent=IG_UA,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            await page.goto("https://www.instagram.com/accounts/login/",
                            wait_until="domcontentloaded", timeout=60000)
            waited = 0
            while waited < WAIT_SECONDS:
                await asyncio.sleep(5)
                waited += 5
                # ユーザーがタブを開閉しても落ちないよう、生きているページを都度選ぶ
                live = [p for p in ctx.pages if not p.is_closed()]
                if not live:
                    print("\nブラウザが閉じられました。ログインするにはもう一度実行してください。")
                    return 1
                if page.is_closed():
                    page = live[-1]
                try:
                    data = await fetch_inbox_json(page)
                except Exception:
                    data = None
                if data is not None:
                    viewer = (data.get("viewer") or {})
                    print("\nログインを検知しました。")
                    print(f"  アカウント: @{viewer.get('username')} (pk={viewer.get('pk')})")
                    threads = ((data.get("inbox") or {}).get("threads") or [])
                    print(f"  受信箱スレッド数: {len(threads)}")
                    print(f"  未読: {(data.get('inbox') or {}).get('unseen_count')}")
                    print("\nこのプロファイルは保存されました。巡回はここから読み取ります。")
                    return 0
                if waited % 300 == 0:
                    print(f"  待機中... ({waited // 60}分 / {WAIT_SECONDS // 60}分)"
                          " — ブラウザは開いたままにしています")
            print("\nタイムアウト。ログインが確認できませんでした。")
            return 1
        except Exception as exc:
            if "closed" in str(exc).lower():
                print("\nブラウザが閉じられました。ログインするにはもう一度実行してください。")
                return 1
            raise
        finally:
            try:
                await ctx.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
