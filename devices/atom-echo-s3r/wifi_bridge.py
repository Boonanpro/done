"""Local browser <-> authenticated Atom TCP PCM bridge. No API keys or chat writes."""
import asyncio,json,logging,sys,time,os
from pathlib import Path
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI,WebSocket,WebSocketDisconnect,Request,HTTPException
import secrets
from voice_state import VoiceGate
from audio_owner import AudioOwner
from event_log import event_logger
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'.tmp/atom-aec-tools'))
import numpy as np
from pywebrtc_audio import AudioProcessor

CONFIG=Path(os.environ.get('DAN_ATOM_CONFIG',str(ROOT/'.tmp/atom-wifi-pairing.json')))
cfg=json.loads(CONFIG.read_text(encoding='utf-8'))
audio_owner=AudioOwner(CONFIG.with_name('atom-audio-owner.json'))
from voice_destination import ROOM
browser=None
writer=None
pending=asyncio.Queue(maxsize=6)
status={'device_connected':False,'browser_connected':False,'mic_bytes':0,'speaker_bytes':0,'reconnects':0}
gate=VoiceGate()
event=event_logger('bridge')
wake=None
relay=None
relay_input=asyncio.Queue(maxsize=12)

class RelayReader:
    async def readexactly(self, count):
        data=await relay_input.get()
        if data is None: raise ConnectionError('Phone relay disconnected')
        if len(data)!=count: raise ValueError('Invalid phone frame')
        return data

class RelayWriter:
    def __init__(self, socket): self.socket=socket; self.packet=None
    def write(self, data): self.packet=data
    async def drain(self):
        if self.packet is not None: await self.socket.send_bytes(self.packet); self.packet=None
    def close(self): pass
    async def wait_closed(self): pass

