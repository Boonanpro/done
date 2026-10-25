"""A real call on the PC screen, recorded: the owner's voice is a WAV played as Chromium's fake microphone, the chat
page opens as the owner (a short-lived token), the 音声 button starts the call, and the stage (voice_stage) draws while
Dan talks. The screen is recorded by Playwright; both voices are recorded in the page (MediaRecorder on the microphone
and Dan's audio) and muxed into one MP4 afterwards. The scenes the stage showed are logged with their times.

Usage: python scripts/check_voice_stage_call.py <base_url> <token_file> <project_id> <owner.wav> <out_dir> [seconds]
  base_url     the screens (http://127.0.0.1:3002 for `work.py try`, http://127.0.0.1:3000 for the owner's screen)
  token_file   a file holding the owner's access token (auth_service.create_access_token)
  project_id   the chat to open (/chat/<project_id>); the call is in that chat's room
  owner.wav    what the owner says, with the pauses in which Dan answers (48 kHz mono)
  seconds      how long after the call connects to hang up (default: the WAV's length + 12)
Writes <out_dir>/call.mp4 (screen + both voices), <out_dir>/scenes.json (the stage's versions with times, the captions)
and <out_dir>/screen-<version>.png (one frame per scene).
"""
import asyncio
import base64
import json
import subprocess
import sys
import time
import wave
from pathlib import Path

from playwright.async_api import async_playwright

VIEWPORT = {'width': 1000, 'height': 820}   # the call's panel (520px, bottom right) takes half of it

# before any page script: keep the microphone stream so the page can record it with Dan's voice
KEEP_MIC = '''
(() => {
  const real = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = async (c) => { const s = await real(c); if (c && c.audio) window.__mic = s; return s; };
})();
'''

START_RECORDER = '''
async () => {
  const audio = document.querySelector('audio');
  const remote = audio && audio.srcObject;
  if (!remote || !window.__mic) return 'no streams';
  const ctx = new AudioContext();
  const dest = ctx.createMediaStreamDestination();
  ctx.createMediaStreamSource(remote).connect(dest);
  ctx.createMediaStreamSource(window.__mic).connect(dest);
  window.__chunks = [];
  const rec = new MediaRecorder(dest.stream, {mimeType: 'audio/webm;codecs=opus'});
  rec.ondataavailable = e => { if (e.data.size) window.__chunks.push(e.data); };
  rec.start(500);
  window.__rec = rec;
  return 'recording';
}
'''

STOP_RECORDER = '''
async () => {
  const rec = window.__rec;
  if (!rec) return '';
  await new Promise(r => { rec.onstop = r; rec.stop(); });
  const blob = new Blob(window.__chunks, {type: 'audio/webm'});
  const buf = await blob.arrayBuffer();
  let s = ''; const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}
'''

READ_STAGE = '''
() => {
  const stage = document.querySelector('[data-voice-stage]');
  const status = document.querySelector('[data-voice-status]');
  return {version: stage ? stage.getAttribute('data-voice-stage') : null,
          caption: stage ? (stage.querySelector('[data-stage-caption]') || {}).textContent || '' : '',
          scene: !!(stage && stage.querySelector('[data-stage-scene]')),
          connecting: !!Array.from(document.querySelectorAll('div')).find(d => d.textContent === '接続中…'),
          panel: !!document.querySelector('button[aria-label="音声モードを閉じる"]'),
          note: (Array.from(document.querySelectorAll('.text-destructive')).map(d => d.textContent).join(' | ') || '').slice(0, 200),
          audio: !!(document.querySelector('audio') && document.querySelector('audio').srcObject)};
}
'''


def wav_seconds(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


async def main(base, token_file, project_id, wav, out_dir, seconds=None):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    token = Path(token_file).read_text().strip()
    total = float(seconds) if seconds else wav_seconds(wav) + 12
    log = []
    def mark(kind, **f): log.append({'t': round(time.monotonic() - t0, 2), 'kind': kind, **f})
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
                                                f'--use-file-for-fake-audio-capture={Path(wav).resolve()}%noloop',
                                                '--autoplay-policy=no-user-gesture-required'])
        context = await browser.new_context(viewport=VIEWPORT, record_video_dir=str(out), record_video_size=VIEWPORT,
                                            locale='ja-JP', timezone_id='Asia/Tokyo', color_scheme='dark')
        await context.add_init_script(KEEP_MIC)
        await context.add_init_script(f"localStorage.setItem('done-token', {json.dumps(token)});")
        page = await context.new_page()
        t0 = time.monotonic()   # the video starts with the page
        await page.goto(f'{base}/chat/{project_id}', wait_until='domcontentloaded')
        await page.get_by_role('button', name='音声').wait_for(timeout=60000)
        await page.wait_for_timeout(1500)
        mark('page_ready')
        await page.get_by_role('button', name='音声').click()
        mark('clicked')
        # connected: the remote audio arrived and 「接続中…」 is gone
        for _ in range(120):
            st = await page.evaluate(READ_STAGE)
            if st['audio'] and not st['connecting']: break
            await page.wait_for_timeout(500)
        else:
            raise SystemExit('the call did not connect: ' + json.dumps(st, ensure_ascii=False))
        mark('connected')
        t_call = time.monotonic()
        rec = await page.evaluate(START_RECORDER)
        t_audio = time.monotonic()
        mark('recorder', state=rec)
        seen = None
        while time.monotonic() - t_call < total:
            st = await page.evaluate(READ_STAGE)
            key = (st['version'], st['caption'], st['scene'])
            if key != seen:
                seen = key
                mark('stage', version=st['version'], caption=st['caption'].replace('今の話: ', ''), scene=st['scene'])
                if st['scene']:
                    await page.wait_for_timeout(400)   # the fade-in
                    await page.screenshot(path=str(out / f"screen-{st['version']}.png"))
            await page.wait_for_timeout(300)
        audio_b64 = await page.evaluate(STOP_RECORDER)
        mark('hangup', state=await page.evaluate(READ_STAGE))
        close = page.get_by_role('button', name='音声モードを閉じる')
        if await close.count(): await close.click()   # gone already when the call ended by itself
        else: mark('panel_gone')
        await page.wait_for_timeout(2500)
        await context.close()
        video_path = await page.video.path()
        await browser.close()
    (out / 'voices.webm').write_bytes(base64.b64decode(audio_b64)) if audio_b64 else None
    offset = t_audio - t0
    (out / 'scenes.json').write_text(json.dumps({'base': base, 'project_id': project_id, 'audio_offset_s': round(offset, 2),
                                                 'total_s': total, 'events': log}, ensure_ascii=False, indent=1), encoding='utf-8')
    if audio_b64:
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', video_path, '-itsoffset', f'{offset:.2f}', '-i', str(out / 'voices.webm'),
                        '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac', '-b:a', '128k', '-shortest', '-movflags', '+faststart', str(out / 'call.mp4')], check=True)
    else:
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', video_path, '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
                        '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(out / 'call.mp4')], check=True)
    for e in log:
        print(e)
    print('video', out / 'call.mp4')


if __name__ == '__main__':
    asyncio.run(main(*sys.argv[1:7]))
