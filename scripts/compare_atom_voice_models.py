"""Same Atom PCM/frontend/Astra path for both models, with simulated device I/O.

Uses the dedicated existing voice test room. No physical device is controlled.
Run against a prepared isolated frontend: --base http://localhost:3108
"""
import argparse
import asyncio
import audioop
import base64
from collections import deque
import json
from pathlib import Path
import time
import wave

from fastapi import HTTPException
from starlette.requests import Request
from playwright.async_api import async_playwright
from app.services.auth_service import create_access_token
from app.api import voicelog_routes as routes
from app.services import voice_live

ROOT = Path(__file__).resolve().parents[1]
ROOM = '14d138aa-9499-4f51-b752-d088d12b5c59'
USER = '2582a188-ff24-4a4f-b989-6063034d90b2'


def frames(path):
    with wave.open(str(path), 'rb') as f:
        data=f.readframes(f.getnframes())
        if f.getnchannels()==2: data=audioop.tomono(data, f.getsampwidth(), .5, .5)
        if f.getsampwidth()!=2: data=audioop.lin2lin(data, f.getsampwidth(), 2)
        data,_=audioop.ratecv(data, 2, 1, f.getframerate(), 48000, None)
    return [data[i:i+960].ljust(960,b'\0') for i in range(0,len(data),960)]


