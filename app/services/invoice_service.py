"""
Invoice Management Service - Phase 7A/7B: 請求書情報抽出・スケジュール計算
"""
import logging
import hashlib
import json
import re
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import settings
from app.models.invoice_schemas import (
    InvoiceExtractionResult,
    BankInfo,
    ScheduleCalculationResponse,
)

logger = logging.getLogger(__name__)


class InvoiceExtractor:
    """7A: 請求書情報抽出 - Phase 6の分類結果から詳細情報を抽出"""
    
    EXTRACTION_PROMPT = """あなたは請求書解析AIです。
以下のテキストから請求書情報を抽出してください。

## 入力テキスト
{text}

## 出力形式（JSONのみ）
{{
  "amount": 金額（整数、税込み、円単位）,
  "currency": "JPY",
  "due_date": "YYYY-MM-DD"形式の支払期日,
  "invoice_number": "請求書番号",
  "invoice_month": "YYYY-MM"形式の請求対象月,
  "issuer_name": "発行元の会社名・個人名",
  "issuer_address": "発行元の住所",
  "bank_info": {{
    "bank_name": "銀行名",
    "branch_name": "支店名",
    "branch_code": "支店コード",
    "account_type": "普通 or 当座",
    "account_number": "口座番号",
    "account_holder": "口座名義（カタカナ）"
  }},
  "confidence_score": 0.0-1.0の抽出信頼度
}}

注意事項:
- 金額は税込み金額を抽出してください
- 日付はYYYY-MM-DD形式に変換してください
- 情報が見つからない場合はnullを設定してください
- 金額の「,」は除去して整数にしてください
- bank_infoは振込先情報がある場合のみ設定してください

JSONのみを出力してください。"""

    @staticmethod
    async def extract_from_text(
        text: str,
        existing_data: Optional[Dict[str, Any]] = None,
    ) -> InvoiceExtractionResult:
        """
        テキストから請求書情報を抽出
        
        Args:
            text: 請求書のテキストコンテンツ
            existing_data: Phase 6で既に抽出されたデータ（オプション）
        
        Returns:
            InvoiceExtractionResult
        """
        try:
            from langchain_anthropic import ChatAnthropic
            
            # Phase 6で既に抽出されたデータがある場合は活用
            if existing_data:
                result = InvoiceExtractor._parse_existing_data(existing_data)
                if result.success and result.amount and result.due_date:
                    return result
            
            # AIで抽出
            prompt = InvoiceExtractor.EXTRACTION_PROMPT.format(
                text=text[:15000]  # 最大15KB
            )
            
            llm = ChatAnthropic(
                model="claude-sonnet-4-20250514",
                api_key=settings.ANTHROPIC_API_KEY,
                temperature=0,
                max_tokens=1024,
            )
            
            response = await llm.ainvoke(prompt)
            response_text = response.content
            
            # JSONを抽出
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                json_str = json_match.group(0) if json_match else response_text
            
            data = json.loads(json_str)
            
            return InvoiceExtractor._build_result(data)
            
        except Exception as e:
            logger.error(f"Invoice extraction failed: {e}")
            return InvoiceExtractionResult(
                success=False,
                error=str(e)
            )
    
    @staticmethod
    def _parse_existing_data(data: Dict[str, Any]) -> InvoiceExtractionResult:
        """Phase 6で抽出されたデータをパース"""
        try:
            amount = data.get("amount")
            if isinstance(amount, str):
                amount = int(re.sub(r'[,\s]', '', amount))
            
            due_date = None
            due_date_str = data.get("due_date")
            if due_date_str:
                try:
                    due_date = datetime.fromisoformat(due_date_str.replace("Z", "+00:00"))
                except ValueError:
                    # 日付形式を解析
                    for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"]:
                        try:
                            due_date = datetime.strptime(due_date_str, fmt)
                            break
                        except ValueError:
                            continue
            
            bank_info = None
            if data.get("bank_info"):
                bank_info = BankInfo(**data["bank_info"])
            
            return InvoiceExtractionResult(
                success=True,
                amount=amount,
                currency=data.get("currency", "JPY"),
                due_date=due_date,
                invoice_number=data.get("invoice_number"),
                invoice_month=data.get("invoice_month"),
                issuer_name=data.get("issuer_name"),
                issuer_address=data.get("issuer_address"),
                bank_info=bank_info,
                raw_extracted_data=data,
                confidence_score=data.get("confidence_score", 0.8),
            )
        except Exception as e:
            logger.error(f"Failed to parse existing data: {e}")
            return InvoiceExtractionResult(
                success=False,
                error=f"Failed to parse existing data: {e}"
            )
    
    @staticmethod
    def _build_result(data: Dict[str, Any]) -> InvoiceExtractionResult:
        """AI応答からInvoiceExtractionResultを構築"""
        try:
            amount = data.get("amount")
            if isinstance(amount, str):
                amount = int(re.sub(r'[,\s]', '', amount))
            
            due_date = None
            due_date_str = data.get("due_date")
            if due_date_str:
                try:
                    due_date = datetime.fromisoformat(due_date_str)
                except ValueError:
                    for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"]:
                        try:
                            due_date = datetime.strptime(due_date_str, fmt)
                            break
                        except ValueError:
                            continue
            
            bank_info = None
            bank_data = data.get("bank_info")
            if bank_data and isinstance(bank_data, dict):
                # nullでない値のみを含める
                filtered_bank = {k: v for k, v in bank_data.items() if v is not None}
                if filtered_bank.get("bank_name"):
                    bank_info = BankInfo(**filtered_bank)
            
            return InvoiceExtractionResult(
                success=True,
                amount=amount,
                currency=data.get("currency", "JPY"),
                due_date=due_date,
                invoice_number=data.get("invoice_number"),
                invoice_month=data.get("invoice_month"),
                issuer_name=data.get("issuer_name"),
                issuer_address=data.get("issuer_address"),
                bank_info=bank_info,
                raw_extracted_data=data,
                confidence_score=data.get("confidence_score", 0.8),
            )
        except Exception as e:
            logger.error(f"Failed to build result: {e}")
            return InvoiceExtractionResult(
                success=False,
                error=str(e)
            )


