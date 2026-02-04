"""
EX予約 HTMLパーサー

設計原則:
1. CSSセレクタで構造的に抽出（正規表現ではなく）
2. 欠損値は明示的にNone/空文字（推測しない）
3. パース失敗時は詳細なログ

正規表現での文字列分割は壊れやすい。
Playwrightのlocator APIで構造的にアクセスする。
"""

import re
import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from playwright.async_api import Page, Locator

from app.executors.ex_reservation.models import TrainInfo, BookingInfo

logger = logging.getLogger(__name__)


# =============================================================================
# 検索結果パーサー
# =============================================================================

async def parse_search_results(page: Page) -> List[TrainInfo]:
    """
    検索結果ページから列車情報を抽出

    CSSセレクタで構造的にアクセスし、各候補の情報を取得する。

    Returns:
        List[TrainInfo]: 列車情報のリスト
    """
    trains: List[TrainInfo] = []

    try:
        # 候補ブロックを取得（.train_info_block や .candidate_block 等）
        # まずは「この候補を選択」ボタンの数で候補数を判定
        select_buttons = await page.locator('text="この候補を選択"').all()
        num_candidates = len(select_buttons)

        if num_candidates == 0:
            logger.warning("列車候補が見つかりません")
            return trains

        logger.info(f"列車候補数: {num_candidates}")

        # 各候補の情報を抽出
        # SmartEXの構造: 候補ごとにdiv.train_blockまたは類似の構造
        # h3で列車名、dtで時刻、空席状況はspan.ordinary_ico等

        # 方法1: 候補ラベル「候補 N / M」で区切られた領域を探す
        candidate_labels = await page.locator('text=/候補 \\d+ \\/ \\d+/').all()

        if candidate_labels:
            # 候補ラベルの親要素から情報を取得
            for i, label in enumerate(candidate_labels):
                train = await _parse_candidate_from_label(page, label, i)
                if train:
                    trains.append(train)
                    logger.info(
                        f"  [{i}] {train.train_name} "
                        f"{train.departure_time}発 → {train.arrival_time}着 "
                        f"(空席: {'○' if train.available else '×'})"
                    )
        else:
            # 方法2: HTMLを直接パースするフォールバック
            trains = await _parse_candidates_from_html(page, num_candidates)

    except Exception as e:
        logger.error(f"検索結果パースエラー: {e}", exc_info=True)

    return trains


async def _parse_candidate_from_label(
    page: Page, label: Locator, index: int
) -> Optional[TrainInfo]:
    """
    候補ラベルの近くから列車情報を抽出

    候補ラベル「候補 1 / 6」の周辺要素から情報を取得する。
    """
    try:
        # 親要素を上にたどる（候補ブロック全体を取得）
        # 通常は3-5階層上に候補ブロックがある
        parent = label
        for _ in range(5):
            parent = parent.locator('..')

        # 親要素のHTMLを取得してパース
        html = await parent.inner_html()
        return _extract_train_from_html(html, index)

    except Exception as e:
        logger.warning(f"候補ラベルからのパース失敗 [{index}]: {e}")
        return None


async def _parse_candidates_from_html(page: Page, num_candidates: int) -> List[TrainInfo]:
    """
    HTMLを直接パースして列車情報を抽出（フォールバック）

    CSSセレクタで取得できない場合の代替手段。
    """
    trains: List[TrainInfo] = []

    try:
        html = await page.content()

        # 「候補」で分割（最初の要素はヘッダー部分なので除外）
        blocks = html.split('候補')

        # 各候補ブロックを処理
        for i in range(min(num_candidates, len(blocks) - 1)):
            block = blocks[i + 1]  # 最初の要素はスキップ
            train = _extract_train_from_html(block, i)
            if train:
                trains.append(train)
                logger.info(
                    f"  [{i}] {train.train_name} "
                    f"{train.departure_time}発 → {train.arrival_time}着 "
                    f"(空席: {'○' if train.available else '×'})"
                )

    except Exception as e:
        logger.error(f"HTMLパースエラー: {e}", exc_info=True)

    return trains


