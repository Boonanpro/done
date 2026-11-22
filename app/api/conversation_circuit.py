"""Observed paths and isolated handoff previews for the instructions screen."""
import asyncio
import base64
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.chat_routes import get_current_user, _session_model_payload
from app.services import conversation_circuit as circuit, prompt_store
from app.services.chat_service import ChatService
from app.services.owner import resolve_owner_user_id
from app.services.supabase_client import get_supabase_client

router = APIRouter(prefix='/circuit')


async def owner(user=Depends(get_current_user)):
    if user.user_id != await asyncio.to_thread(resolve_owner_user_id):
        raise HTTPException(403, '本人の画面から開いてください。')
    return user.user_id


async def check_room(room, user):
    record = await ChatService().get_room(room, user)
    if not record or record.get('type') not in ('dan', 'project'):
        raise HTTPException(404, 'ダンと話す部屋を選んでください。')


@router.get('/rooms')
async def rooms(user=Depends(owner)):
    return await asyncio.to_thread(circuit.owner_rooms, get_supabase_client().client, user)


@router.get('/active')
async def active_requests(user=Depends(owner)):
    return await asyncio.to_thread(circuit.active_requests, get_supabase_client().client, user)


@router.get('/history')
async def history(room: str, selected: str = '', user=Depends(owner)):
    await check_room(room, user)
    return await asyncio.to_thread(circuit.snapshot, get_supabase_client().client, room, user, selected)


class Trial(BaseModel):
    room: str
    channel: Literal['voice', 'chat']
    words: str = Field(min_length=1, max_length=8000)


def now():
    return datetime.now(timezone.utc).isoformat()


@router.post('/preview')
async def preview(body: Trial, user=Depends(owner)):
    await check_room(body.room, user)
    events = [circuit.step(now(), 'owner', '振り分けに渡す言葉', body.words)]
    from app.services import voice_editor
    place = await asyncio.to_thread(voice_editor.call_editor, body.room)
    if body.channel == 'chat':
        from app.services import voice_calls
        if await asyncio.to_thread(voice_calls.active, body.room):
            events.append(circuit.step(now(), 'voice', '進行中の通話に渡す直前', body.words))
            return events
        result = await _session_model_payload(body.room, None)
        events.append(circuit.step(now(), 'editor' if place else 'chat',
                      'エディターのダンに渡す直前' if place else 'チャットのダンに渡す直前',
                      body.words, model=result['effective_model']))
        return events
    from app.services.voice_router import Router, TO_CHAT_DAN, prepare_chat_task
    from app.services.voice_sideband import Dialogue
    dialogue = Dialogue()
    if place:
        dialogue.editor = voice_editor.Moments(**place)
    dialogue.add('user', body.words)
    route = Router('', user, body.room, dialogue, None, None, {}, observe_only=True)
    try:
        with prompt_store.observed_reads() as reads:
            await route.targets_now()
            name, target, span, confidence, ms = await route.route()
            events.append(circuit.step(now(), 'router', '振り分け', circuit.ROUTES.get(name, name),
                                       ms=ms, prompts=list(reads)))
        if name in TO_CHAT_DAN:
            with prompt_store.observed_reads() as reads:
                task, _, _ = await prepare_chat_task(body.room, dialogue, route.request_words(), preview=True)
                events.append(circuit.step(now(), 'parallel', '作業担当に渡す直前', task, prompts=list(reads)))
        else:
            events.append(circuit.step(now(), 'lookup' if name == 'lookup' else 'backend',
                          '実行の直前で停止', ' · '.join(filter(None, [circuit.ROUTES.get(name, name), target, span]))))
        return events
    finally:
        await route.close()


class SpokenWords(BaseModel):
    words: str = Field(min_length=1, max_length=800)


def render_speech(words):
    # File output only. Feeding text through stdin also keeps it out of process arguments.
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'speech.wav'
        subprocess.run(['/usr/bin/say', '-v', 'Kyoko', '-o', str(path), '--file-format=WAVE',
                        '--data-format=LEI16@24000', '-f', '-'], input=words.encode(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=True)
        return {'audio': base64.b64encode(path.read_bytes()).decode('ascii')}


@router.post('/speech')
async def speech(body: SpokenWords, user=Depends(owner)):
    try:
        return await asyncio.to_thread(render_speech, body.words)
    except (OSError, subprocess.SubprocessError):
        raise HTTPException(503, '読み上げ音声を作れませんでした。音声ファイルも選べます。')

