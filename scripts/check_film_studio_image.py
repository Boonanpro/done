"""Exercise the actual image tool and its rendered result in the isolated test room."""
import json,os,subprocess,sys,time,urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'scratch/film-studio/check'
def main():
    report=json.loads((OUT/'result.json').read_text(encoding='utf8'))
    env={**os.environ,'DAN_FILM_STUDIO_PORT':'3021','DAN_FILM_STUDIO_ROOM':report['room']}
    log=(OUT/'image-server.log').open('w');proc=subprocess.Popen([sys.executable,'-m','scripts.film_studio_server'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        for _ in range(80):
            try:urllib.request.urlopen('http://127.0.0.1:3021/api/state',timeout=1);break
            except Exception:time.sleep(.25)
        with sync_playwright() as p:
            b=p.chromium.launch(channel='msedge',headless=True);page=b.new_page(viewport={'width':1440,'height':1000})
            page.goto('http://127.0.0.1:3021');page.wait_for_function('()=>!!window.filmStudio?.project')
            start=time.perf_counter()
            result=page.evaluate('''async()=>{
              const r=await fetch('/api/tool',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({call_id:'image-integration-check',name:'generate_look',arguments:{title:'作業場の完成イメージ・検証用',prompt:'Cinematic still frame, realistic Japanese small workshop. A 27-year-old Japanese male engineer in worn navy work clothes inspects a rough prototype car restrained on a steel test rig. His expression is focused, not smiling at camera. Practical daylight from side windows, cool steel and warm muted skin, believable cables and tools, eye-level medium wide shot, 35mm natural cinematic composition. No text or labels. One coherent frame. This is a fictional film concept image, not a real photograph.'}})});return r.json();}''')
            assert result.get('ok'),result
            page.wait_for_function('()=>[...document.querySelectorAll(".proposal-player img")].some(i=>i.complete&&i.naturalWidth>0)',timeout=30000)
            page.locator('.proposal-player img').last.scroll_into_view_if_needed();page.screenshot(path=str(OUT/'image.png'))
            report['image']={'seconds':round(time.perf_counter()-start,2),'model':result['model'],'routing':result['routing'],'path':result['path'],'visible':True}
            (OUT/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            print(json.dumps(report['image'],ensure_ascii=True),flush=True);b.close()
    finally:
        if proc.poll() is None:proc.terminate();proc.wait(timeout=10)
        log.close()
if __name__=='__main__':main()
