"""Run one request of a call that has no fixed route (voice_router.Router.luna: messages, documents, other rooms, talk,
anything Jev is unsure of) on a model, outside a call, and grade what the model did from facts.

    python scripts/voice_backend_compare.py <case.json> <out.json> [--model M --reasoning R]

Without --model the request runs on what a call uses now (voice_settings). The instructions, the tools and the loop are
the call's own (voice_responses.delegation, Router._luna_loop). Reading functions run for real. Functions that send,
start work, draw on the owner's screen or end the call are NOT run: what the model asked is recorded and a plausible
result is returned, so both models meet the same world and nothing reaches the owner or anyone else.

A case (tests/voice_backends/*.json): "turns" (the call up to and with the request, role user/assistant, text),
optional "cards" (drafts on the stage: proposal_id, channel, to, to_name, body) and "expect":
  "tools_any" (one of these functions must be called), "tools_none" (none of these may be),
  "args_all" / "args_none" (regex on the arguments of the called functions), "answer_all" / "answer_none" (regex on
  the spoken answer), "route" (the request first goes through the call's router, Jev's choice of where it goes, and
  must land on this route; 'contact' then reads Chatwork before the backend's first round as a call does). The time
  counts from the router's choice. Exit 0 pass, 1 fail, 2 could not run.
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

REAL = {'get_calendar', 'get_location', 'get_saved_information', 'search_records', 'room_files', 'job_status', 'list_operations', 'dan_tool_help', 'read_chatwork', 'read_mail', 'read_line'}
OWNER = '2582a188-ff24-4a4f-b989-6063034d90b2'
ROOM = 'voice-backend-compare'


def stub(name, args):
    if name == 'run_in_background': return {'started': True, 'id': 'bg_compare', 'note': '裏で調べ始めた。途中で分かった事実と答えは、声で本人に届く。'}
    if name in ('start_work', 'replay_operation'): return {'accepted': True, 'job_id': 'job_compare', 'note': '作業を始めた。結果は後で別に届く。'}
    if name == 'steer_job': return {'accepted': True, 'note': '作業に伝えた。'}
    if name == 'draft_message_on_stage':
        return {'shown': True, 'proposal_id': 'p_compare', 'channel': args.get('channel'), 'to': args.get('to'), 'body': args.get('body'),
                'note': '下書きを本人の画面に出した。送ってはいない。'}
    if name == 'revise_message_on_stage': return {'revised': True, 'proposal_id': args.get('proposal_id'), 'body': args.get('body')}
    if name == 'send_message_on_stage': return {'sent': False, 'read_back': '（下書きの本文）', 'note': '読み上げて、本人の承認の言葉を待つ。'}
    if name == 'end_call': return {'ended': True}
    return {'ok': True, 'note': '実行した。'}


async def run(case, out, model):
    from app.services import voice_router, voice_sideband, voice_responses
    from app.services.voice_sideband import Dialogue
    rounds, steps = [], []
    def record(phase, **f):
        if phase == 'route_luna_round': rounds.append(f)
    async def send(event): pass
    dialogue = Dialogue()
    for t in case['turns']:
        dialogue.add(t['role'], t['text'])
    owner = case.get('user_id') or OWNER
    real = voice_sideband.execute_call
    async def execute_call(item, *a, **k):
        name = item.get('name')
        try: args = json.loads(item.get('arguments') or '{}')
        except ValueError: args = {}
        if name in REAL:
            done = await real(item, *a, **k)
        else:
            done = {'type': 'function_call_output', 'call_id': item.get('call_id'), 'output': json.dumps(stub(name, args), ensure_ascii=False), 'name': name}
        steps.append({'name': name, 'arguments': args, 'real': name in REAL, 'output': str(done.get('output'))[:500]})
        return done
    voice_sideband.execute_call = execute_call
    backend = voice_responses.delegation(ROOM, owner)['responses']
    class Stage:
        scenes = [{'card': dict(c)} for c in case.get('cards') or []]
    router = voice_router.Router('compare', owner, ROOM, dialogue, send, record, lambda *a, **k: None, backend=backend,
                                 stage=Stage() if case.get('cards') else None)
    began = time.monotonic()
    routed, extra = None, ''
    if exp_route := (case.get('expect') or {}).get('route'):
        routed = (await router.route())[0]
        if routed == 'contact' and hasattr(router, 'contact_context'):
            extra = await router.contact_context()
    try:
        loop = router._luna_loop('compare', (), extra) if extra else router._luna_loop('compare')
        answer, ended = await asyncio.wait_for(loop, voice_router.LUNA_SECONDS)
        state = 'ended_call' if ended else ('answered' if answer or steps else 'empty')
    except asyncio.TimeoutError:
        answer, state = '', 'timed_out'
    except Exception as exc:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({'error': f'{type(exc).__name__}: {exc}'[:800]}, ensure_ascii=False, indent=1))
        print('could not run:', type(exc).__name__, str(exc)[:300]); return 2
    finally:
        await router.close()
    seconds = round(time.monotonic() - began, 1)
    exp = case.get('expect') or {}
    called = [s['name'] for s in steps]
    arguments = ' '.join(json.dumps(s['arguments'], ensure_ascii=False) for s in steps)
    failed = []
    if exp.get('tools_any') and not set(exp['tools_any']) & set(called): failed.append('tools_any')
    failed += ['called ' + n for n in exp.get('tools_none', []) if n in called]
    failed += ['args ' + p for p in exp.get('args_all', []) if not re.search(p, arguments)]
    failed += ['args have ' + p for p in exp.get('args_none', []) if re.search(p, arguments)]
    failed += ['answer lacks ' + p for p in exp.get('answer_all', []) if not re.search(p, answer)]
    failed += ['answer has ' + p for p in exp.get('answer_none', []) if re.search(p, answer)]
    if state in ('timed_out', 'empty'): failed.append(state)
    if exp_route and routed != exp_route: failed.append(f'route {routed}')
    tokens = {k: sum(r.get(k, 0) for r in rounds) for k in ('input_tokens', 'cached_tokens', 'output_tokens')}
    used = rounds[0].get('model') if rounds else model
    result = {'route': routed, 'model': used, 'reasoning': os.environ.get('DAN_VOICE_ROUTER_BACKEND_REASONING') or backend.get('reasoning'), 'state': state, 'seconds': seconds,
              'rounds': [{k: r.get(k) for k in ('elapsed_ms', 'calls', 'output_tokens')} for r in rounds], 'tools': called, 'tokens': tokens,
              'answer': answer, 'steps': steps, 'failed': failed, 'passed': not failed}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps({k: result[k] for k in ('route', 'model', 'state', 'seconds', 'tools', 'failed')}, ensure_ascii=False))
    print('answer:', answer)
    return 0 if result['passed'] else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('case'); ap.add_argument('out')
    ap.add_argument('--model'); ap.add_argument('--reasoning')
    a = ap.parse_args()
    from dotenv import dotenv_values
    for k, v in dotenv_values('/Users/mikihonda/done/.env').items():
        if v is not None: os.environ.setdefault(k, v.strip())
    if a.model: os.environ['DAN_VOICE_ROUTER_BACKEND_MODEL'] = a.model
    if a.reasoning: os.environ['DAN_VOICE_ROUTER_BACKEND_REASONING'] = a.reasoning
    os.environ.setdefault('DAN_VOICE_ROUTER', '1')
    tree = Path(__file__).resolve().parent.parent
    os.chdir(tree); sys.path.insert(0, str(tree))
    sys.exit(asyncio.run(run(json.loads(Path(a.case).read_text()), Path(a.out), a.model)))


if __name__ == '__main__':
    main()
