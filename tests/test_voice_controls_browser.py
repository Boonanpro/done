"""Exercise the real shared bridge in Chromium, without an account or backend."""
import asyncio,json,subprocess,uuid
from pathlib import Path
import pytest
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.asyncio
async def test_real_dom_controls_and_refusal_boundaries():
    js=subprocess.check_output(['node','-e',"const fs=require('fs'),ts=require('./node_modules/typescript');process.stdout.write(ts.transpileModule(fs.readFileSync('src/components/artifacts/voice-controls.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText)"],cwd=ROOT/'frontend',text=True)
    child='''<html><head><meta charset="utf-8"></head><body><label for="q">検索</label><input id="q"><input type="password" aria-label="暗証番号" value="secret"><input type="file"><select aria-label="表示"><option>一覧</option><option>地図</option></select><button id="open">開く</button><button id="send">送信</button><button id="unknown">謎の処理</button><script>window.clicks=0;window.inputs=0;document.querySelector('#open').onclick=()=>{window.clicks++};document.querySelector('#send').onclick=()=>{window.clicks+=100};document.querySelector('#q').oninput=()=>{window.inputs++};</script><script>const exports={};JS;exports.installVoiceControls();</script></body></html>'''.replace('JS',js)
    parent='''<iframe src="/artifacts/fixture?call=1" style="width:800px;height:600px"></iframe><script>window.receipts=[];addEventListener('message',e=>{if(e.data.type==='dan-screen-ready')e.source.postMessage({type:'dan-screen-connect'},location.origin);if(e.data.screen)window.observed=e.data.screen;if(e.data.type==='dan-screen-result')window.receipts.push(e.data);});</script>'''
    async with async_playwright() as p:
      b=await p.chromium.launch(headless=True)
      page=await b.new_page()
      await page.route('http://voice.localhost/**',lambda r:r.fulfill(content_type='text/html',body=child if '/artifacts/' in r.request.url else parent))
      await page.goto('http://voice.localhost/host');await page.wait_for_function('window.observed')
      frame=page.frames[1]
      snapshot=await page.evaluate('window.observed')
      assert not any(c['name']=='暗証番号' for c in snapshot['controls'])
      async def make(name,op='click',**fields):
        snapshot=await page.evaluate('window.observed')
        control=next(c for c in snapshot['controls'] if c['name']==name)
        return {'request_id':uuid.uuid4().hex,'page_id':snapshot['page_id'],'target':control['id'],'fingerprint':control['fingerprint'],'op':op,**fields}
      async def send(command):
        count=await page.evaluate('window.receipts.length')
        await page.evaluate("c=>document.querySelector('iframe').contentWindow.postMessage({type:'dan-screen-command',command:c},location.origin)",command)
        await page.wait_for_function('n=>window.receipts.length>n',arg=count)
        return await page.evaluate('window.receipts.at(-1).result')
      assert (await send(await make('検索','fill',value='顧客')) )['ok']
      assert await frame.locator('#q').input_value()=='顧客'
      assert await frame.evaluate('window.inputs')==1
      assert (await send(await make('表示','select',value='地図')))['ok']
      assert await frame.locator('select').input_value()=='地図'
      assert not (await send(await make('送信')))['ok']
      assert not (await send(await make('謎の処理')))['ok']
      command=await make('開く')
      assert (await send(command))['ok']
      await page.evaluate("c=>document.querySelector('iframe').contentWindow.postMessage({type:'dan-screen-command',command:c},location.origin)",command)
      await page.wait_for_timeout(100)
      assert await frame.evaluate('window.clicks')==1
      assert not (await send(await make('開く',page_id='old-page')))['ok']
      old=await make('開く');await frame.locator('#open').evaluate("el=>el.textContent='消去'")
      assert not (await send(old))['ok']
      await frame.locator('#open').evaluate("el=>el.textContent='開く'")
      await page.wait_for_timeout(150)
      await frame.evaluate("()=>{const d=document.createElement('div');d.id='overlay';d.style='position:fixed;inset:0;background:white;z-index:99';document.body.appendChild(d)}")
      assert not (await send(await make('開く')))['ok']
      await frame.locator('#overlay').evaluate('el=>el.remove()')
      snapshot=await page.evaluate('window.observed')
      guarded=await make('送信',authorized=True,guard={'text':snapshot['text'],'values':[[c['id'],c['name'],c.get('value'),c['fingerprint']] for c in snapshot['controls']]})
      await frame.locator('#q').fill('別の宛先')
      assert not (await send(guarded))['ok']
      assert await frame.evaluate('window.clicks')==1
      await b.close()
