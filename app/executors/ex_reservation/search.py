"""
EX予約 列車検索処理

実確認日: 2026/01/09
- 検索フォーム入力
- 検索実行
- 結果取得
"""

from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
import re
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from app.executors.ex_reservation.selectors import MYPAGE, SEARCH_FORM, SEARCH_RESULT


@dataclass
class TrainOption:
    """列車候補"""
    id: str
    train_name: str  # のぞみ 401 号
    departure_time: str  # 14:42
    arrival_time: str  # 16:22
    departure_station: str  # 東京
    arrival_station: str  # 名古屋
    duration: str  # 1時間40分
    price: Optional[int] = None
    seat_type: str = "普通車指定席"
    available: bool = True
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """検索結果"""
    success: bool
    message: str
    options: List[TrainOption] = field(default_factory=list)
    search_url: Optional[str] = None
    screenshot_path: Optional[str] = None


async def open_search_form(page: Page) -> bool:
    """
    マイページから検索フォームを開く
    
    Returns:
        True: 成功
        False: 失敗
    """
    try:
        # 「列車を検索」ボタンをクリック
        search_button = await page.query_selector(MYPAGE["search_train"])
        if search_button:
            await search_button.click()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(1000)
            return True
        return False
    except Exception:
        return False


async def fill_search_form(
    page: Page,
    departure: str,
    arrival: str,
    hour: Optional[str] = None,
    minute: Optional[str] = None,
) -> bool:
    """
    検索フォームに条件を入力
    
    Args:
        page: Playwrightページ
        departure: 出発駅（例: 東 京）
        arrival: 到着駅（例: 名古屋）
        hour: 時（例: 14時）
        minute: 分（例: 30分）
        
    Returns:
        True: 成功
        False: 失敗
    """
    try:
        # 乗車駅を選択
        departure_select = await page.query_selector(SEARCH_FORM["departure_station"])
        if departure_select:
            await departure_select.select_option(label=departure)
        
        # 降車駅を選択
        arrival_select = await page.query_selector(SEARCH_FORM["arrival_station"])
        if arrival_select:
            await arrival_select.select_option(label=arrival)
        
        # 時刻を選択
        if hour:
            hour_select = await page.query_selector(SEARCH_FORM["hour"])
            if hour_select:
                await hour_select.select_option(label=hour)
        
        if minute:
            minute_select = await page.query_selector(SEARCH_FORM["minute"])
            if minute_select:
                await minute_select.select_option(label=minute)
        
        return True
    except Exception:
        return False


async def execute_search(page: Page) -> SearchResult:
    """
    検索を実行して結果を取得
    
    Returns:
        SearchResult: 検索結果
    """
    try:
        # 「予約を続ける」ボタンをクリック
        continue_button = await page.query_selector(SEARCH_FORM["continue_button"])
        if continue_button:
            await continue_button.click()
        else:
            return SearchResult(
                success=False,
                message="「予約を続ける」ボタンが見つかりません",
            )
        
        # 検索結果を待機
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)
        
        # 結果を取得
        options = await parse_search_results(page)
        
        # スクリーンショット
        screenshot_path = f"ex_search_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        await page.screenshot(path=screenshot_path)
        
        if options:
            return SearchResult(
                success=True,
                message=f"{len(options)}件の列車が見つかりました",
                options=options,
                search_url=page.url,
                screenshot_path=screenshot_path,
            )
        else:
            return SearchResult(
                success=False,
                message="該当する列車が見つかりませんでした",
                search_url=page.url,
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
    """
    options: List[TrainOption] = []
    
    try:
        # 候補ラベルを取得（"候補 1 / 6" など）
        candidate_labels = await page.query_selector_all('generic:has-text("候補")')
        
        # 列車名（h3）を取得
        train_names = await page.query_selector_all('heading[level=3]')
        
        # 発時刻を取得
        departure_times = await page.query_selector_all('term:has-text("発")')
        
        # 着時刻を取得
        arrival_times = await page.query_selector_all('term:has-text("着")')
        
        # 候補数を判定
        num_candidates = len(train_names)
        
        for i in range(num_candidates):
            try:
                # 列車名
                train_name = ""
                if i < len(train_names):
                    train_name = await train_names[i].inner_text()
                
                # 発時刻
                dep_time = ""
                if i < len(departure_times):
                    dep_text = await departure_times[i].inner_text()
                    # "14時42分 発" から時刻を抽出
                    match = re.search(r'(\d+)時(\d+)分', dep_text)
                    if match:
                        dep_time = f"{match.group(1)}:{match.group(2)}"
                
                # 着時刻
                arr_time = ""
                if i < len(arrival_times):
                    arr_text = await arrival_times[i].inner_text()
                    match = re.search(r'(\d+)時(\d+)分', arr_text)
                    if match:
                        arr_time = f"{match.group(1)}:{match.group(2)}"
                
                option = TrainOption(
                    id=f"train_{i + 1}",
                    train_name=train_name.strip(),
                    departure_time=dep_time,
                    arrival_time=arr_time,
                    departure_station="",  # ヘッダーから取得
                    arrival_station="",
                    duration="",
                    available=True,
                )
                options.append(option)
                
            except Exception:
                continue
        
    except Exception:
        pass
    
    return options


async def select_train(page: Page, index: int = 0) -> bool:
    """
    列車候補を選択
    
    Args:
        page: Playwrightページ
        index: 候補インデックス（0始まり）
        
    Returns:
        True: 成功
        False: 失敗
    """
    try:
        # 「この候補を選択」ボタンを取得
        select_buttons = await page.query_selector_all(SEARCH_RESULT["select_candidate"])
        
        if index < len(select_buttons):
            await select_buttons[index].click()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(1000)
            return True
        
        return False
    except Exception:
        return False
