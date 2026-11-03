"""A real call with Dan, where the owner's side is played from the owner's goal, then graded (2026-11-03).

Why: the owner refused a check that replayed the 13:35 call word for word (「40kgじゃん」 is only said when Dan gets the
weight wrong, so replaying it after a fix tests nothing). Here the owner's side is decided turn by turn from the goal and
from what Dan actually said and showed, the way a person on the phone does it:

  - The chat page opens in Chromium as the owner (a short-lived token) in a fresh room made for this run, and its 音声
    button starts the same call the owner starts (WebRTC to the speech model, the server's sideband, the backend).
  - The microphone is replaced by an audio stream this script feeds. Each thing the owner says is written by a model
    (OWNER_MODEL) from the scenario's goal and manner, the conversation so far (Dan's words as the call transcribed them)
    and the pages on the call's screen (opened and read here: title, can it be bought). It is turned into speech
    (gpt-4o-mini-tts) and played into that stream. The model only plays the owner; it never grades.
  - The run ends when the call closes or after the scenario's max_seconds. run.json keeps both sides with times, the
    pages shown (from the sideband log, by session), when the owner asked to hang up and when the call closed;
    voices.webm and the screen video are kept beside it.
  - Then scripts/voice_goal_grade.py grades run.json from facts (the pages, the times).

Usage: python scripts/voice_goal_call.py <screens base> <scenario.json> <out dir> [--keep-room] [--log <sideband log>]
  screens base  http://127.0.0.1:3002 for `work.py try` (the worktree's API), http://127.0.0.1:3000 for the running Dan
  --log         the sideband log of the API that serves the call (default: this tree's .tmp/voice-sideband.jsonl; the
                running Dan's is /Users/mikihonda/done/.tmp/voice-sideband.jsonl)
The room is deleted after the run unless --keep-room (the room's history would otherwise reach the next call).
Costs: one call of the speech model for up to max_seconds, plus the owner's lines (a few cents).
"""
import asyncio
import base64
import json
import re
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from dotenv import load_dotenv
load_dotenv('/Users/mikihonda/done/.env')
load_dotenv(ROOT / '.env')

import voice_goal_grade as grader

OWNER_MODEL = 'gpt-6.1-terra'
TTS_MODEL, TTS_VOICE = 'gpt-4o-mini-tts', 'ash'
VIEWPORT = {'width': 1000, 'height': 820}
DAN_QUIET_S = 2.5        # Dan's turn has ended when no words and no sound came for this long
FIRST_WORDS_S = 25.0     # waiting for Dan to say anything after the owner spoke
HANGUP_WAIT_S = 30.0     # long enough to measure a slow close; the grade allows less

# Before any page script: the microphone is a stream this script plays into (window.__say), and the call's event channel
# is read as it arrives (transcripts, session.closed) into window.__ev.
INIT = r'''
(() => {
  window.__ev = [];
  let ctx = null, dest = null, aiAnalyser = null;
  const ensure = () => {
    if (!ctx) {
      ctx = new AudioContext({sampleRate: 48000});
      dest = ctx.createMediaStreamDestination();
      const hold = ctx.createConstantSource(); hold.offset.value = 0; hold.connect(dest); hold.start();
      window.__mixCtx = ctx; window.__mixDest = dest;
    }
    return ctx;
  };
  navigator.mediaDevices.getUserMedia = async (c) => {
    // A fresh track each time, like a real microphone: the page stops the tracks of its first connect (React runs the
    // effect twice in development), and a stopped shared track would leave the call silent.
    if (c && c.audio) { ensure(); await ctx.resume(); return new MediaStream([dest.stream.getAudioTracks()[0].clone()]); }
    throw new Error('video is not used');
  };
  window.__say = async (b64, rate) => {
    ensure(); await ctx.resume();
    const bin = atob(b64); const n = bin.length >> 1;
    const buf = ctx.createBuffer(1, n, rate); const ch = buf.getChannelData(0);
    for (let i = 0; i < n; i++) { let v = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8); if (v >= 32768) v -= 65536; ch[i] = v / 32768; }
    const src = ctx.createBufferSource(); src.buffer = buf; src.connect(dest);
    const start = performance.now(); src.start();
    await new Promise(r => { src.onended = r; });
    return [start, performance.now()];
  };
  window.__aiLevel = () => {
    const audio = document.querySelector('audio');
    if (!audio || !audio.srcObject) return 0;
    if (!aiAnalyser) { ensure(); const s = ctx.createMediaStreamSource(audio.srcObject); aiAnalyser = ctx.createAnalyser(); aiAnalyser.fftSize = 1024; s.connect(aiAnalyser); }
    const a = new Float32Array(1024); aiAnalyser.getFloatTimeDomainData(a);
    return Math.sqrt(a.reduce((s, x) => s + x * x, 0) / a.length);
  };
  const open = RTCPeerConnection.prototype.createDataChannel;
  RTCPeerConnection.prototype.createDataChannel = function (...args) {
    const channel = open.apply(this, args);
    window.__pc = this;
    channel.addEventListener('message', e => {
      try {
        const m = JSON.parse(e.data);
        const row = {t: performance.now(), type: m.type};
        if (typeof m.delta === 'string') row.delta = m.delta;
        window.__ev.push(row);
      } catch (err) {}
    });
    return channel;
  };
})();
'''

