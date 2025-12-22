"""
Detection API Routes - Phase 5: メッセージ検知
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from typing import Optional

from app.services.message_detection import get_detection_service
from app.services.attachment_service import get_attachment_service
from app.models.detection_schemas import (
    MessageSource,
    DetectionStatus,
    ContentType,
    DetectedMessageResponse,
    DetectedMessagesListResponse,
    AttachmentResponse,
    AttachmentsListResponse,
)

router = APIRouter(prefix="/detection", tags=["detection"])

# デフォルトユーザーID（認証未実装のため仮）
DEFAULT_USER_ID = "default-user"


# ==================== Detected Messages ====================

@router.get("/messages", response_model=DetectedMessagesListResponse)
async def list_detected_messages(
    user_id: Optional[str] = None,
    source: Optional[MessageSource] = None,
    status: Optional[DetectionStatus] = None,
    content_type: Optional[ContentType] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """
    検知メッセージ一覧を取得
    
    フィルタ:
    - source: done_chat, gmail, line
    - status: pending, processing, processed, failed
    - content_type: invoice, otp, notification, general
    """
    uid = user_id or DEFAULT_USER_ID
    
    try:
        detection_service = get_detection_service()
        messages = await detection_service.get_detected_messages(
            user_id=uid,
            source=source,
            status=status,
            content_type=content_type,
            limit=limit,
            offset=offset,
        )
        total = await detection_service.count_messages(
            user_id=uid,
            source=source,
            status=status,
        )
        
        return DetectedMessagesListResponse(
            messages=[DetectedMessageResponse(**m) for m in messages],
            total=total,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/messages/{message_id}", response_model=DetectedMessageResponse)
async def get_detected_message(message_id: str):
    """
    検知メッセージを取得
    """
    try:
        detection_service = get_detection_service()
        message = await detection_service.get_detected_message(message_id)
        
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        
        return DetectedMessageResponse(**message)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Attachments ====================

@router.get("/messages/{message_id}/attachments", response_model=AttachmentsListResponse)
async def list_message_attachments(message_id: str):
    """
    検知メッセージの添付ファイル一覧を取得
    """
    try:
        attachment_service = get_attachment_service()
        attachments = await attachment_service.get_attachments_for_message(message_id)
        
        return AttachmentsListResponse(
            attachments=[AttachmentResponse(**a) for a in attachments],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/messages/{message_id}/download-attachments", response_model=AttachmentsListResponse)
async def download_message_attachments(
    message_id: str,
    user_id: Optional[str] = None,
):
    """
    Gmailメッセージの添付ファイルをダウンロード・保存
    
    Gmail連携済みの場合、メッセージの添付ファイルをダウンロードしてローカルに保存
    """
    uid = user_id or DEFAULT_USER_ID
    
    try:
        attachment_service = get_attachment_service()
        attachments = await attachment_service.download_gmail_attachments(
            user_id=uid,
            detected_message_id=message_id,
        )
        
        return AttachmentsListResponse(
            attachments=[AttachmentResponse(**a) for a in attachments],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/attachments/{attachment_id}")
async def download_attachment(attachment_id: str):
    """
    添付ファイルをダウンロード
    """
    try:
        attachment_service = get_attachment_service()
        data, filename, mime_type = await attachment_service.get_attachment_data(attachment_id)
        
        return Response(
            content=data,
            media_type=mime_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/attachments/{attachment_id}/info", response_model=AttachmentResponse)
async def get_attachment_info(attachment_id: str):
    """
    添付ファイル情報を取得
    """
    try:
        attachment_service = get_attachment_service()
        attachment = await attachment_service.get_attachment(attachment_id)
        
        if not attachment:
            raise HTTPException(status_code=404, detail="Attachment not found")
        
        return AttachmentResponse(**attachment)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/attachments/{attachment_id}")
async def delete_attachment(attachment_id: str):
    """
    添付ファイルを削除
    """
    try:
        attachment_service = get_attachment_service()
        success = await attachment_service.delete_attachment(attachment_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Attachment not found")
        
        return {"success": True, "message": "Attachment deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


