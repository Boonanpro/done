"""Google-direct video generation with durable receipts and reusable outputs."""
import base64
import hashlib
import json
import mimetypes
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

MODEL = 'gemini-omni-1.1-flash'
ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/interactions'


def probe(path):
    from app.services.timeline_captions import _ffmpeg
    binary = Path(_ffmpeg()).with_name('ffprobe.exe' if __import__('os').name == 'nt' else 'ffprobe')
    result = subprocess.run([str(binary), '-v', 'error', '-show_entries',
        'format=duration:stream=codec_type,width,height', '-of', 'json', str(path)],
        capture_output=True, text=True, timeout=30,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=True)
    data = json.loads(result.stdout)
    video = next(s for s in data['streams'] if s['codec_type'] == 'video')
    duration = float(data['format']['duration'])
    if duration <= 0:
        raise ValueError('Video has no duration')
    return {'duration': duration, 'width': video['width'], 'height': video['height']}


def _metadata(value):
    if isinstance(value, list):
        return [_metadata(v) for v in value]
    if isinstance(value, dict):
        return {k: '[media omitted]' if k == 'data' else _metadata(v) for k, v in value.items()}
    return value


def generate(folder, prompt, aspect='16:9', duration=5, reference_path='',
             reference_mode='style', resolution='720p'):
    from app.config import settings
    if not prompt.strip():
        raise ValueError('prompt required')
    if aspect not in {'16:9', '9:16'} or resolution not in {'360p', '720p', '1080p', '4k'}:
        raise ValueError('Unsupported Google output format')
    if reference_mode not in {'style', 'edit'} or not 0 < duration <= 10:
        raise ValueError('Use style or edit and a requested duration of 0–10 seconds')
    if not settings.GOOGLE_GEMINI_API_KEY:
        raise ValueError('Google Gemini API key is not configured')
    inputs, prefix, source_hash = [], '', None
    if reference_path:
        source = Path(reference_path).resolve(strict=True)
        mime = mimetypes.guess_type(source.name)[0] or ''
        if not mime.startswith(('video/', 'image/')):
            raise ValueError('Reference must be a video or image')
        if source.stat().st_size > 50 * 1024 * 1024:
            raise ValueError('Reference exceeds 50 MB; prepare a smaller API upload copy')
        kind = mime.split('/')[0]
        if kind == 'video':
            maximum = 3 if reference_mode == 'style' else 10
            if probe(source)['duration'] > maximum + .02:
                raise ValueError(f'{reference_mode} video must be at most {maximum}s; choose a reference excerpt first')
        raw = source.read_bytes()
        source_hash = hashlib.sha256(raw).hexdigest()
        inputs.append({'type': kind, 'mime_type': mime, 'data': base64.b64encode(raw).decode()})
        label = kind.upper()
        prefix = (f'[# References <{label}_REF_0>@Reference1] Use Reference1 as a style reference for the new subject. '
                  if reference_mode == 'style' else f'[# Sources <{label}_0>@Source1] Edit Source1 as requested. ')
    text = prefix + f'Requested length: {duration:g} seconds. ' + prompt
    spec = {'provider': 'google', 'model': MODEL, 'prompt': text, 'source_sha256': source_hash,
            'reference_mode': reference_mode, 'aspect_ratio': aspect, 'resolution': resolution,
            'requested_duration': duration}
    key = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:24]
    target = Path(folder) / 'google-video' / key
    target.mkdir(parents=True, exist_ok=True)
    output, receipt = target / 'output.mp4', target / 'receipt.json'
    if output.exists() and receipt.exists():
        saved = json.loads(receipt.read_text(encoding='utf-8'))
        if saved.get('state') == 'completed':
            return {'path': str(output), 'metadata': saved['metadata'], 'reused': True}
    # An exclusive receipt also protects concurrent calls. Uncertain requests are
    # retained for inspection instead of silently issuing a second paid request.
    with receipt.open('x', encoding='utf-8') as f:
        json.dump({'state': 'requesting', 'request': spec}, f, ensure_ascii=False)
    inputs.append({'type': 'text', 'text': text})
    request = {'model': MODEL, 'input': inputs,
               'response_format': {'type': 'video', 'aspect_ratio': aspect, 'resolution': resolution},
               'background': False, 'store': False, 'stream': False}
    started = time.monotonic()
    saved = {'state': 'uncertain', 'request': spec}
    try:
        response = httpx.post(ENDPOINT, headers={'x-goog-api-key': settings.GOOGLE_GEMINI_API_KEY},
                              json=request, timeout=600)
        saved['http_status'] = response.status_code
        response.raise_for_status()
        data = response.json()
        saved['response'] = _metadata(data)
        blocks = [c for s in data.get('steps', []) if s.get('type') == 'model_output'
                  for c in s.get('content', []) if c.get('type') == 'video']
        if len(blocks) != 1:
            raise ValueError('Google did not return exactly one video; inspect receipt before retrying')
        media = blocks[0]
        if media.get('data'):
            raw = base64.b64decode(media['data'], validate=True)
        else:
            uri = media.get('uri', '')
            parsed = urlparse(uri)
            if parsed.scheme != 'https' or parsed.hostname != 'generativelanguage.googleapis.com':
                raise ValueError('Unexpected Google download URL')
            download = httpx.get(uri, headers={'x-goog-api-key': settings.GOOGLE_GEMINI_API_KEY}, timeout=120)
            download.raise_for_status()
            raw = download.content
        output.write_bytes(raw)
        meta = {**spec, **probe(output), 'generator': 'google', 'usage': data.get('usage', {}),
                'reference_path': str(Path(reference_path).resolve()) if reference_path else None,
                'elapsed_seconds': round(time.monotonic() - started, 2), 'receipt': str(receipt)}
        saved.update(state='completed', metadata=meta)
        return {'path': str(output), 'metadata': meta, 'reused': False}
    finally:
        temp = receipt.with_suffix('.tmp')
        temp.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(receipt)
