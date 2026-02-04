"""
EX予約 メインExecutor

リファクタリング: 2026/01/16
- SearchParams/TrainInfoなどの型付きモデルを使用
- print() → logging
- 重複コード排除（正規化ロジックはmodels.pyに統合）
"""

import logging
import re
from typing import Optional, Dict, Any, List
from datetime import datetime

from playwright.async_api import TimeoutError as PlaywrightTimeout

from app.models.schemas import ExecutionResult, SearchResult as TaskSearchResult
from app.executors.base import BaseExecutor, ExecutorSearchResult, SearchOption
from app.tools.browser import get_executor_page, take_screenshot

from app.executors.ex_reservation.models import (
    SearchParams,
    SearchResult,
    TrainInfo,
)
from app.executors.ex_reservation.constants import TIMEOUTS, ERROR_MESSAGES
from app.executors.ex_reservation.errors import (
    CredentialsNotFoundError,
    LoginError,
)
from app.executors.ex_reservation.parser import parse_confirmation_page
from app.executors.ex_reservation.login import login, check_logged_in
from app.executors.ex_reservation.search import (
    search_trains,
    select_train,
)
from app.executors.ex_reservation.seat import complete_seat_selection
from app.executors.ex_reservation.cancel import cancel_reservation
from app.executors.ex_reservation.selectors_complete import CONFIRMATION
from app.services.cancellation import CancellationRegistry, CancelledError

logger = logging.getLogger(__name__)


def _check_cancelled() -> bool:
    """キャンセル状態をチェック（ヘルパー関数）"""
    if CancellationRegistry.check_cancelled():
        session_id = CancellationRegistry.get_current_session()
        logger.info(f"EX Reservation: Operation cancelled (session={session_id})")
        return True
    return False


