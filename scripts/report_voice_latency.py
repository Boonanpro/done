"""Report injected-audio latency with explicit sample count and missing replies.

This does not measure handset acoustic latency, route changes, or intelligibility.
Trailing WAV silence is estimated from 20ms RMS windows and reported separately.
"""
import argparse
import json
import math
import statistics
import wave
from pathlib import Path

import numpy as np


def trailing_silence(path):
    with wave.open(str(path), 'rb') as source:
        if source.getsampwidth() != 2:
            raise ValueError('Expected signed 16-bit PCM')
        rate = source.getframerate()
        samples = np.frombuffer(source.readframes(source.getnframes()), dtype='<i2')
        samples = samples.reshape(-1, source.getnchannels()).astype(float) / 32768
    window = max(1, round(rate * .02))
    last = None
    for start in range(0, len(samples), window):
        end = min(len(samples), start + window)
        if np.sqrt(np.mean(samples[start:end] ** 2)) >= .005:
            last = end
    return None if last is None else (len(samples) - last) / rate


def report(path):
    events = json.loads(path.read_text(encoding='utf-8'))
    results = []
    for index, event in enumerate(events):
        if event.get('kind') != 'input_end':
            continue
        audio = None
        for following in events[index + 1:]:
            if following.get('kind') in ('case_end', 'input_start'):
                break
            if following.get('type') == 'audio_start':
                audio = following
                break
        silence = trailing_silence(path.parent / (event['case'] + '.wav'))
        latency = None if audio is None else audio['at'] - event['at']
        results.append({'case': event['case'], 'wav_end_to_reply_s': latency,
                        'trailing_silence_s': silence,
                        'estimated_speech_end_to_reply_s': None if latency is None or silence is None else round(latency + silence, 3)})
    values = sorted(row['estimated_speech_end_to_reply_s'] for row in results if row['estimated_speech_end_to_reply_s'] is not None)
    median = statistics.median(values) if values else None
    p95 = values[math.ceil(.95 * len(values)) - 1] if values else None
    return {'source': str(path), 'scope': 'synthetic desktop WebRTC; not handset acceptance',
            'attempts': len(results), 'measured': len(values), 'missing': len(results)-len(values),
            'median_s': median, 'p95_s': p95,
            'latency_thresholds_met': bool(values) and len(values)==len(results) and median<=1 and p95<=2,
            'trials': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('path', type=Path)
    args = parser.parse_args()
    print(json.dumps(report(args.path), ensure_ascii=False, indent=2))
