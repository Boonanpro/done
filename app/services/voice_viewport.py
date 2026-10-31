"""A call's display size, scoped to its authenticated session and short client lease."""
import json
import os
import time
import uuid
from app.services.voice_calls import ROOT, _name


def path(room):
    return ROOT / (_name(room) + '.viewport.json')


def read(room):
    try:
        return json.loads(path(room).read_text())
    except (OSError, ValueError):
        return {}


def accept(room, state, body):
    if not state.get('active') or body.get('session_id') != state.get('session_id'):
        return False
    width, height = body.get('width'), body.get('height')
    if type(width) is not int or type(height) is not int or not (240 <= width <= 2560 and 240 <= height <= 2560):
        return False
    now = time.time()
    old = read(room)
    if (old.get('session_id') == body['session_id'] and old.get('client_id') != body.get('client_id')
            and now - old.get('received_at', 0) < 8):
        return False
    value = {**body, 'received_at': now}
    ROOT.mkdir(parents=True, exist_ok=True)
    tmp = path(room).with_suffix('.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(value)); os.replace(tmp, path(room))
    return True


def current(room):
    from app.services.voice_stage import read_state
    state = read_state(room)
    value = read(room)
    if (not state.get('active') or value.get('session_id') != state.get('session_id')
            or time.time() - value.get('received_at', 0) > 12):
        return None
    return {k: value[k] for k in ('width', 'height')}


async def fit(page, room):
    size = current(room)
    if size and page.viewport_size != size:
        await page.set_viewport_size(size)
