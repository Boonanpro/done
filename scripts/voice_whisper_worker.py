"""Transcribes the whispered utterances of a call on this Mac's GPU (MLX Whisper), for app/services/voice_whisper.py.

One JSON object per line on stdin: {"id": .., "pcm": base64 float32 mono 16 kHz}. One line back on stdout:
{"id": .., "segments": [{"text", "avg_logprob", "no_speech_prob", "compression_ratio"}], "ms": ..}, or {"id", "error"}.
It runs in its own environment (MLX and its torch would not fit Dan's): /Users/mikihonda/whisper-mlx-venv
  /opt/homebrew/bin/python3.13 -m venv ~/whisper-mlx-venv && ~/whisper-mlx-venv/bin/pip install mlx-whisper
The model (mlx-community/whisper-large-v3-turbo, 1.6 GB) is fetched into the Hugging Face cache on first use.
A 2〜4 s utterance takes about 0.3 s on the M6 (the CPU path took 2.6〜3.3 s, 2026-11-08).

It leaves by itself after IDLE seconds without an utterance (default 10 minutes); the server starts it again at the next
call (voice_whisper.warm) and on a request finds it gone and starts it once more. Held for the process's life, each one
kept about 2.4 GB, and a generation of Dan that had a call kept its own: on 2026-11-27 seven drained generations held
about 17 GB this way, the Mac's swap was full and an After Effects render stalled the editor's media for 80 seconds.
"""
import base64
import json
import os
import sys
import threading
import time

import numpy as np

MODEL = os.environ.get('DAN_VOICE_WHISPER_MLX_MODEL', 'mlx-community/whisper-large-v3-turbo')
# Whisper's own fallback: a decoding that loops (compression) or is unsure (log-probability) is redone warmer.
OPTIONS = {'condition_on_previous_text': False, 'without_timestamps': True, 'temperature': (0.0, 0.2, 0.4, 0.6),
           'compression_ratio_threshold': 2.4, 'logprob_threshold': -1.0, 'no_speech_threshold': 0.6}
IDLE = float(os.environ.get('DAN_VOICE_WHISPER_IDLE') or 600)
_last = [time.monotonic()]
_busy = threading.Lock()


def _leave_when_idle(idle=IDLE, every=None):
    every = every or max(0.05, min(30.0, idle / 4))
    while True:
        time.sleep(every)
        with _busy:
            if time.monotonic() - _last[0] >= idle:
                os._exit(0)


def main():
    import mlx_whisper
    silence = np.zeros(16000, dtype=np.float32)
    mlx_whisper.transcribe(silence, path_or_hf_repo=MODEL, language='ja')   # loads the weights before the first utterance
    print(json.dumps({'ready': True}), flush=True)
    _last[0] = time.monotonic()
    if IDLE > 0:
        threading.Thread(target=_leave_when_idle, daemon=True, name='leave-when-idle').start()
    for line in sys.stdin:
        try:
            ask = json.loads(line)
        except ValueError:
            continue
        with _busy:
            answer(ask)
            _last[0] = time.monotonic()


def answer(ask):
    import mlx_whisper
    began = time.monotonic()
    try:
        audio = np.frombuffer(base64.b64decode(ask['pcm']), dtype=np.float32)
        options = dict(OPTIONS, **{k: tuple(v) if isinstance(v, list) else v for k, v in (ask.get('options') or {}).items()})   # a test may try another decoding; calls use OPTIONS
        result = mlx_whisper.transcribe(audio, path_or_hf_repo=options.pop('model', MODEL), language='ja', **options)
        segments = [{'text': s.get('text', ''), 'avg_logprob': s.get('avg_logprob', 0.0),
                     'no_speech_prob': s.get('no_speech_prob', 0.0), 'compression_ratio': s.get('compression_ratio', 1.0)}
                    for s in result.get('segments', [])]
        print(json.dumps({'id': ask.get('id'), 'segments': segments, 'ms': round((time.monotonic() - began) * 1000)},
                         ensure_ascii=False), flush=True)
    except Exception as exc:
        print(json.dumps({'id': ask.get('id'), 'error': f'{type(exc).__name__}: {exc}'[:300]}), flush=True)


if __name__ == '__main__':
    main()
