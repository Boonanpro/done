"""
LINE Messaging API Tools
"""
from typing import Optional
from langchain_core.tools import tool
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    TextMessage,
    PushMessageRequest,
    ReplyMessageRequest,
)
from linebot.v3.exceptions import InvalidSignatureError

from app.config import settings


def get_line_api() -> MessagingApi:
    """LINE Messaging APIクライアントを取得"""
    configuration = Configuration(
        access_token=settings.LINE_CHANNEL_ACCESS_TOKEN
    )
    api_client = ApiClient(configuration)
    return MessagingApi(api_client)


def get_webhook_handler() -> WebhookHandler:
    """Webhookハンドラーを取得"""
    return WebhookHandler(settings.LINE_CHANNEL_SECRET)


@tool
async def send_line_message(
    user_id: str,
    message: str,
) -> str:
    """
    LINEメッセージを送信します。
    
    Args:
        user_id: 送信先のLINEユーザーID
        message: 送信するメッセージ
        
    Returns:
        送信結果のメッセージ
    """
    try:
        if not settings.LINE_CHANNEL_ACCESS_TOKEN:
            return "エラー: LINE Channel Access Tokenが設定されていません。"
        
        line_api = get_line_api()
        
        request = PushMessageRequest(
            to=user_id,
            messages=[TextMessage(text=message)],
        )
        
        line_api.push_message(request)
        
        return f"LINEメッセージを送信しました: {user_id}"
    except Exception as e:
        return f"エラー: LINEメッセージ送信に失敗しました - {str(e)}"


async def reply_line_message(
    reply_token: str,
    message: str,
) -> str:
    """
    LINEメッセージに返信します（Webhook用）
    
    Args:
        reply_token: 返信トークン
        message: 返信メッセージ
        
    Returns:
        送信結果のメッセージ
    """
    try:
        if not settings.LINE_CHANNEL_ACCESS_TOKEN:
            return "エラー: LINE Channel Access Tokenが設定されていません。"
        
        line_api = get_line_api()
        
        request = ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=message)],
        )
        
        line_api.reply_message(request)
        
        return "LINEメッセージに返信しました"
    except Exception as e:
        return f"エラー: LINE返信に失敗しました - {str(e)}"

