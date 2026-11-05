"""Telephone audio ↔ GPT-Live, using the same owner conversation/backend as the app.

Only a short-lived local grant made by an authorized outbound operation can open a
stream. Telephone peers never become the owner merely by calling our number.
"""
import asyncio
import base64
import copy
import json
import os
from pathlib import Path
import re
import secrets
import time
from xml.sax.saxutils import escape

import httpx
import websockets

from app.config import settings

ROOT = Path.home() / '.dan' / 'telephone'
VERSION = 'live-telephone-1'
LIVE_URL = 'wss://api.openai.com/v1/live/sessions'


def origin():
    return settings.DAN_PUBLIC_ORIGIN.rstrip('/')


def path(key):
    if not re.fullmatch(r'[a-f0-9]{48}', key):
        raise ValueError('Invalid call reference')
    return ROOT / (key + '.json')


def save(key, value):
    ROOT.mkdir(parents=True, exist_ok=True)
    temporary = path(key).with_suffix('.tmp-' + secrets.token_hex(4))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        json.dump(value, out, ensure_ascii=False)
    os.replace(temporary, path(key))


def read(key):
    return json.loads(path(key).read_text())


def stream_url(key):
    return origin().replace('https://', 'wss://') + '/api/v1/voice/telephone/stream/' + key


def twiml(key):
    return '<Response><Connect><Stream url="' + escape(stream_url(key), {'"': '&quot;'}) + '" /></Connect><Hangup/></Response>'


def signature_ok(url, signature):
    from twilio.request_validator import RequestValidator
    validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
    # Twilio signs its WSS handshake URL; accept HTTPS representation too for
    # deployments whose proxy normalizes the scheme, never a supplied Host.
    return bool(signature) and any(validator.validate(candidate, {}, signature)
        for candidate in (url, url + '/', url.replace('wss://', 'https://'), url.replace('wss://', 'https://') + '/'))


def greeting_for(grant):
    if grant['peer'] == 'owner':
        return '相手が電話に出ました。今すぐ日本語で「ダンです。声は聞こえますか？」と短く名乗って声をかけ、相手の返事を待ってください。'
    return '相手が電話に出ました。今すぐ日本語で本田さんのAIアシスタントのダンだと名乗り、今回の用件を一文で伝え、相手の返事を待ってください。'


async def config_for(grant):
    from app.services.voice_live import session_config
    from app.services.voice_history import room_history
    from app.services.chat_service import ChatService
    chat = ChatService()
    if not await chat.get_room(grant['room_id'], grant['user_id']):
        raise ValueError('Room is not accessible')
    if grant['peer'] == 'owner':
        history = room_history(await chat.get_messages(grant['room_id'], grant['user_id'], limit=96))
        config = session_config(history, room_id=grant['room_id'], user_id=grant['user_id'])
        config['instructions'] += '\n本人が希望した電話での会話です。最初にダンだと短く名乗り、自然に話してください。'
    else:
        from app.services.voice_settings import snapshot
        voice = snapshot()
        config = {'model': voice['model'], 'instructions':
            'あなたは本田さんのAIアシスタントのダンです。電話の相手は本人ではなく問い合わせ先です。'
            '最初にAIの代理人だと名乗り、次の用件だけを自然な日本語で話してください。'
            '聞き取りづらい数字と名前だけ聞き返し、相手の話を聞いて応じてください。'
            '本人確認を求められたら代理人であると伝え、本人が必要な手順を確認してください。'
            '本人になりすましたり、与えられていない情報や結果を作ったりしません。'
            '新しい契約、購入、解約、支払いや送信は約束・実行せず、本人の判断に戻してください。'
            '\n今回の用件と、相手に伝えてよい情報:\n' + grant['purpose'],
            'audio': {'output': {'voice': voice['voice']}},
            'delegation': {'type': 'responses', 'responses': {'model': voice['backend_model'],
                'instructions': '電話の用件の範囲で回答を助けてください。外部操作の権限も本人の私的記録もありません。',
                'tools': []}}}
    config.setdefault('input', []).append({'type': 'message', 'role': 'developer',
        'content': [{'type': 'input_text', 'text': greeting_for(grant)}]})
    config['audio']['format'] = {'type': 'audio/pcmu', 'rate': 8000}
    return config


