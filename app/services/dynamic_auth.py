"""
Dynamic Auth Service for Phase 3B/3C: Execution Engine
動的認証/新規登録サービス - 汎用的な認証フロー対応
"""
import secrets
import string
import re
from typing import Optional, Any
from datetime import datetime

from playwright.async_api import Page

from app.models.schemas import (
    AuthField,
    AuthFieldType,
    AuthResult,
    RegistrationConfig,
)
from app.services.credentials_service import get_credentials_service


class DynamicAuthService:
    """動的認証/新規登録サービス"""
    
    # パスワード生成のデフォルト設定
    DEFAULT_PASSWORD_LENGTH = 16
    DEFAULT_PASSWORD_REQUIREMENTS = {
        "min_length": 8,
        "require_uppercase": True,
        "require_lowercase": True,
        "require_digits": True,
        "require_special": False,
    }
    
    def __init__(self):
        """サービスを初期化"""
        self.credentials_service = get_credentials_service()
    
    def generate_secure_password(
        self,
        length: int = DEFAULT_PASSWORD_LENGTH,
        requirements: Optional[dict[str, Any]] = None,
    ) -> str:
        """
        セキュアなパスワードを自動生成
        
        Args:
            length: パスワード長
            requirements: パスワード要件（min_length, require_uppercase等）
            
        Returns:
            生成されたパスワード
        """
        req = requirements or self.DEFAULT_PASSWORD_REQUIREMENTS
        
        # 要件を満たす文字セットを構築
        chars = ""
        required_chars = []
        
        if req.get("require_lowercase", True):
            chars += string.ascii_lowercase
            required_chars.append(secrets.choice(string.ascii_lowercase))
        
        if req.get("require_uppercase", True):
            chars += string.ascii_uppercase
            required_chars.append(secrets.choice(string.ascii_uppercase))
        
        if req.get("require_digits", True):
            chars += string.digits
            required_chars.append(secrets.choice(string.digits))
        
        if req.get("require_special", False):
            special = "!@#$%^&*"
            chars += special
            required_chars.append(secrets.choice(special))
        
        # 残りの文字をランダムに生成
        remaining_length = max(length - len(required_chars), 0)
        password_chars = required_chars + [
            secrets.choice(chars) for _ in range(remaining_length)
        ]
        
        # シャッフル
        password_list = list(password_chars)
        secrets.SystemRandom().shuffle(password_list)
        
        return "".join(password_list)
    
    def validate_password(
        self,
        password: str,
        requirements: Optional[dict[str, Any]] = None,
    ) -> tuple[bool, str]:
        """
        パスワードが要件を満たすか検証
        
        Args:
            password: 検証するパスワード
            requirements: パスワード要件
            
        Returns:
            (is_valid, error_message)
        """
        req = requirements or self.DEFAULT_PASSWORD_REQUIREMENTS
        
        if len(password) < req.get("min_length", 8):
            return False, f"パスワードは{req.get('min_length', 8)}文字以上必要です"
        
        if req.get("require_lowercase", True) and not re.search(r"[a-z]", password):
            return False, "パスワードには小文字が必要です"
        
        if req.get("require_uppercase", True) and not re.search(r"[A-Z]", password):
            return False, "パスワードには大文字が必要です"
        
        if req.get("require_digits", True) and not re.search(r"[0-9]", password):
            return False, "パスワードには数字が必要です"
        
        if req.get("require_special", False) and not re.search(r"[!@#$%^&*]", password):
            return False, "パスワードには特殊文字が必要です"
        
        return True, ""
    
    async def prepare_registration(
        self,
        page: Page,
        config: RegistrationConfig,
        user_data: dict[str, Any],
        auto_generate_password: bool = True,
    ) -> AuthResult:
        """
        登録フォームに自動入力してプレビュー表示（送信はしない）
        
        ユーザーに「この情報で登録しますか？」と確認を取るため、
        フォームに入力だけして送信ボタンは押さない。
        
        Args:
            page: Playwrightページ
            config: 登録設定
            user_data: ユーザーデータ（メール、名前等）
            auto_generate_password: パスワードを自動生成するか
            
        Returns:
            プレビュー結果（credentials に自動生成値を含む）
        """
        try:
            # 登録ページに遷移
            await page.goto(config.registration_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
            
            # パスワード生成
            password = user_data.get("password")
            if auto_generate_password or not password:
                password = self.generate_secure_password(
                    requirements=config.password_requirements
                )
                user_data["password"] = password
            
            # 各フィールドに入力（プレビュー用）
            for field in config.fields:
                try:
                    await self._fill_field(page, field, user_data)
                except Exception as e:
                    return AuthResult(
                        success=False,
                        message=f"フィールド '{field.name}' の入力に失敗しました: {str(e)}",
                    )
            
            # ★ 送信ボタンはクリックしない ★
            # ユーザーに確認を取ってから confirm_registration で送信
            
            credentials = {
                "email": user_data.get("email", ""),
                "password": password,
            }
            
            return AuthResult(
                success=True,
                message="登録情報を入力しました。この内容で登録しますか？",
                credentials=credentials,
                requires_confirmation=True,  # 確認が必要
                details={
                    "service": config.service_name,
                    "email": user_data.get("email", ""),
                    "generated_password": password,
                    "preview": True,
                    "timestamp": datetime.now().isoformat(),
                },
            )
            
        except Exception as e:
            return AuthResult(
                success=False,
                message=f"登録フォームの入力中にエラーが発生しました: {str(e)}",
            )
    
    async def confirm_registration(
        self,
        page: Page,
        config: RegistrationConfig,
        user_data: Optional[dict[str, Any]] = None,
    ) -> AuthResult:
        """
        プレビュー後、ユーザー確認を経て登録を確定
        
        prepare_registration でフォーム入力済みの状態で呼び出す。
        user_data が渡された場合は、その値で上書きしてから送信。
        
        Args:
            page: Playwrightページ（フォーム入力済み）
            config: 登録設定
            user_data: ユーザーが編集したデータ（任意）
            
        Returns:
            登録結果
        """
        try:
            # ユーザーが編集した場合は再入力
            if user_data:
                for field in config.fields:
                    try:
                        await self._fill_field(page, field, user_data)
                    except Exception:
                        pass  # 編集分のみ更新、失敗は無視
            
            # 送信ボタンをクリック
            submit_button = await page.query_selector(config.submit_selector)
            if submit_button:
                await submit_button.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(3000)
            
            credentials = {
                "email": user_data.get("email", "") if user_data else "",
                "password": user_data.get("password", "") if user_data else "",
            }
            
            return AuthResult(
                success=True,
                message="登録が完了しました",
                credentials=credentials,
                requires_confirmation=False,
                details={
                    "service": config.service_name,
                    "timestamp": datetime.now().isoformat(),
                },
            )
            
        except Exception as e:
            return AuthResult(
                success=False,
                message=f"登録処理中にエラーが発生しました: {str(e)}",
            )
    
    async def register_new_account(
        self,
        page: Page,
        config: RegistrationConfig,
        user_data: dict[str, Any],
        auto_generate_password: bool = True,
        skip_confirmation: bool = False,
    ) -> AuthResult:
        """
        新規アカウント登録を実行（互換性維持用）
        
        デフォルトでは prepare_registration のみ実行し、確認を待つ。
        skip_confirmation=True の場合のみ即時登録。
        
        Args:
            page: Playwrightページ
            config: 登録設定
            user_data: ユーザーデータ（メール、名前等）
            auto_generate_password: パスワードを自動生成するか
            skip_confirmation: 確認をスキップして即時登録するか（デフォルトFalse）
            
        Returns:
            登録結果
        """
        # まずプレビュー（フォーム入力のみ）
        preview_result = await self.prepare_registration(
            page, config, user_data, auto_generate_password
        )
        
        if not preview_result.success:
            return preview_result
        
        # skip_confirmation=False（デフォルト）なら確認を待つ
        if not skip_confirmation:
            return preview_result  # requires_confirmation=True の状態で返す
        
        # skip_confirmation=True なら即時登録
        return await self.confirm_registration(page, config, user_data)
    
    async def _fill_field(
        self,
        page: Page,
        field: AuthField,
        user_data: dict[str, Any],
    ) -> None:
        """
        フィールドに値を入力
        
        Args:
            page: Playwrightページ
            field: フィールド定義
            user_data: ユーザーデータ
        """
        value = self._get_field_value(field, user_data)
        if value is None:
            return
        
        if field.field_type == AuthFieldType.CHECKBOX:
            checkbox = await page.query_selector(field.selector)
            if checkbox and value:
                is_checked = await checkbox.is_checked()
                if not is_checked:
                    await checkbox.click()
        
        elif field.field_type == AuthFieldType.RADIO:
            # ラジオボタンは値に対応するセレクタをクリック
            radio = await page.query_selector(f'{field.selector}:has-text("{value}")')
            if radio:
                await radio.click()
            else:
                # セレクタ内の最初のラジオをクリック
                first_radio = await page.query_selector(field.selector)
                if first_radio:
                    await first_radio.click()
        
        elif field.field_type in [AuthFieldType.PREFECTURE, AuthFieldType.OCCUPATION]:
            # セレクトボックス
            select = await page.query_selector(field.selector)
            if select:
                await select.select_option(label=str(value))
        
        elif field.field_type == AuthFieldType.BIRTHDATE:
            # 生年月日は特殊処理（年/月/日が別々の場合あり）
            await self._fill_birthdate(page, field, value)
        
        else:
            # 通常のテキスト入力
            input_elem = await page.query_selector(field.selector)
            if input_elem:
                await input_elem.fill(str(value))
    
    def _get_field_value(
        self,
        field: AuthField,
        user_data: dict[str, Any],
    ) -> Optional[Any]:
        """
        フィールドに入力する値を取得
        """
        type_to_key = {
            AuthFieldType.EMAIL: "email",
            AuthFieldType.PASSWORD: "password",
            AuthFieldType.PHONE: "phone",
            AuthFieldType.NAME: "name",
            AuthFieldType.NAME_KANA: "name_kana",
            AuthFieldType.BIRTHDATE: "birthdate",
            AuthFieldType.GENDER: "gender",
            AuthFieldType.ADDRESS: "address",
            AuthFieldType.POSTAL_CODE: "postal_code",
            AuthFieldType.PREFECTURE: "prefecture",
            AuthFieldType.OCCUPATION: "occupation",
            AuthFieldType.CHECKBOX: "checkbox",
            AuthFieldType.RADIO: "radio",
        }
        
        key = type_to_key.get(field.field_type)
        if key:
            return user_data.get(key)
        
        # フィールド名で検索
        return user_data.get(field.name)
    
    async def _fill_birthdate(
        self,
        page: Page,
        field: AuthField,
        value: str,
    ) -> None:
        """
        生年月日を入力（年/月/日が別々の場合対応）
        
        Args:
            page: Playwrightページ
            field: フィールド定義
            value: 生年月日（YYYY-MM-DD形式）
        """
        try:
            parts = value.split("-")
            if len(parts) == 3:
                year, month, day = parts
                
                # セレクタがカンマ区切りで年/月/日を指定している場合
                selectors = field.selector.split(",")
                if len(selectors) == 3:
                    year_sel, month_sel, day_sel = [s.strip() for s in selectors]
                    
                    year_elem = await page.query_selector(year_sel)
                    if year_elem:
                        await year_elem.select_option(label=year)
                    
                    month_elem = await page.query_selector(month_sel)
                    if month_elem:
                        await month_elem.select_option(label=month.lstrip("0"))
                    
                    day_elem = await page.query_selector(day_sel)
                    if day_elem:
                        await day_elem.select_option(label=day.lstrip("0"))
                else:
                    # 単一のセレクタの場合
                    input_elem = await page.query_selector(field.selector)
                    if input_elem:
                        await input_elem.fill(value)
        except Exception:
            pass  # 生年月日入力失敗は続行
    
    async def save_credentials(
        self,
        user_id: str,
        service: str,
        credentials: dict[str, str],
    ) -> dict[str, Any]:
        """
        認証情報を安全に保存
        
        Args:
            user_id: ユーザーID
            service: サービス名
            credentials: 認証情報
            
        Returns:
            保存結果
        """
        return await self.credentials_service.save_credential(
            user_id=user_id,
            service=service,
            credentials=credentials,
        )
    
    async def get_or_register(
        self,
        page: Page,
        user_id: str,
        service: str,
        config: RegistrationConfig,
        user_data: dict[str, Any],
    ) -> AuthResult:
        """
        認証情報を取得、なければ新規登録
        
        Args:
            page: Playwrightページ
            user_id: ユーザーID
            service: サービス名
            config: 登録設定
            user_data: ユーザーデータ
            
        Returns:
            認証結果
        """
        # 既存の認証情報をチェック
        existing = await self.credentials_service.get_credential(user_id, service)
        if existing:
            return AuthResult(
                success=True,
                message="既存の認証情報を使用します",
                credentials={
                    "email": existing.get("email", ""),
                    "password": existing.get("password", ""),
                },
            )
        
        # 新規登録を実行
        result = await self.register_new_account(page, config, user_data)
        
        if result.success and result.credentials:
            # 認証情報を保存
            await self.save_credentials(user_id, service, result.credentials)
        
        return result


# シングルトンインスタンス
_dynamic_auth_service: Optional[DynamicAuthService] = None


def get_dynamic_auth_service() -> DynamicAuthService:
    """動的認証サービスのシングルトンインスタンスを取得"""
    global _dynamic_auth_service
    if _dynamic_auth_service is None:
        _dynamic_auth_service = DynamicAuthService()
    return _dynamic_auth_service








