"""Real inspection browser: audio/video progress with speaker output disabled.
Uses a disposable profile, never the owner's room/authenticated profile.
"""
import asyncio
import base64
import io
import json
import math
import struct
import tempfile
import wave
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.tools.browser import _spawn_detached_browser, _pick_free_port, _connect_detached_browser
from playwright.async_api import async_playwright

async def main():
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wav:
        wav.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b''.join(struct.pack('<h', int(1000 * math.sin(i * .1))) for i in range(16000)))
    src = 'data:audio/wav;base64,' + base64.b64encode(buf.getvalue()).decode()
    with tempfile.TemporaryDirectory(prefix='dan-silent-proof-') as profile:
        async with async_playwright() as pw:
            port = _pick_free_port()
            _spawn_detached_browser(pw.chromium.executable_path, profile, port)
            browser = await _connect_detached_browser(pw, port)
            try:
                page = await browser.contexts[0].new_page()
                await page.goto('chrome://version')
                command = await page.locator('#command_line').inner_text()
                assert '--mute-audio' in command, 'Browser speaker output not disabled'
                cases = []
                for tag in ['audio', 'video']:
                    await page.goto('about:blank')
                    await page.set_content(f'<{tag} controls></{tag}><button>Play</button>')
                    await page.evaluate('''({src,tag})=>{const m=document.querySelector(tag); m.src=src; document.querySelector('button').onclick=()=>m.play()}''', {'src':src,'tag':tag})
                    await page.click('button')
                    await page.wait_for_function('(tag)=>document.querySelector(tag).currentTime > .2', arg=tag)
                    state = await page.locator(tag).evaluate('(m)=>({time:m.currentTime,paused:m.paused,error:m.error})')
                    assert not state['paused'] and not state['error']
                    cases.append({'element':tag, **state})
                print(json.dumps({'speaker_output_disabled':True, 'playback':cases}))
            finally:
                await browser.close()

asyncio.run(main())
