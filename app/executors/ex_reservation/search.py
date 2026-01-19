"""
EX予約 列車検索処理

リファクタリング: 2026/01/16
- 共通モジュール（models, constants, errors, parser）を使用
- print() → logging
- マジックストリング排除
"""

import logging
from typing import Optional
from datetime import datetime
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from app.executors.ex_reservation.models import (
    SearchParams,
    SearchResult,
    TrainInfo,
)
from app.executors.ex_reservation.constants import TIMEOUTS, ERROR_MESSAGES
from app.executors.ex_reservation.errors import (
    SearchError,
    NoTrainsFoundError,
    TimeoutError as EXTimeoutError,
)
from app.executors.ex_reservation.parser import parse_search_results
from app.executors.ex_reservation.selectors_complete import (
    MYPAGE,
    SEARCH_FORM,
    TIME_NOTICE,
)

logger = logging.getLogger(__name__)


async def open_search_form(page: Page) -> bool:
    """
    マイページから検索フォームを開く

    Returns:
        True: 成功, False: 失敗
    """
    try:
        search_button = page.locator(MYPAGE["search_train"])
        if await search_button.count() > 0:
            await search_button.click()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(TIMEOUTS["long_wait"])
            return True

        logger.warning("列車検索ボタンが見つかりません")
        return False

    except Exception as e:
        logger.error(f"検索フォーム遷移エラー: {e}")
        return False


async def fill_search_form(
    page: Page,
    params: SearchParams,
) -> bool:
    """
    検索フォームに条件を入力

    Args:
        page: Playwrightページ
        params: 検索パラメータ（SearchParamsインスタンス）

    Returns:
        True: 成功, False: 失敗
    """
    try:
        # フォーム用パラメータに変換
        form_params = params.to_form_params()

        # 駅名からvalue値を取得
        dep_value = SEARCH_FORM["stations"].get(form_params["departure"])
        arr_value = SEARCH_FORM["stations"].get(form_params["arrival"])

        if not dep_value:
            logger.error(f"出発駅が見つかりません: {form_params['departure']}")
            return False
        if not arr_value:
            logger.error(f"到着駅が見つかりません: {form_params['arrival']}")
            return False

        # 日付を選択
        if form_params["date"]:
            await _select_date(page, form_params["date"])

        # 出発/到着時刻選択
        logger.debug("出発/到着: 出発時刻で検索")
        await page.locator(SEARCH_FORM["departure_arrival"]).select_option(value="1")
        await page.wait_for_timeout(TIMEOUTS["short_wait"])

        # 時刻を選択（時）
        if form_params["hour"]:
            hour_value = SEARCH_FORM["hours"].get(form_params["hour"])
            if hour_value:
                logger.debug(f"時刻（時）: {form_params['hour']} -> {hour_value}")
                await page.locator(SEARCH_FORM["hour"]).select_option(value=hour_value)
                await page.wait_for_timeout(TIMEOUTS["short_wait"])

        # 時刻を選択（分）
        if form_params["minute"]:
            minute_value = SEARCH_FORM["minutes"].get(form_params["minute"])
            if minute_value:
                logger.debug(f"時刻（分）: {form_params['minute']} -> {minute_value}")
                await page.locator(SEARCH_FORM["minute"]).select_option(value=minute_value)
                await page.wait_for_timeout(TIMEOUTS["short_wait"])

        # 出発駅を選択
        logger.debug(f"出発駅: {form_params['departure']} -> {dep_value}")
        await page.locator(SEARCH_FORM["departure_station"]).select_option(value=dep_value)
        await page.wait_for_timeout(TIMEOUTS["short_wait"])

        # 到着駅を選択
        logger.debug(f"到着駅: {form_params['arrival']} -> {arr_value}")
        await page.locator(SEARCH_FORM["arrival_station"]).select_option(value=arr_value)
        await page.wait_for_timeout(TIMEOUTS["short_wait"])

        # 人数を選択
        adult_count = form_params.get("adult_count", 1)
        if adult_count > 0:
            adult_value = f"{adult_count:02d}"
            logger.debug(f"大人人数: {adult_count} -> {adult_value}")
            await page.locator(SEARCH_FORM["adult_count"]).select_option(value=adult_value)

        await page.wait_for_timeout(TIMEOUTS["medium_wait"])

        logger.info(
            f"検索条件入力完了: {form_params['departure']} → {form_params['arrival']} "
            f"{form_params.get('date', '本日')} {form_params.get('hour', '')} {form_params.get('minute', '')}"
        )
        return True

    except Exception as e:
        logger.error(f"検索フォーム入力エラー: {e}", exc_info=True)
        return False


