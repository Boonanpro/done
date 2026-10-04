"""Separate-room real model/browser check; never modifies the user's demo."""
import json,os,subprocess,sys,time,urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'scratch/film-studio/check';OUT.mkdir(parents=True,exist_ok=True)

def main():
    room='film-studio-check-'+str(time.time_ns())
    env={**os.environ,'DAN_FILM_STUDIO_PORT':'3021','DAN_FILM_STUDIO_ROOM':room}
    log=(OUT/'server.log').open('w')
    proc=subprocess.Popen([sys.executable,'-m','scripts.film_studio_server'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    results={'room':room,'turns':[]}
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen('http://127.0.0.1:3021/api/state',timeout=1);break
            except Exception:time.sleep(.25)
        with sync_playwright() as p:
            b=p.chromium.launch(channel='msedge',headless=True,args=['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream'])
            page=b.new_page(viewport={'width':1440,'height':1000});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://127.0.0.1:3021');page.wait_for_function('()=>!!window.filmStudio?.project')
            assert not page.evaluate('()=>window.filmStudio.project.film_plan.story')
            texts=[
                'まだ展開は決めてない。2分で見せられる話を1案提案して。大成功して飛ぶより、小さな進歩で終わりたい。まだ画像や動画の生成はしないで。',
                'その方向でいい。冒頭の場面だけ、簡単な立体で作業場と人物と車の位置が見えるように見せて。人物が2秒で車へ近づく動きも入れて。完成の見た目は後で決める。',
                '今の人物だけ右へ1メートルずらして。カメラと車は変えないで。'
            ]
            for i,text in enumerate(texts):
                start=time.perf_counter();page.locator('#text').fill(text);page.locator('#send').click()
                page.wait_for_function('()=>document.querySelector("#send").disabled')
                page.wait_for_function('()=>!document.querySelector("#send").disabled',timeout=240000)
                s=page.evaluate('()=>window.filmStudio.project')
                assert s['jobs'][-1]['status']=='completed',s['jobs'][-1]
                if i:
                    page.wait_for_function('()=>document.querySelector(".proposal-player")?.ready!==undefined',timeout=30000)
                    ready=page.evaluate('()=>Promise.all([...document.querySelectorAll(".proposal-player")].filter(x=>x.ready).map(x=>x.ready))')
                    assert all(r['ok'] for r in ready),ready
                results['turns'].append({'text':text,'seconds':round(time.perf_counter()-start,2),'state':s})
                (OUT/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
                page.screenshot(path=str(OUT/f'turn-{i}.png'))
                print('turn',i,results['turns'][-1]['seconds'],'seconds',flush=True)
            before=[v for v in results['turns'][1]['state']['items'].values() if v['kind']=='scene'][-1]
            after=[v for v in results['turns'][2]['state']['items'].values() if v['kind']=='scene'][-1]
            results['scene_diff']={'same_code':before['scene']['code']==after['scene']['code'],'before_params':before['scene']['params'],'after_params':after['scene']['params']}
            page.reload();page.wait_for_function('()=>window.filmStudio?.project?.dialogue.length>=6')
            results['reload_preserved']=True
            page.locator('#voice').click();page.wait_for_function('()=>window.filmStudio.live?.started',timeout=60000)
            results['voice_connected']=True
            page.locator('#voice').click();page.wait_for_function('()=>!window.filmStudio.live')
            results['voice_closed']=True;results['page_errors']=errors
            assert not errors,errors
            (OUT/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
            b.close();print('PASS real text, persisted scenes, actual rendering, LIVE connection and close',flush=True)
    finally:
        if proc.poll() is None:proc.terminate();proc.wait(timeout=10)
        log.close()

if __name__=='__main__':main()
