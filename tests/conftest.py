"""
Pytest configuration and fixtures
"""
import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    """テスト用のHTTPクライアント"""
    return TestClient(app)


# ==================== Chat Fixtures ====================

@pytest.fixture
def auth_token(client):
    """認証済みユーザーのトークン"""
    import uuid
    unique_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    
    # Register
    client.post(
        "/api/v1/chat/register",
        json={
            "email": unique_email,
            "password": "password123",
            "display_name": "Test User"
        }
    )
    
    # Login
    response = client.post(
        "/api/v1/chat/login",
        json={
            "email": unique_email,
            "password": "password123"
        }
    )
    return response.json()["access_token"]


@pytest.fixture
def friend_token(client):
    """友達ユーザーのトークン"""
    import uuid
    unique_email = f"friend_{uuid.uuid4().hex[:8]}@example.com"
    
    # Register
    client.post(
        "/api/v1/chat/register",
        json={
            "email": unique_email,
            "password": "password123",
            "display_name": "Friend User"
        }
    )
    
    # Login
    response = client.post(
        "/api/v1/chat/login",
        json={
            "email": unique_email,
            "password": "password123"
        }
    )
    return response.json()["access_token"]


@pytest.fixture
def friend_id(client, auth_token, friend_token):
    """友達のユーザーID（招待承諾後）"""
    # Create invite from auth user
    invite_response = client.post(
        "/api/v1/chat/invite",
        json={},
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    code = invite_response.json()["code"]
    
    # Accept invite from friend
    accept_response = client.post(
        f"/api/v1/chat/invite/{code}/accept",
        headers={"Authorization": f"Bearer {friend_token}"}
    )
    return accept_response.json()["friend_id"]


@pytest.fixture
def room_id(client, auth_token, friend_id):
    """テスト用ルームID"""
    # Create a group room
    response = client.post(
        "/api/v1/chat/rooms",
        json={
            "name": "Test Room",
            "member_ids": [friend_id]
        },
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    return response.json()["id"]


@pytest.fixture
def another_friend_id(client, auth_token):
    """追加メンバー用の友達ID"""
    import uuid
    unique_email = f"another_{uuid.uuid4().hex[:8]}@example.com"
    
    # Register another user
    client.post(
        "/api/v1/chat/register",
        json={
            "email": unique_email,
            "password": "password123",
            "display_name": "Another User"
        }
    )
    
    # Login
    login_response = client.post(
        "/api/v1/chat/login",
        json={
            "email": unique_email,
            "password": "password123"
        }
    )
    another_token = login_response.json()["access_token"]
    
    # Create invite from auth user
    invite_response = client.post(
        "/api/v1/chat/invite",
        json={},
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    code = invite_response.json()["code"]
    
    # Accept invite
    accept_response = client.post(
        f"/api/v1/chat/invite/{code}/accept",
        headers={"Authorization": f"Bearer {another_token}"}
    )
    return accept_response.json()["friend_id"]
