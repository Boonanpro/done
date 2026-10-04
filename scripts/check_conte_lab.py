"""Exercise real semantic editing and a real LIVE1 audio/tool round trip."""
import asyncio,json,wave,time
from pathlib import Path
import httpx
from playwright.async_api import async_playwright
from app.config import settings
OUT=Path('scratch/conte-lab');OUT.mkdir(parents=True,exist_ok=True)

async def main():
    audio=OUT/'voice-test.wav'
    if not audio.exists():
        async with httpx.AsyncClient(timeout=60) as c:
            r=await c.post('https://api.openai.com/v1/audio/speech',headers={'Authorization':'Bearer '+settings.OPENAI_API_KEY},json={
                'model':'gpt-4o-mini-tts','voice':'ash','response_format':'wav',
                'input':'男を作業台の手前まで歩かせて、着いたらしゃがんでほしい。歩くのは四秒くらい。カメラは全体が見えるようにして。',
                'instructions':'自然な日本語の会話。操作を頼む成人男性。落ち着いた速さで、機械的に読み上げない。'})
            r.raise_for_status();audio.write_bytes(r.content)
    second=OUT/'voice-second.wav'
    if not second.exists():
        async with httpx.AsyncClient(timeout=60) as c:
            r=await c.post('https://api.openai.com/v1/audio/speech',headers={'Authorization':'Bearer '+settings.OPENAI_API_KEY},json={
                'model':'gpt-4o-mini-tts','voice':'ash','response_format':'wav',
                'input':'今の動きを全体で半分の時間にして。他の配置はそのままで。',
                'instructions':'自然な日本語の会話。成人男性が普通に編集を頼む口調。'})
            r.raise_for_status();second.write_bytes(r.content)
    # Feed once, with enough trailing silence to prevent the fake microphone loop.
    with wave.open(str(audio),'rb') as w:params=w.getparams();frames=w.readframes(w.getnframes())
    with wave.open(str(second),'rb') as w:second_frames=w.readframes(w.getnframes());assert w.getframerate()==params.framerate
    silence=lambda seconds:b'\0'*(params.framerate*params.nchannels*params.sampwidth*seconds)
    padded=OUT/'voice-padded.wav'
    with wave.open(str(padded),'wb') as w:
        w.setparams(params._replace(nframes=0));w.writeframes(silence(12)+frames+silence(18)+second_frames+silence(90))
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--use-file-for-fake-audio-capture='+str(padded.resolve())])
        context=await browser.new_context(viewport={'width':1440,'height':1000},permissions=['microphone'],record_video_dir=str(OUT/'recording'))
        page=await context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto('http://127.0.0.1:3018');await page.wait_for_function('!!window.conteLab')
        await page.get_by_role('button',name='LIVE1で話す',exact=True).click()
        try:
            await page.wait_for_function('window.conteLab.live',timeout=45000)
            await page.wait_for_function("window.conteLab.state.objects.find(o=>o.id==='man').actions.length>=2",timeout=60000)
            state=await page.evaluate('window.conteLab.state')
            actions=next(o for o in state['objects'] if o['id']=='man')['actions']
            assert actions[0]['type']=='walk' and actions[1]['type']=='crouch',actions
            first=state
            await page.wait_for_function("window.conteLab.state.objects.find(o=>o.id==='man').actions[0]?.duration===2",timeout=60000)
            state=await page.evaluate('window.conteLab.state')
            assert state['objects'][1:]==first['objects'][1:]
            await page.wait_for_timeout(3500)
            assert not await page.evaluate('window.conteLiveErrors')
            await page.evaluate('window.conteLab.setTime(5)');await page.wait_for_timeout(600)
            await page.screenshot(path=str(OUT/'voice-result.png'))
            result={'ok':True,'state':state,'browser_errors':errors}
        except Exception as e:
            result={'ok':False,'error':str(e),'status':await page.locator('#status').inner_text(),'browser_errors':errors}
        finally:
            if await page.get_by_role('button',name='会話を終了',exact=True).count():await page.get_by_role('button',name='会話を終了',exact=True).click()
            await context.close();await browser.close()
        (OUT/'voice-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False))
        assert result['ok'],result

if __name__=='__main__':asyncio.run(main())
