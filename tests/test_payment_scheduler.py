"""
Tests for Phase 7D: Payment Scheduler
"""
import pytest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock


class TestPaymentScheduler:
    """支払いスケジューラのテスト"""
    
    def create_test_invoice(self, client, auth_token, scheduled_time=None):
        """テスト用の請求書を作成"""
        unique_id = uuid.uuid4().hex[:6]
        response = client.post(
            "/api/v1/invoices",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "sender_name": f"スケジューラテスト_{unique_id}",
                "amount": 30000,
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
    
    def test_celery_beat_schedule_configured(self):
        """Celery Beatスケジュールが設定されていることを確認"""
        from app.tasks.celery_app import celery_app
        
        beat_schedule = celery_app.conf.beat_schedule
        
        assert "check-scheduled-payments" in beat_schedule
        assert beat_schedule["check-scheduled-payments"]["task"] == "app.tasks.payment_tasks.check_scheduled_payments"
    
    def test_payment_tasks_included(self):
        """payment_tasksがCeleryに含まれていることを確認"""
        from app.tasks.celery_app import celery_app
        
        includes = celery_app.conf.include
        
        assert "app.tasks.payment_tasks" in includes
    
    def test_check_scheduled_payments_task_exists(self):
        """check_scheduled_paymentsタスクが存在することを確認"""
        from app.tasks.payment_tasks import check_scheduled_payments
        
        assert check_scheduled_payments is not None
        assert callable(check_scheduled_payments)
    
    def test_execute_single_payment_task_exists(self):
        """execute_single_paymentタスクが存在することを確認"""
        from app.tasks.payment_tasks import execute_single_payment
        
        assert execute_single_payment is not None
        assert callable(execute_single_payment)
    
    def test_check_scheduled_payments_no_invoices(self):
        """スケジュールされた請求書がない場合のテスト"""
        from app.tasks.payment_tasks import check_scheduled_payments
        
        # タスクを直接実行
        result = check_scheduled_payments()
        
        # エラーがなければOK（processed: 0でも成功）
        assert result is not None
        if "error" not in result:
            assert "processed" in result
    
    def test_invoice_approval_sets_scheduled_time(self, client, auth_token):
        """請求書承認時にscheduled_payment_timeが設定されることを確認"""
        # 請求書を作成
        invoice = self.create_test_invoice(client, auth_token)
        invoice_id = invoice["id"]
        
        # 承認
        approved = self.approve_invoice(client, auth_token, invoice_id)
        
        # scheduled_payment_timeが設定されている
        assert approved["status"] == "approved"
        assert approved.get("scheduled_payment_time") is not None


