"""
Phase 10: Voice Communication API Routes
音声通話関連のAPIエンドポイント
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from app.services.voice_service import get_voice_service
from app.models.voice_schemas import (
    PhoneRuleType, CallDirection, CallStatus,
    VoiceSettingsUpdate, VoiceSettingsResponse,
    PhoneNumberRuleCreate, PhoneNumberRuleResponse, PhoneNumberRuleListResponse,
    VoiceCallResponse, VoiceCallListResponse,
    InboundToggleRequest, InboundToggleResponse,
)

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])

# デフォルトユーザーID（認証実装後は動的に取得）
DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"


# ========================================
# Voice Settings API (10C)
# ========================================

@router.get("/settings", response_model=VoiceSettingsResponse)
async def get_voice_settings():
    """
    音声設定を取得
    
    ユーザーの音声通話設定を取得します。
    設定がない場合はデフォルト設定が作成されます。
    """
    service = get_voice_service()
    settings = await service.get_voice_settings(DEFAULT_USER_ID)
    return settings


@router.patch("/settings", response_model=VoiceSettingsResponse)
async def update_voice_settings(update: VoiceSettingsUpdate):
    """
    音声設定を更新
    
    音声通話の設定を更新します。
    指定したフィールドのみが更新されます。
    """
    service = get_voice_service()
    settings = await service.update_voice_settings(DEFAULT_USER_ID, update)
    return settings


@router.patch("/inbound", response_model=InboundToggleResponse)
async def toggle_inbound(request: InboundToggleRequest):
    """
    受電のオン/オフを切り替え
    
    受電を受けるかどうかを設定します。
    """
    service = get_voice_service()
    inbound_enabled = await service.toggle_inbound(DEFAULT_USER_ID, request.enabled)
    return InboundToggleResponse(success=True, inbound_enabled=inbound_enabled)


# ========================================
# Phone Number Rules API (10D)
# ========================================

@router.get("/rules", response_model=PhoneNumberRuleListResponse)
async def get_phone_rules(
    rule_type: Optional[PhoneRuleType] = Query(default=None, description="ルールタイプでフィルタ")
):
    """
    電話番号ルール一覧を取得
    
    ホワイトリスト/ブラックリストの電話番号ルールを取得します。
    """
    service = get_voice_service()
    rules = await service.get_phone_rules(DEFAULT_USER_ID, rule_type)
    return PhoneNumberRuleListResponse(rules=rules)


@router.post("/rules", response_model=PhoneNumberRuleResponse, status_code=201)
async def add_phone_rule(rule: PhoneNumberRuleCreate):
    """
    電話番号ルールを追加
    
    ホワイトリストまたはブラックリストに電話番号を追加します。
    """
    service = get_voice_service()
    result = await service.add_phone_rule(DEFAULT_USER_ID, rule)
    return result


@router.delete("/rules/{rule_id}")
async def delete_phone_rule(rule_id: str):
    """
    電話番号ルールを削除
    
    指定した電話番号ルールを削除します。
    """
    service = get_voice_service()
    success = await service.delete_phone_rule(DEFAULT_USER_ID, rule_id)
    if not success:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"success": True, "message": "Rule deleted"}


# ========================================
# Voice Calls API (10B)
# ========================================

@router.get("/calls", response_model=VoiceCallListResponse)
async def get_call_history(
    limit: int = Query(default=20, le=100, description="取得件数"),
    direction: Optional[CallDirection] = Query(default=None, description="通話方向でフィルタ"),
    status: Optional[CallStatus] = Query(default=None, description="状態でフィルタ"),
):
    """
    通話履歴を取得
    
    ユーザーの通話履歴を取得します。
    """
    service = get_voice_service()
    calls = await service.get_call_history(
        DEFAULT_USER_ID, limit=limit, direction=direction, status=status
    )
    return VoiceCallListResponse(calls=calls, total=len(calls))


@router.get("/call/{call_id}", response_model=VoiceCallResponse)
async def get_call(call_id: str):
    """
    通話情報を取得
    
    指定した通話の詳細情報を取得します。
    """
    service = get_voice_service()
    call = await service.get_call(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    return call


# ========================================
# Placeholder for future implementation
# ========================================

# POST /api/v1/voice/call - 架電開始 (10B)
# POST /api/v1/voice/call/{id}/end - 通話終了 (10B)
# POST /api/v1/voice/webhook/incoming - 着信Webhook (10C)
# POST /api/v1/voice/webhook/status - 通話状態Webhook (10B)
# WS /api/v1/voice/stream - Media Streams WebSocket (10A)

