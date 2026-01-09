"""
EX予約 ログイン処理

実確認日: 2026/01/09
- ログイン状態確認
- ログイン実行
- OTP（電話認証）処理
"""

from typing import Optional
from dataclasses import dataclass
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from app.executors.ex_reservation.selectors import URLS, LOGIN, OTP, COMMON


@dataclass
class LoginResult:
    """ログイン結果"""
    success: bool
    message: str
    requires_otp: bool = False


async def check_logged_in(page: Page) -> bool:
    """
    ログイン状態を確認
    
    Returns:
        True: ログイン済み
        False: 未ログイン
    """
    try:
        logout_link = await page.query_selector(COMMON["logged_in"])
        return logout_link is not None
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
        await page.wait_for_timeout(1000)
        
        # 会員ID入力
        member_id_input = await page.query_selector(LOGIN["member_id"])
        if not member_id_input:
            return LoginResult(
                success=False,
                message="会員ID入力フィールドが見つかりません",
            )
        await member_id_input.fill(member_id)
        
        # パスワード入力
        password_input = await page.query_selector(LOGIN["password"])
        if not password_input:
            return LoginResult(
                success=False,
                message="パスワード入力フィールドが見つかりません",
            )
        await password_input.fill(password)
        
        # ログインボタンをクリック
        login_button = await page.query_selector(LOGIN["login_button"])
        if login_button:
            await login_button.click()
        else:
            await page.keyboard.press("Enter")
        
        # ページ遷移を待機
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)
        
        # OTPが要求されたかチェック
        otp_button = await page.query_selector(OTP["send_voice_button"])
        if otp_button:
            return LoginResult(
                success=False,
                message="ワンタイムパスワード（電話認証）が必要です",
                requires_otp=True,
            )
        
        # ログイン成功を確認
        if await check_logged_in(page):
            return LoginResult(
                success=True,
                message="ログイン成功",
            )
        
        # URLでログイン状態を判定
        current_url = page.url
        if "login" in current_url.lower() or "index.htm" in current_url.lower():
            return LoginResult(
                success=False,
                message="ログイン失敗: 会員IDまたはパスワードが正しくありません",
            )
        
        return LoginResult(
            success=True,
            message="ログイン成功（推定）",
        )
        
    except PlaywrightTimeout:
        return LoginResult(
            success=False,
            message="タイムアウト: ログインページの読み込みに失敗しました",
        )
    except Exception as e:
        return LoginResult(
            success=False,
            message=f"ログインエラー: {str(e)}",
        )


async def request_otp(page: Page) -> LoginResult:
    """
    OTP（電話認証）を要求
    
    「自動音声案内発信」ボタンをクリックして電話を発信する
    
    Returns:
        LoginResult: 結果
    """
    try:
        # 「自動音声案内発信」ボタンをクリック
        send_button = await page.query_selector(OTP["send_voice_button"])
        if not send_button:
            return LoginResult(
                success=False,
                message="自動音声案内発信ボタンが見つかりません",
            )
        
        await send_button.click()
        await page.wait_for_timeout(1000)
        
        # ダイアログが表示されたら閉じる
        close_button = await page.query_selector(OTP["close_dialog"])
        if close_button:
            await close_button.click()
            await page.wait_for_timeout(500)
        
        return LoginResult(
            success=True,
            message="電話認証を発信しました。登録済み電話番号に着信があります。",
        )
        
    except Exception as e:
        return LoginResult(
            success=False,
            message=f"OTP発信エラー: {str(e)}",
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
        # OTP入力フィールドを探す
        otp_input = await page.query_selector(OTP["otp_input"])
        if not otp_input:
            return LoginResult(
                success=False,
                message="OTP入力フィールドが見つかりません",
            )
        
        # OTPを入力
        await otp_input.fill(otp_code)
        
        # 次へボタンをクリック
        next_button = await page.query_selector(OTP["next_button"])
        if next_button:
            await next_button.click()
        else:
            await page.keyboard.press("Enter")
        
        # ページ遷移を待機
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)
        
        # ログイン成功を確認
        if await check_logged_in(page):
            return LoginResult(
                success=True,
                message="OTP認証成功",
            )
        
        # エラーチェック
        error = await page.query_selector(COMMON["error"])
        if error:
            error_text = await error.inner_text()
            return LoginResult(
                success=False,
                message=f"OTP認証失敗: {error_text}",
            )
        
        return LoginResult(
            success=False,
            message="OTP認証失敗: 不明なエラー",
        )
        
    except PlaywrightTimeout:
        return LoginResult(
            success=False,
            message="タイムアウト: OTP認証に失敗しました",
        )
    except Exception as e:
        return LoginResult(
            success=False,
            message=f"OTPエラー: {str(e)}",
        )
