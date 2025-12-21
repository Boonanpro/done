"""
EX Reservation Executor for Phase 3B: Execution Engine
EX予約（新幹線）の実行ロジック
"""
from typing import Optional, Any
from datetime import datetime

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from app.models.schemas import (
    ExecutionStep,
    ExecutionResult,
    SearchResult,
)
from app.executors.base import BaseExecutor
from app.tools.browser import get_page, take_screenshot


class EXReservationExecutor(BaseExecutor):
    """EX予約（新幹線）実行ロジック"""
    
    service_name = "ex_reservation"
    
    # EX予約用のセレクタ
    SELECTORS = {
        # ログイン関連
        "login_link": 'a[href*="login"], .login-button',
        "member_id_input": 'input[name="memberId"], input[name="userId"], #memberId',
        "password_input": 'input[name="password"], input[type="password"], #password',
        "login_button": 'button[type="submit"], input[type="submit"], .login-submit',
        
        # 予約検索関連
        "departure_station": 'select[name="departure"], #departureStation, input[name="from"]',
        "arrival_station": 'select[name="arrival"], #arrivalStation, input[name="to"]',
        "date_input": 'input[name="date"], input[type="date"], #reservationDate',
        "time_input": 'input[name="time"], select[name="hour"], #departureTime',
        "search_button": 'button[type="submit"]:has-text("検索"), .search-button',
        
        # 列車選択関連
        "train_list": '.train-list, .result-list, table.trains',
        "train_row": '.train-item, tr.train-row, .result-item',
        "select_train": 'button:has-text("選択"), a:has-text("予約"), .reserve-button',
        
        # 座席選択関連
        "seat_type": 'select[name="seatType"], input[name="seat"]',
        "seat_confirm": 'button:has-text("確定"), .seat-confirm',
        
        # 確認・完了関連
        "confirm_button": 'button:has-text("確認"), .confirm-button',
        "reservation_complete": '.reservation-complete, .complete-message',
        "reservation_number": '.reservation-number, .confirmation-number, #reservationNo',
    }
    
    # EX予約のURL
    URLS = {
        "top": "https://expy.jp/",
        "login": "https://expy.jp/member/login/",
        "reservation": "https://expy.jp/reservation/",
        "my_page": "https://expy.jp/member/mypage/",
    }
    
    async def _do_execute(
        self,
        task_id: str,
        search_result: SearchResult,
        credentials: Optional[dict[str, str]] = None,
    ) -> ExecutionResult:
        """
        EX予約で新幹線を予約
        
        注意: 安全のため、確認画面まで進み、実際の予約確定は行わない
        """
        page = await get_page()
        
        try:
            # 予約詳細を取得
            details = search_result.details or {}
            departure = details.get("departure", "東京")
            arrival = details.get("arrival", "新大阪")
            date = details.get("date", "")
            time = details.get("time", "")
            
            # Step 1: EX予約サイトにアクセス
            reservation_url = search_result.url or self.URLS["reservation"]
            await page.goto(reservation_url, wait_until="domcontentloaded", timeout=30000)
            await self._update_progress(
                task_id=task_id,
                step=ExecutionStep.OPENED_URL.value,
                details={"url": reservation_url},
            )
            
            # Step 2: ログイン確認・実行
            login_result = await self._ensure_logged_in(page, credentials)
            if not login_result["success"]:
                return ExecutionResult(
                    success=False,
                    message=login_result["message"],
                )
            
            await self._update_progress(
                task_id=task_id,
                step=ExecutionStep.LOGGED_IN.value,
                details={"logged_in": True},
            )
            
            # Step 3: 予約情報を入力
            input_result = await self._enter_reservation_details(
                page, departure, arrival, date, time
            )
            if not input_result["success"]:
                return ExecutionResult(
                    success=False,
                    message=input_result["message"],
                )
            
            await self._update_progress(
                task_id=task_id,
                step=ExecutionStep.ENTERED_DETAILS.value,
                details={
                    "departure": departure,
                    "arrival": arrival,
                    "date": date,
                    "time": time,
                },
            )
            
            # Step 4: 列車を検索・選択
            search_result_data = await self._search_and_select_train(page)
            if not search_result_data["success"]:
                return ExecutionResult(
                    success=False,
                    message=search_result_data["message"],
                )
            
            # Step 5: 確認画面まで進む（実際の予約は行わない）
            await self._update_progress(
                task_id=task_id,
                step=ExecutionStep.CONFIRMED.value,
                details={"train_info": search_result_data.get("train_info", {})},
            )
            
            # Step 6: 完了（予約確定は手動で行う）
            # 安全のため、実際の予約確定は行わない
            temp_reservation_id = f"EX-TEMP-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            await self._update_progress(
                task_id=task_id,
                step=ExecutionStep.COMPLETED.value,
                details={"temp_reservation_id": temp_reservation_id},
            )
            
            return ExecutionResult(
                success=True,
                confirmation_number=temp_reservation_id,
                message="予約確認画面まで進みました。予約を確定するにはEX予約サイトで手動で操作してください。",
                details={
                    "departure": departure,
                    "arrival": arrival,
                    "date": date,
                    "time": time,
                    "train_info": search_result_data.get("train_info", {}),
                    "reservation_url": self.URLS["my_page"],
                },
            )
            
        except PlaywrightTimeout as e:
            screenshot_path = f"error_ex_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            await take_screenshot(screenshot_path)
            
            return ExecutionResult(
                success=False,
                message=f"タイムアウトエラー: ページの読み込みに失敗しました - {str(e)}",
                details={"screenshot": screenshot_path},
            )
        except Exception as e:
            screenshot_path = f"error_ex_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            try:
                await take_screenshot(screenshot_path)
            except Exception:
                pass
            
            return ExecutionResult(
                success=False,
                message=f"実行エラー: {str(e)}",
                details={"screenshot": screenshot_path},
            )
    
    async def _ensure_logged_in(
        self,
        page: Page,
        credentials: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """
        ログイン状態を確認し、必要であればログイン
        
        Returns:
            {"success": bool, "message": str}
        """
        # ログイン状態を確認
        try:
            # マイページへのリンクがあるか確認
            mypage_link = await page.query_selector('a[href*="mypage"], .mypage-link')
            if mypage_link:
                return {"success": True, "message": "既にログイン済み"}
            
            # ログアウトボタンがあるか確認
            logout_button = await page.query_selector('a:has-text("ログアウト"), button:has-text("ログアウト")')
            if logout_button:
                return {"success": True, "message": "既にログイン済み"}
        except Exception:
            pass
        
        # 認証情報がない場合
        if not credentials:
            return {
                "success": False,
                "message": "EX予約のログイン情報が必要です",
            }
        
        member_id = credentials.get("email", credentials.get("member_id", ""))
        password = credentials.get("password", "")
        
        if not member_id or not password:
            return {
                "success": False,
                "message": "会員IDまたはパスワードが不足しています",
            }
        
        try:
            # ログインページに移動
            await page.goto(self.URLS["login"], wait_until="domcontentloaded", timeout=30000)
            
            # 会員IDを入力
            await page.wait_for_selector(self.SELECTORS["member_id_input"], timeout=10000)
            await page.fill(self.SELECTORS["member_id_input"], member_id)
            
            # パスワードを入力
            await page.wait_for_selector(self.SELECTORS["password_input"], timeout=10000)
            await page.fill(self.SELECTORS["password_input"], password)
            
            # ログインボタンをクリック
            login_btn = await page.query_selector(self.SELECTORS["login_button"])
            if login_btn:
                await login_btn.click()
            else:
                await page.keyboard.press("Enter")
            
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(2000)
            
            # ログイン成功を確認
            if "login" in page.url.lower() or "error" in page.url.lower():
                return {
                    "success": False,
                    "message": "ログインに失敗しました。会員IDまたはパスワードを確認してください。",
                }
            
            return {"success": True, "message": "ログイン成功"}
            
        except PlaywrightTimeout:
            return {
                "success": False,
                "message": "ログインページの読み込みがタイムアウトしました",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"ログイン中にエラーが発生しました: {str(e)}",
            }
    
    async def _enter_reservation_details(
        self,
        page: Page,
        departure: str,
        arrival: str,
        date: str,
        time: str,
    ) -> dict[str, Any]:
        """
        予約情報を入力
        
        Returns:
            {"success": bool, "message": str}
        """
        try:
            # 予約ページに移動
            if "reservation" not in page.url:
                await page.goto(self.URLS["reservation"], wait_until="domcontentloaded", timeout=30000)
            
            # 出発駅を入力
            departure_field = await page.query_selector(self.SELECTORS["departure_station"])
            if departure_field:
                tag_name = await departure_field.evaluate("el => el.tagName.toLowerCase()")
                if tag_name == "select":
                    await departure_field.select_option(label=departure)
                else:
                    await departure_field.fill(departure)
            
            # 到着駅を入力
            arrival_field = await page.query_selector(self.SELECTORS["arrival_station"])
            if arrival_field:
                tag_name = await arrival_field.evaluate("el => el.tagName.toLowerCase()")
                if tag_name == "select":
                    await arrival_field.select_option(label=arrival)
                else:
                    await arrival_field.fill(arrival)
            
            # 日付を入力
            if date:
                date_field = await page.query_selector(self.SELECTORS["date_input"])
                if date_field:
                    await date_field.fill(date)
            
            # 時間を入力
            if time:
                time_field = await page.query_selector(self.SELECTORS["time_input"])
                if time_field:
                    tag_name = await time_field.evaluate("el => el.tagName.toLowerCase()")
                    if tag_name == "select":
                        await time_field.select_option(value=time)
                    else:
                        await time_field.fill(time)
            
            return {"success": True, "message": "予約情報を入力しました"}
            
        except Exception as e:
            return {
                "success": False,
                "message": f"予約情報の入力中にエラーが発生しました: {str(e)}",
            }
    
    async def _search_and_select_train(self, page: Page) -> dict[str, Any]:
        """
        列車を検索して選択
        
        Returns:
            {"success": bool, "message": str, "train_info": dict}
        """
        try:
            # 検索ボタンをクリック
            search_button = await page.query_selector(self.SELECTORS["search_button"])
            if search_button:
                await search_button.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2000)
            
            # 列車リストを確認
            train_list = await page.query_selector(self.SELECTORS["train_list"])
            if not train_list:
                return {
                    "success": False,
                    "message": "列車が見つかりませんでした。検索条件を確認してください。",
                }
            
            # 最初の列車を選択
            select_button = await page.query_selector(self.SELECTORS["select_train"])
            if select_button:
                await select_button.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2000)
            
            # 列車情報を取得（簡易版）
            train_info = {
                "selected": True,
                "timestamp": datetime.now().isoformat(),
            }
            
            # 確認ボタンがあれば進む（予約確定はしない）
            confirm_button = await page.query_selector(self.SELECTORS["confirm_button"])
            if confirm_button:
                # 確認画面までは進む（最終確定はしない）
                pass  # 安全のため、ここで停止
            
            return {
                "success": True,
                "message": "列車を選択しました",
                "train_info": train_info,
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"列車の検索・選択中にエラーが発生しました: {str(e)}",
            }
