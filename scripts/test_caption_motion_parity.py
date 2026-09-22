"""Real browser vs native caption motion, including backwards seeks."""
import json
import os
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright
from app.services import timeline_context as ctx


def bbox(path):
    import numpy as np
    a=np.asarray(Image.open(path).convert('RGBA'))
    yy,xx=np.where((a[:,:,:3].min(axis=2)>180)&(a[:,:,3]>100))
    assert len(xx),'text not visible'
    return [int(xx.min()),int(yy.min()),int(xx.max()),int(yy.max())]


def main():
    record=json.loads(Path('uploads/reference-motion-latest.json').read_text())
    folder=Path('uploads/production-assets')/record['room_id'];out=folder/'parity';out.mkdir(exist_ok=True)
    clip={'id':'parity-title','text':'動く文字','timeline_start':0,'timeline_end':3,
          'style':{'font':'noto-sans','fontSize':1,'outlineWidth':0,'color':'#ffffff','y':.4},
          'transform_keys':[{'t':0,'x':-.2,'y':.1,'w':.8,'h':.8},{'t':2,'x':.1,'y':-.2,'w':1.3,'h':1.3}]}
    second={**clip,'id':'parity-second','text':'別の文字','style':{**clip['style'],'y':.15}}
    sequence={'format':'16:9','frame_rate':30,'duration':3,'tracks':[{'type':'video','clips':[clip]},{'type':'video','clips':[second]}]}
    os.environ['NATIVE_UI_EXE']=str(Path('scripts/poc/production_desktop/native_ui/target/release/native_ui.exe').resolve())
    times=[0,1,2,1]
    native=ctx.render_timeline_frames(sequence,str(folder),times,out_dir=str(out))
    assert native['ok'],native
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1920,'height':1080})
        page.goto(os.environ.get('DAN_CAPTION_RENDER_BASE','http://127.0.0.1:3000')+'/caption-frame')
        page.wait_for_function('()=>typeof window.__setCaptionPayload==="function"')
        page.wait_for_selector('body[data-caption-ready="1"]',state='attached')
        payload={'outW':1920,'outH':1080,'time':0,'captions':[{'id':c['id'],'text':c['text'],'start':0,'end':3,'design':c['style'],'transform_keys':c['transform_keys']} for c in [clip,second]]}
        page.evaluate('p=>window.__setCaptionPayload(p)',payload)
        results=[]
        for i,t in enumerate(times):
            page.evaluate('t=>window.__renderCaptionAt(t)',t)
            boxes=page.evaluate("()=>Array.from(document.querySelectorAll('p')).map(p=>{const b=p.parentElement.getBoundingClientRect();return [b.width,b.height]})")
            assert len(boxes)==2 and all(0<w<500 and 0<h<200 for w,h in boxes),boxes
            path=out/f'browser-{i}.png';page.screenshot(path=str(path),omit_background=True)
            a,b=bbox(native['paths'][i]),bbox(path)
            results.append({'t':t,'native':a,'browser':b})
            assert max(abs(x-y) for x,y in zip(a,b))<=3,results
        assert results[1]['native']==results[3]['native']
        assert results[1]['browser']==results[3]['browser']
        (out/'result.json').write_text(json.dumps(results,indent=2))
        browser.close()
    print('PASS native/browser motion positions, scale and backwards seeks',results)


if __name__=='__main__':main()