async def device_loop():
    global writer
    while True:
        if audio_owner.mode == 'phone':
            await asyncio.sleep(.2)
            continue
        try:
            # Provisioning may update DHCP address while the bridge is running.
            current=json.loads(CONFIG.read_text(encoding='utf-8'))
            if relay:
                r,w=RelayReader(),RelayWriter(relay)
            else:
                r,w=await asyncio.wait_for(asyncio.open_connection(current['ip'],48800),5)
                writer=w
                w.write(b'DAN4'+cfg['key'].encode('ascii'));await w.drain()
                if await asyncio.wait_for(r.readexactly(4),3)!=b'OKF4':raise ValueError('Wake-control firmware required')
            writer=w
            ap=AudioProcessor(sample_rate=48000,echo_cancellation=True,noise_suppression=True,ns_level=1,stream_delay_ms=40)
            status['aec']=True
            health_at=previous_frame=time.monotonic()
            frames=send_timeouts=0
            raw_energy=clean_energy=far_energy=max_gap=0.0
            while not pending.empty():pending.get_nowait()
            while True:
                packet=await asyncio.wait_for(r.readexactly(972),5)
                if audio_owner.mode == 'phone': break
                if not status['device_connected']:
                    status['device_connected']=True;status['reconnects']+=1
                    status['connected_at']=time.time();event('device_connected')
                if gate.receive(packet[:12]):
                    while not pending.empty():pending.get_nowait()
                    ap.reset()
                    event('device_intent',**gate.status())
                    if wake:wake.reset(3 if not gate.requested else 0)
                pcm=packet[12:]
                if wake and not gate.requested and not gate.pending:
                    status['wake_mic_rms']=round(float(np.sqrt(np.mean(np.frombuffer(pcm,dtype=np.int16).astype(np.float32)**2))),1)
                    wake.feed(pcm,(gate.boot,gate.revision))
                status['mic_bytes']+=len(pcm)
                # The device microphone clock paces both directions at 10 ms.
                # This reference is exactly the PCM sent to the speaker.
                far=pending.get_nowait() if gate.ready and not pending.empty() else bytes(960)
                if not gate.ready:
                    pcm=bytes(960)
                    while not pending.empty():pending.get_nowait()
                w.write(gate.outgoing()+far);await asyncio.wait_for(w.drain(),2)
                status['speaker_bytes']+=len(far)
                near=np.frombuffer(pcm,dtype=np.int16)
                # No speaker reference or cloud audio in standby: avoid running
                # AEC on silent frames while the offline recognizer is active.
                clean=ap.process(near,np.frombuffer(far,dtype=np.int16)) if gate.ready else np.zeros_like(near)
                status['mic_raw_rms']=round(float(np.sqrt(np.mean(near.astype(np.float32)**2))),1)
                status['mic_clean_rms']=round(float(np.sqrt(np.mean(clean.astype(np.float32)**2))),1)
                status['speaker_rms']=round(float(np.sqrt(np.mean(np.frombuffer(far,dtype=np.int16).astype(np.float32)**2))),1)
                now=time.monotonic()
                if gate.ready:
                    frames+=1
                    max_gap=max(max_gap,now-previous_frame)
                    raw_energy+=status['mic_raw_rms']**2
                    clean_energy+=status['mic_clean_rms']**2
                    far_energy+=status['speaker_rms']**2
                previous_frame=now
                if browser:
                    try:await asyncio.wait_for(browser.send_bytes(clean.tobytes()),.25)
                    except Exception:send_timeouts+=1
                if now-health_at>=1:
                    if frames:
                        event('audio_health',frames=frames,max_gap_ms=round(max_gap*1000,1),
                              mic_raw_rms=round((raw_energy/frames)**.5,1),
                              mic_clean_rms=round((clean_energy/frames)**.5,1),
                              speaker_rms=round((far_energy/frames)**.5,1),send_timeouts=send_timeouts)
                    health_at=now
                    frames=send_timeouts=0
                    raw_energy=clean_energy=far_energy=max_gap=0.0
        except Exception as e:
            status['last_error']=type(e).__name__
            status['last_error_at']=time.time()
            event('device_error',kind=type(e).__name__)
        finally:
            switching_to_phone=relay is not None and not isinstance(writer,RelayWriter)
            if not switching_to_phone:
                status['device_connected']=False
                gate.disconnected()
            if wake:wake.reset()
            if writer:
                writer.close()
                try:await asyncio.wait_for(writer.wait_closed(),1)
                except Exception:writer.transport.abort()
            writer=None
        await asyncio.sleep(.05 if relay else 1)

@asynccontextmanager
async def lifespan(app):
    global wake
    if cfg.get('wake_enabled',False):
        try:
            from local_wake import LocalWake
            loop=asyncio.get_running_loop()
            def detected(intent):
                if audio_owner.mode == 'pc' and gate.connected and not gate.requested and not gate.pending and intent==(gate.boot,gate.revision):
                    gate.control(True);event('wake_detected')
            wake=await asyncio.to_thread(LocalWake,lambda intent:loop.call_soon_threadsafe(detected,intent),cfg.get('wake_phrases'))
            gate.wake_enabled=True
        except Exception as error:
            status['wake_error']=type(error).__name__;event('wake_error',kind=type(error).__name__)
    task=asyncio.create_task(device_loop())
    yield
    task.cancel();await asyncio.gather(task,return_exceptions=True)
    if wake:await asyncio.to_thread(wake.close)

app=FastAPI(lifespan=lifespan)

@app.websocket('/device-relay')
async def device_relay(ws:WebSocket):
    """Loopback gateway only; carries existing framed PCM, never model credentials."""
    global relay
    await ws.accept()
    try:
        auth=await asyncio.wait_for(ws.receive_json(),5)
        if not secrets.compare_digest(str(auth.get('key','')),cfg['key']) or relay or audio_owner.mode != 'pc':
            await ws.close(code=1008);return
        relay=ws
        while not relay_input.empty():relay_input.get_nowait()
        if writer and not isinstance(writer,RelayWriter):writer.close()
        await ws.send_json({'type':'ready'})
        event('phone_relay_connected')
        while True:
            frame=await asyncio.wait_for(ws.receive_bytes(),8)
            if len(frame)!=972:await ws.close(code=1008);break
            if relay_input.full():relay_input.get_nowait()
            relay_input.put_nowait(frame)
    except (WebSocketDisconnect,asyncio.TimeoutError):pass
    finally:
        if relay is ws:
            relay=None
            while not relay_input.empty():relay_input.get_nowait()
            relay_input.put_nowait(None)
            event('phone_relay_disconnected')