class ScheduleCalculator:
    """7B: スケジュール計算 - 支払日時を算出"""
    
    # デフォルト支払い時刻（JST 18:00）
    DEFAULT_PAYMENT_HOUR = 18
    JST = ZoneInfo("Asia/Tokyo")
    
    @staticmethod
    def calculate_payment_schedule(
        due_date: datetime,
        invoice_month: Optional[str] = None,
        consider_holidays: bool = False,
    ) -> ScheduleCalculationResponse:
        """
        支払い日時を計算
        
        ロジック:
        1. 期日ベース: 期日の前日18:00（JST）
        2. 翌月末ベース: invoice_monthが指定された場合、その翌月末の前日18:00
        
        Args:
            due_date: 支払期日
            invoice_month: 請求対象月（YYYY-MM形式、オプション）
            consider_holidays: 休日を考慮するか（オプション）
        
        Returns:
            ScheduleCalculationResponse
        """
        # タイムゾーンを確認・設定
        if due_date.tzinfo is None:
            due_date = due_date.replace(tzinfo=ScheduleCalculator.JST)
        
        # 期日の前日18:00を計算
        payment_date = due_date - timedelta(days=1)
        payment_time = payment_date.replace(
            hour=ScheduleCalculator.DEFAULT_PAYMENT_HOUR,
            minute=0,
            second=0,
            microsecond=0
        )
        
        # 休日考慮（オプション）
        is_holiday_adjusted = False
        if consider_holidays:
            payment_time, is_holiday_adjusted = ScheduleCalculator._adjust_for_holidays(payment_time)
        
        # 支払いまでの日数を計算
        now = datetime.now(ScheduleCalculator.JST)
        days_until = (payment_time.date() - now.date()).days
        
        return ScheduleCalculationResponse(
            scheduled_payment_time=payment_time,
            due_date=due_date,
            days_until_payment=max(0, days_until),
            is_holiday_adjusted=is_holiday_adjusted
        )
    
    @staticmethod
    def calculate_from_invoice_month(
        invoice_month: str,
        consider_holidays: bool = False,
    ) -> ScheduleCalculationResponse:
        """
        請求対象月から支払い日時を計算（翌月末の前日18:00）
        
        Args:
            invoice_month: 請求対象月（YYYY-MM形式）
            consider_holidays: 休日を考慮するか
        
        Returns:
            ScheduleCalculationResponse
        """
        # YYYY-MM形式をパース
        year, month = map(int, invoice_month.split("-"))
        
        # 翌月を計算
        if month == 12:
            next_year = year + 1
            next_month = 1
        else:
            next_year = year
            next_month = month + 1
        
        # 翌月末日を計算
        if next_month == 12:
            last_day = 31
        elif next_month in [4, 6, 9, 11]:
            last_day = 30
        elif next_month == 2:
            # うるう年判定
            if (next_year % 4 == 0 and next_year % 100 != 0) or (next_year % 400 == 0):
                last_day = 29
            else:
                last_day = 28
        else:
            last_day = 31
        
        due_date = datetime(next_year, next_month, last_day, tzinfo=ScheduleCalculator.JST)
        
        return ScheduleCalculator.calculate_payment_schedule(
            due_date=due_date,
            invoice_month=invoice_month,
            consider_holidays=consider_holidays
        )
    
    @staticmethod
    def _adjust_for_holidays(payment_time: datetime) -> tuple[datetime, bool]:
        """
        休日の場合は前営業日にシフト
        
        Args:
            payment_time: 支払い予定日時
        
        Returns:
            (調整後の日時, 調整されたかどうか)
        """
        adjusted = False
        
        # 土日チェック
        while payment_time.weekday() >= 5:  # 5=土曜, 6=日曜
            payment_time = payment_time - timedelta(days=1)
            adjusted = True
        
        # 祝日チェック（jpholidayがインストールされている場合）
        try:
            import jpholiday
            while jpholiday.is_holiday(payment_time.date()):
                payment_time = payment_time - timedelta(days=1)
                adjusted = True
                # 土日に戻った場合は再度チェック
                while payment_time.weekday() >= 5:
                    payment_time = payment_time - timedelta(days=1)
        except ImportError:
            # jpholidayがない場合は土日のみ考慮
            pass
        
        return payment_time, adjusted
    
    @staticmethod
    def is_payment_due(scheduled_time: datetime) -> bool:
        """
        支払い時刻が到来しているかチェック
        
        Args:
            scheduled_time: スケジュールされた支払い日時
        
        Returns:
            True if 支払い時刻が到来している
        """
        now = datetime.now(ScheduleCalculator.JST)
        if scheduled_time.tzinfo is None:
            scheduled_time = scheduled_time.replace(tzinfo=ScheduleCalculator.JST)
        return now >= scheduled_time


