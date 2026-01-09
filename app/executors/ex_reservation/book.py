"""
EX予約 予約実行処理

実確認日: 2026/01/09
- 商品選択
- 座席選択
- 確認画面まで（購入はしない）
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from app.executors.ex_reservation.selectors import PRODUCT_SELECT, CONFIRMATION


@dataclass
class BookingResult:
    """予約結果"""
    success: bool
    message: str
    train_name: Optional[str] = None
    seat_info: Optional[str] = None
    price: Optional[int] = None
    screenshot_path: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


async def select_product(
    page: Page,
    product_type: str = "regular",  # "regular", "green", "free"
) -> BookingResult:
    """
    商品（座席タイプ）を選択
    
    Args:
        page: Playwrightページ
        product_type: 商品タイプ
            - "regular": 普通車指定席（スマートEX）
            - "green": グリーン車
            - "free": 自由席
            
    Returns:
        BookingResult: 結果
    """
    try:
        # 商品を選択
        if product_type == "regular":
            # 普通車指定席（スマートEX）の価格表示をクリック
            # 「￥11,100」などの価格をクリック
            price_elements = await page.query_selector_all('generic:has-text("￥"):has-text("○")')
            if price_elements and len(price_elements) > 0:
                await price_elements[0].click()
            else:
                return BookingResult(
                    success=False,
                    message="普通車指定席が見つかりません",
                )
        
        elif product_type == "green":
            price_elements = await page.query_selector_all('generic:has-text("￥"):has-text("○")')
            if price_elements and len(price_elements) > 1:
                await price_elements[1].click()  # 2番目がグリーン車
            else:
                return BookingResult(
                    success=False,
                    message="グリーン車が見つかりません",
                )
        
        elif product_type == "free":
            free_seat = await page.query_selector('generic:has-text("自由席"):has-text("￥")')
            if free_seat:
                await free_seat.click()
            else:
                return BookingResult(
                    success=False,
                    message="自由席が見つかりません",
                )
        
        await page.wait_for_timeout(1000)
        
        return BookingResult(
            success=True,
            message=f"商品を選択しました: {product_type}",
        )
        
    except Exception as e:
        return BookingResult(
            success=False,
            message=f"商品選択エラー: {str(e)}",
        )


async def select_seat_position(
    page: Page,
    position: str = "指定なし",
) -> BookingResult:
    """
    座席位置を選択
    
    Args:
        page: Playwrightページ
        position: 座席位置
            - "指定なし"
            - "窓 側（普A／グA）"
            - "中 央（普B）"
            - "通路側（普C／グB）"
            - "通路側（普D／グC）"
            - "窓 側（普E／グD）"
            
    Returns:
        BookingResult: 結果
    """
    try:
        seat_select = await page.query_selector(PRODUCT_SELECT["seat_position"])
        if seat_select:
            await seat_select.select_option(label=position)
            return BookingResult(
                success=True,
                message=f"座席位置を選択しました: {position}",
            )
        else:
            return BookingResult(
                success=False,
                message="座席位置選択が見つかりません",
            )
    except Exception as e:
        return BookingResult(
            success=False,
            message=f"座席位置選択エラー: {str(e)}",
        )


async def proceed_to_confirmation(page: Page) -> BookingResult:
    """
    確認画面へ進む
    
    Returns:
        BookingResult: 結果（確認画面の情報を含む）
    """
    try:
        # 「予約を続ける」ボタンをクリック
        continue_button = await page.query_selector(PRODUCT_SELECT["continue_button"])
        if continue_button:
            await continue_button.click()
        else:
            return BookingResult(
                success=False,
                message="「予約を続ける」ボタンが見つかりません",
            )
        
        # 確認画面を待機
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)
        
        # 確認画面かどうかチェック
        not_complete = await page.query_selector(CONFIRMATION["not_complete_heading"])
        if not not_complete:
            return BookingResult(
                success=False,
                message="確認画面に到達できませんでした",
            )
        
        # 確認画面の情報を取得
        info = await get_confirmation_info(page)
        
        # スクリーンショット
        screenshot_path = f"ex_confirm_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        await page.screenshot(path=screenshot_path)
        
        return BookingResult(
            success=True,
            message="確認画面に到達しました。購入は手動で行ってください。",
            train_name=info.get("train_name"),
            seat_info=info.get("seat_info"),
            price=info.get("price"),
            screenshot_path=screenshot_path,
            details=info,
        )
        
    except PlaywrightTimeout:
        screenshot_path = f"error_ex_confirm_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        try:
            await page.screenshot(path=screenshot_path)
        except Exception:
            pass
        
        return BookingResult(
            success=False,
            message="タイムアウト: 確認画面への遷移に失敗しました",
            screenshot_path=screenshot_path,
        )
    except Exception as e:
        return BookingResult(
            success=False,
            message=f"確認画面遷移エラー: {str(e)}",
        )


async def get_confirmation_info(page: Page) -> Dict[str, Any]:
    """
    確認画面から情報を取得
    
    Returns:
        Dict: 予約情報
    """
    info: Dict[str, Any] = {}
    
    try:
        # 列車名
        train_name_elem = await page.query_selector(CONFIRMATION["train_name"])
        if train_name_elem:
            info["train_name"] = await train_name_elem.inner_text()
        
        # 座席情報
        seat_elem = await page.query_selector(CONFIRMATION["seat_info"])
        if seat_elem:
            info["seat_info"] = await seat_elem.inner_text()
        
        # 金額
        price_elem = await page.query_selector(CONFIRMATION["price"])
        if price_elem:
            price_text = await price_elem.inner_text()
            # "￥11,100" から数値を抽出
            import re
            match = re.search(r'(\d{1,3}(?:,\d{3})*)', price_text)
            if match:
                info["price"] = int(match.group(1).replace(',', ''))
        
    except Exception:
        pass
    
    return info


async def go_back(page: Page) -> bool:
    """
    戻る
    
    Returns:
        True: 成功
        False: 失敗
    """
    try:
        back_link = await page.query_selector(CONFIRMATION["back_link"])
        if back_link:
            await back_link.click()
            await page.wait_for_load_state("domcontentloaded")
            return True
        
        back_button = await page.query_selector('button:has-text("戻る")')
        if back_button:
            await back_button.click()
            await page.wait_for_load_state("domcontentloaded")
            return True
        
        return False
    except Exception:
        return False


# ※ 購入処理は実装しない（安全のため）
# async def purchase(page: Page) -> BookingResult:
#     """
#     購入を実行（※実装しない）
#     """
#     raise NotImplementedError("購入処理は安全のため実装していません")

