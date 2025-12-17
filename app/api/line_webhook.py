"""
LINE Webhook Handler
"""
from fastapi import APIRouter, Request, HTTPException, Header
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError
import json

from app.config import settings
from app.tools.line_tool import get_webhook_handler, reply_line_message
from app.agent.agent import AISecretaryAgent

router = APIRouter()


@router.post("/line")
async def line_webhook(
    request: Request,
    x_line_signature: str = Header(None),
):
    """
    LINEからのWebhookを処理
    """
    if not settings.LINE_CHANNEL_SECRET:
        raise HTTPException(status_code=500, detail="LINE Channel Secret not configured")
    
    body = await request.body()
    body_str = body.decode("utf-8")
    
    # 署名の検証
    handler = get_webhook_handler()
    try:
        handler.handle(body_str, x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    # イベントを処理
    events = json.loads(body_str).get("events", [])
    
    for event in events:
        if event["type"] == "message" and event["message"]["type"] == "text":
            user_id = event["source"]["userId"]
            text = event["message"]["text"]
            reply_token = event["replyToken"]
            
            # AIエージェントで処理
            agent = AISecretaryAgent()
            result = await agent.process_wish(
                wish=text,
                user_id=user_id,
            )
            
            # 返信
            response_text = f"{result['message']}\n\n"
            if result["proposed_actions"]:
                response_text += "提案するアクション:\n"
                for i, action in enumerate(result["proposed_actions"], 1):
                    response_text += f"{i}. {action}\n"
            
            if result["requires_confirmation"]:
                response_text += "\n実行してよろしければ「OK」と返信してください。"
            
            await reply_line_message(reply_token, response_text)
    
    return {"status": "ok"}

