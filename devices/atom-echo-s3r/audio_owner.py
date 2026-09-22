"""Persist which host may open Atom TCP; losing a phone connection never wakes the PC."""
import json
from pathlib import Path


class AudioOwner:
    def __init__(self, path):
        self.path = Path(path)
        self.mode = 'pc'
        if self.path.exists():
            value = json.loads(self.path.read_text(encoding='utf-8'))
            if value.get('mode') not in ('pc', 'phone'):
                raise ValueError('Invalid Atom audio owner')
            self.mode = value['mode']

    def select(self, mode, *, busy):
        if mode not in ('pc', 'phone'):
            raise ValueError('Invalid Atom audio owner')
        if mode == self.mode:
            return
        if busy:
            raise RuntimeError('An active voice connection cannot be transferred')
        temporary = self.path.with_suffix('.new')
        temporary.write_text(json.dumps({'mode': mode}) + '\n', encoding='utf-8')
        temporary.replace(self.path)
        self.mode = mode
