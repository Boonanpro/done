"""Pictures made for the call's stage: generated while the owner watches, redone on their words (voice_stage, 2026-10-27:
"画像や映像を編集したり生成する時とかも目の前で指示が反映されていくのも最高").

One generation is one request to OpenAI's image endpoint (the same route as scripts/gpt_image.py, Dan's usual image
route): a new picture from a prompt, or an edit of the picture on the stage with the owner's instruction (the previous
picture goes with the request, so 「もっと明るく」 changes that picture instead of drawing another). The stage asks for
the smallest size and the low quality: a few yen a picture and 10-20 s, measured on 2026-10-27 (high quality takes a
minute and costs ten times as much, which is not a conversation). DAN_VOICE_STAGE_IMAGE_MODEL / _SIZE / _QUALITY change
that. The result is one of Dan's files (/api/v1/files/…), the way every picture on the stage is."""
import asyncio
import base64
import logging
import os
import time

logger = logging.getLogger(__name__)

MODEL = os.environ.get('DAN_VOICE_STAGE_IMAGE_MODEL', 'gpt-image-2.5-sunburst')
SIZE = os.environ.get('DAN_VOICE_STAGE_IMAGE_SIZE', '1024x1024')
QUALITY = os.environ.get('DAN_VOICE_STAGE_IMAGE_QUALITY', 'low')
TIMEOUT_S = 120.0
USD_PER_M = {'text_in': 5.0, 'image_in': 8.0, 'image_out': 30.0}   # the published rates (scripts/gpt_image.py); the bill is OpenAI's


def _api_key():
    from app.services import inbox
    inbox._env()
    from app.config import settings
    key = settings.OPENAI_API_KEY or os.environ.get('OPENAI_API_KEY', '')
    if not key: raise RuntimeError('OPENAI_API_KEY is not set')
    return key


def _cost(body):
    usage = (body or {}).get('usage') or {}
    detail = usage.get('input_tokens_details') or {}
    return round(detail.get('text_tokens', 0) / 1e6 * USD_PER_M['text_in'] + detail.get('image_tokens', 0) / 1e6 * USD_PER_M['image_in']
                 + usage.get('output_tokens', 0) / 1e6 * USD_PER_M['image_out'], 4)


def _request(prompt, reference=None):
    """The HTTP request, in a thread: PNG bytes and the approximate cost."""
    import httpx
    headers = {'Authorization': 'Bearer ' + _api_key()}
    with httpx.Client(timeout=TIMEOUT_S) as client:
        if reference:
            r = client.post('https://api.openai.com/v1/images/edits', headers=headers,
                            data={'model': MODEL, 'prompt': prompt, 'size': SIZE, 'quality': QUALITY},
                            files=[('image[]', ('reference.png', reference, 'image/png'))])
        else:
            r = client.post('https://api.openai.com/v1/images/generations', headers=headers,
                            json={'model': MODEL, 'prompt': prompt, 'size': SIZE, 'quality': QUALITY})
    if r.status_code != 200:
        raise RuntimeError(f'image API {r.status_code}: {r.text[:200]}')
    body = r.json()
    data = (body.get('data') or [{}])[0]
    if not data.get('b64_json'): raise RuntimeError('image API returned no image')
    return base64.b64decode(data['b64_json']), _cost(body)


def _save(png, room_id):
    from app.api.file_routes import UPLOAD_DIR
    from app.services.voice_calls import _name
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f'stage-pic-{_name(room_id)[:24]}-{int(time.time() * 1000)}.png'
    (UPLOAD_DIR / name).write_bytes(png)
    return '/api/v1/files/' + name


def _read(url):
    """The bytes of one of Dan's files (the picture on the stage) for an edit; None for anything else."""
    from app.api.file_routes import UPLOAD_DIR
    name = str(url or '').rsplit('/', 1)[-1]
    if not str(url or '').startswith('/api/v1/files/') or not name: return None
    path = (UPLOAD_DIR / name).resolve()
    if not path.is_relative_to(UPLOAD_DIR.resolve()) or not path.is_file(): return None
    return path.read_bytes()


async def make(prompt, room_id, reference_url=None):
    """A picture from the prompt, or the referenced picture edited by it: (url, seconds, cost_usd)."""
    started = time.monotonic()
    reference = await asyncio.to_thread(_read, reference_url) if reference_url else None
    png, cost = await asyncio.to_thread(_request, prompt, reference)
    url = await asyncio.to_thread(_save, png, room_id)
    return url, round(time.monotonic() - started, 1), cost
