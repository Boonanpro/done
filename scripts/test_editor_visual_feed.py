"""Real presentation API and browser; fixture media, no model or paid generation."""
import os
import base64
import json
from pathlib import Path
import struct
import uuid
import httpx
from playwright.sync_api import sync_playwright
from app.services import editor_presentation as presentation


def main():
    base=os.environ.get('EDITOR_TEST_BASE','http://127.0.0.1:8037');room='visual-feed-'+uuid.uuid4().hex[:8]
    folder=Path('uploads/production-assets')/room;folder.mkdir(parents=True)
    (folder/'contents.json').write_text('[]');(folder/'assets.json').write_text('[]')
    token=(Path.home()/'.done/native_token.txt').read_text().strip()
    client=httpx.Client(base_url=base,headers={'Authorization':'Bearer '+token})
    cid=client.post('/api/v1/editor-assistant/new',json={'room_id':room}).json()['content_id']
    for i in range(14):
        presentation.present(room,cid,[{'kind':'text','title':f'Idea {i}','text':f'Visual {i}'}])
    latest=presentation.present(room,cid,[{'kind':'image','title':'Cafe','url':'https://fixture.example/cafe.png'},
        {'kind':'model','title':'3D fixture','url':'https://fixture.example/triangle.gltf'},
        {'kind':'link','title':'Reference site','url':'https://example.com'},
        {'kind':'video','title':'Movie','url':'https://fixture.example/movie.mp4'}])['presentation']
    data=struct.pack('<9f',-1,-1,0,1,-1,0,0,1,0)
    gltf={'asset':{'version':'2.0'},'scene':0,'scenes':[{'nodes':[0]}],'nodes':[{'mesh':0}],
        'meshes':[{'primitives':[{'attributes':{'POSITION':0},'material':0}]}],
        'materials':[{'doubleSided':True,'pbrMetallicRoughness':{'baseColorFactor':[.3,.7,1,1],'metallicFactor':0}}],
        'buffers':[{'byteLength':len(data),'uri':'data:application/octet-stream;base64,'+base64.b64encode(data).decode()}],
        'bufferViews':[{'buffer':0,'byteOffset':0,'byteLength':len(data)}],
        'accessors':[{'bufferView':0,'componentType':5126,'count':3,'type':'VEC3','min':[-1,-1,0],'max':[1,1,0]}]}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel="msedge",headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        def media(route):
            url=route.request.url
            if url.endswith('.gltf'):route.fulfill(body=json.dumps(gltf),content_type='model/gltf+json',headers={'Access-Control-Allow-Origin':'*'})
            elif url.endswith('.png'):route.fulfill(path='scratch/cafe-final-12.png',content_type='image/png')
            else:route.fulfill(path='exports/editor-observed-cafe-20260910.mp4',content_type='video/mp4')
        page.route('https://fixture.example/**',media)
        page.goto(base+'/api/v1/editor-assistant/page')
        page.evaluate('v=>window.__setEditorAuth(v)',{'token':token})
        page.evaluate('c=>window.__updateEditorContext(c)',{'room_id':room,'content_id':cid,'playhead':0,'selected':[]})
        page.evaluate('p=>renderReferences(p)',latest)
        page.wait_for_function('()=>document.querySelectorAll(".visual-entry").length===12')
        assert page.get_by_text('この方向で下書きを作る').count()==0
        page.wait_for_function('()=>document.querySelector("model-viewer")?.loaded===true',timeout=30000)
        page.wait_for_function('()=>document.querySelector(".reference-card video")?.readyState>=2')
        page.locator('#hide-references').click()
        page.locator('#show-presentations').click()
        assert page.locator('#references').is_visible()
        page.evaluate('()=>{window.keptVideo=document.querySelector(".reference-card video");keptVideo.currentTime=3;$("references").scrollTop=0;}')
        more=presentation.present(room,cid,[{'kind':'text','title':'Revision','text':'New direction','revises':latest['items'][0]['id']}])['presentation']
        page.evaluate('p=>renderReferences(p)',more)
        assert page.evaluate('keptVideo===document.querySelector(".reference-card video")')
        assert page.evaluate('$("references").scrollTop')==0
        assert page.locator('#latest-presentation').is_visible()
        page.locator('#earlier-presentations').click()
        page.wait_for_function('()=>document.querySelectorAll(".visual-entry").length===16')
        old=page.locator('.reference-card').first;old.hover()
        focused=old.get_attribute('data-item-id')
        captured=page.evaluate('async()=>await begin(context,"text","この案について",epoch)')
        assert captured['context']['focused_presentation_item']['id']==focused
        page.evaluate('()=>{error(new Error("Permission dismissed"));error(new Error("Permission dismissed"));}')
        assert page.locator('#log .error').count()==0
        assert page.locator('#toast button').count()==1
        page.locator('#toast button').click()
        assert page.locator('#toast').inner_text()==''
        page.locator('#latest-presentation').click()
        page.screenshot(path='scratch/visual-feed-wide.png')
        page.set_viewport_size({'width':420,'height':850})
        page.screenshot(path='scratch/visual-feed-narrow.png')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        composition=presentation.clean_composition(room,{'duration':20,'layers':[{'type':'text','text':'Motion'}]})
        page.evaluate('c=>{window.motion=createProposalPlayer({kind:"composition",composition:c});document.body.append(motion);motion.style="position:fixed;inset:0;background:black;z-index:100";}',composition)
        page.wait_for_function('()=>Number(motion.querySelector("input").value)>.1')
        page.evaluate('()=>motion.style.display="none"')
        page.wait_for_timeout(100)
        stopped=page.evaluate('()=>motion.querySelector("input").value')
        page.wait_for_timeout(200)
        assert page.evaluate('()=>motion.querySelector("input").value')==stopped
        page.evaluate('()=>{motion.dispose();motion.remove();}')
        assert not errors,errors
        print(json.dumps({'room':room,'content':cid,'result':'PASS','checks':'history, 3D, mixed media, stable player, scroll, old focus, dismissed error, narrow viewport'}))
        browser.close()


if __name__=='__main__':main()
