"""
Gmail API Routes - Phase 5B: メール受信検知
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.services.gmail_service import get_gmail_service
from app.models.detection_schemas import (
    GmailSetupResponse,
    GmailCallbackRequest,
    GmailCallbackResponse,
    GmailStatusResponse,
    GmailSyncResponse,
    GmailDisconnectResponse,
)

router = APIRouter(prefix="/gmail", tags=["gmail"])

# デフォルトユーザーID（認証未実装のため仮）
DEFAULT_USER_ID = "default-user"


@router.post("/setup", response_model=GmailSetupResponse)
async def gmail_setup(user_id: Optional[str] = None):
    """
    Gmail OAuth2認証を開始
    
    認証URLを返すので、ユーザーにそのURLにアクセスさせてGmail連携を許可してもらう
    """
    uid = user_id or DEFAULT_USER_ID
    
    try:
        gmail_service = get_gmail_service()
        auth_url = gmail_service.get_auth_url(uid)
        
        return GmailSetupResponse(
            auth_url=auth_url,
            message="Please visit this URL to authorize Gmail access",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback")
async def gmail_callback(
    code: str = Query(..., description="Authorization code from Google"),
    state: str = Query(..., description="User ID passed as state"),
):
    """
    Gmail OAuth2コールバック（GETリダイレクト用）
    
    Googleからリダイレクトされてきた時に呼ばれる
    """
    try:
        gmail_service = get_gmail_service()
        success, message, email = await gmail_service.handle_callback(code, state)
        
        if success:
            # 成功時はHTMLレスポンスを返す（ブラウザで表示）
            return {
                "success": True,
                "email": email,
                "message": message,
                "html": f"""
                <html>
                <head><title>Gmail連携完了</title></head>
                <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                    <h1>✅ Gmail連携が完了しました</h1>
                    <p>アカウント: {email}</p>
                    <p>このウィンドウを閉じてください。</p>
                </body>
                </html>
                """
            }
        else:
            raise HTTPException(status_code=400, detail=message)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/callback", response_model=GmailCallbackResponse)
async def gmail_callback_post(
    request: GmailCallbackRequest,
    user_id: Optional[str] = None,
):
    """
    Gmail OAuth2コールバック（POST用）
    
    フロントエンドからコードを送信する場合に使用
    """
    uid = user_id or DEFAULT_USER_ID
    
    try:
        gmail_service = get_gmail_service()
        success, message, email = await gmail_service.handle_callback(request.code, uid)
        
        return GmailCallbackResponse(
            success=success,
            email=email,
            message=message,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status", response_model=GmailStatusResponse)
async def gmail_status(user_id: Optional[str] = None):
    """
    Gmail連携状態を確認
    """
    uid = user_id or DEFAULT_USER_ID
    
    try:
        gmail_service = get_gmail_service()
        status = await gmail_service.get_connection_status(uid)
        
        return GmailStatusResponse(**status)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync", response_model=GmailSyncResponse)
async def gmail_sync(
    user_id: Optional[str] = None,
    max_results: int = Query(50, ge=1, le=100, description="最大取得件数"),
):
    """
    手動でメール同期を実行
    
    新着の未読メールを取得してdetected_messagesに保存
    """
    uid = user_id or DEFAULT_USER_ID
    
    try:
        gmail_service = get_gmail_service()
        new_count, message_ids = await gmail_service.sync_emails(uid, max_results=max_results)
        
        return GmailSyncResponse(
            success=True,
            new_messages=new_count,
            message_ids=message_ids,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/disconnect", response_model=GmailDisconnectResponse)
async def gmail_disconnect(user_id: Optional[str] = None):
    """
    Gmail連携を解除
    """
    uid = user_id or DEFAULT_USER_ID
    
    try:
        gmail_service = get_gmail_service()
        success = await gmail_service.disconnect(uid)
        
        return GmailDisconnectResponse(
            success=success,
            message="Gmail connection disconnected" if success else "No active connection found",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
