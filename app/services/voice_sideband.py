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
        record('backend_'+kind.split('.')[-1], delegation_id=delegation_id[:40], detail=str(inner.get('error') or inner.get('response', {}).get('status') or '')[:200])
        calls = pending.pop(delegation_id, [])
        if kind == 'response.completed' and calls:
            outputs = await asyncio.gather(*calls)
            if any(out['name'] == 'end_call' for out in outputs):
                # The owner asked to end the call: close now. (Asking for a farewell and waiting a fixed 2.5 s before closing
                # raced the speech: in both real calls nothing was heard, once the farewell was empty. 2026-09-23)
                await send({'type': 'session.close', 'event_id': f'dan-{time.time_ns()}'})
                return
            # per the guide: every function_call_output of the response, then response.create (no delegation_id field)
            for out in outputs:
                await send({'type': 'response.item.create', 'event_id': f'dan-{time.time_ns()}', 'item': {k: out[k] for k in ('type', 'call_id', 'output')}})
            await send({'type': 'response.create', 'event_id': f'dan-{time.time_ns()}'})


FEED_SECONDS = 1.0
SPOKEN = {'result', 'error', 'confirmation'}   # what the owner hears without asking; everything else is silent material


async def job_feed(send, user_id, room_id, record, connected_at):
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
                text = {'result': '作業「%s」の結果: %s', 'error': '作業「%s」で問題: %s', 'confirmation': '作業「%s」から本人への確認: %s'}[e['kind']] % (
                    job.get('task', '').split('参考の直前会話')[0].replace('今回のユーザー発言（原文）:', '').strip()[:80], e['text'][:1500])
                for part in chunks(text):
                    await send({'type': 'session.commentary.append', 'event_id': f'dan-{time.time_ns()}', 'delegation_id': None, 'content': part})
                record('job_spoken', job_id=job['id'][:8], kind=e['kind'], chars=len(text))


async def _run(session_id, user_id, room_id, api_key, own):
    import websockets
    record = lambda phase, **fields: note(session_id, room_id, phase, **fields)
    started = time.monotonic()
    counts, dialogue, working = {}, Dialogue(), set()
    try:
        async with websockets.connect(URL.format(session_id=session_id), additional_headers={'Authorization': 'Bearer '+api_key},
                                      max_size=8*1024*1024, open_timeout=10) as socket:
            record('sideband_attached', elapsed_ms=round((time.monotonic()-started)*1000), own=bool(own))
            lock = asyncio.Lock()
            async def send(event):
                async with lock: await socket.send(json.dumps(event, ensure_ascii=False))
            pending = {}
            if own:
                feed = asyncio.create_task(job_feed(send, user_id, room_id, record, datetime.now(timezone.utc).isoformat()))
                working.add(feed); feed.add_done_callback(working.discard)
            while time.monotonic()-started < MAX_SECONDS:
                try: event = json.loads(await socket.recv())
                except (TypeError, ValueError): continue
                kind = str(event.get('type') or '')
                counts[kind] = counts.get(kind, 0)+1
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
        record('sideband_closed', seconds=round(time.monotonic()-started), counts=dict(sorted(counts.items(), key=lambda x: -x[1])[:20]))
