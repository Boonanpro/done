"""Replays recordings through the call's whisper listener (app/services/voice_whisper.py) as the sideband receives a call's
input (24 kHz PCM16 in 200 ms chunks), and prints what the speech model would be given. No call is made.

  python scripts/check_voice_whisper.py <wav>... [--truth truth.json]
truth.json: {"<file name>": ["what was said", ...]}; each sentence is scored by its best match among the words handed over
(perfect >= .9, almost >= .7, character similarity after removing punctuation; kanji numerals read as digits).
The recordings of 2026-09-24〜30 are on the owner's PC (D:\\dan-hw\\recordings); they are the owner's voice, so they are not
kept in the repository.
"""
import argparse
import asyncio
import base64
import difflib
import json
import os
import re
import sys
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from app.services import voice_whisper as W  # noqa: E402

W.ANSWER_WAIT_S = 0   # no speech model here to answer

NUM = str.maketrans('〇一二三四五六七八九', '0123456789')


def norm(s):
    return re.sub(r'[\s、。．，,.!?！？「」]', '', s).translate(NUM).replace('金曜日', '金曜')


def score(truth, texts):
    t, hay, best = norm(truth), norm(''.join(texts)), 0.0
    for size in range(max(1, int(len(t) * .7)), int(len(t) * 1.3) + 1):
        for i in range(0, max(1, len(hay) - size + 1)):
            best = max(best, difflib.SequenceMatcher(None, t, hay[i:i + size]).ratio())
    return best


def to24k(x, sr):
    if sr == 24000:
        return x
    if sr == 16000:
        taps = 95
        n = np.arange(taps) - (taps - 1) / 2
        h = np.sinc(n / 3) * np.hamming(taps)
        h /= h.sum()
        up = np.zeros(len(x) * 3, dtype=np.float32)
        up[::3] = x * 3
        return np.convolve(up, h, mode='same')[::2].astype(np.float32)
    raise SystemExit(f'{sr} Hz: only 16 and 24 kHz recordings')


async def replay(path):
    x, sr = sf.read(path, dtype='float32')
    x = to24k(x if x.ndim == 1 else x[:, 0], sr)
    clock = {'t': 1000.0}
    given, log = [], []
    async def send(event): given.append((clock['t'] - 1000.0, event))
    listener = W.Listener(send, lambda phase, **f: log.append((phase, f)), clock=lambda: clock['t'])
    pcm = (np.clip(x, -1, 1) * 32767).astype('<i2').tobytes()
    began = time.monotonic()
    for i in range(0, len(pcm), 9600):
        chunk = pcm[i:i + 9600]
        clock['t'] += len(chunk) / 2 / W.RATE
        listener.audio(base64.b64encode(chunk).decode())
        await asyncio.sleep(0)
    listener.audio(base64.b64encode(np.zeros(W.RATE, dtype='<i2').tobytes()).decode())
    while listener.tasks:
        await asyncio.gather(*list(listener.tasks), return_exceptions=True)
    given = [(at, e) for at, e in given if e['type'] == 'session.instructions.append']
    words = [e['content'].split('：「', 1)[1].rstrip('」') for _, e in given]
    ms = [f['transcribe_ms'] for p, f in log if 'transcribe_ms' in f]
    return words, given, log, ms, time.monotonic() - began


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('wav', nargs='+')
    ap.add_argument('--truth')
    args = ap.parse_args()
    truth = json.load(open(args.truth, encoding='utf-8')) if args.truth else {}
    totals = [0, 0, 0]
    for path in args.wav:
        words, given, log, ms, took = asyncio.run(replay(path))
        skipped = {}
        for phase, f in log:
            if phase == 'whisper_skipped': skipped[f['why']] = skipped.get(f['why'], 0) + 1
        print(f'== {os.path.basename(path)}  handed over {len(words)}, skipped {skipped}, transcription median '
              f'{int(np.median(ms)) if ms else 0} ms')
        for at, e in given:
            print(f'   {at:6.1f}s  {e["content"].split("：「", 1)[1].rstrip("」")}')
        sentences = truth.get(os.path.basename(path), [])
        for s in sentences:
            v = score(s, words)
            mark = 'perfect' if v >= .9 else 'almost' if v >= .7 else 'missed'
            totals[0] += v >= .9; totals[1] += .7 <= v < .9; totals[2] += 1
            print(f'   [{mark:7s} {v:.2f}] {s}')
    if totals[2]:
        print(f'TOTAL perfect {totals[0]}, almost {totals[1]}, of {totals[2]}')


if __name__ == '__main__':
    main()
