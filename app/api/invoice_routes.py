"""
Invoice Management API Routes - Phase 7C
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
import logging

from app.models.invoice_schemas import (
    InvoiceCreateRequest,
    InvoiceApproveRequest,
    InvoiceRejectRequest,
    InvoiceResponse,
    InvoiceListResponse,
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


@router.get("", response_model=InvoiceListResponse)
async def list_invoices(
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    current_user: dict = Depends(get_current_user),
):
    """
    請求書一覧を取得
    
    - **status**: ステータスでフィルタ（pending/approved/paid等）
    - **page**: ページ番号（デフォルト: 1）
    - **page_size**: 1ページあたりの件数（デフォルト: 20）
    """
    try:
        service = get_invoice_service()
        user_id = current_user.user_id if hasattr(current_user, 'user_id') else "default"
        
        invoices, total = await service.list_invoices(
            user_id=user_id,
            status=status,
            page=page,
            page_size=page_size,
        )
        
        # レスポンスを構築
        invoice_responses = []
        for inv in invoices:
            invoice_responses.append(InvoiceResponse(
                id=inv["id"],
                user_id=inv["user_id"],
                sender_name=inv["sender_name"],
                sender_contact_type=inv.get("sender_contact_type"),
                sender_contact_id=inv.get("sender_contact_id"),
                amount=inv["amount"],
                due_date=inv["due_date"],
                invoice_number=inv.get("invoice_number"),
                invoice_month=inv.get("invoice_month"),
                source=inv["source"],
                source_channel=inv["source_channel"],
                source_url=inv.get("source_url"),
                bank_info=inv.get("bank_info"),
                status=InvoiceStatus(inv["status"]),
                scheduled_payment_time=inv.get("scheduled_payment_time"),
                approved_at=inv.get("approved_at"),
                approved_by=inv.get("approved_by"),
                paid_at=inv.get("paid_at"),
                transaction_id=inv.get("transaction_id"),
                error_message=inv.get("error_message"),
                is_duplicate=False,
                notification_id=inv.get("notification_id"),
                created_at=inv["created_at"],
                updated_at=inv.get("updated_at"),
            ))
        
        return InvoiceListResponse(
            invoices=invoice_responses,
            total=total,
            page=page,
            page_size=page_size,
        )
        
    except Exception as e:
        logger.error(f"Failed to list invoices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{invoice_id}/approve", response_model=InvoiceResponse)
async def approve_invoice(
    invoice_id: str,
    request: InvoiceApproveRequest = None,
    current_user: dict = Depends(get_current_user),
):
    """
    請求書を承認
    
    - **invoice_id**: 請求書ID
    - **payment_type**: 支払い方法タイプ（bank_transfer/credit_card/convenience）
    - **payment_method_id**: 支払い方法ID（オプション）
    - **scheduled_time_override**: スケジュール上書き（オプション）
    """
    try:
        service = get_invoice_service()
        user_id = current_user.user_id if hasattr(current_user, 'user_id') else "default"
        
        # リクエストボディがない場合はデフォルト値を使用
        payment_type = "bank_transfer"
        payment_method_id = None
        scheduled_time_override = None
        
        if request:
            payment_type = request.payment_type.value if request.payment_type else "bank_transfer"
            payment_method_id = request.payment_method_id
            scheduled_time_override = request.scheduled_time_override
        
        invoice = await service.approve_invoice(
            invoice_id=invoice_id,
            user_id=user_id,
            payment_type=payment_type,
            payment_method_id=payment_method_id,
            scheduled_time_override=scheduled_time_override,
        )
        
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
        
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
            is_duplicate=False,
            notification_id=invoice.get("notification_id"),
            created_at=invoice["created_at"],
            updated_at=invoice.get("updated_at"),
        )
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to approve invoice: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{invoice_id}/reject", response_model=InvoiceResponse)
async def reject_invoice(
    invoice_id: str,
    request: InvoiceRejectRequest = None,
    current_user: dict = Depends(get_current_user),
):
    """
    請求書を却下
    
    - **invoice_id**: 請求書ID
    - **reason**: 却下理由（オプション）
    """
    try:
        service = get_invoice_service()
        user_id = current_user.user_id if hasattr(current_user, 'user_id') else "default"
        
        reason = request.reason if request else None
        
        invoice = await service.reject_invoice(
            invoice_id=invoice_id,
            user_id=user_id,
            reason=reason,
        )
        
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
        
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
            is_duplicate=False,
            notification_id=invoice.get("notification_id"),
            created_at=invoice["created_at"],
            updated_at=invoice.get("updated_at"),
        )
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to reject invoice: {e}")
        raise HTTPException(status_code=500, detail=str(e))

