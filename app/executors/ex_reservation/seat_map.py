"""
EX予約 座席表機能

座席表を表示して空席状況を確認し、特定の席を選択する機能。
"""

import base64
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Tuple

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)


async def _capture_screenshot_base64(page: Page, full_page: bool = False) -> Optional[str]:
    """
    スクリーンショットをbase64で取得（Vision API用）

    Args:
        page: Playwrightページ
        full_page: True=ページ全体、False=表示領域のみ

    Returns:
        base64エンコードされた画像文字列、失敗時はNone
    """
    try:
        screenshot_bytes = await page.screenshot(full_page=full_page)
        return base64.b64encode(screenshot_bytes).decode('utf-8')
    except Exception as e:
        logger.error(f"スクリーンショット取得エラー: {e}")
        return None


@dataclass
class SeatMapInfo:
    """座席表情報"""
    car_number: int  # 号車番号
    available_seats: List[str] = field(default_factory=list)  # 空席リスト ["3A", "5B"]
    seat_layout: Dict[str, str] = field(default_factory=dict)  # {"3A": "○", "3B": "×"}
    screenshot_path: Optional[str] = None
    screenshot_base64: Optional[str] = None  # Vision API用
    total_rows: int = 0  # 座席の行数


# 新幹線座席配置（普通車）
# A-B-C | D-E (2+3配列)
# A: 窓側, B: 中央, C: 通路側, D: 通路側, E: 窓側
SEAT_ADJACENCY = {
    "A": ["B"],       # A席の隣はB席
    "B": ["A", "C"],  # B席の隣はA席とC席
    "C": ["B"],       # C席の隣はB席
    "D": ["E"],       # D席の隣はE席
    "E": ["D"],       # E席の隣はD席
}

# 座席タイプ
SEAT_TYPES = {
    "A": "窓側",
    "B": "中央",
    "C": "通路側",
    "D": "通路側",
    "E": "窓側",
}


@dataclass
class OpenSeatMapResult:
    """座席表を開いた結果"""
    success: bool
    screenshot_base64: Optional[str] = None
    message: str = ""


async def open_seat_map(page: Page, capture_screenshot: bool = True) -> OpenSeatMapResult:
    """
    座席表を開く

    Args:
        page: Playwrightページ
        capture_screenshot: スクリーンショットを撮影するか

    Returns:
        OpenSeatMapResult: 結果（スクショ含む）
    """
    try:
        # 検証済みセレクタ
        btn = page.locator('button.seat_map_button').first
        if await btn.count() > 0:
            await btn.click()
            await page.wait_for_timeout(3000)
            logger.info("座席表を開きました")

            # 決定ポイント: 座席表が開いた（ダンがこの画面を見る）
            screenshot_b64 = None
            if capture_screenshot:
                screenshot_b64 = await _capture_screenshot_base64(page)
                logger.info("[VISION] 座席表スクリーンショットを撮影しました")

            return OpenSeatMapResult(
                success=True,
                screenshot_base64=screenshot_b64,
                message="座席表を開きました",
            )

        logger.warning("座席表ボタンが見つかりませんでした")
        return OpenSeatMapResult(success=False, message="座席表ボタンが見つかりません")

    except Exception as e:
        logger.error(f"座席表を開く際にエラー: {e}")
        return OpenSeatMapResult(success=False, message=str(e))


