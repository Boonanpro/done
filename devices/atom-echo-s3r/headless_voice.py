"""Dedicated headless voice browser. Never attaches to the user's browser."""
import asyncio
from collections import deque
from contextlib import asynccontextmanager
import json
from pathlib import Path
import secrets
import time

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright
import uvicorn
from event_log import event_logger
from voice_credentials import load_credentials, save_credentials, PairingExpired, credential_lock
from voice_destination import ROOM, TITLE
from voice_idle import VoiceIdle
event_log=event_logger("voice")

ROOT = Path(__file__).resolve().parents[2]
PAIR = ROOT / '.tmp/atom-wifi-pairing.json'
AUTH = ROOT / '.tmp/atom-headless-auth.json'
VOICE_CONFIG = ROOT / '.tmp/atom-voice-provider.json'
BASE = 'http://localhost:3000'
CORE = 'http://127.0.0.1:9000'
events = deque(maxlen=100)
state = {'state': 'starting', 'headless': True}
restart = asyncio.Event()
page = None
idle = VoiceIdle()
last_backend_output = None


async def observe_backend(response):
    global last_backend_output
    if '/voicelog/live/backend' in response.url and response.status >= 400:
        event_log('backend_error', status=response.status)
    if response.url.endswith('/voicelog/live/backend') and response.status == 200:
        try:
            data = await response.json()
            if any(item.get('type') == 'message' for item in data.get('output', [])):
                last_backend_output = data
        except Exception:
            pass

INSPECT = """() => {
  if(window.__atomConnection)return window.__atomConnection();
  const el=document.querySelector('[aria-label="音声モードを閉じる"]');
  if(!el)return {connection:'missing'};
  let f=el[Object.keys(el).find(k=>k.startsWith('__reactFiber$'))],refs=[];
  while(f){refs=[];for(let h=f.memoizedState;h;h=h.next){const v=h.memoizedState?.current;if(v)refs.push(v);}
    if(refs.some(x=>x instanceof RTCPeerConnection))break;f=f.return;}
  const pc=refs.find(x=>x instanceof RTCPeerConnection),dc=refs.find(x=>x instanceof RTCDataChannel);
  window.__atomVoice={pc,dc};
  if(dc?.readyState==='open'&&!dc.__atomObserved){dc.__atomObserved=true;dc.addEventListener('message',e=>{
    try{const m=JSON.parse(e.data);
      if(m.type==='session.started')window.__atomConfig={model:m.session?.model};
      const inner=m.type==='response.event'?m.event:m;
      if(inner?.type==='response.output_item.done'&&inner.item?.type==='function_call'){
        let args={};try{args=JSON.parse(inner.item.arguments||'{}')}catch{}
        window.atomEvent({type:'tool_call',name:inner.item.name,action:args.action,project_id:args.project_id,call_id:inner.item.call_id});
      }
      if(m.type==='session.input_transcript.delta'&&m.delta?.trim())window.atomEvent({type:'user_speech'});
      if(['session.delegation.created','session.closed','error'].includes(m.type))
        window.atomEvent({type:m.type,error:m.error?.message});
      if(inner?.type==='response.failed')window.atomEvent({type:inner.type,error:inner.response?.error?.message});
    }catch{}});}
  return {room:f?.memoizedProps?.roomId,connection:pc?.connectionState||'connecting',channel:dc?.readyState,config:window.__atomConfig};
}"""


async def device_status():
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            r=await client.get('http://127.0.0.1:48801/status')
            r.raise_for_status();return r.json()
    except Exception:
        return {'device_connected':False,'requested':False}


async def device_command(action, **fields):
    pairing=json.loads(PAIR.read_text(encoding='utf-8'))
    async with httpx.AsyncClient(timeout=2) as client:
        r=await client.post('http://127.0.0.1:48801/control',json={'key':pairing['key'],'action':action,**fields})
        r.raise_for_status();return r.json()


