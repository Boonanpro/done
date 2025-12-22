"""
Invoice Management API Routes - Phase 7C
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
import logging

from app.models.invoice_schemas import (
    InvoiceCreateRequest,
    InvoiceResponse,
    InvoiceStatus,
)
from app.services.invoice_service import get_invoice_service
from app.api.chat_routes import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.post("", response_model=InvoiceResponse)
async def create_invoice(
    request: InvoiceCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    請求書を作成
    
    - **sender_name**: 発行元名（必須）
    - **amount**: 請求金額（必須、税込み）
    - **due_date**: 支払期日（必須）
    - **invoice_number**: 請求書番号（オプション）
    - **invoice_month**: 請求対象月（オプション、YYYY-MM形式）
    - **bank_info**: 振込先情報（オプション）
    - **source**: ソース（email/chat/manual）
    - **source_channel**: ソースチャンネル
    """
    try:
        service = get_invoice_service()
        
        # bank_infoをdict化
        bank_info_dict = None
        if request.bank_info:
            bank_info_dict = request.bank_info.model_dump(exclude_none=True)
        
        # current_userはTokenDataオブジェクト
        user_id = current_user.user_id if hasattr(current_user, 'user_id') else "default"
        
        invoice = await service.create_invoice(
            sender_name=request.sender_name,
            amount=request.amount,
            due_date=request.due_date,
            source=request.source.value,
            source_channel=request.source_channel,
            user_id=user_id,
            invoice_number=request.invoice_number,
            invoice_month=request.invoice_month,
            bank_info=bank_info_dict,
            source_url=request.source_url,
            raw_content=request.raw_content,
            sender_contact_type=request.sender_contact_type,
            sender_contact_id=request.sender_contact_id,
            pdf_data=request.pdf_data,
            screenshot=request.screenshot,
        )
        
        # レスポンスを構築
        return InvoiceResponse(
            id=invoice["id"],
            user_id=invoice["user_id"],
            sender_name=invoice["sender_name"],
            sender_contact_type=invoice.get("sender_contact_type"),
            sender_contact_id=invoice.get("sender_contact_id"),
            amount=invoice["amount"],
            due_date=invoice["due_date"],
            invoice_number=invoice.get("invoice_number"),
            invoice_month=invoice.get("invoice_month"),
            source=invoice["source"],
            source_channel=invoice["source_channel"],
            source_url=invoice.get("source_url"),
            bank_info=invoice.get("bank_info"),
            status=InvoiceStatus(invoice["status"]),
            scheduled_payment_time=invoice.get("scheduled_payment_time"),
            approved_at=invoice.get("approved_at"),
            approved_by=invoice.get("approved_by"),
            paid_at=invoice.get("paid_at"),
            transaction_id=invoice.get("transaction_id"),
            error_message=invoice.get("error_message"),
            is_duplicate=invoice.get("is_duplicate", False),
            notification_id=invoice.get("notification_id"),
            created_at=invoice["created_at"],
            updated_at=invoice.get("updated_at"),
        )
        
    except Exception as e:
        logger.error(f"Failed to create invoice: {e}")
        raise HTTPException(status_code=500, detail=str(e))