async def get_seat_map_info(page: Page) -> Optional[SeatMapInfo]:
    """
    座席表から空席情報を取得

    Args:
        page: Playwrightページ

    Returns:
        SeatMapInfo: 座席表情報、失敗時はNone
    """
    try:
        # 号車番号を取得
        car_number = await _get_current_car_number(page)

        # 座席情報を取得
        seat_layout = {}
        available_seats = []

        # 座席表テーブルから座席セルを取得
        # セルIDパターン: [A-E]-[1-20] (例: A-19, B-5)
        for letter in ['A', 'B', 'C', 'D', 'E']:
            for num in range(1, 21):
                seat_id = f"{letter}-{num}"
                cell = page.locator(f'td#{seat_id}')

                if await cell.count() > 0:
                    try:
                        text = (await cell.text_content() or "").strip()
                        class_attr = await cell.get_attribute("class") or ""

                        # 空席判定: disabledクラスがない = 空席
                        is_available = "disabled" not in class_attr and "○" in text

                        # 座席IDを "番号+列" 形式に変換 (例: "19A")
                        normalized_id = f"{num}{letter}"
                        seat_layout[normalized_id] = "○" if is_available else "×"

                        if is_available:
                            available_seats.append(normalized_id)

                    except Exception as e:
                        logger.debug(f"座席セル {seat_id} 解析エラー: {e}")
                        continue

        # スクリーンショット（ファイル保存＆base64）
        screenshot_path = f"ex_seat_map_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        await page.screenshot(path=screenshot_path)
        screenshot_b64 = await _capture_screenshot_base64(page)

        # 行数を計算
        total_rows = 20  # 新幹線は最大20列

        logger.info(f"座席表取得: {car_number}号車, 空席数={len(available_seats)}")

        return SeatMapInfo(
            car_number=car_number,
            available_seats=sorted(available_seats, key=_seat_sort_key),
            seat_layout=seat_layout,
            screenshot_path=screenshot_path,
            screenshot_base64=screenshot_b64,
            total_rows=total_rows,
        )

    except Exception as e:
        logger.error(f"座席表情報取得エラー: {e}")
        return None


async def _get_current_car_number(page: Page) -> int:
    """現在表示中の号車番号を取得"""
    try:
        # JavaScriptで号車番号を取得
        car_number = await page.evaluate("""
            () => {
                // 1. h3タグ内の「普通 14号車」のようなテキストから取得
                const heading = document.querySelector('.seat-select h3 span');
                if (heading) {
                    const match = heading.textContent.match(/(\\d+)号車/);
                    if (match) return parseInt(match[1]);
                }

                // 2. 号車選択セレクタのselected optionから取得
                const select = document.querySelector('#pc-sel1');
                if (select) {
                    const selectedOption = select.options[select.selectedIndex];
                    if (selectedOption) {
                        const match = selectedOption.textContent.match(/(\\d+)号車/);
                        if (match) return parseInt(match[1]);
                    }
                }

                return null;
            }
        """)

        if car_number:
            return car_number

    except Exception as e:
        logger.debug(f"号車番号取得エラー: {e}")

    return 1  # デフォルト


async def _parse_seat_map_text(page: Page) -> Tuple[Dict[str, str], List[str]]:
    """テキストベースで座席表を解析"""
    seat_layout = {}
    available_seats = []

    try:
        # ページ全体のテキストから座席情報を抽出
        content = await page.content()

        # パターン: "3A: ○" や "3A ○" など
        pattern = r'(\d+[A-E])\s*[:\s]?\s*([○×])'
        matches = re.findall(pattern, content)

        for seat_id, status in matches:
            seat_layout[seat_id] = status
            if status == "○":
                available_seats.append(seat_id)

    except Exception as e:
        logger.debug(f"テキスト解析エラー: {e}")

    return seat_layout, available_seats


def _seat_sort_key(seat: str) -> Tuple[int, str]:
    """座席のソートキー（行番号、席名順）"""
    match = re.match(r'(\d+)([A-E])', seat)
    if match:
        return (int(match.group(1)), match.group(2))
    return (999, seat)


@dataclass
class ChangeCarResult:
    """号車変更結果"""
    success: bool
    car_number: int
    screenshot_base64: Optional[str] = None
    message: str = ""


