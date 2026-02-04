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
    SEAT_MAP,
)
from app.executors.ex_reservation.seat_map import (
    open_seat_map,
    OpenSeatMapResult,
    get_seat_map_info,
    select_seat_from_map,
    find_seats_with_adjacent_empty,
    parse_seat_specification,
    format_seat_info,
    SeatMapInfo,
    SEAT_TYPES,
    scan_all_cars_for_seat,
    AllCarsScanResult,
)
from app.executors.ex_reservation.models import (
    BrowserState,
    RequestedConditions,
    ActualResult,
    SeatDeviation,
)
from app.executors.ex_reservation.login import check_logged_in


@dataclass
class SeatSelectionResult:
    """
    座席選択結果

    第一原理に基づいた設計:
    1. 要件と結果の差分を必ず報告
    2. ブラウザの実際の状態を含める
    3. 失敗時は理由と代替案を提示
    4. 決定ポイントのスクリーンショットをVision API用に含める
    """
    success: bool
    message: str
    screenshot_path: Optional[str] = None
    screenshot_base64: Optional[str] = None  # Vision API用（決定ポイントのスクショ）
    seat_map_info: Optional[SeatMapInfo] = None  # 座席表情報
    selected_seat: Optional[str] = None  # 選択した座席（例: "5号車3番A席"）
    adjacent_empty_seats: Optional[List[str]] = None  # 隣が空いている席のリスト
    # 第一原理: 差分報告
    deviation: Optional[SeatDeviation] = None  # 要件と結果の差分
    browser_state: Optional[BrowserState] = None  # ブラウザの実際の状態
    # 失敗時の診断情報
    failure_reason: Optional[str] = None  # 具体的な失敗理由
    suggested_alternatives: Optional[List[str]] = None  # 代替案


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
        # まず見出しで確認（より確実）
        heading = page.locator(AGREEMENT_DIALOG["heading"])
        if await heading.count() > 0:
            print("同意事項ダイアログが表示されました")

            # スクリーンショット
            screenshot_path = f"ex_agreement_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            await page.screenshot(path=screenshot_path)
            print(f"  スクリーンショット: {screenshot_path}")

            # 同意するチェックボックスをクリック
            agree_checkbox = page.locator(AGREEMENT_DIALOG["agree_checkbox"])
            if await agree_checkbox.count() > 0:
                await agree_checkbox.click(force=True)
                print("  「同意する」をクリックしました")

                # ボタンが有効化されるのを待つ
                await page.wait_for_timeout(1000)

                # JavaScriptでダイアログ内のボタンを直接クリック
                # sb-4: 同意後に確認画面へ進むボタン (display:noneでも発火)
                await page.evaluate("""
                    () => {
                        const button = document.getElementById('sb-4');
                        if (button && button.onclick) {
                            button.onclick.call(button);
                        }
                    }
                """)
                print("  「予約を続ける」ボタンをクリックしました（JavaScript実行）")

                # ページ遷移を待つ
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
                await page.wait_for_timeout(1000)

                # ダイアログが閉じたか確認
                dialog = page.locator(AGREEMENT_DIALOG["dialog"])
                dialog_visible = await dialog.is_visible() if await dialog.count() > 0 else False

                if not dialog_visible:
                    print("  [OK] ダイアログが閉じました")
                    return True
                else:
                    print("  [WARN]  ダイアログがまだ表示されています")
                    return False

            return False
        return False

    except Exception as e:
        print(f"同意事項ダイアログ処理エラー: {e}")
        return False


def _determine_seat_type(letter: str) -> str:
    """座席列から座席タイプを判定（2列席/3列席）"""
    if letter in ("D", "E"):
        return "2列席" + SEAT_TYPES.get(letter, "")
    else:
        return "3列席" + SEAT_TYPES.get(letter, "")


def _determine_requested_seat_type(seat_position: str) -> Optional[str]:
    """座席位置指定からリクエストされた座席タイプを推定"""
    if not seat_position or seat_position == "指定なし":
        return None

    pos_lower = seat_position.lower()

    # 窓側E = 2列席窓側
    if "e" in pos_lower or ("窓" in seat_position and "2" in seat_position):
        return "2列席窓側"
    # 窓側A = 3列席窓側
    if "a" in pos_lower and "窓" in seat_position:
        return "3列席窓側"
    # 通路側D = 2列席通路側
    if "d" in pos_lower:
        return "2列席通路側"
    # 通路側C = 3列席通路側
    if "c" in pos_lower:
        return "3列席通路側"
    # 窓側（指定なし）= どちらか
    if "窓" in seat_position:
        return "窓側"
    if "通路" in seat_position:
        return "通路側"

    return None


