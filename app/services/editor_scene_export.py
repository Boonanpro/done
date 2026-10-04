"""Materialize editable scenes only for export; never replace the editor sources."""
from copy import deepcopy
import hashlib
import json
import math
import subprocess
from app.services import timeline_draft as td


def materialize(room,sequence,canvas,fps,ffmpeg,preview_origin='http://127.0.0.1:3000'):
    clips=[c for tr in sequence.get('tracks',[]) if not tr.get('hidden') for c in tr.get('clips',[]) if c.get('scene')]
    if not clips:return sequence
    from playwright.sync_api import sync_playwright
    from app.services.editor_media import import_media
    result=deepcopy(sequence)
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        try:
            page=browser.new_page(viewport={'width':canvas[0],'height':canvas[1]},device_scale_factor=1)
            page.goto(preview_origin+'/caption-frame')
            page.wait_for_function('()=>!!window.__setCaptionPayload')
            for track in result.get('tracks',[]):
                for clip in track.get('clips',[]):
                    if not clip.get('scene') or track.get('hidden'):continue
                    duration=clip['timeline_end']-clip['timeline_start']
                    key=hashlib.sha256(json.dumps([clip['scene'],duration,canvas,fps],sort_keys=True).encode()).hexdigest()[:24]
                    folder=td._room_dir(room)/'scene-export';folder.mkdir(exist_ok=True)
                    output=folder/(key+'.mp4')
                    if not output.exists():
                        temporary=folder/(key+'.working.mp4')
                        payload={'outW':canvas[0],'outH':canvas[1],'time':0,'captions':[
                            {'id':clip['id'],'text':'','start':0,'end':duration,'scene':clip['scene']}]}
                        page.evaluate('p=>window.__setCaptionPayload(p)',payload)
                        page.wait_for_selector('[data-scene-ready="true"]',timeout=20000)
                        process=subprocess.Popen([ffmpeg,'-y','-v','error','-f','image2pipe','-vcodec','png','-r',str(fps),'-i','-',
                            '-an','-c:v','libx264','-pix_fmt','yuv420p',str(temporary)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                        try:
                            for n in range(math.ceil(duration*fps)):
                                page.evaluate('t=>window.__renderCaptionAt(t)',n/fps)
                                page.wait_for_function('t=>Math.abs((window.__nativeSceneTime??-1)-t)<.0001',arg=n/fps,timeout=10000)
                                process.stdin.write(page.screenshot(type='png'))
                            process.stdin.close()
                            error=process.stderr.read().decode('utf-8',errors='replace')
                            if process.wait(timeout=60):raise RuntimeError(error[-1500:])
                            temporary.replace(output)
                        finally:
                            if process.poll() is None:process.kill();process.wait()
                            temporary.unlink(missing_ok=True)
                    media=import_media(room,str(output),'コンテ書き出し '+clip.get('label',clip['id']),origin='editable-scene-export')
                    if not media.get('ok'):raise RuntimeError(str(media))
                    clip.pop('scene');clip.update(asset_id=media['asset_id'],source_start=0,source_end=duration,fit='contain')
        finally:browser.close()
    return result