START_RECORDER = '''() => {
  const audio = document.querySelector('audio');
  if (!audio || !audio.srcObject || !window.__mixCtx) return 'no streams';
  const ctx = window.__mixCtx; const out = ctx.createMediaStreamDestination();
  ctx.createMediaStreamSource(audio.srcObject).connect(out);
  ctx.createMediaStreamSource(window.__mixDest.stream).connect(out);
  window.__chunks = [];
  const rec = new MediaRecorder(out.stream, {mimeType: 'audio/webm;codecs=opus'});
  rec.ondataavailable = e => { if (e.data.size) window.__chunks.push(e.data); };
  rec.start(500); window.__rec = rec; return 'recording';
}'''

STOP_RECORDER = '''async () => {
  const rec = window.__rec; if (!rec) return '';
  if (rec.state !== 'inactive') await new Promise(r => { rec.onstop = r; rec.stop(); });
  const bytes = new Uint8Array(await new Blob(window.__chunks, {type: 'audio/webm'}).arrayBuffer());
  let s = ''; for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}'''

SCREEN = '''() => {
  const stage = document.querySelector('[data-voice-stage]');
  return {caption: stage ? ((stage.querySelector('[data-stage-caption]') || {}).textContent || '') : '',
          panel: !!document.querySelector('button[aria-label="音声モードを閉じる"]'),
          connecting: !!Array.from(document.querySelectorAll('div')).find(d => d.textContent === '接続中…'),
          audio: !!(document.querySelector('audio') && document.querySelector('audio').srcObject),
          error: (Array.from(document.querySelectorAll('.text-destructive')).map(d => d.textContent).join(' | ') || '').slice(0, 200)};
}'''

OWNER_SYSTEM = """あなたは、電話でAIアシスタントの「ダン」と話している本人（みきさん）を演じます。ダンの出来を判定するのはあなたの仕事ではありません。本人ならこの場面で何を言うか、黙って待つかだけを決めます。
- 本人の目的と話し方は渡される。目的に向かって、本物の電話のように話す。1回に話すのは1〜2文、くだけた話し言葉。
- ダンが実際に言ったこと（通話の文字起こし。聞き間違いを含むことがある）と、画面に出たページの事実だけを根拠にする。ダンが言っていないことを、言ったことにしない。
- 画面に出たページの重さ・数・在庫などが本人の条件と違えば、人がするように指摘する（例「これ40キロじゃん」「売り切れてるじゃん」）。
- ダンが「待って」「調べるね」と言って作業中なら、wait で待つ（待つ秒数も決める）。長く黙ったままなら、人がするように声をかける。
- 目的が済んだ（条件に合う買える商品が画面で見られて、決められた）か、これ以上進まないと思ったら、お礼か一言を添えて電話を切ってと頼む（hangup=true）。
- 購入・送信・予約の確定は頼まない。
JSONだけを返す: {"action": "say" か "wait", "text": "言う言葉（sayの時）", "wait_s": 待つ秒数（waitの時、5〜40）, "hangup": 切ってと頼む言葉ならtrue, "why": "そう決めた理由を短く"}"""


