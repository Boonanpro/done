"""
Tests for HighwayBusExecutor
高速バス予約実行ロジックのユニットテスト
"""
import pytest

from app.executors.highway_bus_executor import HighwayBusExecutor
from app.executors.base import ExecutorFactory
from app.models.schemas import RegistrationConfig, AuthFieldType


class TestHighwayBusExecutor:
    """HighwayBusExecutorのテスト"""
    
    def setup_method(self):
        """テストセットアップ"""
        self.executor = HighwayBusExecutor()
    
    def test_service_name(self):
        """サービス名がwillerであること"""
        assert self.executor.service_name == "willer"
    
    def test_has_selectors(self):
        """必要なセレクタが定義されていること"""
        required_selectors = [
            "login_link",
            "login_id_input",
            "password_input",
            "login_button",
            "register_link",
            "book_button",
            "mypage_link",
        ]
        
        for selector_name in required_selectors:
            assert selector_name in self.executor.SELECTORS, f"セレクタ '{selector_name}' が定義されていません"
    
    def test_has_urls(self):
        """必要なURLが定義されていること"""
        required_urls = [
            "top",
            "login",
            "register",
            "mypage",
            "bus_search",
        ]
        
        for url_name in required_urls:
            assert url_name in self.executor.URLS, f"URL '{url_name}' が定義されていません"
    
    def test_urls_are_valid_willer_urls(self):
        """URLがWILLERドメインであること"""
        for name, url in self.executor.URLS.items():
            assert "willer" in url, f"URL '{name}' がWILLERドメインではありません: {url}"
    
    def test_password_requirements(self):
        """パスワード要件が定義されていること"""
        requirements = self.executor.PASSWORD_REQUIREMENTS
        
        assert "min_length" in requirements
        assert requirements["min_length"] == 8
        assert "require_digits" in requirements
        assert requirements["require_digits"] is True


class TestBuildSearchUrl:
    """検索URL構築のテスト"""
    
    def setup_method(self):
        """テストセットアップ"""
        self.executor = HighwayBusExecutor()
    
    def test_build_search_url_tokyo_osaka(self):
        """東京→大阪の検索URLが正しく生成されること"""
        url = self.executor._build_search_url("東京", "大阪")
        
        assert "bus_search" in url
        assert "tokyo" in url
        assert "osaka" in url
    
    def test_build_search_url_with_date(self):
        """日付付きの検索URLが正しく生成されること"""
        url = self.executor._build_search_url("東京", "大阪", "2024-12-25")
        
        assert "ym_202412" in url
    
    def test_build_search_url_nagoya(self):
        """名古屋が正しくマッピングされること"""
        url = self.executor._build_search_url("名古屋", "東京")
        
        assert "aichi" in url or "nagoya" in url
    
    def test_build_search_url_unknown_city(self):
        """不明な都市はデフォルト値が使われること"""
        url = self.executor._build_search_url("不明な都市", "大阪")
        
        # デフォルトはtokyoにフォールバック
        assert "tokyo" in url
        assert "osaka" in url


class TestGetRegistrationConfig:
    """登録設定取得のテスト"""
    
    def setup_method(self):
        """テストセットアップ"""
        self.executor = HighwayBusExecutor()
    
    def test_get_registration_config(self):
        """登録設定が取得できること"""
        config = self.executor.get_registration_config()
        
        assert isinstance(config, RegistrationConfig)
        assert config.service_name == "willer"
    
    def test_registration_config_has_required_fields(self):
        """登録設定に必要なフィールドが含まれていること"""
        config = self.executor.get_registration_config()
        
        field_types = [field.field_type for field in config.fields]
        
        # 必須フィールドタイプの確認
        assert AuthFieldType.EMAIL in field_types
        assert AuthFieldType.PASSWORD in field_types
    
    def test_registration_config_has_urls(self):
        """登録設定にURLが含まれていること"""
        config = self.executor.get_registration_config()
        
        assert config.registration_url
        assert config.login_url
        assert "willer" in config.registration_url
        assert "willer" in config.login_url
    
    def test_registration_config_has_submit_selector(self):
        """登録設定に送信ボタンセレクタが含まれていること"""
        config = self.executor.get_registration_config()
        
        assert config.submit_selector
    
    def test_registration_config_has_password_requirements(self):
        """登録設定にパスワード要件が含まれていること"""
        config = self.executor.get_registration_config()
        
        assert config.password_requirements
        assert "min_length" in config.password_requirements


class TestExecutorFactory:
    """ExecutorFactoryのテスト（bus category）"""
    
    def test_factory_returns_highway_bus_executor(self):
        """busカテゴリでHighwayBusExecutorが返されること"""
        executor = ExecutorFactory.get_executor("bus")
        
        assert isinstance(executor, HighwayBusExecutor)
        assert executor.service_name == "willer"
    
    def test_factory_bus_executor_has_dynamic_auth(self):
        """HighwayBusExecutorがDynamicAuthServiceを持つこと"""
        executor = ExecutorFactory.get_executor("bus")
        
        assert hasattr(executor, "dynamic_auth")
        assert executor.dynamic_auth is not None