async def change_car_number(
    page: Page,
    car_number: int,
    capture_screenshot: bool = True,
) -> ChangeCarResult:
    """
    号車を変更

    Args:
        page: Playwrightページ
        car_number: 変更先の号車番号
        capture_screenshot: スクリーンショットを撮影するか

    Returns:
        ChangeCarResult: 結果（スクショ含む）
    """
    try:
        # 号車選択セレクト: #pc-sel1
        # optionのvalue形式: "2,XX,1,00" (XXが号車番号、2桁ゼロ埋め)
        car_str = f"{car_number:02d}"  # 2桁ゼロ埋め

        # JavaScriptで該当号車のvalueを取得
        target_value = await page.evaluate(f"""
            () => {{
                const select = document.querySelector('#pc-sel1');
                if (!select) return null;

                const options = select.querySelectorAll('option');
                for (const opt of options) {{
                    const value = opt.value || '';
                    const text = opt.textContent || '';
                    // value形式: "2,03,1,00" や テキストに "3号車" を含む
                    if (value.includes(',{car_str},') || text.includes('{car_number}号車')) {{
                        return value;
                    }}
                }}
                return null;
            }}
        """)

        if target_value:
            car_select = page.locator('#pc-sel1')
            if await car_select.count() > 0:
                await car_select.select_option(value=target_value)
                await page.wait_for_timeout(3000)  # ページ再読み込みを待つ
                logger.info(f"{car_number}号車に変更しました")

                # 決定ポイント: 号車変更後（ダンがこの画面を見る）
                screenshot_b64 = None
                if capture_screenshot:
                    screenshot_b64 = await _capture_screenshot_base64(page)
                    logger.info(f"[VISION] {car_number}号車のスクリーンショットを撮影しました")

                return ChangeCarResult(
                    success=True,
                    car_number=car_number,
                    screenshot_base64=screenshot_b64,
                    message=f"{car_number}号車に変更しました",
                )

        logger.warning(f"号車変更ができませんでした: {car_number}号車")
        return ChangeCarResult(
            success=False,
            car_number=car_number,
            message=f"{car_number}号車に変更できませんでした",
        )

    except Exception as e:
        logger.error(f"号車変更エラー: {e}")
        return ChangeCarResult(
            success=False,
            car_number=car_number,
            message=str(e),
        )


async def select_seat_from_map(
    page: Page,
    car_number: int,
    row: int,
    letter: str,
) -> bool:
    """
    座席表から特定の席を選択

    Args:
        page: Playwrightページ
        car_number: 号車番号
        row: 行番号（例: 3）
        letter: 席記号（例: "A"）

    Returns:
        True: 成功, False: 失敗
    """
    try:
        letter = letter.upper()
        logger.info(f"座席選択: {car_number}号車 {row}番{letter}席")

        # まず号車を変更（必要な場合）
        current_car = await _get_current_car_number(page)
        if current_car != car_number:
            change_result = await change_car_number(page, car_number, capture_screenshot=False)
            if not change_result.success:
                return False

        # 座席セルのID形式: [A-E]-[番号] (例: A-19)
        cell_id = f"{letter}-{row}"
        cell = page.locator(f'td#{cell_id}')

        if await cell.count() == 0:
            logger.warning(f"座席セル {cell_id} が見つかりません")
            return False

        # 空席かチェック
        class_attr = await cell.get_attribute("class") or ""
        if "disabled" in class_attr:
            logger.warning(f"座席 {row}番{letter}席 は既に予約されています")
            return False

        # 座席セルをクリック
        await cell.click()
        await page.wait_for_timeout(500)

        # 選択されたか確認（セルに "selected" クラスが付くか、カウンターが更新される）
        updated_class = await cell.get_attribute("class") or ""
        counter = page.locator('#count_up')
        counter_text = await counter.text_content() if await counter.count() > 0 else ""

        logger.info(f"座席 {row}番{letter}席 を選択しました (counter: {counter_text})")
        return True

    except Exception as e:
        logger.error(f"座席選択エラー: {e}")
        return False


