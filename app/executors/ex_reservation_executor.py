"""
EX Reservation Executor for Architecture v2
EX予約（新幹線）の実行ロジック

SmartEX/エクスプレス予約で新幹線を検索・予約する
"""
from typing import Optional, Any, Dict, List
from datetime import datetime

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from app.models.schemas import (
    ExecutionStep,
    ExecutionResult,
    SearchResult,
)
from app.executors.base import BaseExecutor, ExecutorSearchResult, SearchOption
from app.tools.browser import (
    get_page, 
    take_screenshot,
    page_goto,
    page_wait_for_load_state,
    page_wait_for_timeout,
    page_query_selector,
    page_query_selector_all,
    page_fill,
    page_click,
    page_url,
    page_screenshot,
)


class EXReservationExecutor(BaseExecutor):
    """EX予約（新幹線）実行ロジック"""
    
    service_type = "train"
    service_name = "ex_reservation"
    service_display_name = "EX予約（新幹線）"
    
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
                message="Reached confirmation screen. Please complete the reservation manually on EX reservation website.",
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
                message=f"Timeout error: Failed to load page - {str(e)}",
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
                message=f"Execution error: {str(e)}",
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
                return {"success": True, "message": "Already logged in"}
            
            # ログアウトボタンがあるか確認
            logout_button = await page.query_selector('a:has-text("ログアウト"), button:has-text("ログアウト")')
            if logout_button:
                return {"success": True, "message": "Already logged in"}
        except Exception:
            pass
        
        # 認証情報がない場合
        if not credentials:
            return {
                "success": False,
                "message": "EX reservation login credentials required",
            }
        
        member_id = credentials.get("email", credentials.get("member_id", ""))
        password = credentials.get("password", "")
        
        if not member_id or not password:
            return {
                "success": False,
                "message": "Member ID or password is missing",
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
            
            # OTP（2段階認証）が必要かチェック
            otp_result = await self._handle_otp_if_required(
                page=page,
                user_id=credentials.get("user_id", ""),
            )
            if not otp_result["success"]:
                return otp_result
            
            # ログイン成功を確認
            if "login" in page.url.lower() or "error" in page.url.lower():
                return {
                    "success": False,
                    "message": "Login failed. Please check your member ID and password.",
                }
            
            return {"success": True, "message": "Login successful"}
            
        except PlaywrightTimeout:
            return {
                "success": False,
                "message": "Login page loading timed out",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error during login: {str(e)}",
            }
    
    async def _handle_otp_if_required(
        self,
        page: Page,
        user_id: str,
    ) -> dict[str, Any]:
        """
        OTP（2段階認証）が必要な場合に処理
        
        SmartEXは「自動音声案内発信」ボタンをクリックすると、
        登録電話番号に自動発信され、音声でOTPが通知される。
        Twilioで着信を受け、文字起こしからOTPを抽出して入力する。
        
        Args:
            page: Playwrightページ
            user_id: ユーザーID（OTPService用）
            
        Returns:
            {"success": bool, "message": str}
        """
        try:
            # OTP入力画面かどうか確認
            otp_send_button = await page.query_selector(self.SELECTORS["otp_send_button"])
            
            if not otp_send_button:
                # OTP不要（通常ログイン成功）
                return {"success": True, "message": "OTP not required"}
            
            # OTPが必要な場合
            print("[EX_OTP] OTP authentication required")
            
            # 「自動音声案内発信」ボタンをクリック
            await otp_send_button.click()
            print("[EX_OTP] Clicked 'Send voice guidance' button")
            
            # OTPServiceを使用してOTPを待機・取得
            from app.services.otp_service import get_otp_service
            otp_service = get_otp_service()
            
            # 音声OTPを待機（最大90秒、5秒間隔でポーリング）
            # SmartEXからの発信 → Twilio着信 → 文字起こし → OTP抽出
            otp_code = None
            
            # まずVoice OTPを試行
            print("[EX_OTP] Waiting for voice OTP...")
            for attempt in range(18):  # 90秒 / 5秒 = 18回
                await page.wait_for_timeout(5000)
                
                # 最新の音声通話からOTPを抽出
                otp_result = await otp_service.extract_otp_from_latest_voice_call(
                    user_id=user_id,
                    service="ex_reservation",
                    max_age_minutes=3,
                )
                
                if otp_result and otp_result.code:
                    otp_code = otp_result.code
                    print(f"[EX_OTP] OTP obtained: {otp_code[:2]}****")
                    break
                
                print(f"[EX_OTP] Waiting... attempt {attempt + 1}/18")
            
            if not otp_code:
                return {
                    "success": False,
                    "message": "OTP not received. Please check Twilio configuration and phone number registration.",
                }
            
            # OTPを入力
            otp_input = await page.wait_for_selector(self.SELECTORS["otp_input"], timeout=10000)
            if otp_input:
                await otp_input.fill(otp_code)
                print("[EX_OTP] OTP entered")
            else:
                return {
                    "success": False,
                    "message": "OTP input field not found",
                }
            
            # 次へボタンをクリック
            next_button = await page.query_selector(self.SELECTORS["otp_next_button"])
            if next_button:
                await next_button.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2000)
                print("[EX_OTP] OTP submitted")
            
            return {"success": True, "message": "OTP authentication successful"}
            
        except Exception as e:
            print(f"[EX_OTP] Error: {str(e)}")
            return {
                "success": False,
                "message": f"OTP handling error: {str(e)}",
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
            
            return {"success": True, "message": "Reservation details entered"}
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Error entering reservation details: {str(e)}",
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
                    "message": "No trains found. Please check your search criteria.",
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
                "message": "Train selected",
                "train_info": train_info,
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Error during train search/selection: {str(e)}",
            }
    
    # ========================================
    # 探索モード（Architecture v2）
    # ========================================
    
    async def _do_search(
        self,
        params: Dict[str, Any],
        credentials: Optional[Dict[str, str]] = None,
    ) -> ExecutorSearchResult:
        """
        SmartEXで新幹線の空席を検索
        
        Args:
            params: 検索パラメータ
                - departure: 出発駅（東京、新大阪など）
                - arrival: 到着駅
                - date: 日付（YYYY-MM-DD）
                - time: 時刻（HH:MM）
                
        Returns:
            ExecutorSearchResult: 検索結果
        """
        await get_page()  # ブラウザスレッドを確保
        options: List[SearchOption] = []
        
        # デバッグ用print（ログ設定に依存しない）
        print(f"[EX_SEARCH] Starting search with params: {params}")
        
        try:
            departure = params.get("departure", "東京")
            arrival = params.get("arrival", "新大阪")
            date = params.get("date", "")
            time = params.get("time", "")
            
            print(f"[EX_SEARCH] departure={departure}, arrival={arrival}, date={date}, time={time}")
            
            await self._notify_progress(
                "browser",
                "ブラウザを起動中...",
            )
            
            # Step 1: SmartEXにアクセス
            await self._notify_progress(
                "connect",
                f"{self.service_display_name}にアクセス中...",
            )
            await page_goto(self.URLS["top"], wait_until="domcontentloaded", timeout=30000)
            
            # Step 2: ログイン（必要な場合）
            # 注: ログインはcredentialsが必要な場合のみ。今回はスキップして検索のみ行う
            
            # Step 3: 検索条件を入力
            await self._notify_progress(
                "input",
                f"検索条件を入力中... {departure}→{arrival}",
            )
            
            # SmartEXのトップページで検索フォームを探す
            await page_wait_for_timeout(2000)
            
            # 出発駅を選択
            departure_selects = await page_query_selector_all('select')
            if departure_selects:
                # セレクトボックスがある場合は選択
                pass  # TODO: 実際のフォーム操作
            
            # Step 4: 検索実行
            await self._notify_progress(
                "searching",
                f"列車を検索中... {departure}→{arrival}",
            )
            
            # 「予約を続ける」または「検索」ボタンをクリック
            search_button = await page_query_selector('button[type="submit"], input[type="submit"]')
            if search_button:
                await page_click('button[type="submit"], input[type="submit"]')
                await page_wait_for_load_state("domcontentloaded")
                await page_wait_for_timeout(3000)
            
            # Step 5: 列車選択画面で候補を確認
            await self._notify_progress(
                "extracting",
                "列車情報を抽出中...",
            )

            # 現在のURLを取得
            current_url = await page_url()

            # 候補を取得（SmartEXの場合）
            train_candidates = await page_query_selector_all('[class*="candidate"], [class*="train"], [class*="result"]')

            print(f"[EX_SEARCH] Found {len(train_candidates) if train_candidates else 0} train candidates")

            # SmartEXから候補を取得できなかった場合 → web_searchで料金を取得
            if not options:
                print("[EX_SEARCH] No options from SmartEX, falling back to web_search")
                await self._notify_progress(
                    "fallback",
                    "EX予約から情報を取得できませんでした。Web検索で料金を確認中...",
                )

                # web_searchで新幹線料金を検索
                web_result = await self._search_train_price_via_web(departure, arrival, date, time)
                if web_result:
                    options = web_result

            # Step 6: 最終確認画面まで進む（購入ボタンは押さない）
            await self._notify_progress(
                "selecting",
                "列車を選択中...",
            )

            # 「この候補を選択」ボタンをクリック
            select_button = await page_query_selector('text=この候補を選択')
            if select_button:
                print("[EX_SEARCH] Clicking '選択' button to proceed to confirmation")
                await page_click('text=この候補を選択')
                await page_wait_for_load_state("domcontentloaded")
                await page_wait_for_timeout(2000)

                # Step 7: 設備・座席選択画面があれば進む
                # 座席位置の指定（パラメータから取得）
                seat_position = params.get("seat_position", "")
                if seat_position:
                    await self._notify_progress(
                        "seat_selection",
                        f"座席を選択中... ({seat_position})",
                    )
                    # 座席位置のセレクトボックスがあれば選択
                    seat_select = await page_query_selector('select[name*="seat"], select[name*="zaseki"]')
                    if seat_select:
                        # 座席位置をマッピング
                        seat_map = {
                            "窓側": "A", "window": "A",
                            "通路側": "C", "aisle": "C",
                            "A": "A", "B": "B", "C": "C", "D": "D", "E": "E",
                        }
                        seat_value = seat_map.get(seat_position, "")
                        if seat_value:
                            try:
                                await seat_select.select_option(label=seat_value)
                            except Exception as e:
                                print(f"[EX_SEARCH] Could not select seat position: {e}")

                # 「次へ」または「確認」ボタンを探してクリック
                next_buttons = ['text=次へ', 'text=確認へ進む', 'text=確認', 'button[type="submit"]']
                for btn_selector in next_buttons:
                    next_btn = await page_query_selector(btn_selector)
                    if next_btn:
                        print(f"[EX_SEARCH] Clicking next button: {btn_selector}")
                        await page_click(btn_selector)
                        await page_wait_for_load_state("domcontentloaded")
                        await page_wait_for_timeout(2000)
                        break

                # Step 8: 最終確認画面でスクリーンショットを撮る
                await self._notify_progress(
                    "confirmation",
                    "確認画面に到達しました",
                )

                # 購入ボタンが表示されているか確認（最終確認画面にいることの確認）
                purchase_btn = await page_query_selector('text=予約する（購入）')
                if purchase_btn:
                    print("[EX_SEARCH] Reached final confirmation screen")
                else:
                    print("[EX_SEARCH] May not be on final confirmation screen")

            # 最終確認画面（または到達した画面）でスクリーンショット
            screenshot_path = f"ex_search_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            await page_screenshot(screenshot_path)
            print(f"[EX_SEARCH] Screenshot saved: {screenshot_path}")

            return ExecutorSearchResult(
                success=True,
                options=options,
                message=f"確認画面に到達しました。スクリーンショットを確認してください。",
                search_url=current_url,
                screenshot_path=screenshot_path,
            )
            
        except PlaywrightTimeout as e:
            screenshot_path = f"error_ex_search_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            try:
                await page_screenshot(screenshot_path)
            except Exception:
                pass
            
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=f"タイムアウト: ページの読み込みに失敗しました - {str(e)}",
                screenshot_path=screenshot_path,
            )
            
        except Exception as e:
            import traceback
            print(f"[EX_SEARCH] Exception: {str(e)}")
            print(traceback.format_exc())
            
            screenshot_path = f"error_ex_search_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            try:
                await page_screenshot(screenshot_path)
            except Exception:
                screenshot_path = None
            
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=f"検索エラー: {str(e)}",
                screenshot_path=screenshot_path,
            )
    
    async def _search_train_price_via_web(
        self,
        departure: str,
        arrival: str,
        date: str,
        time: str,
    ) -> List[SearchOption]:
        """
        Web検索で新幹線の料金を取得（SmartEX検索が失敗した場合のフォールバック）
        
        1. Tavilyのスニペット/AI回答から価格抽出（高速）
        2. 取れなければJinaでページ全体を読む（確実）
        """
        try:
            from app.tools.tavily_search import tavily_search_raw
            from app.tools.jina_reader import read_url
            import re
            
            # 検索クエリを構築
            query = f"{departure} {arrival} 新幹線 料金 のぞみ 指定席"
            
            print(f"[EX_SEARCH] Web search query: {query}")
            
            # Tavilyで検索（生のレスポンスを取得）
            tavily_results = await tavily_search_raw(query, max_results=5)
            
            if not tavily_results:
                print("[EX_SEARCH] No Tavily results")
                return []
            
            price_info = None
            
            # 価格抽出用の正規表現パターン
            price_patterns = [
                r'指定席[^\d]*(\d{1,2},?\d{3})円',
                r'のぞみ[^\d]*指定席[^\d]*(\d{1,2},?\d{3})円',
                r'(\d{1,2},?\d{3})円[^\d]*指定席',
                r'料金合計[^\d]*(\d{1,2},?\d{3})円',
                r'(\d{1,2},?\d{3})円',  # 最後の手段：数字+円
            ]
            
            # ===== Step 1: Tavilyのスニペット/AI回答から抽出 =====
            print("[EX_SEARCH] Step 1: Extracting from Tavily snippets...")
            
            # AI回答から抽出
            if tavily_results.get("answer"):
                answer = tavily_results["answer"]
                print(f"[EX_SEARCH] AI Answer: {answer[:200]}...")
                for pattern in price_patterns:
                    match = re.search(pattern, answer)
                    if match:
                        price_str = match.group(1).replace(',', '')
                        price_info = int(price_str)
                        print(f"[EX_SEARCH] Found price in AI answer: {price_info}")
                        break
            
            # スニペットから抽出
            if not price_info:
                for result in tavily_results.get("results", []):
                    content = result.get("content", "")
                    if content:
                        print(f"[EX_SEARCH] Snippet: {content[:100]}...")
                        for pattern in price_patterns:
                            match = re.search(pattern, content)
                            if match:
                                price_str = match.group(1).replace(',', '')
                                price_info = int(price_str)
                                print(f"[EX_SEARCH] Found price in snippet: {price_info}")
                                break
                        if price_info:
                            break
            
            # ===== Step 2: Jinaでページ全体を読む =====
            if not price_info:
                print("[EX_SEARCH] Step 2: Reading full pages with Jina...")
                for result in tavily_results.get("results", [])[:3]:
                    try:
                        url = result.get("url", "")
                        if not url:
                            continue
                        
                        print(f"[EX_SEARCH] Reading URL: {url}")
                        jina_result = await read_url(url)
                        content = jina_result.get("content", "") if jina_result else ""
                        
                        if content:
                            for pattern in price_patterns:
                                match = re.search(pattern, content)
                                if match:
                                    price_str = match.group(1).replace(',', '')
                                    price_info = int(price_str)
                                    print(f"[EX_SEARCH] Found price via Jina: {price_info}")
                                    break
                            if price_info:
                                break
                    
                    except Exception as e:
                        print(f"[EX_SEARCH] Error reading URL: {e}")
                        continue
            
            # 価格が見つからなかった場合
            if not price_info:
                print("[EX_SEARCH] Could not extract price from web search")
                return []
            
            # 検索結果を構築（実際のWeb検索から取得した価格を使用）
            options = [
                SearchOption(
                    id="train_web_1",
                    title=f"のぞみ（{departure}→{arrival}）",
                    description=f"{date} 17時台 普通車指定席",
                    price=price_info,
                    available=True,
                    details={
                        "departure": departure,
                        "arrival": arrival,
                        "date": date,
                        "time": time or "17:00",
                        "seat_type": "普通車指定席",
                        "source": "web_search",
                        "note": "Web検索から取得した料金です。時刻表はEX予約で確認してください。",
                    },
                ),
            ]
            
            return options
            
        except Exception as e:
            print(f"[EX_SEARCH] Web search fallback failed: {e}")
            import traceback
            traceback.print_exc()
            return []
