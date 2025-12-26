"""
Tests for DynamicAuthService
動的認証/新規登録サービスのユニットテスト
"""
import pytest
import re

from app.services.dynamic_auth import DynamicAuthService, get_dynamic_auth_service
from app.models.schemas import (
    AuthField,
    AuthFieldType,
    RegistrationConfig,
)


class TestDynamicAuthService:
    """DynamicAuthServiceのテスト"""
    
    def setup_method(self):
        """テストセットアップ"""
        self.service = DynamicAuthService()
    
    def test_singleton_instance(self):
        """シングルトンインスタンスが取得できること"""
        service1 = get_dynamic_auth_service()
        service2 = get_dynamic_auth_service()
        assert service1 is service2
    
    def test_generate_secure_password_default_length(self):
        """デフォルト長のパスワードが生成されること"""
        password = self.service.generate_secure_password()
        assert len(password) == 16
    
    def test_generate_secure_password_custom_length(self):
        """カスタム長のパスワードが生成されること"""
        password = self.service.generate_secure_password(length=20)
        assert len(password) == 20
    
    def test_generate_secure_password_meets_default_requirements(self):
        """生成されたパスワードがデフォルト要件を満たすこと"""
        password = self.service.generate_secure_password()
        
        # 小文字を含む
        assert re.search(r"[a-z]", password), "小文字が含まれていません"
        # 大文字を含む
        assert re.search(r"[A-Z]", password), "大文字が含まれていません"
        # 数字を含む
        assert re.search(r"[0-9]", password), "数字が含まれていません"
    
    def test_generate_secure_password_with_special_chars(self):
        """特殊文字を含むパスワードが生成されること"""
        requirements = {
            "min_length": 12,
            "require_uppercase": True,
            "require_lowercase": True,
            "require_digits": True,
            "require_special": True,
        }
        password = self.service.generate_secure_password(
            length=16,
            requirements=requirements,
        )
        
        # 特殊文字を含む
        assert re.search(r"[!@#$%^&*]", password), "特殊文字が含まれていません"
    
    def test_generate_secure_password_lowercase_only(self):
        """小文字と数字のみのパスワードが生成されること（WILLER用）"""
        requirements = {
            "min_length": 8,
            "require_uppercase": False,
            "require_lowercase": True,
            "require_digits": True,
            "require_special": False,
        }
        password = self.service.generate_secure_password(
            length=12,
            requirements=requirements,
        )
        
        # 小文字を含む
        assert re.search(r"[a-z]", password)
        # 数字を含む
        assert re.search(r"[0-9]", password)
    
    def test_generate_unique_passwords(self):
        """異なるパスワードが生成されること"""
        passwords = [self.service.generate_secure_password() for _ in range(10)]
        unique_passwords = set(passwords)
        assert len(unique_passwords) == 10, "重複したパスワードが生成されました"
    
    def test_validate_password_valid(self):
        """有効なパスワードが検証を通過すること"""
        valid_password = "MyPassword123"
        is_valid, message = self.service.validate_password(valid_password)
        assert is_valid
        assert message == ""
    
    def test_validate_password_too_short(self):
        """短すぎるパスワードが検証で失敗すること"""
        short_password = "Pass1"
        is_valid, message = self.service.validate_password(short_password)
        assert not is_valid
        assert "8文字以上" in message
    
    def test_validate_password_no_lowercase(self):
        """小文字がないパスワードが検証で失敗すること"""
        password = "PASSWORD123"
        is_valid, message = self.service.validate_password(password)
        assert not is_valid
        assert "小文字" in message
    
    def test_validate_password_no_uppercase(self):
        """大文字がないパスワードが検証で失敗すること"""
        password = "password123"
        is_valid, message = self.service.validate_password(password)
        assert not is_valid
        assert "大文字" in message
    
    def test_validate_password_no_digits(self):
        """数字がないパスワードが検証で失敗すること"""
        password = "PasswordOnly"
        is_valid, message = self.service.validate_password(password)
        assert not is_valid
        assert "数字" in message
    
    def test_validate_password_custom_requirements(self):
        """カスタム要件でパスワード検証ができること"""
        # 特殊文字必須
        requirements = {
            "min_length": 8,
            "require_uppercase": False,
            "require_lowercase": True,
            "require_digits": True,
            "require_special": True,
        }
        
        # 特殊文字なし
        password = "password123"
        is_valid, message = self.service.validate_password(password, requirements)
        assert not is_valid
        assert "特殊文字" in message
        
        # 特殊文字あり
        password_with_special = "password123!"
        is_valid, message = self.service.validate_password(password_with_special, requirements)
        assert is_valid


class TestAuthFieldModel:
    """AuthFieldモデルのテスト"""
    
    def test_create_auth_field(self):
        """AuthFieldが作成できること"""
        field = AuthField(
            field_type=AuthFieldType.EMAIL,
            selector='input[type="email"]',
            name="email",
            required=True,
        )
        
        assert field.field_type == AuthFieldType.EMAIL
        assert field.selector == 'input[type="email"]'
        assert field.name == "email"
        assert field.required is True
    
    def test_auth_field_with_options(self):
        """オプション付きAuthFieldが作成できること"""
        field = AuthField(
            field_type=AuthFieldType.RADIO,
            selector='input[type="radio"]',
            name="gender",
            required=True,
            options=["男性", "女性"],
        )
        
        assert field.options == ["男性", "女性"]
    
    def test_auth_field_types(self):
        """全てのAuthFieldTypeが存在すること"""
        expected_types = [
            "email", "password", "phone", "name", "name_kana",
            "birthdate", "gender", "address", "postal_code",
            "prefecture", "occupation", "checkbox", "radio", "other"
        ]
        
        for type_name in expected_types:
            assert hasattr(AuthFieldType, type_name.upper())


class TestRegistrationConfig:
    """RegistrationConfigモデルのテスト"""
    
    def test_create_registration_config(self):
        """RegistrationConfigが作成できること"""
        config = RegistrationConfig(
            service_name="test_service",
            registration_url="https://example.com/register",
            login_url="https://example.com/login",
            fields=[],
            submit_selector='button[type="submit"]',
        )
        
        assert config.service_name == "test_service"
        assert config.registration_url == "https://example.com/register"
        assert config.login_url == "https://example.com/login"
    
    def test_registration_config_with_fields(self):
        """フィールド付きRegistrationConfigが作成できること"""
        fields = [
            AuthField(
                field_type=AuthFieldType.EMAIL,
                selector='input[name="email"]',
                name="email",
                required=True,
            ),
            AuthField(
                field_type=AuthFieldType.PASSWORD,
                selector='input[name="password"]',
                name="password",
                required=True,
            ),
        ]
        
        config = RegistrationConfig(
            service_name="test_service",
            registration_url="https://example.com/register",
            login_url="https://example.com/login",
            fields=fields,
            submit_selector='button[type="submit"]',
            password_requirements={"min_length": 8},
        )
        
        assert len(config.fields) == 2
        assert config.password_requirements == {"min_length": 8}








