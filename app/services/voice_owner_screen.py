"""The owner's screen, shared into one ongoing call and looked at only when a request needs it (owner, 2026-11-24/25:
「ダンも俺が見ているものを正しく認識しながら「これ」とかが何を示すかを理解しながら作業できるように」, then
「書き足し続けるのは良くないと思う。…AIがわざわざ無駄な言及するバイアスが働く」「Jevが『今は画面を見た方が良い』と判断したら
その時は見させる」).

- The speech model of the call (GPT-Live) is told nothing about the screen: not that it is shared, not what is on it. It
  hears only the answers to his requests.
- The page keeps the pictures of the shared screen itself, the last 90 s, one each time the picture changes
  (components/voice/call-owner-screen.tsx). Nothing leaves the page while nobody needs to look.
- Jev, which already chooses where each request goes (voice_router), is asked one question more: does this request need
  the screen? Only then the router asks the page (a long poll the page keeps open, /live/backend/screen/.../wait) for the
  pictures that were on the screen while he said the request, gets them within a second, and gives them to the model that
  reads images (Router.luna) or, as files, to the work it starts.
- Which pictures: the words of the request were heard here at known times (heard, the transcript as it arrives). The
  window is from the first word of the request to the last, moved back by LAG (the transcript comes this long after he
  speaks). A screen he opens after he finished speaking is outside it.
"""
import asyncio
import base64
import io
import os
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from PIL import Image

from app.services import prompt_store

MAX_SIDE = 2000
GIVEN = 5             # pictures the page gives for one request at most
LAG = 0.8             # the owner's words reach this server this long after he said them (GPT-Live's streamed transcript)
WAIT_S = 3.0          # how long a request waits for the page's pictures
POLL_S = 20.0         # one long poll of the page
SURFACES = {'monitor': '画面全体', 'window': 'ウィンドウ', 'browser': 'ブラウザのタブ'}
TOKYO = ZoneInfo('Asia/Tokyo')


class Frame:
    __slots__ = ('at', 'surface', 'data', 'words')

    def __init__(self, at, surface, data):
        self.at, self.surface, self.data = at, surface, data
        self.words = ''   # what he said while this picture was on the screen


def decoded(jpeg):
    data = base64.b64decode(jpeg, validate=True)
    with Image.open(io.BytesIO(data)) as im:
        if im.format != 'JPEG' or max(im.size) > MAX_SIDE or min(im.size) < 1:
            raise ValueError('invalid screen image')
        im.verify()
    return data


class Screen:
    def __init__(self, dialogue, clock=time.time):
        self.dialogue = dialogue
        self.clock = clock
        self.active = False
        self.surface = ''
        self.heard_log = []        # (time heard, words) of the owner since the share began
        self.wants = asyncio.Queue()
        self.waiting = {}          # want id -> future of the pictures
        self.folder = Path.home() / '.dan' / 'voice-screens' / uuid4().hex

    # -- the page -------------------------------------------------------------------------------------------------
    def start(self, surface=''):
        if not self.active:
            self.heard_log = []
        self.active = True
        self.surface = surface if surface in SURFACES else self.surface

    def stop(self):
        was, self.active = self.active, False
        for future in self.waiting.values():
            if not future.done(): future.set_result([])
        return was

    async def next_want(self, timeout=POLL_S):
        """The page's long poll: the next window of time it is asked for, or None."""
        try:
            return await asyncio.wait_for(self.wants.get(), timeout)
        except asyncio.TimeoutError:
            return None

    def receive(self, want_id, frames):
        """The page's pictures for one want: [{'ago_ms', 'jpeg', 'surface'}], oldest first."""
        now = self.clock()
        got = [Frame(now - max(0, float(f.get('ago_ms') or 0)) / 1000, str(f.get('surface') or self.surface),
                     decoded(str(f.get('jpeg') or ''))) for f in frames[:GIVEN]]   # a bad picture is refused first
        got.sort(key=lambda f: f.at)
        future = self.waiting.get(want_id)
        if future is None or future.done():
            return False
        future.set_result(got)
        return True

    # -- the call -------------------------------------------------------------------------------------------------
    def sharing(self):
        return self.active

    def heard(self, words):
        """The owner's words as they arrive (Dialogue.add)."""
        if self.active and words:
            self.heard_log.append((self.clock(), words))
            del self.heard_log[:-400]

    def window(self, request):
        """(began, ended): when he said the request, moved back by LAG. The request's words are the last ones heard."""
        now = self.clock()
        need, began = len((request or '').replace(chr(10), '').strip()), None
        for moment, words in reversed(self.heard_log):
            began = moment
            need -= len(words.strip())
            if need <= 0:
                break
        if began is None:   # nothing heard during the share: the screen as it is now
            return now - LAG, now - LAG
        return began - LAG, self.heard_log[-1][0] - LAG

    async def look(self, request, timeout=WAIT_S):
        """The pictures that were on the screen while he said the request, oldest first; [] when the page gives none."""
        if not self.active:
            return []
        began, ended = self.window(request)
        now = self.clock()
        want = {'id': uuid4().hex[:12], 'since_ago_ms': round(max(0, now - began) * 1000),
                'until_ago_ms': round(max(0, now - ended) * 1000)}
        future = asyncio.get_running_loop().create_future()
        self.waiting[want['id']] = future
        await self.wants.put(want)
        try:
            frames = await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            frames = []
        finally:
            self.waiting.pop(want['id'], None)
        for moment, words in self.heard_log:   # what he said while each picture was on the screen
            said = moment - LAG
            if frames and began - .01 <= said <= ended + .01:
                on = next((f for f in reversed(frames) if f.at <= said), frames[0])
                on.words += words
        return frames


def parts(frames):
    """The pictures for a model that reads images (Router.luna)."""
    if not frames:
        return []
    out = [{'type': 'input_text', 'text': prompt_store.text('call/screen-backend')}]
    for index, frame in enumerate(frames, 1):
        out += [{'type': 'input_text', 'text': label(index, frame)},
                {'type': 'input_image', 'image_url': 'data:image/jpeg;base64,' + base64.b64encode(frame.data).decode()}]
    return out


def handoff(frames, folder):
    """The pictures as files, for work started from the call (chat Dan reads them)."""
    if not frames:
        return ''
    folder.mkdir(mode=0o700, exist_ok=True, parents=True)
    rows = []
    for index, frame in enumerate(frames, 1):
        path = folder / f'{int(frame.at * 1000)}.jpg'
        if not path.exists():
            tmp = folder / (uuid4().hex + '.tmp')
            tmp.write_bytes(frame.data)
            os.replace(tmp, path)
        rows.append(f'{label(index, frame)} {path}')
    return '\n\n' + prompt_store.text('call/screen-backend') + '\n' + '\n'.join(rows)


def label(index, frame):
    kind = SURFACES.get(frame.surface, '画面')
    arrow = ('マウスの矢印は映っていない（タブの共有）' if frame.surface == 'browser'
             else '映っているマウスの矢印が本人の指している所')
    since = datetime.fromtimestamp(frame.at, TOKYO).strftime('%H:%M:%S')
    said = frame.words.strip()[-300:]
    return f'共有画面{index}（{since}から映った{kind}・{arrow}）この画面の間に聞こえた本人の言葉「{said or "（なし）"}」'
