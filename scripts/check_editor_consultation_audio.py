"""Speak ordinary requests through the deployed editor's actual Live audio path.

No forced backend response or direct sheet tool invocation. Isolated test room;
production handoff is recorded without launching media work.
"""
import asyncio,base64,json,time,uuid,sys
from pathlib import Path
import httpx
from playwright.async_api import async_playwright
from app.config import settings

PHRASES=[
    '都市伝説系のYouTubeチャンネルを作りたくて、その一本目を相談したいんだよね。題材はシミュレーション仮説がいいな。参考動画はあとで選びたい。',
    '都市伝説が好きな大人に、現実の見え方がちょっと変わる面白さを感じてほしい。長さは十五分くらい。使いたい素材は、今は特にないかな。',
    'あ、やっぱり十五分じゃなくて十分くらいにしよう。ほかはそのままでいい。',
    'うん、その方向でいいよ。参考作品は、いったん未定のままでいい。',
]

def evaluate(result):
    turns=result['turns']
    assert len(turns)==4
    assert not result['errors'],result['errors']
    assert all(any(e['type']=='consultation_sheet_updated' for e in t['events']) for t in turns)
    duration=turns[2]['sheet']['fields']['duration']['value']
    assert '10' in duration or '十' in duration
    assert turns[-1]['sheet']['ready_for_draft']
    # The last "yes, that direction" follows Dan's concrete offer to create a
    # plan. It may authorize handoff; treating that as forbidden was a bad oracle.
    for i,t in enumerate(turns):
        for e in t['events']:
            if e['type'] in ('production_handoff','unexpected_production'):
                assert i==3,'Production before the user agreed'
                assert any(u['type']=='consultation_sheet_updated' and u['ms']<e['ms']
                           and u['sheet']['ready_for_draft'] for u in t['events'])
    preserved=all(turns[1]['sheet']['fields'][k]==turns[2]['sheet']['fields'][k] for k in turns[1]['sheet']['fields'] if k!='duration')
    assert preserved,'Duration correction changed unrelated fields'
    return {'saved_without_prompting':4,'correction_preserved_other_fields':preserved,
            'save_ms':[round(next(e['ms'] for e in t['events'] if e['type']=='consultation_sheet_updated')-t['input_timing']['end']) for t in turns],
            'ready_before_handoff':True,'production_executed':False}