# シングルトンインスタンス
_invoice_extractor: Optional[InvoiceExtractor] = None
_schedule_calculator: Optional[ScheduleCalculator] = None


def get_invoice_extractor() -> InvoiceExtractor:
    """InvoiceExtractorのインスタンスを取得"""
    global _invoice_extractor
    if _invoice_extractor is None:
        _invoice_extractor = InvoiceExtractor()
    return _invoice_extractor


def get_schedule_calculator() -> ScheduleCalculator:
    """ScheduleCalculatorのインスタンスを取得"""
    global _schedule_calculator
    if _schedule_calculator is None:
        _schedule_calculator = ScheduleCalculator()
    return _schedule_calculator


class InvoiceService:
    """7C: 請求書管理サービス - DB操作"""
    
    def __init__(self):
        from app.services.supabase_client import get_supabase_client
        supabase_client = get_supabase_client()
        self.db = supabase_client.client  # Supabase Client インスタンス
    
    def _generate_duplicate_hash(
        self,
        sender_name: str,
        amount: int,
        due_date: datetime
    ) -> str:
        """重複チェック用ハッシュを生成"""
        hash_input = f"{sender_name}|{amount}|{due_date.strftime('%Y-%m-%d')}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:32]
    
    async def check_duplicate(
        self,
        sender_name: str,
        amount: int,
        due_date: datetime,
        days_back: int = 30
    ) -> tuple[bool, Optional[str]]:
        """
        重複チェック
        
        Returns:
            (is_duplicate, duplicate_invoice_id)
        """
        duplicate_hash = self._generate_duplicate_hash(sender_name, amount, due_date)
        
        # 過去N日以内の同じハッシュを検索
        from datetime import timedelta
        check_from = datetime.now() - timedelta(days=days_back)
        
        result = self.db.table("invoices").select("id").eq(
            "duplicate_check_hash", duplicate_hash
        ).gte("created_at", check_from.isoformat()).execute()
        
        if result.data and len(result.data) > 0:
            return True, result.data[0]["id"]
        
        return False, None
    
    async def create_invoice(
        self,
        sender_name: str,
        amount: int,
        due_date: datetime,
        source: str,
        source_channel: str,
        user_id: str = "default",
        invoice_number: Optional[str] = None,
        invoice_month: Optional[str] = None,
        bank_info: Optional[Dict[str, Any]] = None,
        source_url: Optional[str] = None,
        raw_content: Optional[str] = None,
        sender_contact_type: Optional[str] = None,
        sender_contact_id: Optional[str] = None,
        pdf_data: Optional[str] = None,
        screenshot: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        請求書を作成
        
        Returns:
            作成された請求書データ
        """
        # 重複チェック
        is_duplicate, duplicate_id = await self.check_duplicate(
            sender_name, amount, due_date
        )
        
        # 重複ハッシュを生成
        duplicate_hash = self._generate_duplicate_hash(sender_name, amount, due_date)
        
        # 支払いスケジュールを計算
        schedule = ScheduleCalculator.calculate_payment_schedule(due_date)
        
        # データを構築
        invoice_data = {
            "user_id": user_id,
            "sender_name": sender_name,
            "amount": amount,
            "due_date": due_date.isoformat(),
            "source": source,
            "source_channel": source_channel,
            "status": "pending",
            "duplicate_check_hash": duplicate_hash,
            "scheduled_payment_time": schedule.scheduled_payment_time.isoformat(),
        }
        
        # オプションフィールド
        if invoice_number:
            invoice_data["invoice_number"] = invoice_number
        if invoice_month:
            invoice_data["invoice_month"] = invoice_month
        if bank_info:
            invoice_data["bank_info"] = bank_info
        if source_url:
            invoice_data["source_url"] = source_url
        if raw_content:
            invoice_data["raw_content"] = raw_content
        if sender_contact_type:
            invoice_data["sender_contact_type"] = sender_contact_type
        if sender_contact_id:
            invoice_data["sender_contact_id"] = sender_contact_id
        if pdf_data:
            invoice_data["pdf_data"] = pdf_data
        if screenshot:
            invoice_data["screenshot"] = screenshot
        
        # DBに保存
        result = self.db.table("invoices").insert(invoice_data).execute()
        
        if not result.data or len(result.data) == 0:
            raise Exception("Failed to create invoice")
        
        created = result.data[0]
        created["is_duplicate"] = is_duplicate
        if is_duplicate:
            created["duplicate_of"] = duplicate_id
        
        return created
    
    async def get_invoice(self, invoice_id: str) -> Optional[Dict[str, Any]]:
        """請求書を取得"""
        result = self.db.table("invoices").select("*").eq(
            "id", invoice_id
        ).execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    
    async def list_invoices(
        self,
        user_id: str = "default",
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Dict[str, Any]], int]:
        """
        請求書一覧を取得
        
        Returns:
            (invoices, total_count)
        """
        query = self.db.table("invoices").select("*", count="exact")
        
        # フィルタ
        query = query.eq("user_id", user_id)
        if status:
            query = query.eq("status", status)
        
        # ソート・ページネーション
        offset = (page - 1) * page_size
        query = query.order("created_at", desc=True).range(offset, offset + page_size - 1)
        
        result = query.execute()
        
        total = result.count if hasattr(result, 'count') and result.count else len(result.data or [])
        
        return result.data or [], total
    
    async def approve_invoice(
        self,
        invoice_id: str,
        user_id: str,
        payment_type: str = "bank_transfer",
        payment_method_id: Optional[str] = None,
        scheduled_time_override: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        請求書を承認
        
        Args:
            invoice_id: 請求書ID
            user_id: 承認者ID
            payment_type: 支払い方法タイプ
            payment_method_id: 支払い方法ID（オプション）
            scheduled_time_override: スケジュール上書き（オプション）
        
        Returns:
            更新された請求書データ
        """
        # 請求書を取得
        invoice = await self.get_invoice(invoice_id)
        if not invoice:
            return None
        
        # 既にapproved以降なら何もしない
        if invoice["status"] not in ["pending"]:
            raise ValueError(f"Cannot approve invoice with status: {invoice['status']}")
        
        # 更新データを構築
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        updates = {
            "status": "approved",
            "approved_at": now.isoformat(),
            "approved_by": user_id,
            "selected_payment_type": payment_type,
            "updated_at": now.isoformat(),
        }
        
        if payment_method_id:
            updates["selected_payment_method_id"] = payment_method_id
        
        if scheduled_time_override:
            updates["scheduled_payment_time"] = scheduled_time_override.isoformat()
        
        # DBを更新
        result = self.db.table("invoices").update(updates).eq("id", invoice_id).execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    
    async def reject_invoice(
        self,
        invoice_id: str,
        user_id: str,
        reason: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        請求書を却下
        
        Args:
            invoice_id: 請求書ID
            user_id: 却下者ID
            reason: 却下理由（オプション）
        
        Returns:
            更新された請求書データ
        """
        # 請求書を取得
        invoice = await self.get_invoice(invoice_id)
        if not invoice:
            return None
        
        # 既にrejected/paid以降なら何もしない
        if invoice["status"] not in ["pending", "approved"]:
            raise ValueError(f"Cannot reject invoice with status: {invoice['status']}")
        
        # 更新データを構築
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        updates = {
            "status": "rejected",
            "updated_at": now.isoformat(),
        }
        
        if reason:
            updates["error_message"] = f"Rejected: {reason}"
        
        # DBを更新
        result = self.db.table("invoices").update(updates).eq("id", invoice_id).execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None


# シングルトンインスタンス
_invoice_service: Optional[InvoiceService] = None


def get_invoice_service() -> InvoiceService:
    """InvoiceServiceのインスタンスを取得"""
    global _invoice_service
    if _invoice_service is None:
        _invoice_service = InvoiceService()
    return _invoice_service


