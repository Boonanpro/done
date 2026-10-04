"""Real LIVE1 audio -> shared scene tool -> saved visual revision."""
import json,os,subprocess,sys,time,urllib.request,wave
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'scratch/film-studio/check'
def main():
    report=json.loads((OUT/'result.json').read_text(encoding='utf8'))
    from app.services import timeline_draft as td
    baseline=report['turns'][2]['state'];voice_room='film-studio-voice-'+str(time.time_ns())
    td._room_dir(voice_room).mkdir(parents=True)
    td._write_contents_raw(voice_room,[{'id':'two-minute-film','title':'isolated voice verification',
        'sheet':baseline['sheet'],'film_plan':baseline['film_plan'],'studio_dialogue':baseline['dialogue'],
        'recipes':{},'proposal_history':[{'id':'fixture-'+str(n),'items':[i],'created_at':time.time(),'author':'dan'} for n,i in enumerate(baseline['items'].values())],
        'timeline':{'format':'16:9','sequence':{'duration':0,'tracks':[]}}}])
    report['voice_room']=voice_room
    audio=ROOT/'scratch/conte-lab/voice-second.wav'
    with wave.open(str(audio),'rb') as w:params=w.getparams();frames=w.readframes(w.getnframes())
    silence=lambda n:b'\0'*(params.framerate*params.nchannels*params.sampwidth*n)
    padded=OUT/'voice-padded.wav'
    with wave.open(str(padded),'wb') as w:w.setparams(params._replace(nframes=0));w.writeframes(silence(12)+frames+silence(130))
    env={**os.environ,'DAN_FILM_STUDIO_PORT':'3022','DAN_FILM_STUDIO_ROOM':voice_room}
    log=(OUT/'voice-server.log').open('w');proc=subprocess.Popen([sys.executable,'-m','scripts.film_studio_server'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        for _ in range(80):
            try:urllib.request.urlopen('http://127.0.0.1:3022/api/state',timeout=1);break
            except Exception:time.sleep(.25)
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--use-file-for-fake-audio-capture='+str(padded)])
            context=browser.new_context(viewport={'width':1440,'height':1000},permissions=['microphone'])
            page=context.new_page();page.goto('http://127.0.0.1:3022');page.wait_for_function('()=>!!window.filmStudio?.project')
            before=page.evaluate('()=>Object.values(window.filmStudio.project.items).filter(i=>i.kind==="scene").at(-1)')
            page.locator('#scenes button').first.click();page.locator('#voice').click();start=time.perf_counter()
            try:
                page.wait_for_function('()=>window.filmStudio.live?.started',timeout=45000)
                page.wait_for_function('expected=>Object.values(window.filmStudio.project.items).filter(i=>i.kind==="scene").at(-1)?.scene.params.walkSeconds===expected',arg=before['scene']['params']['walkSeconds']/2,timeout=100000)
                after=page.evaluate('()=>Object.values(window.filmStudio.project.items).filter(i=>i.kind==="scene").at(-1)')
                assert after['scene']['duration']==before['scene']['duration']/2
                assert {k:v for k,v in before['scene']['params'].items() if k!='walkSeconds'}=={k:v for k,v in after['scene']['params'].items() if k!='walkSeconds'}
                page.wait_for_function('()=>window.filmStudio.live?.pending===false',timeout=60000)
                page.wait_for_timeout(10000)
                report['voice_edit']={'ok':True,'seconds_from_connect_click':round(time.perf_counter()-start,2),'before':before['scene']['params'],'after':after['scene']['params'],'dialogue':page.evaluate('()=>window.filmStudio.project.dialogue.slice(-3)')}
                page.screenshot(path=str(OUT/'voice.png'))
            except Exception as e:
                report['voice_edit']={'ok':False,'error':str(e),'status':page.locator('#status').inner_text()}
            finally:
                if page.evaluate('()=>!!window.filmStudio.live'):page.locator('#voice').click()
                context.close();browser.close()
            (OUT/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report['voice_edit'],ensure_ascii=True),flush=True)
            assert report['voice_edit']['ok']
    finally:
        if proc.poll() is None:proc.terminate();proc.wait(timeout=10)
        log.close()
if __name__=='__main__':main()
