"""Real browser/Gemini/Astra transport check; simulated Atom, no external work."""
import asyncio
import base64
import json
from pathlib import Path
import subprocess
import time
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

from playwright.async_api import async_playwright
from app.config import settings
from app.services.voice_gemini import provision
from app.services.voice_codex import VoiceCodex

ROOT = Path(__file__).resolve().parents[1]


async def main():
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs): super().__init__(*args, directory=str(ROOT/'frontend/public'), **kwargs)
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    code = subprocess.check_output(['node', '-e', "const fs=require('fs'),ts=require('./frontend/node_modules/typescript');process.stdout.write(ts.transpileModule(fs.readFileSync('frontend/src/components/voice/gemini-transport.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)"], cwd=ROOT).decode()
    session = await provision(settings.GOOGLE_GEMINI_API_KEY, [])
    session['session'] = {'id': 'isolated-gemini-transport'}
    agent = VoiceCodex()
    tools = [{'type':'function','name':'read_status','description':'現在の作業状態を読み取る','parameters':{'type':'object','properties':{}}},
             {'type':'function','name':'enter_voice_standby','description':'音声会話を終了する','parameters':{'type':'object','properties':{}}}]
    events = []
    calls = []
    instructions = '日本語の音声窓口。現在の状態を聞かれたらread_statusを呼ぶ。通話終了の依頼はenter_voice_standbyを呼ぶ。結果を一文で伝える。'
    active = set()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--autoplay-policy=no-user-gesture-required'])
        context = await browser.new_context(service_workers='block')
        page = await context.new_page()
        await page.route('**/__gemini_probe', lambda route: route.fulfill(content_type='text/html', body='<html><body>Isolated voice transport test</body></html>'))
        await context.route('**/gemini-mic-worklet.js', lambda route: route.fulfill(content_type='text/javascript', body=(ROOT/'frontend/public/gemini-mic-worklet.js').read_text()))
        async def handle(event):
            events.append({**event, 'at': time.monotonic()})
            if event['type'] != 'session.delegation.created': return
            result = await agent.respond([{'type':'message','role':'user','content':[{'type':'input_text','text':event.get('request','')}]}], tools, instructions)
            while True:
                outputs = result.get('output', [])
                functions = [x for x in outputs if x['type']=='function_call']
                if not functions: break
                answers = []
                for call in functions:
                    calls.append(call['name'])
                    answers.append({'type':'function_call_output','call_id':call['call_id'],'output':json.dumps({'status':'running','detail':'比較テストは実行中です'} if call['name']=='read_status' else {'state':'standby'})})
                result = await agent.respond(answers, tools, instructions)
            text='\n'.join(p['text'] for x in outputs if x['type']=='message' for p in x.get('content',[]) if p.get('type')=='output_text')
            await page.evaluate('x=>window.transport.complete(x.id,x.text)', {'id':event['delegation']['id'],'text':text})
        def receive(event):
            task=asyncio.create_task(handle(event));active.add(task);task.add_done_callback(active.discard)
        await page.expose_function('voiceEvent', receive)
        try:
            await page.goto(f'http://127.0.0.1:{server.server_port}/__gemini_probe')
            await page.add_script_tag(content='window.exports={};\n'+code)
            await page.evaluate('''async session => {
                const ac = new AudioContext({sampleRate:48000}); window.ac=ac;
                window.input=ac.createMediaStreamDestination();
                window.transport=new exports.GeminiTransport(ac,session,e=>window.voiceEvent(e),()=>{},()=>{});
                const analyser=ac.createAnalyser();analyser.fftSize=1024;
                ac.createMediaStreamSource(transport.output.stream).connect(analyser);
                window.peak=0;window.audioTimer=setInterval(()=>{const f=new Float32Array(1024);analyser.getFloatTimeDomainData(f);for(const v of f)window.peak=Math.max(window.peak,Math.abs(v));},20);
                await ac.resume();await transport.start(input.stream);
            }''', session)
            print('browser_connected', flush=True)
            await page.evaluate('transport.sendText("現在の作業状態をバックエンドに確認してください。")')
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                if calls and any(e['type']=='session.output_transcript.delta' and '実行' in e.get('delta','') for e in events): break
                await asyncio.sleep(.2)
            assert 'read_status' in calls, {'calls':calls,'events':events[-8:]}
            await asyncio.sleep(2)
            peak=await page.evaluate('window.peak')
            assert peak>0, 'No output PCM'
            await page.evaluate('''async data=>{
                const source=ac.createBufferSource();source.buffer=await ac.decodeAudioData(Uint8Array.from(atob(data),c=>c.charCodeAt(0)).buffer);
                source.connect(input);source.start();
            }''', base64.b64encode((ROOT/'.tmp/atom-close-phone.wav').read_bytes()).decode())
            deadline=time.monotonic()+60
            while time.monotonic()<deadline and 'enter_voice_standby' not in calls: await asyncio.sleep(.2)
            assert 'enter_voice_standby' in calls, {'calls':calls,'events':events[-8:]}
            result={'model':session['model'],'real_gemini':True,'real_astra':True,'physical_atom':False,'tools':calls,'output_pcm_peak':peak,
                    'input_transcript':''.join(e.get('delta','') for e in events if e['type']=='session.input_transcript.delta'),
                    'output_transcript':''.join(e.get('delta','') for e in events if e['type']=='session.output_transcript.delta')}
            (ROOT/'.tmp/gemini-voice-transport-proof.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(result,ensure_ascii=True),flush=True)
        finally:
            await page.evaluate('window.transport?.close();clearInterval(window.audioTimer);window.ac?.close()')
            for task in active: task.cancel()
            await asyncio.gather(*active,return_exceptions=True)
            agent.close()
            await browser.close()
            server.shutdown()


if __name__ == '__main__': asyncio.run(main())
