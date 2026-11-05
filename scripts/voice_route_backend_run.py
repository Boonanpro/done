"""A call's request from Jev's routing to chat Dan's result, without the speech model (no call is placed).

    python scripts/voice_route_backend_run.py <scenario.json> <out dir> [--model astra|opus|fable] [--keep-room]

The scenario's turns are a real call's words up to a request (tests/voice_routes/salon_backend.json: the owner's salon
request of 2026-11-05 0:59). In a room made for the run (deleted afterwards), the call's router (voice_router.Router)
gets one delegation for the last words, exactly as a call would give it; the work it starts runs in the running Core like
any call's work. While it runs, the call's own parts read it as in a call: the screen follower (what the owner's call
screen would show) and the silent state / spoken findings (voice_sideband.tell_state). Nothing reaches a speech model.

Read from facts: the route, seconds to the result, the result's text against the scenario's patterns, and every screen
the call would have shown (a flat white or black one is a fail). Exit 0 pass, 1 fail, 2 the run could not see.
"""
import asyncio
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main(scenario_path, out_dir, model='', keep=False):
    import os
    os.environ.setdefault('DAN_VOICE_ROUTER', '1')
    from app.services.owner import resolve_owner_user_id
    from app.services.project_service import ProjectService
    from app.services import voice_router, voice_lookup, voice_calls, voice_stage, parallel_job_runner
    from app.services.voice_sideband import Dialogue, tell_state, flush_state
    from app.services.voice_worker_screen import Follower
    from app.services.voice_screen_media import blank
    from app.services.command_job_state import list_owned, TERMINAL
    scenario = json.loads(Path(scenario_path).read_text(encoding='utf-8'))
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    owner = resolve_owner_user_id()
    projects = ProjectService()
    project = await projects.create_project(owner, '通話の振り分けの試験', description='voice_route_backend_run.py が作り、終わると消す部屋')
    room = project['room_id']
    session = 'route-run-' + str(int(time.time()))
    events, said, told = [], [], {}
    record = lambda phase, **f: events.append({'at': round(time.monotonic() - began, 2), 'phase': phase, **f})
    async def send(event):
        said.append({'at': round(time.monotonic() - began, 2), 'type': event['type'], 'content': event.get('content'), 'delegation_id': event.get('delegation_id')})
    if model:
        parallel_job_runner.room_model = lambda room_id: model
    began = time.monotonic()
    run = {'scenario': scenario_path, 'room_id': room, 'route': None, 'job_id': None, 'result': None, 'seconds': None, 'screens': []}
    voice_calls.begin(room, session)   # the result stays with the call: the room's Dan is not woken
    stage = call = router = None
    try:
        dialogue = Dialogue()
        dialogue.began_iso = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
        for role, text in scenario['turns']:
            dialogue.add(role, text + ' ')
        stage = voice_stage.Stage(room, session, dialogue, record, user_id=owner)
        router = voice_router.Router(session, owner, room, dialogue, send, record, {}, backend=None, stage=stage)
        call = voice_lookup.open_call(session, owner, room, dialogue, send, record)
        call.router = router
        follower = Follower(stage, owner, room, dialogue.began_iso)
        await router.answer('item_route_run', time.monotonic())
        run['route'] = next((e.get('route') for e in events if e['phase'] == 'route_chosen'), None)
        run['job_id'] = next(iter(router.jobs), None)
        seen = {}
        later = list(scenario.get('later') or [])   # the owner's later words (「今どういう状況？」), each a new delegation
        run['later'] = []
        deadline = time.monotonic() + max(360, scenario['success'].get('seconds', 180) * 2)
        while time.monotonic() < deadline:
            await asyncio.sleep(1)
            if later and time.monotonic() - began >= later[0]['at']:
                turn = later.pop(0)
                dialogue.add('user', turn['say'] + ' ')
                mark = len(said)
                await router.answer(f'item_later_{len(run["later"])}', time.monotonic())
                replies = [x for x in said[mark:] if (x['delegation_id'] or '').startswith('item_later')]
                run['later'].append({'say': turn['say'], 'route': [e.get('route') for e in events if e['phase'] == 'route_chosen'][-1],
                                     'replies': replies, 'expect_route': turn.get('route')})
            jobs = list_owned(owner, room)
            follower.update(jobs)
            for job in jobs:
                fresh = [e for e in job.get('events') or [] if e.get('seq', 0) > seen.get(job['id'], 0)]
                seen[job['id']] = job.get('seq', 0)
                if fresh: await tell_state(send, job, fresh, told, record)
            await flush_state(send, told, record)
            lookups_running = any(l.state == 'running' for l in call.lookups.values())
            if not run['job_id'] and router.jobs:
                run['job_id'] = next(iter(router.jobs))
            job = next((j for j in jobs if j['id'] == run['job_id']), None)
            if job and job['state'] in TERMINAL | {'awaiting_confirmation'}:
                run['result'] = job.get('result') or job.get('error') or (job.get('confirmation') or {}).get('summary')
                run['state'] = job['state']
                run['seconds'] = round(time.monotonic() - began, 1)
                break
            answered = [l for l in call.lookups.values() if l.state == 'answered']
            if not run['job_id'] and answered and not lookups_running:
                run['result'], run['seconds'], run['state'] = answered[-1].answer, round(time.monotonic() - began, 1), 'answered'
                break
        for scene in stage.scenes:
            image = scene.get('image') or ''
            run['screens'].append({'at': scene.get('at'), 'caption': scene.get('caption'), 'image': image, 'frame': scene.get('frame'),
                                   'program': bool(scene.get('program')), 'blank': bool(image) and blank(image)})
    finally:
        if call is not None: voice_lookup.close_call(call)
        if router is not None: await router.close()
        if stage is not None: stage.close()
        voice_calls.end(room, session)
        if not keep:
            try: await projects.delete_project(project['id'], owner)
            except Exception as exc: print('room not deleted:', exc)
    run['said'], run['events'] = said, events
    (out / 'run.json').write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding='utf-8')
    goal = scenario['success']
    checks = {'route': run['route'] in goal.get('route', [run['route']]),
              'in_time': run['seconds'] is not None and run['seconds'] <= goal.get('seconds', 180),
              'result': bool(run['result']) and all(re.search(p, run['result']) for p in goal.get('result_has', [])),
              'screens': not any(s['blank'] or s['program'] for s in run['screens']),
              # each later question answered once, by the route it should take (a status: one commentary, no second answer)
              'later': all(l['route'] in (l['expect_route'] or [l['route']]) and len([r for r in l['replies'] if r['type'] == 'session.commentary.append']) == 1
                           for l in run['later'])}
    print(json.dumps({'checks': checks, 'route': run['route'], 'seconds': run['seconds'], 'state': run.get('state'),
                      'result': (run['result'] or '')[:600], 'screens': len(run['screens']),
                      'later': [{'say': l['say'], 'route': l['route'], 'replies': [(r['type'].split('.')[1], r['at'], r['content']) for r in l['replies']]} for l in run['later']],
                      'spoken': [s['content'] for s in said if s['type'] == 'session.commentary.append']}, ensure_ascii=False, indent=1))
    if run['route'] is None:
        return 2
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    argv = sys.argv[1:]
    model = argv[argv.index('--model') + 1] if '--model' in argv else ''
    paths = [a for i, a in enumerate(argv) if not a.startswith('--') and not (i and argv[i - 1] == '--model')]
    sys.exit(asyncio.run(main(paths[0], paths[1], model, '--keep-room' in argv)))
