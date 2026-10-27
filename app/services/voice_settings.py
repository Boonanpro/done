"""Read one immutable settings snapshot per new call; existing calls keep theirs."""
import json
import os
from pathlib import Path
import re

PATH = Path.home() / '.dan' / 'voice-settings.json'
DEFAULTS = {'model': 'gpt-live-1', 'backend_model': 'gpt-6.1-terra',
            'reasoning': 'medium', 'voice': 'shida'}
ENV = {'model': 'DAN_VOICE_LIVE_MODEL', 'backend_model': 'DAN_VOICE_BACKEND_MODEL',
       'reasoning': 'DAN_VOICE_BACKEND_REASONING'}


def validate(values):
    if not isinstance(values, dict) or set(values) - set(DEFAULTS):
        raise ValueError('Unknown voice setting')
    for key, value in values.items():
        if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,80}', value):
            raise ValueError('Invalid voice setting: ' + key)
        if key == 'reasoning' and value not in {'none', 'minimal', 'low', 'medium', 'high', 'xhigh'}:
            raise ValueError('Invalid reasoning level')
    return values


def snapshot():
    values = {**DEFAULTS, **{k: os.environ[v] for k, v in ENV.items() if v in os.environ}}
    # Invalid configuration fails call creation explicitly; never silently uses
    # an unintended provider or model. Atomic replace prevents partial reads.
    if PATH.exists():
        values.update(validate(json.loads(PATH.read_text(encoding='utf-8'))))
    return validate(values)


def save(values):
    values = validate(values)
    PATH.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    fd, temporary = tempfile.mkstemp(dir=PATH.parent, prefix='.voice-settings-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(values, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, PATH)
    finally:
        Path(temporary).unlink(missing_ok=True)
