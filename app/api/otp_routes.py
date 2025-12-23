"""
OTP API Routes - Phase 9: OTP Automation
"""
from fastapi import APIRouter, HTTPException, Query, Header, Form, Request
from fastapi.responses import Response
from typing import Optional

from app.services.otp_service import get_otp_service
from app.models.otp_schemas import (
    OTPExtractionRequest,
    OTPExtractionResponse,
    OTPLatestResponse,
    OTPMarkUsedResponse,
    OTPHistoryResponse,
    SMSStatusResponse,
)

router = APIRouter(prefix="/otp", tags=["OTP"])

# デフォルトユーザーID（開発用）
DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"


def get_user_id(x_user_id: Optional[str] = Header(None)) -> str:
    """ユーザーIDを取得"""
    return x_user_id or DEFAULT_USER_ID


# ==================== Email OTP ====================

@router.post("/extract/email", response_model=OTPExtractionResponse)
async def extract_otp_from_email(
    request: OTPExtractionRequest,
    x_user_id: Optional[str] = Header(None),
):
    """
    メールからOTPを抽出
    
    Gmailから最新のメールを取得し、OTPを抽出します。
    """
    user_id = get_user_id(x_user_id)
    otp_service = get_otp_service()
    
    try:
        otp_result = await otp_service.extract_otp_from_email(
            user_id=user_id,
            service=request.service,
            max_age_minutes=request.max_age_minutes,
            sender_filter=request.sender_filter,
        )
        
        if otp_result:
            return OTPExtractionResponse(
                success=True,
                otp=otp_result,
            )
        else:
            return OTPExtractionResponse(
                success=False,
                message="No OTP found in recent emails",
            )
    except ValueError as e:
        return OTPExtractionResponse(
            success=False,
            message=str(e),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/latest", response_model=OTPLatestResponse)
async def get_latest_otp(
    service: Optional[str] = Query(None, description="対象サービス"),
    source: Optional[str] = Query(None, description="ソース (email/sms)"),
    x_user_id: Optional[str] = Header(None),
):
    """
    最新のOTPを取得
    
    未使用かつ有効期限内の最新OTPを返します。
    """
    user_id = get_user_id(x_user_id)
    otp_service = get_otp_service()
    
    otp_result = await otp_service.get_latest_otp(
        user_id=user_id,
        service=service,
        source=source,
    )
    
    return OTPLatestResponse(otp=otp_result)


@router.post("/{otp_id}/mark-used", response_model=OTPMarkUsedResponse)
async def mark_otp_used(
    otp_id: str,
    x_user_id: Optional[str] = Header(None),
):
    """
    OTPを使用済みにマーク
    """
    otp_service = get_otp_service()
    
    success = await otp_service.mark_otp_used(otp_id)
    
    if success:
        return OTPMarkUsedResponse(
            success=True,
            message="OTP marked as used",
        )
    else:
        raise HTTPException(status_code=404, detail="OTP not found")


@router.get("/history", response_model=OTPHistoryResponse)
async def get_otp_history(
    limit: int = Query(20, ge=1, le=100),
    service: Optional[str] = Query(None, description="サービスでフィルタ"),
    x_user_id: Optional[str] = Header(None),
):
    """
    OTP抽出履歴を取得
    """
    user_id = get_user_id(x_user_id)
    otp_service = get_otp_service()
    
    extractions, total = await otp_service.get_otp_history(
        user_id=user_id,
        limit=limit,
        service=service,
    )
    
    return OTPHistoryResponse(
        extractions=extractions,
        total=total,
    )


# ==================== SMS OTP ====================

@router.get("/sms/status", response_model=SMSStatusResponse)
async def get_sms_status(
    x_user_id: Optional[str] = Header(None),
):
    """
    SMS受信設定状態を確認
    """
    user_id = get_user_id(x_user_id)
    otp_service = get_otp_service()
    
    status = await otp_service.get_sms_status(user_id)
    
    return SMSStatusResponse(**status)


@router.post("/sms/webhook")
async def sms_webhook(request: Request):
    """
    Twilio SMS受信Webhook
    
    TwilioからSMSを受信した際に呼び出されます。
    リクエストはapplication/x-www-form-urlencoded形式です。
    """
    otp_service = get_otp_service()
    
    try:
        # フォームデータを取得
        form_data = await request.form()
        
        from_number = form_data.get("From", "")
        body = form_data.get("Body", "")
        message_sid = form_data.get("MessageSid", "")
        
        if body:
            await otp_service.save_sms_otp(
                from_number=from_number,
                body=body,
                message_sid=message_sid,
            )
        
        # TwiML空レスポンス
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type="application/xml",
        )
    except Exception as e:
        # エラーでもTwiMLを返す
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type="application/xml",
        )


@router.post("/extract/sms", response_model=OTPExtractionResponse)
async def extract_otp_from_sms(
    request: OTPExtractionRequest,
    x_user_id: Optional[str] = Header(None),
):
    """
    SMSからOTPを抽出
    
    受信済みSMSから最新のOTPを取得します。
    """
    user_id = get_user_id(x_user_id)
    otp_service = get_otp_service()
    
    otp_result = await otp_service.extract_otp_from_sms(
        user_id=user_id,
        service=request.service,
        max_age_minutes=request.max_age_minutes,
    )
    
    if otp_result:
        return OTPExtractionResponse(
            success=True,
            otp=otp_result,
        )
    else:
        return OTPExtractionResponse(
            success=False,
            message="No OTP found in recent SMS messages",
        )

