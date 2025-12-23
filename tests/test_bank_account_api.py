"""
Tests for Phase 8B: Bank Account Management API
"""
import pytest
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.fixture
async def async_client():
    """非同期HTTPクライアントを作成"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def auth_token(async_client: AsyncClient):
    """テスト用認証トークンを取得"""
    import uuid
    
    # テストユーザーを登録
    email = f"test_bank_{uuid.uuid4().hex[:8]}@example.com"
    register_response = await async_client.post(
        "/api/v1/chat/register",
        json={
            "email": email,
            "password": "testpass123",
            "display_name": "Bank Test User"
        }
    )
    
    if register_response.status_code != 200:
        # 既に登録されている場合はログインを試みる
        pass
    
    # ログイン
    login_response = await async_client.post(
        "/api/v1/chat/login",
        json={
            "email": email,
            "password": "testpass123"
        }
    )
    
    if login_response.status_code == 200:
        return login_response.json()["access_token"]
    
    # フォールバック: 既存ユーザーでログイン試行
    login_response = await async_client.post(
        "/api/v1/chat/login",
        json={
            "email": "test_phase8@example.com",
            "password": "test1234"
        }
    )
    return login_response.json()["access_token"]


class TestBankAccountAPI:
    """振込先管理APIのテスト"""
    
    @pytest.mark.asyncio
    async def test_create_bank_account(self, async_client: AsyncClient, auth_token: str):
        """振込先作成テスト"""
        response = await async_client.post(
            "/api/v1/bank-accounts",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "display_name": "テスト株式会社",
                "bank_name": "三菱UFJ銀行",
                "bank_code": "0005",
                "branch_name": "渋谷支店",
                "branch_code": "045",
                "account_type": "普通",
                "account_number": "1234567",
                "account_holder": "カ）テスト"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "id" in data
        assert data["display_name"] == "テスト株式会社"
        assert data["bank_name"] == "三菱UFJ銀行"
        assert data["bank_code"] == "0005"
        assert data["branch_name"] == "渋谷支店"
        assert data["branch_code"] == "045"
        assert data["account_type"] == "普通"
        # 口座番号はマスクされる
        assert "****" in data["account_number"]
        assert data["account_holder"] == "カ）テスト"
        assert data["is_verified"] is False
    
    @pytest.mark.asyncio
    async def test_list_bank_accounts(self, async_client: AsyncClient, auth_token: str):
        """振込先一覧取得テスト"""
        # まず1件作成
        await async_client.post(
            "/api/v1/bank-accounts",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "display_name": "リスト用テスト",
                "bank_name": "みずほ銀行",
                "bank_code": "0001",
                "branch_name": "新宿支店",
                "branch_code": "001",
                "account_type": "普通",
                "account_number": "7654321",
                "account_holder": "テストユーザー"
            }
        )
        
        # 一覧取得
        response = await async_client.get(
            "/api/v1/bank-accounts",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "bank_accounts" in data
        assert "total" in data
        assert isinstance(data["bank_accounts"], list)
        assert data["total"] >= 1
    
    @pytest.mark.asyncio
    async def test_get_bank_account_detail(self, async_client: AsyncClient, auth_token: str):
        """振込先詳細取得テスト"""
        # まず1件作成
        create_response = await async_client.post(
            "/api/v1/bank-accounts",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "display_name": "詳細テスト用",
                "bank_name": "りそな銀行",
                "bank_code": "0010",
                "branch_name": "池袋支店",
                "branch_code": "100",
                "account_type": "普通",
                "account_number": "9876543",
                "account_holder": "シヨウサイテスト"
            }
        )
        
        account_id = create_response.json()["id"]
        
        # 詳細取得
        response = await async_client.get(
            f"/api/v1/bank-accounts/{account_id}",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["id"] == account_id
        assert data["display_name"] == "詳細テスト用"
    
    @pytest.mark.asyncio
    async def test_delete_bank_account(self, async_client: AsyncClient, auth_token: str):
        """振込先削除テスト"""
        # まず1件作成
        create_response = await async_client.post(
            "/api/v1/bank-accounts",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "display_name": "削除用テスト",
                "bank_name": "三井住友銀行",
                "bank_code": "0009",
                "branch_name": "大阪支店",
                "branch_code": "500",
                "account_type": "当座",
                "account_number": "1111111",
                "account_holder": "サクジヨテスト"
            }
        )
        
        account_id = create_response.json()["id"]
        
        # 削除
        response = await async_client.delete(
            f"/api/v1/bank-accounts/{account_id}",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # 削除後は取得できないことを確認
        get_response = await async_client.get(
            f"/api/v1/bank-accounts/{account_id}",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert get_response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_verify_bank_account(self, async_client: AsyncClient, auth_token: str):
        """振込先検証テスト"""
        # まず1件作成
        create_response = await async_client.post(
            "/api/v1/bank-accounts",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "display_name": "検証用テスト",
                "bank_name": "楽天銀行",
                "bank_code": "0036",
                "branch_name": "第一営業支店",
                "branch_code": "251",
                "account_type": "普通",
                "account_number": "2222222",
                "account_holder": "ケンショウテスト"
            }
        )
        
        account_id = create_response.json()["id"]
        assert create_response.json()["is_verified"] is False
        
        # 検証
        response = await async_client.post(
            f"/api/v1/bank-accounts/{account_id}/verify",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["is_verified"] is True
    
    @pytest.mark.asyncio
    async def test_duplicate_bank_account_rejected(self, async_client: AsyncClient, auth_token: str):
        """重複振込先は拒否されるテスト"""
        bank_data = {
            "display_name": "重複テスト",
            "bank_name": "ゆうちょ銀行",
            "bank_code": "9900",
            "branch_name": "〇〇八支店",
            "branch_code": "008",
            "account_type": "普通",
            "account_number": "3333333",
            "account_holder": "チヨウフクテスト"
        }
        
        # 1回目は成功
        response1 = await async_client.post(
            "/api/v1/bank-accounts",
            headers={"Authorization": f"Bearer {auth_token}"},
            json=bank_data
        )
        assert response1.status_code == 200
        
        # 2回目は重複エラー
        response2 = await async_client.post(
            "/api/v1/bank-accounts",
            headers={"Authorization": f"Bearer {auth_token}"},
            json=bank_data
        )
        assert response2.status_code == 400
        assert "既に登録" in response2.json()["detail"]
    
    @pytest.mark.asyncio
    async def test_invalid_account_type_rejected(self, async_client: AsyncClient, auth_token: str):
        """無効な口座種別は拒否されるテスト"""
        response = await async_client.post(
            "/api/v1/bank-accounts",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "display_name": "無効種別テスト",
                "bank_name": "テスト銀行",
                "branch_name": "テスト支店",
                "account_type": "無効な種別",  # 普通/当座以外
                "account_number": "4444444",
                "account_holder": "テスト"
            }
        )
        
        assert response.status_code == 422  # Validation Error
    
    @pytest.mark.asyncio
    async def test_unauthenticated_access_rejected(self, async_client: AsyncClient):
        """認証なしアクセスは拒否されるテスト"""
        response = await async_client.get("/api/v1/bank-accounts")
        assert response.status_code == 401

