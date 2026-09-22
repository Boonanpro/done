"""Verify the actual embedded panel and native Undo on a disposable document."""
import ctypes
import json
import os
import subprocess
import time
import uuid
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    room = 'assistant-native-test-' + uuid.uuid4().hex[:8]
    folder = ROOT / 'uploads/production-assets' / room
    folder.mkdir(parents=True)
    seq = {'duration': 10, 'format': '16:9', 'frame_rate': 30, 'tracks': [
        {'id': 'caption', 'type': 'caption', 'clips': [
            {'id': 'target', 'text': '変更前の字幕', 'timeline_start': 0, 'timeline_end': 5},
            {'id': 'neighbor', 'text': '触らない字幕', 'timeline_start': 5, 'timeline_end': 10}]}]}
    contents = folder / 'contents.json'
    contents.write_text(json.dumps([{'id': 'test', 'title': '会話パネル動作確認', 'timeline': {'format':'16:9','sequence': seq}}]), encoding='utf-8')
    (folder / 'assets.json').write_text('[]', encoding='utf-8')
    token = os.environ.get('EDITOR_TEST_TOKEN') or (Path.home() / '.done/native_token.txt').read_text().strip()
    native_token = token
    if '--expired-auth' in sys.argv:
        assert os.environ.get('EDITOR_TEST_TOKEN'), 'Expired-auth tests require an isolated test identity'
        from datetime import timedelta
        from app.services.auth_service import decode_access_token, create_access_token, create_refresh_token
        identity = decode_access_token(token)
        native_token = create_access_token(identity.user_id, identity.email, timedelta(seconds=-1))
        credentials = folder / 'test-user' / '.done'
        credentials.mkdir(parents=True)
        (credentials / 'native_token.txt').write_text(native_token)
        (credentials / 'native_refresh_token.txt').write_text(create_refresh_token(identity.user_id, identity.email))
    exe = ROOT / 'scripts/poc/production_desktop/native_ui/target/release/native_ui.exe'
    voice = '--voice' in sys.argv
    keyboard = '--keyboard' in sys.argv
    flags = '--remote-debugging-port=9226'
    if keyboard:
        import wave
        silence=folder/'silence.wav'
        with wave.open(str(silence),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(48000);f.writeframes(b'\0\0'*48000*30)
        flags += ' --use-fake-ui-for-media-stream --use-fake-device-for-media-stream --use-file-for-fake-audio-capture='+str(silence)
    if voice:
        flags += ' --use-fake-ui-for-media-stream --use-fake-device-for-media-stream --use-file-for-fake-audio-capture=' + str(ROOT/'uploads/assistant-point-command.wav')
    proc = subprocess.Popen([str(exe), str(contents), str(folder)],
        env={**os.environ, 'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS': flags,
             **({'DONE_TOKEN': native_token, 'DONE_NATIVE_AUTH_DIR': str(folder / 'test-user' / '.done')} if os.environ.get('EDITOR_TEST_TOKEN') else {}),
             'WEBVIEW2_USER_DATA_FOLDER': str(folder / 'webview')},
        stdout=subprocess.DEVNULL, stderr=(folder / 'native.log').open('w', encoding='utf-8'))
    try:
        with sync_playwright() as p, httpx.Client(headers={'Authorization': 'Bearer '+token}, timeout=20) as client:
            deadline = time.monotonic() + 30
            browser = None
            while time.monotonic() < deadline:
                try:
                    browser = p.chromium.connect_over_cdp('http://127.0.0.1:9226')
                    break
                except Exception:
                    time.sleep(.5)
            assert browser is not None, 'native WebView did not start'
            page = None
            for _ in range(120):
                page = next((x for c in browser.contexts for x in c.pages if 'editor-assistant/page' in x.url), None)
                if page:
                    break
                pages = [x for c in browser.contexts for x in c.pages]
                if pages:
                    pages[0].wait_for_timeout(250)
                else:
                    time.sleep(.25)
            if page is None:
                import pyautogui
                pyautogui.screenshot().save(str(ROOT / 'uploads/assistant-test-failure.png'))
            assert page is not None, f'embedded assistant missing: process={proc.poll()}, pages={[x.url for c in browser.contexts for x in c.pages]}, log={(folder / "native.log").read_text(encoding="utf-8")[-1500:]}'
            page.wait_for_selector('#target')
            page.wait_for_timeout(1600)
            if '--expired-auth' in sys.argv:
                assert page.evaluate("api('/auth',{})")['ok']
                renewed = (credentials / 'native_token.txt').read_text()
                assert decode_access_token(renewed).user_id == identity.user_id
                assert renewed != native_token
                print('expired_native_login_renewed', True, flush=True)
            print('embedded_panel', page.locator('#target').inner_text())
            assert page.evaluate("async () => (await api('/auth',{})).ok"), 'embedded authentication failed'
            # Reproduce the original load-order failure: the token arrives after JS.
            page.evaluate("window.__editorBootstrap={}")
            assert page.evaluate("async () => (await api('/auth',{})).ok"), 'late authentication did not recover'
            focus = page.evaluate("""async () => editorAction({kind:'focus',content_id:'test',t:1,
                start:0,end:5,rect:context.visible_targets.find(t=>t.id==='target').rect,label:'この字幕？'})""")
            assert focus['ok'], focus
            page.wait_for_timeout(1000)
            assert page.evaluate('context.playhead') == 1
            import pyautogui
            pyautogui.screenshot().save(str(ROOT / 'uploads/assistant-native-focus.png'))
            print('native_auth_and_focus', True)
            def current():
                return json.loads(contents.read_text(encoding='utf-8'))[0]['timeline']['sequence']
            before = current()
            before_rect = page.evaluate("context.visible_targets.find(t=>t.id==='target').rect")
            if keyboard:
                windows=[]
                @ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
                def foreground(hwnd,_):
                    pid=ctypes.c_ulong();ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                    if pid.value==proc.pid and ctypes.windll.user32.IsWindowVisible(hwnd):windows.append(hwnd)
                    return True
                ctypes.windll.user32.EnumWindows(foreground,0)
                assert windows
                pyautogui.press('alt')
                ctypes.windll.user32.ShowWindow(windows[0],9)
                ctypes.windll.user32.SetForegroundWindow(windows[0])
                page.wait_for_timeout(300)
                focused_pid=ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(ctypes.windll.user32.GetForegroundWindow(),ctypes.byref(focused_pid))
                assert focused_pid.value==proc.pid,'Test window must be foreground before sending OS keys'
                page.locator('#mic').click()
                page.wait_for_function('()=>micOn',timeout=30000)
                page.wait_for_timeout(500)
                def space_plays_and_stops():
                    start=page.evaluate('context.playhead')
                    pyautogui.press('space');page.wait_for_timeout(1000)
                    if page.evaluate('context.playhead')<=start+.3:
                        pyautogui.screenshot().save(str(ROOT/'uploads/assistant-keyboard-failure.png'))
                        print('keyboard_debug',page.evaluate('({focus:document.activeElement?.id,documentFocus:document.hasFocus(),micOn,context})'),flush=True)
                    assert page.evaluate('context.playhead')>start+.3,'Space did not play timeline'
                    pyautogui.press('space');page.wait_for_timeout(400)
                    stop=page.evaluate('context.playhead');page.wait_for_timeout(500)
                    assert abs(page.evaluate('context.playhead')-stop)<.05,'Space did not stop timeline'
                space_plays_and_stops()
                assert page.evaluate('micOn'),'Space toggled microphone'
                page.locator('#clear').click();page.wait_for_timeout(300)
                space_plays_and_stops()
                assert page.evaluate('micOn')
                page.locator('#input').click();page.locator('#input').fill('text')
                page.wait_for_timeout(300)
                stop=page.evaluate('context.playhead');pyautogui.press('space');page.wait_for_timeout(500)
                assert page.locator('#input').input_value()=='text '
                assert abs(page.evaluate('context.playhead')-stop)<.05
                assert current()==before
                print('PASS microphone click and other button return Space to timeline; text input retains spaces',flush=True)
                page.locator('#mic').click()
                return
            body = {'room_id': room, 'content_id': 'test', 'playhead': 1, 'selected': [seq['tracks'][0]['clips'][0]]}
            started = client.post('http://127.0.0.1:8000/api/v1/editor-assistant/begin', json=body)
            started.raise_for_status()
            if voice:
                windows=[]
                @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
                def find(hwnd, _):
                    pid=ctypes.c_ulong()
                    ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                    if pid.value==proc.pid and ctypes.windll.user32.IsWindowVisible(hwnd): windows.append(hwnd)
                    return True
                ctypes.windll.user32.EnumWindows(find,0)
                assert windows
                from ctypes.wintypes import POINT
                origin=POINT(0,0)
                ctypes.windll.user32.ClientToScreen(windows[0],ctypes.byref(origin))
                viewport=page.evaluate('context.preview_viewport')
                box=page.evaluate("context.visible_targets.find(t=>t.id==='target').rect")
                x=origin.x+(viewport['x']+(box[0]+box[2]/2)*viewport['w'])*viewport['scale']
                y=origin.y+(viewport['y']+(box[1]+box[3]/2)*viewport['h'])*viewport['scale']
                pyautogui.moveTo(x,y,duration=.2)
                page.wait_for_timeout(600)
                pointer=page.evaluate('context.pointer')
                assert abs(pointer['x']-(box[0]+box[2]/2))<.05, pointer
                assert page.evaluate('context.selected.length')==0
                page.locator('#mic').click()
                deadline=time.monotonic()+75
                while time.monotonic()<deadline:
                    page.wait_for_timeout(500)
                    if '写真' in current()['tracks'][0]['clips'][0]['text']: break
                page.locator('#mic').click()
                assert '写真' in current()['tracks'][0]['clips'][0]['text'], page.locator('#log').inner_text()
                assert current()['tracks'][0]['clips'][1]==before['tracks'][0]['clips'][1]
                print('native_pointer_voice_edit',True,flush=True)
                print('conversation',page.locator('#log').inner_text(),flush=True)
            else:
                changed = client.post('http://127.0.0.1:8000/api/v1/editor-assistant/tool', json={
                    'room_id': room, 'turn_id': started.json()['turn_id'], 'name': 'resize_captions' if '--size' in sys.argv else 'timeline_edit',
                    'args': {'clip_ids':['target'],'factor':1.5} if '--size' in sys.argv else {'op': 'set_clip', 'args': {'clip_id': 'target', 'text': '変更後の字幕'}}})
                assert changed.json().get('committed'), changed.text
            page.wait_for_timeout(2800)
            if '--size' in sys.argv:
                assert current()['tracks'][0]['clips'][0]['style']['fontSize']==1.5
                after_rect=page.evaluate("context.visible_targets.find(t=>t.id==='target').rect")
                assert after_rect[2]>before_rect[2]*1.3 and after_rect[3]>before_rect[3]*1.3,(before_rect,after_rect)
                assert current()['tracks'][0]['clips'][1]==before['tracks'][0]['clips'][1]
                pyautogui.screenshot().save(str(ROOT/'uploads/assistant-native-size-after.png'))
                print('native_size_visible',before_rect,after_rect,flush=True)
            else:
                assert current()['tracks'][0]['clips'][0]['text'] != '変更前の字幕'
            page.locator('#undo').click()
            page.wait_for_timeout(2200)
            assert current() == before, 'native Undo did not restore the previous document'
            print('native_undo', True)
            page.screenshot(path=str(ROOT / 'uploads/assistant-native-test-panel.png'))
    finally:
        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def close(hwnd, _):
            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == proc.pid:
                ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
            return True
        ctypes.windll.user32.EnumWindows(close, 0)
        proc.wait(timeout=15)


if __name__ == '__main__':
    main()
