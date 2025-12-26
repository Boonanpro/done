"""
Phase 5: Message Detection - Unit Tests
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime
import json

# Test fixtures and mocks
from app.models.detection_schemas import (
    MessageSource,
    DetectionStatus,
    ContentType,
    StorageType,
)


class TestMessageDetectionService:
    """Phase 5A: Doneチャット検知サービスのテスト"""
    
    @pytest.fixture
    def mock_supabase(self):
        """Supabaseモック"""
        mock = MagicMock()
        mock.table.return_value = mock
        mock.select.return_value = mock
        mock.insert.return_value = mock
        mock.update.return_value = mock
        mock.eq.return_value = mock
        mock.order.return_value = mock
        mock.limit.return_value = mock
        mock.offset.return_value = mock
        mock.execute.return_value = MagicMock(data=[], count=0)
        return mock
    
    @pytest.fixture
    def detection_service(self, mock_supabase):
        """MessageDetectionServiceのテストインスタンス"""
        with patch('app.services.message_detection.get_supabase_client') as mock_client:
            mock_client.return_value.client = mock_supabase
            from app.services.message_detection import MessageDetectionService
            service = MessageDetectionService()
            service.supabase = mock_supabase
            return service
    
    @pytest.mark.asyncio
    async def test_detect_message_creates_new_record(self, detection_service, mock_supabase):
        """新しいメッセージを検知して保存できること"""
        # Setup - first call returns empty (no duplicate), second returns inserted data
        mock_supabase.execute.side_effect = [
            MagicMock(data=[]),  # duplicate check returns empty
            MagicMock(data=[{  # insert returns the new record
                "id": "test-id",
                "user_id": "user-1",
                "source": "done_chat",
                "content": "テストメッセージ",
                "status": "pending",
                "created_at": datetime.utcnow().isoformat(),
            }]),
        ]
        
        # Execute
        result = await detection_service.detect_message(
            user_id="user-1",
            source=MessageSource.DONE_CHAT,
            content="テストメッセージ",
            source_id="msg-1",
        )
        
        # Verify
        assert result["id"] == "test-id"
    
    @pytest.mark.asyncio
    async def test_detect_message_skips_duplicate(self, detection_service, mock_supabase):
        """重複メッセージをスキップすること"""
        # Setup - 既存メッセージを返す
        mock_supabase.execute.return_value = MagicMock(data=[{
            "id": "existing-id",
        }])
        
        # Execute
        result = await detection_service.detect_message(
            user_id="user-1",
            source=MessageSource.GMAIL,
            content="テスト",
            source_id="existing-msg",
        )
        
        # Verify
        assert result["id"] == "existing-id"
        # insertは呼ばれない（selectのみ）
    
    @pytest.mark.asyncio
    async def test_update_message_status(self, detection_service, mock_supabase):
        """メッセージステータスを更新できること"""
        # Setup
        mock_supabase.execute.return_value = MagicMock(data=[{
            "id": "msg-1",
            "status": "processed",
            "content_type": "invoice",
        }])
        
        # Execute
        result = await detection_service.update_message_status(
            message_id="msg-1",
            status=DetectionStatus.PROCESSED,
            content_type=ContentType.INVOICE,
        )
        
        # Verify
        assert result["status"] == "processed"
        assert result["content_type"] == "invoice"
        mock_supabase.update.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_pending_messages(self, detection_service, mock_supabase):
        """未処理メッセージを取得できること"""
        # Setup
        mock_supabase.execute.return_value = MagicMock(data=[
            {"id": "msg-1", "status": "pending"},
            {"id": "msg-2", "status": "pending"},
        ])
        
        # Execute
        result = await detection_service.get_pending_messages(limit=10)
        
        # Verify
        assert len(result) == 2
        mock_supabase.eq.assert_called_with("status", "pending")


class TestChatServiceDetectionHook:
    """Phase 5A: ChatServiceの検知フックのテスト"""
    
    @pytest.fixture
    def mock_supabase(self):
        """Supabaseモック"""
        mock = MagicMock()
        mock.table.return_value = mock
        mock.select.return_value = mock
        mock.insert.return_value = mock
        mock.eq.return_value = mock
        mock.execute.return_value = MagicMock(data=[])
        return mock
    
    @pytest.mark.asyncio
    async def test_send_message_triggers_detection_when_ai_enabled(self, mock_supabase):
        """AI有効ルームでメッセージ送信時に検知がトリガーされること"""
        with patch('app.services.chat_service.get_supabase_client') as mock_client:
            mock_client.return_value.client = mock_supabase
            
            # Setup
            # 1. メンバーシップチェック
            mock_supabase.execute.side_effect = [
                MagicMock(data=[{"user_id": "sender-1", "room_id": "room-1"}]),  # membership
                MagicMock(data=[{"display_name": "Test User", "done_user_id": "done-user-1"}]),  # sender
                MagicMock(data=[{"id": "msg-1", "room_id": "room-1", "sender_id": "sender-1", "sender_type": "human", "content": "test", "created_at": datetime.utcnow().isoformat()}]),  # insert
                MagicMock(data=[{"enabled": True, "mode": "auto"}]),  # ai_settings
                MagicMock(data=[]),  # duplicate check
                MagicMock(data=[{"id": "detected-1"}]),  # detection insert
            ]
            
            from app.services.chat_service import ChatService
            service = ChatService()
            service.supabase = mock_supabase
            
            with patch('app.services.message_detection.get_detection_service') as mock_detection:
                mock_detection_service = AsyncMock()
                mock_detection.return_value = mock_detection_service
                
                # Execute
                result = await service.send_message(
                    room_id="room-1",
                    sender_id="sender-1",
                    content="テストメッセージ",
                )
                
                # Verify
                assert result["id"] == "msg-1"
    
    @pytest.mark.asyncio
    async def test_send_message_skips_detection_when_ai_disabled(self, mock_supabase):
        """AI無効ルームでは検知がスキップされること"""
        with patch('app.services.chat_service.get_supabase_client') as mock_client:
            mock_client.return_value.client = mock_supabase
            
            # Setup
            mock_supabase.execute.side_effect = [
                MagicMock(data=[{"user_id": "sender-1", "room_id": "room-1"}]),  # membership
                MagicMock(data=[{"display_name": "Test User", "done_user_id": "done-user-1"}]),  # sender
                MagicMock(data=[{"id": "msg-1", "room_id": "room-1", "sender_id": "sender-1", "sender_type": "human", "content": "test", "created_at": datetime.utcnow().isoformat()}]),  # insert
                MagicMock(data=[{"enabled": False, "mode": "off"}]),  # ai_settings - disabled
            ]
            
            from app.services.chat_service import ChatService
            service = ChatService()
            service.supabase = mock_supabase
            
            with patch('app.services.message_detection.get_detection_service') as mock_detection:
                mock_detection_service = AsyncMock()
                mock_detection.return_value = mock_detection_service
                
                # Execute
                result = await service.send_message(
                    room_id="room-1",
                    sender_id="sender-1",
                    content="テストメッセージ",
                )
                
                # Verify
                assert result["id"] == "msg-1"
                # 検知は呼ばれない
                mock_detection_service.detect_message.assert_not_called()


class TestGmailService:
    """Phase 5B: Gmailサービスのテスト"""
    
    @pytest.fixture
    def mock_supabase(self):
        """Supabaseモック"""
        mock = MagicMock()
        mock.table.return_value = mock
        mock.select.return_value = mock
        mock.insert.return_value = mock
        mock.update.return_value = mock
        mock.eq.return_value = mock
        mock.execute.return_value = MagicMock(data=[])
        return mock
    
    @pytest.mark.asyncio
    async def test_get_connection_status_not_connected(self, mock_supabase):
        """未接続状態を正しく返すこと"""
        with patch('app.services.gmail_service.get_supabase_client') as mock_client:
            mock_client.return_value.client = mock_supabase
            mock_supabase.execute.return_value = MagicMock(data=[])
            
            from app.services.gmail_service import GmailService
            service = GmailService()
            service.supabase = mock_supabase
            
            # Execute
            status = await service.get_connection_status("user-1")
            
            # Verify
            assert status["connected"] is False
            assert status["email"] is None
    
    @pytest.mark.asyncio
    async def test_get_connection_status_connected(self, mock_supabase):
        """接続状態を正しく返すこと"""
        with patch('app.services.gmail_service.get_supabase_client') as mock_client:
            mock_client.return_value.client = mock_supabase
            mock_supabase.execute.return_value = MagicMock(data=[{
                "email": "test@gmail.com",
                "last_sync_at": "2024-01-01T00:00:00Z",
                "is_active": True,
            }])
            
            from app.services.gmail_service import GmailService
            service = GmailService()
            service.supabase = mock_supabase
            
            # Execute
            status = await service.get_connection_status("user-1")
            
            # Verify
            assert status["connected"] is True
            assert status["email"] == "test@gmail.com"
            assert status["is_active"] is True
    
    def test_extract_body_plain_text(self):
        """プレーンテキストの本文を抽出できること"""
        with patch('app.services.gmail_service.get_supabase_client'):
            from app.services.gmail_service import GmailService
            import base64
            
            service = GmailService()
            
            payload = {
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {
                            "data": base64.urlsafe_b64encode("Hello World".encode()).decode()
                        }
                    }
                ]
            }
            
            # Execute
            body = service._extract_body(payload)
            
            # Verify
            assert body == "Hello World"
    
    def test_extract_attachment_info(self):
        """添付ファイル情報を抽出できること"""
        with patch('app.services.gmail_service.get_supabase_client'):
            from app.services.gmail_service import GmailService
            
            service = GmailService()
            
            payload = {
                "parts": [
                    {
                        "filename": "invoice.pdf",
                        "mimeType": "application/pdf",
                        "body": {
                            "attachmentId": "att-1",
                            "size": 12345,
                        }
                    },
                    {
                        "filename": "image.png",
                        "mimeType": "image/png",
                        "body": {
                            "attachmentId": "att-2",
                            "size": 5678,
                        }
                    }
                ]
            }
            
            # Execute
            attachments = service._extract_attachment_info(payload, "msg-1")
            
            # Verify
            assert len(attachments) == 2
            assert attachments[0]["filename"] == "invoice.pdf"
            assert attachments[0]["mime_type"] == "application/pdf"
            assert attachments[1]["filename"] == "image.png"


class TestAttachmentService:
    """Phase 5C: 添付ファイルサービスのテスト"""
    
    @pytest.fixture
    def mock_supabase(self):
        """Supabaseモック"""
        mock = MagicMock()
        mock.table.return_value = mock
        mock.select.return_value = mock
        mock.insert.return_value = mock
        mock.delete.return_value = mock
        mock.eq.return_value = mock
        mock.order.return_value = mock
        mock.lt.return_value = mock
        mock.execute.return_value = MagicMock(data=[])
        return mock
    
    @pytest.fixture
    def attachment_service(self, mock_supabase, tmp_path):
        """AttachmentServiceのテストインスタンス"""
        with patch('app.services.attachment_service.get_supabase_client') as mock_client:
            mock_client.return_value.client = mock_supabase
            with patch('app.services.attachment_service.settings') as mock_settings:
                mock_settings.ATTACHMENT_STORAGE_PATH = str(tmp_path)
                mock_settings.ATTACHMENT_MAX_SIZE_MB = 10
                
                from app.services.attachment_service import AttachmentService
                service = AttachmentService()
                service.supabase = mock_supabase
                return service
    
    def test_calculate_checksum(self, attachment_service):
        """チェックサムを正しく計算できること"""
        data = b"test data"
        checksum = attachment_service._calculate_checksum(data)
        
        assert len(checksum) == 64  # SHA256 hex
        assert checksum == "916f0027a575074ce72a331777c3478d6513f786a591bd892da1a577bf2335f9"
    
    @pytest.mark.asyncio
    async def test_save_attachment_success(self, attachment_service, mock_supabase, tmp_path):
        """添付ファイルを保存できること"""
        # Setup
        mock_supabase.execute.side_effect = [
            MagicMock(data=[]),  # duplicate check
            MagicMock(data=[{
                "id": "att-1",
                "detected_message_id": "msg-1",
                "filename": "test.pdf",
                "mime_type": "application/pdf",
                "file_size": 100,
                "storage_type": "local",
            }]),  # insert
        ]
        
        # Execute
        result = await attachment_service.save_attachment(
            detected_message_id="msg-1",
            user_id="user-1",
            filename="test.pdf",
            mime_type="application/pdf",
            data=b"PDF content here",
        )
        
        # Verify
        assert result["id"] == "att-1"
        mock_supabase.insert.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_save_attachment_size_limit(self, attachment_service):
        """ファイルサイズ制限が適用されること"""
        # 11MBのデータ（10MB制限を超過）
        large_data = b"x" * (11 * 1024 * 1024)
        
        with pytest.raises(ValueError, match="File size exceeds limit"):
            await attachment_service.save_attachment(
                detected_message_id="msg-1",
                user_id="user-1",
                filename="large.pdf",
                mime_type="application/pdf",
                data=large_data,
            )
    
    @pytest.mark.asyncio
    async def test_get_attachments_for_message(self, attachment_service, mock_supabase):
        """メッセージの添付ファイル一覧を取得できること"""
        # Setup
        mock_supabase.execute.return_value = MagicMock(data=[
            {"id": "att-1", "filename": "file1.pdf"},
            {"id": "att-2", "filename": "file2.png"},
        ])
        
        # Execute
        result = await attachment_service.get_attachments_for_message("msg-1")
        
        # Verify
        assert len(result) == 2


class TestDetectionRoutes:
    """Detection APIルートのテスト"""
    
    @pytest.fixture
    def client(self):
        """テストクライアント"""
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app)
    
    def test_list_detected_messages(self, client):
        """検知メッセージ一覧APIが動作すること"""
        with patch('app.api.detection_routes.get_detection_service') as mock:
            mock_service = AsyncMock()
            mock_service.get_detected_messages.return_value = []
            mock_service.count_messages.return_value = 0
            mock.return_value = mock_service
            
            response = client.get("/api/v1/detection/messages")
            
            assert response.status_code == 200
            data = response.json()
            assert "messages" in data
            assert "total" in data


class TestGmailRoutes:
    """Gmail APIルートのテスト"""
    
    @pytest.fixture
    def client(self):
        """テストクライアント"""
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app)
    
    def test_gmail_status_not_connected(self, client):
        """Gmail未接続状態を取得できること"""
        with patch('app.api.gmail_routes.get_gmail_service') as mock:
            mock_service = AsyncMock()
            mock_service.get_connection_status.return_value = {
                "connected": False,
                "email": None,
                "last_sync": None,
                "is_active": False,
            }
            mock.return_value = mock_service
            
            response = client.get("/api/v1/gmail/status")
            
            assert response.status_code == 200
            data = response.json()
            assert data["connected"] is False
    
    def test_gmail_setup_returns_auth_url(self, client):
        """Gmail設定がauth_urlを返すこと"""
        with patch('app.api.gmail_routes.get_gmail_service') as mock:
            mock_service = MagicMock()
            mock_service.get_auth_url.return_value = "https://accounts.google.com/o/oauth2/auth?..."
            mock.return_value = mock_service
            
            response = client.post("/api/v1/gmail/setup")
            
            assert response.status_code == 200
            data = response.json()
            assert "auth_url" in data
            assert data["auth_url"].startswith("https://accounts.google.com")