def find_seats_with_adjacent_empty(
    seat_layout: Dict[str, str],
    seat_position: Optional[str] = None,
) -> List[str]:
    """
    隣が空いている席を検索

    新幹線座席配置（普通車）:
    A-B-C | D-E (2+3配列)
    A: 窓側, B: 中央, C: 通路側, D: 通路側, E: 窓側

    Args:
        seat_layout: 座席状況 {"3A": "○", "3B": "×", ...}
        seat_position: 座席位置の希望（"窓側", "通路側", None）

    Returns:
        隣が空いている席のリスト（優先度順）
    """
    # 座席位置のフィルタ設定
    allowed_letters = None
    if seat_position:
        pos_lower = seat_position.lower()
        if "窓" in seat_position or "window" in pos_lower:
            allowed_letters = {"A", "E"}  # 窓側のみ
        elif "通路" in seat_position or "aisle" in pos_lower:
            allowed_letters = {"C", "D"}  # 通路側のみ
    result = []

    # 空席を行ごとにグループ化
    available_by_row: Dict[int, List[str]] = {}
    for seat_id, status in seat_layout.items():
        if status != "○":
            continue

        match = re.match(r'(\d+)([A-E])', seat_id)
        if not match:
            continue

        row = int(match.group(1))
        letter = match.group(2)

        if row not in available_by_row:
            available_by_row[row] = []
        available_by_row[row].append(letter)

    # 各空席について隣も空いているかチェック
    seats_with_adjacent = []

    for seat_id, status in seat_layout.items():
        if status != "○":
            continue

        match = re.match(r'(\d+)([A-E])', seat_id)
        if not match:
            continue

        row = int(match.group(1))
        letter = match.group(2)

        # 座席位置フィルタ（窓側/通路側指定がある場合）
        if allowed_letters and letter not in allowed_letters:
            continue

        # 隣の席をチェック
        adjacent_letters = SEAT_ADJACENCY.get(letter, [])
        adjacent_empty_count = 0

        for adj_letter in adjacent_letters:
            adj_seat = f"{row}{adj_letter}"
            if seat_layout.get(adj_seat) == "○":
                adjacent_empty_count += 1

        if adjacent_empty_count > 0:
            seats_with_adjacent.append({
                "seat_id": seat_id,
                "row": row,
                "letter": letter,
                "seat_type": SEAT_TYPES.get(letter, ""),
                "adjacent_empty": adjacent_empty_count,
            })

    # 優先度でソート:
    # 1. 隣の空席が多い順
    # 2. 窓側を優先（A, E）
    # 3. 行番号が小さい順
    def sort_key(s):
        is_window = s["letter"] in ("A", "E")
        return (-s["adjacent_empty"], not is_window, s["row"])

    seats_with_adjacent.sort(key=sort_key)

    return [s["seat_id"] for s in seats_with_adjacent]


def format_seat_info(seat_id: str, car_number: int = 0) -> str:
    """
    座席情報を日本語でフォーマット

    Args:
        seat_id: 座席ID（例: "3A"）
        car_number: 号車番号（0の場合は号車を省略）

    Returns:
        フォーマットされた座席情報（例: "5号車3番A席（窓側）"）
    """
    match = re.match(r'(\d+)([A-E])', seat_id)
    if not match:
        return seat_id

    row = match.group(1)
    letter = match.group(2)
    seat_type = SEAT_TYPES.get(letter, "")

    if car_number > 0:
        return f"{car_number}号車{row}番{letter}席（{seat_type}）"
    else:
        return f"{row}番{letter}席（{seat_type}）"


def parse_seat_specification(spec: str) -> Optional[Dict[str, any]]:
    """
    座席指定文字列をパース

    Args:
        spec: 座席指定（例: "5号車3番A席", "3A", "5号車3A"）

    Returns:
        パース結果 {"car_number": 5, "row": 3, "letter": "A"} またはNone
    """
    # パターン1: "5号車3番A席" または "5号車3A"
    pattern1 = r'(\d+)号車\s*(\d+)(?:番)?([A-Ea-e])(?:席)?'
    match = re.search(pattern1, spec)
    if match:
        return {
            "car_number": int(match.group(1)),
            "row": int(match.group(2)),
            "letter": match.group(3).upper(),
        }

    # パターン2: "3番A席" または "3A"
    pattern2 = r'(\d+)(?:番)?([A-Ea-e])(?:席)?'
    match = re.search(pattern2, spec)
    if match:
        return {
            "car_number": None,  # 号車未指定
            "row": int(match.group(1)),
            "letter": match.group(2).upper(),
        }

    return None


# ==============================================================================
# 全号車スキャン機能（Phase 2: 号車横断検索）
# ==============================================================================

@dataclass
class CarScanResult:
    """号車スキャン結果"""
    car_number: int
    has_matching_seats: bool
    matching_seats: List[str]  # 条件に合う座席リスト
    seat_map_info: Optional[SeatMapInfo] = None


