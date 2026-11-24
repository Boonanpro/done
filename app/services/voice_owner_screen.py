"""The owner's screen, shared into one ongoing call (owner, 2026-11-24: 「ダンも俺が見ているものを正しく認識しながら「これ」
とかが何を示すかを理解しながら作業できるように」).

The speech model of the call (GPT-Live) takes no pictures. The page captures the screen the owner chose with
getDisplayMedia (components/voice/call-owner-screen.tsx) and sends a frame only when the picture changed, at most one every
1.5 s. Only the latest frames are kept here; whoever decides a request in the call (voice_router: the backend model
reads images) gets the newest one next to the call's transcript, and work started from the call gets it as a
file. This is the "snapshot" way of Google's Real time vision for AI agents: no stream into the speech model.

A whole screen or a window carries the mouse arrow in the picture; a browser tab does not (Chrome draws no cursor into a
tab capture), so the label tells which it is.
"""
import asyncio
import base64
import io
import os
import re
import time
from collections import deque
from pathlib import Path
from uuid import uuid4

from PIL import Image

from app.services import prompt_store

MAX_SIDE = 2000
SURFACES = {'monitor': '画面全体', 'window': 'ウィンドウ', 'browser': 'ブラウザのタブ'}
# Words that point at something on the screen: with a shared screen, these requests go to the model that sees it.
POINTING = re.compile(r'これ|それ|あれ|この|その|あの|ここ|そこ|こっち|画面|映って|見て|見える|見えてる|どこ|どれ|共有')


class Screen:
    def __init__(self, dialogue, send):
        self.dialogue = dialogue
        self.send = send
        self.frames = deque(maxlen=2)
        self.sequence = -1
        self.active = False
        self.surface = ''
        self.lock = asyncio.Lock()
        self.folder = Path.home() / '.dan' / 'voice-screens' / uuid4().hex

    async def receive(self, number, jpeg, surface=''):
        async with self.lock:
            if number <= self.sequence:
                return False
            data = base64.b64decode(jpeg, validate=True)
            with Image.open(io.BytesIO(data)) as im:
                if im.format != 'JPEG' or max(im.size) > MAX_SIDE or min(im.size) < 1:
                    raise ValueError('invalid screen image')
                im.verify()
            if not self.active:
                self.active = True
                await self.send({'type': 'session.instructions.append', 'delegation_id': None,
                                 'content': prompt_store.text('call/screen')})
            self.surface = surface if surface in SURFACES else self.surface
            self.frames.append((number, time.time(), self.surface, data))
            self.sequence = number
            return True

    async def stop(self):
        async with self.lock:
            if not self.active:
                return False
            self.active = False
            self.frames.clear()
            await self.send({'type': 'session.instructions.append', 'delegation_id': None,
                             'content': prompt_store.text('call/screen-ended')})
            return True

    def sharing(self):
        return self.active and bool(self.frames)

    def points(self, words):
        """True when the request may be about what is on the shared screen."""
        return self.sharing() and bool(POINTING.search(words or ''))

    def parts(self):
        """The newest picture of the screen for a model that reads images (older pictures only add cost)."""
        if not self.sharing():
            return []
        number, at, surface, data = self.frames[-1]
        return [{'type': 'input_text', 'text': label(at, surface)},
                {'type': 'input_image', 'image_url': 'data:image/jpeg;base64,' + base64.b64encode(data).decode()}]

    def handoff(self):
        if not self.sharing():
            return ''
        self.folder.mkdir(mode=0o700, exist_ok=True, parents=True)
        number, at, surface, data = self.frames[-1]
        path = self.folder / f'{number}.jpg'
        if not path.exists():
            tmp = self.folder / (uuid4().hex + '.tmp')
            tmp.write_bytes(data)
            os.replace(tmp, path)
        return f'\n{label(at, surface)} {path}'


def label(at, surface):
    ago = max(0, round(time.time() - at))
    kind = SURFACES.get(surface, '画面')
    arrow = ('マウスの矢印は映っていない（タブの共有）' if surface == 'browser'
             else '映っているマウスの矢印が本人の指している所')
    # The words said when the picture last changed are not given: the screen often stays the same while he goes on speaking.
    return f'本人が共有している{kind}の今の様子（最後に変わったのは{ago}秒前・{arrow}）'
