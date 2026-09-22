"""Real voice input and concurrent production in an isolated editor project."""
import asyncio,base64,json,time,uuid,wave,threading
from pathlib import Path
import httpx,websockets
from playwright.sync_api import sync_playwright
from app.config import settings
from app.services.auth_service import create_access_token
from app.services import timeline_draft as td

BASE='http://127.0.0.1:8029'
FIXTURE=Path('exports/reasoning-user-voice.wav').resolve()
UTTERANCE='作業は止めずに教えて。このテストでは、新しく動画を生成する必要はある？'
async def make_voice():
    if FIXTURE.exists():return
    pcm=bytearray()
    async with websockets.connect('wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1',additional_headers={'Authorization':'Bearer '+settings.OPENAI_API_KEY},max_size=16*1024*1024) as ws:
        await ws.send(json.dumps({'type':'session.update','session':{'type':'realtime','model':'gpt-realtime-2.1','output_modalities':['audio'],'instructions':'入力文だけを日本語でそのまま読み上げてください。','tools':[],'audio':{'output':{'voice':'marin','format':{'type':'audio/pcm','rate':24000}}}}}))
        while True:
            e=json.loads(await ws.recv())
            if e['type']=='session.updated':break
            if e['type']=='error':raise RuntimeError(e)
        await ws.send(json.dumps({'type':'conversation.item.create','item':{'type':'message','role':'user','content':[{'type':'input_text','text':UTTERANCE}]}}))
        await ws.send(json.dumps({'type':'response.create','response':{'output_modalities':['audio']}}))
        while True:
            e=json.loads(await asyncio.wait_for(ws.recv(),60))
            if e['type'] in {'response.output_audio.delta','response.audio.delta'}:pcm.extend(base64.b64decode(e['delta']))
            if e['type']=='response.done':
                assert e['response']['status']=='completed',e;break
            if e['type']=='error':raise RuntimeError(e)
    with wave.open(str(FIXTURE),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000)
        f.writeframes(bytes(24000*2)+pcm+bytes(24000*2*15))

def main():
    asyncio.run(make_voice())
    room='reasoning-production-'+uuid.uuid4().hex[:8];folder=td._room_dir(room);folder.mkdir(parents=True)
    (folder/'contents.json').write_text('[]');(folder/'assets.json').write_text('[]')
    token=create_access_token('2582a188-ff24-4a4f-b989-6063034d90b2','bold1315@icloud.com')
    with httpx.Client(base_url=BASE,headers={'Authorization':'Bearer '+token},timeout=60) as c:
        r=c.post('/api/v1/editor-assistant/new',json={'room_id':room});r.raise_for_status();cid=r.json()['content_id']
    report={'room':room,'content_id':cid};started=time.monotonic()
    observed={}; stop_observer=threading.Event()
    def observe_timeline():
        while not stop_observer.wait(0.1):
            try:
                current=td._content_sequence(td._read_contents_raw(room)[0])
                clips=[c for t in current.get('tracks',[]) for c in t.get('clips',[])]
                elapsed=round(time.monotonic()-started,2)
                if any(c.get('asset_id') for c in clips):observed.setdefault('media_saved_seconds',elapsed)
                if any(c.get('text') for c in clips):observed.setdefault('caption_saved_seconds',elapsed)
            except (OSError,ValueError,IndexError,KeyError):pass
    threading.Thread(target=observe_timeline,daemon=True).start()
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--autoplay-policy=no-user-gesture-required','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',f'--use-file-for-fake-audio-capture={FIXTURE}'])
        page=browser.new_page(bypass_csp=True)
        page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
        page.goto(BASE+'/api/v1/editor-assistant/page')
        page.evaluate('c=>window.__updateEditorContext(c)',{'room_id':room,'content_id':cid,'playhead':0,'selected':[]})
        page.evaluate("async()=>{$('scope').value='whole';await connect();micOn=true;}")
        page.evaluate("()=>{$('input').value='このテストは生成済みのBを音付きでエディターに置いて再生できるようにすることが目的です。Bは D:/done/exports/omni-direct-comparison/b_from_reference.mp4 にあります。既存ファイルを読み込んで、この空の動画に全尺を音付きで配置して。新しい素材生成や課金は不要です。';submit();}")
        page.wait_for_function('jobs.size>0',timeout=120000)
        report['job_started_seconds']=round(time.monotonic()-started,2)
        print('JOB',report['job_started_seconds'],page.evaluate('[...jobs.keys()]'),flush=True)
        page.evaluate("()=>{$('input').value='追加です。同じ作業の中で、最後の1秒に「確認用B」という字幕も一つ載せて。新規生成は不要です。';submit();}")
        page.wait_for_function('!reasonRunning&&!busy&&!relayActive&&!audioPlaying&&relayQueue.length===0',timeout=120000)
        # Feed real PCM through the microphone and ASR, then mute the fixture track
        # without switching off the voice conversation/completion notification.
        page.evaluate('async()=>{micOn=false;await toggleMic();}')
        page.wait_for_function("conversationMemory.some(m=>m.role==='user'&&m.text.includes('生成する必要'))",timeout=60000)
        page.evaluate('()=>mic.getTracks().forEach(t=>t.enabled=false)')
        page.wait_for_function('!reasonRunning&&!busy&&!relayActive&&!audioPlaying&&relayQueue.length===0',timeout=120000)
        report['voice_question_seconds']=round(time.monotonic()-started,2)
        print('VOICE QUESTION',report['voice_question_seconds'],flush=True)
        deadline=time.monotonic()+300
        while time.monotonic()<deadline:
            contents=td._read_contents_raw(room);seq=td._content_sequence(contents[0]);clips=[x for t in seq['tracks'] for x in t['clips']]
            if seq.get('duration',0)>4.9 and any(x.get('text')=='確認用B' for x in clips):break
            page.wait_for_timeout(1000)
        else:raise AssertionError('Video and correction not delivered')
        page.wait_for_function("spokenJobs.size>0&&!activeNotice&&!completionNotices.length&&!audioPlaying",timeout=120000)
        page.wait_for_timeout(4000)
        page.evaluate('flushAudit()')
        report['elapsed_seconds']=round(time.monotonic()-started,2)
        stop_observer.set();report['timeline_observed']=dict(observed)
        report['ui']=page.evaluate('({messages:[...$("log").querySelectorAll(".message")].map(e=>({kind:e.className,text:e.textContent})),memory:conversationMemory,audit,jobs:[...jobs],notices:completionNotices,activeNotice})')
        report['sequence']=seq
        (folder/'production-e2e.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        assert not [m for m in report['ui']['messages'] if 'error' in m['kind']],report['ui']['messages']
        assert any(t['type']=='audio' and t['clips'] for t in seq['tracks'])
        print('PASS',room,cid,report['elapsed_seconds'],flush=True)
        page.evaluate('disconnect()');browser.close()
if __name__=='__main__':main()