async def get_all_car_numbers(page: Page) -> List[int]:
    """
    利用可能な全号車番号を取得

    Args:
        page: Playwrightページ（座席表が開いている状態）

    Returns:
        号車番号のリスト（例: [4, 5, 6, 7, 8, 9, 10]）
    """
    try:
        # JavaScriptで全号車番号を取得
        car_numbers = await page.evaluate("""
            () => {
                const select = document.querySelector('#pc-sel1');
                if (!select) return [];

                const cars = [];
                const options = select.querySelectorAll('option');
                for (const opt of options) {
                    const text = opt.textContent || '';
                    const match = text.match(/(\\d+)号車/);
                    if (match) {
                        cars.push(parseInt(match[1]));
                    }
                }
                return cars;
            }
        """)

        if car_numbers:
            logger.info(f"利用可能な号車: {sorted(car_numbers)}")
            return sorted(car_numbers)
        return []

    except Exception as e:
        logger.error(f"号車一覧取得エラー: {e}")
        return []


async def scan_car_for_conditions(
    page: Page,
    car_number: int,
    seat_position: Optional[str] = None,
    prefer_adjacent_empty: bool = False,
) -> CarScanResult:
    """
    指定した号車をスキャンして条件に合う座席を探す

    Args:
        page: Playwrightページ
        car_number: スキャンする号車番号
        seat_position: 座席位置の希望（"窓側E", "窓側A", "通路側C", "通路側D"）
        prefer_adjacent_empty: 隣が空いている席を優先

    Returns:
        CarScanResult: スキャン結果
    """
    try:
        # 号車を変更
        current_car = await _get_current_car_number(page)
        if current_car != car_number:
            change_result = await change_car_number(page, car_number, capture_screenshot=False)
            if not change_result.success:
                return CarScanResult(
                    car_number=car_number,
                    has_matching_seats=False,
                    matching_seats=[],
                )

        # 座席表情報を取得
        seat_map_info = await get_seat_map_info(page)
        if not seat_map_info or not seat_map_info.seat_layout:
            return CarScanResult(
                car_number=car_number,
                has_matching_seats=False,
                matching_seats=[],
            )

        # 条件に合う座席をフィルタ
        matching_seats = []

        # 座席位置フィルタを設定
        allowed_letters = None
        is_2col_request = False
        if seat_position:
            pos_lower = seat_position.lower()
            # 2列席（D-E）か3列席（A-B-C）かを判定
            if "e" in pos_lower:
                allowed_letters = {"E"}
                is_2col_request = True
            elif "d" in pos_lower:
                allowed_letters = {"D"}
                is_2col_request = True
            elif "a" in pos_lower and "窓" in seat_position:
                allowed_letters = {"A"}
            elif "b" in pos_lower or "中央" in seat_position:
                allowed_letters = {"B"}
            elif "c" in pos_lower:
                allowed_letters = {"C"}
            elif "窓" in seat_position:
                # 窓側全般: AまたはE
                allowed_letters = {"A", "E"}
            elif "通路" in seat_position:
                # 通路側全般: CまたはD
                allowed_letters = {"C", "D"}

        # 隣空席優先の場合
        if prefer_adjacent_empty:
            adjacent_seats = find_seats_with_adjacent_empty(
                seat_map_info.seat_layout,
                seat_position=seat_position,
            )
            if adjacent_seats:
                # さらに座席位置でフィルタ
                if allowed_letters:
                    matching_seats = [
                        s for s in adjacent_seats
                        if s[-1] in allowed_letters
                    ]
                else:
                    matching_seats = adjacent_seats
        else:
            # 空席から座席位置でフィルタ
            for seat_id in seat_map_info.available_seats:
                match = re.match(r'(\d+)([A-E])', seat_id)
                if match:
                    letter = match.group(2)
                    if allowed_letters is None or letter in allowed_letters:
                        matching_seats.append(seat_id)

        has_matching = len(matching_seats) > 0
        logger.info(f"{car_number}号車スキャン: 条件合致={has_matching}, 件数={len(matching_seats)}")

        return CarScanResult(
            car_number=car_number,
            has_matching_seats=has_matching,
            matching_seats=matching_seats[:10],  # 最大10件
            seat_map_info=seat_map_info,
        )

    except Exception as e:
        logger.error(f"{car_number}号車スキャンエラー: {e}")
        return CarScanResult(
            car_number=car_number,
            has_matching_seats=False,
            matching_seats=[],
        )


