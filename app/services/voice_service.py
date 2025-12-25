"""
Phase 10: Voice Communication Service
音声通話サービス（ElevenLabs + Claude統合）
"""
import logging
import audioop
import struct
import io
from typing import Optional, List, Tuple
from datetime import datetime
import uuid
import aiohttp

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
            
            # Webhook URLを構築
            webhook_base = getattr(settings, 'VOICE_WEBHOOK_BASE_URL', '')
            status_callback = f"{webhook_base}/api/v1/voice/webhook/status" if webhook_base else None
            outbound_url = f"{webhook_base}/api/v1/voice/webhook/outbound" if webhook_base else None
            
            # メタデータにコンテキストを含める
            metadata = {
                "purpose": purpose.value,
                "context": context or {},
            }
            
            # Twilio APIで発信
            call_params = {
                "to": to_number,
                "from_": self.twilio_phone_number,
            }
            
            # Webhook URLがある場合はURL方式、ない場合はTwiML直接指定
            if outbound_url:
                call_params["url"] = outbound_url
                call_params["method"] = "POST"
            else:
                # フォールバック: 固定TwiML
                call_params["twiml"] = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="ja-JP">こんにちは。AIアシスタントのダンです。</Say>
    <Say language="ja-JP">音声会話の設定が完了していません。</Say>
    <Hangup/>
