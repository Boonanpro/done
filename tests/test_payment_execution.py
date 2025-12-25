"""
Tests for Phase 8A: Payment Execution API
"""
import pytest
import uuid
from datetime import datetime, timedelta


class TestPaymentExecutionAPI:
    """支払い実行APIのテスト"""
    
    def create_test_invoice(self, client, auth_token):
        """テスト用の請求書を作成"""
        unique_id = uuid.uuid4().hex[:6]
        response = client.post(
            "/api/v1/invoices",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "sender_name": f"テスト会社_{unique_id}",
                "amount": 50000,
                "due_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                "source": "manual",
                "source_channel": "test",
                "bank_info": {
                    "bank_name": "テスト銀行",
                    "branch_name": "テスト支店",
                    "account_type": "普通",
                    "account_number": "1234567",
                    "account_holder": "テストホルダー"
                }
            }
        )
        assert response.status_code == 200
        return response.json()
    
    def approve_invoice(self, client, auth_token, invoice_id):
        """請求書を承認"""
        response = client.post(
            f"/api/v1/invoices/{invoice_id}/approve",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={}
        )
        assert response.status_code == 200
        return response.json()
    
    def test_execute_payment_simulation(self, client, auth_token):
        """シミュレーション支払い実行テスト"""
        # 請求書を作成
        invoice = self.create_test_invoice(client, auth_token)
        invoice_id = invoice["id"]
        assert invoice["status"] == "pending"
        
        # 承認
        approved = self.approve_invoice(client, auth_token, invoice_id)
        assert approved["status"] == "approved"
        
        # 支払い実行
        response = client.post(
            f"/api/v1/invoices/{invoice_id}/pay",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"bank_type": "simulation"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["invoice_id"] == invoice_id
        assert data["status"] == "completed"
        assert "execution_id" in data
        assert "シミュレーション" in data["message"] or "SIM" in data["message"]
    
    def test_execute_payment_not_approved(self, client, auth_token):
        """未承認の請求書への支払いは失敗するテスト"""
        # 請求書を作成（承認しない）
        invoice = self.create_test_invoice(client, auth_token)
        invoice_id = invoice["id"]
        assert invoice["status"] == "pending"
        
        # 支払い実行（失敗するはず）
        response = client.post(
            f"/api/v1/invoices/{invoice_id}/pay",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"bank_type": "simulation"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "failed"
        assert "承認済みではありません" in data["message"]
    
    def test_get_payment_status(self, client, auth_token):
        """支払い状況取得テスト"""
        # 請求書を作成して承認
        invoice = self.create_test_invoice(client, auth_token)
        invoice_id = invoice["id"]
        self.approve_invoice(client, auth_token, invoice_id)
        
        # 支払い実行
        client.post(
            f"/api/v1/invoices/{invoice_id}/pay",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"bank_type": "simulation"}
        )
        
        # 支払い状況を取得
        response = client.get(
            f"/api/v1/invoices/{invoice_id}/payment-status",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["invoice_id"] == invoice_id
        assert data["status"] == "completed"
        assert "execution_id" in data
        assert "transaction_id" in data
        assert data["transaction_id"] is not None
        assert data["transaction_id"].startswith("SIM-")
    
    def test_get_payment_status_no_execution(self, client, auth_token):
        """未実行の請求書の支払い状況取得テスト"""
        # 請求書を作成のみ
        invoice = self.create_test_invoice(client, auth_token)
        invoice_id = invoice["id"]
        
        # 支払い状況を取得
        response = client.get(
            f"/api/v1/invoices/{invoice_id}/payment-status",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["invoice_id"] == invoice_id
        assert data["status"] == "pending"
    
    def test_payment_unauthenticated_rejected(self, client):
        """認証なしの支払い実行は拒否されるテスト"""
        response = client.post(
            "/api/v1/invoices/some-id/pay",
            json={"bank_type": "simulation"}
        )
        assert response.status_code == 401
    
    def test_payment_status_unauthenticated_rejected(self, client):
        """認証なしの支払い状況取得は拒否されるテスト"""
        response = client.get("/api/v1/invoices/some-id/payment-status")
        assert response.status_code == 401


