"""
EX予約 予約購入処理

最終更新: 2026/01/12
確認画面から購入を実行し、完了画面まで到達
"""

import re
from typing import Optional
from dataclasses import dataclass
from datetime import datetime
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from app.executors.ex_reservation.selectors_complete import (
    CONFIRMATION,
    PURCHASE_COMPLETE,
)


@dataclass
class PurchaseResult:
    """購入結果"""
    success: bool
    message: str
    reservation_number: Optional[str] = None
    screenshot_path: Optional[str] = None


async def handle_3d_secure(page: Page, otp_callback=None, max_wait_seconds: int = 300) -> bool:
    """
    3Dセキュア認証を処理

    Args:
        page: Playwrightページ
        otp_callback: OTP取得コールバック関数（async関数、OTPコードを返す）
        max_wait_seconds: 最大待機時間（秒）

    Returns:
        True: 認証完了, False: 失敗
    """
    try:
        print("[3D_SECURE] 3Dセキュア認証を検出...")

        # 3Dセキュア画面の検出（SafeKey、その他の3DSプロバイダー）
        current_url = page.url

        # 3DS画面判定
        is_3ds = any(keyword in current_url.lower() for keyword in [
            "safekey", "3dsecure", "authentication", "paysec", "auth-api"
        ])

        if is_3ds:
            print(f"  3Dセキュア認証画面: {current_url}")

            # スクリーンショット
            screenshot_3ds = f"ex_3dsecure_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            await page.screenshot(path=screenshot_3ds)
            print(f"  スクリーンショット: {screenshot_3ds}")

            # OTP入力フィールドを探す（SafeKeyは動的にロードされるため待機）
            otp_input_selector = 'input[type="text"], input[type="tel"], input[type="password"], input[name*="otp"], input[name*="code"], input[id*="otp"], input[id*="code"]'
            otp_inputs = []

            # まず即座にチェック
            otp_inputs = await page.locator(otp_input_selector).all()

            # 見つからない場合、最大60秒待機（SafeKeyはSMS送信後に入力フィールドが表示される）
            if not otp_inputs:
                print("  [WAIT] OTP入力フィールドが動的にロードされるのを待機中...")
                try:
                    await page.wait_for_selector(otp_input_selector, timeout=60000, state="visible")
                    print("  [OK] OTP入力フィールドが表示されました")
                    otp_inputs = await page.locator(otp_input_selector).all()
                except PlaywrightTimeout:
                    print("  [TIMEOUT] 60秒経過してもOTP入力フィールドが表示されませんでした")
                    otp_inputs = []

            if otp_inputs and otp_callback:
                print(f"  [OTP_INPUT] OTP入力フィールドが見つかりました（{len(otp_inputs)}個）")

                # コールバックでOTPを取得
                print("  OTPコードの入力を待っています...")
                try:
                    otp_code = await otp_callback()
                    if otp_code:
                        print(f"  OTPコード受信: {otp_code[:3]}*** (長さ: {len(otp_code)})")
                    else:
                        print("  [ERROR] OTPコードが取得できませんでした（タイムアウト）")
                        return False
                except Exception as e:
                    print(f"  [ERROR] OTP取得エラー: {e}")
                    return False

                # OTP入力
                if otp_code:
                    # 最初の入力フィールドに入力
                    await otp_inputs[0].fill(otp_code)
                    await page.wait_for_timeout(500)
                    print("  [OK] OTPコードを入力しました")

                    # 送信ボタンを探す
                    submit_buttons = await page.locator('button[type="submit"], input[type="submit"], button:has-text("送信"), button:has-text("Submit"), button:has-text("確認"), button:has-text("Confirm")').all()

                    if submit_buttons:
                        print(f"  送信ボタンをクリック中...（{len(submit_buttons)}個見つかりました）")
                        await submit_buttons[0].click()
                        await page.wait_for_timeout(2000)
                    else:
                        # Enterキーで送信
                        print("  送信ボタンが見つからないため、Enterキーで送信...")
                        await otp_inputs[0].press("Enter")
                        await page.wait_for_timeout(2000)

                    # 認証完了を待つ
                    print("  認証処理を待機中...")
                    for i in range(60):
                        await page.wait_for_timeout(1000)
                        current_url = page.url

                        # EX予約サイトに戻った場合
                        if "shinkansen2.jr-central.co.jp" in current_url:
                            print(f"\n  [OK] 認証完了！EX予約サイトに戻りました（{i + 1}秒）")
                            return True

                        if (i + 1) % 10 == 0:
                            print(f"    認証待機中... {i + 1}/60秒")

                    print("\n  [ERROR] 認証完了のタイムアウト")
                    return False

            elif otp_inputs and not otp_callback:
                print(f"  [MANUAL] OTP入力フィールドが見つかりました（{len(otp_inputs)}個）")
                print("  コールバック関数が指定されていないため、手動入力または自動承認を待機します...")

                # 認証完了またはタイムアウトまで待機
                print(f"  最大{max_wait_seconds}秒待機...")

                for i in range(max_wait_seconds):
                    await page.wait_for_timeout(1000)
                    current_url = page.url

                    # EX予約サイトに戻った場合
                    if "shinkansen2.jr-central.co.jp" in current_url:
                        print(f"\n  [OK] 認証完了！EX予約サイトに戻りました")
                        return True

                    # 10秒ごとに進捗表示
                    if (i + 1) % 10 == 0:
                        print(f"    待機中... {i + 1}/{max_wait_seconds}秒")

                print(f"\n  [TIMEOUT] {max_wait_seconds}秒経過しましたが認証が完了しませんでした")
                return False

            else:
                # 入力フィールドがない場合（アプリ承認など）
                print("  [AUTO] アプリまたは自動承認を待機...")

                # 認証完了を待つ
                for i in range(max_wait_seconds):
                    await page.wait_for_timeout(1000)
                    current_url = page.url

                    if "shinkansen2.jr-central.co.jp" in current_url:
                        print(f"\n  [OK] 認証完了！EX予約サイトに戻りました（{i + 1}秒）")
                        return True

                    if (i + 1) % 10 == 0:
                        print(f"    自動承認待機中... {i + 1}/{max_wait_seconds}秒")

                print(f"\n  [TIMEOUT] {max_wait_seconds}秒経過しましたが認証が完了しませんでした")
                return False

        return True

    except Exception as e:
        print(f"[3D_SECURE] エラー: {e}")
        return False


