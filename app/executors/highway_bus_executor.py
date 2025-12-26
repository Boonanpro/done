"""
Highway Bus Executor for Phase 3B/3C: Execution Engine
WILLER高速バス予約の実行ロジック
"""
from typing import Optional, Any
from datetime import datetime

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from app.models.schemas import (
    ExecutionStep,
    ExecutionResult,
    SearchResult,
    AuthField,
    AuthFieldType,
    RegistrationConfig,
)
from app.executors.base import BaseExecutor
from app.services.dynamic_auth import get_dynamic_auth_service
from app.tools.browser import get_page, take_screenshot


class HighwayBusExecutor(BaseExecutor):
    """WILLER高速バス予約実行ロジック"""
    
    service_name = "willer"
    
    # WILLER用のセレクタ（実サイト調査済み 2024/12）
    SELECTORS = {
        # ログイン関連
        "login_link": 'a[href*="mypage"]',
        "login_id_input": 'input[name*="mail"], input[type="email"]',
        "password_input": 'input[name*="pass"], input[type="password"]',
        "login_button": 'button:has-text("ログイン")',
        
        # 新規登録関連
        "register_link": 'a:has-text("新規会員登録")',
        "member_type_general": 'input[type="radio"]:first-of-type',  # 一般会員
        "email_input": 'input[type="text"]:nth-of-type(1)',  # メール入力
        "email_confirm": 'input[type="text"]:nth-of-type(2)',  # メール確認
        "password_new": 'input[type="text"]:nth-of-type(3)',  # パスワード
        "password_confirm": 'input[type="text"]:nth-of-type(4)',  # パスワード確認
        "last_name_kana": 'table input[type="text"]:nth-of-type(5)',  # セイ
        "first_name_kana": 'table input[type="text"]:nth-of-type(6)',  # メイ
        "birth_year": 'select:nth-of-type(1)',  # 生年
        "birth_month": 'select:nth-of-type(2)',  # 生月
        "birth_day": 'select:nth-of-type(3)',  # 生日
        "gender_male": 'input[type="radio"][value="1"]',  # 男性
        "gender_female": 'input[type="radio"][value="2"]',  # 女性
        "postal_code1": 'input[size="3"]',  # 郵便番号上3桁
        "postal_code2": 'input[size="4"]',  # 郵便番号下4桁
        "prefecture_select": 'select:has(option:text("東京都"))',  # 都道府県
        "address_input": 'input[name*="addr"]',  # 住所
        "phone1": 'input[name*="tel1"]',  # 電話番号1
        "phone2": 'input[name*="tel2"]',  # 電話番号2
        "phone3": 'input[name*="tel3"]',  # 電話番号3
        "agree_checkbox": 'input[type="checkbox"]:has-text("同意")',  # 規約同意
        "submit_register": 'button:has-text("次へ")',  # 登録次へ
        
        # 検索関連
        "departure_select": 'select:first-of-type',  # 出発地
        "arrival_select": 'select:nth-of-type(2)',  # 到着地
        "date_input": 'input[type="text"][placeholder*="日付"]',  # 日付
        "search_button": 'button:has-text("検索")',  # 検索ボタン
        
        # バス一覧関連
        "bus_item": '.bus-item, [class*="result"]',  # バス便
        "book_button": 'a:has-text("予約に進む"), button:has-text("予約")',  # 予約ボタン
        "price_display": '[class*="price"], .price',  # 価格表示
        
        # 座席選択関連
        "seat_type": 'input[type="radio"][name*="seat"]',  # 座席タイプ
        "seat_map": '[class*="seat-map"]',  # 座席表
        "confirm_seat": 'button:has-text("選択"), button:has-text("確定")',  # 座席確定
        
        # 予約確認関連
        "confirm_button": 'button:has-text("予約を確定"), button:has-text("確認")',
        "back_button": 'a:has-text("戻る"), button:has-text("戻る")',
        
        # マイページ関連
        "mypage_link": 'a[href*="mypage"]',
        "logout_link": 'a:has-text("ログアウト")',
    }
    
    # WILLER関連URL
    URLS = {
        "top": "https://travel.willer.co.jp/",
        "login": "https://travel.willer.co.jp/dy/3/common/pc/login/",
        "register": "https://travel.willer.co.jp/dy/3/common/pc/kainRegister/index",
        "mypage": "https://travel.willer.co.jp/dy/3/common/pc/mypage/menu/index",
        "bus_search": "https://travel.willer.co.jp/bus_search/",
    }
    
    # WILLER パスワード要件
    PASSWORD_REQUIREMENTS = {
        "min_length": 8,
        "require_uppercase": False,  # WILLERは大文字必須ではない
        "require_lowercase": True,
        "require_digits": True,
        "require_special": False,
    }
    
    def __init__(self):
        """Executorを初期化"""
        super().__init__()
        self.dynamic_auth = get_dynamic_auth_service()
    
    async def _do_execute(
        self,
        task_id: str,
        search_result: SearchResult,
        credentials: Optional[dict[str, str]] = None,
    ) -> ExecutionResult:
        """
        WILLER高速バスを予約
        
        注意: 安全のため、確認画面まで進み、実際の予約確定は行わない
        """
        page = await get_page()
        
        try:
            # 予約詳細を取得
            details = search_result.details or {}
            departure = details.get("departure", "東京")
            arrival = details.get("arrival", "大阪")
            date = details.get("date", "")
            
            # Step 1: WILLERサイトにアクセス
            bus_url = search_result.url or self._build_search_url(departure, arrival, date)
            await page.goto(bus_url, wait_until="domcontentloaded", timeout=30000)
            await self._update_progress(
                task_id=task_id,
                step=ExecutionStep.OPENED_URL.value,
                details={"url": bus_url},
            )
            
            # Step 2: ログイン確認・実行
            login_result = await self._ensure_logged_in(page, credentials)
            if not login_result["success"]:
                return ExecutionResult(
                    success=False,
                    message=login_result["message"],
                    details={"requires_registration": login_result.get("requires_registration", False)},
                )
            
            await self._update_progress(
                task_id=task_id,
                step=ExecutionStep.LOGGED_IN.value,
                details={"logged_in": True},
            )
            
            # Step 3: バス検索・選択
            select_result = await self._select_bus(page, details)
            if not select_result["success"]:
                return ExecutionResult(
                    success=False,
                    message=select_result["message"],
                )
            
            await self._update_progress(
                task_id=task_id,
                step=ExecutionStep.SELECTED_ITEM.value,
                details={
                    "bus_info": select_result.get("bus_info", {}),
                },
            )
            
            # Step 4: 座席選択
            seat_result = await self._select_seat(page, details)
            if not seat_result["success"]:
                # 座席選択失敗は警告のみ（続行）
                pass
            
            await self._update_progress(
                task_id=task_id,
                step=ExecutionStep.ENTERED_DETAILS.value,
                details={
                    "seat_info": seat_result.get("seat_info", {}),
                },
            )
            
            # Step 5: 確認画面まで進む（実際の予約は行わない）
            await self._update_progress(
                task_id=task_id,
                step=ExecutionStep.CONFIRMED.value,
                details={"ready_to_book": True},
            )
            
            # スクリーンショットを撮影
            screenshot_path = f"willer_confirm_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            try:
                await take_screenshot(screenshot_path)
            except Exception:
                screenshot_path = None
            
            # Step 6: 完了（予約確定は手動で行う）
            temp_reservation_id = f"WILLER-TEMP-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            await self._update_progress(
                task_id=task_id,
                step=ExecutionStep.COMPLETED.value,
                details={"temp_reservation_id": temp_reservation_id},
            )
            
            return ExecutionResult(
                success=True,
                confirmation_number=temp_reservation_id,
                message="予約確認画面まで進みました。予約を確定するにはWILLER TRAVELサイトで手動で操作してください。",
                details={
                    "departure": departure,
                    "arrival": arrival,
                    "date": date,
                    "bus_info": select_result.get("bus_info", {}),
                    "seat_info": seat_result.get("seat_info", {}),
                    "screenshot": screenshot_path,
                    "mypage_url": self.URLS["mypage"],
                },
            )
            
        except PlaywrightTimeout as e:
            screenshot_path = f"error_willer_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            try:
                await take_screenshot(screenshot_path)
            except Exception:
                pass
            
            return ExecutionResult(
                success=False,
                message=f"タイムアウトエラー: ページの読み込みに失敗しました - {str(e)}",
                details={"screenshot": screenshot_path},
            )
        except Exception as e:
            screenshot_path = f"error_willer_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            try:
                await take_screenshot(screenshot_path)
            except Exception:
                pass
            
            return ExecutionResult(
                success=False,
                message=f"実行エラー: {str(e)}",
                details={"screenshot": screenshot_path},
            )
    
    def _build_search_url(self, departure: str, arrival: str, date: str = "") -> str:
        """
        検索URLを構築
        
        Args:
            departure: 出発地
            arrival: 到着地
            date: 日付（オプション）
            
        Returns:
            検索URL
        """
        # 都市名・都道府県名から英語表記へのマッピング
        # 注意: 将来的にはAIが動的に判断するか、WILLERのAPIを使用する方が良い
        city_map = {
            # 関東
            "東京": "tokyo",
            "新宿": "tokyo",
            "池袋": "tokyo",
            "横浜": "kanagawa/yokohama",
            "神奈川": "kanagawa",
            "千葉": "chiba",
            "埼玉": "saitama",
            "大宮": "saitama/omiya",
            # 関西
            "大阪": "osaka",
            "梅田": "osaka",  # 大阪梅田
            "難波": "osaka",
            "京都": "kyoto",
            "神戸": "hyogo/kobe",
            "兵庫": "hyogo",
            "奈良": "nara",
            # 中部
            "名古屋": "aichi/nagoya",
            "愛知": "aichi",
            "静岡": "shizuoka",
            "長野": "nagano",
            "新潟": "niigata",
            "金沢": "ishikawa/kanazawa",
            "石川": "ishikawa",
            "富山": "toyama",
            # 東北
            "仙台": "miyagi/sendai",
            "宮城": "miyagi",
            "福島": "fukushima",
            "山形": "yamagata",
            "青森": "aomori",
            "秋田": "akita",
            "盛岡": "iwate/morioka",
            "岩手": "iwate",
            # 中国・四国
            "広島": "hiroshima",
            "岡山": "okayama",
            "鳥取": "tottori",
            "米子": "tottori",  # 米子は鳥取県
            "島根": "shimane",
            "松江": "shimane/matsue",
            "出雲": "shimane",
            "山口": "yamaguchi",
            "高松": "kagawa/takamatsu",
            "香川": "kagawa",
            "松山": "ehime/matsuyama",
            "愛媛": "ehime",
            "高知": "kochi",
            "徳島": "tokushima",
            # 九州
            "福岡": "fukuoka",
            "博多": "fukuoka",
            "北九州": "fukuoka/kitakyushu",
            "熊本": "kumamoto",
            "長崎": "nagasaki",
            "大分": "oita",
            "鹿児島": "kagoshima",
            "宮崎": "miyazaki",
            "佐賀": "saga",
            # 北海道
            "札幌": "hokkaido/sapporo",
            "北海道": "hokkaido",
        }
        
        dep_code = city_map.get(departure, "tokyo")
        arr_code = city_map.get(arrival, "osaka")
        
        # 都道府県コードの場合はall付与
        if "/" not in dep_code:
            dep_code = f"{dep_code}/all"
        if "/" not in arr_code:
            arr_code = f"{arr_code}/all"
        
        url = f"{self.URLS['bus_search']}{dep_code}/{arr_code}/"
        
        # 日付指定がある場合
        if date:
            # YYYY-MM-DD から YYYYMM 形式へ
            try:
                year_month = date.replace("-", "")[:6]
                url += f"ym_{year_month}/"
            except Exception:
                pass
        
        return url
    
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
            # ログアウトリンクがあるか確認
            logout_link = await page.query_selector('a:has-text("ログアウト")')
            if logout_link:
                return {"success": True, "message": "既にログイン済み"}
            
            # マイページリンクをクリックしてログインページへ
            mypage_link = await page.query_selector('a[href*="mypage"]')
            if mypage_link:
                # WILLERはマイページクリックでログインページへリダイレクト
                current_url = page.url
                await mypage_link.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(1000)
                
                # ログイン後（ログアウトリンクが表示）なら成功
                logout_after = await page.query_selector('a:has-text("ログアウト")')
                if logout_after:
                    return {"success": True, "message": "既にログイン済み"}
        except Exception:
            pass
        
        # 認証情報がない場合
        if not credentials:
            return {
                "success": False,
                "message": "WILLERのログイン情報が必要です",
                "requires_registration": True,
            }
        
        email = credentials.get("email", "")
        password = credentials.get("password", "")
        
        if not email or not password:
            return {
                "success": False,
                "message": "メールアドレスまたはパスワードが不足しています",
            }
        
        try:
            # ログインページに移動
            await page.goto(self.URLS["login"], wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1000)
            
            # メールアドレスを入力
            email_input = await page.query_selector('input[type="text"], input[type="email"]')
            if email_input:
                await email_input.fill(email)
            
            # パスワードを入力
            password_inputs = await page.query_selector_all('input[type="text"], input[type="password"]')
            if len(password_inputs) >= 2:
                await password_inputs[1].fill(password)
            
            # ログインボタンをクリック
            login_btn = await page.query_selector('button:has-text("ログイン")')
            if login_btn:
                await login_btn.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2000)
            
            # ログイン成功を確認
            logout_link = await page.query_selector('a:has-text("ログアウト")')
            if logout_link:
                return {"success": True, "message": "ログイン成功"}
            
            # エラーメッセージを確認
            error_msg = await page.query_selector('.error, [class*="error"]')
            if error_msg:
                error_text = await error_msg.text_content()
                return {
                    "success": False,
                    "message": f"ログインに失敗しました: {error_text}",
                }
            
            return {
                "success": False,
                "message": "ログインに失敗しました。メールアドレスまたはパスワードを確認してください。",
            }
            
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
    
    async def _select_bus(
        self,
        page: Page,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        """
        バスを検索して選択
        
        Returns:
            {"success": bool, "message": str, "bus_info": dict}
        """
        try:
            departure = details.get("departure", "東京")
            arrival = details.get("arrival", "大阪")
            date = details.get("date", "")
            
            # 検索ページに移動（既にいない場合）
            if "bus_search" not in page.url:
                search_url = self._build_search_url(departure, arrival, date)
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)
            
            # 日付を選択（カレンダーがある場合）
            if date:
                try:
                    # 日付の日部分を取得
                    day = date.split("-")[2].lstrip("0") if "-" in date else date
                    date_cell = await page.query_selector(f'td:has-text("{day}") a, [data-date*="{day}"]')
                    if date_cell:
                        await date_cell.click()
                        await page.wait_for_timeout(2000)
                except Exception:
                    pass
            
            # バス一覧を取得
            await page.wait_for_timeout(1000)
            
            # 最初のバスの「予約に進む」をクリック
            book_button = await page.query_selector('a:has-text("予約に進む")')
            if book_button:
                await book_button.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2000)
                
                return {
                    "success": True,
                    "message": "バスを選択しました",
                    "bus_info": {
                        "departure": departure,
                        "arrival": arrival,
                        "date": date,
                        "timestamp": datetime.now().isoformat(),
                    },
                }
            
            return {
                "success": False,
                "message": "予約可能なバスが見つかりませんでした",
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"バスの検索・選択中にエラーが発生しました: {str(e)}",
            }
    
    async def _select_seat(
        self,
        page: Page,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        """
        座席を選択
        
        Returns:
            {"success": bool, "message": str, "seat_info": dict}
        """
        try:
            # 座席選択ページかどうか確認
            seat_map = await page.query_selector('[class*="seat"], [class*="seatmap"]')
            if not seat_map:
                # 座席選択が不要なプランの場合
                return {
                    "success": True,
                    "message": "座席選択は不要です",
                    "seat_info": {"auto_assigned": True},
                }
            
            # 空席をクリック
            available_seat = await page.query_selector(
                '[class*="available"], [class*="empty"], [class*="○"]'
            )
            if available_seat:
                await available_seat.click()
                await page.wait_for_timeout(1000)
            
            # 確定ボタンをクリック
            confirm_btn = await page.query_selector(
                'button:has-text("選択"), button:has-text("確定"), button:has-text("次へ")'
            )
            if confirm_btn:
                await confirm_btn.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2000)
            
            return {
                "success": True,
                "message": "座席を選択しました",
                "seat_info": {
                    "selected": True,
                    "timestamp": datetime.now().isoformat(),
                },
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"座席選択中にエラーが発生しました: {str(e)}",
                "seat_info": {},
            }
    
    def get_registration_config(self) -> RegistrationConfig:
        """
        WILLERの登録設定を取得
        
        Returns:
            RegistrationConfig
        """
        fields = [
            # 会員種別（一般会員）
            AuthField(
                field_type=AuthFieldType.RADIO,
                selector='input[type="radio"]:first-of-type',
                name="member_type",
                required=True,
            ),
            # メールアドレス
            AuthField(
                field_type=AuthFieldType.EMAIL,
                selector='table tr:has-text("メールアドレス") input:first-of-type',
                name="email",
                required=True,
            ),
            # メールアドレス確認
            AuthField(
                field_type=AuthFieldType.EMAIL,
                selector='table tr:has-text("メールアドレス") input:nth-of-type(2)',
                name="email_confirm",
                required=True,
            ),
            # パスワード
            AuthField(
                field_type=AuthFieldType.PASSWORD,
                selector='table tr:has-text("パスワード") input:first-of-type',
                name="password",
                required=True,
            ),
            # パスワード確認
            AuthField(
                field_type=AuthFieldType.PASSWORD,
                selector='table tr:has-text("パスワード") input:nth-of-type(2)',
                name="password_confirm",
                required=True,
            ),
            # 名前（フリガナ）セイ
            AuthField(
                field_type=AuthFieldType.NAME_KANA,
                selector='table tr:has-text("フリガナ") input:first-of-type',
                name="last_name_kana",
                required=True,
            ),
            # 名前（フリガナ）メイ
            AuthField(
                field_type=AuthFieldType.NAME_KANA,
                selector='table tr:has-text("フリガナ") input:nth-of-type(2)',
                name="first_name_kana",
                required=True,
            ),
            # 生年月日
            AuthField(
                field_type=AuthFieldType.BIRTHDATE,
                selector='table tr:has-text("生年月日") select:nth-of-type(1), table tr:has-text("生年月日") select:nth-of-type(2), table tr:has-text("生年月日") select:nth-of-type(3)',
                name="birthdate",
                required=True,
            ),
            # 性別
            AuthField(
                field_type=AuthFieldType.RADIO,
                selector='table tr:has-text("性別") input[type="radio"]',
                name="gender",
                required=True,
            ),
            # 郵便番号
            AuthField(
                field_type=AuthFieldType.POSTAL_CODE,
                selector='table tr:has-text("郵便番号") input',
                name="postal_code",
                required=True,
            ),
            # 都道府県
            AuthField(
                field_type=AuthFieldType.PREFECTURE,
                selector='table tr:has-text("都道府県") select',
                name="prefecture",
                required=True,
            ),
            # 住所
            AuthField(
                field_type=AuthFieldType.ADDRESS,
                selector='table tr:has-text("住所") input',
                name="address",
                required=True,
            ),
            # 職業
            AuthField(
                field_type=AuthFieldType.RADIO,
                selector='table tr:has-text("職業") input[type="radio"]',
                name="occupation",
                required=True,
            ),
            # 電話番号
            AuthField(
                field_type=AuthFieldType.PHONE,
                selector='table tr:has-text("携帯電話") input',
                name="phone",
                required=True,
            ),
            # サイト知ったきっかけ
            AuthField(
                field_type=AuthFieldType.RADIO,
                selector='table tr:has-text("どうやって") input[type="radio"]',
                name="referrer",
                required=True,
            ),
            # 規約同意
            AuthField(
                field_type=AuthFieldType.CHECKBOX,
                selector='input[type="checkbox"]:has-text("同意"), input[type="checkbox"]',
                name="agree_terms",
                required=True,
            ),
        ]
        
        return RegistrationConfig(
            service_name=self.service_name,
            registration_url=self.URLS["register"],
            login_url=self.URLS["login"],
            fields=fields,
            submit_selector='button:has-text("次へ")',
            password_requirements=self.PASSWORD_REQUIREMENTS,
        )








