"""
Invoice Management Tests - Phase 7
"""
import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, patch, MagicMock

from app.models.invoice_schemas import (
    InvoiceExtractionResult,
    BankInfo,
    InvoiceStatus,
    ScheduleCalculationResponse,
)
from app.services.invoice_service import (
    InvoiceExtractor,
    ScheduleCalculator,
    get_invoice_extractor,
    get_schedule_calculator,
)


class TestInvoiceExtractor:
    """7A: 請求書情報抽出テスト"""
    
    def test_parse_existing_data_success(self):
        """Phase 6の抽出データをパースできる"""
        existing_data = {
            "amount": 50000,
            "due_date": "2024-01-31",
            "invoice_number": "INV-2024-001",
            "issuer_name": "株式会社テスト",
            "bank_info": {
                "bank_name": "みずほ銀行",
                "branch_name": "本店",
                "account_type": "普通",
                "account_number": "1234567",
                "account_holder": "カ）テストカイシャ"
            }
        }
        
        result = InvoiceExtractor._parse_existing_data(existing_data)
        
        assert result.success is True
        assert result.amount == 50000
        assert result.due_date.year == 2024
        assert result.due_date.month == 1
        assert result.due_date.day == 31
        assert result.invoice_number == "INV-2024-001"
        assert result.issuer_name == "株式会社テスト"
        assert result.bank_info is not None
        assert result.bank_info.bank_name == "みずほ銀行"
    
    def test_parse_existing_data_with_string_amount(self):
        """文字列金額をパースできる"""
        existing_data = {
            "amount": "50,000",
            "due_date": "2024-01-31",
            "issuer_name": "テスト会社"
        }
        
        result = InvoiceExtractor._parse_existing_data(existing_data)
        
        assert result.success is True
        assert result.amount == 50000
    
    def test_parse_existing_data_with_japanese_date(self):
        """日本語日付形式をパースできる"""
        existing_data = {
            "amount": 10000,
            "due_date": "2024年01月31日",
            "issuer_name": "テスト"
        }
        
        result = InvoiceExtractor._parse_existing_data(existing_data)
        
        assert result.success is True
        assert result.due_date is not None
        assert result.due_date.year == 2024
    
    def test_parse_existing_data_with_slash_date(self):
        """スラッシュ形式の日付をパースできる"""
        existing_data = {
            "amount": 10000,
            "due_date": "2024/01/31",
            "issuer_name": "テスト"
        }
        
        result = InvoiceExtractor._parse_existing_data(existing_data)
        
        assert result.success is True
        assert result.due_date is not None
    
    def test_parse_existing_data_missing_fields(self):
        """必須フィールドがなくても成功する"""
        existing_data = {
            "issuer_name": "テスト会社"
        }
        
        result = InvoiceExtractor._parse_existing_data(existing_data)
        
        assert result.success is True
        assert result.amount is None
        assert result.due_date is None
    
    def test_build_result_success(self):
        """AI応答からの結果構築が成功する"""
        data = {
            "amount": 100000,
            "currency": "JPY",
            "due_date": "2024-02-28",
            "invoice_number": "INV-2024-002",
            "invoice_month": "2024-02",
            "issuer_name": "株式会社サンプル",
            "bank_info": {
                "bank_name": "三菱UFJ銀行",
                "branch_name": "渋谷支店",
                "account_type": "普通",
                "account_number": "9876543"
            },
            "confidence_score": 0.95
        }
        
        result = InvoiceExtractor._build_result(data)
        
        assert result.success is True
        assert result.amount == 100000
        assert result.currency == "JPY"
        assert result.invoice_number == "INV-2024-002"
        assert result.bank_info.bank_name == "三菱UFJ銀行"
        assert result.confidence_score == 0.95
    
    def test_build_result_with_null_bank_info(self):
        """bank_infoがnullの場合"""
        data = {
            "amount": 50000,
            "due_date": "2024-01-31",
            "bank_info": None
        }
        
        result = InvoiceExtractor._build_result(data)
        
        assert result.success is True
        assert result.bank_info is None
    
    def test_build_result_with_partial_bank_info(self):
        """bank_infoが部分的な場合"""
        data = {
            "amount": 50000,
            "due_date": "2024-01-31",
            "bank_info": {
                "bank_name": "みずほ銀行",
                "branch_name": None,
                "account_number": None
            }
        }
        
        result = InvoiceExtractor._build_result(data)
        
        assert result.success is True
        assert result.bank_info is not None
        assert result.bank_info.bank_name == "みずほ銀行"
    
    @pytest.mark.asyncio
    async def test_extract_from_text_with_existing_data(self):
        """既存データがある場合はAI呼び出しをスキップ"""
        existing_data = {
            "amount": 50000,
            "due_date": "2024-01-31",
            "issuer_name": "テスト会社"
        }
        
        result = await InvoiceExtractor.extract_from_text(
            text="テスト請求書",
            existing_data=existing_data
        )
        
        assert result.success is True
        assert result.amount == 50000
    
    @pytest.mark.asyncio
    async def test_extract_from_text_calls_ai(self):
        """既存データがない場合はAIを呼び出す"""
        mock_response = MagicMock()
        mock_response.content = '''```json
{
    "amount": 75000,
    "due_date": "2024-03-15",
    "invoice_number": "INV-TEST",
    "issuer_name": "AI抽出会社",
    "bank_info": null,
    "confidence_score": 0.9
}
```'''
        
        with patch('langchain_anthropic.ChatAnthropic') as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.ainvoke.return_value = mock_response
            mock_llm_class.return_value = mock_llm
            
            result = await InvoiceExtractor.extract_from_text(
                text="請求書\n金額: 75,000円\n期日: 2024年3月15日"
            )
            
            assert result.success is True
            assert result.amount == 75000
            assert result.issuer_name == "AI抽出会社"
    
    def test_get_invoice_extractor_singleton(self):
        """シングルトンインスタンスが返される"""
        extractor1 = get_invoice_extractor()
        extractor2 = get_invoice_extractor()
        
        assert extractor1 is extractor2
        assert isinstance(extractor1, InvoiceExtractor)


