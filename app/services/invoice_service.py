"""
Invoice Management Service - Phase 7A: 請求書情報抽出
"""
import logging
import hashlib
import json
import re
from typing import Optional, Dict, Any
from datetime import datetime

from app.config import settings
from app.models.invoice_schemas import (
    InvoiceExtractionResult,
    BankInfo,
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


# シングルトンインスタンス
_invoice_extractor: Optional[InvoiceExtractor] = None


def get_invoice_extractor() -> InvoiceExtractor:
    """InvoiceExtractorのインスタンスを取得"""
    global _invoice_extractor
    if _invoice_extractor is None:
        _invoice_extractor = InvoiceExtractor()
    return _invoice_extractor