def _extract_train_from_html(html: str, index: int) -> Optional[TrainInfo]:
    """
    HTMLブロックから列車情報を抽出

    Args:
        html: 候補ブロックのHTML
        index: 候補インデックス

    Returns:
        TrainInfo or None
    """
    # 列車名を抽出（h3タグ）
    train_name = _extract_pattern(html, r'<h3[^>]*>([^<]+)</h3>')

    # 出発時刻を抽出
    # パターン1: <dt>19時02分 発</dt>
    # パターン2: <span class="time">19:02</span>
    departure_time = (
        _extract_pattern(html, r'<dt[^>]*>(\d+時\d+分)\s*発</dt>') or
        _extract_pattern(html, r'(\d{1,2}:\d{2})\s*発') or
        _extract_pattern(html, r'(\d{1,2}時\d{1,2}分)\s*発')
    )

    # 到着時刻を抽出
    # パターン1: <dt>21時30分 着</dt>
    # パターン2: <span class="time">21:30</span>
    arrival_time = (
        _extract_pattern(html, r'<dt[^>]*>(\d+時\d+分)\s*着</dt>') or
        _extract_pattern(html, r'(\d{1,2}:\d{2})\s*着') or
        _extract_pattern(html, r'(\d{1,2}時\d{1,2}分)\s*着')
    )

    # 空席状況を抽出
    # 普通車アイコンの後の○×を確認
    available = True
    seat_match = re.search(r'<span[^>]*class="[^"]*ordinary[^"]*"[^>]*></span>[^○×−]*([○×−])', html)
    if seat_match:
        available = (seat_match.group(1) == '○')
    else:
        # 代替パターン: 普通車：○ のようなテキスト
        alt_match = re.search(r'普通車[^○×−]*([○×−])', html)
        if alt_match:
            available = (alt_match.group(1) == '○')

    # 到着時刻が取れない場合、追加パターンを試す
    if not arrival_time:
        # dd要素の中に時刻がある場合
        arrival_time = _extract_pattern(html, r'着[^<]*<[^>]*>(\d+時\d+分)')
        if not arrival_time:
            # 2つ目の時刻表示を取得
            times = re.findall(r'(\d{1,2}[時:]\d{1,2}分?)', html)
            if len(times) >= 2:
                arrival_time = times[1]

    # 最低限の情報がなければNone
    if not train_name and not departure_time:
        return None

    return TrainInfo(
        index=index,
        train_name=train_name or f"列車候補 {index + 1}",
        departure_time=departure_time or "",
        arrival_time=arrival_time or "",
        available=available,
    )


