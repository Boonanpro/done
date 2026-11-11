"""Run one call lookup (voice_lookup) on a recorded or written case, outside a call, and grade the answer from facts.

    python scripts/voice_lookup_compare.py <tree> <case.json> <out.json> [--model M --reasoning R]

<tree> is the code to run (/Users/mikihonda/done for what runs now, a worktree for a change): the same case run on both
shows before and after. The lookup is the real one: its model, its instructions, Dan's search and page reading. The
screen tools run against a room with no call, so they show nothing (both sides alike); hand_over is recorded, not started.

A case (tests/voice_lookups/*.json): "turns" (the call up to the request, role user/assistant), "task" (what the call
handed over), and "expect": "all" (every pattern must be in the answer, regex), "none" (none may be). A confirmation
question naming the right candidate counts as the answer reaching it. Exit 0 pass, 1 fail, 2 could not run.
Cost uses DeepSeek's peak prices (the higher ones) per 1M tokens: V4 Pro 1.32 in / 0.044 cached / 3.96 out.
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

PRICES = {'deepseek-v4-pro': (1.32, 0.044, 3.96), 'deepseek-flash': (0.3, 0.006, 1.2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('tree'); ap.add_argument('case'); ap.add_argument('out')
    ap.add_argument('--model'); ap.add_argument('--reasoning')
    a = ap.parse_args()
    from dotenv import dotenv_values
    for k, v in dotenv_values('/Users/mikihonda/done/.env').items():
        if v is not None: os.environ.setdefault(k, v.strip())
    if a.model: os.environ['DAN_VOICE_LOOKUP_MODEL'] = a.model
    if a.reasoning: os.environ['DAN_VOICE_LOOKUP_REASONING'] = a.reasoning
    os.environ.setdefault('DAN_VOICE_ROUTER', '1')
    tree = Path(a.tree).resolve()
    os.chdir(tree); sys.path.insert(0, str(tree))
    case = json.loads(Path(a.case).read_text())
    sys.exit(asyncio.run(run(case, Path(a.out))))


async def run(case, out):
    from app.services import voice_lookup
    from app.services.voice_sideband import Dialogue
    rounds, handed, events = [], [], []
    def record(phase, **f):
        if phase == 'lookup_round': rounds.append(f)
        elif phase.startswith('lookup_'): events.append({'phase': phase, **f})
    async def send(event): pass
    dialogue = Dialogue()
    for t in case['turns']:
        dialogue.add(t['role'], t['text'])
    owner = case.get('user_id') or '2582a188-ff24-4a4f-b989-6063034d90b2'
    call = voice_lookup.Call('compare', owner, 'voice-lookup-compare', dialogue, send, record)
    lookup = voice_lookup.Lookup(call, case['task'], case.get('label') or 'compare')
    async def hand_over(why, found=''):
        handed.append({'why': why, 'found': found[:2000]})
        lookup.state = 'handed_over'
    lookup.hand_over = hand_over
    from app.services import voice_sideband
    real, steps = voice_sideband.execute_call, []
    async def execute_call(item, *a, **k):   # what the lookup asked and a little of what came back, to read a run later
        out_item = await real(item, *a, **k)
        steps.append({'name': item.get('name'), 'arguments': str(item.get('arguments'))[:300], 'output': str(out_item.get('output'))[:600]})
        return out_item
    voice_sideband.execute_call = execute_call
    began = time.monotonic()
    try:
        answer = await asyncio.wait_for(lookup._loop(), voice_lookup.SECONDS)
        state = 'answered' if lookup.state == 'running' else lookup.state
    except asyncio.TimeoutError:
        answer, state = '', 'timed_out'
    except Exception as exc:
        out.write_text(json.dumps({'error': f'{type(exc).__name__}: {exc}'[:500]}, ensure_ascii=False, indent=1))
        print('could not run:', type(exc).__name__, str(exc)[:300]); return 2
    seconds = round(time.monotonic() - began, 1)
    text = answer + ' ' + ' '.join(lookup.progress) + ' ' + ' '.join(h['why'] + h['found'] for h in handed)
    exp = case.get('expect') or {}
    missing = [p for p in exp.get('all', []) if not re.search(p, text)]
    banned = [p for p in exp.get('none', []) if re.search(p, answer)]
    model = voice_lookup.MODEL
    price = PRICES.get(model)
    tokens = {k: sum(r.get(k, 0) for r in rounds) for k in ('input_tokens', 'cached_tokens', 'output_tokens')}
    usd = None
    if price:
        usd = round(((tokens['input_tokens'] - tokens['cached_tokens']) * price[0] + tokens['cached_tokens'] * price[1]
                     + tokens['output_tokens'] * price[2]) / 1e6, 5)
    tools = [n for r in rounds for n in r.get('calls', [])]
    result = {'model': model, 'reasoning': voice_lookup.REASONING, 'state': state, 'seconds': seconds, 'rounds': len(rounds),
              'tools': tools, 'round_detail': [{k: r.get(k) for k in ('elapsed_ms', 'calls', 'output_tokens')} for r in rounds], 'tokens': tokens, 'usd': usd, 'answer': answer, 'progress': lookup.progress, 'steps': steps, 'events': events, 'handed_over': handed,
              'missing': missing, 'banned': banned, 'passed': not missing and not banned}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps({k: result[k] for k in ('model', 'state', 'seconds', 'rounds', 'usd', 'passed', 'missing', 'banned')}, ensure_ascii=False))
    print('answer:', answer)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    main()
