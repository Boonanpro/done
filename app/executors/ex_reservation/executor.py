"""
EX予約 メインExecutor

実確認日: 2026/01/09
各アクション（login, search, book）を組み合わせて実行
"""

from typing import Optional, Dict, Any, List
from datetime import datetime

from playwright.async_api import TimeoutError as PlaywrightTimeout

from app.models.schemas import ExecutionResult, SearchResult as TaskSearchResult
from app.executors.base import BaseExecutor, ExecutorSearchResult, SearchOption
from app.tools.browser import get_page, take_screenshot

from app.executors.ex_reservation.selectors import URLS, MYPAGE
from app.executors.ex_reservation.login import login, check_logged_in, complete_otp_authentication
from app.executors.ex_reservation.search import (
    open_search_form,
    fill_search_form,
    execute_search,
    select_train,
    TrainOption,
)
from app.executors.ex_reservation.book import (
    select_product,
    select_seat_position,
    proceed_to_confirmation,
    go_back,
)


class EXReservationExecutor(BaseExecutor):
    """EX予約（新幹線）実行ロジック"""
    
    service_type = "train"
    service_name = "ex_reservation"
    service_display_name = "EX予約（新幹線）"
    
    # OTPが必要な場合がある
    REQUIRES_OTP = True
    
    async def _do_search(
        self,
        params: Dict[str, Any],
        credentials: Optional[Dict[str, str]] = None,
    ) -> ExecutorSearchResult:
        """
        SmartEXで新幹線の空席を検索
        
        Args:
            params: 検索パラメータ
                - departure: 出発駅（例: 東 京）
                - arrival: 到着駅（例: 名古屋）
                - date: 日付（YYYY-MM-DD）
                - time: 時刻（HH:MM）
                
        Returns:
            ExecutorSearchResult: 検索結果
        """
        page = await get_page()
        options: List[SearchOption] = []
        
        try:
            departure = params.get("departure", "東 京")
            arrival = params.get("arrival", "名古屋")
            date = params.get("date", "")
            time = params.get("time", "")
            
            print(f"[EX_SEARCH] Starting search: {departure} → {arrival}")
            
            await self._notify_progress("connect", f"{self.service_display_name}にアクセス中...")
            
            # Step 1: ログイン確認・実行
            if not await check_logged_in(page):
                if not credentials:
                    return ExecutorSearchResult(
                        success=False,
                        options=[],
                        message="ログイン情報が必要です",
                    )
                
                await self._notify_progress("login", "ログイン中...")
                
                login_result = await login(
                    page,
                    credentials.get("member_id", credentials.get("email", "")),
                    credentials.get("password", ""),
                )
                
                if login_result.requires_otp:
                    # OTPが必要な場合
                    return ExecutorSearchResult(
                        success=False,
                        options=[],
                        message="電話認証（OTP）が必要です。登録済み電話番号に着信があります。",
                    )
                
                if not login_result.success:
                    return ExecutorSearchResult(
                        success=False,
                        options=[],
                        message=login_result.message,
                    )
            
            # Step 2: 検索フォームを開く
            await self._notify_progress("form", "検索フォームを開いています...")
            await open_search_form(page)
            
            # Step 3: 検索条件を入力
            await self._notify_progress("input", f"検索条件を入力中... {departure}→{arrival}")
            
            # 時刻を分解
            hour = None
            minute = None
            if time and ":" in time:
                parts = time.split(":")
                hour = f"{parts[0]}時"
                minute = f"{parts[1]}分"
            
            await fill_search_form(page, departure, arrival, hour, minute)
            
            # Step 4: 検索実行
            await self._notify_progress("search", "列車を検索中...")
            search_result = await execute_search(page)
            
            if not search_result.success:
                return ExecutorSearchResult(
                    success=False,
                    options=[],
                    message=search_result.message,
                    screenshot_path=search_result.screenshot_path,
                )
            
            # Step 5: 結果を変換
            for train in search_result.options:
                options.append(SearchOption(
                    id=train.id,
                    title=train.train_name,
                    description=f"{train.departure_time}発 → {train.arrival_time}着",
                    price=train.price,
                    available=train.available,
                    details={
                        "departure_time": train.departure_time,
                        "arrival_time": train.arrival_time,
                        "departure_station": departure,
                        "arrival_station": arrival,
                        "date": date,
                    },
                ))
            
            return ExecutorSearchResult(
                success=True,
                options=options,
                message=f"{len(options)}件の列車が見つかりました",
                search_url=search_result.search_url,
                screenshot_path=search_result.screenshot_path,
            )
            
        except PlaywrightTimeout as e:
            screenshot_path = f"error_ex_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            try:
                await take_screenshot(screenshot_path)
            except Exception:
                pass
            
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=f"タイムアウト: {str(e)}",
                screenshot_path=screenshot_path,
            )
        except Exception as e:
            import traceback
            print(f"[EX_SEARCH] Error: {str(e)}")
            traceback.print_exc()
            
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=f"検索エラー: {str(e)}",
            )
    
    async def _do_execute(
        self,
        task_id: str,
        search_result: TaskSearchResult,
        credentials: Optional[Dict[str, str]] = None,
    ) -> ExecutionResult:
        """
        EX予約で新幹線を予約（確認画面まで）
        
        注意: 安全のため、確認画面まで進み、実際の購入は行わない
        """
        page = await get_page()
        
        try:
            details = search_result.details or {}
            train_index = details.get("train_index", 0)
            product_type = details.get("product_type", "regular")
            seat_position = details.get("seat_position", "指定なし")
            
            print(f"[EX_EXECUTE] Starting booking: train_index={train_index}")
            
            # Step 1: ログイン確認
            if not await check_logged_in(page):
                if not credentials:
                    return ExecutionResult(
                        success=False,
                        message="ログイン情報が必要です",
                    )
                
                login_result = await login(
                    page,
                    credentials.get("member_id", credentials.get("email", "")),
                    credentials.get("password", ""),
                )

                if login_result.requires_otp:
                    # OTPが必要な場合
                    return ExecutionResult(
                        success=False,
                        message="電話認証（OTP）が必要です。登録済み電話番号に着信があります。",
                    )

                if not login_result.success:
                    return ExecutionResult(
                        success=False,
                        message=login_result.message,
                    )
            
            # Step 2: 列車を選択
            await self._notify_progress("select", "列車を選択中...")
            if not await select_train(page, train_index):
                return ExecutionResult(
                    success=False,
                    message="列車の選択に失敗しました",
                )
            
            # Step 3: 商品を選択
            await self._notify_progress("product", "商品を選択中...")
            product_result = await select_product(page, product_type)
            if not product_result.success:
                return ExecutionResult(
                    success=False,
                    message=product_result.message,
                )
            
            # Step 4: 座席位置を選択
            await select_seat_position(page, seat_position)
            
            # Step 5: 確認画面へ
            await self._notify_progress("confirm", "確認画面へ進んでいます...")
            confirm_result = await proceed_to_confirmation(page)
            
            if not confirm_result.success:
                return ExecutionResult(
                    success=False,
                    message=confirm_result.message,
                )
            
            # Step 6: 完了（購入は行わない）
            temp_id = f"EX-TEMP-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            return ExecutionResult(
                success=True,
                confirmation_number=temp_id,
                message="確認画面に到達しました。購入はSmartEXサイトで手動で行ってください。",
                details={
                    "train_name": confirm_result.train_name,
                    "seat_info": confirm_result.seat_info,
                    "price": confirm_result.price,
                    "screenshot": confirm_result.screenshot_path,
                    "note": "安全のため、実際の購入は行っていません",
                },
            )
            
        except PlaywrightTimeout as e:
            screenshot_path = f"error_ex_exec_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            try:
                await take_screenshot(screenshot_path)
            except Exception:
                pass
            
            return ExecutionResult(
                success=False,
                message=f"タイムアウト: {str(e)}",
                details={"screenshot": screenshot_path},
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            
            return ExecutionResult(
                success=False,
                message=f"実行エラー: {str(e)}",
            )