def record_event(event):
    if event.get('type') == 'user_speech':
        idle.speech()
        return
    events.append({'at':time.time(),**event})
    event_log(event.get('type','event'),**{k:event.get(k) for k in ('status','name','action','project_id','call_id','checked','total','failed') if event.get(k) is not None})


async def load_worker(worker, intent):
    """A button OFF cancels startup, including a stalled page navigation."""
    async def intent_ended():
        while True:
            device=await device_status()
            if restart.is_set() or not device.get('device_connected') or not device.get('requested') or (device.get('boot'),device.get('revision'))!=intent:return
            await asyncio.sleep(.25)
    try: provider=json.loads(VOICE_CONFIG.read_text(encoding='utf-8')).get('provider','openai')
    except (OSError, ValueError): provider='openai'
    suffix='&voice=gemini' if provider=='gemini' else ''
    navigation=asyncio.create_task(worker.goto(BASE+'/atom-voice?worker=1'+suffix,wait_until='domcontentloaded',timeout=30000))
    guard=asyncio.create_task(intent_ended())
    try:
        done,_=await asyncio.wait([navigation,guard],return_when=asyncio.FIRST_COMPLETED)
        if guard in done:return False
        await navigation
        return True
    finally:
        for task in (navigation,guard):
            if not task.done():task.cancel()
        await asyncio.gather(navigation,guard,return_exceptions=True)


async def browser_loop():
    global page
    async with async_playwright() as pw:
        attempts=0;retry_at=0.;intent=None;was_online=False
        while True:
            device=await device_status()
            current=(device.get('boot'),device.get('revision'))
            online=bool(device.get('device_connected'))
            if restart.is_set() or current!=intent or (online and not was_online):
                restart.clear();attempts=0;retry_at=0.
                if current!=intent:idle.reset()
                intent=current
            was_online=online
            if not device.get('device_connected') or not device.get('requested'):
                state.update(state='standby' if device.get('device_connected') else 'device_offline',connection='closed')
                await asyncio.sleep(.5);continue
            if idle.expired():
                try:
                    await device_command('stop');event_log('idle_standby')
                except Exception:
                    event_log('idle_stop_retry')
                await asyncio.sleep(.5);continue
            if not AUTH.exists():
                state.update(state='waiting_for_pairing',connection='closed')
                await asyncio.sleep(.5);continue
            if attempts>=3 or time.monotonic()<retry_at:
                state.update(state='connection_error' if attempts>=3 else 'reconnecting',connection='closed')
                await asyncio.sleep(.5);continue
            context=None
            try:
                auth=await load_credentials(AUTH, CORE)
                pairing=json.loads(PAIR.read_text(encoding='utf-8'))
                state.update(state='connecting');event_log('session_start',attempt=attempts+1)
                context=await pw.chromium.launch_persistent_context(
                    str(ROOT/'.tmp/atom-headless-profile'),headless=True,ignore_default_args=['--mute-audio'],
                    args=['--autoplay-policy=no-user-gesture-required','--disable-background-timer-throttling','--disable-renderer-backgrounding'],
                    viewport={'width':900,'height':700})
                page=context.pages[0] if context.pages else await context.new_page()
                page.on('response', observe_backend)
                # A stale cookie otherwise overrides the fresh Authorization header.
                await context.clear_cookies()
                await page.expose_function('atomEvent',record_event)
                await page.add_init_script('(()=>{const a='+json.dumps({'token':auth['token'],'config':{'enabled':True,'roomId':ROOM,'title':TITLE,'key':pairing['key']}})+';if(location.origin==='+json.dumps(BASE)+'){localStorage.setItem("done-token",a.token);localStorage.setItem("dan-atom-wifi",JSON.stringify(a.config));}})();')
                if not await load_worker(page,intent):continue
                failures=0;connected_at=None;greeted=False
                while not restart.is_set():
                    device=await device_status()
                    if not device.get('device_connected') or not device.get('requested') or (device.get('boot'),device.get('revision'))!=intent:break
                    if idle.expired():
                        await device_command('stop');event_log('idle_standby');break
                    result=await page.evaluate(INSPECT);state.update(result)
                    connected=result.get('connection')=='connected' and (result.get('config') or {}).get('model') in ('gpt-live-1','gemini-3.8-live-extended-thinking')
                    state['state']='connected' if connected else 'connecting'
                    await device_command('session',boot=intent[0],revision=intent[1],active=connected)
                    if connected:
                        if device.get('voice_ready') and not greeted:
                            greeted=await page.evaluate('Boolean(window.__atomGreet?.())')
                            if greeted:event_log('greeting_requested')
                        failures=0
                        if connected_at is None:connected_at=time.monotonic();event_log('session_connected')
                        if time.monotonic()-connected_at>30:attempts=0
                    else:
                        failures+=1
                        if result.get('connection') in ('closed', 'failed') or failures>=100:
                            raise RuntimeError('Voice connection unavailable')
                    await asyncio.sleep(.5)
            except PairingExpired:
                attempts=3
                state.update(state='waiting_for_pairing',error='pairing_expired')
                event_log('pairing_expired')
            except asyncio.CancelledError:raise
            except Exception as error:
                attempts+=1;retry_at=time.monotonic()+min(30,2**attempts)
                state.update(state='reconnecting',error=type(error).__name__)
                event_log('session_error',kind=type(error).__name__,attempt=attempts)
            finally:
                page=None
                try:await device_command('session',boot=intent[0],revision=intent[1],active=False)
                except Exception:pass
                if context:
                    try:await asyncio.wait_for(context.close(),5)
                    except Exception as error:event_log('browser_close_error',kind=type(error).__name__)
                state.update(connection='closed',channel='closed');event_log('session_closed')


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(browser_loop())
    async def renew_loop():
        while True:
            await asyncio.sleep(60)
            if not AUTH.exists(): continue
            try:
                auth = await load_credentials(AUTH, CORE)
                if page:
                    await page.evaluate('(token) => localStorage.setItem("done-token", token)', auth['token'])
            except PairingExpired:
                pass
            except Exception:
                event_log('credential_refresh_retry')
    renew = asyncio.create_task(renew_loop())
    yield
    task.cancel()
    renew.cancel()
    await asyncio.gather(task, renew, return_exceptions=True)


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[BASE], allow_methods=['POST', 'GET'], allow_headers=['Content-Type'])


