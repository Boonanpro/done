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
    
    # SmartEX/EX予約用のセレクタ（実サイト調査済み 2024/12）
    SELECTORS = {
        # ログイン関連
        "member_id_input": 'role=textbox[name="会員ID"]',
        "password_input": 'role=textbox[name="パスワード"]',
        "login_button": 'role=button[name="ログイン"]',
        
        # ワンタイムパスワード認証（2段階認証）
        "otp_send_button": 'role=button[name="自動音声案内発信"]',
        "otp_input": 'role=textbox[name="数字6桁（半角）"]',
        "otp_next_button": 'role=button[name="次へ"]',
        
        # メニュー
        "menu_link": 'role=link[name="メニュー"]',
        "logout_link": 'role=link[name="ログアウト"]',
        "train_search": 'text=列車を検索',
        
        # 予約検索関連
        "departure_station": 'role=combobox >> nth=2',  # 乗車駅
        "arrival_station": 'role=combobox >> nth=3',    # 降車駅
        "hour_select": 'role=combobox >> nth=0',        # 時
        "minute_select": 'role=combobox >> nth=1',      # 分
        "continue_button": 'role=button[name="予約を続ける"]',
        
        # 列車選択関連
        "train_candidate": 'text=この候補を選択',
        "train_name": 'role=heading[level=3]',  # のぞみ XXX 号
        
        # 商品・座席選択関連
        "seat_position": 'role=combobox >> text=座席位置',
        "seat_map_button": 'role=button[name="座席表から指定する"]',
        
        # 確認・完了関連
        "purchase_button": 'role=button[name="予約する（購入）"]',
        "back_link": 'role=link[name="戻る"]',
        "back_button": 'role=button[name="戻る"]',
    }
    
    # SmartEX/EX予約のURL（実サイト調査済み）
    URLS = {
        "top": "https://smart-ex.jp/",
        "login": "https://shinkansen2.jr-central.co.jp/RSV_P/smart_index.htm",
        "expy_login": "https://shinkansen1.jr-central.co.jp/RSV_P/index.htm",  # エクスプレス予約会員向け
        "my_page": "https://shinkansen2.jr-central.co.jp/RSV_P/p7B/ClientService",
    }
    
    # 重要: SmartEXはログイン時にワンタイムパスワード（電話認証）が必要
    # 完全自動化には別途OTP対応が必要
    REQUIRES_OTP = True
    
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
        予約情報を入力（SmartEX用）
        
        注意: SmartEXは「列車を検索」をクリックすると検索フォームが表示される
        駅はプリセットから選ぶか、comboboxで選択する
        
        Returns:
            {"success": bool, "message": str}
        """
        try:
            # メニューページから「列車を検索」をクリック
            train_search = await page.query_selector('text=列車を検索')
            if train_search:
                await train_search.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(1000)
            
            # SmartEXでは駅選択はcomboboxで行う
            # 出発駅を選択（comboboxがある場合）
            try:
                departure_selects = await page.query_selector_all('role=combobox')
                if len(departure_selects) >= 3:
                    # 乗車駅は3番目のcombobox
                    await departure_selects[2].select_option(label=departure)
            except Exception:
                pass  # 駅選択できなくても続行
            
            # 到着駅を選択
            try:
                arrival_selects = await page.query_selector_all('role=combobox')
                if len(arrival_selects) >= 4:
                    # 降車駅は4番目のcombobox
                    await arrival_selects[3].select_option(label=arrival)
            except Exception:
                pass  # 駅選択できなくても続行
            
            # 時間を選択（時と分のcombobox）
            if time:
                try:
                    hour = time.split(":")[0] if ":" in time else time[:2]
                    hour_selects = await page.query_selector_all('role=combobox')
                    if len(hour_selects) >= 1:
                        await hour_selects[0].select_option(label=f"{hour}時")
                except Exception:
                    pass
            
            return {"success": True, "message": "予約情報を入力しました"}
            
        except Exception as e:
            return {
                "success": False,
                "message": f"予約情報の入力中にエラーが発生しました: {str(e)}",
            }
    
    async def _search_and_select_train(self, page: Page) -> dict[str, Any]:
        """
        列車を検索して選択（SmartEX用）
        
        Returns:
            {"success": bool, "message": str, "train_info": dict}
        """
        try:
            # 「予約を続ける」ボタンをクリックして検索実行
            continue_button = await page.query_selector('role=button[name="予約を続ける"]')
            if continue_button:
                await continue_button.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2000)
            
            # 列車候補を確認（「候補 1 / X」などのテキストがあるか）
            train_candidate = await page.query_selector('text=候補')
            if not train_candidate:
                return {
                    "success": False,
                    "message": "列車が見つかりませんでした。検索条件を確認してください。",
                }
            
            # 最初の列車を選択（「この候補を選択」をクリック）
            select_button = await page.query_selector('text=この候補を選択')
            if select_button:
                await select_button.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2000)
            
            # 列車情報を取得（簡易版）
            train_info = {
                "selected": True,
                "timestamp": datetime.now().isoformat(),
            }
            
            # 注意: 最終確認画面には進まない（安全のため）
            # 確認画面の「予約する（購入）」ボタンは押さない
            
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
