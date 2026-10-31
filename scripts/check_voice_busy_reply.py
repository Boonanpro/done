"""Bounded diagnostic: real Live speech during a 20-second fixture status read.

No actual task, room write, browser action, or external phone call is performed.
This isolates whether an outstanding backend tool necessarily blocks call-outs;
it is NOT acceptance evidence for actual artifact creation, steering, or stop.
Outputs are immutable per mode. Inspect raw logs and microphone clock alignment;
transcript arrival is not physical-device audible latency.
"""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
BASELINE = '7ce68543'  # version tested on 2026-11-01
sys.path.insert(0, str(ROOT))
OUT = ROOT / '.tmp/voice-response-proof'
OUT.mkdir(parents=True, exist_ok=True)
CASES = [
    ('今進めている台本の作業はどうなってる？', 'job_status'),
    ('おい、聞いてる？', ''),
    ('返事だけして。聞こえてる？', ''),
]



def prepare():
    if any((OUT/f'{mode}.json').exists() for mode in ('baseline','after')):
        raise RuntimeError('do not replace audio for an existing paid measurement')
    rate = 24000
    audio = bytearray(b'\x00\x00' * rate * 10)
    schedule = []
    for i, (text, name) in enumerate(CASES):
        aiff, wav = OUT / f'{i}.aiff', OUT / f'{i}.wav'
        subprocess.run(['say', '-v', 'Kyoko', '-r', '205', '-o', str(aiff), text], check=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(aiff), '-ar', str(rate), '-ac', '1', str(wav)], check=True)
        with wave.open(str(wav), 'rb') as f: pcm = f.readframes(f.getnframes())
        start = len(audio) / (rate * 2)
        audio.extend(pcm)
        end = len(audio) / (rate * 2)
        schedule.append(dict(q=text, expected=name, start=start, end=end))
        audio.extend(b'\x00\x00' * rate * (4 if i < 2 else 28))
    with wave.open(str(OUT / 'owner.wav'), 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate); f.writeframes(audio)
    (OUT / 'schedule.json').write_text(json.dumps({'schedule': schedule, 'total': len(audio)/(rate*2)}, ensure_ascii=False, indent=2))