async def main():
    out=Path('scratch/consultation-audio-20260923');out.mkdir(parents=True,exist_ok=True)
    async with httpx.AsyncClient(timeout=60) as client:
        for i,text in enumerate(PHRASES):
            path=out/f'input-{i}.wav'
            if not path.exists():
                response=await client.post('https://api.openai.com/v1/audio/speech',
                    headers={'Authorization':'Bearer '+settings.OPENAI_API_KEY},
                    json={'model':'gpt-4o-mini-tts','voice':'ash','input':text,'response_format':'wav',
                          'instructions':'自然な日本語の雑談の声。友人に相談するように、抑揚と短い間をつけて、普通の速さで話す。読み上げや演説にしない。'})
                response.raise_for_status();path.write_bytes(response.content)
    room='consultation-audio-'+uuid.uuid4().hex[:10]
    (Path('uploads/production-assets')/room).mkdir(parents=True)
    token=(Path.home()/'.done/native_token.txt').read_text().strip()
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        context_browser=await browser.new_context(viewport={'width':1440,'height':1000},record_video_dir=str(out/'screen'))
        page=await context_browser.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
        await page.evaluate('v=>window.__setEditorAuth(v)',{'token':token})
        cid=await page.evaluate('async room=>(await api("/new",{room_id:room})).content_id',room)
        await page.evaluate('''c=>{
          window.__updateEditorContext(c);window.trialEvents=[];
          const original=record;record=(type,data)=>{trialEvents.push({ms:performance.now(),type,...data});original(type,data);};
          const execute=executeLiveConsultationTool;
          executeLiveConsultationTool=async(item,...args)=>{
            if(item.name==='run_editor_task'){record('production_handoff',{arguments:item.arguments});return {accepted:false,reason:'test_handoff_boundary'};}
            return execute(item,...args);
          };
        }''',{'room_id':room,'content_id':cid})
        snapshots=[]
        try:
            await page.evaluate('''async()=>{
              await connectLive();
              window.testAudio=new AudioContext();await testAudio.resume();
              window.testInput=testAudio.createMediaStreamDestination();
              // A microphone emits silence continuously too. Keep the audio
              // clock running after each file ends, not just during playback.
              window.testSilence=testAudio.createConstantSource();testSilence.offset.value=0;
              testSilence.connect(testInput);testSilence.start();
              await pc.getSenders().find(s=>!s.track||s.track.kind==='audio').replaceTrack(testInput.stream.getAudioTracks()[0]);
              window.testMix=testAudio.createMediaStreamDestination();
              testAudio.createMediaStreamSource(audio.srcObject).connect(testMix);
              window.recorded=[];window.testRecorder=new MediaRecorder(testMix.stream);
              testRecorder.ondataavailable=e=>recorded.push(e.data);testRecorder.start();
              micOn=true;
              dc.addEventListener('message',e=>{const m=JSON.parse(e.data);
                if(m.type==='response.event')record('test_response_event',{envelope:m});});
            }''')
            for i,text in enumerate(PHRASES):
                await page.wait_for_function('()=>!audioPlaying&&!liveConnection?.responsePending',timeout=60000)
                await page.wait_for_timeout(1200)
                data=base64.b64encode((out/f'input-{i}.wav').read_bytes()).decode()
                start=await page.evaluate('''async data=>{
                  const source=testAudio.createBufferSource();
                  source.buffer=await testAudio.decodeAudioData(Uint8Array.from(atob(data),c=>c.charCodeAt(0)).buffer);
                  source.connect(testInput);source.connect(testMix);const start=performance.now();
                  source.start();await new Promise(resolve=>source.onended=resolve);
                  return {start,end:performance.now()};
                }''',data)
                print('SPOKEN',i,flush=True)
                # Let the actual model decide to delegate, persist and ask next.
                # A timer never invokes a backend response or a sheet update.
                deadline=time.monotonic()+45
                while time.monotonic()<deadline:
                    await page.wait_for_timeout(500)
                    snapshot=await page.evaluate('''start=>({sheet:readConsultationMemo(liveConnection),
                      pending:!!liveConnection?.responsePending,speaking:audioPlaying,
                      transcript:conversationMemory,
                      events:trialEvents.filter(e=>e.ms>=start.start)})''',start)
                    updates=[e for e in snapshot['events'] if e['type']=='consultation_sheet_updated']
                    outputs=[e for e in snapshot['events'] if e['type']=='voice_output_stopped' and updates and e['ms']>updates[-1]['ms']]
                    if any(e['type']=='production_handoff' for e in snapshot['events']) or (updates and outputs and not snapshot['pending'] and not snapshot['speaking']):
                        break
                snapshot.update(input=text,input_timing=start)
                snapshots.append(snapshot)
                (out/'result.json').write_text(json.dumps({'room':room,'content_id':cid,'turns':snapshots,'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
                print('RESULT',i,json.dumps(snapshot['sheet'],ensure_ascii=False),flush=True)
                await page.screenshot(path=str(out/f'turn-{i}.png'))
            print(json.dumps(evaluate({'turns':snapshots,'errors':errors}),ensure_ascii=False))
        finally:
            audio_data=await page.evaluate('''async()=>{
              if(!window.testRecorder)return null;
              await new Promise(resolve=>{testRecorder.onstop=resolve;testRecorder.stop();});
              const bytes=new Uint8Array(await new Blob(recorded).arrayBuffer());
              let s='';for(let i=0;i<bytes.length;i+=8192)s+=String.fromCharCode(...bytes.subarray(i,i+8192));
              return btoa(s);
            }''')
            if audio_data:(out/'conversation.webm').write_bytes(base64.b64decode(audio_data))
            await page.evaluate('()=>{disconnect("audio_test_complete");window.testAudio?.close();}')
            await page.wait_for_timeout(1200)
            await context_browser.close();await browser.close()

if __name__=='__main__':
    if '--evaluate' in sys.argv:
        result=json.loads(Path('scratch/consultation-audio-20260923/result.json').read_text(encoding='utf-8'))
        print(json.dumps(evaluate(result),ensure_ascii=False))
    else:asyncio.run(main())
