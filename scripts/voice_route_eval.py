"""Run the owner's real call requests through the call's router (voice_router) and say which went to the wrong place.

    python scripts/voice_route_eval.py <owner user id> [cases.json] [--repeat N] [--only id,id]

The cases (tests/voice_routes/real_requests.json) are what the owner said on calls from 2026-10-23 to 11-04, with the
places the request could rightly go to. Each case is asked of Jev with the same state and questions the router builds
during a call (voice_router.questions), so a change to the route descriptions is checked here before a call. Exit 1 when a
case went somewhere not allowed; exit 2 when Jev could not be asked (the check could not see).
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def one(judge, case, targets):
    from app.services import voice_router
    running = [{'label': label, 'kind': 'job', 'id': f'job{i}'} for i, label in enumerate(case.get('running') or [])]
    turns = [{'role': who, 'text': text} for who, text in case.get('context') or []] + [{'role': '本人', 'text': case['say']}]
    state = {'conversation': turns, 'running_work': [w['label'] for w in running], 'screen': ''}
    started = time.monotonic()
    got = await judge.choose(state, voice_router.questions(running, {name: f'「{name}」' for name in targets}))
    ms = round((time.monotonic() - started) * 1000)
    if not got.get('available'):
        return None, 0.0, ms, ''
    route, probability = voice_router.decide(got['answers'], running)
    if route.startswith(('stop:', 'change:')):   # stop:job:job0 -> stop_0, the way the cases name them
        route = route.split(':')[0] + '_' + route.rsplit('job', 1)[-1]
    target, sure = voice_router.chosen(got['answers'], 'target')
    return route, probability, ms, (target if sure >= voice_router.CONFIDENT else '')


async def main():
    argv = sys.argv[1:]
    args = [a for i, a in enumerate(argv) if not a.startswith('--') and not (i and argv[i - 1] in ('--repeat', '--only'))]
    user = args[0]
    path = Path(args[1]) if len(args) > 1 else ROOT / 'tests' / 'voice_routes' / 'real_requests.json'
    repeat = int(sys.argv[sys.argv.index('--repeat') + 1]) if '--repeat' in sys.argv else 1
    only = set(sys.argv[sys.argv.index('--only') + 1].split(',')) if '--only' in sys.argv else None
    cases = [c for c in json.loads(path.read_text(encoding='utf-8'))['cases'] if not only or c['id'] in only]
    from app.services.jev_decisions import Decisions
    from app.services.voice_stage import artifact_rows
    rows = await artifact_rows(user)
    targets = list(dict.fromkeys(str(r.get('label') or r.get('slug') or '')[:60] for r in rows[:120] if r.get('label') or r.get('slug')))
    wrong, blind, times = [], 0, []
    async with Decisions(user, timeout=3.0, max_calls=len(cases) * repeat + 5) as judge:
        for case in cases:
            for _ in range(repeat):
                route, probability, ms, target = await one(judge, case, targets)
                times.append(ms)
                if route is None:
                    blind += 1
                    print(f'?? {case["id"]}: Jev に聞けなかった')
                    continue
                ok = route in case['expect']
                if not ok: wrong.append(case['id'])
                print(f'{"OK" if ok else "NG"} {case["id"]}: {route} ({probability:.2f}, {ms}ms)' + (f' 画面: {target}' if target else '')
                      + ('' if ok else f'  ← 正しいのは {"/".join(case["expect"])}'))
    total = len(cases) * repeat
    print(f'\n{total - len(wrong) - blind}/{total} が正しい行き先。外れ {len(wrong)}、聞けなかった {blind}。'
          f' 判断の時間 中央値 {sorted(times)[len(times) // 2] if times else 0}ms')
    sys.exit(2 if blind == total else 1 if wrong else 0)


if __name__ == '__main__':
    asyncio.run(main())