@dataclass
class AllCarsScanResult:
    """全号車スキャン結果"""
    scanned_cars: List[int]
    best_car: Optional[int] = None
    best_seats: List[str] = field(default_factory=list)
    all_results: Dict[int, CarScanResult] = field(default_factory=dict)
    no_matching_seats_anywhere: bool = False


async def scan_all_cars_for_seat(
    page: Page,
    seat_position: Optional[str] = None,
    prefer_adjacent_empty: bool = False,
    max_cars_to_scan: int = 16,
    scan_all: bool = True,
) -> AllCarsScanResult:
    """
    全号車をスキャンして条件に合う座席を探す

    第一原理:
    - 全号車をスキャンして状況を完全に把握する
    - 条件に合う席がある号車を全てリストアップ
    - 最適な号車を選択

    Args:
        page: Playwrightページ（座席表が開いている状態）
        seat_position: 座席位置の希望
        prefer_adjacent_empty: 隣が空いている席を優先
        max_cars_to_scan: スキャンする最大号車数
        scan_all: Trueなら見つかっても全号車をスキャン（状況把握のため）

    Returns:
        AllCarsScanResult: 全号車スキャン結果
    """
    logger.info(f"[SCAN] 全号車スキャン開始: position={seat_position}, adjacent_empty={prefer_adjacent_empty}")

    # 利用可能な号車を取得
    all_cars = await get_all_car_numbers(page)
    if not all_cars:
        logger.warning("[SCAN] 利用可能な号車がありません")
        return AllCarsScanResult(
            scanned_cars=[],
            no_matching_seats_anywhere=True,
        )

    logger.info(f"[SCAN] 利用可能な号車: {all_cars}")

    # 現在の号車を最初にスキャン（既に開いている可能性が高い）
    current_car = await _get_current_car_number(page)
    cars_to_scan = [current_car] if current_car in all_cars else []
    cars_to_scan.extend([c for c in all_cars if c != current_car])
    cars_to_scan = cars_to_scan[:max_cars_to_scan]

    all_results: Dict[int, CarScanResult] = {}
    cars_with_matches: List[Tuple[int, int, List[str]]] = []  # (号車, 席数, 席リスト)

    # 全号車をスキャン
    for car_num in cars_to_scan:
        result = await scan_car_for_conditions(
            page,
            car_num,
            seat_position=seat_position,
            prefer_adjacent_empty=prefer_adjacent_empty,
        )
        all_results[car_num] = result

        if result.has_matching_seats:
            cars_with_matches.append((car_num, len(result.matching_seats), result.matching_seats))
            logger.info(f"[SCAN] {car_num}号車: 条件合致 {len(result.matching_seats)}席 {result.matching_seats[:3]}")
        else:
            logger.info(f"[SCAN] {car_num}号車: 条件に合う席なし")

    # 結果サマリーをログ出力
    logger.info(f"[SCAN] === スキャン完了 ===")
    logger.info(f"[SCAN] スキャン済み: {len(cars_to_scan)}号車")

    if cars_with_matches:
        # 席数が多い順にソート
        cars_with_matches.sort(key=lambda x: -x[1])
        best_car = cars_with_matches[0][0]
        best_seats = cars_with_matches[0][2]

        summary = ", ".join([f"{c}号車({n}席)" for c, n, _ in cars_with_matches])
        logger.info(f"[SCAN] 条件合致: {summary}")
        logger.info(f"[SCAN] 推奨: {best_car}号車 ({len(best_seats)}席)")
    else:
        best_car = None
        best_seats = []
        logger.warning(f"[SCAN] 全{len(cars_to_scan)}号車をスキャンしましたが、条件に合う座席が見つかりませんでした")
        # スキャンした号車を明示
        scanned_str = ", ".join([f"{c}号車" for c in cars_to_scan])
        logger.warning(f"[SCAN] スキャン済み号車: {scanned_str}")

    return AllCarsScanResult(
        scanned_cars=cars_to_scan,
        best_car=best_car,
        best_seats=best_seats,
        all_results=all_results,
        no_matching_seats_anywhere=best_car is None,
    )
