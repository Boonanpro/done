"""チャット統合音声モード（V1）のバックエンド。

  POST /api/v1/voicelog/live/session — 通話(Live 1 + Responses 委譲)の開始。委譲はサーバーの sideband が答える
  POST /api/v1/voicelog/{room_id}    — 音声会話の文字起こしを部屋の履歴に保存

音声そのものはブラウザ ↔ OpenAI の WebRTC 直結。ここはトークン発行と
「会話をチャットログに残す」だけを担う。文字起こしを chat_messages に保存する
ことで、ダン（CLI）が後のターンで音声会話を文脈として読める＝部屋が共有記憶になる。

サンドボックス側に置く理由: 反映が sandbox restart だけで済む（コアは不変の原則）。
next.config の rewrites では /api/v1/voicelog/* は既定でサンドボックス(8000)に届く。
"""
from __future__ import annotations

import logging
from typing import Optional, Literal
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings
from app.services.auth_service import TokenData, decode_access_token
from app.api.atom_relay_routes import router as atom_relay_router
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voicelog", tags=["voice-mode"])
router.include_router(atom_relay_router)

CLIENT_SECRETS_ENDPOINT = "https://api.openai.com/v1/realtime/client_secrets"
REALTIME_MODEL = "gpt-realtime-2.1"
ACCESS_TOKEN_COOKIE = "done_access_token"


def _get_user(request: Request) -> TokenData:
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    td = decode_access_token(token) if token else None
    if not td:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return td


@router.get('/command-center/device')
async def command_center_device(request: Request):
    import asyncio
    import json
    from pathlib import Path
    user = _get_user(request)
    try:
        destination = json.loads((Path(__file__).resolve().parents[2] / '.tmp/atom-voice-room.json').read_text(encoding='utf-8'))
        if not await ChatService().get_room(destination['room_id'], user.user_id):
            raise HTTPException(status_code=403, detail='No access to this device')
        async with httpx.AsyncClient(timeout=2) as client:
            device, voice = await asyncio.gather(client.get('http://127.0.0.1:48801/status'), client.get('http://127.0.0.1:48802/status'))
            device.raise_for_status()
            voice.raise_for_status()
            d, v = device.json(), voice.json()
        return {'connected': bool(d.get('device_connected')), 'state': v.get('state'),
            'requested': bool(d.get('requested')), 'room_id': destination['room_id']}
    except HTTPException:
        raise
    except Exception:
        return {'connected': False, 'state': 'unavailable'}


_EDITOR_TOOLS = [   # the editor assistant's shared definitions (the phone/web voice tools retired 2026-09-23)
    {
        "type": "function",
        "name": "timeline_edit",
        "description": (
            "動画エディタのタイムラインに小さな編集を1つ即時反映する（数秒で画面が変わる）。"
            "op と args を渡す。op: move_clip{clip_id,new_start} / trim_clip{clip_id,edge:left|right,new_time} / "
            "remove_clip{clip_id} / split_clip{clip_id,at} / set_clip{clip_id,text?,style?}(字幕の文言) / "
            "set_clip_props{clip_id,props:{position|fit|crop|opacity|volume|muted|speed|transform_keys|asset_id|source_start|grade}} / "
            "gradeは{ev,contrast,sat,temp,tint}の全置換。明るさはev(露出段数、0=無補正)、contrast/satは倍率(1=無補正)、temp/tintは0=無補正。既存の他の補正を保つなら現在値も含める。 / "
            "add_region{timeline_start,timeline_end,x,y,width,height,style:gaussian|mosaic|frame|marker|spotlight,color?,strength?,keys?}"
            "（ぼかし/黄色枠。座標は画面比0-1、左上原点） / set_region{clip_id,x?,y?,width?,height?,style?,color?,strength?,keys?,clear_keys?} / "
            "add_caption{text,timeline_start,timeline_end} / add_clip{asset_id,timeline_start,duration,source_start?,position?,speed?} / "
            "add_audio{asset_id,duration,at,source_start?,volume?,role?}。"
            "複数の編集は1つずつ順に呼ぶ。素材の生成・複雑な構成変更は delegate_to_dan。"
        ),
        "parameters": {"type": "object", "properties": {
            "op": {"type": "string"},
            "args": {"type": "object", "description": "opの引数"},
            "content_id": {"type": "string", "description": "省略時はエディタで開いているコンテンツ"}},
            "required": ["op", "args"]},
    },
    {
        "type": "function",
        "name": "timeline_frame",
        "description": "動画の指定秒の合成後の画面（字幕・ぼかし・枠・重ね全部込み）を画像で見る。編集の前後確認に使う。約10秒。",
        "parameters": {"type": "object", "properties": {
            "t": {"type": "number", "description": "タイムライン秒。省略時は再生位置"},
            "content_id": {"type": "string"}}, "required": []},
    },
    {
        "type": "function",
        "name": "read_skill",
        "description": (
            "制作の作法が定義されたスキル文書を読む。name省略で一覧、指定で本文。"
            "まとまった制作・編集（LP作成、デザイン変更など）を自分でやる前に、該当スキルがあれば読んで作法に従う。"
        ),
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "例: build"}},
            "required": [],
        },
    },
]