def _raise_if_cancelled():
    """キャンセルされていたら例外を発生"""
    CancellationRegistry.check_cancelled_raise()


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
            params: 検索パラメータ（SearchParams.from_dict()で正規化）

        Returns:
            ExecutorSearchResult: 1つの提案（確認画面の情報）
        """
        page = await get_executor_page()

        try:
            # パラメータを正規化（Postel's Law: 入力は寛容に）
            search_params = SearchParams.from_dict(params)

            logger.info(
                f"検索開始: {search_params.departure} → {search_params.arrival}, "
                f"{search_params.date} {search_params.time or ''}"
            )
            logger.debug(f"座席: {search_params.seat_position}, 商品: {search_params.product_type}")

            await self._notify_progress("connect", f"{self.service_display_name}にアクセス中...")

            # キャンセルチェック
            _raise_if_cancelled()

            # Step 1: ログイン確認・実行
            if not await self._ensure_logged_in(page, credentials):
                # 認証情報がない場合は credentials_required
                if not credentials:
                    return ExecutorSearchResult(
                        success=False,
                        options=[],
                        message="ログインに必要な認証情報がありません",
                        error_type="credentials_required",
                        requires_credentials=True,
                    )
                # 認証情報はあるがログイン失敗
                return ExecutorSearchResult(
                    success=False,
                    options=[],
                    message="ログインに失敗しました。認証情報を確認してください。",
                    error_type="credentials_invalid",
                )

            # キャンセルチェック
            _raise_if_cancelled()

            # Step 2-4: 検索実行（search_trainsが一連の処理を行う）
            await self._notify_progress("search", f"列車を検索中... {search_params.departure}→{search_params.arrival}")
            search_result = await search_trains(page, search_params)

            if not search_result.success:
                return ExecutorSearchResult(
                    success=False,
                    options=[],
                    message=search_result.message,
                    screenshot_path=search_result.screenshot_path,
                )

            if not search_result.trains:
                return ExecutorSearchResult(
                    success=False,
                    options=[],
                    message=ERROR_MESSAGES["no_trains"],
                    screenshot_path=search_result.screenshot_path,
                    error_type="not_found",
                    recoverable=True,
                )

            # キャンセルチェック
            _raise_if_cancelled()

            # Step 5: 最適な列車を選択
            selected_train = self._select_best_train(search_result.trains, search_params.time)

            if not selected_train:
                return ExecutorSearchResult(
                    success=False,
                    options=[],
                    message=ERROR_MESSAGES["no_seats"],
                    screenshot_path=search_result.screenshot_path,
                    error_type="not_available",
                    recoverable=True,
                )

            logger.info(f"列車選択: {selected_train.train_name} {selected_train.departure_time}発")

            await self._notify_progress("select", f"{selected_train.train_name}を選択中...")
            if not await select_train(page, selected_train.index):
                return ExecutorSearchResult(
                    success=False,
                    options=[],
                    message="列車の選択に失敗しました",
                )

            # キャンセルチェック
            _raise_if_cancelled()

            # Step 6: 座席選択→確認画面まで進む
            await self._notify_progress("seat", "座席を選択中...")

            product_index = 1 if search_params.product_type == "green" else 0

            # 座席表機能の通知
            if search_params.show_seat_map or search_params.prefer_adjacent_empty:
                await self._notify_progress("seat_map", "座席表を確認中...")
            if search_params.specific_seat:
                await self._notify_progress("seat_map", f"指定席 {search_params.specific_seat} を選択中...")

            seat_result = await complete_seat_selection(
                page,
                product_index=product_index,
                seat_position=search_params.seat_position,
                specific_seat=search_params.specific_seat,
                prefer_adjacent_empty=search_params.prefer_adjacent_empty,
                show_seat_map=search_params.show_seat_map,
            )

            if not seat_result.success:
                return ExecutorSearchResult(
                    success=False,
                    options=[],
                    message=seat_result.message,
                    screenshot_path=seat_result.screenshot_path,
                )

            # キャンセルチェック
            _raise_if_cancelled()

            # Step 7: 確認画面の情報を取得
            await self._notify_progress("confirm", "予約内容を確認中...")

            # parser.pyの関数で確認画面をパース
            booking_info = await parse_confirmation_page(page)

            # スクリーンショット
            screenshot_path = f"ex_proposal_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            await page.screenshot(path=screenshot_path)

            # 1つの提案として返す
            price = booking_info.price if booking_info else None
            seat_info = booking_info.seat_info if booking_info else ""
            arrival_time = (
                booking_info.arrival_time if booking_info
                else selected_train.arrival_time
            )

            # 座席表で選択した座席がある場合はそちらを優先
            if seat_result.selected_seat:
                seat_info = seat_result.selected_seat

            # 詳細情報を構築
            details = {
                "train_name": selected_train.train_name,
                "departure_time": selected_train.departure_time,
                "arrival_time": arrival_time,
                "departure_station": search_params.departure,
                "arrival_station": search_params.arrival,
                "date": search_params.date,
                "seat_info": seat_info,
                "price": price,
                "screenshot": screenshot_path,
                "status": "確認画面で待機中",
            }

            # 座席表情報を追加
            if seat_result.seat_map_info:
                details["seat_map_screenshot"] = seat_result.seat_map_info.screenshot_path
                details["available_seats"] = seat_result.seat_map_info.available_seats
                details["car_number"] = seat_result.seat_map_info.car_number

            if seat_result.adjacent_empty_seats:
                details["adjacent_empty_seats"] = seat_result.adjacent_empty_seats

            # 差分情報を追加（第一原理: 要件と結果の差分を報告）
            deviation_dict = None
            if seat_result.deviation:
                deviation_dict = seat_result.deviation.to_dict()
                details["deviation"] = deviation_dict

            # ブラウザ状態を追加
            browser_state_dict = None
            if seat_result.browser_state:
                browser_state_dict = seat_result.browser_state.to_dict()
                details["browser_state"] = browser_state_dict

            proposal = SearchOption(
                id=f"proposal_{selected_train.index}",
                title=f"{selected_train.train_name} {selected_train.departure_time}発",
                description=f"{search_params.departure} → {search_params.arrival}",
                price=price,
                available=True,
                details=details,
            )

            # 座席情報を含むメッセージを構築
            seat_display = seat_info if seat_info else "座席情報なし"
            price_display = f"¥{price:,}" if price else "料金不明"
            message = (
                f"予約準備完了: {selected_train.train_name} "
                f"{selected_train.departure_time}発 → {arrival_time}着\n"
                f"座席: {seat_display}\n"
                f"料金: {price_display}"
            )

            # 隣が空いている席の情報を追加
            if seat_result.adjacent_empty_seats and search_params.prefer_adjacent_empty:
                message += f"\n\n隣が空いている席: {', '.join(seat_result.adjacent_empty_seats[:5])}"
                if seat_result.selected_seat:
                    message += f"\n（{seat_result.selected_seat} を選択しました - 隣も空席）"

            # 差分情報をメッセージに追加（第一原理: 差分があれば必ず報告）
            if seat_result.deviation and seat_result.deviation.has_deviation:
                message += f"\n\n【重要: 要件との差分】\n{seat_result.deviation.describe()}"

            # 結果を構築（差分情報とブラウザ状態を含む）
            # Vision API用: 座席選択のスクリーンショットを含める（ダンが画面を見られるように）
            vision_screenshot = seat_result.screenshot_base64 if seat_result else None

            result = ExecutorSearchResult(
                success=True,
                options=[proposal],
                message=message,
                screenshot_path=screenshot_path,
                screenshot_base64=vision_screenshot,  # Vision API用
            )

            # 差分情報とブラウザ状態を結果に追加
            if deviation_dict:
                result.deviation = deviation_dict
            if browser_state_dict:
                result.browser_state = browser_state_dict

            if vision_screenshot:
                logger.info("[VISION] 座席選択のスクリーンショットを結果に含めました")

            return result

        except CancelledError as e:
            # キャンセルされた
            logger.info(f"検索がキャンセルされました: {e.session_id}")
            return ExecutorSearchResult(
                success=False,
                options=[],
                message="処理がキャンセルされました",
                error_type="cancelled",
            )

        except ValueError as e:
            # SearchParams.from_dict()のバリデーションエラー
            logger.error(f"パラメータエラー: {e}")
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=str(e),
            )

        except PlaywrightTimeout as e:
            screenshot_path = f"error_ex_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            try:
                await take_screenshot(screenshot_path)
            except Exception:
                pass

            # タイムアウト時にセッション切れかどうかチェック
            if await self.detect_session_expired(page):
                logger.info("タイムアウト時にセッション切れを検出")
                return ExecutorSearchResult(
                    success=False,
                    options=[],
                    message="セッションが切れました。再ログインを試みます。",
                    screenshot_path=screenshot_path,
                    error_type="session_expired",
                    recoverable=True,
                )

            logger.error(f"タイムアウト: {e}")
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=f"タイムアウト: {str(e)}",
                screenshot_path=screenshot_path,
                error_type="page_timeout",
                recoverable=True,
            )

        except Exception as e:
            logger.error(f"検索エラー: {e}", exc_info=True)

            # エラー時にセッション切れかどうかチェック
            try:
                if await self.detect_session_expired(page):
                    logger.info("エラー時にセッション切れを検出")
                    return ExecutorSearchResult(
                        success=False,
                        options=[],
                        message="セッションが切れました。再ログインを試みます。",
                        error_type="session_expired",
                        recoverable=True,
                    )
            except Exception:
                pass

            # エラータイプを推定
            error_str = str(e).lower()
            if "timeout" in error_str:
                error_type = "page_timeout"
            elif "selector" in error_str or "not found" in error_str or "locator" in error_str:
                error_type = "selector_not_found"
            elif "login" in error_str or "credential" in error_str or "auth" in error_str:
                error_type = "credentials_invalid"
            else:
                error_type = "internal_error"

            return ExecutorSearchResult(
                success=False,
                options=[],
                message=f"検索エラー: {str(e)}",
                error_type=error_type,
                recoverable=True,
            )

    async def _ensure_logged_in(
        self,
        page,
        credentials: Optional[Dict[str, str]] = None,
    ) -> bool:
        """ログイン状態を確認し、必要ならログインする（OTP自動処理含む）"""

        if await check_logged_in(page):
            logger.debug("ログイン済み")
            return True

        if not credentials:
            logger.warning("認証情報がありません")
            return False

        await self._notify_progress("login", "ログイン中...")

        # 統一スキーマ: credentials["id"] を使用
        login_result = await login(
            page,
            credentials.get("id", ""),
            credentials.get("password", ""),
        )

        if login_result.requires_otp:
            return await self._handle_otp_login(page)

        if not login_result.success:
            logger.error(f"ログイン失敗: {login_result.message}")
            return False

        logger.info("ログイン成功")
        return True

    async def _handle_otp_login(self, page) -> bool:
        """OTP認証を処理"""
        from app.executors.ex_reservation.login import request_otp, close_otp_dialog, enter_otp
        from app.services.otp_service import get_otp_service

        await self._notify_progress("otp", "SMS認証を処理中...")
        logger.info("OTP認証開始")

        # SMS送信
        otp_request_result = await request_otp(page)
        if not otp_request_result.success:
            logger.error(f"OTP送信失敗: {otp_request_result.message}")
            return False

        # ダイアログを閉じる
        await close_otp_dialog(page)

        # OTP取得
        await self._notify_progress("otp_wait", "OTPの到着を待機中...")

        user_id = getattr(self, '_user_id', None)
        if not user_id:
            logger.error("OTP取得に必要なuser_idがありません")
            return False

        otp_service = get_otp_service()
        otp_code = await otp_service.wait_for_otp(
            user_id=user_id,
            service="ex_reservation",
            source="email",
            timeout_seconds=TIMEOUTS["otp_wait"] // 1000,
            poll_interval=5,
        )

        if not otp_code:
            logger.error("OTPタイムアウト")
            return False

        logger.info(f"OTP受信: {otp_code[:2]}****")

        # OTP入力
        await self._notify_progress("otp_enter", "OTPを入力中...")
        otp_login_result = await enter_otp(page, otp_code)

        if not otp_login_result.success:
            logger.error(f"OTP認証失敗: {otp_login_result.message}")
            return False

        logger.info("OTP認証成功")
        return True

    def _select_best_train(
        self, trains: List[TrainInfo], requested_time: Optional[str]
    ) -> Optional[TrainInfo]:
        """
        最適な列車を選択

        選択基準:
        1. 空席ありの列車のみ対象
        2. 希望時刻に最も近い列車
        """
        available_trains = [t for t in trains if t.available]

        if not available_trains:
            return None

        if not requested_time:
            return available_trains[0]

        # 希望時刻をパース
        try:
            if ":" in requested_time:
                requested_hour, requested_min = map(int, requested_time.split(":"))
            else:
                return available_trains[0]
            requested_minutes = requested_hour * 60 + requested_min
        except ValueError:
            return available_trains[0]

        # 各列車の出発時刻との差を計算
        def time_diff(train: TrainInfo) -> int:
            try:
                dep_time = train.departure_time_formatted
                if ":" in dep_time:
                    h, m = map(int, dep_time.split(":"))
                    train_minutes = h * 60 + m
                    return abs(train_minutes - requested_minutes)
            except (ValueError, AttributeError):
                pass
            return 9999

        return min(available_trains, key=time_diff)

    async def _do_execute(
        self,
        task_id: str,
        search_result: TaskSearchResult,
        credentials: Optional[Dict[str, str]] = None,
    ) -> ExecutionResult:
        """
        購入を実行（確認画面から購入ボタンをクリック）

        注意: purchaseメソッドを直接使用してください
        """
        return ExecutionResult(
            success=False,
            message="purchaseメソッドを直接使用してください",
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
            # キャンセルチェック
            _raise_if_cancelled()

            confirm = params.get("confirm", True)
            handle_3ds = params.get("handle_3ds", True)

            logger.info(f"購入開始: confirm={confirm}, handle_3ds={handle_3ds}")

            # 確認画面にいるかチェック
            confirmation_heading = page.locator(CONFIRMATION["not_complete_heading"])
            is_on_confirmation = await confirmation_heading.count() > 0

            # 確認画面にいない場合は検索から自動実行
            if not is_on_confirmation:
                logger.info("確認画面にいないため、検索から自動実行")
                await self._notify_progress("auto_search", "確認画面にいないため、検索から自動実行します...")

                search_result = await self._do_search(params, credentials)

                if not search_result.success:
                    return ExecutionResult(
                        success=False,
                        message=f"自動検索に失敗: {search_result.message}",
                    )

                is_on_confirmation = await confirmation_heading.count() > 0
                if not is_on_confirmation:
                    return ExecutionResult(
                        success=False,
                        message="検索後も確認画面に到達できませんでした",
                    )

            # OTPコールバック（3Dセキュア用）
            # 3DS OTPはSMS→SMS Forwarder→Gmailで転送されるため、source="email"でIMAPメソッドを使用
            async def otp_callback():
                if user_id:
                    otp_service = get_otp_service()
                    return await otp_service.wait_for_otp(
                        user_id=user_id,
                        service="3ds",  # 3DS用のサービス名（カード会社共通）
                        source="email",  # SMS ForwarderでGmailに転送されたものをIMAPで取得
                        timeout_seconds=TIMEOUTS["3ds_wait"] // 1000,
                    )
                return None

            # キャンセルチェック
            _raise_if_cancelled()

            # 購入実行
            await self._notify_progress("purchase", "購入処理を実行中...")

            purchase_result = await execute_purchase(
                page,
                confirm=confirm,
                handle_3ds=handle_3ds,
                otp_callback=otp_callback if user_id else None,
            )

            if purchase_result.success:
                logger.info(f"購入成功: {purchase_result.reservation_number}")
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
                logger.error(f"購入失敗: {purchase_result.message}")
                return ExecutionResult(
                    success=False,
                    message=purchase_result.message,
                    details={
                        "screenshot": purchase_result.screenshot_path,
                    },
                )

        except CancelledError as e:
            logger.info(f"購入がキャンセルされました: {e.session_id}")
            return ExecutionResult(
                success=False,
                message="購入処理がキャンセルされました",
            )

        except Exception as e:
            logger.error(f"購入エラー: {e}", exc_info=True)
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
                - reservation_id/reservation_number: 予約番号（省略時は最新の予約を自動検出）
                - departure_date: 出発日（予約特定用、オプション）
                - train_name: 列車名（予約特定用、オプション）
                - confirm: 実際にキャンセルを実行するか（デフォルト: False）
        """
        page = await get_executor_page()

        try:
            # キャンセルチェック
            _raise_if_cancelled()

            # パラメータ取得（複数の名前を受け付ける）
            reservation_id = (
                params.get("reservation_id") or
                params.get("reservation_number") or
                ""
            )
            # ユーザーが「キャンセルして」と言った場合は実行する（デフォルトTrue）
            confirm = params.get("confirm", True)
            departure_date = params.get("departure_date", "")
            train_name = params.get("train_name", "")

            # キャンセルチェック
            _raise_if_cancelled()

            # ログイン確認（予約一覧を見るために先にログイン）
            if not await self._ensure_logged_in(page, credentials):
                return ExecutionResult(
                    success=False,
                    message="ログインに失敗しました",
                )

            # 予約番号が指定されていない場合、予約一覧から自動検出
            # この場合、予約一覧画面に遷移するのでcancel_reservationでの再遷移をスキップ
            already_on_reservation_list = False
            if not reservation_id:
                await self._notify_progress("cancel", "予約一覧を確認中...")
                logger.info("予約番号が未指定のため、予約一覧から検索します")
                already_on_reservation_list = True  # 予約一覧に遷移する

                # メニューを開く
                menu_button = page.locator('button:has-text("メニュー"), a:has-text("メニュー")').first
                if await menu_button.count() > 0:
                    await menu_button.click()
                    await page.wait_for_timeout(2000)

                # 予約確認リンクをクリック
                reservation_link_selectors = [
                    'a:has-text("予約確認/変更/払戻")',
                    'a:has-text("予約確認")',
                ]
                for selector in reservation_link_selectors:
                    link = page.locator(selector).first
                    if await link.count() > 0:
                        await link.click()
                        await page.wait_for_timeout(3000)
                        break

                # 予約一覧ページのスクリーンショット
                screenshot_list = f"ex_reservation_list_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
                await page.screenshot(path=screenshot_list)

                # 予約カードを取得（各予約は通常カード形式で表示される）
                # 予約情報を含む要素を探す
                reservations_found = []

                # 予約件数が1件で払戻ボタンがある場合、予約番号不要で直接払戻可能
                refund_buttons = await page.locator('button:has-text("払戻"), a:has-text("払戻"), input[value*="払戻"]').all()
                logger.info(f"払戻ボタン数: {len(refund_buttons)}")

                if len(refund_buttons) == 1:
                    # 予約が1件のみ - 予約番号を取得して直接キャンセル処理へ
                    # お預かり番号を探す
                    try:
                        reservation_text = await page.locator('text=/お預かり番号/').first.text_content() or ""
                        match = re.search(r'(\d{4,})', reservation_text)
                        if match:
                            reservation_id = match.group(1)
                            logger.info(f"予約が1件のみ、自動選択: {reservation_id}")
                            await self._notify_progress("cancel", f"予約番号 {reservation_id} を選択しました")
                        else:
                            # 予約番号が取れなくても、1件だけなので続行
                            reservation_id = "auto"
                            logger.info("予約番号不明だが1件のみのため自動選択")
                    except Exception as e:
                        reservation_id = "auto"
                        logger.info(f"予約番号取得エラー、1件のみのため自動選択: {e}")
                elif len(refund_buttons) == 0:
                    # 払戻ボタンがない = 予約がない
                    return ExecutionResult(
                        success=False,
                        message="予約が見つかりませんでした。予約一覧に払戻ボタンがありません。",
                        details={"screenshot": screenshot_list},
                    )
                else:
                    # 複数の払戻ボタンがある = 複数予約、マッチングが必要
                    logger.info(f"複数予約あり ({len(refund_buttons)}件)、予約番号でマッチング")

                    # 予約番号（4桁以上）を含む要素を全て取得
                    reservation_number_elements = await page.locator('text=/お預かり番号/').all()
                    logger.info(f"お預かり番号要素数: {len(reservation_number_elements)}")

                    for elem in reservation_number_elements:
                        try:
                            text = await elem.text_content() or ""
                            match = re.search(r'(\d{4,})', text)
                            if match:
                                res_num = match.group(1)
                                # 親要素から予約情報を取得（列車名、日付など）
                                parent = elem.locator('..')
                                parent_text = ""
                                try:
                                    parent_text = await parent.text_content() or ""
                                except:
                                    pass

                                grandparent_text = ""
                                try:
                                    grandparent = parent.locator('..')
                                    grandparent_text = await grandparent.text_content() or ""
                                except:
                                    pass

                                full_context = f"{text} {parent_text} {grandparent_text}"

                                reservations_found.append({
                                    "reservation_number": res_num,
                                    "context": full_context[:200],
                                })
                        except Exception as e:
                            logger.debug(f"予約情報取得エラー: {e}")
                            continue

                    # 重複を除去
                    seen = set()
                    unique_reservations = []
                    for res in reservations_found:
                        if res["reservation_number"] not in seen:
                            seen.add(res["reservation_number"])
                            unique_reservations.append(res)

                    if not unique_reservations:
                        return ExecutionResult(
                            success=False,
                            message="複数予約があるようですが、予約番号を取得できませんでした。",
                            details={"screenshot": screenshot_list},
                        )

                    logger.info(f"予約を{len(unique_reservations)}件発見")

                    # 予約が1件のみの場合 → そのままキャンセル
                    if len(unique_reservations) == 1:
                        reservation_id = unique_reservations[0]["reservation_number"]
                        logger.info(f"予約が1件のみのため自動選択: {reservation_id}")
                        await self._notify_progress("cancel", f"予約番号 {reservation_id} を選択しました")

                    # 予約が複数あり、文脈情報（日付・列車名）がある場合 → マッチングを試みる
                    elif len(unique_reservations) > 1 and (departure_date or train_name):
                        logger.info(f"複数予約あり、文脈情報でマッチング: date={departure_date}, train={train_name}")
                        matched = None

                        for res in unique_reservations:
                            context = res["context"]
                            # 日付でマッチング（YYYY-MM-DD → MM/DD や M月D日 形式にも対応）
                            date_match = False
                            if departure_date:
                                # 様々な日付形式をチェック
                                date_patterns = [
                                    departure_date,  # 2026-02-10
                                    departure_date.replace("-", "/"),  # 2026/02/10
                                    f"{int(departure_date[5:7])}月{int(departure_date[8:10])}日",  # 2月10日
                                    f"{int(departure_date[5:7])}/{int(departure_date[8:10])}",  # 2/10
                                ]
                                for dp in date_patterns:
                                    if dp in context:
                                        date_match = True
                                        break

                            # 列車名でマッチング
                            train_match = False
                            if train_name:
                                # 「のぞみ37号」→「のぞみ」「37」などで部分マッチ
                                train_parts = re.findall(r'[ぁ-んァ-ン一-龥]+|\d+', train_name)
                                train_match = all(part in context for part in train_parts if part)

                            # 両方指定されている場合は両方マッチ、片方のみの場合はその条件でマッチ
                            if departure_date and train_name:
                                if date_match and train_match:
                                    matched = res
                                    break
                            elif departure_date and date_match:
                                matched = res
                                break
                            elif train_name and train_match:
                                matched = res
                                break

                        if matched:
                            reservation_id = matched["reservation_number"]
                            logger.info(f"文脈情報にマッチした予約を選択: {reservation_id}")
                            await self._notify_progress("cancel", f"予約番号 {reservation_id} をマッチしました")
                        else:
                            # マッチしない場合は一覧を返す
                            reservations_list = "\n".join([
                                f"・{res['reservation_number']}: {res['context'][:50]}..."
                                for res in unique_reservations
                            ])
                            return ExecutionResult(
                                success=False,
                                message=f"複数の予約が見つかりましたが、指定された条件にマッチするものがありませんでした。\n\n予約一覧:\n{reservations_list}\n\nキャンセルしたい予約番号を指定してください。",
                                details={
                                    "screenshot": screenshot_list,
                                    "reservations": unique_reservations,
                                },
                            )

                    # 予約が複数あり、文脈情報もない場合 → 一覧を返してユーザーに選択を促す
                    else:
                        reservations_list = "\n".join([
                            f"・{res['reservation_number']}: {res['context'][:50]}..."
                            for res in unique_reservations
                        ])
                        return ExecutionResult(
                            success=False,
                            message=f"複数の予約が見つかりました。どの予約をキャンセルしますか？\n\n{reservations_list}\n\nキャンセルしたい予約番号を指定してください。",
                            details={
                                "screenshot": screenshot_list,
                                "reservations": unique_reservations,
                            },
                        )

            logger.info(f"キャンセル開始: {reservation_id}")

            # キャンセル実行（既にログイン済み）
            await self._notify_progress("cancel", f"予約 {reservation_id} をキャンセル中...")

            cancel_result = await cancel_reservation(
                page,
                reservation_number=reservation_id,
                confirm=confirm,
                skip_navigation=already_on_reservation_list,
            )

            if cancel_result.success:
                logger.info(f"キャンセル成功: 返金額 {cancel_result.refund_amount}")
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
                logger.error(f"キャンセル失敗: {cancel_result.message}")
                return ExecutionResult(
                    success=False,
                    message=cancel_result.message,
                    details={
                        "screenshot": cancel_result.screenshot_path,
                    },
                )

        except CancelledError as e:
            logger.info(f"キャンセル処理が中断されました: {e.session_id}")
            return ExecutionResult(
                success=False,
                message="キャンセル処理が中断されました",
            )

        except Exception as e:
            logger.error(f"キャンセルエラー: {e}", exc_info=True)
            return ExecutionResult(
                success=False,
                message=f"キャンセルエラー: {str(e)}",
            )

    async def cancel(
        self,
        params: Dict[str, Any],
        credentials: Optional[Dict[str, str]] = None,
        user_id: Optional[str] = None,
    ) -> ExecutionResult:
        """
        予約をキャンセル（払戻）

        Args:
            params: キャンセルパラメータ
                - reservation_id/reservation_number: 予約番号
                - confirm: 実際にキャンセルを実行するか
            credentials: 認証情報
            user_id: ユーザーID

        Returns:
            ExecutionResult: キャンセル結果
        """
        # user_idを保持（OTP取得で使用）
        self._user_id = user_id
        return await self._do_cancel(params, credentials)

    # ========================================
    # セッション切れ自動再試行（Session Auto-Retry）
    # ========================================

    def supports_auto_relogin(self) -> bool:
        """EX予約は自動再ログインをサポート（OTP不要時のみ）"""
        return True

    async def detect_session_expired(self, page) -> bool:
        """
        セッション切れを検出

        検出条件:
        1. ログインページにリダイレクトされた（URLまたはログインフォームの存在）
        2. セッションタイムアウトのエラーメッセージ表示

        Args:
            page: Playwrightページ

        Returns:
            セッション切れの場合True
        """
        from app.executors.ex_reservation.selectors_complete import LOGIN, URLS

        try:
            current_url = page.url

            # 1. ログインページにリダイレクトされた
            if "smart_index" in current_url or current_url == URLS["login"]:
                logger.info("セッション切れ検出: ログインページにリダイレクト")
                return True

            # 2. ログインフォームが表示されている
            login_button = page.locator(LOGIN["login_button"])
            if await login_button.count() > 0:
                # ログインボタンがあり、かつマイページの要素がない場合
                from app.executors.ex_reservation.selectors_complete import MYPAGE
                search_button = page.locator(MYPAGE["search_train"])
                if await search_button.count() == 0:
                    logger.info("セッション切れ検出: ログインフォーム表示")
                    return True

            # 3. セッションタイムアウトのエラーメッセージ
            error_messages = [
                "セッションがタイムアウト",
                "セッションが切れ",
                "再度ログイン",
                "ログインし直し",
            ]
            page_text = await page.inner_text("body")
            for msg in error_messages:
                if msg in page_text:
                    logger.info(f"セッション切れ検出: エラーメッセージ '{msg}'")
                    return True

            return False

        except Exception as e:
            logger.warning(f"セッション切れ検出中にエラー: {e}")
            return False

    async def re_login(
        self,
        page,
        credentials: Dict[str, str],
        user_id: Optional[str] = None,
    ) -> bool:
        """
        セッション切れ後に再ログインを実行

        注意: OTPが必要な場合はFalseを返す（自動再ログイン不可）

        Args:
            page: Playwrightページ
            credentials: 認証情報（member_id, password）
            user_id: ユーザーID（OTP取得に必要だが、自動再ログインではOTPスキップ）

        Returns:
            再ログイン成功の場合True、OTP必要や失敗の場合False
        """
        try:
            logger.info("EX予約: 再ログイン開始")

            # 統一スキーマ: credentials["id"] を使用
            login_result = await login(
                page,
                credentials.get("id", ""),
                credentials.get("password", ""),
            )

            # OTPが必要な場合は自動再ログイン不可
            if login_result.requires_otp:
                logger.info("再ログイン: OTPが必要なため自動再ログイン不可")
                return False

            if not login_result.success:
                logger.warning(f"再ログイン失敗: {login_result.message}")
                return False

            logger.info("EX予約: 再ログイン成功")
            return True

        except Exception as e:
            logger.error(f"再ログイン中にエラー: {e}", exc_info=True)
            return False