</Response>'''
            
            # ステータスコールバックを設定
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
        
        Media Streams WebSocketを使用して双方向音声会話を実現。
        """
        webhook_base = getattr(settings, 'VOICE_WEBHOOK_BASE_URL', '')
        
        if webhook_base:
            # Media Streams WebSocketを使用
            ws_url = webhook_base.replace('https://', 'wss://').replace('http://', 'ws://')
            stream_url = f"{ws_url}/api/v1/voice/stream/{call_sid}"
            
            twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{stream_url}">
            <Parameter name="call_sid" value="{call_sid}" />
            <Parameter name="direction" value="outbound" />
        </Stream>
    </Connect>
</Response>'''
        else:
            # Webhook URLが設定されていない場合はフォールバック
            twiml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="ja-JP">こんにちは。AIアシスタントのダンです。</Say>
    <Pause length="1"/>
    <Say language="ja-JP">申し訳ありません。音声会話の設定が完了していません。</Say>
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
    
    # ========================================
    # Audio Format Conversion (10E)
    # ========================================
    
    def ulaw_to_pcm(self, ulaw_data: bytes) -> bytes:
        """
        μ-law (8kHz) → PCM (16-bit, 8kHz) 変換
        
        Args:
            ulaw_data: μ-law形式の音声データ
            
        Returns:
            PCM形式の音声データ (16-bit signed, 8kHz)
        """
        try:
            # μ-law → PCM (16-bit)
            pcm_data = audioop.ulaw2lin(ulaw_data, 2)  # 2 = 16-bit
            return pcm_data
        except Exception as e:
            logger.error(f"ulaw_to_pcm conversion failed: {e}")
            return b""
    
    def pcm_to_ulaw(self, pcm_data: bytes) -> bytes:
        """
        PCM (16-bit, 8kHz) → μ-law (8kHz) 変換
        
        Args:
            pcm_data: PCM形式の音声データ (16-bit signed)
            
        Returns:
            μ-law形式の音声データ
        """
        try:
            # PCM → μ-law
            ulaw_data = audioop.lin2ulaw(pcm_data, 2)  # 2 = 16-bit
            return ulaw_data
        except Exception as e:
            logger.error(f"pcm_to_ulaw conversion failed: {e}")
            return b""
    
    def resample_audio(
        self, 
        audio_data: bytes, 
        from_rate: int, 
        to_rate: int, 
        sample_width: int = 2
    ) -> bytes:
        """
        サンプルレート変換
        
        Args:
            audio_data: 音声データ
            from_rate: 元のサンプルレート
            to_rate: 変換先のサンプルレート
            sample_width: サンプル幅（バイト数、2=16-bit）
            
        Returns:
            リサンプリングされた音声データ
        """
        try:
            # audioop.ratecvを使用してリサンプリング
            converted, _ = audioop.ratecv(
                audio_data, 
                sample_width, 
                1,  # nchannels
                from_rate, 
                to_rate, 
                None  # state
            )
            return converted
        except Exception as e:
            logger.error(f"resample_audio failed: {e}")
            return audio_data
    
    # ========================================
    # ElevenLabs STT/TTS (10E)
    # ========================================
    
    async def speech_to_text(self, audio_data: bytes) -> Optional[str]:
        """
        ElevenLabs STTで音声をテキストに変換
        
        Args:
            audio_data: PCM音声データ（16kHz推奨）
            
        Returns:
            認識されたテキスト
        """
        if not self.elevenlabs_api_key:
            logger.warning("ElevenLabs API key not configured")
            return None
        
        try:
            # 音声データをWAV形式に変換
            wav_data = self._pcm_to_wav(audio_data, sample_rate=16000)
            
            async with aiohttp.ClientSession() as session:
                # ElevenLabs Speech-to-Text API
                url = "https://api.elevenlabs.io/v1/speech-to-text"
                
                headers = {
                    "xi-api-key": self.elevenlabs_api_key,
                }
                
                form_data = aiohttp.FormData()
                form_data.add_field(
                    "audio",
                    wav_data,
                    filename="audio.wav",
                    content_type="audio/wav"
                )
                form_data.add_field("model_id", "scribe_v1")  # Whisper-based model
                form_data.add_field("language_code", "ja")  # Japanese
                
                async with session.post(url, headers=headers, data=form_data) as response:
                    if response.status == 200:
                        result = await response.json()
                        text = result.get("text", "")
                        logger.debug(f"STT result: {text[:50]}..." if len(text) > 50 else f"STT result: {text}")
                        return text
                    else:
                        error_text = await response.text()
                        logger.error(f"ElevenLabs STT error: {response.status} - {error_text}")
                        return None
                        
        except Exception as e:
            logger.error(f"speech_to_text failed: {e}")
            return None
    
    async def text_to_speech(
        self, 
        text: str, 
        voice_id: Optional[str] = None
    ) -> Optional[bytes]:
        """
        ElevenLabs TTSでテキストを音声に変換
        
        Args:
            text: 音声に変換するテキスト
            voice_id: 使用する音声ID（省略時はデフォルト）
            
        Returns:
            MP3形式の音声データ
        """
        if not self.elevenlabs_api_key:
            logger.warning("ElevenLabs API key not configured")
            return None
        
        voice_id = voice_id or self.elevenlabs_voice_id or "pNInz6obpgDQGcFmaJgB"  # デフォルト: Adam
        
        try:
            async with aiohttp.ClientSession() as session:
                # ElevenLabs Text-to-Speech API
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                
                headers = {
                    "xi-api-key": self.elevenlabs_api_key,
                    "Content-Type": "application/json",
                }
                
                payload = {
                    "text": text,
                    "model_id": self.elevenlabs_model_id,
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                    }
                }
                
                async with session.post(url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        audio_data = await response.read()
                        logger.debug(f"TTS generated {len(audio_data)} bytes")
                        return audio_data
                    else:
                        error_text = await response.text()
                        logger.error(f"ElevenLabs TTS error: {response.status} - {error_text}")
                        return None
                        
        except Exception as e:
            logger.error(f"text_to_speech failed: {e}")
            return None
    
    async def text_to_speech_ulaw(
        self, 
        text: str, 
        voice_id: Optional[str] = None
    ) -> Optional[bytes]:
        """
        TTSで生成した音声をμ-law 8kHz形式に変換
        Twilio Media Streamsで使用するため
        
        Args:
            text: 音声に変換するテキスト
            voice_id: 使用する音声ID
            
        Returns:
            μ-law 8kHz形式の音声データ
        """
        if not self.elevenlabs_api_key:
            logger.warning("ElevenLabs API key not configured")
            return None
        
        voice_id = voice_id or self.elevenlabs_voice_id or "pNInz6obpgDQGcFmaJgB"
        
        try:
            async with aiohttp.ClientSession() as session:
                # PCM形式で取得（μ-law変換用）
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                
                headers = {
                    "xi-api-key": self.elevenlabs_api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/wav",  # WAV形式でリクエスト
                }
                
                payload = {
                    "text": text,
                    "model_id": self.elevenlabs_model_id,
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                    },
                    "output_format": "pcm_16000"  # 16kHz PCM
                }
                
                async with session.post(url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        pcm_data = await response.read()
                        
                        # 16kHz → 8kHz リサンプリング
                        pcm_8k = self.resample_audio(pcm_data, 16000, 8000, 2)
                        
                        # PCM → μ-law
                        ulaw_data = self.pcm_to_ulaw(pcm_8k)
                        
                        logger.debug(f"TTS+μ-law generated {len(ulaw_data)} bytes")
                        return ulaw_data
                    else:
                        error_text = await response.text()
                        logger.error(f"ElevenLabs TTS error: {response.status} - {error_text}")
                        return None
                        
        except Exception as e:
            logger.error(f"text_to_speech_ulaw failed: {e}")
            return None
    
    def _pcm_to_wav(self, pcm_data: bytes, sample_rate: int = 16000, channels: int = 1, sample_width: int = 2) -> bytes:
        """
        PCMデータをWAV形式に変換
        
        Args:
            pcm_data: PCM音声データ
            sample_rate: サンプルレート
            channels: チャンネル数
            sample_width: サンプル幅（バイト数）
            
        Returns:
            WAV形式の音声データ
        """
        import wave
        
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)
        
        buffer.seek(0)
        return buffer.read()
    
    # ========================================
    # Claude Response Generation (10E)
    # ========================================
    
    async def generate_response(
        self, 
        user_message: str, 
        conversation_history: List[dict],
        context: Optional[dict] = None
    ) -> str:
        """
        Claudeで音声会話の応答を生成
        
        Args:
            user_message: ユーザーの発話
            conversation_history: 会話履歴 [{"role": "user/assistant", "content": "..."}]
            context: 追加のコンテキスト（予約目的など）
            
        Returns:
            AI応答テキスト
        """
        try:
            from langchain_anthropic import ChatAnthropic
            from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
            
            llm = ChatAnthropic(
                model="claude-sonnet-4-20250514",
                api_key=settings.ANTHROPIC_API_KEY,
                max_tokens=500,  # 音声会話は短い応答
            )
            
            # システムプロンプト
            system_prompt = """あなたはAI秘書「ダン」です。電話で相手と会話しています。

ルール:
- 簡潔に応答する（1〜2文程度）
- 質問には直接答える
- 予約や問い合わせの要件を聞き取る
- 必要な情報を確認する
- 敬語を使う
"""
            
            if context:
                purpose = context.get("purpose", "")
                if purpose:
                    system_prompt += f"\n現在の通話目的: {purpose}"
            
            messages = [SystemMessage(content=system_prompt)]
            
            # 会話履歴を追加
            for msg in conversation_history[-10:]:  # 最新10件まで
                if msg["role"] == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                else:
                    messages.append(AIMessage(content=msg["content"]))
            
            # 現在のユーザーメッセージ
            messages.append(HumanMessage(content=user_message))
            
            # 応答を生成
            response = await llm.ainvoke(messages)
            
            return response.content
            
        except Exception as e:
            logger.error(f"generate_response failed: {e}")
            return "申し訳ありません。少々お待ちください。"
    
    # ========================================
    # Chat Notification (10F)
    # ========================================
    
    async def notify_chat(
        self,
        user_id: str,
        call: VoiceCallResponse,
    ) -> bool:
        """
        通話内容をチャットに通知
        
        Args:
            user_id: ユーザーID
            call: 通話情報
            
        Returns:
            通知成功の場合True
        """
        try:
            # 1. 設定確認
            settings = await self.get_voice_settings(user_id)
            if not settings or not settings.notify_via_chat:
                logger.debug(f"Chat notification disabled for user: {user_id}")
                return False
            
            # 2. 通知メッセージを構築
            direction_text = "着信" if call.direction == CallDirection.INBOUND else "発信"
            
            other_number = call.from_number if call.direction == CallDirection.INBOUND else call.to_number
            
            duration_text = f"{call.duration_seconds}秒" if call.duration_seconds else "不明"
            purpose_text = call.purpose.value if call.purpose else "不明"
            
            message = f"""📞 **{direction_text}通話が終了しました**

相手: {other_number}
時間: {duration_text}
目的: {purpose_text}

**要約:**
{call.summary or "（要約なし）"}
"""
            
            # 3. チャットサービスに送信
            from app.services.chat_service import get_chat_service
            chat_service = get_chat_service()
            
            result = await chat_service.send_system_message(
                user_id=user_id,
                message=message,
            )
            
            if result:
                logger.info(f"Chat notification sent for call: {call.call_sid}")
                return True
            else:
                logger.warning(f"Failed to send chat notification for call: {call.call_sid}")
                return False
            
        except Exception as e:
            logger.error(f"notify_chat failed: {e}")
            return False


# シングルトンインスタンス
_voice_service: Optional[VoiceService] = None


def get_voice_service() -> VoiceService:
    """VoiceServiceのシングルトンインスタンスを取得"""
    global _voice_service
    if _voice_service is None:
        _voice_service = VoiceService()
    return _voice_service

