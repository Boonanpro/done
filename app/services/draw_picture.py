"""Dan draws a picture in the chat (2026-11-16, the owner: show things so they are understood at a glance).

When there is no real photo or screen to show (a scene that has not happened yet, how something would look), Dan
draws the scene with OpenAI's most precise image model and keeps it as Dan's own file (/api/v1/files/...), so
attach_image, Image, Item, Card and a Compare cell can show it. A reference picture (a real photo, a screenshot)
makes the model draw from it instead of from words alone.

The owner asked for the more precise model (「2.5とか2.6とかより高精度にやれるほう」). gpt-image-2.6-sunburst is the
precision one of the 2.6 pair (flare is the fast one) at the same price: image output $30 / 1M tokens. A 1536x1024
medium picture measured 33 s and about $0.034 (2026-11-16).
"""
import asyncio
import base64
import os
import time
import uuid
from pathlib import Path

import httpx

MODEL = os.environ.get('DAN_DRAW_MODEL', 'gpt-image-2.6-sunburst')
SIZES = {'wide': '1536x1024', 'square': '1024x1024', 'tall': '1024x1536'}
USD_PER_M = {'text_in': 5.0, 'image_in': 8.0, 'image_out': 30.0}
TIMEOUT_S = 200   # the MCP layer gives a tool 240 s
REF_MAX = 4
REF_BYTES_MAX = 20 * 1024 * 1024

TOOL = {
    'name': 'draw_picture',
    'description': ('場面や物の絵を描いて、ダンのファイル（/api/v1/files/…）として返す。本物の写真や画面が無い話（これから起きる場面・'
                    'こうなるという見た目・説明したい状況）を見せる時に使う。返った url は attach_image・Image・Item・Card・Compare のセルに使える。'
                    'reference に本物の写真や画面を渡すと、それを元に描く。1枚30〜60秒・約5円。'),
    'input_schema': {'type': 'object', 'properties': {
        'prompt': {'type': 'string', 'maxLength': 4000, 'description': '描く物（誰が・どこで・何をしている・画面に何が出ている・雰囲気）。絵に入れる文字は「」で書く'},
        'shape': {'type': 'string', 'enum': ['wide', 'square', 'tall'], 'description': '横長（既定）・正方形・縦長'},
        'quality': {'type': 'string', 'enum': ['medium', 'high'], 'description': '既定 medium。細かい文字が多い絵は high'},
        'reference': {'type': 'array', 'maxItems': REF_MAX, 'items': {'type': 'string'},
                      'description': '元にする画像（/api/v1/files/… か、この機械のファイルの絶対パス）'},
    }, 'required': ['prompt'], 'additionalProperties': False},
}


def _api_key() -> str:
    key = os.environ.get('OPENAI_API_KEY', '')
    if not key:
        try:
            from app.config import settings
            key = settings.OPENAI_API_KEY or ''
        except Exception:
            key = ''
    return key.strip().strip('"')


def _reference_bytes(src: str) -> tuple[bytes, str] | None:
    """A reference given as /api/v1/files/<name> (or a URL ending in it) or an absolute path on this machine."""
    from app.api.file_routes import UPLOAD_DIR
    s = str(src or '').strip()
    if '/api/v1/files/' in s:
        path = UPLOAD_DIR / Path(s.split('/api/v1/files/', 1)[1].split('?', 1)[0]).name
    else:
        path = Path(s).expanduser()
    if not path.is_absolute() or not path.is_file() or path.stat().st_size > REF_BYTES_MAX:
        return None
    return path.read_bytes(), path.name


def _save(png: bytes) -> str:
    from app.api.file_routes import UPLOAD_DIR
    name = f'draw-{uuid.uuid4().hex}.png'
    (UPLOAD_DIR / name).write_bytes(png)
    return '/api/v1/files/' + name


def _preview(png: bytes) -> str | None:
    """A small copy for Dan to look at (the tool result carries it as an image)."""
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(png))
        im.thumbnail((768, 768))
        buf = io.BytesIO()
        im.convert('RGB').save(buf, 'PNG', optimize=True)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


async def draw(prompt: str, shape: str = 'wide', quality: str = 'medium', reference=None) -> dict:
    prompt = str(prompt or '').strip()
    if not prompt:
        return {'success': False, 'error': 'prompt が空'}
    key = _api_key()
    if not key:
        return {'success': False, 'error': 'OpenAI の鍵が無い'}
    size = SIZES.get(shape or 'wide', SIZES['wide'])
    quality = quality if quality in ('medium', 'high') else 'medium'
    refs, missing = [], []
    for src in (reference or [])[:REF_MAX]:
        got = _reference_bytes(src)
        (refs.append(got) if got else missing.append(str(src)[:120]))
    if missing and not refs:
        return {'success': False, 'error': '元にする画像を読めなかった: ' + '、'.join(missing)}
    headers = {'Authorization': f'Bearer {key}'}
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        if refs:
            files = [('image[]', (name, data, 'image/png' if name.lower().endswith('.png') else 'image/jpeg')) for data, name in refs]
            r = await client.post('https://api.openai.com/v1/images/edits', headers=headers, files=files,
                                  data={'model': MODEL, 'prompt': prompt, 'size': size, 'quality': quality})
        else:
            r = await client.post('https://api.openai.com/v1/images/generations', headers=headers,
                                  json={'model': MODEL, 'prompt': prompt, 'size': size, 'quality': quality})
    seconds = round(time.monotonic() - started, 1)
    try:
        body = r.json()
    except Exception:
        body = {}
    if r.status_code != 200 or not body.get('data'):
        err = (body.get('error') or {}).get('message') if isinstance(body.get('error'), dict) else None
        return {'success': False, 'error': f'描けなかった（{r.status_code}）: {(err or r.text)[:300]}'}
    png = base64.b64decode(body['data'][0]['b64_json'])
    url = _save(png)
    usage = body.get('usage') or {}
    detail = usage.get('input_tokens_details') or {}
    cost = (detail.get('text_tokens', 0) / 1e6 * USD_PER_M['text_in'] + detail.get('image_tokens', 0) / 1e6 * USD_PER_M['image_in']
            + usage.get('output_tokens', 0) / 1e6 * USD_PER_M['image_out'])
    out = {'success': True, 'url': url, 'size': size, 'quality': quality, 'model': MODEL, 'seconds': seconds,
           'cost_usd_approx': round(cost, 4), 'note': '見せる時は attach_image か部品の image に url を使う'}
    preview = _preview(png)
    if preview:
        out['screenshot_base64'] = preview   # Dan sees what was drawn before showing it
    if missing:
        out['reference_note'] = '読めなかった元の画像（使っていない）: ' + '、'.join(missing)
    return out


async def tool(params: dict) -> dict:
    try:
        return await asyncio.wait_for(draw(params.get('prompt', ''), params.get('shape') or 'wide', params.get('quality') or 'medium',
                                           params.get('reference') or []), TIMEOUT_S + 15)
    except asyncio.TimeoutError:
        return {'success': False, 'error': f'{TIMEOUT_S}秒で描けなかった'}
    except httpx.HTTPError as exc:
        return {'success': False, 'error': f'OpenAI につながらなかった: {type(exc).__name__}'}