async def main(mode):
    if mode not in ('baseline', 'after') or (OUT/f'{mode}.json').exists():
        raise RuntimeError('only one baseline and one after call; existing evidence is immutable')
    from dotenv import load_dotenv
    load_dotenv(Path.home() / 'done/.env')  # read existing secrets into memory, never copy to output
    from app.services import voice_prefetch as P, voice_sideband as S, voice_live as L, voice_responses as R
    if mode == 'baseline':
        for module in (P, R, L, S):
            source = subprocess.check_output(['git', 'show', BASELINE + ':' + module.__file__.removeprefix(str(ROOT) + '/')], cwd=ROOT, text=True)
            exec(compile(source, module.__file__, 'exec'), module.__dict__)
    from app.config import settings
    from app.services.jev_decisions import Decisions
    from app.services import jev_browser_budget as budget
    from app.services.credentials_service import get_credentials_service
    # Synthetic test user; the owner-authorized API key pays for this bounded evaluation.
    user, room = '1f53bb2a-51da-4a2a-be9e-4c5a0f74d5f1', 'voice-early-fixture'
    owner = '2582a188-ff24-4a4f-b989-6063034d90b2'
    key = None
    for service in ('typesafe', 'typesafe_jev'):
        c = await get_credentials_service().get_credential(owner, service)
        if c and c.get('password'): key = c['password']; break
    async def credential(self): return key
    Decisions._credential = credential
    budget.PATH = OUT / 'jev-budget.json'
    if not budget.PATH.exists():
        budget.PATH.write_text(json.dumps(dict(enabled=True, publish=True, user_id=user, approved_usd=.3, reserved_usd=0, requests=0, max_requests=250)))
    R.catalog = lambda: ''
    R.remembered = lambda: ''
    # Keep model instructions/tools identical except no production room context and no stage.
    R.tools = lambda: [*R.TOOLS, {'type':'function','name':'list_operations','description':'記憶した手順の一覧を読む', 'parameters':{'type':'object','properties':{},'additionalProperties':False}}]
    import app.services.dan_core
    app.services.dan_core.shared = lambda *a: ''
    from app.services import voice_stage, voice_calls
    voice_stage.enabled = lambda: True
    voice_stage.ROOT = OUT / ('stage-' + mode)
    async def draw(*a): return {'action':'keep','caption':''}, {}
    voice_stage.ask_model = draw
    voice_calls.begin = lambda *a: None
    voice_calls.end = lambda *a: None
    async def idle(*a): await asyncio.Event().wait()
    async def noop(*a, **kw): return []
    S.job_feed = S.chat_feed = idle
    S.call_log = S.after_call = noop
    log = []
    def mark(kind, **fields): log.append(dict(t=time.monotonic(), kind=kind, **fields))
    S.note = lambda sid, rid, phase, **kw: mark('note', phase=phase, **kw)
    original_add = S.Dialogue.add
    def add(self, role, delta):
        if delta: mark('delta', role=role, text=delta)
        original_add(self, role, delta)
    S.Dialogue.add = add
    async def fixture(name, args, uid, rid, dialogue, **kw):
        mark('fixture_start', name=name, args=args)
        if name in ('get_calendar', 'job_status', 'search_records', 'room_files'):
            await asyncio.sleep(20 if name == 'job_status' else .8)
        values = {
            'job_status': {'jobs': [{'task':'テスト用の調査','state':'running','progress':'表紙を作成中'}]},
            'get_calendar': {'events':[{'title':'テスト打ち合わせ','start':str(args.get('from') or '今日')+' 15:00'}]},
            'search_records': {'records':[{'text':'パソコンはメモリ32GBと決めた。'}]},
            'room_files': {'files':[{'name':'test-plan.pdf','label':'テスト企画書'}]},
            'list_operations': {'operations':[]},
            'start_work': {'accepted':True,'job_id':f'fixture-{len(log)}','note':'試験用の作業を受け付けた。'},
        }
        mark('fixture_end', name=name)
        return values.get(name, {'error':'試験ではこの操作を実行しない'})
    R.run_function = fixture
    async def no_search(*a): return {'success':False,'error':'試験にウェブ検索はない'}
    from app.services import web_search
    web_search.find = no_search
    # Fail-closed fixture layer: no actual work or reads can escape via execute_call.
    from playwright.async_api import async_playwright
    import httpx
    PAGE = "async () => {\n  const stream = await navigator.mediaDevices.getUserMedia({audio: true});\n  window.pc = new RTCPeerConnection();\n  stream.getTracks().forEach(t => pc.addTrack(t, stream));\n  window.dc = pc.createDataChannel('oai-events');\n  dc.onmessage = e => { const m = JSON.parse(e.data); if (m.type === 'error' || m.type === 'session.started') dcEvent(m.type, JSON.stringify(m).slice(0, 300)); };\n  await pc.setLocalDescription(await pc.createOffer());\n  if (pc.iceGatheringState !== 'complete') await new Promise(r => { pc.addEventListener('icegatheringstatechange', () => { if (pc.iceGatheringState === 'complete') r(); }); });\n  return pc.localDescription.sdp;\n}"
    plan = json.loads((OUT/'schedule.json').read_text())
    if plan['total'] > 65: raise RuntimeError('bounded call duration exceeded')
    if (OUT/f'{mode}.json').exists(): raise RuntimeError('existing paid run: do not overwrite or silently repeat')
    # Bounded diagnostic under the owner's permission to resume useful audio tests.
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', f'--use-file-for-fake-audio-capture={OUT / "owner.wav"}%noloop'])
        page = await browser.new_page()
        await page.expose_function('dcEvent', lambda kind, body: mark('dc', type=kind))
        mic=[]
        await page.expose_function('micChunk', lambda data: mic.append(data))
        await page.route('http://localhost/**', lambda route: route.fulfill(body='<html></html>', content_type='text/html'))
        await page.goto('http://localhost/voice-early-test')
        a=time.monotonic(); browser_ms=await page.evaluate('performance.now()'); b=time.monotonic()
        offset=(a+b)/2-browser_ms/1000
        uncertainty=(b-a)/2
        PAGE = PAGE.replace("window.pc = new RTCPeerConnection();", """
  window.audioContext = new AudioContext(); await audioContext.resume();
  const source=audioContext.createMediaStreamSource(stream);
  const processor=audioContext.createScriptProcessor(1024,1,1);
  const mute=audioContext.createGain(); mute.gain.value=0;
  source.connect(processor); processor.connect(mute); mute.connect(audioContext.destination);
  const epoch=performance.now()/1000-audioContext.currentTime;
  processor.onaudioprocess=e=>{
    const x=e.inputBuffer.getChannelData(0); let first=-1,last=-1;
    for(let i=0;i<x.length;i++){if(Math.abs(x[i])>.002){if(first<0)first=i;last=i;}}
    if(first>=0)micChunk({start:epoch+e.playbackTime+first/audioContext.sampleRate,
      end:epoch+e.playbackTime+last/audioContext.sampleRate,received:performance.now()/1000});
  };
  window.pc = new RTCPeerConnection();
""")
        t0 = time.monotonic()
        sdp = await page.evaluate(PAGE)
        async with httpx.AsyncClient(timeout=40) as client:
            r = await client.post('https://api.openai.com/v1/live/sessions', headers={'Authorization':'Bearer '+settings.OPENAI_API_KEY}, json={'session':L.session_config(room_id=None,user_id=user), 'transport':{'type':'webrtc','sdp':sdp}})
        if r.status_code not in (200,201):
            (OUT/f'{mode}.json').write_text(json.dumps({'status':r.status_code,'error':'Live session rejected; no retry'}))
            await browser.close()
            return
        data=r.json()
        await page.evaluate('sdp => pc.setRemoteDescription({type:"answer",sdp})',data['transport']['sdp'])
        side=asyncio.create_task(S._run(data['session']['id'], user, room, settings.OPENAI_API_KEY, True))
        try:
            await asyncio.sleep(max(0, plan['total']+2-(time.monotonic()-t0)))
            await page.evaluate('() => dc.send(JSON.stringify({type:"session.close"}))')
            try: await asyncio.wait_for(side,10)
            except asyncio.TimeoutError: side.cancel()
        finally: await browser.close()
    groups=[]
    for c in mic:
        if not groups or c['start']-groups[-1]['end']>2: groups.append({'start':c['start'],'end':c['end']})
        else: groups[-1]['end']=c['end']
    rows=[]
    for i,q in enumerate(plan['schedule']):
        end=t0+q['end']; lo=t0+q['start']; hi=t0+(plan['schedule'][i+1]['start'] if i+1<len(CASES) else plan['total']+2)
        inside=[e for e in log if lo<=e['t']<hi]
        calls=[e for e in inside if e['kind']=='fixture_start']
        matching=[e for e in calls if e['name']==q['expected']]
        done=[e for e in inside if e['kind']=='note' and e.get('phase')=='function_done' and e.get('name')==q['expected']]
        rows.append({**q,'heard':''.join(e['text'] for e in inside if e['kind']=='delta' and e['role']=='user'),
            'functions':[e['name'] for e in calls], 'requests':[e['args'] for e in matching],
            'start_after_audio_end_s':round(matching[0]['t']-end,3) if matching else None,
            'done_after_audio_end_s':round(done[0]['t']-end,3) if done else None,
            'prefetch_hits':len([e for e in inside if e['kind']=='note' and e.get('phase')=='prefetch_hit'])})
    (OUT/f'{mode}.json').write_text(json.dumps({'mode':mode,'baseline_commit':BASELINE,'fixture_delay_s':20,'rows':rows,'log':log,'mic_groups':groups,'mic_chunks':mic,'browser_to_python_s':offset,'clock_uncertainty_s':uncertainty,'t0':t0,'stage':'fixture stage; tools isolated; measures voice response during delayed status read'},ensure_ascii=False,indent=2))
    print(json.dumps({'rows':rows,'speech':[e for e in log if e['kind']=='delta']},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('prepare', 'baseline', 'after'):
        raise SystemExit('prepare|baseline|after')
    if sys.argv[1]=='prepare': prepare()
    else: asyncio.run(main(sys.argv[1]))
