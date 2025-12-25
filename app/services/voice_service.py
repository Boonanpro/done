"""
Phase 10: Voice Communication Service
音声通話サービス（ElevenLabs + Claude統合）
"""
import logging
from typing import Optional, List
from datetime import datetime
import uuid

from app.config import settings
from app.services.supabase_client import get_supabase_client
from app.models.voice_schemas import (
    CallDirection, CallStatus, CallPurpose, PhoneRuleType, MessageRole,
    VoiceCallCreate, VoiceCallResponse,
    PhoneNumberRuleCreate, PhoneNumberRuleResponse,
    VoiceSettingsUpdate, VoiceSettingsResponse,
    VoiceCallMessageResponse,
)

logger = logging.getLogger(__name__)


class VoiceService:
    """音声通話サービス（ElevenLabs + Claude統合）"""
    
    def __init__(self):
        self.supabase = get_supabase_client()
        
        # ElevenLabs設定（環境変数から取得）
        self.elevenlabs_api_key = getattr(settings, 'ELEVENLABS_API_KEY', None)
        self.elevenlabs_voice_id = getattr(settings, 'ELEVENLABS_VOICE_ID', None)
        self.elevenlabs_model_id = getattr(settings, 'ELEVENLABS_MODEL_ID', 'eleven_turbo_v2_5')
        
        # Twilio設定（環境変数から取得）
        self.twilio_account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', None)
        self.twilio_auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', None)
        self.twilio_phone_number = getattr(settings, 'TWILIO_PHONE_NUMBER', None)
    
    # ========================================
    # Voice Settings (10C/10D)
    # ========================================
    
    async def get_voice_settings(self, user_id: str) -> Optional[VoiceSettingsResponse]:
        """
        ユーザーの音声設定を取得
        設定がない場合はデフォルト設定を作成して返す
        """
        try:
            result = self.supabase.client.table("voice_settings").select("*").eq(
                "user_id", user_id
            ).execute()
            
            if result.data and len(result.data) > 0:
                data = result.data[0]
                return VoiceSettingsResponse(
                    id=str(data["id"]),
                    user_id=str(data["user_id"]),
                    inbound_enabled=data.get("inbound_enabled", False),
                    default_greeting=data.get("default_greeting"),
                    auto_answer_whitelist=data.get("auto_answer_whitelist", False),
                    record_calls=data.get("record_calls", False),
                    notify_via_chat=data.get("notify_via_chat", True),
                    elevenlabs_voice_id=data.get("elevenlabs_voice_id"),
                    created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
                    updated_at=datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00")),
                )
            
            # 設定がない場合はデフォルト設定を作成
            return await self._create_default_voice_settings(user_id)
            
        except Exception as e:
            logger.error(f"Failed to get voice settings: {e}")
            raise
    
    async def _create_default_voice_settings(self, user_id: str) -> VoiceSettingsResponse:
        """デフォルトの音声設定を作成"""
        now = datetime.utcnow().isoformat()
        
        insert_data = {
            "user_id": user_id,
            "inbound_enabled": False,
            "default_greeting": "お電話ありがとうございます。AIアシスタントがご用件をお伺いします。",
            "auto_answer_whitelist": False,
            "record_calls": False,
            "notify_via_chat": True,
            "created_at": now,
            "updated_at": now,
        }
        
        result = self.supabase.client.table("voice_settings").insert(insert_data).execute()
        
        if result.data and len(result.data) > 0:
            data = result.data[0]
            return VoiceSettingsResponse(
                id=str(data["id"]),
                user_id=str(data["user_id"]),
                inbound_enabled=data.get("inbound_enabled", False),
                default_greeting=data.get("default_greeting"),
                auto_answer_whitelist=data.get("auto_answer_whitelist", False),
                record_calls=data.get("record_calls", False),
                notify_via_chat=data.get("notify_via_chat", True),
                elevenlabs_voice_id=data.get("elevenlabs_voice_id"),
                created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
                updated_at=datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00")),
            )
        
        raise Exception("Failed to create default voice settings")
    
    async def update_voice_settings(
        self, user_id: str, update: VoiceSettingsUpdate
    ) -> VoiceSettingsResponse:
        """音声設定を更新"""
        try:
            # まず既存の設定を取得（なければ作成される）
            await self.get_voice_settings(user_id)
            
            # 更新データを構築（Noneでない値のみ）
            update_data = {}
            if update.inbound_enabled is not None:
                update_data["inbound_enabled"] = update.inbound_enabled
            if update.default_greeting is not None:
                update_data["default_greeting"] = update.default_greeting
            if update.auto_answer_whitelist is not None:
                update_data["auto_answer_whitelist"] = update.auto_answer_whitelist
            if update.record_calls is not None:
                update_data["record_calls"] = update.record_calls
            if update.notify_via_chat is not None:
                update_data["notify_via_chat"] = update.notify_via_chat
            if update.elevenlabs_voice_id is not None:
                update_data["elevenlabs_voice_id"] = update.elevenlabs_voice_id
            
            if update_data:
                update_data["updated_at"] = datetime.utcnow().isoformat()
                
                self.supabase.client.table("voice_settings").update(update_data).eq(
                    "user_id", user_id
                ).execute()
            
            # 更新後の設定を取得して返す
            return await self.get_voice_settings(user_id)
            
        except Exception as e:
            logger.error(f"Failed to update voice settings: {e}")
            raise
    
    async def toggle_inbound(self, user_id: str, enabled: bool) -> bool:
        """受電のオン/オフを切り替え"""
        update = VoiceSettingsUpdate(inbound_enabled=enabled)
        result = await self.update_voice_settings(user_id, update)
        return result.inbound_enabled
    
    # ========================================
    # Phone Number Rules (10D)
    # ========================================
    
    async def get_phone_rules(
        self, user_id: str, rule_type: Optional[PhoneRuleType] = None
    ) -> List[PhoneNumberRuleResponse]:
        """電話番号ルール一覧を取得"""
        try:
            query = self.supabase.client.table("phone_number_rules").select("*").eq(
                "user_id", user_id
            )
            
            if rule_type:
                query = query.eq("rule_type", rule_type.value)
            
            result = query.order("created_at", desc=True).execute()
            
            rules = []
            for data in result.data or []:
                rules.append(PhoneNumberRuleResponse(
                    id=str(data["id"]),
                    phone_number=data["phone_number"],
                    rule_type=PhoneRuleType(data["rule_type"]),
                    label=data.get("label"),
                    notes=data.get("notes"),
                    created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
                ))
            
            return rules
            
        except Exception as e:
            logger.error(f"Failed to get phone rules: {e}")
            raise
    
    async def add_phone_rule(
        self, user_id: str, rule: PhoneNumberRuleCreate
    ) -> PhoneNumberRuleResponse:
        """電話番号ルールを追加"""
        try:
            insert_data = {
                "user_id": user_id,
                "phone_number": rule.phone_number,
                "rule_type": rule.rule_type.value,
                "label": rule.label,
                "notes": rule.notes,
                "created_at": datetime.utcnow().isoformat(),
            }
            
            result = self.supabase.client.table("phone_number_rules").insert(insert_data).execute()
            
            if result.data and len(result.data) > 0:
                data = result.data[0]
                return PhoneNumberRuleResponse(
                    id=str(data["id"]),
                    phone_number=data["phone_number"],
                    rule_type=PhoneRuleType(data["rule_type"]),
                    label=data.get("label"),
                    notes=data.get("notes"),
                    created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
                )
            
            raise Exception("Failed to add phone rule")
            
        except Exception as e:
            logger.error(f"Failed to add phone rule: {e}")
            raise
    
    async def delete_phone_rule(self, user_id: str, rule_id: str) -> bool:
        """電話番号ルールを削除"""
        try:
            self.supabase.client.table("phone_number_rules").delete().eq(
                "id", rule_id
            ).eq("user_id", user_id).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to delete phone rule: {e}")
            raise
    
    async def check_phone_rule(
        self, user_id: str, phone_number: str
    ) -> Optional[PhoneNumberRuleResponse]:
        """電話番号のルールを確認"""
        try:
            result = self.supabase.client.table("phone_number_rules").select("*").eq(
                "user_id", user_id
            ).eq("phone_number", phone_number).execute()
            
            if result.data and len(result.data) > 0:
                data = result.data[0]
                return PhoneNumberRuleResponse(
                    id=str(data["id"]),
                    phone_number=data["phone_number"],
                    rule_type=PhoneRuleType(data["rule_type"]),
                    label=data.get("label"),
                    notes=data.get("notes"),
                    created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to check phone rule: {e}")
            raise
    
    # ========================================
    # Voice Calls (10B)
    # ========================================
    
    async def get_call_history(
        self,
        user_id: str,
        limit: int = 20,
        direction: Optional[CallDirection] = None,
        status: Optional[CallStatus] = None,
    ) -> List[VoiceCallResponse]:
        """通話履歴を取得"""
        try:
            query = self.supabase.client.table("voice_calls").select("*").eq(
                "user_id", user_id
            )
            
            if direction:
                query = query.eq("direction", direction.value)
            if status:
                query = query.eq("status", status.value)
            
            result = query.order("started_at", desc=True).limit(limit).execute()
            
            calls = []
            for data in result.data or []:
                calls.append(self._parse_voice_call(data))
            
            return calls
            
        except Exception as e:
            logger.error(f"Failed to get call history: {e}")
            raise
    
    async def get_call(self, call_id: str) -> Optional[VoiceCallResponse]:
        """通話情報を取得"""
        try:
            result = self.supabase.client.table("voice_calls").select("*").eq(
                "id", call_id
            ).execute()
            
            if result.data and len(result.data) > 0:
                return self._parse_voice_call(result.data[0])
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get call: {e}")
            raise
    
    async def get_call_by_sid(self, call_sid: str) -> Optional[VoiceCallResponse]:
        """Call SIDで通話情報を取得"""
        try:
            result = self.supabase.client.table("voice_calls").select("*").eq(
                "call_sid", call_sid
            ).execute()
            
            if result.data and len(result.data) > 0:
                return self._parse_voice_call(result.data[0])
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get call by SID: {e}")
            raise
    
    async def create_call_record(
        self,
        user_id: str,
        call_sid: str,
        direction: CallDirection,
        from_number: str,
        to_number: str,
        purpose: Optional[CallPurpose] = None,
        task_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> VoiceCallResponse:
        """通話レコードを作成"""
        try:
            now = datetime.utcnow().isoformat()
            
            insert_data = {
                "user_id": user_id,
                "call_sid": call_sid,
                "direction": direction.value,
                "status": CallStatus.INITIATED.value,
                "from_number": from_number,
                "to_number": to_number,
                "purpose": purpose.value if purpose else None,
                "task_id": task_id,
                "metadata": metadata or {},
                "started_at": now,
                "created_at": now,
                "updated_at": now,
            }
            
            result = self.supabase.client.table("voice_calls").insert(insert_data).execute()
            
            if result.data and len(result.data) > 0:
                return self._parse_voice_call(result.data[0])
            
            raise Exception("Failed to create call record")
            
        except Exception as e:
            logger.error(f"Failed to create call record: {e}")
            raise
    
    async def update_call_status(
        self,
        call_id: str,
        status: CallStatus,
        duration_seconds: Optional[int] = None,
        transcription: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> Optional[VoiceCallResponse]:
        """通話状態を更新"""
        try:
            update_data = {
                "status": status.value,
                "updated_at": datetime.utcnow().isoformat(),
            }
            
            if status == CallStatus.IN_PROGRESS:
                update_data["answered_at"] = datetime.utcnow().isoformat()
            elif status in [CallStatus.COMPLETED, CallStatus.FAILED, CallStatus.CANCELED]:
                update_data["ended_at"] = datetime.utcnow().isoformat()
            
            if duration_seconds is not None:
                update_data["duration_seconds"] = duration_seconds
            if transcription is not None:
                update_data["transcription"] = transcription
            if summary is not None:
                update_data["summary"] = summary
            
            self.supabase.client.table("voice_calls").update(update_data).eq(
                "id", call_id
            ).execute()
            
            return await self.get_call(call_id)
            
        except Exception as e:
            logger.error(f"Failed to update call status: {e}")
            raise
    
    def _parse_voice_call(self, data: dict) -> VoiceCallResponse:
        """DB結果をVoiceCallResponseに変換"""
        return VoiceCallResponse(
            id=str(data["id"]),
            call_sid=data["call_sid"],
            direction=CallDirection(data["direction"]),
            status=CallStatus(data["status"]),
            from_number=data["from_number"],
            to_number=data["to_number"],
            started_at=datetime.fromisoformat(data["started_at"].replace("Z", "+00:00")),
            answered_at=datetime.fromisoformat(data["answered_at"].replace("Z", "+00:00")) if data.get("answered_at") else None,
            ended_at=datetime.fromisoformat(data["ended_at"].replace("Z", "+00:00")) if data.get("ended_at") else None,
            duration_seconds=data.get("duration_seconds"),
            transcription=data.get("transcription"),
            summary=data.get("summary"),
            purpose=CallPurpose(data["purpose"]) if data.get("purpose") else None,
            task_id=str(data["task_id"]) if data.get("task_id") else None,
        )
    
    # ========================================
    # Call Messages
    # ========================================
    
    async def add_call_message(
        self, call_id: str, role: MessageRole, content: str
    ) -> VoiceCallMessageResponse:
        """通話メッセージを追加"""
        try:
            now = datetime.utcnow().isoformat()
            
            insert_data = {
                "call_id": call_id,
                "role": role.value,
                "content": content,
                "timestamp": now,
            }
            
            result = self.supabase.client.table("voice_call_messages").insert(insert_data).execute()
            
            if result.data and len(result.data) > 0:
                data = result.data[0]
                return VoiceCallMessageResponse(
                    id=str(data["id"]),
                    call_id=str(data["call_id"]),
                    role=MessageRole(data["role"]),
                    content=data["content"],
                    timestamp=datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00")),
                )
            
            raise Exception("Failed to add call message")
            
        except Exception as e:
            logger.error(f"Failed to add call message: {e}")
            raise
    
    async def get_call_messages(self, call_id: str) -> List[VoiceCallMessageResponse]:
        """通話メッセージを取得"""
        try:
            result = self.supabase.client.table("voice_call_messages").select("*").eq(
                "call_id", call_id
            ).order("timestamp").execute()
            
            messages = []
            for data in result.data or []:
                messages.append(VoiceCallMessageResponse(
                    id=str(data["id"]),
                    call_id=str(data["call_id"]),
                    role=MessageRole(data["role"]),
                    content=data["content"],
                    timestamp=datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00")),
                ))
            
            return messages
            
        except Exception as e:
            logger.error(f"Failed to get call messages: {e}")
            raise
    
    # ========================================
    # Twilio Voice Integration (10B)
    # ========================================
    
    def _get_twilio_client(self):
        """Twilioクライアントを取得"""
        if not self.twilio_account_sid or not self.twilio_auth_token:
            raise ValueError("Twilio credentials are not configured")
        
        try:
            from twilio.rest import Client
            return Client(self.twilio_account_sid, self.twilio_auth_token)
        except ImportError:
            raise ImportError("twilio package is not installed. Run: pip install twilio")
    
    async def initiate_call(
        self,
        user_id: str,
        to_number: str,
        purpose: CallPurpose = CallPurpose.OTHER,
        context: Optional[dict] = None,
        task_id: Optional[str] = None,
    ) -> VoiceCallResponse:
        """
        架電を開始
        
        Twilioを使用して指定の電話番号に発信し、
        ElevenLabs Conversational AIで会話を処理します。
        """
        if not self.twilio_phone_number:
            raise ValueError("Twilio phone number is not configured")
        
        try:
            client = self._get_twilio_client()
            
            # Webhook URLを構築（ステータスコールバック用）
            webhook_base = getattr(settings, 'VOICE_WEBHOOK_BASE_URL', '')
            status_callback = f"{webhook_base}/api/v1/voice/webhook/status" if webhook_base else None
            
            # メタデータにコンテキストを含める
            metadata = {
                "purpose": purpose.value,
                "context": context or {},
            }
            
            # TwiMLを直接生成（ngrokを経由しない）
            twiml_content = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="ja-JP">こんにちは。AIアシスタントのダンです。ご用件をお伺いします。</Say>
    <Pause length="2"/>
    <Say language="ja-JP">申し訳ありません。現在、音声会話機能は準備中です。後ほどおかけ直しください。</Say>
    <Hangup/>
</Response>'''
            
            # Twilio APIで発信（twimlパラメータを使用）
            call_params = {
                "to": to_number,
                "from_": self.twilio_phone_number,
                "twiml": twiml_content,
            }
            
            # ステータスコールバックを設定（webhook_baseがある場合のみ）
            if status_callback:
                call_params["status_callback"] = status_callback
                call_params["status_callback_event"] = ['initiated', 'ringing', 'answered', 'completed']
                call_params["status_callback_method"] = 'POST'
            
            call = client.calls.create(**call_params)
            
            # DBに通話レコードを作成
            call_record = await self.create_call_record(
                user_id=user_id,
                call_sid=call.sid,
                direction=CallDirection.OUTBOUND,
                from_number=self.twilio_phone_number,
                to_number=to_number,
                purpose=purpose,
                task_id=task_id,
                metadata=metadata,
            )
            
            logger.info(f"Initiated outbound call: {call.sid} to {to_number}")
            return call_record
            
        except Exception as e:
            logger.error(f"Failed to initiate call: {e}")
            raise
    
    async def end_call(self, call_id: str) -> Optional[VoiceCallResponse]:
        """
        通話を終了
        
        Twilio APIを使用して進行中の通話を終了します。
        """
        try:
            # DBから通話情報を取得
            call = await self.get_call(call_id)
            if not call:
                raise ValueError(f"Call not found: {call_id}")
            
            if call.status in [CallStatus.COMPLETED, CallStatus.FAILED, CallStatus.CANCELED]:
                logger.warning(f"Call {call_id} is already ended with status: {call.status}")
                return call
            
            client = self._get_twilio_client()
            
            # Twilio APIで通話を終了
            client.calls(call.call_sid).update(status='completed')
            
            # DBの状態を更新
            updated_call = await self.update_call_status(
                call_id=call_id,
                status=CallStatus.COMPLETED,
            )
            
            logger.info(f"Ended call: {call.call_sid}")
            return updated_call
            
        except Exception as e:
            logger.error(f"Failed to end call: {e}")
            raise
    
    async def handle_status_callback(
        self,
        call_sid: str,
        call_status: str,
        call_duration: Optional[int] = None,
    ) -> Optional[VoiceCallResponse]:
        """
        Twilioからの通話状態コールバックを処理
        """
        try:
            # Call SIDから通話を検索
            call = await self.get_call_by_sid(call_sid)
            if not call:
                logger.warning(f"Call not found for SID: {call_sid}")
                return None
            
            # Twilioのステータスを内部ステータスにマッピング
            status_mapping = {
                'queued': CallStatus.INITIATED,
                'initiated': CallStatus.INITIATED,
                'ringing': CallStatus.RINGING,
                'in-progress': CallStatus.IN_PROGRESS,
                'completed': CallStatus.COMPLETED,
                'busy': CallStatus.BUSY,
                'no-answer': CallStatus.NO_ANSWER,
                'failed': CallStatus.FAILED,
                'canceled': CallStatus.CANCELED,
            }
            
            new_status = status_mapping.get(call_status.lower(), CallStatus.FAILED)
            
            # 状態を更新
            updated_call = await self.update_call_status(
                call_id=call.id,
                status=new_status,
                duration_seconds=call_duration,
            )
            
            logger.info(f"Updated call {call_sid} status to {new_status.value}")
            return updated_call
            
        except Exception as e:
            logger.error(f"Failed to handle status callback: {e}")
            raise
    
    def generate_outbound_twiml(self, call_sid: str) -> str:
        """
        架電用のTwiMLを生成
        
        ElevenLabs Conversational AIとの接続を設定します。
        Phase 10E完了後はMedia Streamsで接続しますが、
        現在は日本語挨拶を流すシンプルな実装です。
        """
        webhook_base = getattr(settings, 'VOICE_WEBHOOK_BASE_URL', '')
        
        # TODO: Phase 10E完了後にMedia Streams WebSocket連携を有効化
        # ws_url = webhook_base.replace('https://', 'wss://').replace('http://', 'ws://')
        # stream_url = f"{ws_url}/api/v1/voice/stream/{call_sid}"
        
        # 現在は日本語の挨拶を流す（テスト用）
        twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="ja-JP">こんにちは。AIアシスタントのダンです。ご用件をお伺いします。</Say>
    <Pause length="2"/>
    <Say language="ja-JP">申し訳ありません。現在、音声会話機能は準備中です。後ほどおかけ直しください。</Say>
    <Hangup/>
</Response>'''
        
        return twiml
    
    def generate_inbound_twiml(self, call_sid: str, caller: str) -> str:
        """
        受電用のTwiMLを生成
        """
        webhook_base = getattr(settings, 'VOICE_WEBHOOK_BASE_URL', '')
        ws_url = webhook_base.replace('https://', 'wss://').replace('http://', 'ws://')
        stream_url = f"{ws_url}/api/v1/voice/stream/{call_sid}"
        
        twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{stream_url}">
            <Parameter name="call_sid" value="{call_sid}" />
            <Parameter name="caller" value="{caller}" />
        </Stream>
    </Connect>
</Response>'''
        
        return twiml


# シングルトンインスタンス
_voice_service: Optional[VoiceService] = None


def get_voice_service() -> VoiceService:
    """VoiceServiceのシングルトンインスタンスを取得"""
    global _voice_service
    if _voice_service is None:
        _voice_service = VoiceService()
    return _voice_service