class LiveSessionRequest(BaseModel):
    server_delegation: bool = True   # kept for older apps; the server's sideband always answers (Responses delegation)
    sdp: str = Field(default='', max_length=65536)
    room_id: str
    device: bool = False
    provider: Literal['openai'] = 'openai'
    timezone: str = Field(default='Asia/Tokyo', max_length=128)


@router.post('/live/session')
async def create_live_session(request: Request, body: LiveSessionRequest):
    from app.services.voice_live import MODEL, session_config, register, bind_session, close
    from uuid import uuid4
    user = _get_user(request)
    chat = ChatService()
    if not await chat.get_room(body.room_id, user.user_id):
        raise HTTPException(403, '部屋へのアクセス権がありません')
    if not body.sdp:
        raise HTTPException(422, 'SDP is required for Live 1')
    if not settings.OPENAI_API_KEY:
        raise HTTPException(503, 'OPENAI_API_KEY が未設定です')
    from app.services.voice_history import room_history
    # Load once, with the same room membership check as ordinary chat history.
    # A failed read must not silently turn an existing room into an empty call.
    messages = await chat.get_messages(body.room_id, user.user_id, limit=96)
    history = room_history(messages)
    pending_id = 'pending-' + uuid4().hex
    register(pending_id, user.user_id, room_id=body.room_id)
    bound = False
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.post('https://api.openai.com/v1/live/sessions',
                headers={'Authorization': 'Bearer ' + settings.OPENAI_API_KEY},
                json={'session': session_config(history, timezone=body.timezone),
                    'transport': {'type': 'webrtc', 'sdp': body.sdp}})
        data = response.json()
        if response.status_code not in (200, 201) or not data.get('session', {}).get('id') or not data.get('transport', {}).get('sdp'):
            logger.error('Live session rejected: status=%s request_id=%s', response.status_code, response.headers.get('x-request-id'))
            raise HTTPException(502, 'Live 1への接続に失敗しました')
        bind_session(pending_id, data['session']['id'])
        bound = True
        # The backend model's function calls arrive only on the server's own connection to the call: it always answers them.
        from app.services import voice_sideband
        owned = voice_sideband.attach(data['session']['id'], user.user_id, body.room_id, settings.OPENAI_API_KEY, own=True)
        # Dan's tools for this call start loading now (a few seconds), not when the backend first needs one
        from app.services import voice_tools
        voice_tools.warm(user.user_id, body.room_id)
        return {'session': {'id': data['session']['id']}, 'transport': data['transport'], 'model': MODEL, 'server_delegation': owned}
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, 'Live 1への接続に失敗しました') from exc
    finally:
        if not bound:
            close(pending_id, user.user_id)


class LiveCloseRequest(BaseModel):
    session_id: str

@router.post('/live/backend/close')
async def close_live_backend(request: Request, body: LiveCloseRequest):
    from app.services.voice_live import close
    user=_get_user(request)
    try: close(body.session_id,user.user_id)
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc
    return {'closed':True}


class CommandCenterRequest(BaseModel):
    room_id: str
    args: dict


@router.post("/command-center")
async def command_center(request: Request, body: CommandCenterRequest):
    from app.services.command_center import execute
    user = _get_user(request)
    try:
        return await execute(body.args, body.room_id, user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ------------------------------------------------------- artifact editing
#
# V2: 成果物編集ツール群（scratch実験で実証済みの一式の本番移植）。
# チャットのプレビューiframeはクロスオリジン(postMessage方式)のため、
# 編集・撮影・検査はすべてサーバー側で実行し、フロントは編集後に
# プレビューの contentVersion を bump して再読込で見せる。

import asyncio
import base64
import re as _re
import subprocess


# ------------------------------------------------------------- transcript

class TranscriptRequest(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=8000)
    created_at: Optional[datetime] = None


@router.post("/{room_id}")
async def add_voice_transcript(room_id: str, request: Request, body: TranscriptRequest):
    """音声会話の1発話を部屋の履歴に保存する（🎙マーク付き）。

    sender_type は human/ai を使い分けるので、チャットUIでは通常の
    ユーザー/ダンの吹き出しとして時系列に並ぶ。ダン（CLI）は後のターンで
    この履歴を読めるため、音声↔テキストの記憶が部屋単位で繋がる。
    """
    user = _get_user(request)
    sender_type = "human" if body.role == "user" else "ai"
    content = f"🎙 {body.content.strip()}"
    svc = ChatService()
    try:
        message = await svc.send_message(room_id, user.user_id, content, sender_type=sender_type,
            created_at=body.created_at.isoformat() if body.created_at else None)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {"ok": True, "id": message.get("id")}
