"""
EX予約 キャンセル（払戻）処理

最終更新: 2026/01/12
予約をキャンセルして払戻を実行
"""

from typing import Optional, Callable, Awaitable
from dataclasses import dataclass
from datetime import datetime
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout


@dataclass
class CancelResult:
    """キャンセル結果"""
    success: bool
    message: str
    refund_amount: Optional[str] = None  # 払戻金額
    refund_fee: Optional[str] = None  # 払戻手数料
    screenshot_path: Optional[str] = None


async def cancel_reservation(
    page: Page,
    reservation_number: str,
    confirm: bool = False,
) -> CancelResult:
    """
    予約をキャンセル（払戻）する

    Args:
        page: Playwrightのページオブジェクト
        reservation_number: 予約番号（お預かり番号）
        confirm: Trueの場合、実際にキャンセルを実行

    Returns:
        CancelResult: キャンセル結果
    """
    try:
        print(f"[CANCEL] 予約番号 {reservation_number} をキャンセル中...")
        print()

        # Step 1: メニューボタンをクリック
        print("[1/7] メニューを開く...")
        menu_button = page.locator('button:has-text("メニュー"), a:has-text("メニュー")').first
        if await menu_button.count() > 0:
            await menu_button.click()
            await page.wait_for_timeout(2000)
            print("  [OK] メニューを開きました")
        else:
            print("  [INFO] メニューボタンが見つかりません（すでにメニュー画面の可能性）")

        # Step 2: 予約確認リンクをクリック
        print("[2/7] 予約確認画面に移動...")

        # より広いセレクタで検索
        reservation_link_selectors = [
            'a:has-text("予約確認/変更/払戻")',
            'a:has-text("予約確認")',
            'a:has-text("確認")',
            'text="予約確認"',
        ]

        reservation_link = None
        for selector in reservation_link_selectors:
            link = page.locator(selector).first
            if await link.count() > 0:
                # テキストに"確認"または"変更"または"払戻"が含まれているか確認
                text_content = await link.text_content()
                if text_content and ("確認" in text_content or "変更" in text_content or "払戻" in text_content):
                    reservation_link = link
                    print(f"  [INFO] リンクを発見: '{text_content.strip()}'")
                    break

        if not reservation_link:
            # デバッグ: 現在の画面を保存
            screenshot_debug = f"ex_cancel_debug_no_link_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            await page.screenshot(path=screenshot_debug)

            # 全てのリンクを表示
            all_links = await page.locator('a').all()
            print(f"  [DEBUG] Found {len(all_links)} links on page:")
            for i, link in enumerate(all_links[:20]):
                try:
                    text = await link.text_content()
                    if text and text.strip():
                        print(f"    [{i}] {text.strip()[:50]}")
                except:
                    pass

            return CancelResult(
                success=False,
                message="予約確認リンクが見つかりませんでした",
                screenshot_path=screenshot_debug
            )

        await reservation_link.click()
        await page.wait_for_timeout(3000)
        print("  [OK] 予約確認画面に移動しました")

        # Step 3: 予約番号を探す
        print(f"[3/7] 予約番号 {reservation_number} を検索...")
        reservation_element = page.get_by_text(reservation_number, exact=False).first

        if await reservation_element.count() == 0:
            # スクリーンショットを保存
            screenshot_path = f"ex_cancel_not_found_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            await page.screenshot(path=screenshot_path)

            return CancelResult(
                success=False,
                message=f"予約番号 {reservation_number} が見つかりませんでした",
                screenshot_path=screenshot_path
            )

        print(f"  [OK] 予約番号 {reservation_number} を見つけました")

        # Step 4: 払戻ボタンをクリック
        print("[4/7] 払戻ボタンをクリック...")

        # 実際のsubmitボタンを探す
        refund_button = page.locator('input[type="submit"][value*="払戻"]').first

        if await refund_button.count() == 0:
            # フォールバック: id="sb-1"で探す
            refund_button = page.locator('input[id="sb-1"]').first

        if await refund_button.count() == 0:
            return CancelResult(
                success=False,
                message="払戻ボタンが見つかりませんでした"
            )

        await refund_button.click(force=True)  # force clickでオーバーレイをバイパス
        await page.wait_for_timeout(3000)
        print("  [OK] 払戻ボタンをクリックしました")

        # Step 5: 確認ダイアログのOKボタンをクリック
        print("[5/7] 確認ダイアログのOKボタンをクリック...")

        # ダイアログ内の「確認画面へ」ボタンを探す
        dialog_ok_selectors = [
            'button[name="b3"]',
            'button:has-text("確認画面へ")',
            'text="確認画面へ"',
        ]

        dialog_clicked = False
        for selector in dialog_ok_selectors:
            dialog_ok = page.locator(selector).first
            if await dialog_ok.count() > 0:
                await dialog_ok.click()
                await page.wait_for_timeout(3000)
                print("  [OK] 確認ダイアログのOKボタンをクリックしました")
                dialog_clicked = True
                break

        if not dialog_clicked:
            print("  [INFO] 確認ダイアログが表示されませんでした")

        # 確認画面のスクリーンショット
        screenshot_confirm = f"ex_cancel_confirm_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        await page.screenshot(path=screenshot_confirm)
        print(f"  [Screenshot] {screenshot_confirm}")

        # 払戻金額と手数料を取得
        refund_amount = None
        refund_fee = None

        try:
            # 払戻金額を探す
            amount_text = await page.locator('text=/払戻金額/').locator('..').text_content()
            if "¥" in amount_text:
                refund_amount = amount_text.split("¥")[-1].strip()

            # 払戻手数料を探す
            fee_text = await page.locator('text=/払戻手数料/').locator('..').text_content()
            if "¥" in fee_text:
                refund_fee = fee_text.split("¥")[-1].strip()

            print(f"  [INFO] 払戻金額: ¥{refund_amount}, 手数料: ¥{refund_fee}")
        except:
            print("  [WARN] 払戻金額の取得に失敗しました")

        # Step 6: 最終確認
        if not confirm:
            print()
            print("[6/7] 実際のキャンセルはスキップします（confirm=False）")
            print()
            return CancelResult(
                success=True,
                message="キャンセル確認画面まで到達しました（実行はスキップ）",
                refund_amount=refund_amount,
                refund_fee=refund_fee,
                screenshot_path=screenshot_confirm
            )

        # Step 7: 払戻を実行
        print("[6/7] 払戻を実行中...")
        print()
        print("=" * 70)
        print("WARNING: 実際に払戻を実行します！")
        print("=" * 70)
        print()

        # 最終実行ボタンをクリック
        execute_button = page.locator('input[name="b2"][type="submit"]').first

        if await execute_button.count() == 0:
            # フォールバック
            execute_button = page.locator('text="OK 払戻する"').first

        if await execute_button.count() == 0:
            return CancelResult(
                success=False,
                message="払戻実行ボタンが見つかりませんでした",
                screenshot_path=screenshot_confirm
            )

        await execute_button.click(force=True)
        await page.wait_for_timeout(2000)
        print("  [OK] 払戻実行ボタンをクリックしました")

        # 最終確認ダイアログのOKボタンをクリック
        print("  [INFO] 最終確認ダイアログのOKボタンをクリック中...")
        final_ok_selectors = [
            'text="OK"',
            'button:has-text("OK")',
            'input[type="button"][value="OK"]',
            'a:has-text("OK")',
        ]

        dialog_closed = False
        for selector in final_ok_selectors:
            final_ok = page.locator(selector).first
            if await final_ok.count() > 0:
                await final_ok.click()
                await page.wait_for_timeout(5000)
                print("  [OK] 最終確認ダイアログのOKボタンをクリックしました")
                dialog_closed = True
                break

        if not dialog_closed:
            print("  [WARN] 最終確認ダイアログが見つかりませんでした")

        print("  [OK] 払戻を実行しました")

        # Step 7: 完了画面を確認
        print("[7/7] 完了画面を確認...")

        # 完了メッセージを探す
        success_messages = [
            "払戻が完了しました",
            "払戻しました",
            "払戻完了",
        ]

        completed = False
        for msg in success_messages:
            if await page.locator(f'text="{msg}"').count() > 0:
                completed = True
                print(f"  [OK] 完了メッセージを検出: {msg}")
                break

        # 完了画面のスクリーンショット
        screenshot_complete = f"ex_cancel_complete_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        await page.screenshot(path=screenshot_complete)

        if completed:
            print()
            print("=" * 70)
            print("キャンセル（払戻）が完了しました")
            print("=" * 70)
            print(f"予約番号: {reservation_number}")
            if refund_amount:
                print(f"払戻金額: ¥{refund_amount}")
            if refund_fee:
                print(f"払戻手数料: ¥{refund_fee}")
            print()

            return CancelResult(
                success=True,
                message="キャンセル（払戻）が完了しました",
                refund_amount=refund_amount,
                refund_fee=refund_fee,
                screenshot_path=screenshot_complete
            )
        else:
            return CancelResult(
                success=False,
                message="完了画面を確認できませんでした",
                refund_amount=refund_amount,
                refund_fee=refund_fee,
                screenshot_path=screenshot_complete
            )

    except PlaywrightTimeout as e:
        screenshot_path = f"ex_cancel_timeout_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        await page.screenshot(path=screenshot_path)

        return CancelResult(
            success=False,
            message=f"タイムアウト: {str(e)}",
            screenshot_path=screenshot_path
        )

    except Exception as e:
        screenshot_path = f"ex_cancel_error_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        await page.screenshot(path=screenshot_path)

        return CancelResult(
            success=False,
            message=f"エラー: {str(e)}",
            screenshot_path=screenshot_path
        )