def owner_input(scenario, turns, pages, now, quiet_for, screen):
    lines = [f"本人の目的: {scenario['goal']}", f"本人の話し方: {scenario['persona']}", '', '通話の流れ（秒は通話の始まりから）:']
    for t in turns:
        who = '本人' if t['role'] == 'owner' else 'ダン'
        lines.append(f"[{t['start']:.0f}秒] {who}: {t['text']}")
    lines.append('')
    if pages:
        lines.append('画面に出たページ（新しい物が下。本人が画面で見た事実）:')
        for p in pages:
            stock = {'in_stock': '買える', 'sold_out': '売り切れ', 'unknown': '買えるか不明'}.get(p.get('stock'), '不明')
            lines.append(f"- {p.get('title') or p['url']}（{stock}）: {p.get('text_head', '')[:240]}")
    else:
        lines.append('画面に出たページ: まだ無い')
    if screen.get('caption'):
        lines.append(f"画面の札: {screen['caption']}")
    lines.append(f"\n今 {now:.0f}秒。ダンが最後に声を出してから {quiet_for:.0f}秒。")
    return '\n'.join(lines)


async def owner_decides(client, scenario, turns, pages, now, quiet_for, screen):
    response = await client.responses.create(model=OWNER_MODEL, reasoning={'effort': 'low'}, max_output_tokens=1200,
                                             instructions=OWNER_SYSTEM, input=owner_input(scenario, turns, pages, now, quiet_for, screen))
    text = response.output_text or ''
    found = re.search(r'\{.*\}', text, re.S)
    try:
        data = json.loads(found.group(0)) if found else {}
    except ValueError:
        data = {}
    if data.get('action') not in ('say', 'wait') or (data.get('action') == 'say' and not str(data.get('text') or '').strip()):
        data = {'action': 'wait', 'wait_s': 10, 'why': 'model answer unreadable: ' + text[:120]}
    return data


async def speech(client, text):
    """The owner's words as 24 kHz 16-bit mono PCM, base64."""
    response = await client.audio.speech.create(model=TTS_MODEL, voice=TTS_VOICE, input=text, response_format='pcm',
                                                instructions='日本語。電話で友だちに話すような、くだけた若い男性の話し方。少し早口。')
    return base64.b64encode(response.content).decode()


def stage_pages(log_path, session_id):
    """The pages the call's screen showed, from the sideband log (stage_page with a url, written by voice_stage)."""
    rows = []
    if not session_id or not Path(log_path).exists():
        return rows
    for line in Path(log_path).read_text(encoding='utf-8', errors='replace').splitlines():
        if session_id not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get('session_id') == session_id and d.get('phase') == 'stage_page' and d.get('url'):
            rows.append({'at': d['at'], 'url': d['url']})
    return rows


def phases(log_path, session_id):
    counts = {}
    if Path(log_path).exists():
        for line in Path(log_path).read_text(encoding='utf-8', errors='replace').splitlines():
            if session_id and session_id in line:
                try: d = json.loads(line)
                except ValueError: continue
                counts[d.get('phase')] = counts.get(d.get('phase'), 0) + 1
    return counts


class Transcript:
    """Both sides as the call transcribed them: deltas joined into utterances (a gap over 1.6 s starts a new one)."""
    def __init__(self, t0):
        self.t0, self.seen, self.heard = t0, 0, []   # heard: what the speech model transcribed of the owner
        self.dan_times = []                           # the time of every piece of Dan's words (for the reply gaps)

    def take(self, events, turns):
        new_dan = False
        for e in events[self.seen:]:
            t = (e['t'] - self.t0) / 1000
            if e['type'] == 'session.output_transcript.delta' and e.get('delta'):
                last = turns[-1] if turns else None
                if last and last['role'] == 'dan' and t - last['end'] < 1.6:
                    last['text'] += e['delta']; last['end'] = t
                else:
                    turns.append({'role': 'dan', 'start': round(t, 2), 'end': t, 'text': e['delta']})
                self.dan_times.append(round(t, 2))
                new_dan = True
            elif e['type'] == 'session.input_transcript.delta' and e.get('delta'):
                if self.heard and t - self.heard[-1]['end'] < 1.6:
                    self.heard[-1]['text'] += e['delta']; self.heard[-1]['end'] = t
                else:
                    self.heard.append({'start': round(t, 2), 'end': t, 'text': e['delta']})
        self.seen = len(events)
        return new_dan


