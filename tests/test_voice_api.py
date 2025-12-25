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


class TestOutboundCallAPI:
    """架電APIのテスト"""
    
    def test_initiate_call(self, client, mock_voice_service):
        """架電開始のテスト"""
        mock_voice_service.initiate_call = AsyncMock(return_value=VoiceCallResponse(
            id="new-call-id",
            call_sid="CA789012",
            direction=CallDirection.OUTBOUND,
            status=CallStatus.INITIATED,
            from_number="+815012345678",
            to_number="+819099999999",
            started_at=datetime.now(),
            answered_at=None,
            ended_at=None,
            duration_seconds=None,
            transcription=None,
            summary=None,
            purpose=CallPurpose.RESERVATION,
            task_id=None,
        ))
        
        response = client.post("/api/v1/voice/call", json={
            "to_number": "+819099999999",
            "purpose": "reservation",
            "context": {"restaurant": "Test Restaurant"},
        })
        
        assert response.status_code == 201
        data = response.json()
        assert data["success"] == True
        assert data["call"]["call_sid"] == "CA789012"
        assert data["call"]["direction"] == "outbound"
        assert data["call"]["status"] == "initiated"
    
    def test_initiate_call_error(self, client, mock_voice_service):
        """架電開始エラーのテスト"""
        mock_voice_service.initiate_call = AsyncMock(
            side_effect=ValueError("Twilio credentials are not configured")
        )
        
        response = client.post("/api/v1/voice/call", json={
            "to_number": "+819099999999",
        })
        
        assert response.status_code == 400
        data = response.json()
        assert "Twilio credentials" in data["detail"]
    
    def test_end_call(self, client, mock_voice_service):
        """通話終了のテスト"""
        mock_voice_service.end_call = AsyncMock(return_value=VoiceCallResponse(
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
            transcription=None,
            summary=None,
            purpose=CallPurpose.RESERVATION,
            task_id=None,
        ))
        
        response = client.post("/api/v1/voice/call/call-1/end")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["call"]["status"] == "completed"
    
    def test_end_call_not_found(self, client, mock_voice_service):
        """通話終了（存在しない場合）のテスト"""
        mock_voice_service.end_call = AsyncMock(
            side_effect=ValueError("Call not found: nonexistent-id")
        )
        
        response = client.post("/api/v1/voice/call/nonexistent-id/end")
        
        assert response.status_code == 400


