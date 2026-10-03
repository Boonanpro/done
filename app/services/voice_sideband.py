"""The server's own connection to a Live call (OpenAI "sideband": wss://api.openai.com/v1/live/sessions/{id}/attach).

Why: every backend step of a call travelled speech model -> PHONE -> this server -> phone -> speech model. Measured on
2026-09-21: owner's words -> Dan's voice 8.5s median while the work inside this server was 1.0s; when the phone changed
from Wi-Fi to mobile the requests did not arrive for two minutes; and on a good network the phone app still held a finished
answer for 6.3s before handing it to the speech model (server done 14:23:56.2, appended 14:24:02.5).

The server always answers the call's delegations here: the backend model (Responses delegation, voice_responses) chooses
Dan's functions, this connection runs them (execute_call) and sends the results back; results of finished work are
appended as spoken commentary (job_feed). The phone carries audio only.

Switch: DAN_VOICE_SIDEBAND=0 turns everything off. A failure here never touches the call's audio.
Only metadata is logged (event types, sizes, timing): no audio, no words.
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
URL = 'wss://api.openai.com/v1/live/sessions/{session_id}/attach'
MAX_SECONDS = 3 * 3600
CHUNK = 300             # an append is limited to 500 tokens; Japanese runs at about a token a character
_tasks = {}
LOG = Path(__file__).resolve().parents[2]/'.tmp'/'voice-sideband.jsonl'


def note(session_id, room_id, phase, **fields):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 4*1024*1024: LOG.replace(LOG.with_suffix('.previous.jsonl'))
        with LOG.open('a', encoding='utf-8') as out:
            out.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(), 'session_id': session_id, 'room_id': room_id,
                                  'phase': phase, 'pid': os.getpid(), **fields}, ensure_ascii=False)+chr(10))   # pid: the restart guard counts a call only while this process lives
    except OSError:
        pass


def enabled():
    return os.environ.get('DAN_VOICE_SIDEBAND', '1') != '0'


def attach(session_id, user_id, room_id, api_key, own=False):
    """Start the sideband for a call in the background. Returns True when this server owns the delegations."""
    if not enabled() or not session_id or not api_key or session_id in _tasks:
        return False
    own = bool(own) and os.environ.get('DAN_VOICE_SIDEBAND_OWN', '1') != '0'   # DAN_VOICE_SIDEBAND_OWN=0: observe only, the app answers as before
    try:
        task = asyncio.get_running_loop().create_task(_run(session_id, user_id, room_id, api_key, own))
    except RuntimeError:
        return False
    _tasks[session_id] = task
    task.add_done_callback(lambda _: _tasks.pop(session_id, None))
    return bool(own)


def summary(event):
    """What is kept of an event: its type and sizes, never audio and never the words."""
    kind = str(event.get('type') or '')
    kept = {'event': kind}
    if isinstance(event.get('delegation'), dict):
        kept['delegation_id'] = str(event['delegation'].get('id') or '')[:40]
        kept['target'] = event['delegation'].get('target')
        kept['delegation_keys'] = sorted(event['delegation'])[:10]
    if isinstance(event.get('error'), dict):   # why a call ended: the code and the service's own message, no user content
        kept['error'] = {k: str(event['error'].get(k))[:200] for k in ('type', 'code', 'message') if event['error'].get(k)}
    for key in ('delta', 'transcript', 'text', 'request'):
        value = event.get(key)
        if isinstance(value, str): kept[key+'_chars'] = len(value)
    kept['keys'] = sorted(k for k in event if k not in ('audio', 'delta', 'transcript', 'text'))[:12]
    return kept


class Dialogue:
    """The conversation as this server hears it: consecutive deltas of one speaker are one turn."""
    def __init__(self):
        self.turns = []
        self.heard_at = 0.0

    def add(self, role, delta):
        if not delta: return
        if role == 'user': self.heard_at = time.monotonic()
        if self.turns and self.turns[-1]['role'] == role: self.turns[-1]['text'] += delta
        else: self.turns.append({'role': role, 'text': delta})
        del self.turns[:-24]

    def recent(self):
        return [{'role': t['role'], 'text': t['text'].strip()[:1200]} for t in self.turns[-12:] if t['text'].strip()]


def for_speech(text):
    """Text that is going to be read aloud: no thousands separators (14,320円 was read as 「十四、三百二十円」 on 2026-09-22)."""
    import re
    return re.sub(r'(?<=\d),(?=\d{3})', '', text)


def chunks(text):
    text = for_speech(text).strip()
    while text:
        cut = len(text) if len(text) <= CHUNK else max(text.rfind('。', 0, CHUNK)+1, text.rfind('、', 0, CHUNK)+1) or CHUNK
        yield text[:cut]
        text = text[cut:].lstrip()


async def execute_call(item, user_id, room_id, dialogue, record, delegation_id, speak=None):
    """One function call of the backend model, run here. Returns the function_call_output item."""
    from app.services.voice_responses import run_function
    started = time.monotonic()
    try: args = json.loads(item.get('arguments') or '{}')
    except ValueError: args = {}
    try: output = await run_function(item.get('name'), args, user_id, room_id, dialogue.recent(), speak=speak)
    except Exception as exc:
        output = {'error': f'{type(exc).__name__}: {str(exc)[:200]}'}
    try:   # place names the speech model would misread get their reading (voice_furigana)
        from app.services.voice_furigana import annotate_all
        output = annotate_all(output)
    except Exception:
        pass
    detail = {k: str(output.get(k))[:120] for k in ('reason', 'error', 'replayed', 'accepted') if isinstance(output, dict) and output.get(k) is not None}   # outcome codes only, never content
    record('function_done', delegation_id=str(delegation_id)[:40], name=item.get('name'), elapsed_ms=round((time.monotonic()-started)*1000), output_chars=len(json.dumps(output, ensure_ascii=False)), **({'detail': detail} if detail else {}))
    return {'type': 'function_call_output', 'call_id': item.get('call_id'), 'output': json.dumps(output, ensure_ascii=False)[:12000], 'name': item.get('name')}


async def handle_response_event(send, session_id, user_id, room_id, envelope, dialogue, record, pending=None):
    """One response.event envelope from the backend model (responses delegation). The backend may call several functions
    in one response (parallel_tool_calls): their outputs are collected and sent together, then ONE response.create. Sending
    each output with its own response.create made the API refuse: function_call_outputs_required (2026-09-22 17:35)."""
    pending = pending if pending is not None else {}
    inner = envelope.get('event') or {}
    kind = str(inner.get('type') or '')
    delegation_id = str(envelope.get('delegation_id') or '')
    item = inner.get('item') or {}
    if kind == 'response.output_item.done' and item.get('type') == 'function_call':
        async def speak(text):   # a later result of a function (a replay) goes into the call as spoken commentary
            for part in chunks(text):
                await send({'type': 'session.commentary.append', 'event_id': f'dan-{time.time_ns()}', 'delegation_id': None, 'content': part})
            record('replay_spoken', chars=len(text))
        pending.setdefault(delegation_id, []).append(asyncio.ensure_future(execute_call(item, user_id, room_id, dialogue, record, delegation_id, speak)))
        return
    if kind == 'response.output_item.done' and item.get('type') == 'message':
        text = ''.join(c.get('text', '') for c in (item.get('content') or []) if isinstance(c, dict))
        record('backend_message', delegation_id=delegation_id[:40], chars=len(text))
        return
    if kind in ('response.completed', 'response.failed', 'response.incomplete', 'error'):
        # the backend's tokens: billed apart from Live's per-minute rate, and half of a call's cost in a measured call (2026-09-24)
        usage = (inner.get('response') or {}).get('usage') or {}
        tokens = {'input_tokens': usage.get('input_tokens', 0), 'cached_tokens': (usage.get('input_tokens_details') or {}).get('cached_tokens', 0),
                  'output_tokens': usage.get('output_tokens', 0), 'model': (inner.get('response') or {}).get('model', '')} if usage else {}
        record('backend_'+kind.split('.')[-1], delegation_id=delegation_id[:40], detail=str(inner.get('error') or inner.get('response', {}).get('status') or '')[:200], **tokens)
        calls = pending.pop(delegation_id, [])
        if kind == 'response.completed' and calls:
            outputs = await asyncio.gather(*calls)
            if any(out['name'] == 'end_call' for out in outputs):
                # From here on nothing new is pushed into the call, and the room's chat is where results go again
                # (command_center reports while no call is active): a result finishing in these seconds is written there.
                ENDING[session_id] = datetime.now(timezone.utc).isoformat()
                try:
                    from app.services import voice_calls
                    voice_calls.end(room_id, session_id)
                except Exception:
                    pass
                # The owner asked to end the call. The phone hangs up itself 4 s after it sees end_call, so Dan can finish
                # 「はい、切ります」. Closing here at once stopped Dan mid-word (2026-10-01: 「少々お待ちくだ…」, then
                # silence until the phone hung up). The server closes only as a fallback for clients that do not.
                async def fallback_close():
                    await asyncio.sleep(HANGUP_FALLBACK_S)
                    try:
                        await send({'type': 'session.close', 'event_id': f'dan-{time.time_ns()}'})
                    except Exception:
                        pass   # already closed by the phone
                asyncio.ensure_future(fallback_close())
                return
            # per the guide: every function_call_output of the response, then response.create (no delegation_id field)
            for out in outputs:
                await send({'type': 'response.item.create', 'event_id': f'dan-{time.time_ns()}', 'item': {k: out[k] for k in ('type', 'call_id', 'output')}})
            await send({'type': 'response.create', 'event_id': f'dan-{time.time_ns()}'})


ENDING = {}   # calls whose end was chosen (end_call) -> when; a closed call's id is dropped in _run's finally
HANGUP_FALLBACK_S = 6.0   # the phone closes 3.5 s after end_call; the server closes later only for clients that don't
FEED_SECONDS = 1.0
SPOKEN = {'result', 'error', 'confirmation'}   # what the owner hears without asking; everything else is silent material


async def job_feed(send, user_id, room_id, record, connected_at, session_id=''):
    """The room's jobs, from this server (own mode): results, errors and questions to the owner go into the call as
    commentary (spoken) the moment they appear. Nothing else is pushed. The running work's STATE is read on demand by
    the backend model (job_status) when the owner's words concern it; pushing it as thinking, on a timer or at each
    utterance, made the speech model say 「うん、もう少し待って」 unprompted (2026-09-22 17:46) or fed it into unrelated
    turns. Before, the phone polled the job list every 1.5s and appended; the phone now carries audio only."""
    from app.services.command_job_state import list_owned, TERMINAL
    seen = {}
    while True:
        await asyncio.sleep(FEED_SECONDS)
        try: jobs = await asyncio.to_thread(list_owned, user_id, room_id)
        except Exception: continue
        for job in jobs:
            events = job.get('events') or []
            previous = seen.get(job['id'])
            seen[job['id']] = job.get('seq', 0)
            old = job.get('created_at', '') < connected_at
            if previous is None and old and job['state'] in TERMINAL: continue   # finished before the call: not news
            fresh = [e for e in events if e.get('seq', 0) > (previous or 0)]
            if previous is None and old: fresh = fresh[-1:]
            if not fresh: continue
            said = [e for e in fresh if e.get('kind') in SPOKEN]
            for e in said:
                if session_id in ENDING:
                    # Being hung up: not said. A result that arrived before the end was chosen was kept out of the chat
                    # for the call (command_center), so it is written there now; later ones the chat gets as usual.
                    if e['kind'] == 'result' and str(e.get('at') or '') < ENDING[session_id]:
                        try:
                            from app.services.chat_service import ChatService
                            await ChatService().send_message(room_id, user_id, e['text'], sender_type='ai')
                        except Exception:
                            logger.exception('call ending: result not written room=%s', room_id)
                    continue
                # The report is written for the chat (headings, bullets, every detail). Given as the words to say, it was
                # read out like a script (2026-10-02). It goes in as material; what to say is Dan's own, in conversation.
                task = job.get('task', '').split('参考の直前会話')[0].replace('今回のユーザー発言（原文）:', '').strip()[:80]
                material = {'result': '作業「%s」の結果:\n%s', 'error': '作業「%s」で起きた問題:\n%s',
                            'confirmation': '作業「%s」から本人への確認:\n%s'}[e['kind']] % (task, e['text'][:1500])
                try:
                    from app.services.voice_furigana import annotate
                    material = annotate(material)
                except Exception:
                    pass
                for part in chunks(material):
                    await send({'type': 'session.thinking.append', 'event_id': f'dan-{time.time_ns()}', 'delegation_id': None, 'content': part})
                cue = {'result': '今の作業が終わった。結果を、本人に会話として自分の言葉で伝える（書かれた文を読み上げない。細かい番号などは聞かれたら答える）。',
                       'error': '今の作業で問題が起きた。何が起きて、どうするかを、本人に会話として短く伝える。',
                       'confirmation': '今の作業から本人に確認したいことがある。何を確かめたいかを、会話として短く聞く。'}[e['kind']]
                await send({'type': 'session.commentary.append', 'event_id': f'dan-{time.time_ns()}', 'delegation_id': None, 'content': cue})
                record('job_spoken', job_id=job['id'][:8], kind=e['kind'], chars=len(material))


async def chat_feed(send, room_id, dialogue, record):
    """What the owner sends to this room's chat during the call reaches the Dan on the call (voice_calls), as if said on the
    call: the speech model takes it up itself, in its own words. It went in as silent context first, and Dan said nothing
    about a link until the owner asked whether it had been seen (2026-10-01 21:17 -> 21:20). How to react is not prescribed.
    Also the owner's turn for the work handed on from the call."""
    from app.services import voice_calls
    done = 0
    while True:
        await asyncio.sleep(.5)
        try: texts, done = await asyncio.to_thread(voice_calls.take, room_id, done)
        except Exception: continue
        for text in texts:
            dialogue.add('user', '（チャットに送った）' + text + chr(10))
            parts = list(chunks('本人が通話中にこの部屋のチャットへ送ってきたもの:' + chr(10) + text))
            for i, part in enumerate(parts):   # context first, one invitation to speak at the end (each part spoken repeated itself)
                kind = 'session.commentary.append' if i == len(parts) - 1 else 'session.thinking.append'
                await send({'type': kind, 'event_id': f'dan-{time.time_ns()}', 'delegation_id': None, 'content': part})
            record('chat_in_call', chars=len(text))