class TestScheduleCalculator:
    """7B: スケジュール計算テスト"""
    
    JST = ZoneInfo("Asia/Tokyo")
    
    def test_calculate_payment_schedule_basic(self):
        """基本的なスケジュール計算（期日の前日18:00）"""
        due_date = datetime(2024, 1, 31, 0, 0, 0, tzinfo=self.JST)
        
        result = ScheduleCalculator.calculate_payment_schedule(due_date)
        
        assert result.scheduled_payment_time.year == 2024
        assert result.scheduled_payment_time.month == 1
        assert result.scheduled_payment_time.day == 30  # 前日
        assert result.scheduled_payment_time.hour == 18
        assert result.due_date == due_date
        assert result.is_holiday_adjusted is False
    
    def test_calculate_payment_schedule_february(self):
        """2月末の期日テスト"""
        due_date = datetime(2024, 2, 29, 0, 0, 0, tzinfo=self.JST)  # うるう年
        
        result = ScheduleCalculator.calculate_payment_schedule(due_date)
        
        assert result.scheduled_payment_time.day == 28
        assert result.scheduled_payment_time.month == 2
    
    def test_calculate_payment_schedule_without_timezone(self):
        """タイムゾーンなしの日時でも動作する"""
        due_date = datetime(2024, 3, 15)  # タイムゾーンなし
        
        result = ScheduleCalculator.calculate_payment_schedule(due_date)
        
        assert result.scheduled_payment_time.day == 14
        assert result.scheduled_payment_time.hour == 18
    
    def test_calculate_from_invoice_month_basic(self):
        """請求対象月からの計算（翌月末の前日）"""
        # 12月分 → 1月末の前日（1月30日）
        result = ScheduleCalculator.calculate_from_invoice_month("2023-12")
        
        assert result.scheduled_payment_time.year == 2024
        assert result.scheduled_payment_time.month == 1
        assert result.scheduled_payment_time.day == 30  # 1月31日の前日
        assert result.scheduled_payment_time.hour == 18
    
    def test_calculate_from_invoice_month_february(self):
        """1月分 → 2月末の前日（うるう年考慮）"""
        # 2024年はうるう年なので2月は29日まで
        result = ScheduleCalculator.calculate_from_invoice_month("2024-01")
        
        assert result.scheduled_payment_time.month == 2
        assert result.scheduled_payment_time.day == 28  # 2月29日の前日
    
    def test_calculate_from_invoice_month_april(self):
        """3月分 → 4月末の前日（30日の月）"""
        result = ScheduleCalculator.calculate_from_invoice_month("2024-03")
        
        assert result.scheduled_payment_time.month == 4
        assert result.scheduled_payment_time.day == 29  # 4月30日の前日
    
    def test_adjust_for_holidays_saturday(self):
        """土曜日は金曜日にシフト"""
        # 2024年1月27日は土曜日
        saturday = datetime(2024, 1, 27, 18, 0, 0, tzinfo=self.JST)
        
        adjusted, was_adjusted = ScheduleCalculator._adjust_for_holidays(saturday)
        
        assert was_adjusted is True
        assert adjusted.weekday() == 4  # 金曜日
        assert adjusted.day == 26
    
    def test_adjust_for_holidays_sunday(self):
        """日曜日は金曜日にシフト"""
        # 2024年1月28日は日曜日
        sunday = datetime(2024, 1, 28, 18, 0, 0, tzinfo=self.JST)
        
        adjusted, was_adjusted = ScheduleCalculator._adjust_for_holidays(sunday)
        
        assert was_adjusted is True
        assert adjusted.weekday() == 4  # 金曜日
        assert adjusted.day == 26
    
    def test_adjust_for_holidays_weekday(self):
        """平日はそのまま"""
        # 2024年1月29日は月曜日
        monday = datetime(2024, 1, 29, 18, 0, 0, tzinfo=self.JST)
        
        adjusted, was_adjusted = ScheduleCalculator._adjust_for_holidays(monday)
        
        assert was_adjusted is False
        assert adjusted == monday
    
    def test_is_payment_due_past(self):
        """過去の日時は支払い時刻到来"""
        past = datetime.now(self.JST) - timedelta(hours=1)
        
        assert ScheduleCalculator.is_payment_due(past) is True
    
    def test_is_payment_due_future(self):
        """未来の日時は支払い時刻未到来"""
        future = datetime.now(self.JST) + timedelta(hours=1)
        
        assert ScheduleCalculator.is_payment_due(future) is False
    
    def test_get_schedule_calculator_singleton(self):
        """シングルトンインスタンスが返される"""
        calc1 = get_schedule_calculator()
        calc2 = get_schedule_calculator()
        
        assert calc1 is calc2
        assert isinstance(calc1, ScheduleCalculator)


