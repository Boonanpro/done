"""
Credentials API Test
Phase 3B: 認証情報API自動テスト

テスト実行: pytest tests/test_credentials_api.py -v
"""
import pytest


class TestCredentialsAPI:
    """認証情報API"""
    
    def test_save_credentials(self, client):
        """POST /api/v1/credentials - 認証情報を保存"""
        response = client.post(
            "/api/v1/credentials",
            json={
                "service": "ex_reservation",
                "credentials": {
                    "email": "test@example.com",
                    "password": "secret123"
                }
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["service"] == "ex_reservation"
        assert "message" in data
    
    def test_save_credentials_amazon(self, client):
        """POST /api/v1/credentials - Amazon認証情報を保存"""
        response = client.post(
            "/api/v1/credentials",
            json={
                "service": "amazon",
                "credentials": {
                    "email": "amazon@example.com",
                    "password": "amazonpass"
                }
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["service"] == "amazon"
    
    def test_list_credentials(self, client):
        """GET /api/v1/credentials - 保存済みサービス一覧"""
        # まず認証情報を保存
        client.post(
            "/api/v1/credentials",
            json={
                "service": "rakuten",
                "credentials": {
                    "email": "rakuten@example.com",
                    "password": "rakutenpass"
                }
            }
        )
        
        # 一覧を取得
        response = client.get("/api/v1/credentials")
        assert response.status_code == 200
        data = response.json()
        assert "services" in data
        assert isinstance(data["services"], list)
        
        # 保存したサービスが含まれていることを確認
        services = [s["service"] for s in data["services"]]
        assert "rakuten" in services
    
    def test_delete_credentials(self, client):
        """DELETE /api/v1/credentials/{service} - 認証情報を削除"""
        # まず認証情報を保存
        client.post(
            "/api/v1/credentials",
            json={
                "service": "test_delete",
                "credentials": {
                    "email": "delete@example.com",
                    "password": "deletepass"
                }
            }
        )
        
        # 削除
        response = client.delete("/api/v1/credentials/test_delete")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["service"] == "test_delete"
        
        # 削除されていることを確認（一覧に含まれない）
        list_response = client.get("/api/v1/credentials")
        services = [s["service"] for s in list_response.json()["services"]]
        assert "test_delete" not in services
    
    def test_delete_credentials_not_found(self, client):
        """DELETE /api/v1/credentials/{service} - 存在しない認証情報"""
        response = client.delete("/api/v1/credentials/nonexistent_service")
        assert response.status_code == 404
    
    def test_update_credentials(self, client):
        """POST /api/v1/credentials - 認証情報を更新（上書き）"""
        # 最初に保存
        client.post(
            "/api/v1/credentials",
            json={
                "service": "update_test",
                "credentials": {
                    "email": "old@example.com",
                    "password": "oldpass"
                }
            }
        )
        
        # 更新（同じサービス名で再度POST）
        response = client.post(
            "/api/v1/credentials",
            json={
                "service": "update_test",
                "credentials": {
                    "email": "new@example.com",
                    "password": "newpass"
                }
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        
        # クリーンアップ
        client.delete("/api/v1/credentials/update_test")