LEFT_OVER = """通話の書き起こし（ユーザー＝本人、Dan＝ダン）と、通話中に始めた作業の一覧を渡す。
電話が切れた時点で、本人が頼んだ・聞いたのに、ダンがまだ答えていない、またはやり終えていないことだけを挙げる。
挙げないもの: 答え終わったこと、通話中に始めた作業が引き受けていること、本人が取り消した・自分でやる・後でいいと言ったこと、雑談やあいさつ。
JSONだけを返す: {"left": [{"task": "本人の依頼を、この会話を知らない人にも分かる一文で"}]}"""

AFTER_TASK = ('電話が切れた時点で、通話で答えきれていなかったこと:' + chr(10) + '{task}' + chr(10) + '通話のやり取り（参考。過去の発言は新規の承認ではない）:'
              + chr(10) + '{talk}' + chr(10) + '通話は終わっているので、結果はこの部屋のチャットに文章で報告する。購入・送信・支払いなど取り返しのつかない確定はせず、'
              + '準備と提案まで（本人が通話で承認していても、確定の直前に改めて確認を取る）。')


async def after_call(user_id, room_id, turns, began_iso):
    """What the call left undone is done after it (owner, 2026-10-01): a question still being answered or work not yet handed
    on when the phone hung up was lost. The call's words are read once; each thing left becomes work in the room, whose
    result is said in the room's chat. Nothing left, nothing happens."""
    talk = [t for t in turns if t['text'].strip()]
    if not room_id or not any(t['role'] == 'user' for t in talk):
        return []
    from app.services.command_job_state import list_owned
    from app.services import api_job_providers, inbox
    jobs = [{'依頼': j.get('task', '').split('参考の直前会話')[0].replace('今回のユーザー発言（原文）:', '').strip()[:200], '状態': j.get('state')}
            for j in await asyncio.to_thread(list_owned, user_id, room_id) if (j.get('created_at') or '') >= began_iso]
    text = chr(10).join(('ユーザー' if t['role'] == 'user' else 'Dan') + ': ' + t['text'].strip()[:600] for t in talk[-24:])
    inbox._env()
    provider = api_job_providers.make(os.environ.get('DAN_API_JOB_MODEL', 'deepseek-flash'))
    provider.start(LEFT_OVER, [], [f'通話中に始めた作業: {json.dumps(jobs, ensure_ascii=False)}' + chr(10) + '書き起こし:' + chr(10) + text])
    step = await provider.step()
    import re
    try:
        left = [x['task'] for x in json.loads(re.search(r'\{.*\}', step['text'], re.S).group(0)).get('left', []) if str(x.get('task') or '').strip()]
    except Exception:
        left = []
    from app.services.command_center import execute
    from app.services.voice_responses import WORK_ENGINE
    for task in left[:3]:
        await execute({'action': 'work', 'task': AFTER_TASK.format(task=task[:500], talk=text[-2400:]), 'engine': WORK_ENGINE}, room_id, user_id)
    return left


