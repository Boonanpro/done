"""
Tests for Phase 8B: Bank Account Management API
"""
import pytest
import uuid


class TestBankAccountAPI:
    """振込先管理APIのテスト"""
    
    def test_create_bank_account(self, client, auth_token):
        """振込先作成テスト"""
        response = client.post(
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
    
    def test_list_bank_accounts(self, client, auth_token):
        """振込先一覧取得テスト"""
        # まず1件作成
        client.post(
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
        response = client.get(
            "/api/v1/bank-accounts",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "bank_accounts" in data
        assert "total" in data
        assert isinstance(data["bank_accounts"], list)
        assert data["total"] >= 1
    
    def test_get_bank_account_detail(self, client, auth_token):
        """振込先詳細取得テスト"""
        # まず1件作成
        unique_id = uuid.uuid4().hex[:4]
        create_response = client.post(
            "/api/v1/bank-accounts",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "display_name": f"詳細テスト用{unique_id}",
                "bank_name": "りそな銀行",
                "bank_code": "0010",
                "branch_name": "池袋支店",
                "branch_code": "100",
                "account_type": "普通",
                "account_number": f"987{unique_id[:4].zfill(4)}",
                "account_holder": "シヨウサイテスト"
            }
        )
        
        account_id = create_response.json()["id"]
        
        # 詳細取得
        response = client.get(
            f"/api/v1/bank-accounts/{account_id}",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["id"] == account_id
        assert "詳細テスト用" in data["display_name"]
    
    def test_delete_bank_account(self, client, auth_token):
        """振込先削除テスト"""
        # まず1件作成
        unique_id = uuid.uuid4().hex[:4]
        create_response = client.post(
            "/api/v1/bank-accounts",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "display_name": f"削除用テスト{unique_id}",
                "bank_name": "三井住友銀行",
                "bank_code": "0009",
                "branch_name": "大阪支店",
                "branch_code": "500",
                "account_type": "当座",
                "account_number": f"111{unique_id[:4].zfill(4)}",
                "account_holder": "サクジヨテスト"
            }
        )
        
        account_id = create_response.json()["id"]
        
        # 削除
        response = client.delete(
            f"/api/v1/bank-accounts/{account_id}",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # 削除後は取得できないことを確認
        get_response = client.get(
            f"/api/v1/bank-accounts/{account_id}",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert get_response.status_code == 404
    
    def test_verify_bank_account(self, client, auth_token):
        """振込先検証テスト"""
        # まず1件作成
        unique_id = uuid.uuid4().hex[:4]
        create_response = client.post(
            "/api/v1/bank-accounts",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "display_name": f"検証用テスト{unique_id}",
                "bank_name": "楽天銀行",
                "bank_code": "0036",
                "branch_name": "第一営業支店",
                "branch_code": "251",
                "account_type": "普通",
                "account_number": f"222{unique_id[:4].zfill(4)}",
                "account_holder": "ケンショウテスト"
            }
        )
        
        account_id = create_response.json()["id"]
        assert create_response.json()["is_verified"] is False
        
        # 検証
        response = client.post(
            f"/api/v1/bank-accounts/{account_id}/verify",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["is_verified"] is True
    
    def test_duplicate_bank_account_rejected(self, client, auth_token):
        """重複振込先は拒否されるテスト"""
        unique_id = uuid.uuid4().hex[:4]
        bank_data = {
            "display_name": f"重複テスト{unique_id}",
            "bank_name": "ゆうちょ銀行",
            "bank_code": "9900",
            "branch_name": f"〇〇八支店{unique_id}",
            "branch_code": "008",
            "account_type": "普通",
            "account_number": f"333{unique_id[:4].zfill(4)}",
            "account_holder": "チヨウフクテスト"
        }
        
        # 1回目は成功
        response1 = client.post(
            "/api/v1/bank-accounts",
            headers={"Authorization": f"Bearer {auth_token}"},
            json=bank_data
        )
        assert response1.status_code == 200
        
        # 2回目は重複エラー
        response2 = client.post(
            "/api/v1/bank-accounts",
            headers={"Authorization": f"Bearer {auth_token}"},
            json=bank_data
        )
        assert response2.status_code == 400
        assert "既に登録" in response2.json()["detail"]
    
    def test_invalid_account_type_rejected(self, client, auth_token):
        """無効な口座種別は拒否されるテスト"""
        response = client.post(
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
    
    def test_unauthenticated_access_rejected(self, client):
        """認証なしアクセスは拒否されるテスト"""
        response = client.get("/api/v1/bank-accounts")
        assert response.status_code == 401
