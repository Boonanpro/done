"""
EX予約 列車検索処理

最終更新: 2026/01/11
完全検証済みセレクタを使用
"""

from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from app.executors.ex_reservation.selectors_complete import (
    MYPAGE,
    SEARCH_FORM,
    TIME_NOTICE,
    SEARCH_RESULT,
)


@dataclass
class TrainOption:
    """列車候補"""
    index: int  # 候補のインデックス（0始まり）
    train_name: str  # のぞみ 49 号
    departure_time: str  # 19:02
    arrival_time: str  # 21:30
    departure_station: str = ""
    arrival_station: str = ""
    available: bool = True


@dataclass
class SearchResult:
    """検索結果"""
    success: bool
    message: str
    options: List[TrainOption] = field(default_factory=list)
    screenshot_path: Optional[str] = None


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
            await page.wait_for_timeout(2000)
            return True
        return False
    except Exception:
        return False


async def fill_search_form(
    page: Page,
    departure_station: str,
    arrival_station: str,
    hour: Optional[str] = None,
    adult_count: int = 1,
) -> bool:
    """
    検索フォームに条件を入力

    Args:
        page: Playwrightページ
        departure_station: 出発駅名（例: "新大阪"）
        arrival_station: 到着駅名（例: "博多"）
        hour: 時刻（例: "19時"）
        adult_count: 大人の人数（デフォルト: 1）

    Returns:
        True: 成功, False: 失敗
    """
    try:
        # 駅名からvalue値を取得
        dep_value = SEARCH_FORM["stations"].get(departure_station)
        arr_value = SEARCH_FORM["stations"].get(arrival_station)

        if not dep_value or not arr_value:
            print(f"エラー: 駅名が見つかりません - {departure_station} or {arrival_station}")
            return False

        # 時刻を選択
        if hour:
            hour_value = SEARCH_FORM["hours"].get(hour)
            if hour_value:
                await page.locator(SEARCH_FORM["hour"]).select_option(value=hour_value)

        # 出発駅を選択
        await page.locator(SEARCH_FORM["departure_station"]).select_option(value=dep_value)
        await page.wait_for_timeout(500)

        # 到着駅を選択
        await page.locator(SEARCH_FORM["arrival_station"]).select_option(value=arr_value)
        await page.wait_for_timeout(500)

        # 人数を選択
        if adult_count > 0:
            adult_value = f"{adult_count:02d}"
            await page.locator(SEARCH_FORM["adult_count"]).select_option(value=adult_value)

        await page.wait_for_timeout(1000)
        return True

    except Exception as e:
        print(f"検索フォーム入力エラー: {e}")
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
            await page.wait_for_timeout(3000)
        else:
            return SearchResult(
                success=False,
                message="「予約を続ける」ボタンが見つかりません",
            )

        # 時間帯注意ページが表示された場合
        notice_heading = await page.locator(TIME_NOTICE["heading"]).count()
        if notice_heading > 0:
            print("時間帯注意ページが表示されました - 「予約を続ける」をクリック")

            # スクリーンショット
            screenshot_path = f"ex_time_notice_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            await page.screenshot(path=screenshot_path)

            # 「予約を続ける」ボタンをクリック
            continue_btn2 = page.locator(TIME_NOTICE["continue_button"])
            if await continue_btn2.count() > 0:
                await continue_btn2.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(3000)

        # 検索結果をパース
        options = await parse_search_results(page)

        # スクリーンショット
        screenshot_path = f"ex_search_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        await page.screenshot(path=screenshot_path)

        if options:
            return SearchResult(
                success=True,
                message=f"{len(options)}件の列車が見つかりました",
                options=options,
                screenshot_path=screenshot_path,
            )
        else:
            return SearchResult(
                success=False,
                message="該当する列車が見つかりませんでした",
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
        return SearchResult(
            success=False,
            message=f"検索エラー: {str(e)}",
        )


async def parse_search_results(page: Page) -> List[TrainOption]:
    """
    検索結果をパースして列車候補リストを返す

    検証済みの検索結果画面から情報を抽出
    """
    options: List[TrainOption] = []

    try:
        # HTMLコンテンツを取得
        html = await page.content()

        # 「この候補を選択」ボタンの数で候補数を判定
        select_buttons = await page.locator(SEARCH_RESULT["select_candidate"]).all()
        num_candidates = len(select_buttons)

        print(f"列車候補数: {num_candidates}")

        # 各候補の情報を抽出
        import re

        # 候補ごとにブロックを分割（「候補」というテキストで分割）
        candidate_blocks = html.split('候補')[1:]  # 最初の要素は不要

        for i in range(min(num_candidates, len(candidate_blocks))):
            block = candidate_blocks[i]

            # 列車名を抽出
            train_name = ""
            train_match = re.search(r'<h3>([^<]+)</h3>', block)
            if train_match:
                train_name = train_match.group(1).strip()

            # 出発時刻を抽出
            dep_time = ""
            dep_match = re.search(r'<dt>(\d+時\d+分) 発</dt>', block)
            if dep_match:
                dep_time = dep_match.group(1)

            # 到着時刻を抽出
            arr_time = ""
            arr_match = re.search(r'<dt>(\d+時\d+分) 着</dt>', block)
            if arr_match:
                arr_time = arr_match.group(1)

            # 空席状況を抽出（普通車の○×を確認）
            available = True
            # 普通車アイコンの後の○×を確認
            ordinary_match = re.search(r'<span class="ordinary_ico"></span>：([○×−])', block)
            if ordinary_match:
                seat_status = ordinary_match.group(1)
                available = (seat_status == '○')

            option = TrainOption(
                index=i,
                train_name=train_name if train_name else f"列車候補 {i + 1}",
                departure_time=dep_time,
                arrival_time=arr_time,
                available=available,
            )
            options.append(option)

            print(f"  [{i}] {option.train_name} {option.departure_time}発 → {option.arrival_time}着 (空席: {'○' if option.available else '×'})")

    except Exception as e:
        print(f"検索結果パースエラー: {e}")
        import traceback
        traceback.print_exc()

    return options


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
        select_buttons = await page.locator(SEARCH_RESULT["select_candidate"]).all()

        if index < len(select_buttons):
            await select_buttons[index].click()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(3000)
            return True

        print(f"エラー: インデックス {index} は範囲外です（候補数: {len(select_buttons)}）")
        return False

    except Exception as e:
        print(f"列車選択エラー: {e}")
        return False
