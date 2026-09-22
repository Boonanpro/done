"""Inspect actual component previews; never promote model reviews to approval."""
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.enrich_production_library import OUT, read, save

IDS = ('hf-caption-editorial-emphasis', 'hf-caption-weight-shift', 'hf-data-chart',
       'hf-apple-money-count', 'hf-ios26-liquid-glass', 'hf-vfx-liquid-glass',
       'hf-nyc-paris-flight', 'dan-optical-type')
PROMPT = '''Inspect the actual animation, not its file name. This is a strict
production component review, not an encouragement exercise. We want finished,
professionally art-directed components, not bare mechanism demonstrations.
Minimal design can be excellent. Assess readability, spacing, hierarchy,
composition, motion timing, easing, artifacts and whether the sample actually
demonstrates useful content. Identify specific weaknesses with timestamps.
Do not guess how the code works or claim that parameter edits were tested.
Return JSON only in Japanese:
{"accessible":true,"verdict":"polished_candidate|needs_design_work|reject|uncertain",
"strengths":[],"problems":[{"time":number,"issue":string}],
"suitable_for":[],"required_changes":[],"reason":string,
"adaptation_tested":false}.
Even polished_candidate means only a model's review, never final approval.
If inaccessible return accessible:false, verdict:uncertain and reason.
'''


async def main():
    from google import genai
    from app.config import settings
    from app.services.video_analyzer import MODEL, _video_input, _extract_text
    rows = {r['id']: r for r in read(ROOT / 'docs/component-library.json')}
    gate = asyncio.Semaphore(2)

    def inspect(row):
        path = ROOT / 'uploads/reference-library' / (row['id'] + '.mp4')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != row['sha256']: raise ValueError('Preview changed since import')
        client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY,
                             http_options={'timeout': 120000, 'retry_options': {'attempts': 1}})
        asset = None
        try:
            asset = client.files.upload(file=str(path))
            for _ in range(30):
                asset = client.files.get(name=asset.name)
                if asset.state.name == 'ACTIVE': break
                if asset.state.name == 'FAILED': raise RuntimeError('Media processing failed')
                time.sleep(1)
            else: raise TimeoutError('Media processing deadline')
            result = client.interactions.create(model=MODEL, input=[
                _video_input(asset.uri, asset.mime_type, 'agentic'), {'type': 'text', 'text': PROMPT}])
            raw = (_extract_text(result) or '').strip()
            if raw.startswith('```'): raw = raw.split('\n', 1)[1].rsplit('```', 1)[0]
            review = json.loads(raw)
            if review.get('verdict') not in ('polished_candidate', 'needs_design_work', 'reject', 'uncertain'):
                raise ValueError('Invalid verdict')
            review['adaptation_tested'] = False
            usage = getattr(result, 'usage', None)
            return {'id': row['id'], 'preview_sha256': digest, 'model': MODEL, 'review': review,
                    'quality_status': 'model_review_only',
                    'usage': usage.model_dump(mode='json') if hasattr(usage, 'model_dump') else None}
        finally:
            try:
                if asset: client.files.delete(name=asset.name)
            finally: client.close()

    async def one(ident):
        async with gate:
            try: result = await asyncio.to_thread(inspect, rows[ident])
            except Exception as exc: result = {'id': ident, 'error_type': type(exc).__name__}
        save(OUT / 'component-reviews' / (ident + '.json'), result)
        print(json.dumps({'id': ident, 'verdict': result.get('review', {}).get('verdict'),
                          'error': result.get('error_type')}), flush=True)
        return result

    results = await asyncio.gather(*(one(i) for i in IDS))
    save(OUT / 'component-review-report.json', results)


if __name__ == '__main__': asyncio.run(main())
