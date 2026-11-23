"""The last few states of the board shared into one ongoing conversation."""
import asyncio
import base64
import io
import os
from collections import deque
from pathlib import Path
from uuid import uuid4

from PIL import Image

from app.services import prompt_store


class Sketch:
    def __init__(self, dialogue, send):
        self.dialogue = dialogue
        self.send = send
        self.frames = deque(maxlen=6)
        self.sequence = -1
        self.lock = asyncio.Lock()
        self.folder = Path.home() / '.dan' / 'voice-sketches' / uuid4().hex

    async def receive(self, number, jpeg):
        async with self.lock:
            if number <= self.sequence:
                return False
            data = base64.b64decode(jpeg, validate=True)
            with Image.open(io.BytesIO(data)) as im:
                if im.format != 'JPEG' or max(im.size) > 1600 or min(im.size) < 1:
                    raise ValueError('invalid board image')
                im.verify()
            if not self.frames:
                await self.send({'type': 'session.instructions.append', 'delegation_id': None,
                                 'content': prompt_store.text('call/sketch')})
            # Snapshot the words received by this moment. Subsequent transcript deltas mutate history in place.
            words = next((t['text'][-180:] for t in reversed(self.dialogue.history) if t['role'] == 'user'), '')
            if self.frames and self.frames[-1][1] == words:
                self.frames.pop()  # many strokes during the same pause are one state
            self.frames.append((number, words, data))
            self.sequence = number
            return True

    def parts(self):
        parts = []
        for number, words, data in self.frames:
            parts.extend([{'type': 'input_text', 'text': label(number, words)},
                          {'type': 'input_image', 'image_url': 'data:image/jpeg;base64,' + base64.b64encode(data).decode()}])
        return parts

    def handoff(self):
        if not self.frames:
            return ''
        self.folder.mkdir(mode=0o700, exist_ok=True, parents=True)
        rows = []
        for number, words, data in self.frames:
            path = self.folder / f'{number}.jpg'
            if not path.exists():
                tmp = self.folder / (uuid4().hex + '.tmp')
                tmp.write_bytes(data)
                os.replace(tmp, path)
            rows.append(f'{label(number, words)} {path}')
        return '\n' + '\n'.join(rows)


def label(number, words):
    return f'手描きの画面 {number}（この時点で届いた直近の発言「{words}」）'