class TestInvoiceCreateAPI:
    """7C-1: POST /invoices 請求書作成APIテスト"""
    
    def test_create_invoice_success(self, client, auth_token):
        """請求書作成が成功する"""
        response = client.post(
            "/api/v1/invoices",
            json={
                "sender_name": "株式会社テスト",
                "amount": 50000,
                "due_date": "2024-01-31T00:00:00Z",
                "invoice_number": "INV-TEST-001",
                "invoice_month": "2024-01",
                "source": "manual",
                "source_channel": "manual",
                "bank_info": {
                    "bank_name": "みずほ銀行",
                    "branch_name": "本店",
                    "account_type": "普通",
                    "account_number": "1234567"
                }
            },
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["sender_name"] == "株式会社テスト"
        assert data["amount"] == 50000
        assert data["status"] == "pending"
        assert data["invoice_number"] == "INV-TEST-001"
        assert "scheduled_payment_time" in data
        assert data["bank_info"]["bank_name"] == "みずほ銀行"
    
    def test_create_invoice_minimal(self, client, auth_token):
        """最小限のフィールドで請求書作成"""
        response = client.post(
            "/api/v1/invoices",
            json={
                "sender_name": "最小テスト社",
                "amount": 10000,
                "due_date": "2024-02-15T00:00:00Z",
                "source": "email",
                "source_channel": "gmail"
            },
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["sender_name"] == "最小テスト社"
        assert data["amount"] == 10000
    
    def test_create_invoice_without_auth(self, client):
        """認証なしでは失敗する"""
        response = client.post(
            "/api/v1/invoices",
            json={
                "sender_name": "テスト",
                "amount": 1000,
                "due_date": "2024-01-31T00:00:00Z",
                "source": "manual",
                "source_channel": "manual"
            }
        )
        
        assert response.status_code == 401


class TestInvoiceListAPI:
    """7C-2: GET /invoices 請求書一覧APIテスト"""
    
    def test_list_invoices_empty(self, client, auth_token):
        """空の一覧が取得できる"""
        response = client.get(
            "/api/v1/invoices",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "invoices" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
    
    def test_list_invoices_with_data(self, client, auth_token):
        """作成した請求書が一覧に表示される"""
        # まず請求書を作成
        client.post(
            "/api/v1/invoices",
            json={
                "sender_name": "一覧テスト社",
                "amount": 25000,
                "due_date": "2024-03-15T00:00:00Z",
                "source": "manual",
                "source_channel": "manual"
            },
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        # 一覧を取得
        response = client.get(
            "/api/v1/invoices",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        
        # 作成した請求書が含まれているか
        sender_names = [inv["sender_name"] for inv in data["invoices"]]
        assert "一覧テスト社" in sender_names
    
    def test_list_invoices_with_status_filter(self, client, auth_token):
        """ステータスでフィルタできる"""
        response = client.get(
            "/api/v1/invoices?status=pending",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        # 全てpendingステータス
        for inv in data["invoices"]:
            assert inv["status"] == "pending"
    
    def test_list_invoices_pagination(self, client, auth_token):
        """ページネーションが動作する"""
        response = client.get(
            "/api/v1/invoices?page=1&page_size=5",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 5
        assert len(data["invoices"]) <= 5
    
    def test_list_invoices_without_auth(self, client):
        """認証なしでは失敗する"""
        response = client.get("/api/v1/invoices")
        assert response.status_code == 401


class TestInvoiceApproveRejectAPI:
    """7C-3/4: 請求書承認・却下APIテスト"""
    
    def _create_test_invoice(self, client, auth_token):
        """テスト用請求書を作成"""
        response = client.post(
            "/api/v1/invoices",
            json={
                "sender_name": "承認テスト社",
                "amount": 30000,
                "due_date": "2024-04-30T00:00:00Z",
                "source": "manual",
                "source_channel": "manual"
            },
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        return response.json()["id"]
    
    def test_approve_invoice_success(self, client, auth_token):
        """請求書承認が成功する"""
        invoice_id = self._create_test_invoice(client, auth_token)
        
        response = client.post(
            f"/api/v1/invoices/{invoice_id}/approve",
            json={"payment_type": "bank_transfer"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approved"
        assert data["approved_at"] is not None
    
    def test_approve_invoice_without_body(self, client, auth_token):
        """リクエストボディなしでも承認できる"""
        invoice_id = self._create_test_invoice(client, auth_token)
        
        response = client.post(
            f"/api/v1/invoices/{invoice_id}/approve",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approved"
    
    def test_approve_invoice_not_found(self, client, auth_token):
        """存在しない請求書は404"""
        response = client.post(
            "/api/v1/invoices/00000000-0000-0000-0000-000000000000/approve",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 404
    
    def test_reject_invoice_success(self, client, auth_token):
        """請求書却下が成功する"""
        invoice_id = self._create_test_invoice(client, auth_token)
        
        response = client.post(
            f"/api/v1/invoices/{invoice_id}/reject",
            json={"reason": "金額が違う"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"
        assert "金額が違う" in data["error_message"]
    
    def test_reject_invoice_without_reason(self, client, auth_token):
        """理由なしでも却下できる"""
        invoice_id = self._create_test_invoice(client, auth_token)
        
        response = client.post(
            f"/api/v1/invoices/{invoice_id}/reject",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"
    
    def test_cannot_approve_rejected_invoice(self, client, auth_token):
        """却下済み請求書は承認できない"""
        invoice_id = self._create_test_invoice(client, auth_token)
        
        # まず却下
        client.post(
            f"/api/v1/invoices/{invoice_id}/reject",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        # 承認を試みる
        response = client.post(
            f"/api/v1/invoices/{invoice_id}/approve",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 400
    
    def test_approve_without_auth(self, client):
        """認証なしでは失敗する"""
        response = client.post("/api/v1/invoices/test-id/approve")
        assert response.status_code == 401