class TestTwilioWebhooks:
    """Twilio Webhookのテスト"""
    
    def test_status_callback(self, client, mock_voice_service):
        """通話状態コールバックのテスト"""
        mock_voice_service.handle_status_callback = AsyncMock(return_value=VoiceCallResponse(
            id="call-1",
            call_sid="CA123456",
            direction=CallDirection.OUTBOUND,
            status=CallStatus.IN_PROGRESS,
            from_number="+815012345678",
            to_number="+819012345678",
            started_at=datetime.now(),
            answered_at=datetime.now(),
            ended_at=None,
            duration_seconds=None,
            transcription=None,
            summary=None,
            purpose=None,
            task_id=None,
        ))
        
        response = client.post("/api/v1/voice/webhook/status", data={
            "CallSid": "CA123456",
            "CallStatus": "in-progress",
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
    
    def test_outbound_webhook(self, client, mock_voice_service):
        """架電用TwiML Webhookのテスト"""
        mock_voice_service.generate_outbound_twiml = MagicMock(
            return_value='<?xml version="1.0" encoding="UTF-8"?><Response><Connect><Stream url="wss://example.com/stream"/></Connect></Response>'
        )
        
        response = client.post("/api/v1/voice/webhook/outbound", data={
            "CallSid": "CA123456",
        })
        
        assert response.status_code == 200
        assert "application/xml" in response.headers["content-type"]
        assert "<Response>" in response.text
    
    def test_incoming_webhook_enabled(self, client, mock_voice_service):
        """受電Webhook（受電有効時）のテスト"""
        mock_voice_service.get_voice_settings = AsyncMock(return_value=VoiceSettingsResponse(
            id="settings-1",
            user_id="user-1",
            inbound_enabled=True,
            default_greeting="こんにちは",
            auto_answer_whitelist=False,
            record_calls=False,
            notify_via_chat=True,
            elevenlabs_voice_id=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ))
        mock_voice_service.check_phone_rule = AsyncMock(return_value=None)
        mock_voice_service.create_call_record = AsyncMock(return_value=VoiceCallResponse(
            id="call-1",
            call_sid="CA123456",
            direction=CallDirection.INBOUND,
            status=CallStatus.INITIATED,
            from_number="+819012345678",
            to_number="+815012345678",
            started_at=datetime.now(),
            answered_at=None,
            ended_at=None,
            duration_seconds=None,
            transcription=None,
            summary=None,
            purpose=CallPurpose.INQUIRY,
            task_id=None,
        ))
        mock_voice_service.generate_inbound_twiml = MagicMock(
            return_value='<?xml version="1.0" encoding="UTF-8"?><Response><Connect><Stream url="wss://example.com/stream"/></Connect></Response>'
        )
        
        response = client.post("/api/v1/voice/webhook/incoming", data={
            "CallSid": "CA123456",
            "From": "+819012345678",
            "To": "+815012345678",
        })
        
        assert response.status_code == 200
        assert "application/xml" in response.headers["content-type"]
        assert "<Response>" in response.text
    
    def test_incoming_webhook_disabled(self, client, mock_voice_service):
        """受電Webhook（受電無効時）のテスト"""
        mock_voice_service.get_voice_settings = AsyncMock(return_value=VoiceSettingsResponse(
            id="settings-1",
            user_id="user-1",
            inbound_enabled=False,
            default_greeting="こんにちは",
            auto_answer_whitelist=False,
            record_calls=False,
            notify_via_chat=True,
            elevenlabs_voice_id=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ))
        
        response = client.post("/api/v1/voice/webhook/incoming", data={
            "CallSid": "CA123456",
            "From": "+819012345678",
            "To": "+815012345678",
        })
        
        assert response.status_code == 200
        assert "application/xml" in response.headers["content-type"]
        assert "出ることができません" in response.text or "<Hangup/>" in response.text


class TestMediaStreamsWebSocket:
    """Media Streams WebSocket (10E) のテスト"""
    
    def test_websocket_connection(self, client):
        """WebSocket接続のテスト"""
        # FastAPIのTestClientはWebSocketをサポート
        with client.websocket_connect("/api/v1/voice/stream/CA_TEST_123") as websocket:
            # Twilio Media Streams形式のconnectedイベントを送信
            websocket.send_json({
                "event": "connected",
                "protocol": "Call",
                "version": "1.0.0"
            })
            
            # startイベントを送信
            websocket.send_json({
                "event": "start",
                "sequenceNumber": "1",
                "start": {
                    "streamSid": "MZ_TEST_STREAM",
                    "accountSid": "AC_TEST",
                    "callSid": "CA_TEST_123",
                    "tracks": ["inbound"],
                    "mediaFormat": {
                        "encoding": "audio/x-mulaw",
                        "sampleRate": 8000,
                        "channels": 1
                    }
                },
                "streamSid": "MZ_TEST_STREAM"
            })
            
            # stopイベントを送信して正常終了
            websocket.send_json({
                "event": "stop",
                "sequenceNumber": "100",
                "streamSid": "MZ_TEST_STREAM"
            })
    
    def test_websocket_media_handling(self, client):
        """音声データ受信のテスト"""
        import base64
        
        with client.websocket_connect("/api/v1/voice/stream/CA_TEST_456") as websocket:
            # 接続イベント
            websocket.send_json({"event": "connected", "protocol": "Call"})
            
            # 開始イベント
            websocket.send_json({
                "event": "start",
                "start": {"streamSid": "MZ_TEST_STREAM_2", "callSid": "CA_TEST_456"},
                "streamSid": "MZ_TEST_STREAM_2"
            })
            
            # 音声データ（μ-law形式のダミーデータ）
            dummy_audio = base64.b64encode(b"\x7f" * 160).decode("utf-8")  # 20ms of silence
            websocket.send_json({
                "event": "media",
                "sequenceNumber": "2",
                "media": {
                    "track": "inbound",
                    "chunk": "1",
                    "timestamp": "0",
                    "payload": dummy_audio
                },
                "streamSid": "MZ_TEST_STREAM_2"
            })
            
            # 終了
            websocket.send_json({
                "event": "stop",
                "streamSid": "MZ_TEST_STREAM_2"
            })


class TestAudioConversion:
    """音声変換機能（10E Step 2）のテスト"""
    
    def test_ulaw_to_pcm_conversion(self):
        """μ-law → PCM変換のテスト"""
        from app.services.voice_service import VoiceService
        
        service = VoiceService()
        
        # ダミーのμ-lawデータ（無音に近い値）
        ulaw_data = bytes([0xFF] * 160)  # 0xFF = μ-law silence
        
        pcm_data = service.ulaw_to_pcm(ulaw_data)
        
        # PCMデータは2バイト/サンプルなので2倍のサイズ
        assert len(pcm_data) == len(ulaw_data) * 2
        assert isinstance(pcm_data, bytes)
    
    def test_pcm_to_ulaw_conversion(self):
        """PCM → μ-law変換のテスト"""
        from app.services.voice_service import VoiceService
        
        service = VoiceService()
        
        # ダミーのPCMデータ（16-bit, 無音に近い値）
        pcm_data = bytes([0x00, 0x00] * 160)
        
        ulaw_data = service.pcm_to_ulaw(pcm_data)
        
        # μ-lawデータは1バイト/サンプルなので半分のサイズ
        assert len(ulaw_data) == len(pcm_data) // 2
        assert isinstance(ulaw_data, bytes)
    
    def test_roundtrip_conversion(self):
        """往復変換のテスト（μ-law → PCM → μ-law）"""
        from app.services.voice_service import VoiceService
        
        service = VoiceService()
        
        # 元のμ-lawデータ
        original_ulaw = bytes([0x80, 0x90, 0xA0, 0xB0] * 40)
        
        # μ-law → PCM
        pcm_data = service.ulaw_to_pcm(original_ulaw)
        
        # PCM → μ-law
        converted_ulaw = service.pcm_to_ulaw(pcm_data)
        
        # サイズが同じであることを確認
        assert len(converted_ulaw) == len(original_ulaw)
    
    def test_resample_audio(self):
        """リサンプリングのテスト"""
        from app.services.voice_service import VoiceService
        
        service = VoiceService()
        
        # 8kHz PCMデータ
        pcm_8k = bytes([0x00, 0x80] * 8000)  # 1秒分
        
        # 8kHz → 16kHz
        pcm_16k = service.resample_audio(pcm_8k, 8000, 16000, 2)
        
        # 16kHzは約2倍のサイズ
        assert len(pcm_16k) >= len(pcm_8k) * 1.9
        assert len(pcm_16k) <= len(pcm_8k) * 2.1
    
    def test_pcm_to_wav(self):
        """PCM → WAV変換のテスト"""
        from app.services.voice_service import VoiceService
        
        service = VoiceService()
        
        # ダミーのPCMデータ
        pcm_data = bytes([0x00, 0x00] * 100)
        
        wav_data = service._pcm_to_wav(pcm_data, sample_rate=16000)
        
        # WAVヘッダーを確認
        assert wav_data[:4] == b"RIFF"
        assert b"WAVE" in wav_data[:12]
        assert len(wav_data) > len(pcm_data)