async def authenticated(request):
    origin = request.headers.get('origin')
    if origin and origin != BASE: raise HTTPException(403)
    body = await request.json()
    key = json.loads(PAIR.read_text(encoding='utf-8'))['key']
    if not isinstance(body.get('key'), str) or not secrets.compare_digest(body['key'], key):
        raise HTTPException(403)
    return body


@app.get('/status')
async def status(): return {**state, 'destination_room': ROOM, 'destination_title': TITLE, 'events': list(events)[-12:]}


@app.post('/pair')
async def pair(request: Request):
    body = await authenticated(request)
    token = body.get('token')
    if not isinstance(token, str) or not 10 < len(token) < 20000: raise HTTPException(400)
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(BASE + f'/api/v1/chat/rooms/{ROOM}/messages?limit=1', headers={'Authorization': 'Bearer ' + token})
    if response.status_code != 200: raise HTTPException(401)
    AUTH.parent.mkdir(parents=True, exist_ok=True)
    credentials = {'token': token}
    refresh = body.get('refresh_token')
    if refresh is not None:
        if not isinstance(refresh, str) or not 10 < len(refresh) < 20000: raise HTTPException(400)
        credentials['refresh_token'] = refresh
    async with credential_lock:
        save_credentials(AUTH, credentials)
    await device_command('start')
    restart.set()
    return {'ok': True}


