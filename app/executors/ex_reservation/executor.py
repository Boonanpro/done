"""
EX予約 メインExecutor

最終更新: 2026/01/15
アクションファースト原則: 検索→確認画面まで進み、1つの具体的な提案を返す
"""

from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

from playwright.async_api import TimeoutError as PlaywrightTimeout

from app.models.schemas import ExecutionResult, SearchResult as TaskSearchResult
from app.executors.base import BaseExecutor, ExecutorSearchResult, SearchOption
from app.tools.browser import get_page, take_screenshot

from app.executors.ex_reservation.selectors import URLS, MYPAGE
from app.executors.ex_reservation.login import login, check_logged_in
from app.executors.ex_reservation.search import (
    open_search_form,
    fill_search_form,
    execute_search,
    select_train,
    TrainOption,
)
from app.executors.ex_reservation.seat import complete_seat_selection
from app.executors.ex_reservation.cancel import cancel_reservation

# Executor用: 本物のPlaywright Pageを取得
from app.tools.browser import get_executor_page


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
        SmartEXで新幹線を検索し、確認画面まで進んで1つの提案を返す

        アクションファースト原則:
        - 複数候補を返すのではなく、1つの具体的な提案を返す
        - ユーザーの要望を満たす仮説に基づいて列車を選択
        - 確認画面まで進み、実際の空席状況を確認

        Args:
            params: 検索パラメータ
                - departure/departure_station: 出発駅
                - arrival/arrival_station: 到着駅
                - date/departure_date: 日付（YYYY-MM-DD または "tomorrow"）
                - time/departure_time: 時刻（HH:MM）
                - seat_position: 座席位置（"窓側", "通路側", "指定なし"）
                - product_type: 商品タイプ（"regular", "green"）

        Returns:
            ExecutorSearchResult: 1つの提案（確認画面の情報）
        """
        page = await get_executor_page()

        try:
            # パラメータ名の互換性
            departure = params.get("departure") or params.get("departure_station") or "東京"
            arrival = params.get("arrival") or params.get("arrival_station") or "名古屋"
            date = params.get("date") or params.get("departure_date") or ""
            time = params.get("time") or params.get("departure_time") or ""
            seat_position = params.get("seat_position") or params.get("seat") or "指定なし"
            product_type = params.get("product_type") or params.get("seat_type") or "regular"

            # 座席位置の正規化
            seat_position = self._normalize_seat_position(seat_position)

            # "tomorrow" などの相対日付を変換
            if date == "tomorrow":
                tomorrow = datetime.now() + timedelta(days=1)
                date = tomorrow.strftime("%Y-%m-%d")

            print(f"[EX_SEARCH] Starting search: {departure} → {arrival}, {date} {time}")
            print(f"[EX_SEARCH] Seat: {seat_position}, Product: {product_type}")

            await self._notify_progress("connect", f"{self.service_display_name}にアクセス中...")

            # Step 1: ログイン確認・実行
            login_success = await self._ensure_logged_in(page, credentials)
            if not login_success:
                return ExecutorSearchResult(
                    success=False,
                    options=[],
                    message="ログインに失敗しました",
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
                minute_int = int(parts[1])
                minute_rounded = (minute_int // 5) * 5
                minute = f"{minute_rounded:02d}分"

            # 日付を変換（YYYY-MM-DD -> YYYYMMDD）
            date_formatted = date.replace("-", "") if date else None
            print(f"[EX_SEARCH] Date: {date} -> {date_formatted}, Time: {hour} {minute}")

            await fill_search_form(page, departure, arrival, hour, minute, date=date_formatted)

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

            if not search_result.options:
                return ExecutorSearchResult(
                    success=False,
                    options=[],
                    message="該当する列車が見つかりませんでした",
                    screenshot_path=search_result.screenshot_path,
                )

            # Step 5: 最適な列車を選択（アクションファースト）
            # 希望時刻に最も近い空席ありの列車を選ぶ
            selected_train = self._select_best_train(search_result.options, time)

            if not selected_train:
                return ExecutorSearchResult(
                    success=False,
                    options=[],
                    message="空席のある列車が見つかりませんでした",
                    screenshot_path=search_result.screenshot_path,
                )

            print(f"[EX_SEARCH] Selected train: {selected_train.train_name} {selected_train.departure_time}発")

            await self._notify_progress("select", f"{selected_train.train_name}を選択中...")
            if not await select_train(page, selected_train.index):
                return ExecutorSearchResult(
                    success=False,
                    options=[],
                    message="列車の選択に失敗しました",
                )

            # Step 6: 座席選択→確認画面まで進む
            await self._notify_progress("seat", "座席を選択中...")

            # product_typeをindexに変換（0: 普通車, 1: グリーン車）
            product_index = 1 if product_type == "green" else 0

            seat_result = await complete_seat_selection(
                page,
                product_index=product_index,
                seat_position=seat_position,
            )

            if not seat_result.success:
                return ExecutorSearchResult(
                    success=False,
                    options=[],
                    message=seat_result.message,
                    screenshot_path=seat_result.screenshot_path,
                )

            # Step 7: 確認画面の情報を取得して1つの提案として返す
            await self._notify_progress("confirm", "予約内容を確認中...")

            # 確認画面から情報を取得
            confirmation_info = await self._get_confirmation_info(page)

            # スクリーンショット
            screenshot_path = f"ex_proposal_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            await page.screenshot(path=screenshot_path)

            # 1つの提案として返す
            proposal = SearchOption(
                id=f"proposal_{selected_train.index}",
                title=f"{selected_train.train_name} {selected_train.departure_time}発",
                description=f"{departure} → {arrival}",
                price=confirmation_info.get("price"),
                available=True,
                details={
                    "train_name": selected_train.train_name,
                    "departure_time": selected_train.departure_time,
                    "arrival_time": selected_train.arrival_time,
                    "departure_station": departure,
                    "arrival_station": arrival,
                    "date": date,
                    "seat_info": confirmation_info.get("seat_info", ""),
                    "price": confirmation_info.get("price"),
                    "screenshot": screenshot_path,
                    "status": "確認画面で待機中",
                },
            )

            return ExecutorSearchResult(
                success=True,
                options=[proposal],  # 1つだけ返す
                message=f"予約準備完了: {selected_train.train_name} {selected_train.departure_time}発 → {selected_train.arrival_time}着",
                screenshot_path=screenshot_path,
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

    async def _ensure_logged_in(
        self,
        page,
        credentials: Optional[Dict[str, str]] = None,
    ) -> bool:
        """ログイン状態を確認し、必要ならログインする（OTP自動処理含む）"""

        if await check_logged_in(page):
            print("[EX_LOGIN] Already logged in")
            return True

        if not credentials:
            print("[EX_LOGIN] No credentials provided")
            return False

        await self._notify_progress("login", "ログイン中...")

        login_result = await login(
            page,
            credentials.get("member_id", credentials.get("email", "")),
            credentials.get("password", ""),
        )

        if login_result.requires_otp:
            # OTPが必要な場合 - 自動処理
            await self._notify_progress("otp", "SMS認証を処理中...")
            print("[EX_LOGIN] OTP required, starting automatic OTP flow")

            from app.executors.ex_reservation.login import request_otp, close_otp_dialog, enter_otp
            from app.services.otp_service import get_otp_service

            # Step 1: SMS送信ボタンをクリック
            otp_request_result = await request_otp(page)
            if not otp_request_result.success:
                print(f"[EX_LOGIN] OTP request failed: {otp_request_result.message}")
                return False
            print(f"[EX_LOGIN] OTP requested: {otp_request_result.message}")

            # Step 2: ダイアログを閉じる
            close_result = await close_otp_dialog(page)
            if not close_result.success:
                print(f"[EX_LOGIN] Warning: {close_result.message}")

            # Step 3: OTPをGmail経由で取得
            await self._notify_progress("otp_wait", "OTPの到着を待機中...")
            print("[EX_LOGIN] Waiting for OTP via Gmail...")

            otp_service = get_otp_service()
            otp_user_id = getattr(self, '_user_id', None)
            if not otp_user_id:
                print("[EX_LOGIN] No user_id for OTP")
                return False

            print(f"[EX_LOGIN] OTP user_id: {otp_user_id[:8]}...")
            otp_code = await otp_service.wait_for_otp(
                user_id=otp_user_id,
                service="ex_reservation",
                source="email",
                timeout_seconds=90,
                poll_interval=5,
            )

            if not otp_code:
                print("[EX_LOGIN] OTP timeout")
                return False

            print(f"[EX_LOGIN] OTP received: {otp_code[:2]}****")

            # Step 4: OTPを入力
            await self._notify_progress("otp_enter", "OTPを入力中...")
            otp_login_result = await enter_otp(page, otp_code)

            if not otp_login_result.success:
                print(f"[EX_LOGIN] OTP login failed: {otp_login_result.message}")
                return False

            print("[EX_LOGIN] OTP login successful")
            return True

        if not login_result.success:
            print(f"[EX_LOGIN] Login failed: {login_result.message}")
            return False

        print("[EX_LOGIN] Login successful")
        return True

    def _normalize_seat_position(self, seat_position: str) -> str:
        """座席位置を正規化"""
        position_map = {
            "窓側": "窓側A",
            "窓": "窓側A",
            "window": "窓側A",
            "通路側": "通路側C",
            "通路": "通路側C",
            "aisle": "通路側C",
            "指定なし": "指定なし",
            "none": "指定なし",
            "any": "指定なし",
        }
        return position_map.get(seat_position.lower() if isinstance(seat_position, str) else seat_position, seat_position)

    def _select_best_train(self, options: List[TrainOption], requested_time: str) -> Optional[TrainOption]:
        """
        最適な列車を選択

        選択基準:
        1. 空席ありの列車のみ対象
        2. 希望時刻に最も近い列車
        """
        available_trains = [t for t in options if t.available]

        if not available_trains:
            return None

        if not requested_time:
            # 時刻指定なしの場合は最初の空席あり列車
            return available_trains[0]

        # 希望時刻をパース
        try:
            requested_hour, requested_min = map(int, requested_time.split(":"))
            requested_minutes = requested_hour * 60 + requested_min
        except:
            return available_trains[0]

        # 各列車の出発時刻との差を計算
        def time_diff(train: TrainOption) -> int:
            try:
                # "19時21分" → 分に変換
                dep_time = train.departure_time
                if "時" in dep_time and "分" in dep_time:
                    h = int(dep_time.split("時")[0])
                    m = int(dep_time.split("時")[1].replace("分", ""))
                    train_minutes = h * 60 + m
                    return abs(train_minutes - requested_minutes)
            except:
                pass
            return 9999

        # 最も近い時刻の列車を返す
        return min(available_trains, key=time_diff)

    async def _get_confirmation_info(self, page) -> Dict[str, Any]:
        """確認画面から情報を取得"""
        info: Dict[str, Any] = {}

        try:
            # 価格を取得
            price_elements = await page.locator('text=/￥[\\d,]+/').all()
            if price_elements:
                for elem in price_elements:
                    text = await elem.text_content()
                    if text and "￥" in text:
                        import re
                        match = re.search(r'￥([\d,]+)', text)
                        if match:
                            info["price"] = int(match.group(1).replace(',', ''))
                            break

            # 座席情報を取得
            seat_elements = await page.locator('text=/[\\d]+号車[\\d]+[A-E]/').all()
            if seat_elements:
                seat_text = await seat_elements[0].text_content()
                info["seat_info"] = seat_text
        except Exception as e:
            print(f"[EX_CONFIRM] Error getting info: {e}")

        return info

    async def _do_execute(
        self,
        task_id: str,
        search_result: TaskSearchResult,
        credentials: Optional[Dict[str, str]] = None,
    ) -> ExecutionResult:
        """
        購入を実行（確認画面から購入ボタンをクリック）

        注意: 現在は安全のため実装していません（execute経由）
        purchaseメソッドを直接使用してください
        """
        return ExecutionResult(
            success=False,
            message="購入機能は安全のため無効化されています。SmartEXサイトで手動で購入してください。",
        )

    async def purchase(
        self,
        params: Dict[str, Any],
        credentials: Optional[Dict[str, str]] = None,
        user_id: Optional[str] = None,
    ) -> ExecutionResult:
        """
        購入を実行（確認画面から購入ボタンをクリック）

        Args:
            params: 購入パラメータ
                - confirm: 実際に購入を実行するか（デフォルト: True）
                - handle_3ds: 3Dセキュア認証を処理するか（デフォルト: True）
            credentials: 認証情報
            user_id: ユーザーID（OTP取得用）

        Returns:
            ExecutionResult: 購入結果
        """
        from app.executors.ex_reservation.purchase import execute_purchase
        from app.services.otp_service import get_otp_service

        page = await get_executor_page()

        # user_idを保持（OTP取得で使用）
        self._user_id = user_id

        try:
            confirm = params.get("confirm", True)
            handle_3ds = params.get("handle_3ds", True)

            print(f"[EX_PURCHASE] Starting purchase: confirm={confirm}, handle_3ds={handle_3ds}")
            print(f"[EX_PURCHASE] user_id set: {user_id[:8] if user_id else 'None'}...")

            # 確認画面にいるかチェック
            from app.executors.ex_reservation.selectors_complete import CONFIRMATION
            confirmation_heading = page.locator(CONFIRMATION["not_complete_heading"])
            is_on_confirmation = await confirmation_heading.count() > 0
            print(f"[EX_PURCHASE] On confirmation page: {is_on_confirmation}")

            # 確認画面にいない場合は検索から自動実行
            if not is_on_confirmation:
                print("[EX_PURCHASE] Not on confirmation page, starting full flow...")
                await self._notify_progress("auto_search", "確認画面にいないため、検索から自動実行します...")

                # 検索を実行して確認画面まで進む
                search_result = await self._do_search(params, credentials)

                if not search_result.success:
                    return ExecutionResult(
                        success=False,
                        message=f"自動検索に失敗: {search_result.message}",
                    )

                # 検索成功後、確認画面にいるはず
                is_on_confirmation = await confirmation_heading.count() > 0
                if not is_on_confirmation:
                    return ExecutionResult(
                        success=False,
                        message="検索後も確認画面に到達できませんでした",
                    )

                print("[EX_PURCHASE] Auto-search completed, now on confirmation page")

            # OTPコールバック（3Dセキュア用）
            async def otp_callback():
                if user_id:
                    otp_service = get_otp_service()
                    otp_code = await otp_service.wait_for_otp(
                        user_id=user_id,
                        service="ex_reservation",
                        source="sms",
                        timeout_seconds=300,
                    )
                    return otp_code
                return None

            # 購入実行
            await self._notify_progress("purchase", "購入処理を実行中...")

            purchase_result = await execute_purchase(
                page,
                confirm=confirm,
                handle_3ds=handle_3ds,
                otp_callback=otp_callback if user_id else None,
            )

            if purchase_result.success:
                return ExecutionResult(
                    success=True,
                    message=purchase_result.message,
                    confirmation_number=purchase_result.reservation_number,
                    details={
                        "reservation_number": purchase_result.reservation_number,
                        "screenshot": purchase_result.screenshot_path,
                    },
                )
            else:
                return ExecutionResult(
                    success=False,
                    message=purchase_result.message,
                    details={
                        "screenshot": purchase_result.screenshot_path,
                    },
                )

        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"[EX_PURCHASE] Error: {e}\n{error_details}")
            return ExecutionResult(
                success=False,
                message=f"購入エラー: {str(e)}",
            )

    async def _do_cancel(
        self,
        params: Dict[str, Any],
        credentials: Optional[Dict[str, str]] = None,
    ) -> ExecutionResult:
        """
        予約をキャンセル（払戻）

        Args:
            params: キャンセルパラメータ
                - reservation_id/reservation_number: 予約番号
                - confirm: 実際にキャンセルを実行するか（デフォルト: False）
        """
        page = await get_executor_page()

        try:
            reservation_id = params.get("reservation_id") or params.get("reservation_number") or ""
            confirm = params.get("confirm", False)

            if not reservation_id:
                return ExecutionResult(
                    success=False,
                    message="予約番号が指定されていません",
                )

            print(f"[EX_CANCEL] Starting cancel: {reservation_id}")

            # ログイン確認
            login_success = await self._ensure_logged_in(page, credentials)
            if not login_success:
                return ExecutionResult(
                    success=False,
                    message="ログインに失敗しました",
                )

            # キャンセル実行
            await self._notify_progress("cancel", f"予約 {reservation_id} をキャンセル中...")

            cancel_result = await cancel_reservation(
                page,
                reservation_number=reservation_id,
                confirm=confirm,
            )

            if cancel_result.success:
                return ExecutionResult(
                    success=True,
                    message=cancel_result.message,
                    details={
                        "reservation_id": reservation_id,
                        "refund_amount": cancel_result.refund_amount,
                        "refund_fee": cancel_result.refund_fee,
                        "screenshot": cancel_result.screenshot_path,
                    },
                )
            else:
                return ExecutionResult(
                    success=False,
                    message=cancel_result.message,
                    details={
                        "screenshot": cancel_result.screenshot_path,
                    },
                )

        except Exception as e:
            import traceback
            traceback.print_exc()

            return ExecutionResult(
                success=False,
                message=f"キャンセルエラー: {str(e)}",
            )