@app.get('/status')
async def get_status():return {**status,**gate.status(),'audio_owner':audio_owner.mode,'wake_enabled':gate.wake_enabled,'wake_phrases':cfg.get('wake_phrases',['hey dan']) if gate.wake_enabled else [],'wake':wake.status() if wake else None}

@app.post('/control')
async def control(request:Request):
    body=await request.json()
    if not isinstance(body.get('key'),str) or not secrets.compare_digest(body['key'],cfg['key']):raise HTTPException(403)
    if body.get('action') == 'audio_owner':
        try:
            audio_owner.select(body.get('mode'), busy=bool(gate.requested or gate.pending or browser or relay))
        except ValueError: raise HTTPException(400)
        except RuntimeError: raise HTTPException(409, '音声接続の終了後に切り替えてください')
        if audio_owner.mode == 'phone' and writer:
            previous=writer
            previous.close()
            try: await asyncio.wait_for(previous.wait_closed(),1)
            except (Exception, asyncio.TimeoutError): raise HTTPException(503, 'デバイス接続の解放を確認できませんでした')
        event('audio_owner',mode=audio_owner.mode)
        return {'audio_owner':audio_owner.mode}
    if audio_owner.mode != 'pc': raise HTTPException(409, 'Atomの音声はスマホが管理しています')
    if body.get('action') in ('start','stop'):
        if body['action']=='start' and not gate.connected:raise HTTPException(409)
        gate.control(body['action']=='start')
        while not pending.empty():pending.get_nowait()
        event('host_intent',action=body['action'])
    elif body.get('action')=='session':
        if not gate.lease(body.get('boot'),body.get('revision'),bool(body.get('active'))):raise HTTPException(409)
    else:raise HTTPException(400)
    return gate.status()

@app.websocket('/audio')
async def audio(ws:WebSocket):
    global browser
    if ws.headers.get('origin') not in ('http://localhost:3000','http://127.0.0.1:3000','http://localhost:3002','http://127.0.0.1:3002'):
        await ws.close(code=1008);return
    await ws.accept()
    try:
        auth=await asyncio.wait_for(ws.receive_json(),5)
        if auth.get('key')!=cfg['key'] or auth.get('roomId')!=ROOM or browser or audio_owner.mode != 'pc':
            await ws.close(code=1008);return
        browser=ws;status['browser_connected']=True
        event('browser_connected')
        await ws.send_json({'type':'ready','sampleRate':48000,'deviceConnected':status['device_connected']})
        while True:
            message=await ws.receive()
            if message['type']=='websocket.disconnect':break
            if message.get('text'):
                control=json.loads(message['text'])
                if control.get('type')=='flush':
                    while not pending.empty():pending.get_nowait()
                    status['interruptions']=status.get('interruptions',0)+1
                continue
            data=message.get('bytes',b'')
            if len(data)!=960:await ws.close(code=1008);break
            if not status['device_connected']:continue
            if pending.full():pending.get_nowait()
            pending.put_nowait(data)
    except (WebSocketDisconnect,asyncio.TimeoutError):pass
    finally:
        if browser is ws:
            browser=None;status['browser_connected']=False
            gate.ready_until=0
            event('browser_disconnected')
            while not pending.empty():pending.get_nowait()

if __name__=='__main__':
    uvicorn.run(app,host='127.0.0.1',port=48801,log_level='warning',access_log=False)
