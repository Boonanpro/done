"""Exercise the real editor visual tool in an isolated project; no model call."""
import asyncio,json,uuid
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    room='visual-consultation-'+uuid.uuid4().hex[:10]
    (Path('uploads/production-assets')/room).mkdir(parents=True)
    token=(Path.home()/'.done/native_token.txt').read_text().strip()
    out=Path('scratch/consultation-visual');out.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        page=await browser.new_page(viewport={'width':1440,'height':1000})
        await page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
        await page.evaluate('v=>window.__setEditorAuth(v)',{'token':token})
        cid=await page.evaluate('async room=>(await api("/new",{room_id:room})).content_id',room)
        await page.evaluate('c=>{context=c}',{'room_id':room,'content_id':cid})
        layers=[]
        for i,label in enumerate(['恐竜の生活','化石・図解','生活を再現']):
            x=60+i*420
            layers.extend([{'type':'rect','x':x,'y':180,'width':320,'height':280,'background':'#24334a','borderRadius':24},
                           {'type':'text','text':label,'x':x+20,'y':280,'width':280,'height':80,'fontSize':38,'color':'#ffffff'}])
            if i<2:layers.append({'type':'text','text':'→','x':x+340,'y':280,'width':70,'height':80,'fontSize':48})
        args={'items':[{'kind':'composition','title':'構成案','composition':{'width':1280,'height':720,'duration':8,'background':'#101723','layers':layers}}]}
        decisions=out/'decisions.json'
        if decisions.exists():
            results=json.loads(decisions.read_text(encoding='utf8'))
            args=next(c['args'] for r in results for c in r['calls'] if c['name']=='show_consultation_visual')
        result=await page.evaluate('''async args=>executeLiveConsultationTool(
            {name:'show_consultation_visual',call_id:'visual-check',arguments:JSON.stringify(args)},
            {id:'visual-check',editContext:context},context)''',args)
        assert result['shown'],result
        await page.wait_for_timeout(1000)
        await page.screenshot(path=str(out/'flow.png'))
        navigation=await page.evaluate('''()=>{
          const commands=[];window.ipc={postMessage:c=>commands.push(c)};
          window.dispatchEvent(new CustomEvent('dan-vconte-started',{detail:context}));
          return {commands,compact:document.body.classList.contains('compact')};
        }''')
        assert navigation['compact'] and navigation['commands']==['stage_compact'],navigation
        (out/'result.json').write_text(json.dumps({'room':room,'content_id':cid,'result':result},ensure_ascii=False,indent=2),encoding='utf8')
        print('PASS: native consultation visual rendered in isolated editor')
        await browser.close()

if __name__=='__main__':asyncio.run(main())
