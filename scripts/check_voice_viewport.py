"""Exercise the real phone stage + viewport report + browser reflow without a call.
Uses an isolated public-page fixture, no account writes, no room browser profile.
"""
import asyncio,json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from playwright.async_api import async_playwright
from app.services import voice_viewport as V, voice_stage as S

async def main():
    output=ROOT/'.data/viewport-proof';output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        V.ROOT=Path(tmp)
        state={'active':True,'session_id':'test-call','version':1,'image':'/api/v1/voicelog/stage/test-room/image/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg','caption':'部品の接続条件'}
        S.read_state=lambda room:state
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(headless=True)
            source=await browser.new_page(viewport={'width':1440,'height':900})
            await source.set_content('<meta name="viewport" content="width=device-width"><style>body{margin:0;font:20px sans-serif;background:white}.menu{width:260px;float:left;background:#eee;height:900px}.article{margin-left:280px;padding:20px;max-width:800px} @media(max-width:600px){.menu{display:none}.article{margin:0;padding:16px}}</style><nav class="menu">製品一覧</nav><main class="article"><h1>メガネの表示部品</h1><p>文字を読める表示サイズと接続条件を確認します。</p><h2>接続に必要なもの</h2><p>表示部品と接続基板の組み合わせを確認し、見積もりを待っています。</p><input aria-label="メモ" value="見積もり待ち"></main>')
            before=await source.screenshot(type='jpeg')
            viewer=await browser.new_page(viewport={'width':390,'height':700})
            seen=[];frames={'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg':before}
            async def serve(route):
                url=route.request.url
                if '/image/' in url:
                    await route.fulfill(body=frames[url.rsplit('/',1)[1]],content_type='image/jpeg');return
                if url.endswith('/viewport'):
                    body=route.request.post_data_json;seen.append(body)
                    await route.fulfill(json={'accepted':V.accept('test-room',state,body)});return
                await asyncio.sleep(.1)
                await route.fulfill(json=dict(state))
            await viewer.route('**/api/v1/voicelog/stage/**',serve)
            await viewer.goto('http://127.0.0.1:3036/voice-stage?room=test-room')
            await viewer.locator('img[alt="部品の接続条件"]').wait_for()
            await asyncio.sleep(.4)
            await viewer.screenshot(path=str(output/'before.png'))
            for _ in range(60):
                if V.current('test-room'):break
                await asyncio.sleep(.1)
            assert V.current('test-room'),seen
            await V.fit(source,'test-room')
            frames['bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg']=await source.screenshot(type='jpeg')
            state.update(version=2,image='/api/v1/voicelog/stage/test-room/image/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg')
            await viewer.wait_for_function('document.querySelector("img")?.naturalWidth < 600')
            await asyncio.sleep(.4)
            await viewer.screenshot(path=str(output/'after.png'))
            assert not await source.locator('nav').is_visible()
            assert await source.locator('input').input_value()=='見積もり待ち'
            report={'reported':seen,'actual_browser_viewport':source.viewport_size,'scope':'Real stage frontend and viewport POST with isolated responsive page; not an actual voice call.'}
            (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(report)
            await browser.close()
asyncio.run(main())