async def run(base, provider, pw, deployed=False):
    browser=await pw.chromium.launch(headless=True,args=['--autoplay-policy=no-user-gesture-required'])
    context=await browser.new_context(service_workers='block')
    page=await context.new_page()
    page_errors=[]
    page.on('pageerror',lambda error:page_errors.append(str(error)[:300]))
    token=create_access_token(USER,'')
    request=Request({'type':'http','headers':[(b'authorization', ('Bearer '+token).encode())]})
    cfg={'enabled':True,'roomId':ROOM,'title':'音声比較テスト','key':'a'*32}
    await page.add_init_script('localStorage.setItem("done-token",'+json.dumps(token)+');localStorage.setItem("dan-atom-wifi",'+json.dumps(json.dumps(cfg))+');')
    await page.add_init_script('''window.voiceEvents=[];window.atomEvent=e=>window.voiceEvents.push({...e,at:Date.now()});
      const OriginalWorklet=AudioWorkletNode;window.AudioWorkletNode=class extends OriginalWorklet{constructor(...args){super(...args);if(args[1]==='atom-wifi-mic')window.testAtomMic=this;}};
      const original=RTCPeerConnection.prototype.createDataChannel;
      RTCPeerConnection.prototype.createDataChannel=function(...args){window.testPeer=this;window.testChannel=original.apply(this,args);return window.testChannel;};''')
    sockets=[];pending=deque();output=[];transcripts=[];sessions=[];stops=[];backend=[];errors=[]
    last_output=[0.]
    async def observe(response):
        if not deployed: return
        if response.url.endswith('/voicelog/live/session') and response.status==200:
            sessions.append((await response.json())['session']['id'])
        elif response.url.endswith('/voicelog/live/backend'):
            backend.append({'at':time.monotonic(),'status':response.status})
    page.on('response',observe)
    async def bridge(ws):
        sockets.append(ws)
        def receive(data):
            if isinstance(data,str):
                if 'roomId' in data: ws.send(json.dumps({'type':'ready','sampleRate':48000,'deviceConnected':True}))
            elif data and audioop.rms(data,2)>100:
                output.append(time.monotonic());last_output[0]=time.monotonic()
        ws.on_message(receive)
    await page.route_web_socket('ws://127.0.0.1:48801/audio',bridge)
    async def inject(path):
        data=b''.join(frames(path))
        return await asyncio.wait_for(page.evaluate('''async encoded=>{
          const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));
          await new Promise(resolve=>{
            window.pcmInput={bytes,index:0,done:resolve};
          });
        }''',base64.b64encode(data).decode()),20)
    async def api(route):
        data=route.request.post_data_json or {}
        endpoint=route.request.url.split('/voicelog/')[-1]
        if deployed and endpoint.startswith('live/'):
            await route.continue_();return
        try:
            if endpoint=='live/session':
                result=await routes.create_live_session(request,routes.LiveSessionRequest(**data))
                sessions.append(result['session']['id'])
            elif endpoint=='live/backend':
                result=await routes.live_backend(request,routes.LiveBackendRequest(**data))
                backend.append({'at':time.monotonic(),'output_types':[r['type'] for r in result['output']]})
            elif endpoint=='live/backend/steer': result=await routes.steer_live_backend(request,routes.LiveBackendRequest(**data))
            elif endpoint=='live/backend/close':
                result=await routes.close_live_backend(request,routes.LiveCloseRequest(**data))
            elif endpoint==ROOM:
                transcripts.append({**data,'at':time.monotonic()});result={'ok':True}
            elif endpoint=='command-center': result={'jobs':[],'requests':[]}
            else:
                await route.continue_();return
            await route.fulfill(json=result)
        except HTTPException as error:
            errors.append({'endpoint':endpoint,'status':error.status_code,'detail':error.detail})
            await route.fulfill(status=error.status_code,json={'detail':error.detail})
    await page.route('**/api/v1/voicelog/**',api)
    async def stop(route):
        if route.request.method=='OPTIONS':
            await route.fulfill(headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'content-type','Access-Control-Allow-Methods':'POST'});return
        stops.append(time.monotonic())
        await route.fulfill(json={'ok':True},headers={'Access-Control-Allow-Origin':'*'})
    await page.route('http://127.0.0.1:48802/command',stop)
    try:
        start=time.monotonic()
        await page.goto(base+'/atom-voice?worker=1'+('&voice=gemini' if provider=='gemini' else ''),wait_until='domcontentloaded')
        await page.wait_for_function('Boolean(window.__atomConfig?.model)',timeout=65000)
        await page.evaluate('''()=>{
          if(!window.testAtomMic)throw new Error('Atom input worklet was not captured');
          let next=performance.now();
          window.pcmTimer=setInterval(()=>{
            const now=performance.now();
            while(next<=now){
              const input=window.pcmInput;
              const buffer=input?input.bytes.slice(input.index,input.index+960).buffer:new ArrayBuffer(960);
              window.testAtomMic.port.postMessage(buffer,[buffer]);
              if(input){input.index+=960;if(input.index>=input.bytes.length){window.pcmInput=null;input.done();}}
              next+=10;
            }
          },5);
        }''')
        connection=time.monotonic()-start
        await page.screenshot(path=str(ROOT/f'.tmp/voice-compare-{provider}.png'))
        print(provider,'connected',round(connection,2),flush=True)
        await page.evaluate('window.__atomGreet()')
        deadline=time.monotonic()+25
        while not output and time.monotonic()<deadline: await asyncio.sleep(.1)
        assert output, 'Greeting produced no speaker PCM'
        deadline=time.monotonic()+25
        while time.monotonic()-last_output[0]<1 and time.monotonic()<deadline: await asyncio.sleep(.1)
        print(provider,'greeting complete',flush=True)
        # The same prerecorded interruption, through the normal Atom input worklet.
        long_text='これから、音声の接続試験について三十秒ほど詳しく説明してください。マイク、スピーカー、エコー除去、ネットワークの順に、それぞれの働きを説明してください。'
        await page.evaluate('text=>{if(window.__atomConnection){window.__atomTestText(text);}else{window.testChannel.send(JSON.stringify({type:"session.commentary.append",delegation_id:null,content:text}));}}',long_text)
        n=len(output);deadline=time.monotonic()+30
        while len(output)==n and time.monotonic()<deadline: await asyncio.sleep(.1)
        assert len(output)>n, 'No explanation audio'
        print(provider,'explanation audio',flush=True)
        await asyncio.sleep(.7)
        cutin_started=time.monotonic()
        print(provider,'injecting cutin',flush=True)
        await inject(ROOT/'.tmp/atom-live-cutin.wav')
        print(provider,'cutin sent',flush=True)
        cutin_ended=time.monotonic()
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            if any(r['role']=='assistant' and '聞こえ' in r['content'] for r in transcripts):break
            await asyncio.sleep(.2)
        cutin_answer=any(r['role']=='assistant' and '聞こえ' in r['content'] for r in transcripts)
        print(provider,'cutin answer',cutin_answer,flush=True)
        deadline=time.monotonic()+25
        while time.monotonic()-last_output[0]<1 and time.monotonic()<deadline: await asyncio.sleep(.1)
        await inject(ROOT/'.tmp/atom-close-phone.wav')
        audio_ended=time.monotonic()
        deadline=time.monotonic()+35
        while not stops and time.monotonic()<deadline: await asyncio.sleep(.1)
        await asyncio.sleep(.5)
        result={'provider':provider,'model':(await page.evaluate('window.__atomConfig')).get('model'),'physical_atom':False,
                'connection_seconds':round(connection,3),'greeting_pcm':True,'interruption_answer_received':cutin_answer,
                'cutin_audio_seconds':round(cutin_ended-cutin_started,3),
                'standby_count':len(stops),'standby_after_audio_seconds':round(stops[0]-audio_ended,3) if stops else None,
                'backend_responses':len(backend),'transcripts':transcripts,'errors':errors,'page_errors':page_errors}
        (ROOT/f'.tmp/voice-compare-{provider}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k!='transcripts'},ensure_ascii=True),flush=True)
        assert len(stops)==1, result
        assert cutin_answer, result
        return result
    finally:
        await page.evaluate('clearInterval(window.pcmTimer)')
        for session in sessions:
            if session in voice_live._sessions:voice_live.close(session,USER)
        await browser.close()


async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--base',default='http://localhost:3108');parser.add_argument('--provider',choices=['both','gemini','openai'],default='both');parser.add_argument('--deployed',action='store_true');args=parser.parse_args()
    async with async_playwright() as pw:
        results=[]
        for provider in (['openai','gemini'] if args.provider=='both' else [args.provider]):
            results.append(await run(args.base,provider,pw,args.deployed))
        (ROOT/'.tmp/voice-model-comparison.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':asyncio.run(main())
