"""Run the real editor UI offline: delayed speech, fast reference navigation,
tool execution and status. No model calls or changes to user projects."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    files={'page':'editor-assistant.html','script':'editor-assistant.js','live-script':'editor-live.js','proposal-script':'editor-proposals.js','proposal-style':'editor-proposals.css'}
    requests=[]
    def route(r):
        name=r.request.url.rsplit('/',1)[-1]
        if name in files:
            f=Path('app/static')/files[name]
            return r.fulfill(body=f.read_text(encoding='utf-8'),content_type='text/html' if name=='page' else 'text/css' if name=='proposal-style' else 'application/javascript')
        data=r.request.post_data_json or {}
        requests.append((name,data))
        if name=='begin':result={'turn_id':'a'*32,'context':data}
        elif name=='reason':
            if not data.get('outputs'):
                rows=[{'type':'tool','name':'timeline_frame','call_id':'frame','arguments':json.dumps({'t':10})},{'type':'done','has_tools':True,'usage':{}}]
            else:rows=[{'type':'text','delta':'Checked the opening. No edit is running.'},{'type':'done','has_tools':False,'usage':{}}]
            return r.fulfill(body='\n'.join(json.dumps(x,ensure_ascii=False) for x in rows)+'\n',content_type='application/x-ndjson')
        elif name=='project-status':result={'jobs':[],'clip_count':1}
        elif name=='presentations':result={'presentations':[]}
        else:result={'ok':True}
        r.fulfill(json=result)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',route)
        page.goto('https://editor.test/api/v1/editor-assistant/page')
        page.evaluate("""()=>{
          window.__setEditorAuth({token:'offline-test'});
          window.__updateEditorContext({room_id:'test',content_id:'A',playhead:10,selected:[]});
          window.sent=[];dc={readyState:'open',send:s=>window.sent.push(JSON.parse(s))};micOn=true;
          liveConnection={started:true,startedAt:Date.now()-5000,id:'test-session',rows:{},views:[{at_ms:0,view:structuredClone(context)}],editContext:structuredClone(context)};
          window.__updateEditorContext({room_id:'test',content_id:'B',playhead:75,selected:[]});
          liveTranscript({type:'session.input_transcript.delta',start_ms:100,end_ms:3000,delta:'Look at this opening'},liveConnection);
          liveDelegate({delegation:{id:'test-delegation'}},liveConnection);
        }""")
        page.wait_for_function("()=>liveConnection.work?.status==='idle'")
        page.wait_for_timeout(300)
        assert page.evaluate('liveConnection.editContext.content_id')=='A'
        begun=next(d for n,d in requests if n=='begin')
        assert begun['content_id']=='A' and begun['playhead']==10
        assert begun['observed_views'][0]['view']['content_id']=='A'
        assert begun['viewed_context']['content_id']=='B'
        assert not any(n=='cancel' for n,d in requests)
        assert page.locator('body').get_attribute('data-work')=='idle'
        page.evaluate("micOn=false;productionSnapshot={active_count:1,phase:'edit',highlights:[]};workObservedAt=Date.now();updatePresence()")
        assert page.locator('body').get_attribute('data-work')=='edit'
        assert page.locator('body').get_attribute('data-agent')=='thinking'
        assert page.locator('#mic').get_attribute('aria-pressed')=='false'
        page.evaluate("""()=>{
          statusPending=true;
          renderProductionStatus({jobs:[
            {id:'old',status:'failed',created_at:'2020',updated_at:'2020'},
            {id:'current',status:'running',created_at:'2026',request:'73秒の日野の銘板の番号をぼかす',pending_instructions:1,
             activity:[{tool:'set_clip_props',description:'日野の銘板に合わせてぼかしの位置を調整',category:'editing',state:'running',started_at:Date.now()/1000-12,clip_ids:['plate']}]}]},context);
          updatePresence();
        }""")
        assert '日野' in page.locator('#work-focus').inner_text()
        assert 'ぼかしの位置' in page.locator('#orb-status').inner_text()
        assert '受領待ち' in page.locator('#work-meta').inner_text()
        snapshot=page.evaluate('JSON.parse(liveConnection.jobSnapshot)')
        assert [j['id'] for j in snapshot['active']]==['current']
        before=page.locator('#work-readout').bounding_box()
        page.wait_for_timeout(600)
        after=page.locator('#work-readout').bounding_box()
        assert before==after, (before,after)
        page.screenshot(path='scratch/editor-muted-working.png')
        page.set_viewport_size({'width':390,'height':720})
        page.evaluate("document.body.classList.add('compact');updatePresence()")
        page.screenshot(path='scratch/editor-work-compact.png')
        rect=page.locator('#work-readout').bounding_box()
        assert rect['x']>=0 and rect['x']+rect['width']<=390
        assert rect['y']+rect['height']<page.locator('#dock').bounding_box()['y']
        assert page.evaluate("sent.some(e=>e.type==='session.thinking.append' && e.content.includes('idle'))")
        assert not errors,errors
        print('PASS: real UI, A speech -> B navigation -> A context/tool -> idle UI and voice state; no paid calls')
        browser.close()


if __name__=='__main__':main()

