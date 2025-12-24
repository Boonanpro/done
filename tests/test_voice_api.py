"""
Phase 10: Voice Communication API Tests
音声通話APIのテスト
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from main import app
from app.models.voice_schemas import (
    CallDirection, CallStatus, CallPurpose, PhoneRuleType,
    VoiceSettingsResponse, PhoneNumberRuleResponse, VoiceCallResponse,
)


@pytest.fixture
def client():
    """テストクライアント"""
    return TestClient(app)


@pytest.fixture
def mock_voice_service():
    """VoiceServiceのモック"""
    with patch('app.api.voice_routes.get_voice_service') as mock:
        service = MagicMock()
        mock.return_value = service
        yield service


class TestVoiceSettingsAPI:
    """音声設定APIのテスト"""
    
    def test_get_voice_settings(self, client, mock_voice_service):
        """音声設定取得のテスト"""
        # モックの設定
        mock_voice_service.get_voice_settings = AsyncMock(return_value=VoiceSettingsResponse(
            id="test-settings-id",
            user_id="test-user-id",
            inbound_enabled=False,
            default_greeting="こんにちは",
            auto_answer_whitelist=False,
            record_calls=False,
            notify_via_chat=True,
            elevenlabs_voice_id=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ))
        
        response = client.get("/api/v1/voice/settings")
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "test-settings-id"
        assert data["inbound_enabled"] == False
        assert data["notify_via_chat"] == True
    
    def test_update_voice_settings(self, client, mock_voice_service):
        """音声設定更新のテスト"""
        mock_voice_service.update_voice_settings = AsyncMock(return_value=VoiceSettingsResponse(
            id="test-settings-id",
            user_id="test-user-id",
            inbound_enabled=True,
            default_greeting="更新されたメッセージ",
            auto_answer_whitelist=True,
            record_calls=True,
            notify_via_chat=True,
            elevenlabs_voice_id="voice-123",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ))
        
        response = client.patch("/api/v1/voice/settings", json={
            "inbound_enabled": True,
            "record_calls": True,
            "elevenlabs_voice_id": "voice-123"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["inbound_enabled"] == True
        assert data["record_calls"] == True
        assert data["elevenlabs_voice_id"] == "voice-123"
    
    def test_toggle_inbound(self, client, mock_voice_service):
        """受電オン/オフ切り替えのテスト"""
        mock_voice_service.toggle_inbound = AsyncMock(return_value=True)
        
        response = client.patch("/api/v1/voice/inbound", json={"enabled": True})
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["inbound_enabled"] == True


class TestPhoneRulesAPI:
    """電話番号ルールAPIのテスト"""
    
    def test_get_phone_rules(self, client, mock_voice_service):
        """電話番号ルール一覧取得のテスト"""
        mock_voice_service.get_phone_rules = AsyncMock(return_value=[
            PhoneNumberRuleResponse(
                id="rule-1",
                phone_number="+819012345678",
                rule_type=PhoneRuleType.WHITELIST,
                label="Company A",
                notes=None,
                created_at=datetime.now(),
            ),
            PhoneNumberRuleResponse(
                id="rule-2",
                phone_number="+819087654321",
                rule_type=PhoneRuleType.BLACKLIST,
                label="Spam",
                notes="迷惑電話",
                created_at=datetime.now(),
            ),
        ])
        
        response = client.get("/api/v1/voice/rules")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["rules"]) == 2
        assert data["rules"][0]["phone_number"] == "+819012345678"
        assert data["rules"][0]["rule_type"] == "whitelist"
    
    def test_get_phone_rules_filtered(self, client, mock_voice_service):
        """電話番号ルール一覧取得（フィルター付き）のテスト"""
        mock_voice_service.get_phone_rules = AsyncMock(return_value=[
            PhoneNumberRuleResponse(
                id="rule-1",
                phone_number="+819012345678",
                rule_type=PhoneRuleType.WHITELIST,
                label="Company A",
                notes=None,
                created_at=datetime.now(),
            ),
        ])
        
        response = client.get("/api/v1/voice/rules?rule_type=whitelist")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["rules"]) == 1
        mock_voice_service.get_phone_rules.assert_called_once()
    
    def test_add_phone_rule(self, client, mock_voice_service):
        """電話番号ルール追加のテスト"""
        mock_voice_service.add_phone_rule = AsyncMock(return_value=PhoneNumberRuleResponse(
            id="new-rule-id",
            phone_number="+819099999999",
            rule_type=PhoneRuleType.WHITELIST,
            label="New Company",
            notes="備考テスト",
            created_at=datetime.now(),
        ))
        
        response = client.post("/api/v1/voice/rules", json={
            "phone_number": "+819099999999",
            "rule_type": "whitelist",
            "label": "New Company",
            "notes": "備考テスト"
        })
        
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "new-rule-id"
        assert data["phone_number"] == "+819099999999"
        assert data["rule_type"] == "whitelist"
    
    def test_delete_phone_rule(self, client, mock_voice_service):
        """電話番号ルール削除のテスト"""
        mock_voice_service.delete_phone_rule = AsyncMock(return_value=True)
        
        response = client.delete("/api/v1/voice/rules/rule-id-123")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True


class TestVoiceCallsAPI:
    """通話履歴APIのテスト"""
    
    def test_get_call_history(self, client, mock_voice_service):
        """通話履歴取得のテスト"""
        mock_voice_service.get_call_history = AsyncMock(return_value=[
            VoiceCallResponse(
                id="call-1",
                call_sid="CA123456",
                direction=CallDirection.OUTBOUND,
                status=CallStatus.COMPLETED,
                from_number="+815012345678",
                to_number="+819012345678",
                started_at=datetime.now(),
                answered_at=datetime.now(),
                ended_at=datetime.now(),
                duration_seconds=120,
                transcription="テスト通話",
                summary="予約確認",
                purpose=CallPurpose.RESERVATION,
                task_id=None,
            ),
        ])
        
        response = client.get("/api/v1/voice/calls")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["calls"][0]["call_sid"] == "CA123456"
        assert data["calls"][0]["direction"] == "outbound"
        assert data["calls"][0]["status"] == "completed"
    
    def test_get_call_history_filtered(self, client, mock_voice_service):
        """通話履歴取得（フィルター付き）のテスト"""
        mock_voice_service.get_call_history = AsyncMock(return_value=[])
        
        response = client.get("/api/v1/voice/calls?direction=inbound&status=completed&limit=10")
        
        assert response.status_code == 200
        mock_voice_service.get_call_history.assert_called_once()
    
    def test_get_call(self, client, mock_voice_service):
        """通話情報取得のテスト"""
        mock_voice_service.get_call = AsyncMock(return_value=VoiceCallResponse(
            id="call-1",
            call_sid="CA123456",
            direction=CallDirection.OUTBOUND,
            status=CallStatus.COMPLETED,
            from_number="+815012345678",
            to_number="+819012345678",
            started_at=datetime.now(),
            answered_at=datetime.now(),
            ended_at=datetime.now(),
            duration_seconds=120,
            transcription="テスト通話",
            summary="予約確認",
            purpose=CallPurpose.RESERVATION,
            task_id=None,
        ))
        
        response = client.get("/api/v1/voice/call/call-1")
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "call-1"
        assert data["call_sid"] == "CA123456"
    
    def test_get_call_not_found(self, client, mock_voice_service):
        """通話情報取得（存在しない場合）のテスト"""
        mock_voice_service.get_call = AsyncMock(return_value=None)
        
        response = client.get("/api/v1/voice/call/nonexistent-id")
        
        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Call not found"