@app.post('/command')
async def command(request: Request):
    body = await authenticated(request)
    if body.get('action') == 'provider':
        provider=body.get('provider')
        if provider not in ('openai','gemini'): raise HTTPException(400)
        device=await device_status()
        if device.get('requested') or page: raise HTTPException(409, '通話終了後にモデルを切り替えてください')
        VOICE_CONFIG.write_text(json.dumps({'provider':provider}),encoding='utf-8')
        return {'ok':True,'provider':provider}
    if body.get('action') == 'diagnostics':
        return {'backend': last_backend_output}
    if body.get('action') == 'reconnect':
        restart.set()
        return {'ok': True}
    if body.get('action') == 'stop':
        await device_command('stop')
        restart.set()
        return {'ok': True}
    if body.get('action') == 'test_audio' and page and state.get('connection') == 'connected':
        if (state.get('config') or {}).get('model') == 'gemini-3.8-live-extended-thinking':
            raise HTTPException(409, 'この診断はWebRTC専用です。Geminiの録音比較はcompare_atom_voice_modelsのPCM入力を使用してください')
        audio = body.get('wav_base64', '')
        if not isinstance(audio, str) or not 1 <= len(audio) <= 4_000_000: raise HTTPException(400)
        await page.evaluate("""async encoded => {
          const peer=window.__atomVoice.pc,sender=peer.getSenders().find(s=>s.track?.kind==='audio');
          const original=sender.track,context=new AudioContext();
          const data=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));
          const source=context.createBufferSource();source.buffer=await context.decodeAudioData(data.buffer);
          const output=context.createMediaStreamDestination();source.connect(output);
          await sender.replaceTrack(output.stream.getAudioTracks()[0]);
          source.onended=async()=>{try{if(peer.connectionState!=='closed')await sender.replaceTrack(original);}finally{output.stream.getTracks().forEach(t=>t.stop());await context.close();}};
          await context.resume();source.start();
        }""", audio)
        event_log('test_audio')
        return {'ok': True}
    if body.get('action') == 'test_utterance' and page and state.get('connection') == 'connected':
        text=body.get('text','')
        if not isinstance(text,str) or not 1<=len(text)<=500:raise HTTPException(400)
        # Controlled acceptance input: restore automatically, including after a failed test client.
        mute_seconds=body.get('mute_input_seconds',0)
        if not isinstance(mute_seconds,int) or not 0<=mute_seconds<=180:raise HTTPException(400)
        if mute_seconds and (state.get('config') or {}).get('model') == 'gemini-3.8-live-extended-thinking':
            raise HTTPException(409, 'GeminiではこのWebRTCマイク差し替え診断を使用できません')
        if mute_seconds:
            await page.evaluate("seconds => {const tracks=window.__atomVoice.pc.getSenders().map(s=>s.track).filter(t=>t?.kind==='audio');const previous=tracks.map(t=>t.enabled);tracks.forEach(t=>t.enabled=false);setTimeout(()=>tracks.forEach((t,i)=>t.enabled=previous[i]),seconds*1000);}",mute_seconds)
        await page.evaluate("text => window.__atomTestText(text)",text)
        event_log('test_utterance')
        return {'ok':True}
    if body.get('action') == 'say' and page and state.get('connection') == 'connected':
        text = body.get('text', '')
        if not isinstance(text, str) or not 1 <= len(text) <= 500: raise HTTPException(400)
        if (state.get('config') or {}).get('model') == 'gemini-3.8-live-extended-thinking':
            await page.evaluate("text => window.__atomTestText('以下の案内を読み上げてください。外部操作は不要です。\\n' + text)", text)
        else:
            await page.evaluate("text => window.__atomVoice.dc.send(JSON.stringify({type:'session.commentary.append',event_id:crypto.randomUUID(),delegation_id:null,content:text}))", text)
        return {'ok': True}
    raise HTTPException(409)


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=48802, log_level='warning', access_log=False)
