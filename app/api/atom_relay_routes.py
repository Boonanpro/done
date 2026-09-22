"""Authenticated phone audio relay; the same Atom/Live session stays on the PC."""
import asyncio
import json
from pathlib import Path
import httpx
import websockets
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from app.services.auth_service import decode_access_token
from app.services.chat_service import ChatService

router = APIRouter()
ROOT = Path(__file__).resolve().parents[2]

async def paired_device(authorization: str):
    if not authorization.startswith('Bearer '): raise HTTPException(401)
    try: user=decode_access_token(authorization[7:])
    except Exception: raise HTTPException(401)
    if not user: raise HTTPException(401)
    room=json.loads((ROOT/'.tmp/atom-voice-room.json').read_text(encoding='utf-8'))
    if not await ChatService().get_room(room['room_id'],user.user_id):raise HTTPException(403)
    pairing=json.loads((ROOT/'.tmp/atom-wifi-pairing.json').read_text(encoding='utf-8'))
    return pairing

@router.get('/atom-relay')
async def relay_config(request:Request):
    pairing=await paired_device(request.headers.get('authorization',''))
    return {'host':pairing['ip'],'port':48800,'key':pairing['key'],'sampleRate':48000}

@router.post('/atom-direct')
async def direct_config(request:Request):
    """Claim an idle Atom for phone-owned audio; no PCM passes through this endpoint."""
    pairing=await paired_device(request.headers.get('authorization',''))
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response=await client.post('http://127.0.0.1:48801/control',json={
                'key':pairing['key'],'action':'audio_owner','mode':'phone'})
    except httpx.HTTPError:
        raise HTTPException(503, 'デバイスの接続管理にアクセスできませんでした')
    if response.status_code == 409:
        raise HTTPException(409, '現在の音声接続を終了してから切り替えてください')
    if response.status_code != 200:
        raise HTTPException(503, 'デバイス接続の解放を確認できませんでした')
    return {'host':pairing['ip'],'port':48800,'key':pairing['key'],'sampleRate':48000,'audioOwner':'phone'}

@router.websocket('/atom-relay')
async def relay_socket(ws:WebSocket):
    try: pairing=await paired_device(ws.headers.get('authorization',''))
    except (HTTPException, OSError, ValueError):await ws.close(code=1008);return
    await ws.accept()
    tasks=[]
    try:
        async with websockets.connect('ws://127.0.0.1:48801/device-relay',max_size=4096,open_timeout=5,close_timeout=1) as bridge:
            await bridge.send(json.dumps({'key':pairing['key']}))
            ready=await asyncio.wait_for(bridge.recv(),5)
            await ws.send_text(ready)
            async def upstream():
                while True:
                    frame=await ws.receive_bytes()
                    if len(frame)!=972:raise ValueError('Invalid audio frame')
                    await bridge.send(frame)
            async def downstream():
                async for frame in bridge:
                    if isinstance(frame,bytes):await ws.send_bytes(frame)
            tasks=[asyncio.create_task(upstream()),asyncio.create_task(downstream())]
            await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
    except (WebSocketDisconnect,Exception):
        # Frames, tokens and pairing secrets must never enter logs.
        pass
    finally:
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        try:await ws.close()
        except RuntimeError:pass