async def _get_browser_state(page: Page) -> BrowserState:
    """現在のブラウザ状態を取得"""
    try:
        url = page.url
        logged_in = await check_logged_in(page)

        # ページタイプを判定
        page_type = "unknown"
        if "login" in url.lower():
            page_type = "login"
        elif "seat" in url.lower() or await page.locator('button.seat_map_button').count() > 0:
            page_type = "seat_selection"
        elif await page.locator('.seat-select').count() > 0:
            page_type = "seat_map"
        elif "confirm" in url.lower():
            page_type = "confirmation"

        # エラーメッセージを探す
        error_message = None
        error_elem = page.locator('.error-message, .alert-danger, [class*="error"]').first
        if await error_elem.count() > 0:
            error_message = await error_elem.text_content()

        return BrowserState(
            url=url,
            page_type=page_type,
            logged_in=logged_in,
            error_message=error_message,
        )
    except Exception as e:
        return BrowserState(error_message=str(e))


async def complete_seat_selection(
    page: Page,
    product_index: int = 0,
    seat_position: str = "指定なし",
    allow_separate_seats: bool = False,
    specific_seat: Optional[str] = None,
    prefer_adjacent_empty: bool = False,
    show_seat_map: bool = False,
) -> SeatSelectionResult:
    """
    座席選択を完了して確認画面へ進む

    第一原理に基づいた設計:
    1. 要件と結果の差分を必ず報告
    2. ブラウザの実際の状態を含める
    3. 失敗時は理由と代替案を提示

    Args:
        page: Playwrightページ
        product_index: 商品のインデックス（0: 最初の商品）
        seat_position: 座席位置（"指定なし", "窓側A", "通路側C", "通路側D", "窓側E"）
        allow_separate_seats: 席が離れても良いか（複数人予約時のみ有効）
        specific_seat: 特定席指定（例: "5号車3番A席"）
        prefer_adjacent_empty: 隣が空いている席を優先するか
        show_seat_map: 座席表を表示してスクリーンショットを返すか

    Returns:
        SeatSelectionResult: 座席選択結果（差分情報含む）
    """
    # リクエストされた条件を記録（第一原理: 何がリクエストされたかを明示）
    requested = RequestedConditions(
        seat_type=_determine_requested_seat_type(seat_position),
        seat_position=seat_position if seat_position != "指定なし" else None,
        adjacent_empty=prefer_adjacent_empty,
        specific_seat=specific_seat,
    )
    print(f"[SEAT] リクエスト条件: {requested.describe()}")

    try:
        # 商品を選択
        print(f"商品を選択中（インデックス: {product_index}）...")
        if not await select_product(page, product_index):
            return SeatSelectionResult(
                success=False,
                message="商品の選択に失敗しました",
            )

        print("[OK] 商品選択完了")

        # 座席表関連の変数
        seat_map_info: Optional[SeatMapInfo] = None
        selected_seat: Optional[str] = None
        adjacent_empty_seats: Optional[List[str]] = None
        vision_screenshot: Optional[str] = None  # Vision API用のスクショ

        # 座席表機能を使用する場合
        if specific_seat or prefer_adjacent_empty or show_seat_map:
            print("座席表を開いています...")

            open_result = await open_seat_map(page)
            if open_result.success:
                # Vision用スクリーンショットを保持
                vision_screenshot = open_result.screenshot_base64

                # 戦略: 座席表を開いたら最初から全号車をスキャンして状況を把握
                print("[STRATEGY] 全号車スキャンを開始して条件に合う席を探します...")

                scan_result = await scan_all_cars_for_seat(
                    page,
                    seat_position=seat_position,
                    prefer_adjacent_empty=prefer_adjacent_empty,
                )

                # スキャン結果のサマリーを表示
                if scan_result.scanned_cars:
                    print(f"[SCAN] スキャン完了: {len(scan_result.scanned_cars)}号車を確認")

                    # 条件に合う号車があるか
                    matching_cars = [
                        (car, result.matching_seats)
                        for car, result in scan_result.all_results.items()
                        if result.has_matching_seats
                    ]

                    if matching_cars:
                        summary = ", ".join([f"{c}号車({len(seats)}席)" for c, seats in matching_cars])
                        print(f"[SCAN] 条件に合う号車: {summary}")
                    else:
                        scanned_str = ", ".join([f"{c}号車" for c in scan_result.scanned_cars])
                        print(f"[SCAN] 条件に合う席が見つかりませんでした")
                        print(f"[SCAN] 確認済み: {scanned_str}")

                # 現在の号車の座席表情報を取得（表示用）
                current_car = scan_result.scanned_cars[0] if scan_result.scanned_cars else None
                if current_car and current_car in scan_result.all_results:
                    seat_map_info = scan_result.all_results[current_car].seat_map_info

                # 特定席指定の場合
                if specific_seat:
                    spec = parse_seat_specification(specific_seat)
                    if spec:
                        car_num = spec.get("car_number") or (seat_map_info.car_number if seat_map_info else 1)
                        row = spec["row"]
                        letter = spec["letter"]

                        print(f"特定席を選択中: {car_num}号車{row}番{letter}席...")

                        if await select_seat_from_map(page, car_num, row, letter):
                            selected_seat = format_seat_info(f"{row}{letter}", car_num)
                            print(f"[OK] {selected_seat} を選択しました")
                        else:
                            return SeatSelectionResult(
                                success=False,
                                message=f"指定された座席 {specific_seat} を選択できませんでした",
                                seat_map_info=seat_map_info,
                            )
                    else:
                        print(f"[WARN] 座席指定のパースに失敗: {specific_seat}")

                # 条件に合う席を選択（スキャン結果から最適な号車を使用）
                elif scan_result.best_car and scan_result.best_seats:
                    best_seat = scan_result.best_seats[0]
                    spec = parse_seat_specification(best_seat)

                    if spec:
                        row = spec["row"]
                        letter = spec["letter"]
                        car_num = scan_result.best_car

                        print(f"[SELECT] 最適な席を選択: {car_num}号車{row}番{letter}席...")

                        if await select_seat_from_map(page, car_num, row, letter):
                            selected_seat = format_seat_info(f"{row}{letter}", car_num)
                            # 選択した号車の座席表情報に更新
                            if car_num in scan_result.all_results:
                                seat_map_info = scan_result.all_results[car_num].seat_map_info
                            adjacent_empty_seats = scan_result.best_seats
                            print(f"[OK] {selected_seat} を選択しました")
                        else:
                            print(f"[WARN] 座席選択に失敗、通常のフローで続行")
                else:
                    # どの号車にも条件に合う席がない
                    if scan_result.no_matching_seats_anywhere:
                        print(f"[WARN] 全{len(scan_result.scanned_cars)}号車に条件に合う席がありません、通常のフローで続行")
                    else:
                        print("[WARN] スキャン結果が不明、通常のフローで続行")
            else:
                print(f"[WARN] 座席表を開けませんでした: {open_result.message}、通常のフローで続行")

        # 座席表で選択しなかった場合は通常の座席位置選択
        if not selected_seat and seat_position != "指定なし":
            print(f"座席位置を選択中（{seat_position}）...")
            if not await select_seat_position(page, seat_position):
                return SeatSelectionResult(
                    success=False,
                    message=f"座席位置（{seat_position}）の選択に失敗しました",
                    seat_map_info=seat_map_info,
                )
            print("[OK] 座席位置選択完了")

        # 「席が離れても良い」チェックボックス（複数人予約時）
        if allow_separate_seats:
            print("「席が離れても良い」をチェック中...")
            checkbox = page.locator(SEAT_SELECTION["allow_separate_checkbox"])
            if await checkbox.count() > 0:
                await checkbox.click(force=True)
                await page.wait_for_timeout(500)
                print("[OK] 「席が離れても良い」をチェックしました")
            else:
                print("[WARN]  「席が離れても良い」チェックボックスが見つかりません（1人予約の場合は正常）")

        # スクリーンショット
        screenshot_path = f"ex_seat_selected_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        await page.screenshot(path=screenshot_path)

        # 予約を続けるボタンをクリック
        print("「予約を続ける」ボタンをクリック中...")
        continue_btn = page.locator(SEAT_SELECTION["continue_button"])
        if await continue_btn.count() > 0:
            await continue_btn.click()
            await page.wait_for_load_state("domcontentloaded")
            # ダイアログまたは確認画面の表示を待つ
            await page.wait_for_timeout(2000)
        else:
            return SeatSelectionResult(
                success=False,
                message="「予約を続ける」ボタンが見つかりません",
                screenshot_path=screenshot_path,
            )

        # 同意事項ダイアログが表示された場合に対応
        print("同意事項ダイアログの確認中...")
        await handle_agreement_dialog(page)

        # 確認画面のスクリーンショット
        final_screenshot_path = f"ex_confirmation_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        await page.screenshot(path=final_screenshot_path)

        # ブラウザ状態を取得
        browser_state = await _get_browser_state(page)
        browser_state.screenshot_path = final_screenshot_path

        # 実際の結果を構築
        actual = None
        if selected_seat:
            spec = parse_seat_specification(selected_seat)
            if spec:
                actual_letter = spec.get("letter", "")
                actual = ActualResult(
                    seat=selected_seat,
                    seat_type=_determine_seat_type(actual_letter),
                    car_number=spec.get("car_number"),
                    row=spec.get("row"),
                    letter=actual_letter,
                    adjacent_empty=actual_letter in [s[-1] for s in (adjacent_empty_seats or [])[:5]],
                )

        # 差分を計算（第一原理: 差分があれば必ず報告）
        deviation = None
        if requested.seat_type and actual:
            # 2列席を要求したのに3列席を返した、など
            requested_is_2col = "2列席" in (requested.seat_type or "")
            actual_is_2col = "2列席" in (actual.seat_type or "")

            if requested_is_2col != actual_is_2col:
                deviation = SeatDeviation(
                    has_deviation=True,
                    requested=requested,
                    actual=actual,
                    reason=f"要求された{requested.seat_type}が現在の号車で見つからなかったため、{actual.seat_type}を選択しました",
                    alternatives_checked=[f"{seat_map_info.car_number}号車"] if seat_map_info else [],
                )
                print(f"[SEAT] 差分検出: {deviation.describe()}")

        # メッセージを構築
        message = "座席選択が完了しました"
        if selected_seat:
            message = f"座席選択が完了しました: {selected_seat}"

        # 差分がある場合はメッセージに追加
        if deviation and deviation.has_deviation:
            message += f"\n\n【注意】{deviation.reason}"

        # 決定ポイントのスクリーンショット（優先度: 最終画面 > 座席表画面）
        # ダンに見せるのは「最終的に選んだ状態」が良い
        final_vision_screenshot = None
        if seat_map_info and seat_map_info.screenshot_base64:
            final_vision_screenshot = seat_map_info.screenshot_base64
        elif vision_screenshot:
            final_vision_screenshot = vision_screenshot

        return SeatSelectionResult(
            success=True,
            message=message,
            screenshot_path=final_screenshot_path,
            screenshot_base64=final_vision_screenshot,
            seat_map_info=seat_map_info,
            selected_seat=selected_seat,
            adjacent_empty_seats=adjacent_empty_seats,
            deviation=deviation,
            browser_state=browser_state,
        )

    except PlaywrightTimeout:
        screenshot_path = f"error_ex_seat_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        try:
            await page.screenshot(path=screenshot_path)
        except Exception:
            pass

        # ブラウザ状態を取得（可能な場合）
        browser_state = None
        try:
            browser_state = await _get_browser_state(page)
            browser_state.screenshot_path = screenshot_path
        except Exception:
            pass

        return SeatSelectionResult(
            success=False,
            message="タイムアウト: 座席選択に失敗しました",
            screenshot_path=screenshot_path,
            seat_map_info=seat_map_info if 'seat_map_info' in dir() else None,
            browser_state=browser_state,
            failure_reason="ページの読み込みまたは要素の表示がタイムアウトしました",
            deviation=SeatDeviation(
                has_deviation=True,
                requested=requested,
                actual=None,
                reason="タイムアウトのため座席選択を完了できませんでした",
            ),
        )
    except Exception as e:
        # ブラウザ状態を取得（可能な場合）
        browser_state = None
        try:
            browser_state = await _get_browser_state(page)
        except Exception:
            pass

        return SeatSelectionResult(
            success=False,
            message=f"座席選択エラー: {str(e)}",
            seat_map_info=seat_map_info if 'seat_map_info' in dir() else None,
            browser_state=browser_state,
            failure_reason=str(e),
            deviation=SeatDeviation(
                has_deviation=True,
                requested=requested,
                actual=None,
                reason=f"エラーが発生しました: {str(e)}",
            ),
        )
