"""A real gpt-live-1 call with a spoken owner, to time web searches with and without the early search (voice_prefetch).

The owner's voice is a WAV played as Chromium's fake microphone (macOS `say -v Kyoko`); the call is created here and this
process runs the real sideband (voice_sideband._run, own=True), so no Dan server port is involved and nothing reaches a
room (test user, no room). Words are kept only in this script's output file.

Usage: DAN_VOICE_PREFETCH=1|0 python scripts/check_voice_prefetch_call.py <owner.wav> <schedule.json> <out.json>
schedule.json: {"schedule": [{"q", "start", "end"} seconds into the WAV], "total": seconds}
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings
from app.services import voice_sideband as S
from app.services.voice_live import session_config

TEST_USER = '1f53bb2a-51da-4a2a-be9e-4c5a0f74d5f1'   # dan-test@example.com
log = []


def mark(_kind, **fields):
    log.append({'t': time.monotonic(), 'kind': _kind, **fields})


_note = S.note
def note(session_id, room_id, phase, **fields):
    mark('note', phase=phase, **fields)
    _note(session_id, room_id, phase, **fields)
S.note = note

_add = S.Dialogue.add
def add(self, role, delta):
    if delta: mark('delta', role=role, text=delta)
    _add(self, role, delta)
S.Dialogue.add = add

async def no_call_log(*args, **kwargs): pass
S.call_log = no_call_log

PAGE = '''async () => {
  const stream = await navigator.mediaDevices.getUserMedia({audio: true});
  window.pc = new RTCPeerConnection();
  stream.getTracks().forEach(t => pc.addTrack(t, stream));
  window.dc = pc.createDataChannel('oai-events');
  dc.onmessage = e => { const m = JSON.parse(e.data); if (m.type === 'error' || m.type === 'session.started') dcEvent(m.type, JSON.stringify(m).slice(0, 300)); };
  await pc.setLocalDescription(await pc.createOffer());
  if (pc.iceGatheringState !== 'complete') await new Promise(r => { pc.addEventListener('icegatheringstatechange', () => { if (pc.iceGatheringState === 'complete') r(); }); });
  return pc.localDescription.sdp;
}'''


async def main(wav, schedule_path, out_path):
    plan = json.loads(Path(schedule_path).read_text())
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
                                                f'--use-file-for-fake-audio-capture={wav}%noloop', '--autoplay-policy=no-user-gesture-required'])
        page = await browser.new_page()
        await page.expose_function('dcEvent', lambda kind, body: mark('dc', type=kind, body=body))
        await page.route('http://localhost/**', lambda route: route.fulfill(body='<html></html>', content_type='text/html'))
        await page.goto('http://localhost/call')   # a secure origin, where getUserMedia exists
        sdp = await page.evaluate(PAGE)
        t0 = time.monotonic()   # the fake microphone starts with getUserMedia
        async with httpx.AsyncClient(timeout=40) as client:
            r = await client.post('https://api.openai.com/v1/live/sessions', headers={'Authorization': 'Bearer ' + settings.OPENAI_API_KEY},
                                  json={'session': session_config(None, room_id=None, user_id=TEST_USER), 'transport': {'type': 'webrtc', 'sdp': sdp}})
        data = r.json()
        if r.status_code not in (200, 201):
            raise SystemExit(f'session rejected {r.status_code} {str(data)[:300]}')
        session_id = data['session']['id']
        await page.evaluate('sdp => pc.setRemoteDescription({type: "answer", sdp})', data['transport']['sdp'])
        side = asyncio.create_task(S._run(session_id, TEST_USER, None, settings.OPENAI_API_KEY, True))
        await asyncio.sleep(max(0, plan['total'] + 4 - (time.monotonic() - t0)))
        await page.evaluate("() => { try { dc.send(JSON.stringify({type: 'session.close'})); } catch (e) {} }")
        try: await asyncio.wait_for(side, 15)
        except asyncio.TimeoutError: side.cancel()
        await browser.close()
    rows = []
    for i, q in enumerate(plan['schedule']):
        lo, hi = t0 + q['start'], t0 + (plan['schedule'][i + 1]['start'] if i + 1 < len(plan['schedule']) else plan['total'] + 4)
        owner_end = t0 + q['end']
        inside = [e for e in log if lo <= e['t'] < hi]
        searches = [e for e in inside if e['kind'] == 'note' and e['phase'] == 'function_done' and e.get('name') == 'web_search']
        calls = [e.get('name') for e in inside if e['kind'] == 'note' and e['phase'] == 'function_done']
        done = searches[0]['t'] if searches else None
        answer = next((e['t'] for e in inside if e['kind'] == 'delta' and e['role'] == 'assistant' and done and e['t'] > done), None)
        rows.append({'q': q['q'], 'heard': ''.join(e['text'] for e in inside if e['kind'] == 'delta' and e['role'] == 'user'),
                     'dan': ''.join(e['text'] for e in inside if e['kind'] == 'delta' and e['role'] == 'assistant'),
                     'functions': calls,
                     'search_asked_after_owner_s': round(done - searches[0]['elapsed_ms'] / 1000 - owner_end, 2) if searches else None,
                     'search_ms': searches[0]['elapsed_ms'] if searches else None,
                     'result_after_owner_s': round(done - owner_end, 2) if done else None,
                     'answer_after_owner_s': round(answer - owner_end, 2) if answer else None,
                     'prefetch': [{k: v for k, v in e.items() if k not in ('t', 'kind')} for e in inside if e['kind'] == 'note' and str(e['phase']).startswith('prefetch')]})
    summary = [{k: v for k, v in e.items() if k != 't'} for e in log if e['kind'] == 'note' and e['phase'] in ('prefetch_summary', 'sideband_failed')]
    out = {'prefetch': os.environ.get('DAN_VOICE_PREFETCH', '1'), 'rows': rows, 'summary': summary,
           'errors': [e for e in log if e['kind'] == 'dc' and e['type'] == 'error']}
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for row in rows:
        print(row['q'], '| 検索を頼んだのは話し終わりの', row['search_asked_after_owner_s'], '秒後 | 検索', row['search_ms'], 'ms | 答えの声', row['answer_after_owner_s'], '秒後', row['functions'])


if __name__ == '__main__':
    asyncio.run(main(*sys.argv[1:4]))
