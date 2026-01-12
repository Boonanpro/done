"""
EX予約 ログイン処理

実確認日: 2026/01/09
- ログイン状態確認
- ログイン実行
- OTP（電話認証）処理
"""

from typing import Optional, Callable, Awaitable
from dataclasses import dataclass
from enum import Enum
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from app.executors.ex_reservation.selectors import URLS, LOGIN, OTP, COMMON


class PageState(Enum):
    """ページ状態"""
    UNKNOWN = "unknown"
    LOGIN_FORM = "login_form"
    OTP_REQUIRED = "otp_required"
    LOGGED_IN = "logged_in"
    ERROR = "error"


@dataclass
class LoginResult:
    """ログイン結果"""
    success: bool
    message: str
    requires_otp: bool = False
    page_state: PageState = PageState.UNKNOWN


async def detect_page_state(page: Page) -> PageState:
    """
    現在のページ状態を検出

    Returns:
        PageState: ページ状態
    """
    try:
        # OTP画面かチェック（音声OTPまたはSMS OTPボタンの存在で判定）
        voice_otp_exists = await page.locator(OTP["send_voice_button"]).count() > 0
        sms_otp_exists = await page.locator(OTP["send_sms_button"]).count() > 0

        if voice_otp_exists or sms_otp_exists:
            return PageState.OTP_REQUIRED

        # ログイン済みかチェック
        if await page.locator(COMMON["logged_in"]).count() > 0:
            return PageState.LOGGED_IN

        # ログインフォームかチェック
        if await page.locator(LOGIN["member_id"]).count() > 0:
            return PageState.LOGIN_FORM

        # エラーかチェック
        if await page.locator(COMMON["error"]).count() > 0:
            return PageState.ERROR

        return PageState.UNKNOWN
    except Exception:
        return PageState.UNKNOWN


async def check_logged_in(page: Page) -> bool:
    """
    ログイン状態を確認
    
    Returns:
        True: ログイン済み
        False: 未ログイン
    """
    try:
        return await page.locator(COMMON["logged_in"]).count() > 0
    except Exception:
        return False