async def execute_purchase(page: Page, confirm: bool = True, handle_3ds: bool = True, otp_callback=None) -> PurchaseResult:
    """
    確認画面から予約を購入

    Args:
        page: Playwrightページ（確認画面に遷移済み）
        confirm: 実際に購入を実行するか（Falseの場合は確認のみ）
        handle_3ds: 3Dセキュア認証を処理するか
        otp_callback: 3Dセキュア用OTP取得コールバック関数（async関数）

    Returns:
        PurchaseResult: 購入結果
    """
    try:
        # 3DS認証成功フラグ（wait_for_selectorの結果を保持）
        _3ds_complete_success = False

        # 確認画面にいるか確認
        heading = page.locator(CONFIRMATION["not_complete_heading"])
        if await heading.count() == 0:
            return PurchaseResult(
                success=False,
                message="確認画面が表示されていません",
            )

        print("[OK] 確認画面にいます")

        # スクリーンショット（購入前）
        screenshot_before = f"ex_before_purchase_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        await page.screenshot(path=screenshot_before)
        print(f"  購入前スクリーンショット: {screenshot_before}")

        if not confirm:
            return PurchaseResult(
                success=True,
                message="購入確認のみ（実際の購入は実行していません）",
                screenshot_path=screenshot_before,
            )

        # 購入ボタンをクリック
        print("\n[購入実行] 予約する（購入）ボタンをクリック...")
        purchase_btn = page.locator(CONFIRMATION["purchase_button"])

        if await purchase_btn.count() == 0:
            return PurchaseResult(
                success=False,
                message="購入ボタンが見つかりません",
                screenshot_path=screenshot_before,
            )

        # JavaScriptで直接onclickイベントを発火
        # ボタンがdisabledでも実行できる
        await page.evaluate("""
            () => {
                const button = document.getElementById('sb-1');
                if (button && button.onclick) {
                    button.onclick.call(button);
                }
            }
        """)
        print("  購入ボタンをクリックしました（JavaScript実行）")

        # ページ遷移を待つ
        # 3Dセキュア認証画面に遷移する場合もあるため、長めに待つ
        print("  ページ遷移を待機中...")
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # 3Dセキュア認証が必要な場合
        if handle_3ds:
            current_url = page.url
            # 3Dセキュア認証画面のURLパターン
            is_3ds = any(keyword in current_url.lower() for keyword in [
                "safekey", "3dsecure", "authentication", "paysec", "auth-api"
            ])
            # EX予約サイト以外のドメインも3DS画面として扱う
            is_external = "shinkansen2.jr-central.co.jp" not in current_url.lower()

            if is_3ds or is_external:
                print("\n[3DS] 3Dセキュア認証画面に遷移しました")

                if not await handle_3d_secure(page, otp_callback=otp_callback, max_wait_seconds=300):
                    return PurchaseResult(
                        success=False,
                        message="3Dセキュア認証がタイムアウトしました",
                    )

                # 認証完了後、完了画面の表示を待つ（最大30秒）
                print("  購入処理完了を待機中...")
                try:
                    await page.wait_for_selector(
                        PURCHASE_COMPLETE["complete_heading"],
                        timeout=30000,
                        state="visible"
                    )
                    print("  [OK] 完了画面が表示されました（3DS認証後）")
                    # wait_for_selectorが成功したら、完了画面到達済みとしてフラグを立てる
                    _3ds_complete_success = True
                except PlaywrightTimeout:
                    print("  [WARN] 完了画面の表示がタイムアウトしました")
                    _3ds_complete_success = False

        # 完了画面に到達したか確認
        # 複数のパターンでチェック（句点の有無、部分一致など）
        complete_selectors = [
            PURCHASE_COMPLETE["complete_heading"],  # text="予約が完了しました"
            'text=/予約が完了/',  # 部分一致
            ':has-text("予約が完了しました")',  # 含む
            '.complete-message, .success-message',  # クラス名
        ]

        complete_found = False
        for selector in complete_selectors:
            try:
                elem = page.locator(selector)
                if await elem.count() > 0:
                    complete_found = True
                    print(f"  [OK] 完了画面検出（セレクタ: {selector[:30]}...）")
                    break
            except Exception:
                continue

        # 3DS認証後にwait_for_selectorが成功していた場合も完了とみなす
        if handle_3ds and _3ds_complete_success:
            complete_found = True
            print("  [OK] 3DS認証後の完了を信頼")

        if complete_found:
            print("\n[OK] 予約が完了しました！")

            # 予約番号を取得（お預かり番号も対象）
            reservation_number = None

            # まず「お預かり番号」を探す
            reference_elem = page.locator('text=/お預かり番号/')
            if await reference_elem.count() > 0:
                # お預かり番号が見つかった場合、次の要素から番号を取得
                # スクリーンショット上では大きなフォントで番号が表示されている
                number_elem = page.locator('.azukaribango, .number, h2, h3').filter(has_text=re.compile(r'^\d+$'))
                if await number_elem.count() > 0:
                    reservation_number = await number_elem.first.text_content()
                    reservation_number = reservation_number.strip()
                    print(f"  お預かり番号: {reservation_number}")

            # 見つからなければ「予約番号」を探す
            if not reservation_number:
                reservation_elem = page.locator(PURCHASE_COMPLETE["reservation_number"])
                if await reservation_elem.count() > 0:
                    text = await reservation_elem.first.text_content()
                    # "予約番号：12345678" から番号部分を抽出
                    if text and "：" in text:
                        reservation_number = text.split("：")[1].strip()
                        print(f"  予約番号: {reservation_number}")

            # スクリーンショット（購入後）
            screenshot_after = f"ex_purchase_complete_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            await page.screenshot(path=screenshot_after)
            print(f"  完了画面スクリーンショット: {screenshot_after}")

            return PurchaseResult(
                success=True,
                message="予約購入が完了しました",
                reservation_number=reservation_number,
                screenshot_path=screenshot_after,
            )
        else:
            # 3Dセキュア認証画面またはエラー画面の可能性
            current_url = page.url
            print(f"\n[WARN] 完了画面に到達していません")
            print(f"  現在のURL: {current_url}")

            # スクリーンショット（エラー確認用）
            screenshot_error = f"ex_purchase_error_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            await page.screenshot(path=screenshot_error)
            print(f"  エラー確認用スクリーンショット: {screenshot_error}")

            # 3Dセキュア認証が必要な場合のメッセージ
            if "3dsecure" in current_url.lower() or "authentication" in current_url.lower():
                return PurchaseResult(
                    success=False,
                    message="3Dセキュア認証が必要です（手動で認証を完了してください）",
                    screenshot_path=screenshot_error,
                )

            return PurchaseResult(
                success=False,
                message="購入処理が完了しませんでした（エラーまたは認証が必要）",
                screenshot_path=screenshot_error,
            )

    except PlaywrightTimeout:
        screenshot_path = f"error_purchase_timeout_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        try:
            await page.screenshot(path=screenshot_path)
        except Exception:
            pass

        return PurchaseResult(
            success=False,
            message="タイムアウト: 購入処理に失敗しました",
            screenshot_path=screenshot_path,
        )
    except Exception as e:
        screenshot_path = f"error_purchase_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        try:
            await page.screenshot(path=screenshot_path)
        except Exception:
            pass

        return PurchaseResult(
            success=False,
            message=f"購入エラー: {str(e)}",
            screenshot_path=screenshot_path,
        )
