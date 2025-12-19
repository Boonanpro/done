"""
Done Chat API Tests
Phase 2: AIネイティブチャット機能のテスト

テスト実行: pytest tests/test_chat_api.py -v
"""
import pytest


class TestChatAuth:
    """認証・ユーザー管理API"""
    
    def test_register(self, client):
        """POST /api/v1/chat/register - ユーザー登録"""
        response = client.post(
            "/api/v1/chat/register",
            json={
                "email": "test@example.com",
                "password": "password123",
                "display_name": "Test User"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert data["email"] == "test@example.com"
        assert data["display_name"] == "Test User"
    
    def test_register_duplicate_email(self, client):
        """POST /api/v1/chat/register - 重複メール"""
        # First registration
        client.post(
            "/api/v1/chat/register",
            json={
                "email": "duplicate@example.com",
                "password": "password123",
                "display_name": "User 1"
            }
        )
        # Second registration with same email
        response = client.post(
            "/api/v1/chat/register",
            json={
                "email": "duplicate@example.com",
                "password": "password456",
                "display_name": "User 2"
            }
        )
        assert response.status_code == 400
    
    def test_login(self, client):
        """POST /api/v1/chat/login - ログイン"""
        # Register first
        client.post(
            "/api/v1/chat/register",
            json={
                "email": "login@example.com",
                "password": "password123",
                "display_name": "Login User"
            }
        )
        # Login
        response = client.post(
            "/api/v1/chat/login",
            json={
                "email": "login@example.com",
                "password": "password123"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
    
    def test_login_invalid_password(self, client):
        """POST /api/v1/chat/login - 無効なパスワード"""
        # Register first
        client.post(
            "/api/v1/chat/register",
            json={
                "email": "invalid@example.com",
                "password": "password123",
                "display_name": "Invalid User"
            }
        )
        # Login with wrong password
        response = client.post(
            "/api/v1/chat/login",
            json={
                "email": "invalid@example.com",
                "password": "wrongpassword"
            }
        )
        assert response.status_code == 401
    
    def test_get_me(self, client):
        """GET /api/v1/chat/me - プロフィール取得"""
        # Register and login
        client.post(
            "/api/v1/chat/register",
            json={
                "email": "me@example.com",
                "password": "password123",
                "display_name": "Me User"
            }
        )
        login_response = client.post(
            "/api/v1/chat/login",
            json={
                "email": "me@example.com",
                "password": "password123"
            }
        )
        token = login_response.json()["access_token"]
        
        # Get profile
        response = client.get(
            "/api/v1/chat/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "me@example.com"
        assert data["display_name"] == "Me User"
    
    def test_get_me_unauthorized(self, client):
        """GET /api/v1/chat/me - 未認証"""
        response = client.get("/api/v1/chat/me")
        assert response.status_code == 401
    
    def test_update_me(self, client):
        """PATCH /api/v1/chat/me - プロフィール更新"""
        # Register and login
        client.post(
            "/api/v1/chat/register",
            json={
                "email": "update@example.com",
                "password": "password123",
                "display_name": "Original Name"
            }
        )
        login_response = client.post(
            "/api/v1/chat/login",
            json={
                "email": "update@example.com",
                "password": "password123"
            }
        )
        token = login_response.json()["access_token"]
        
        # Update profile
        response = client.patch(
            "/api/v1/chat/me",
            json={"display_name": "Updated Name"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["display_name"] == "Updated Name"


class TestChatInvite:
    """招待管理API"""
    
    def test_create_invite(self, client, auth_token):
        """POST /api/v1/chat/invite - 招待リンク発行"""
        response = client.post(
            "/api/v1/chat/invite",
            json={},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "code" in data
        assert "invite_url" in data
        assert data["max_uses"] == 1
        assert data["use_count"] == 0
    
    def test_get_invite(self, client, auth_token):
        """GET /api/v1/chat/invite/{code} - 招待リンク情報取得"""
        # Create invite
        create_response = client.post(
            "/api/v1/chat/invite",
            json={},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        code = create_response.json()["code"]
        
        # Get invite info
        response = client.get(f"/api/v1/chat/invite/{code}")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == code
        assert data["is_valid"] == True
    
    def test_accept_invite(self, client, auth_token):
        """POST /api/v1/chat/invite/{code}/accept - 招待承諾"""
        # Create invite from first user
        create_response = client.post(
            "/api/v1/chat/invite",
            json={},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        code = create_response.json()["code"]
        
        # Register second user
        client.post(
            "/api/v1/chat/register",
            json={
                "email": "friend@example.com",
                "password": "password123",
                "display_name": "Friend User"
            }
        )
        login_response = client.post(
            "/api/v1/chat/login",
            json={
                "email": "friend@example.com",
                "password": "password123"
            }
        )
        friend_token = login_response.json()["access_token"]
        
        # Accept invite
        response = client.post(
            f"/api/v1/chat/invite/{code}/accept",
            headers={"Authorization": f"Bearer {friend_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "friend_id" in data
        assert "room_id" in data


class TestChatFriends:
    """友達管理API"""
    
    def test_get_friends(self, client, auth_token):
        """GET /api/v1/chat/friends - 友達一覧"""
        response = client.get(
            "/api/v1/chat/friends",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "friends" in data
    
    def test_delete_friend(self, client, auth_token, friend_token, friend_id):
        """DELETE /api/v1/chat/friends/{id} - 友達削除"""
        response = client.delete(
            f"/api/v1/chat/friends/{friend_id}",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200


class TestChatRooms:
    """チャットルームAPI"""
    
    def test_get_rooms(self, client, auth_token):
        """GET /api/v1/chat/rooms - ルーム一覧"""
        response = client.get(
            "/api/v1/chat/rooms",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "rooms" in data
    
    def test_create_room(self, client, auth_token, friend_id):
        """POST /api/v1/chat/rooms - ルーム作成"""
        response = client.post(
            "/api/v1/chat/rooms",
            json={
                "name": "Test Room",
                "member_ids": [friend_id]
            },
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Room"
        assert data["type"] == "group"
    
    def test_get_room(self, client, auth_token, room_id):
        """GET /api/v1/chat/rooms/{id} - ルーム詳細"""
        response = client.get(
            f"/api/v1/chat/rooms/{room_id}",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == room_id
    
    def test_update_room(self, client, auth_token, room_id):
        """PATCH /api/v1/chat/rooms/{id} - ルーム設定更新"""
        response = client.patch(
            f"/api/v1/chat/rooms/{room_id}",
            json={"name": "Updated Room Name"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Room Name"
    
    def test_get_room_members(self, client, auth_token, room_id):
        """GET /api/v1/chat/rooms/{id}/members - メンバー一覧"""
        response = client.get(
            f"/api/v1/chat/rooms/{room_id}/members",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "members" in data
    
    def test_add_room_member(self, client, auth_token, room_id, another_friend_id):
        """POST /api/v1/chat/rooms/{id}/members - メンバー追加"""
        response = client.post(
            f"/api/v1/chat/rooms/{room_id}/members",
            json={"user_id": another_friend_id},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200


class TestChatMessages:
    """メッセージAPI"""
    
    def test_send_message(self, client, auth_token, room_id):
        """POST /api/v1/chat/rooms/{id}/messages - メッセージ送信"""
        response = client.post(
            f"/api/v1/chat/rooms/{room_id}/messages",
            json={"content": "Hello, World!"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["content"] == "Hello, World!"
        assert data["sender_type"] == "human"
    
    def test_get_messages(self, client, auth_token, room_id):
        """GET /api/v1/chat/rooms/{id}/messages - メッセージ履歴取得"""
        response = client.get(
            f"/api/v1/chat/rooms/{room_id}/messages",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "messages" in data
    
    def test_mark_as_read(self, client, auth_token, room_id):
        """POST /api/v1/chat/rooms/{id}/read - 既読マーク"""
        response = client.post(
            f"/api/v1/chat/rooms/{room_id}/read",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True


class TestChatAISettings:
    """AI設定API"""
    
    def test_get_ai_settings(self, client, auth_token, room_id):
        """GET /api/v1/chat/rooms/{id}/ai - AI設定取得"""
        response = client.get(
            f"/api/v1/chat/rooms/{room_id}/ai",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "enabled" in data
        assert "mode" in data
    
    def test_update_ai_settings(self, client, auth_token, room_id):
        """PATCH /api/v1/chat/rooms/{id}/ai - AI設定更新"""
        response = client.patch(
            f"/api/v1/chat/rooms/{room_id}/ai",
            json={"enabled": True, "mode": "assist"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] == True
        assert data["mode"] == "assist"
    
    def test_get_ai_summary(self, client, auth_token, room_id):
        """GET /api/v1/chat/rooms/{id}/ai/summary - AI要約取得"""
        response = client.get(
            f"/api/v1/chat/rooms/{room_id}/ai/summary",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert "message_count" in data
