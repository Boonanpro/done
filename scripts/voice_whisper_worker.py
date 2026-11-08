"""Transcribes the whispered utterances of a call on this Mac's GPU (MLX Whisper), for app/services/voice_whisper.py.

One JSON object per line on stdin: {"id": .., "pcm": base64 float32 mono 16 kHz}. One line back on stdout:
{"id": .., "segments": [{"text", "avg_logprob", "no_speech_prob", "compression_ratio"}], "ms": ..}, or {"id", "error"}.
It runs in its own environment (MLX and its torch would not fit Dan's): /Users/mikihonda/whisper-mlx-venv
  /opt/homebrew/bin/python3.13 -m venv ~/whisper-mlx-venv && ~/whisper-mlx-venv/bin/pip install mlx-whisper
The model (mlx-community/whisper-large-v3-turbo, 1.6 GB) is fetched into the Hugging Face cache on first use.
A 2〜4 s utterance takes about 0.3 s on the M6 (the CPU path took 2.6〜3.3 s, 2026-11-08).
"""
import base64
import json
import os
import sys
import time

import numpy as np

MODEL = os.environ.get('DAN_VOICE_WHISPER_MLX_MODEL', 'mlx-community/whisper-large-v3-turbo')
# Whisper's own fallback: a decoding that loops (compression) or is unsure (log-probability) is redone warmer.
OPTIONS = {'condition_on_previous_text': False, 'without_timestamps': True, 'temperature': (0.0, 0.2, 0.4, 0.6),
           'compression_ratio_threshold': 2.4, 'logprob_threshold': -1.0, 'no_speech_threshold': 0.6}


def main():
    import mlx_whisper
    silence = np.zeros(16000, dtype=np.float32)
    mlx_whisper.transcribe(silence, path_or_hf_repo=MODEL, language='ja')   # loads the weights before the first utterance
    print(json.dumps({'ready': True}), flush=True)
    for line in sys.stdin:
        try:
            ask = json.loads(line)
        except ValueError:
            continue
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
