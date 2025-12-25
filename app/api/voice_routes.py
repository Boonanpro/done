"""
Phase 10: Voice Communication API Routes
音声通話関連のAPIエンドポイント
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Form, Request, Response

from app.services.voice_service import get_voice_service
from app.models.voice_schemas import (
    CallPurpose, PhoneRuleType, CallDirection, CallStatus,
    VoiceCallCreate, VoiceSettingsUpdate, VoiceSettingsResponse,
    PhoneNumberRuleCreate, PhoneNumberRuleResponse, PhoneNumberRuleListResponse,
    VoiceCallResponse, VoiceCallListResponse,
    VoiceCallStartResponse, VoiceCallEndResponse,
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
# Outbound Call API (10B)
# ========================================

@router.post("/call", response_model=VoiceCallStartResponse, status_code=201)
async def initiate_call(request: VoiceCallCreate):
    """
    架電を開始
    
    指定した電話番号に発信します。
    AIが会話を処理します。
    
    - **to_number**: 発信先電話番号（E.164形式、例: +819012345678）
    - **purpose**: 通話目的（reservation, inquiry, otp_verification, confirmation, cancellation, other）
    - **context**: 会話コンテキスト（予約詳細など）
    - **task_id**: 関連タスクID
    """
    service = get_voice_service()
    
    try:
        call = await service.initiate_call(
            user_id=DEFAULT_USER_ID,
            to_number=request.to_number,
            purpose=request.purpose,
            context=request.context,
            task_id=request.task_id,
        )
        return VoiceCallStartResponse(success=True, call=call)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initiate call: {str(e)}")


@router.post("/call/{call_id}/end", response_model=VoiceCallEndResponse)
async def end_call(call_id: str):
    """
    通話を終了
    
    進行中の通話を終了します。
    """
    service = get_voice_service()
    
    try:
        call = await service.end_call(call_id)
        if not call:
            raise HTTPException(status_code=404, detail="Call not found")
        return VoiceCallEndResponse(success=True, call=call)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to end call: {str(e)}")


# ========================================
# Twilio Webhooks (10B/10C)
# ========================================

@router.post("/webhook/status")
async def twilio_status_callback(
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    CallDuration: Optional[str] = Form(None),
):
    """
    Twilio通話状態Webhook
    
    Twilioからの通話状態コールバックを処理します。
    通話の状態（開始、呼び出し中、通話中、終了など）を更新します。
    """
    service = get_voice_service()
    
    try:
        duration = int(CallDuration) if CallDuration else None
        await service.handle_status_callback(
            call_sid=CallSid,
            call_status=CallStatus,
            call_duration=duration,
        )
        return {"success": True}
    except Exception as e:
        # Webhookはエラーでも200を返す（リトライ防止）
        return {"success": False, "error": str(e)}


@router.post("/webhook/outbound")
async def twilio_outbound_webhook(
    CallSid: str = Form(...),
):
    """
    架電用TwiML Webhook
    
    架電開始時にTwilioから呼ばれ、
    ElevenLabsとの接続指示（TwiML）を返します。
    """
    service = get_voice_service()
    
    try:
        twiml = service.generate_outbound_twiml(CallSid)
        return Response(content=twiml, media_type="application/xml")
    except Exception as e:
        # エラー時は音声でエラーを伝える
        error_twiml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="ja-JP">申し訳ありません。システムエラーが発生しました。後ほどお電話ください。</Say>
    <Hangup/>
</Response>'''
        return Response(content=error_twiml, media_type="application/xml")


@router.post("/webhook/incoming")
async def twilio_incoming_webhook(
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    CallerName: Optional[str] = Form(None),
):
    """
    受電用TwiML Webhook
    
    着信時にTwilioから呼ばれ、
    AIによる応答を開始します。
    """
    service = get_voice_service()
    
    try:
        # ユーザーの音声設定を確認
        voice_settings = await service.get_voice_settings(DEFAULT_USER_ID)
        
        if not voice_settings.inbound_enabled:
            # 受電無効の場合は留守電メッセージ
            twiml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="ja-JP">お電話ありがとうございます。ただいま電話に出ることができません。後ほどおかけ直しください。</Say>
    <Hangup/>
</Response>'''
            return Response(content=twiml, media_type="application/xml")
        
        # 電話番号ルールを確認
        rule = await service.check_phone_rule(DEFAULT_USER_ID, From)
        
        if rule and rule.rule_type == PhoneRuleType.BLACKLIST:
            # ブラックリストの場合は即座に切断
            twiml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Hangup/>
</Response>'''
            return Response(content=twiml, media_type="application/xml")
        
        # 通話レコードを作成
        from app.models.voice_schemas import CallDirection, CallPurpose
        call_record = await service.create_call_record(
            user_id=DEFAULT_USER_ID,
            call_sid=CallSid,
            direction=CallDirection.INBOUND,
            from_number=From,
            to_number=To,
            purpose=CallPurpose.INQUIRY,
            metadata={"caller_name": CallerName},
        )
        
        # TwiMLを生成
        twiml = service.generate_inbound_twiml(CallSid, From)
        return Response(content=twiml, media_type="application/xml")
        
    except Exception as e:
        # エラー時は音声でエラーを伝える
        error_twiml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="ja-JP">申し訳ありません。システムエラーが発生しました。後ほどお電話ください。</Say>
    <Hangup/>
</Response>'''
        return Response(content=error_twiml, media_type="application/xml")


# ========================================
# Media Streams WebSocket (10E)
# ========================================

from fastapi import WebSocket, WebSocketDisconnect
import json
import base64
import asyncio
import logging

logger = logging.getLogger(__name__)


class MediaStreamHandler:
    """Twilio Media Streams処理ハンドラー"""
    
    # 無音検知設定
    SILENCE_THRESHOLD = 10  # 無音とみなす音量閾値
    SILENCE_DURATION_MS = 800  # 発話終了とみなす無音時間（ミリ秒）
    MIN_SPEECH_DURATION_MS = 500  # 最小発話時間（ミリ秒）
    SAMPLE_RATE = 8000  # Twilioのサンプルレート
    
    def __init__(self, call_sid: str, websocket: WebSocket):
        self.call_sid = call_sid
        self.websocket = websocket
        self.stream_sid: Optional[str] = None
        self.audio_buffer: bytes = b""
        self.is_connected: bool = False
        self.conversation_history: list = []
        self.is_speaking: bool = False
        self.silence_samples: int = 0
        self.speech_start_time: float = 0
        self.is_processing: bool = False  # 処理中フラグ
        self.context: dict = {}  # 通話コンテキスト
    
    async def handle_message(self, message: dict) -> None:
        """Media Streamsメッセージを処理"""
        event = message.get("event")
        
        if event == "connected":
            await self._handle_connected(message)
        elif event == "start":
            await self._handle_start(message)
        elif event == "media":
            await self._handle_media(message)
        elif event == "stop":
            await self._handle_stop(message)
        elif event == "mark":
            # マーカーイベント（TTS再生完了等）
            logger.debug(f"Mark event received: {message.get('mark', {}).get('name')}")
    
    async def _handle_connected(self, message: dict) -> None:
        """接続確立"""
        logger.info(f"Media Stream connected for call: {self.call_sid}")
        self.is_connected = True
    
    async def _handle_start(self, message: dict) -> None:
        """ストリーム開始"""
        import time
        
        start_data = message.get("start", {})
        self.stream_sid = start_data.get("streamSid")
        
        # パラメータからコンテキストを取得
        custom_params = start_data.get("customParameters", {})
        self.context = {
            "direction": custom_params.get("direction", "unknown"),
            "purpose": custom_params.get("purpose", ""),
        }
        
        logger.info(f"Media Stream started: {self.stream_sid}, context: {self.context}")
        
        self.speech_start_time = time.time()
        
        # 初期挨拶を送信
        await self._send_greeting()
    
    async def _handle_media(self, message: dict) -> None:
        """音声データ受信"""
        import time
        
        if self.is_processing:
            # 処理中は音声を無視（割り込み防止）
            return
        
        media_data = message.get("media", {})
        payload = media_data.get("payload", "")
        
        if payload:
            # Base64デコードしてバッファに追加
            audio_data = base64.b64decode(payload)
            
            # 音量レベルをチェック（無音検知）
            volume = self._calculate_volume(audio_data)
            
            if volume > self.SILENCE_THRESHOLD:
                # 発話中
                if not self.is_speaking:
                    self.is_speaking = True
                    self.speech_start_time = time.time()
                    logger.debug("Speech started")
                
                self.silence_samples = 0
                self.audio_buffer += audio_data
            else:
                # 無音
                if self.is_speaking:
                    self.silence_samples += len(audio_data)
                    self.audio_buffer += audio_data  # 無音も一旦バッファに
                    
                    # 無音が一定時間続いたら発話終了
                    silence_duration_ms = (self.silence_samples / self.SAMPLE_RATE) * 1000
                    
                    if silence_duration_ms >= self.SILENCE_DURATION_MS:
                        speech_duration_ms = (time.time() - self.speech_start_time) * 1000
                        
                        if speech_duration_ms >= self.MIN_SPEECH_DURATION_MS:
                            logger.debug(f"Speech ended, duration: {speech_duration_ms:.0f}ms")
                            await self._process_audio_buffer()
                        else:
                            # 短すぎる発話は無視
                            self.audio_buffer = b""
                        
                        self.is_speaking = False
                        self.silence_samples = 0
    
    def _calculate_volume(self, audio_data: bytes) -> float:
        """μ-law音声データの音量を計算"""
        if not audio_data:
            return 0
        
        # μ-lawデータの平均絶対値を計算
        total = sum(abs(b - 128) for b in audio_data)
        return total / len(audio_data)
    
    async def _handle_stop(self, message: dict) -> None:
        """ストリーム終了"""
        logger.info(f"Media Stream stopped: {self.stream_sid}")
        self.is_connected = False
        
        # 残っているバッファがあれば処理
        if len(self.audio_buffer) > 1000:
            await self._process_audio_buffer()
        
        # 通話記録を更新
        await self._finalize_call()
    
    async def _send_greeting(self) -> None:
        """初期挨拶を送信"""
        service = get_voice_service()
        
        greeting = "お電話ありがとうございます。AIアシスタントのダンです。ご用件をお伺いします。"
        
        # 会話履歴に追加
        self.conversation_history.append({
            "role": "assistant",
            "content": greeting
        })
        
        # TTSで音声生成してTwilioに送信
        try:
            audio_data = await service.text_to_speech_ulaw(greeting)
            if audio_data:
                await self.send_audio(audio_data)
                logger.info(f"Greeting sent for call: {self.call_sid}")
            else:
                logger.warning("Failed to generate greeting audio")
        except Exception as e:
            logger.error(f"Failed to send greeting: {e}")
    
    async def _process_audio_buffer(self) -> None:
        """音声バッファを処理（STT → Claude → TTS パイプライン）"""
        if not self.audio_buffer or self.is_processing:
            return
        
        self.is_processing = True
        service = get_voice_service()
        
        try:
            # 1. μ-law → PCM変換
            pcm_8k = service.ulaw_to_pcm(self.audio_buffer)
            
            # 2. 8kHz → 16kHz リサンプリング（STT用）
            pcm_16k = service.resample_audio(pcm_8k, 8000, 16000, 2)
            
            # 3. STT: 音声 → テキスト
            user_text = await service.speech_to_text(pcm_16k)
            
            if user_text and user_text.strip():
                logger.info(f"User said: {user_text}")
                
                # 会話履歴に追加
                self.conversation_history.append({
                    "role": "user",
                    "content": user_text
                })
                
                # 4. Claude: 応答生成
                response_text = await service.generate_response(
                    user_text,
                    self.conversation_history,
                    self.context
                )
                
                logger.info(f"AI response: {response_text}")
                
                # 会話履歴に追加
                self.conversation_history.append({
                    "role": "assistant",
                    "content": response_text
                })
                
                # 5. TTS: テキスト → 音声（μ-law形式）
                audio_response = await service.text_to_speech_ulaw(response_text)
                
                if audio_response:
                    await self.send_audio(audio_response)
                else:
                    logger.warning("Failed to generate response audio")
            else:
                logger.debug("No speech recognized")
                
        except Exception as e:
            logger.error(f"Error processing audio: {e}")
        finally:
            self.audio_buffer = b""
            self.is_processing = False
    
    async def _finalize_call(self) -> None:
        """通話終了処理"""
        service = get_voice_service()
        try:
            call = await service.get_call_by_sid(self.call_sid)
            if call:
                # 会話履歴から文字起こしを作成
                transcription = "\n".join(
                    f"{'相手' if msg['role'] == 'user' else 'AI'}: {msg['content']}"
                    for msg in self.conversation_history
                )
                
                # AI要約を生成
                summary = None
                if len(self.conversation_history) > 1:
                    try:
                        summary = await self._generate_summary()
                    except Exception as e:
                        logger.warning(f"Failed to generate summary: {e}")
                
                # 通話記録を更新
                updated_call = await service.update_call_status(
                    call_id=call.id,
                    status=CallStatus.COMPLETED,
                    transcription=transcription if transcription else None,
                    summary=summary,
                )
                logger.info(f"Call finalized: {self.call_sid}")
                
                # チャット通知を送信
                if updated_call:
                    try:
                        await service.notify_chat(
                            user_id=call.user_id,
                            call=updated_call,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send chat notification: {e}")
        except Exception as e:
            logger.error(f"Failed to finalize call: {e}")
    
    async def _generate_summary(self) -> Optional[str]:
        """通話の要約を生成"""
        if not self.conversation_history:
            return None
        
        try:
            from langchain_anthropic import ChatAnthropic
            from langchain_core.messages import HumanMessage, SystemMessage
            from app.config import settings
            
            llm = ChatAnthropic(
                model="claude-sonnet-4-20250514",
                api_key=settings.ANTHROPIC_API_KEY,
                max_tokens=200,
            )
            
            conversation_text = "\n".join(
                f"{'相手' if msg['role'] == 'user' else 'AI'}: {msg['content']}"
                for msg in self.conversation_history
            )
            
            messages = [
                SystemMessage(content="以下の電話会話を1-2文で要約してください。重要なポイント（予約内容、問い合わせ内容、決定事項など）を含めてください。"),
                HumanMessage(content=conversation_text)
            ]
            
            response = await llm.ainvoke(messages)
            return response.content
            
        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            return None
    
    async def send_audio(self, audio_data: bytes) -> None:
        """音声データをチャンクで送信"""
        if not self.is_connected or not self.stream_sid:
            return
        
        # Twilioは160バイト（20ms）単位で送信を推奨
        CHUNK_SIZE = 160
        
        for i in range(0, len(audio_data), CHUNK_SIZE):
            chunk = audio_data[i:i + CHUNK_SIZE]
            
            # Base64エンコード
            payload = base64.b64encode(chunk).decode("utf-8")
            
            message = {
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {
                    "payload": payload
                }
            }
            
            try:
                await self.websocket.send_json(message)
            except Exception as e:
                logger.error(f"Failed to send audio chunk: {e}")
                break
            
            # 20ms間隔で送信（リアルタイム再生のため）
            await asyncio.sleep(0.02)


@router.websocket("/stream/{call_sid}")
async def media_stream_websocket(websocket: WebSocket, call_sid: str):
    """
    Twilio Media Streams WebSocket
    
    Twilioからの音声ストリームを受信し、
    ElevenLabsでSTT/TTS処理を行い、
    AIとの双方向会話を実現する。
    """
    await websocket.accept()
    logger.info(f"WebSocket connection accepted for call: {call_sid}")
    
    handler = MediaStreamHandler(call_sid, websocket)
    
    try:
        while True:
            # Twilioからのメッセージを受信
            data = await websocket.receive_text()
            message = json.loads(data)
            
            await handler.handle_message(message)
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for call: {call_sid}")
    except Exception as e:
        logger.error(f"WebSocket error for call {call_sid}: {e}")
    finally:
        # クリーンアップ
        if handler.is_connected:
            await handler._finalize_call()