async def login(
    page: Page,
    member_id: str,
    password: str,
) -> LoginResult:
    """
    SmartEXにログイン
    
    Args:
        page: Playwrightページ
        member_id: 会員ID（数字10桁）
        password: パスワード（英数記号4-8桁）
        
    Returns:
        LoginResult: ログイン結果
    """
    try:
        # ログインページにアクセス
        await page.goto(URLS["login"], wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
        
        # 会員ID入力
        member_id_locator = page.locator(LOGIN["member_id"])
        if await member_id_locator.count() == 0:
            return LoginResult(
                success=False,
                message="会員ID入力フィールドが見つかりません",
                page_state=PageState.UNKNOWN,
            )
        await member_id_locator.fill(member_id)
        
        await page.wait_for_timeout(500)
        
        # パスワード入力
        password_locator = page.locator(LOGIN["password"])
        if await password_locator.count() == 0:
            return LoginResult(
                success=False,
                message="パスワード入力フィールドが見つかりません",
                page_state=PageState.UNKNOWN,
            )
        await password_locator.fill(password)
        
        await page.wait_for_timeout(500)
        
        # ログインボタンをクリック
        login_button_locator = page.locator(LOGIN["login_button"])
        if await login_button_locator.count() > 0:
            await login_button_locator.click()
        else:
            await page.keyboard.press("Enter")
        
        # ページ遷移を待機
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(3000)
        
        # ページ状態を検出
        state = await detect_page_state(page)
        
        if state == PageState.OTP_REQUIRED:
            return LoginResult(
                success=False,
                message="ワンタイムパスワード（OTP認証）が必要です",
                requires_otp=True,
                page_state=state,
            )
        
        if state == PageState.LOGGED_IN:
            return LoginResult(
                success=True,
                message="ログイン成功",
                page_state=state,
            )
        
        if state == PageState.ERROR:
            return LoginResult(
                success=False,
                message="ログイン失敗: 会員IDまたはパスワードが正しくありません",
                page_state=state,
            )
        
        # URLでログイン状態を判定
        current_url = page.url
        if "login" in current_url.lower() or "index.htm" in current_url.lower():
            return LoginResult(
                success=False,
                message="ログイン失敗: ログインページに留まっています",
                page_state=PageState.LOGIN_FORM,
            )
        
        # ClientServiceに遷移していれば成功と判定
        if "ClientService" in current_url:
            return LoginResult(
                success=True,
                message="ログイン成功",
                page_state=PageState.LOGGED_IN,
            )
        
        return LoginResult(
            success=True,
            message="ログイン成功（推定）",
            page_state=state,
        )
        
    except PlaywrightTimeout:
        return LoginResult(
            success=False,
            message="タイムアウト: ログインページの読み込みに失敗しました",
            page_state=PageState.UNKNOWN,
        )
    except Exception as e:
        return LoginResult(
            success=False,
            message=f"ログインエラー: {str(e)}",
            page_state=PageState.UNKNOWN,
        )


async def request_otp(page: Page) -> LoginResult:
    """
    OTP（電話認証またはSMS認証）を要求

    「自動音声案内発信」ボタンまたは「SMS送信」ボタンをクリックしてOTPを発信する

    Returns:
        LoginResult: 結果
    """
    try:
        # SMS送信ボタンがあるかチェック
        sms_button = page.locator(OTP["send_sms_button"])
        if await sms_button.count() > 0:
            print("[REQUEST_OTP] SMS送信ボタンを検出しました")
            await sms_button.click()
            await page.wait_for_timeout(2000)
            return LoginResult(
                success=True,
                message="SMS認証を送信しました。登録済み電話番号にSMSが届きます。",
            )

        # 音声案内発信ボタンがあるかチェック
        voice_button = page.locator(OTP["send_voice_button"])
        if await voice_button.count() > 0:
            print("[REQUEST_OTP] 自動音声案内発信ボタンを検出しました")
            await voice_button.click()
            await page.wait_for_timeout(2000)
            return LoginResult(
                success=True,
                message="電話認証を発信しました。登録済み電話番号に着信があります。",
            )

        return LoginResult(
            success=False,
            message="OTP発信ボタン（SMS送信または自動音声案内発信）が見つかりません",
        )

    except Exception as e:
        return LoginResult(
            success=False,
            message=f"OTP発信エラー: {str(e)}",
        )


async def close_otp_dialog(page: Page) -> LoginResult:
    """
    OTP発信後のダイアログを閉じる

    「自動音声案内を発信します。」のダイアログの「閉じる」ボタンをクリック
    このダイアログが前面にあると、OTP入力フィールドや次へボタンがブロックされる

    Returns:
        LoginResult: 結果
    """
    try:
        print("[CLOSE_DIALOG] ダイアログが表示されるまで待機中...")
        # ダイアログが表示されるまで少し待つ
        await page.wait_for_timeout(3000)

        print("[CLOSE_DIALOG] ダイアログの「閉じる」ボタンを探します...")

        # スクリーンショット保存（デバッグ用）
        try:
            screenshot_path = "screenshots/otp_dialog_debug.png"
            import os
            os.makedirs("screenshots", exist_ok=True)
            await page.screenshot(path=screenshot_path)
            print(f"[CLOSE_DIALOG] デバッグ用スクリーンショット保存: {screenshot_path}")
        except Exception:
            pass

        # より広範囲に全てのボタンを取得して探す
        print("[CLOSE_DIALOG] 全ボタンをスキャンします...")
        all_buttons = await page.locator('button, input[type="button"], input[type="submit"], a').all()
        print(f"[CLOSE_DIALOG] 見つかったボタン数: {len(all_buttons)}")

        close_button = None
        button_info = ""

        for i, btn in enumerate(all_buttons):
            try:
                is_visible = await btn.is_visible()
                if not is_visible:
                    continue

                # タグ、テキスト、value属性を取得
                tag = await btn.evaluate("el => el.tagName") or ""
                text = (await btn.text_content() or "").strip()
                value = await btn.get_attribute("value") or ""
                class_name = await btn.get_attribute("class") or ""
                onclick = await btn.get_attribute("onclick") or ""

                info = f"[{i}] <{tag}> text=\"{text}\" value=\"{value}\" class=\"{class_name}\""
                print(f"[CLOSE_DIALOG]   {info}")

                # 「閉じる」を含むか判定（柔軟に）
                search_text = (text + value + class_name + onclick).lower()
                if any(keyword in search_text for keyword in ["閉じる", "close", "とじる", "閉", "×", "x"]):
                    print(f"[CLOSE_DIALOG] OK 候補発見: {info}")
                    if close_button is None:  # 最初に見つかったものを使う
                        close_button = btn
                        button_info = info

            except Exception as e:
                print(f"[CLOSE_DIALOG]   [{i}] エラー: {e}")
                continue

        if not close_button:
            print("[CLOSE_DIALOG] × 標準検索で閉じるボタンが見つかりません")
            print("[CLOSE_DIALOG] ダイアログ内を直接検索します...")

            # ダイアログ内の閉じるボタンを直接探す
            dialog_close_selectors = [
                'text="閉じる"',
                'text="x 閉じる"',
                ':text("閉じる")',
                '[class*="close"]',
                '[class*="LBX"] >> text="閉じる"',
            ]

            for selector in dialog_close_selectors:
                print(f"[CLOSE_DIALOG]   試行: {selector}")
                try:
                    locator = page.locator(selector)
                    count = await locator.count()
                    if count > 0:
                        print(f"[CLOSE_DIALOG]   OK 見つかった: {selector}")
                        close_button = locator.first
                        button_info = selector
                        break
                except Exception as e:
                    print(f"[CLOSE_DIALOG]   エラー: {e}")
                    continue

        if not close_button:
            print("[CLOSE_DIALOG] × 閉じるボタンが見つかりません")
            return LoginResult(
                success=False,
                message="閉じるボタンが見つかりません",
            )

        print(f"[CLOSE_DIALOG] 閉じるボタンをクリックします: {button_info}")
        try:
            # force: true でオーバーレイを無視してクリック
            await close_button.click(force=True, timeout=5000)
            print("[CLOSE_DIALOG] OK クリック成功")
        except Exception as e:
            print(f"[CLOSE_DIALOG] × クリック失敗: {e}")
            print("[CLOSE_DIALOG] JavaScriptで直接クリックを試みます...")
            try:
                await close_button.evaluate("el => el.click()")
                print("[CLOSE_DIALOG] OK JavaScriptクリック成功")
            except Exception as js_error:
                print(f"[CLOSE_DIALOG] × JavaScriptクリックも失敗: {js_error}")
                return LoginResult(
                    success=False,
                    message=f"閉じるボタンをクリックできません: {js_error}",
                )

        await page.wait_for_timeout(1500)

        print("[CLOSE_DIALOG] OK ダイアログを閉じました")
        return LoginResult(
            success=True,
            message="ダイアログを閉じました",
        )

    except Exception as e:
        print(f"[CLOSE_DIALOG] × エラー: {str(e)}")
        import traceback
        traceback.print_exc()
        return LoginResult(
            success=False,
            message=f"ダイアログを閉じるエラー: {str(e)}",
        )


async def complete_otp_login(page: Page, otp_code: str) -> LoginResult:
    """
    OTP（ワンタイムパスワード）ログインの完全フロー

    1. 自動音声案内発信ボタンをクリック
    2. ダイアログの「閉じる」ボタンをクリック
    3. OTPを入力
    4. OKボタンをクリックしてログイン完了

    Args:
        page: Playwrightページ
        otp_code: 6桁のワンタイムパスワード（ユーザーが電話で取得）

    Returns:
        LoginResult: ログイン結果
    """
    try:
        print("[OTP] Step 1: 自動音声案内発信ボタンをクリック")
        # Step 1: 自動音声案内発信
        request_result = await request_otp(page)
        if not request_result.success:
            return request_result

        print("[OTP] Step 2: 「閉じる」ボタンをクリック")
        # Step 2: ダイアログを閉じる
        close_result = await close_otp_dialog(page)
        if not close_result.success:
            # 「閉じる」ボタンが見つからない場合は続行を試みる
            print(f"[OTP] Warning: {close_result.message}, 続行します")

        print("[OTP] Step 3: OTPを入力してOKをクリック")
        # Step 3: OTPを入力してログイン
        return await enter_otp(page, otp_code)

    except Exception as e:
        return LoginResult(
            success=False,
            message=f"OTPログインエラー: {str(e)}",
        )


async def enter_otp(page: Page, otp_code: str) -> LoginResult:
    """
    OTP（ワンタイムパスワード）を入力

    Args:
        page: Playwrightページ
        otp_code: 6桁のワンタイムパスワード

    Returns:
        LoginResult: 結果
    """
    try:
        print(f"[OTP_ENTER] OTPコード入力開始: {otp_code}")

        # OTP入力フィールドを探す
        otp_input = page.locator(OTP["otp_input"])
        if await otp_input.count() == 0:
            print("[OTP_ENTER] エラー: OTP入力フィールドが見つかりません")
            return LoginResult(
                success=False,
                message="OTP入力フィールドが見つかりません",
            )

        print("[OTP_ENTER] OTP入力フィールドが見つかりました")

        # OTPを入力
        await otp_input.fill(otp_code)
        print(f"[OTP_ENTER] OTPを入力しました: {otp_code}")

        await page.wait_for_timeout(1000)

        # 次へボタンをクリック
        next_button = page.locator(OTP["next_button"])
        next_count = await next_button.count()
        print(f"[OTP_ENTER] 「次へ」ボタン検索結果: {next_count}件")

        if next_count > 0:
            is_enabled = await next_button.is_enabled()
            is_visible = await next_button.is_visible()
            print(f"[OTP_ENTER] 「次へ」ボタン状態: 有効={is_enabled}, 表示={is_visible}")

            if is_enabled and is_visible:
                print("[OTP_ENTER] 「次へ」ボタンをクリックします...")
                await next_button.click()
                print("[OTP_ENTER] 「次へ」ボタンをクリックしました")
            else:
                print("[OTP_ENTER] ボタンが無効または非表示のため、Enterキーを押します")
                await page.keyboard.press("Enter")
        else:
            print("[OTP_ENTER] 「次へ」ボタンが見つからないため、Enterキーを押します")
            await page.keyboard.press("Enter")

        # ページ遷移を待機
        print("[OTP_ENTER] ページ遷移を待機中...")
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
        await page.wait_for_timeout(3000)

        current_url = page.url
        print(f"[OTP_ENTER] 現在のURL: {current_url}")

        # ページ状態を検出
        state = await detect_page_state(page)
        print(f"[OTP_ENTER] ページ状態: {state.value}")

        if state == PageState.LOGGED_IN:
            print("[OTP_ENTER] OK ログイン成功を検出")
            return LoginResult(
                success=True,
                message="OTP認証成功",
                page_state=state,
            )

        if state == PageState.ERROR:
            print("[OTP_ENTER] × エラーを検出")
            return LoginResult(
                success=False,
                message="OTP認証失敗: コードが正しくありません",
                page_state=state,
            )

        # URLで判定
        if "ClientService" in current_url:
            print("[OTP_ENTER] OK URLからログイン成功を判定")
            return LoginResult(
                success=True,
                message="OTP認証成功",
                page_state=PageState.LOGGED_IN,
            )

        print(f"[OTP_ENTER] × 不明な状態: state={state.value}, url={current_url}")
        return LoginResult(
            success=False,
            message=f"OTP認証失敗: 不明なエラー (state={state.value})",
            page_state=state,
        )

    except PlaywrightTimeout as e:
        print(f"[OTP_ENTER] × タイムアウト: {str(e)}")
        return LoginResult(
            success=False,
            message="タイムアウト: OTP認証に失敗しました",
        )
    except Exception as e:
        print(f"[OTP_ENTER] × エラー: {str(e)}")
        import traceback
        traceback.print_exc()
        return LoginResult(
            success=False,
            message=f"OTPエラー: {str(e)}",
        )


async def complete_otp_authentication(
    page: Page,
    otp_callback: Callable[[], Awaitable[str]],
) -> LoginResult:
    """
    OTP認証処理を完了する

    login()でOTPが必要と判定された後に呼び出す。

    1. 音声OTPを発信
    2. ダイアログを閉じる
    3. コールバックでOTPを取得
    4. OTPを入力してログイン完了

    Args:
        page: Playwrightページ（OTP画面にいる状態）
        otp_callback: OTPを取得するコールバック関数（async）

    Returns:
        LoginResult: ログイン結果
    """
    try:
        print("[OTP_AUTH] OTP認証を開始します")

        # Step 1: 音声OTPを発信
        print("[OTP_AUTH] 自動音声案内を発信します...")
        request_result = await request_otp(page)
        if not request_result.success:
            return request_result

        print("[OTP_AUTH] 電話が発信されました。登録済み電話番号に着信があります。")

        # Step 2: ダイアログを閉じる（必須）
        print("[OTP_AUTH] ダイアログを閉じます...")
        close_result = await close_otp_dialog(page)
        if not close_result.success:
            print(f"[OTP_AUTH] × エラー: {close_result.message}")
            return LoginResult(
                success=False,
                message=f"ダイアログを閉じることができません: {close_result.message}",
                requires_otp=True,
                page_state=PageState.OTP_REQUIRED,
            )

        print("[OTP_AUTH] OK ダイアログを閉じました")

        # Step 3: コールバックでOTPを取得
        print("[OTP_AUTH] OTPの入力を待っています...")
        otp_code = await otp_callback()

        if not otp_code or len(otp_code) != 6:
            return LoginResult(
                success=False,
                message=f"無効なOTPコード: {otp_code}",
                requires_otp=True,
                page_state=PageState.OTP_REQUIRED,
            )

        print(f"[OTP_AUTH] OTPを取得しました: {otp_code}")

        # Step 4: OTPを入力してログイン
        print("[OTP_AUTH] OTPを入力してログインします...")
        otp_result = await enter_otp(page, otp_code)

        if otp_result.success:
            print("[OTP_AUTH] OK OTPログイン成功")
        else:
            print(f"[OTP_AUTH] NG OTPログイン失敗: {otp_result.message}")

        return otp_result

    except Exception as e:
        print(f"[OTP_AUTH] エラー: {str(e)}")
        import traceback
        traceback.print_exc()

        return LoginResult(
            success=False,
            message=f"OTP認証エラー: {str(e)}",
            page_state=PageState.UNKNOWN,
        )