async def _select_date(page: Page, date: str) -> bool:
    """
    カレンダーから日付を選択

    Args:
        date: 日付（YYYYMMDD形式）

    Returns:
        True: 成功, False: 失敗
    """
    try:
        logger.debug(f"日付選択: {date}")
        popup = page.locator(SEARCH_FORM["calendar_popup"])

        # ポップアップが既に表示されているか確認
        is_visible = await popup.is_visible() if await popup.count() > 0 else False

        if not is_visible:
            # カレンダーエリアをクリック
            date_area = page.locator(SEARCH_FORM["date_area"])
            await date_area.click(force=True)
            await page.wait_for_timeout(TIMEOUTS["medium_wait"])

            # ポップアップが表示されるのを待つ
            try:
                await popup.wait_for(state="visible", timeout=5000)
            except Exception:
                logger.debug("カレンダーポップアップが表示されませんでした（続行）")

        # 日付セルをクリック
        date_cell = page.locator(f'div.selectable[class*="{date}"]')

        if await date_cell.count() == 0:
            logger.error(f"日付が見つかりません: {date}")
            return False

        await date_cell.click()
        await page.wait_for_timeout(TIMEOUTS["medium_wait"])

        # ポップアップが閉じるのを待つ
        try:
            await popup.wait_for(state="hidden", timeout=3000)
        except Exception:
            pass

        logger.debug("日付選択完了")
        return True

    except Exception as e:
        logger.warning(f"日付選択エラー: {e}")
        return False


async def execute_search(page: Page) -> SearchResult:
    """
    検索を実行して結果を取得

    Returns:
        SearchResult: 検索結果
    """
    try:
        # 「予約を続ける」ボタンをクリック
        continue_btn = page.locator(SEARCH_FORM["continue_button"])
        if await continue_btn.count() > 0:
            await continue_btn.click()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(TIMEOUTS["long_wait"])
        else:
            return SearchResult(
                success=False,
                message="「予約を続ける」ボタンが見つかりません",
            )

        # 時間帯注意ページが表示された場合
        await _handle_time_notice_page(page)

        # 検索結果をパース（parser.pyの関数を使用）
        trains = await parse_search_results(page)

        # スクリーンショット
        screenshot_path = f"ex_search_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        await page.screenshot(path=screenshot_path)

        if trains:
            return SearchResult(
                success=True,
                message=f"{len(trains)}件の列車が見つかりました",
                trains=trains,
                screenshot_path=screenshot_path,
            )
        else:
            return SearchResult(
                success=False,
                message=ERROR_MESSAGES["no_trains"],
                screenshot_path=screenshot_path,
            )

    except PlaywrightTimeout:
        screenshot_path = f"error_ex_search_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        try:
            await page.screenshot(path=screenshot_path)
        except Exception:
            pass

        return SearchResult(
            success=False,
            message="タイムアウト: 検索に失敗しました",
            screenshot_path=screenshot_path,
        )

    except Exception as e:
        logger.error(f"検索実行エラー: {e}", exc_info=True)
        return SearchResult(
            success=False,
            message=f"検索エラー: {str(e)}",
        )


async def _handle_time_notice_page(page: Page) -> None:
    """
    時間帯注意ページが表示された場合に処理

    23:30〜翌5:30の予約時に表示される警告ページ
    """
    notice_heading = await page.locator(TIME_NOTICE["heading"]).count()
    if notice_heading > 0:
        logger.info("時間帯注意ページが表示されました - 「予約を続ける」をクリック")

        # スクリーンショット
        screenshot_path = f"ex_time_notice_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        await page.screenshot(path=screenshot_path)

        # 「予約を続ける」ボタンをクリック
        continue_btn = page.locator(TIME_NOTICE["continue_button"])
        if await continue_btn.count() > 0:
            await continue_btn.click()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(TIMEOUTS["long_wait"])


async def select_train(page: Page, index: int = 0) -> bool:
    """
    列車候補を選択

    Args:
        page: Playwrightページ
        index: 候補インデックス（0始まり）

    Returns:
        True: 成功, False: 失敗
    """
    try:
        select_buttons = await page.locator('text="この候補を選択"').all()

        if index < len(select_buttons):
            logger.info(f"列車候補 {index + 1} を選択")
            await select_buttons[index].click()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(TIMEOUTS["long_wait"])
            return True

        logger.error(f"インデックス {index} は範囲外です（候補数: {len(select_buttons)}）")
        return False

    except Exception as e:
        logger.error(f"列車選択エラー: {e}")
        return False


# =============================================================================
# 高レベルAPI（SearchParamsを使用）
# =============================================================================

async def search_trains(page: Page, params: SearchParams) -> SearchResult:
    """
    列車検索の一連の処理を実行

    1. マイページから検索フォームを開く
    2. 検索条件を入力
    3. 検索実行
    4. 結果をパース

    Args:
        page: Playwrightページ（ログイン済み）
        params: 検索パラメータ

    Returns:
        SearchResult: 検索結果
    """
    logger.info(f"列車検索開始: {params.departure} → {params.arrival} {params.date}")

    # 検索フォームを開く
    if not await open_search_form(page):
        return SearchResult(
            success=False,
            message="検索フォームを開けませんでした",
        )

    # 検索条件を入力
    if not await fill_search_form(page, params):
        return SearchResult(
            success=False,
            message="検索条件の入力に失敗しました",
        )

    # 検索実行
    result = await execute_search(page)

    if result.success:
        logger.info(f"検索成功: {len(result.trains)}件の列車が見つかりました")
    else:
        logger.warning(f"検索失敗: {result.message}")

    return result