async def finish_provider(call_sid):
    """Close the PSTN leg as well as the model. Never retry an uncertain mutation."""
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post('https://api.twilio.com/2010-04-01/Accounts/' + settings.TWILIO_ACCOUNT_SID + '/Calls/' + call_sid + '.json',
            auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN), data={'Status': 'completed'})
        response.raise_for_status()


class ControlEvents:
    """Reuse the app's backend loop on a primary socket (which cannot be attached).
    Audio is consumed only by the bridge; transcript/backend events reach the
    existing sideband runner. This adapter never owns/closes the primary socket.
    """
    def __init__(self, live):
        self.live = live
        self.events = asyncio.Queue(maxsize=256)
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def __aiter__(self): return self
    async def __anext__(self):
        event = await self.events.get()
        if event is None: raise StopAsyncIteration
        return event
    async def recv(self): return await self.__anext__()
    async def send(self, raw): await self.live.send(raw)


class Bridge:
    def __init__(self, phone, grant, finish=finish_provider):
        self.phone, self.grant, self.finish = phone, grant, finish
        self.stream_id = None
        self.session_id = None
        self.live = None
        self.output = asyncio.Queue(maxsize=100)  # at most 2 seconds of unsent audio
        self.marks = {}
        self.transcript = []
        self.started = time.monotonic()
        self.sent = self.received = 0
        self.finalized = False
        self.last_spoke = 0
        self.dialogue = None
        self.hangup = None
        self.control = None

    async def run(self, start):
        data = start.get('start', {})
        if (data.get('callSid') != self.grant['call_sid'] or data.get('accountSid') != settings.TWILIO_ACCOUNT_SID
                or data.get('mediaFormat') != {'encoding': 'audio/x-mulaw', 'sampleRate': 8000, 'channels': 1}):
            raise ValueError('Stream does not match authorized call')
        self.stream_id = data['streamSid']
        config = copy.deepcopy(self.grant.get('config')) or await config_for(self.grant)
        backend = config.pop('_backend', None)
        tasks = []
        try:
            async with websockets.connect(LIVE_URL, additional_headers={'Authorization': 'Bearer ' + settings.OPENAI_API_KEY},
                    open_timeout=15, max_size=8*1024*1024) as live:
                self.live = live
                await live.send(json.dumps({'type': 'session.start', 'session': config}, ensure_ascii=False))
                event = json.loads(await asyncio.wait_for(live.recv(), 20))
                if event.get('type') != 'session.started':
                    raise RuntimeError('Live session startup failed: ' + str(event.get('error', {}).get('code', event.get('type'))))
                self.session_id = event['session']['id']
                from app.services import voice_live, voice_sideband
                voice_live.register(self.session_id, self.grant['user_id'], room_id=self.grant['room_id'])
                if self.grant['peer'] == 'owner':
                    self.control = ControlEvents(live)
                    if not voice_sideband.attach(self.session_id, self.grant['user_id'], self.grant['room_id'], settings.OPENAI_API_KEY, own=True, backend=backend, connection=self.control):
                        raise RuntimeError('Telephone backend unavailable')
                else:
                    from app.services.voice_hangup import HangUp
                    self.dialogue = voice_sideband.Dialogue()
                    self.hangup = HangUp(self.grant['user_id'], self.dialogue, lambda *a, **k: None, self.goodbye)
                tasks = [asyncio.create_task(self.from_phone()), asyncio.create_task(self.from_live()), asyncio.create_task(self.to_phone())]
                if self.control:
                    async def backend_liveness():
                        await asyncio.shield(voice_sideband._tasks[self.session_id])
                        if not self.finalized:
                            raise RuntimeError('Telephone backend disconnected')
                    tasks.append(asyncio.create_task(backend_liveness()))
                await live.send(json.dumps({'type': 'session.commentary.append',
                    'event_id': 'telephone-greeting-' + secrets.token_hex(8), 'delegation_id': None,
                    'content': greeting_for(self.grant)}, ensure_ascii=False))
                done, _ = await asyncio.wait(tasks, timeout=self.grant.get('max_seconds', 600), return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
                # A provider stop or timeout must end the model too. Continue
                # receiving the terminal event without competing socket readers.
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                if not self.finalized:
                    await live.send(json.dumps({'type': 'session.close'}))
                    async def drain():
                        async for raw in live:
                            if json.loads(raw).get('type') == 'session.closed':
                                self.finalized = True
                                if self.control:
                                    await self.control.events.put(raw)
                                break
                    try:
                        await asyncio.wait_for(drain(), 10)
                    except (asyncio.TimeoutError, websockets.ConnectionClosed):
                        pass
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self.control:
                try: self.control.events.put_nowait(None)
                except asyncio.QueueFull: pass
            if self.hangup:
                await self.hangup.close()
            if self.session_id:
                from app.services import voice_live
                if voice_live.get_session(self.session_id, self.grant['user_id']):
                    voice_live.close(self.session_id, self.grant['user_id'])
            await self.finish(self.grant['call_sid'])

    async def goodbye(self):
        from app.services.voice_hangup import after_goodbye
        await after_goodbye(lambda: self.last_spoke, lambda: self.live.send(json.dumps({'type': 'session.close'})))

    async def from_phone(self):
        audio_started = time.monotonic()
        while True:
            event = await self.phone.receive_json()
            kind = event.get('event')
            if kind == 'stop':
                return
            if kind == 'mark':
                marker = self.marks.pop(event.get('mark', {}).get('name'), None)
                if marker:
                    marker.set()
            if kind == 'media' and event.get('media', {}).get('track', 'inbound') == 'inbound':
                payload = event['media']['payload']
                size = len(base64.b64decode(payload, validate=True))
                # Twilio may deliver buffered audio in a burst after setup or a
                # network stall. Preserve words, but never exceed Live's real-time
                # input budget (the actual first call failed at 8 seconds/burst).
                delay = audio_started + self.received / 8000 - .08 - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                self.received += size
                await self.live.send(json.dumps({'type': 'session.input_audio.append', 'audio': payload}))

    async def from_live(self):
        async for raw in self.live:
            event = json.loads(raw)
            kind = event.get('type')
            if self.control and kind != 'session.output_audio.delta':
                await self.control.events.put(raw)
            if kind == 'session.output_audio.delta':
                audio = base64.b64decode(event['delta'], validate=True)
                for offset in range(0, len(audio), 160):
                    # Do not accumulate stale seconds of speech if the network stalls.
                    await asyncio.wait_for(self.output.put(audio[offset:offset+160]), 3)
            elif kind in ('session.input_transcript.delta', 'session.output_transcript.delta'):
                role = 'user' if kind == 'session.input_transcript.delta' else 'assistant'
                text = event.get('delta', '')
                if role == 'assistant':
                    self.last_spoke = time.monotonic()
                if self.transcript and self.transcript[-1]['role'] == role:
                    self.transcript[-1]['text'] += text
                else:
                    self.transcript.append({'role': role, 'text': text, 'at': round(time.monotonic()-self.started, 3)})
                if self.dialogue:
                    self.dialogue.add(role, text)
                    if role == 'user':
                        self.hangup.heard()
            elif kind == 'session.closed':
                self.finalized = True
                return
            elif kind == 'error':
                raise RuntimeError('Live error: ' + str(event.get('error', {}).get('code')))

    async def to_phone(self):
        # Keep at most 200 ms in Twilio's playback queue, independently of input.
        n = 0
        pending_marks = []
        while True:
            audio = await self.output.get()
            await self.phone.send_json({'event': 'media', 'streamSid': self.stream_id,
                'media': {'payload': base64.b64encode(audio).decode()}})
            self.sent += len(audio)
            n += 1
            if n % 5 == 0:
                name = str(n)
                marker = self.marks[name] = asyncio.Event()
                await self.phone.send_json({'event': 'mark', 'streamSid': self.stream_id, 'mark': {'name': name}})
                pending_marks.append(marker)
                if len(pending_marks) >= 2:
                    await asyncio.wait_for(pending_marks.pop(0).wait(), 5)