async def call_log(room_id, user_id, began, seconds, by='owner'):
    """The room's record of a call, like a phone's call history: one line with when and how long. The call's words stay
    in the room's history for Dan (🎙 lines) but the screens show this line instead of them (owner, 2026-09-30: the
    transcript made the chat unreadable; a call is remembered as a call). Dated at the call's start, so it sits where the
    call happened among the reports and anything shown during it. `by` is who placed the call: the screens put the line
    on that side (owner's calls "📞 ダンと通話" on the right, Dan's calls "📞 ダンからの通話" on the left)."""
    from zoneinfo import ZoneInfo
    from app.services.chat_service import ChatService
    local = ZoneInfo('Asia/Tokyo')
    start = began.astimezone(local)
    end = datetime.fromtimestamp(began.timestamp() + seconds, local)
    length = f'{seconds // 60}分{seconds % 60}秒' if seconds >= 60 else f'{seconds}秒'
    head = '📞 ダンからの通話' if by == 'dan' else '📞 ダンと通話'
    await ChatService().send_message(room_id, user_id, f'{head} {start:%H:%M}〜{end:%H:%M}（{length}）',
                                     sender_type='system', created_at=began.isoformat())


async def _run(session_id, user_id, room_id, api_key, own):
    import websockets
    record = lambda phase, **fields: note(session_id, room_id, phase, **fields)
    started, began = time.monotonic(), datetime.now(timezone.utc)
    counts, dialogue, working, spoke = {}, Dialogue(), set(), {}
    try:
        async with websockets.connect(URL.format(session_id=session_id), additional_headers={'Authorization': 'Bearer '+api_key},
                                      max_size=8*1024*1024, open_timeout=10) as socket:
            record('sideband_attached', elapsed_ms=round((time.monotonic()-started)*1000), own=bool(own))
            lock = asyncio.Lock()
            async def send(event):
                async with lock: await socket.send(json.dumps(event, ensure_ascii=False))
            pending = {}
            if own:
                feed = asyncio.create_task(job_feed(send, user_id, room_id, record, datetime.now(timezone.utc).isoformat(), session_id))
                working.add(feed); feed.add_done_callback(working.discard)
                if room_id:   # from now on the room's chat goes to this call, not to a chat Dan
                    from app.services import voice_calls
                    voice_calls.begin(room_id, session_id)
                    inbox = asyncio.create_task(chat_feed(send, room_id, dialogue, record))
                    working.add(inbox); inbox.add_done_callback(working.discard)
            while time.monotonic()-started < MAX_SECONDS:
                try: event = json.loads(await socket.recv())
                except (TypeError, ValueError): continue
                kind = str(event.get('type') or '')
                counts[kind] = counts.get(kind, 0)+1
                # When each side starts speaking, as times only (no words, no audio): a first delta after 1.5 s of quiet.
                # Without it, why Dan was silent for some seconds after an answer reached it could not be told (2026-10-01).
                if kind in ('session.output_audio.delta', 'session.input_transcript.delta'):
                    side = 'dan' if kind == 'session.output_audio.delta' else 'owner'
                    now = time.monotonic()
                    if now - spoke.get(side, 0) > 1.5: record('speech_start', side=side, at_s=round(now - started, 2))
                    spoke[side] = now
                if 'audio' in kind: continue   # reflected audio: counted, never stored
                if kind == 'session.input_transcript.delta': dialogue.add('user', event.get('delta') or '')
                elif kind == 'session.output_transcript.delta': dialogue.add('assistant', event.get('delta') or '')
                if kind == 'response.event':
                    inner = event.get('event') or {}
                    counts['response.event:'+str(inner.get('type'))] = counts.get('response.event:'+str(inner.get('type')), 0)+1
                if counts[kind] <= 3 or 'delegation' in kind or kind in ('session.closed', 'error'):
                    record('sideband_event', **summary(event))
                if own and kind == 'response.event':
                    # tasks run in creation order: a function call is registered (no await before it) before the
                    # response's completion gathers the outputs; the receive loop itself never waits on a function
                    task = asyncio.create_task(handle_response_event(send, session_id, user_id, room_id, event, dialogue, record, pending))
                    working.add(task); task.add_done_callback(working.discard)
                if kind == 'session.closed': break
    except Exception as exc:
        record('sideband_failed', error_type=type(exc).__name__, detail=str(exc)[:200])
        logger.info('voice sideband ended: %s', type(exc).__name__)
    finally:
        for task in working: task.cancel()
        ENDING.pop(session_id, None)
        try:
            from app.services import voice_calls
            voice_calls.end(room_id, session_id)
        except Exception:
            pass
        record('sideband_closed', seconds=round(time.monotonic()-started), counts=dict(sorted(counts.items(), key=lambda x: -x[1])[:20]))
        try:
            await call_log(room_id, user_id, began, round(time.monotonic()-started))
        except Exception:
            logger.exception('call log not written room=%s', room_id)
        if own:
            try:
                left = await after_call(user_id, room_id, dialogue.turns, began.isoformat())
                record('after_call', left=len(left))
            except Exception:
                logger.exception('after-call check failed room=%s', room_id)
