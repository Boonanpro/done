"""Verify actual WebRTC renewal and production cards without starting an edit."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

token=(Path.home()/'.done/native_token.txt').read_text().strip()
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream'])
    page=browser.new_page(viewport={'width':430,'height':900})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
    page.goto('http://127.0.0.1:8011/api/v1/editor-assistant/page')
    page.evaluate("async()=>{record('user_transcript',{text:'HeyGenで声を作る。背景4つ全部を動画にする。'});await connect();}")
    page.evaluate("async()=>{await toggleMic();}")
    assert page.evaluate("micOn&&mic.getAudioTracks()[0].enabled")
    page.evaluate("async()=>{await renewSession();}")
    assert page.evaluate("dc.readyState==='open'&&micOn&&mic.getAudioTracks()[0].enabled&&conversationMemory.some(m=>m.text.includes('HeyGen'))")
    fake={'jobs':[{'id':'testjob','status':'running','pending_instructions':1,'activity':[{'tool':'generate_video','model':'gemini_omni','state':'running','category':'generation','clip_ids':['a']}]}]}
    page.evaluate('(s)=>renderProductionStatus(s,{room_id:"ui-only",content_id:"ui-only"})',fake)
    assert page.locator('.production-card.running').count()==1
    assert page.locator('.activity-steps .current').inner_text()=='素材制作'
    page.screenshot(path='uploads/editor-recovery-check/production-cards.png')
    fake['jobs'][0].update(status='failed',error='接続先から動画を取得できませんでした')
    page.evaluate('(s)=>renderProductionStatus(s,{room_id:"ui-only",content_id:"ui-only"})',fake)
    assert page.locator('.production-card.running').count()==0
    assert page.locator('.production-card.failed').count()==0
    assert page.locator('#log').inner_text().count('作業が止まりました')==1
    fake['work']=[{'id':'account','title':'HeyGenの本人音声を準備','status':'blocked','note':'使うアカウントの確認待ちです。'}]
    page.evaluate('(s)=>renderProductionStatus(s,{room_id:"ui-only",content_id:"ui-only"})',fake)
    assert page.locator('.production-card.blocked').count()==0
    page.screenshot(path='uploads/editor-recovery-check/production-waiting.png')
    page.evaluate('disconnect()');browser.close()
    assert not errors,errors
print('PASS real session renewal, preserved service instruction, animated running card, visible terminal failure')