async def main(base, scenario_path, out_dir, keep_room=False, log_path=None):
    from openai import AsyncOpenAI
    from playwright.async_api import async_playwright
    from app.config import settings
    from app.services.owner import resolve_owner_user_id
    from app.services.auth_service import create_access_token
    from app.services.project_service import ProjectService

    scenario = json.loads(Path(scenario_path).read_text(encoding='utf-8'))
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    log_path = log_path or str(ROOT / '.tmp' / 'voice-sideband.jsonl')
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    owner = resolve_owner_user_id()
    projects = ProjectService()
    project = await projects.create_project(owner, f"通話の試験: {scenario['name']}", description='voice_goal_call.py が作り、終わると消す部屋')
    token = create_access_token(owner, '', timedelta(minutes=30))
    run = {'scenario': scenario['name'], 'base': base, 'project_id': project['id'], 'room_id': project.get('room_id'),
           'turns': [], 'decisions': [], 'pages': [], 'hangup_asked_at': None, 'closed_at': None}
    turns, page_facts, session = run['turns'], {}, {}
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=['--autoplay-policy=no-user-gesture-required', '--use-fake-ui-for-media-stream'])
            context = await browser.new_context(viewport=VIEWPORT, record_video_dir=str(out), record_video_size=VIEWPORT,
                                                locale='ja-JP', timezone_id='Asia/Tokyo', color_scheme='dark', permissions=['microphone'])
            await context.add_init_script(INIT)
            await context.add_init_script(f"localStorage.setItem('done-token', {json.dumps(token)});")
            reader = await browser.new_context(locale='ja-JP', viewport={'width': 1280, 'height': 900})   # opens the shown pages, as the owner sees them
            page = await context.new_page()

            async def on_response(response):
                if response.url.endswith('/api/v1/voicelog/live/session') and response.request.method == 'POST':
                    try: session['id'] = ((await response.json()).get('session') or {}).get('id')
                    except Exception: pass
            page.on('response', lambda r: asyncio.ensure_future(on_response(r)))

            await page.goto(f"{base}/chat/{project['id']}", wait_until='domcontentloaded')
            await page.get_by_role('button', name='音声').wait_for(timeout=60000)
            await page.wait_for_timeout(1500)
            await page.get_by_role('button', name='音声').click()
            for _ in range(120):
                st = await page.evaluate(SCREEN)
                if st['audio'] and not st['connecting']: break
                await page.wait_for_timeout(500)
            else:
                raise SystemExit('the call did not connect: ' + json.dumps(st, ensure_ascii=False))
            t0 = await page.evaluate('performance.now()')
            run['session_id'] = session.get('id')
            await page.evaluate(START_RECORDER)
            transcript = Transcript(t0)
            started = time.monotonic()
            now = lambda: time.monotonic() - started

            async def sync():
                """Dan's new words and the newly shown pages; True when the call has closed."""
                events = await page.evaluate('window.__ev')
                transcript.take(events, turns)
                for shown in stage_pages(log_path, session.get('id')):
                    if shown['url'] not in page_facts:
                        page_facts[shown['url']] = await grader.read_page(reader, shown['url'])
                        run['pages'].append({**shown, 'seen_at': round(now(), 1), 'title': page_facts[shown['url']].get('title', ''),
                                             'stock': page_facts[shown['url']].get('stock')})
                closed = any(e['type'] == 'session.closed' for e in events) or not (await page.evaluate(SCREEN))['panel']
                if closed and run['closed_at'] is None:
                    run['closed_at'] = round(now(), 2)
                return closed

            async def say(text, hangup=False):
                pcm = await speech(client, text)
                begin, end = await page.evaluate('([b, r]) => window.__say(b, r)', [pcm, 24000])
                turns.append({'role': 'owner', 'start': round((begin - t0) / 1000, 2), 'end': round((end - t0) / 1000, 2), 'text': text})
                if hangup: run['hangup_asked_at'] = turns[-1]['end']

            async def wait_for_dan(limit):
                """Until Dan has spoken and gone quiet, or `limit` seconds without a word. Returns seconds Dan has been quiet."""
                began, spoke, last = now(), False, now()
                while now() - began < limit:
                    if await sync(): return 0
                    level = await page.evaluate('window.__aiLevel()')
                    talking = level > .004 or (turns and turns[-1]['role'] == 'dan' and (await page.evaluate('performance.now()') - t0) / 1000 - turns[-1]['end'] < 1.0)
                    if talking: spoke, last = True, now()
                    elif spoke and now() - last >= DAN_QUIET_S: return now() - last
                    await asyncio.sleep(.25)
                return now() - last

            await say(scenario['opening'])
            limit = FIRST_WORDS_S
            while now() < scenario.get('max_seconds', 240):
                quiet = await wait_for_dan(limit)
                if await sync(): break
                last_dan = max((t['end'] for t in turns if t['role'] == 'dan'), default=0)
                screen = await page.evaluate(SCREEN)
                decision = await owner_decides(client, scenario, turns, [page_facts[u] for u in page_facts], now(), now() - last_dan if last_dan else now(), screen)
                decision['at'] = round(now(), 1)
                run['decisions'].append(decision)
                print(json.dumps(decision, ensure_ascii=False), flush=True)
                if decision['action'] == 'say':
                    await say(decision['text'].strip(), hangup=bool(decision.get('hangup')))
                    if decision.get('hangup'):
                        until = now() + HANGUP_WAIT_S
                        while now() < until and not await sync(): await asyncio.sleep(.25)
                        break
                    limit = FIRST_WORDS_S
                else:
                    limit = max(5, min(40, int(decision.get('wait_s') or 10)))
            await sync()
            run['ended_at'] = round(now(), 2)
            run['heard'] = transcript.heard
            run['dan_times'] = transcript.dan_times
            if any(t['role'] == 'owner' for t in turns) and not transcript.heard:
                # Nothing the owner side said reached the call: the run says nothing about Dan (2026-11-03, the first run
                # sent silence because the page stopped the shared microphone track).
                run['harness_error'] = '本人役の声が通話に届いていない（文字起こしが1つも無い）'
            audio_b64 = await page.evaluate(STOP_RECORDER)
            close = page.get_by_role('button', name='音声モードを閉じる')
            if await close.count(): await close.click()
            await page.wait_for_timeout(2000)
            await context.close()
            video = await page.video.path()
            if audio_b64: (out / 'voices.webm').write_bytes(base64.b64decode(audio_b64))
            run['video'] = str(video)
            await reader.close()
            await browser.close()
    finally:
        run['log_phases'] = phases(log_path, session.get('id'))
        (out / 'run.json').write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding='utf-8')
        if not keep_room:
            try: await projects.delete_project(project['id'], owner)
            except Exception as exc: print('room not deleted:', exc)
    if run.get('harness_error'):
        print('試験そのものが失敗:', run['harness_error'])
        return 2
    result = await grader.grade(run, scenario)
    (out / 'grade.json').write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    for t in turns:
        print(f"{t['start']:6.1f} {'本人' if t['role'] == 'owner' else 'ダン'}: {t['text']}")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    argv = sys.argv[1:]
    keep = '--keep-room' in argv
    log = None
    if '--log' in argv:
        i = argv.index('--log'); log = argv[i + 1]; del argv[i:i + 2]
    argv = [a for a in argv if a != '--keep-room']
    sys.exit(asyncio.run(main(argv[0], argv[1], argv[2], keep, log)))