def _extract_pattern(html: str, pattern: str) -> Optional[str]:
    """
    正規表現でパターンを抽出

    Args:
        html: 検索対象のHTML
        pattern: 正規表現パターン（グループ1を返す）

    Returns:
        マッチした文字列 or None
    """
    match = re.search(pattern, html, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


# =============================================================================
# 確認画面パーサー
# =============================================================================

async def parse_confirmation_page(page: Page) -> Optional[BookingInfo]:
    """
    最終確認画面から予約情報を抽出

    Returns:
        BookingInfo or None
    """
    try:
        # 「まだ予約は完了していません」の確認
        not_complete = await page.locator('text="まだ予約は完了していません"').count()
        if not_complete == 0:
            logger.warning("確認画面ではない可能性があります")

        # HTMLを取得
        html = await page.content()

        # 列車名を抽出
        train_name = _extract_pattern(html, r'<h3[^>]*>([^<]+)</h3>')

        # 出発時刻
        departure_time = _extract_pattern(html, r'(\d+時\d+分)\s*発')

        # 到着時刻
        arrival_time = _extract_pattern(html, r'(\d+時\d+分)\s*着')

        # 駅名を抽出
        departure_station = _extract_pattern(html, r'<dd[^>]*>([^<]+)</dd>\s*<dt[^>]*>\d+時\d+分\s*発')
        arrival_station = _extract_pattern(html, r'着</dt>\s*<dd[^>]*>([^<]+)</dd>')

        # 日付を抽出
        date = _extract_pattern(html, r'(\d{4}年\d{1,2}月\d{1,2}日)')

        # 座席情報を抽出（例: 5号車 3番A席, 3号車12A）
        seat_info = (
            _extract_pattern(html, r'(\d+号車\s*\d+番[A-E]席)') or  # 5号車 3番A席
            _extract_pattern(html, r'(\d+号車\s*\d+[A-E])') or       # 3号車12A
            ""
        )

        # 価格を抽出
        price = 0
        price_match = re.search(r'合計[^￥]*￥([0-9,]+)', html)
        if price_match:
            price = int(price_match.group(1).replace(',', ''))
        else:
            # 代替: 最後の価格表示
            prices = re.findall(r'￥([0-9,]+)', html)
            if prices:
                price = int(prices[-1].replace(',', ''))

        if not train_name:
            return None

        return BookingInfo(
            train_name=train_name,
            departure_time=departure_time or "",
            arrival_time=arrival_time or "",
            departure_station=departure_station or "",
            arrival_station=arrival_station or "",
            date=date or "",
            seat_info=seat_info,
            price=price,
        )

    except Exception as e:
        logger.error(f"確認画面パースエラー: {e}", exc_info=True)
        return None


# =============================================================================
# 購入完了画面パーサー
# =============================================================================

async def parse_purchase_complete(page: Page) -> Optional[str]:
    """
    購入完了画面から予約番号を抽出

    Returns:
        予約番号 or None
    """
    try:
        # 「予約が完了しました」の確認
        complete = await page.locator('text="予約が完了しました"').count()
        if complete == 0:
            complete = await page.locator('text="予約完了"').count()
        if complete == 0:
            logger.warning("完了画面ではない可能性があります")
            return None

        # HTMLを取得
        html = await page.content()

        # 予約番号を抽出
        # パターン: 予約番号：XXXX-XXXX-XXXX または 予約番号:XXXX
        reservation_number = _extract_pattern(
            html,
            r'予約番号[：:]\s*([A-Z0-9\-]+)'
        )

        return reservation_number

    except Exception as e:
        logger.error(f"完了画面パースエラー: {e}", exc_info=True)
        return None


# =============================================================================
# 予約一覧パーサー
# =============================================================================

@dataclass
class ReservationSummary:
    """予約一覧の各項目"""
    index: int
    reservation_number: str
    train_name: str
    date: str
    departure_time: str
    arrival_time: str
    departure_station: str
    arrival_station: str
    status: str  # 予約済み, 乗車済み, 払戻済み, etc.


async def parse_reservation_list(page: Page) -> List[ReservationSummary]:
    """
    予約一覧ページから予約リストを抽出

    Returns:
        List[ReservationSummary]: 予約一覧
    """
    reservations: List[ReservationSummary] = []

    try:
        # 予約カードを取得
        cards = await page.locator('.reservation_card, .rsv_card, [class*="reservation"]').all()

        if not cards:
            # フォールバック: HTMLをパース
            html = await page.content()
            return _parse_reservations_from_html(html)

        for i, card in enumerate(cards):
            try:
                card_html = await card.inner_html()

                reservation = ReservationSummary(
                    index=i,
                    reservation_number=_extract_pattern(card_html, r'予約番号[：:]\s*([A-Z0-9\-]+)') or "",
                    train_name=_extract_pattern(card_html, r'<h3[^>]*>([^<]+)</h3>') or "",
                    date=_extract_pattern(card_html, r'(\d{4}年\d{1,2}月\d{1,2}日)') or "",
                    departure_time=_extract_pattern(card_html, r'(\d+時\d+分)\s*発') or "",
                    arrival_time=_extract_pattern(card_html, r'(\d+時\d+分)\s*着') or "",
                    departure_station="",
                    arrival_station="",
                    status=_extract_pattern(card_html, r'(予約済み|乗車済み|払戻済み|キャンセル済み)') or "予約済み",
                )
                reservations.append(reservation)

            except Exception as e:
                logger.warning(f"予約カード [{i}] のパース失敗: {e}")

    except Exception as e:
        logger.error(f"予約一覧パースエラー: {e}", exc_info=True)

    return reservations


def _parse_reservations_from_html(html: str) -> List[ReservationSummary]:
    """HTMLから予約一覧を抽出（フォールバック）"""
    reservations: List[ReservationSummary] = []

    # 予約番号で分割
    blocks = re.split(r'予約番号[：:]', html)

    for i, block in enumerate(blocks[1:]):  # 最初の要素はスキップ
        rsv_num_match = re.match(r'\s*([A-Z0-9\-]+)', block)
        if not rsv_num_match:
            continue

        reservation = ReservationSummary(
            index=i,
            reservation_number=rsv_num_match.group(1),
            train_name=_extract_pattern(block, r'<h3[^>]*>([^<]+)</h3>') or "",
            date=_extract_pattern(block, r'(\d{4}年\d{1,2}月\d{1,2}日)') or "",
            departure_time=_extract_pattern(block, r'(\d+時\d+分)\s*発') or "",
            arrival_time=_extract_pattern(block, r'(\d+時\d+分)\s*着') or "",
            departure_station="",
            arrival_station="",
            status="予約済み",
        )
        reservations.append(reservation)

    return reservations


# =============================================================================
# ユーティリティ
# =============================================================================

def normalize_time(time_str: str) -> str:
    """
    時刻を統一形式に変換

    "19時02分" → "19:02"
    "19:02" → "19:02"
    """
    if not time_str:
        return ""

    if "時" in time_str and "分" in time_str:
        match = re.match(r'(\d+)時(\d+)分', time_str)
        if match:
            h, m = match.groups()
            return f"{int(h):02d}:{int(m):02d}"

    return time_str


def parse_price(price_str: str) -> int:
    """
    価格文字列を整数に変換

    "￥15,820" → 15820
    "15820" → 15820
    """
    if not price_str:
        return 0

    # 数字以外を除去
    digits = re.sub(r'[^\d]', '', price_str)
    return int(digits) if digits else 0
