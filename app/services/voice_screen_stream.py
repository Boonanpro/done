"""Private live screen frames, independent of the agent's observe/act cadence.

Only the latest JPEG is retained. A random stream belongs to one room and one
browser page; stale producers cannot overwrite a later page's stream.
"""
import asyncio
import base64
import os
import re
import time
import uuid
from .voice_screen_media import directory

MAX_FRAME = 4 * 1024 * 1024


def frame_path(room, key):
    if not room or not re.fullmatch(r'[a-f0-9]{32}', key):
        raise ValueError('Invalid stream')
    return directory(room) / (key + '.live.jpg')


def write_frame(room, key, data):
    if not data or len(data) > MAX_FRAME:
        return
    path = frame_path(room, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_bytes(data)
    os.replace(temp, path)


def url(room, key):
    from .voice_calls import _name
    return '/api/v1/voicelog/stage/' + _name(room) + '/image/' + key + '.mjpeg'


async def frames(room, key, disconnected):
    path = frame_path(room, key)
    last = None
    lease = path.with_suffix('.watch')
    while not await disconnected():
        lease.touch()
        try:
            stat = path.stat()
            if time.time() - stat.st_mtime > 30:
                break
            if stat.st_mtime_ns != last:
                data = path.read_bytes()
                if len(data) <= MAX_FRAME:
                    last = stat.st_mtime_ns
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' +
                           str(len(data)).encode() + b'\r\n\r\n' + data + b'\r\n')
        except FileNotFoundError:
            break
        await asyncio.sleep(1 / 20)


class BrowserStream:
    def __init__(self, room):
        self.room, self.key = room, uuid.uuid4().hex
        self.page = self.cdp = None
        self.last = 0.0
        self.task = None
        self.data = None
        self.closed = False
        self.started = time.time()

    async def start(self, page):
        self.page = page
        self.cdp = await page.context.new_cdp_session(page)
        self.cdp.on('Page.screencastFrame', self.on_frame)
        await self.cdp.send('Page.startScreencast', {'format':'jpeg','quality':75,'maxWidth':1440,'maxHeight':1200,'everyNthFrame':1})
        self.task = asyncio.create_task(self.heartbeat())
        return self

    async def on_frame(self, event):
        try:
            now = time.monotonic()
            if not self.closed and now-self.last >= 1/20:
                self.data = base64.b64decode(event['data'], validate=True)
                write_frame(self.room, self.key, self.data)
                self.last = now
        finally:
            try:
                await self.cdp.send('Page.screencastFrameAck', {'sessionId':event['sessionId']})
            except Exception:
                pass

    async def heartbeat(self):
        # Static pages generate no new frames. Keep the current frame available,
        # but stop within 30 s of a dead producer so the UI cannot look live forever.
        while not self.closed:
            await asyncio.sleep(5)
            lease = frame_path(self.room,self.key).with_suffix('.watch')
            try: viewed = lease.stat().st_mtime
            except FileNotFoundError: viewed = self.started
            if self.page.is_closed() or time.time()-viewed > 30:
                await self.close();return
            if self.data:
                write_frame(self.room, self.key, self.data)

    async def close(self):
        self.closed = True
        if self.task and self.task is not asyncio.current_task():
            self.task.cancel()
        if self.cdp:
            try:
                await self.cdp.send('Page.stopScreencast')
                await self.cdp.detach()
            except Exception:
                pass
        frame_path(self.room, self.key).unlink(missing_ok=True)
        frame_path(self.room, self.key).with_suffix('.watch').unlink(missing_ok=True)


async def follow_browser(state, page, fit_viewport=False):
    """Called inside the existing browser executor; never launch another browser."""
    if not (os.environ.get('DAN_TOOL_HOST') == '1' or os.environ.get('DAN_COMMAND_JOB_ID')) or not os.environ.get('DAN_SESSION_ID'):
        return
    if fit_viewport:
        from .voice_viewport import fit
        try:
            await fit(page, os.environ['DAN_SESSION_ID'])
        except Exception:
            pass  # Display sizing must not fail or repeat the user's operation.
    previous = state.get('voice_stream')
    if previous and previous.page is page and not previous.closed:
        return
    if previous:
        await previous.close()
    state['voice_stream'] = None
    try:
        stream = await BrowserStream(os.environ['DAN_SESSION_ID']).start(page)
        state['voice_stream'] = stream
    except Exception:
        return  # An unavailable video path must not repeat or fail a user operation.


def current_url(state):
    stream = state.get('voice_stream')
    if stream and not stream.closed and frame_path(stream.room,stream.key).is_file():
        return url(stream.room,stream.key)
    return ''
