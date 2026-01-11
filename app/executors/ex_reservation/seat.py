"""
EX予約 座席選択処理

最終更新: 2026/01/11
完全検証済みセレクタを使用
"""

from typing import Optional, List
from dataclasses import dataclass
from datetime import datetime
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from app.executors.ex_reservation.selectors_complete import (
    SEAT_SELECTION,
    AGREEMENT_DIALOG,
)


@dataclass
class SeatSelectionResult:
    """座席選択結果"""
    success: bool
    message: str
    screenshot_path: Optional[str] = None


async def select_product(page: Page, product_index: int = 0) -> bool:
    """
    商品（価格）を選択

    Args:
        page: Playwrightページ
        product_index: 商品のインデックス（0: 最初の商品、通常は最安値）

    Returns:
        True: 成功, False: 失敗
    """
    try:
        price_labels = await page.locator(SEAT_SELECTION["price_label"]).all()

        if product_index < len(price_labels):
            await price_labels[product_index].click()
            await page.wait_for_timeout(2000)
            return True
        else:
            print(f"エラー: 商品インデックス {product_index} は範囲外です（商品数: {len(price_labels)}）")
            return False

    except Exception as e:
        print(f"商品選択エラー: {e}")
        return False


async def select_seat_position(page: Page, position: str = "指定なし") -> bool:
    """
    座席位置（窓側/通路側）を選択

    Args:
        page: Playwrightページ
        position: 座席位置（"指定なし", "窓側A", "中央B", "通路側C", "通路側D", "窓側E"）

    Returns:
        True: 成功, False: 失敗
    """
    try:
        # 位置からvalue値を取得
        position_value = SEAT_SELECTION["seat_positions"].get(position)

        if not position_value:
            print(f"エラー: 座席位置が見つかりません - {position}")
            return False

        # 座席位置セレクタを選択
        await page.locator(SEAT_SELECTION["seat_position_select"]).select_option(value=position_value)
        await page.wait_for_timeout(1000)
        return True

    except Exception as e:
        print(f"座席位置選択エラー: {e}")
        return False


async def handle_agreement_dialog(page: Page) -> bool:
    """
    同意事項ダイアログが表示された場合に対応

    Returns:
        True: ダイアログを処理した, False: ダイアログが表示されていない
    """
    try:
        # ダイアログが表示されているかチェック
        dialog = page.locator(AGREEMENT_DIALOG["dialog"])
        if await dialog.count() > 0 and await dialog.is_visible():
            print("同意事項ダイアログが表示されました")

            # スクリーンショット
            screenshot_path = f"ex_agreement_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            await page.screenshot(path=screenshot_path)
            print(f"  スクリーンショット: {screenshot_path}")

            # 同意するチェックボックスをクリック（JavaScriptイベントを発火させる）
            agree_checkbox = page.locator(AGREEMENT_DIALOG["agree_checkbox"])
            if await agree_checkbox.count() > 0:
                # .check() ではなく .click() を使用してJavaScriptイベントを発火
                await agree_checkbox.click(force=True)
                print("  「同意する」をクリックしました")

                # JavaScriptの処理を待つ
                await page.wait_for_timeout(1000)

                # ボタンが有効化されたか確認
                continue_btn = page.locator(AGREEMENT_DIALOG["continue_button"])
                is_enabled = not await continue_btn.is_disabled()
                print(f"  「予約を続ける」ボタンの状態: {'有効' if is_enabled else '無効'}")

                if not is_enabled:
                    # まだ無効の場合は少し待つ
                    await page.wait_for_timeout(2000)
                    is_enabled = not await continue_btn.is_disabled()
                    print(f"  再確認後の状態: {'有効' if is_enabled else '無効'}")

                # 予約を続けるボタンをクリック
                if await continue_btn.count() > 0:
                    await continue_btn.click()
                    await page.wait_for_load_state("domcontentloaded")
                    await page.wait_for_timeout(2000)
                    print("  「予約を続ける」をクリックしました")
                    return True

            return False
        return False

    except Exception as e:
        print(f"同意事項ダイアログ処理エラー: {e}")
        return False


async def complete_seat_selection(page: Page, product_index: int = 0, seat_position: str = "指定なし") -> SeatSelectionResult:
    """
    座席選択を完了して確認画面へ進む

    Args:
        page: Playwrightページ
        product_index: 商品のインデックス（0: 最初の商品）
        seat_position: 座席位置（"指定なし", "窓側A", "通路側C", "通路側D", "窓側E"）

    Returns:
        SeatSelectionResult: 座席選択結果
    """
    try:
        # 商品を選択
        print(f"商品を選択中（インデックス: {product_index}）...")
        if not await select_product(page, product_index):
            return SeatSelectionResult(
                success=False,
                message="商品の選択に失敗しました",
            )

        print("✓ 商品選択完了")

        # 座席位置を選択
        if seat_position != "指定なし":
            print(f"座席位置を選択中（{seat_position}）...")
            if not await select_seat_position(page, seat_position):
                return SeatSelectionResult(
                    success=False,
                    message=f"座席位置（{seat_position}）の選択に失敗しました",
                )
            print("✓ 座席位置選択完了")

        # スクリーンショット
        screenshot_path = f"ex_seat_selected_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        await page.screenshot(path=screenshot_path)

        # 予約を続けるボタンをクリック
        print("「予約を続ける」ボタンをクリック中...")
        continue_btn = page.locator(SEAT_SELECTION["continue_button"])
        if await continue_btn.count() > 0:
            await continue_btn.click()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(3000)
        else:
            return SeatSelectionResult(
                success=False,
                message="「予約を続ける」ボタンが見つかりません",
                screenshot_path=screenshot_path,
            )

        # 同意事項ダイアログが表示された場合に対応
        await handle_agreement_dialog(page)

        # 確認画面のスクリーンショット
        final_screenshot_path = f"ex_confirmation_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        await page.screenshot(path=final_screenshot_path)

        return SeatSelectionResult(
            success=True,
            message="座席選択が完了しました",
            screenshot_path=final_screenshot_path,
        )

    except PlaywrightTimeout:
        screenshot_path = f"error_ex_seat_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        try:
            await page.screenshot(path=screenshot_path)
        except Exception:
            pass

        return SeatSelectionResult(
            success=False,
            message="タイムアウト: 座席選択に失敗しました",
            screenshot_path=screenshot_path,
        )
    except Exception as e:
        return SeatSelectionResult(
            success=False,
            message=f"座席選択エラー: {str(e)}",
        )
