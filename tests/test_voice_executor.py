"""
VoiceExecutor Tests - Phase 10
電話タスク実行のテスト
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestPhoneNumberExtraction:
    """電話番号抽出のテスト"""
    
    def test_extract_domestic_with_hyphens(self):
        """国内番号（ハイフン付き）の抽出"""
        from app.executors.voice_executor import extract_phone_number
        
        assert extract_phone_number("03-1234-5678") == "+81312345678"
        assert extract_phone_number("03-5678-1234") == "+81356781234"
        assert extract_phone_number("090-1234-5678") == "+819012345678"
    
    def test_extract_domestic_without_hyphens(self):
        """国内番号（ハイフンなし）の抽出"""
        from app.executors.voice_executor import extract_phone_number
        
        assert extract_phone_number("0312345678") == "+81312345678"
        assert extract_phone_number("09012345678") == "+819012345678"
    
    def test_extract_international_format(self):
        """国際形式の抽出"""
        from app.executors.voice_executor import extract_phone_number
        
        assert extract_phone_number("+81312345678") == "+81312345678"
    
    def test_extract_from_text(self):
        """テキスト内からの抽出"""
        from app.executors.voice_executor import extract_phone_number
        
        result = extract_phone_number("Please call 03-1234-5678 for more info")
        assert result == "+81312345678"
    
    def test_no_phone_number(self):
        """電話番号がない場合"""
        from app.executors.voice_executor import extract_phone_number
        
        assert extract_phone_number("No phone number here") is None
        assert extract_phone_number("") is None


class TestVoiceExecutor:
    """VoiceExecutorのテスト"""
    
    def test_executor_exists(self):
        """VoiceExecutorが存在すること"""
        from app.executors.voice_executor import VoiceExecutor
        
        executor = VoiceExecutor()
        assert executor.service_name == "voice"
        assert executor._requires_login() is False
    
    def test_executor_factory_returns_voice_executor(self):
        """ExecutorFactoryがVoiceExecutorを返すこと"""
        from app.executors.base import ExecutorFactory
        from app.executors.voice_executor import VoiceExecutor
        
        executor = ExecutorFactory.get_executor("voice")
        assert isinstance(executor, VoiceExecutor)
        
        executor = ExecutorFactory.get_executor("phone")
        assert isinstance(executor, VoiceExecutor)
        
        executor = ExecutorFactory.get_executor("call")
        assert isinstance(executor, VoiceExecutor)


class TestTaskType:
    """TaskTypeのテスト"""
    
    def test_phone_task_type_defined(self):
        """PHONEタスクタイプが定義されていること"""
        from app.models.schemas import TaskType
        
        assert hasattr(TaskType, 'PHONE')
        assert TaskType.PHONE.value == "phone"


class TestSearchResultCategory:
    """SearchResultCategoryのテスト"""
    
    def test_phone_category_defined(self):
        """PHONEカテゴリが定義されていること"""
        from app.models.schemas import SearchResultCategory
        
        assert hasattr(SearchResultCategory, 'PHONE')
        assert SearchResultCategory.PHONE.value == "phone"


