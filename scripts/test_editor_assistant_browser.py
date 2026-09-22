"""Real WebRTC smoke test on an isolated timeline; never edits the user's movie."""
import json
import os
import time
import uuid
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    room = 'assistant-test-' + uuid.uuid4().hex[:8]
    folder = ROOT / 'uploads' / 'production-assets' / room
    folder.mkdir(parents=True)
    seq = {'duration': 10, 'format': '16:9', 'frame_rate': 30, 'tracks': [
        {'id': 'caption', 'type': 'caption', 'clips': [
            {'id': 'target', 'text': '修正する字幕', 'timeline_start': 0, 'timeline_end': 5},
            {'id': 'untouched', 'text': '触らない字幕', 'timeline_start': 5, 'timeline_end': 10}]}]}
    (folder / 'contents.json').write_text(json.dumps([{'id': 'test', 'title': '動作確認', 'timeline': {'sequence': seq}}]), encoding='utf-8')
    (folder / 'assets.json').write_text('[]', encoding='utf-8')
    context = {'room_id': room, 'content_id': 'test', 'playhead': 1,
               'selected': [seq['tracks'][0]['clips'][0]], 'unsaved': False}
    if '--point' in sys.argv:
        context.update(selected=[], pointer={'x': .5, 'y': .88, 't': 1, 'at_ms': int(time.time()*1000)},
            visible_targets=[{'id':'target','text':'修正する字幕','rect':[.2,.8,.6,.15], 'start':0, 'end':5}])
    token = (Path.home() / '.done/native_token.txt').read_text().strip()
    with sync_playwright() as p:
        flags = ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream']
        voice = '--voice' in sys.argv
        if voice:
            flags.append('--use-file-for-fake-audio-capture=' + str(ROOT / ('uploads/assistant-point-command.wav' if '--point' in sys.argv else 'uploads/assistant-test-command.wav')))
        browser = p.chromium.launch(headless=True, args=flags)
        page = browser.new_page(viewport={'width': 380, 'height': 800})
        page.add_init_script('window.__editorBootstrap=' + json.dumps({'token': token}) + ';')
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto('http://127.0.0.1:'+os.getenv('EDITOR_TEST_PORT','8000')+'/api/v1/editor-assistant/page')
        page.evaluate('c => window.__updateEditorContext(c)', context)
        page.locator('#show-chat').click()
        page.locator('#input').fill('選択している字幕を「写真を5枚送ってください」に変更してください。他はそのままで。')
        started = time.monotonic()
        page.locator('#mic' if voice else '#send').click()
        deadline = time.monotonic() + 100
        changed = False
        while time.monotonic() < deadline:
            page.wait_for_timeout(500)
            current = json.loads((folder / 'contents.json').read_text(encoding='utf-8'))[0]['timeline']['sequence']
            if current['tracks'][0]['clips'][0]['text'].replace('。', '').replace('五', '5').strip() == '写真を5枚送ってください':
                changed = True
                break
        print('mode', 'voice' if voice else 'text', 'changed', changed, 'elapsed_s', round(time.monotonic() - started, 1))
        if voice and changed:
            page.locator('#mic').click()
        print('neighbor_preserved', current['tracks'][0]['clips'][1] == seq['tracks'][0]['clips'][1])
        if changed:
            try:
                end = time.monotonic() + 60
                while not page.locator('#input').is_enabled() and time.monotonic() < end:
                    page.wait_for_timeout(500)
            except Exception as exc:
                print('response_still_running', str(exc)[:300])
        print('page_errors', errors)
        print('conversation', page.locator('#log').inner_text()[-1800:])
        page.screenshot(path=str(ROOT / 'uploads' / 'assistant-browser-test.png'))
        page.locator('#disconnect').click()
        browser.close()
        if not changed or errors:
            raise SystemExit(1)
    print('test_room', room)


if __name__ == '__main__':
    main()
