"""
Phase 9: OTP Automation - Unit Tests
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timezone, timedelta

from app.models.otp_schemas import (
    OTPSource,
    OTPResult,
    OTP_PATTERNS,
    OTP_SENDER_DOMAINS,
)


class TestOTPPatterns:
    """OTP抽出パターンのテスト"""
    
    def test_extract_otp_with_label(self):
        """ラベル付きOTPを抽出できること"""
        import re
        
        test_cases = [
            ("認証コード: 123456", "123456"),
            ("確認コード：654321", "654321"),
            ("ワンタイムパスワード: 987654", "987654"),
            ("Your verification code is 112233", "112233"),
            ("OTP: 445566", "445566"),
        ]
        
        for text, expected in test_cases:
            for pattern in OTP_PATTERNS:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    assert match.group(1) == expected, f"Failed for: {text}"
                    break
    
    def test_extract_six_digit_otp(self):
        """6桁数字のOTPを抽出できること"""
        import re
        
        text = "ログイン確認のため、123456 を入力してください"
        
        for pattern in OTP_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                assert match.group(1) == "123456"
                break
    
    def test_service_domains(self):
        """サービスドメインが定義されていること"""
        assert "amazon" in OTP_SENDER_DOMAINS
        assert "ex_reservation" in OTP_SENDER_DOMAINS
        assert "rakuten" in OTP_SENDER_DOMAINS


class TestOTPService:
    """OTPServiceのテスト"""
    
    @pytest.fixture
    def mock_supabase(self):
        """Supabaseモック"""
        mock = MagicMock()
        mock.table.return_value = mock
        mock.select.return_value = mock
        mock.insert.return_value = mock
        mock.update.return_value = mock
        mock.eq.return_value = mock
        mock.gt.return_value = mock
        mock.gte.return_value = mock
        mock.order.return_value = mock
        mock.limit.return_value = mock
        mock.execute.return_value = MagicMock(data=[], count=0)
        return mock
    
    @pytest.fixture
    def otp_service(self, mock_supabase):
        """OTPServiceのテストインスタンス"""
        with patch('app.services.otp_service.get_supabase_client') as mock_client:
            mock_client.return_value.client = mock_supabase
            from app.services.otp_service import OTPService
            service = OTPService()
            service.supabase = mock_supabase
            return service
    
    def test_extract_otp_from_text(self, otp_service):
        """テキストからOTPを抽出できること"""
        test_cases = [
            ("認証コード: 123456", "123456"),
            ("Your code is 654321", "654321"),
            ("OTP: 111222", "111222"),
            ("No OTP here", None),
        ]
        
        for text, expected in test_cases:
            result = otp_service._extract_otp_from_text(text)
            assert result == expected, f"Failed for: {text}"
    
    def test_match_service_domain_amazon(self, otp_service):
        """Amazonドメインのマッチング"""
        assert otp_service._match_service_domain("noreply@amazon.co.jp", "amazon") is True
        assert otp_service._match_service_domain("noreply@other.com", "amazon") is False
    
    def test_match_service_domain_no_filter(self, otp_service):
        """フィルタなしの場合は常にTrue"""
        assert otp_service._match_service_domain("anyone@any.com", None) is True
        assert otp_service._match_service_domain("", "amazon") is True
    
    @pytest.mark.asyncio
    async def test_get_latest_otp_empty(self, otp_service, mock_supabase):
        """OTPがない場合はNoneを返すこと"""
        mock_supabase.execute.return_value = MagicMock(data=[])
        
        result = await otp_service.get_latest_otp(user_id="user-1")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_get_latest_otp_found(self, otp_service, mock_supabase):
        """OTPが見つかった場合は返すこと"""
        mock_supabase.execute.return_value = MagicMock(data=[{
            "id": "otp-1",
            "otp_code": "123456",
            "source": "email",
            "sender": "noreply@amazon.co.jp",
            "subject": "認証コード",
            "service": "amazon",
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            "is_used": False,
        }])
        
        result = await otp_service.get_latest_otp(user_id="user-1")
        
        assert result is not None
        assert result.code == "123456"
        assert result.source == OTPSource.EMAIL
    
    @pytest.mark.asyncio
    async def test_mark_otp_used(self, otp_service, mock_supabase):
        """OTPを使用済みにマークできること"""
        mock_supabase.execute.return_value = MagicMock(data=[{"id": "otp-1"}])
        
        result = await otp_service.mark_otp_used("otp-1")
        
        assert result is True
        mock_supabase.update.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_otp_history(self, otp_service, mock_supabase):
        """OTP履歴を取得できること"""
        mock_supabase.execute.return_value = MagicMock(
            data=[
                {
                    "id": "otp-1",
                    "otp_code": "111111",
                    "source": "email",
                    "extracted_at": datetime.now(timezone.utc).isoformat(),
                    "is_used": True,
                },
                {
                    "id": "otp-2",
                    "otp_code": "222222",
                    "source": "sms",
                    "extracted_at": datetime.now(timezone.utc).isoformat(),
                    "is_used": False,
                },
            ],
            count=2,
        )
        
        extractions, total = await otp_service.get_otp_history(user_id="user-1")
        
        assert len(extractions) == 2
        assert total == 2
    
    @pytest.mark.asyncio
    async def test_get_sms_status_not_configured(self, otp_service, mock_supabase):
        """Twilio未設定の状態を返すこと"""
        mock_supabase.execute.return_value = MagicMock(data=[])
        
        with patch('app.services.otp_service.settings') as mock_settings:
            mock_settings.TWILIO_ACCOUNT_SID = None
            mock_settings.TWILIO_AUTH_TOKEN = None
            mock_settings.TWILIO_PHONE_NUMBER = None
            
            result = await otp_service.get_sms_status("user-1")
        
        assert result["configured"] is False


class TestOTPRoutes:
    """OTP APIルートのテスト"""
    
    @pytest.fixture
    def client(self):
        """テストクライアント"""
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app)
    
    def test_get_otp_history(self, client):
        """OTP履歴取得APIが動作すること"""
        with patch('app.api.otp_routes.get_otp_service') as mock:
            mock_service = AsyncMock()
            mock_service.get_otp_history.return_value = ([], 0)
            mock.return_value = mock_service
            
            response = client.get("/api/v1/otp/history")
            
            assert response.status_code == 200
            data = response.json()
            assert "extractions" in data
            assert "total" in data
    
    def test_get_latest_otp(self, client):
        """最新OTP取得APIが動作すること"""
        with patch('app.api.otp_routes.get_otp_service') as mock:
            mock_service = AsyncMock()
            mock_service.get_latest_otp.return_value = None
            mock.return_value = mock_service
            
            response = client.get("/api/v1/otp/latest")
            
            assert response.status_code == 200
            data = response.json()
            assert "otp" in data
    
    def test_get_sms_status(self, client):
        """SMS設定状態APIが動作すること"""
        with patch('app.api.otp_routes.get_otp_service') as mock:
            mock_service = AsyncMock()
            mock_service.get_sms_status.return_value = {
                "configured": False,
                "phone_number": None,
                "webhook_url": None,
                "is_active": False,
            }
            mock.return_value = mock_service
            
            response = client.get("/api/v1/otp/sms/status")
            
            assert response.status_code == 200
            data = response.json()
            assert "configured" in data
    
    def test_extract_email_otp(self, client):
        """メールOTP抽出APIが動作すること"""
        with patch('app.api.otp_routes.get_otp_service') as mock:
            mock_service = AsyncMock()
            mock_service.extract_otp_from_email.return_value = None
            mock.return_value = mock_service
            
            response = client.post(
                "/api/v1/otp/extract/email",
                json={"service": "amazon", "max_age_minutes": 5}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "success" in data
    
    def test_extract_sms_otp(self, client):
        """SMS OTP抽出APIが動作すること"""
        with patch('app.api.otp_routes.get_otp_service') as mock:
            mock_service = AsyncMock()
            mock_service.extract_otp_from_sms.return_value = None
            mock.return_value = mock_service
            
            response = client.post(
                "/api/v1/otp/extract/sms",
                json={"service": "amazon", "max_age_minutes": 5}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "success" in data
    
    def test_mark_otp_used(self, client):
        """OTP使用済みマークAPIが動作すること"""
        with patch('app.api.otp_routes.get_otp_service') as mock:
            mock_service = AsyncMock()
            mock_service.mark_otp_used.return_value = True
            mock.return_value = mock_service
            
            response = client.post("/api/v1/otp/test-id/mark-used")
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
    
    def test_sms_webhook(self, client):
        """SMS Webhookが動作すること"""
        with patch('app.api.otp_routes.get_otp_service') as mock:
            mock_service = AsyncMock()
            mock_service.save_sms_otp.return_value = None
            mock.return_value = mock_service
            
            response = client.post(
                "/api/v1/otp/sms/webhook",
                data={"From": "+81901234567", "To": "+81801234567", "Body": "Your code is 123456"}
            )
            
            assert response.status_code == 200
            assert "xml" in response.headers.get("content-type", "")


class TestBaseExecutorOTP:
    """BaseExecutorのOTP統合テスト"""
    
    @pytest.fixture
    def mock_supabase(self):
        """Supabaseモック"""
        mock = MagicMock()
        mock.table.return_value = mock
        mock.select.return_value = mock
        mock.insert.return_value = mock
        mock.update.return_value = mock
        mock.eq.return_value = mock
        mock.gt.return_value = mock
        mock.gte.return_value = mock
        mock.order.return_value = mock
        mock.limit.return_value = mock
        mock.execute.return_value = MagicMock(data=[], count=0)
        return mock
    
    def test_otp_page_indicators_defined(self):
        """OTPページ検知パターンが定義されていること"""
        from app.models.otp_schemas import OTP_PAGE_INDICATORS
        
        assert len(OTP_PAGE_INDICATORS) > 0
        assert "認証コード" in OTP_PAGE_INDICATORS
        assert "確認コード" in OTP_PAGE_INDICATORS
    
    def test_otp_field_selectors_defined(self):
        """OTPフィールドセレクタが定義されていること"""
        from app.models.otp_schemas import OTP_FIELD_SELECTORS
        
        assert len(OTP_FIELD_SELECTORS) > 0
        assert any("otp" in s for s in OTP_FIELD_SELECTORS)
        assert any("verification" in s for s in OTP_FIELD_SELECTORS)
    
    def test_base_executor_has_otp_methods(self):
        """BaseExecutorにOTPメソッドが定義されていること"""
        from app.executors.base import BaseExecutor
        
        # OTP関連メソッドの存在確認
        assert hasattr(BaseExecutor, '_handle_otp_challenge')
        assert hasattr(BaseExecutor, '_detect_otp_page')
        assert hasattr(BaseExecutor, '_find_otp_field')


class TestVoiceOTPAPI:
    """音声OTP抽出API（Phase 9C）のテスト"""
    
    def test_extract_voice_otp_endpoint_exists(self, client):
        """音声OTP抽出エンドポイントが存在すること"""
        response = client.post("/api/v1/otp/extract/voice", json={})
        # 404ではなく正常なレスポンス（OTPが見つからない場合でもsuccess=false）
        assert response.status_code == 200
    
    def test_extract_voice_otp_no_call(self, client):
        """通話がない場合のレスポンス"""
        response = client.post("/api/v1/otp/extract/voice", json={
            "service": "test_bank"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "No OTP found" in data["message"]
    
    def test_extract_voice_otp_with_call_id(self, client):
        """通話IDを指定した場合"""
        response = client.post("/api/v1/otp/extract/voice", json={
            "call_id": "00000000-0000-0000-0000-000000000099",
            "service": "mizuho"
        })
        
        assert response.status_code == 200
        data = response.json()
        # 存在しない通話IDなのでOTPは見つからない
        assert data["success"] is False


class TestVoiceOTPService:
    """音声OTPサービスのテスト"""
    
    def test_otp_service_has_voice_methods(self):
        """OTPServiceに音声関連メソッドが存在すること"""
        from app.services.otp_service import OTPService
        
        assert hasattr(OTPService, 'extract_otp_from_voice')
        assert hasattr(OTPService, 'extract_otp_from_latest_voice_call')
    
    def test_extract_otp_from_transcription(self):
        """文字起こしからOTP抽出のテスト"""
        from app.services.otp_service import OTPService
        
        service = OTPService()
        
        # 認証コードを含む文字起こし
        test_cases = [
            ("こちらは銀行です。認証コードは123456です。", "123456"),
            ("確認コード: 789012 を入力してください。", "789012"),
            ("あなたの確認番号は 456789 です", "456789"),
            ("ワンタイムパスワード 654321 をご入力ください", "654321"),
            ("コードは 1234 です。", "1234"),  # 4桁
            ("認証コードは12345678です", "12345678"),  # 8桁
            ("こんにちは。良い天気ですね。", None),  # OTPなし
        ]
        
        for text, expected in test_cases:
            result = service._extract_otp_from_text(text)
            assert result == expected, f"Failed for: {text}"
    
    def test_otp_source_voice_defined(self):
        """OTPSourceにVOICEが定義されていること"""
        from app.models.otp_schemas import OTPSource
        
        assert hasattr(OTPSource, 'VOICE')
        assert OTPSource.VOICE.value == "voice"

