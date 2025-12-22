"""
Content Intelligence API Routes - Phase 6
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from typing import Optional
import logging
import time

from app.models.content_schemas import (
    AnalyzeContentRequest,
    AnalyzeContentResponse,
    ExtractTextFromURLRequest,
    ExtractTextFromURLResponse,
    ClassifyContentRequest,
    ClassifyContentResponse,
    BatchAnalyzeRequest,
    BatchAnalyzeResponse,
)
from app.services.content_intelligence import get_content_intelligence_service
from app.services.attachment_service import get_attachment_service
from app.api.chat_routes import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/content", tags=["content-intelligence"])


@router.post("/extract/pdf", response_model=AnalyzeContentResponse)
async def extract_text_from_pdf(
    file: UploadFile = File(...),
    classify: bool = Form(default=True),
    current_user: dict = Depends(get_current_user),
):
    """
    PDFファイルからテキストを抽出
    
    - **file**: PDFファイル
    - **classify**: 分類も行うかどうか（デフォルト: True）
    """
    start_time = time.time()
    
    if not file.content_type == "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    
    try:
        file_data = await file.read()
        service = get_content_intelligence_service()
        
        extraction_result, classification_result = await service.analyze_attachment(
            file_data=file_data,
            mime_type="application/pdf",
            filename=file.filename or "uploaded.pdf",
            classify=classify,
        )
        
        processing_time = int((time.time() - start_time) * 1000)
        
        return AnalyzeContentResponse(
            success=extraction_result.success,
            extraction_result=extraction_result,
            classification_result=classification_result,
            error=extraction_result.error,
            processing_time_ms=processing_time,
        )
        
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract/image", response_model=AnalyzeContentResponse)
async def extract_text_from_image(
    file: UploadFile = File(...),
    language: str = Form(default="jpn+eng"),
    classify: bool = Form(default=True),
    current_user: dict = Depends(get_current_user),
):
    """
    画像ファイルからテキストを抽出（OCR）
    
    - **file**: 画像ファイル（PNG, JPEG, GIF）
    - **language**: OCR言語（デフォルト: jpn+eng）
    - **classify**: 分類も行うかどうか（デフォルト: True）
    """
    start_time = time.time()
    
    allowed_types = ["image/png", "image/jpeg", "image/jpg", "image/gif"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type. Allowed: {allowed_types}"
        )
    
    try:
        file_data = await file.read()
        service = get_content_intelligence_service()
        
        extraction_result = await service.extract_text_from_image(file_data, language)
        
        classification_result = None
        if classify and extraction_result.success and extraction_result.text:
            classification_result = await service.classify_content(extraction_result.text)
        
        processing_time = int((time.time() - start_time) * 1000)
        
        return AnalyzeContentResponse(
            success=extraction_result.success,
            extraction_result=extraction_result,
            classification_result=classification_result,
            error=extraction_result.error,
            processing_time_ms=processing_time,
        )
        
    except Exception as e:
        logger.error(f"Image OCR failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract/url", response_model=ExtractTextFromURLResponse)
async def extract_text_from_url(
    request: ExtractTextFromURLRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    URLにアクセスしてテキストコンテンツを取得
    
    - **url**: 取得するURL
    - **wait_for_selector**: 待機するCSSセレクタ（オプション）
    - **timeout_ms**: タイムアウト（ミリ秒、デフォルト: 30000）
    """
    try:
        service = get_content_intelligence_service()
        
        result = await service.extract_text_from_url(
            url=request.url,
            wait_for_selector=request.wait_for_selector,
            timeout_ms=request.timeout_ms,
        )
        
        return ExtractTextFromURLResponse(
            success=result.success,
            result=result,
            error=result.error,
        )
        
    except Exception as e:
        logger.error(f"URL extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/classify", response_model=ClassifyContentResponse)
async def classify_content(
    request: ClassifyContentRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    テキストをカテゴリ分類
    
    - **text**: 分類するテキスト
    - **subject**: 件名（オプション）
    - **sender**: 送信者（オプション）
    """
    try:
        service = get_content_intelligence_service()
        
        result = await service.classify_content(
            text=request.text,
            subject=request.subject,
            sender=request.sender,
        )
        
        return ClassifyContentResponse(
            success=True,
            result=result,
        )
        
    except Exception as e:
        logger.error(f"Classification failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze/attachment/{attachment_id}", response_model=AnalyzeContentResponse)
async def analyze_attachment(
    attachment_id: str,
    classify: bool = True,
    current_user: dict = Depends(get_current_user),
):
    """
    保存済み添付ファイルを解析
    
    - **attachment_id**: 添付ファイルID
    - **classify**: 分類も行うかどうか（デフォルト: True）
    """
    start_time = time.time()
    
    try:
        attachment_service = get_attachment_service()
        content_service = get_content_intelligence_service()
        
        # 添付ファイルデータを取得
        data, filename, mime_type = await attachment_service.get_attachment_data(attachment_id)
        
        # 解析
        extraction_result, classification_result = await content_service.analyze_attachment(
            file_data=data,
            mime_type=mime_type,
            filename=filename,
            classify=classify,
        )
        
        processing_time = int((time.time() - start_time) * 1000)
        
        return AnalyzeContentResponse(
            success=extraction_result.success,
            extraction_result=extraction_result,
            classification_result=classification_result,
            error=extraction_result.error,
            processing_time_ms=processing_time,
        )
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Attachment analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze/message/{message_id}")
async def analyze_detected_message(
    message_id: str,
    include_attachments: bool = True,
    current_user: dict = Depends(get_current_user),
):
    """
    検知メッセージを解析・分類
    
    - **message_id**: 検知メッセージID
    - **include_attachments**: 添付ファイルも処理するか（デフォルト: True）
    """
    try:
        service = get_content_intelligence_service()
        
        result = await service.process_detected_message(
            message_id=message_id,
            include_attachments=include_attachments,
        )
        
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("error", "Unknown error"))
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Message analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze/batch", response_model=BatchAnalyzeResponse)
async def batch_analyze_messages(
    request: BatchAnalyzeRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    複数の検知メッセージをバッチ解析
    
    - **message_ids**: 解析するメッセージIDのリスト
    """
    service = get_content_intelligence_service()
    
    results = []
    processed = 0
    failed = 0
    
    for message_id in request.message_ids:
        try:
            result = await service.process_detected_message(
                message_id=message_id,
                include_attachments=True,
            )
            results.append(result)
            if result.get("success"):
                processed += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(f"Batch analysis failed for {message_id}: {e}")
            results.append({
                "message_id": message_id,
                "success": False,
                "error": str(e),
            })
            failed += 1
    
    return BatchAnalyzeResponse(
        success=True,
        total=len(request.message_ids),
        processed=processed,
        failed=failed,
        results=results,
    )

