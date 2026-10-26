"""Free post-merge integration comparison, NOT a call or a speech-latency measurement.

Reuses the ten synthetic questions and backend arguments recorded in the paid test.
Both versions receive the same full text at t=0 and backend requests at t=.5 s.
Judgement (.15 s), route (.15 s), data reads (.8 s), and drawings are fixtures.
The real prefetch, dispatch, Dialogue and merged Stage code run on the Mac clock.
No credentials, network, production files, or work queues are used.
"""
import asyncio
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASELINE = 'd7ceeca472df9111046f6f90ca904b9c4793b1f0'


async def main(mode):
    from app.services import voice_prefetch as P, voice_sideband as S, voice_responses as R
    from app.services import voice_stage as V
    if mode == 'baseline':
        for module in (P, R, S):
            source = subprocess.check_output(['git', 'show', BASELINE + ':' + str(Path(module.__file__).relative_to(ROOT))], text=True, cwd=ROOT)
            exec(compile(source, module.__file__, 'exec'), module.__dict__)
    def no_network(*a, **kw): raise AssertionError('offline check attempted network')
    socket.socket.connect = no_network
    socket.socket.connect_ex = no_network
    P.enabled = lambda: True
    # Curated evidence, not live runtime data. Only fixed synthetic questions/args.
    evidence = json.loads((ROOT/'docs/current/voice-decide-early-20261025.json').read_text())
    rows = evidence['baseline']
    if isinstance(rows, dict): rows = rows['rows']
    output = []
    with tempfile.TemporaryDirectory(prefix='voice-early-stage-') as temporary:
        V.ROOT = Path(temporary)
        for index, row in enumerate(rows):
            calls, events = [], []
            name = row['expected']
            def record(phase, **fields): events.append({'phase':phase, **fields})
            async def kind(self, text):
                await asyncio.sleep(.15)
                return 'read' if index < 5 else 'work'
            async def plan(self, text):
                await asyncio.sleep(.15)
                args = dict(row['requests'][0])
                if name == 'search_records': args = {'query':text}
                return name, args
            P.Prefetch.kind = kind
            if mode != 'baseline': P.Prefetch.read_plan = plan
            async def fixture(fn, args, *a, **kw):
                assert fn in ('job_status','get_calendar','search_records','room_files','list_operations','start_work')
                calls.append({'name':fn, 'args':args, 't':time.monotonic()})
                if fn in ('job_status','get_calendar','search_records','room_files'): await asyncio.sleep(.8)
                return {'fixture':fn, 'accepted': fn == 'start_work'}
            R.run_function = fixture
            async def draw(*a):
                return {'action':'replace','caption':'試験の図','program':'root = Flow([{id: "a", label: "きっぷ", icon: "ticket"}, {id: "b", label: "改札", icon: "gate"}])'}, {}
            d = S.Dialogue()
            p = P.Prefetch('test-user', record, **({'room_id':'fixture'} if mode != 'baseline' else {}))
            d.prefetch = p
            stage = V.Stage('fixture', str(index), d, record, ask=draw)
            start = time.monotonic()
            d.add('user', row['q']); p.heard(d); stage.heard('user', row['q'])
            # Draw through the real merged Stage concurrently with the prefetch.
            drawing = asyncio.create_task(stage.show('試験の図'))
            await asyncio.sleep(.5)
            for args in row['requests']:
                result = await S.execute_call({'name':name,'arguments':json.dumps(args),'call_id':'test'},'test-user','fixture',d,record,'test')
                assert json.loads(result['output'])['fixture'] == name
            done = time.monotonic()
            await drawing
            await p.close(); stage.close()
            state = V.read_state('fixture')
            assert state['version'] == index + 1 and state['active'] is False
            assert 'icon: "doc"' in state['program'] and 'icon: "check"' in stage.summary()
            assert len([c for c in calls if c['name']=='start_work']) == (len(row['requests']) if index >= 5 else 0)
            assert all(c['t'] - start >= .5 for c in calls if c['name']=='start_work')
            matching = [c for c in calls if c['name']==name]
            output.append({'q':row['q'],'expected':name,'start_after_text_s':round(matching[0]['t']-start,3),
                           'done_after_text_s':round(done-start,3),'hits':p.counts['hit'],
                           'work_requests':len([c for c in calls if c['name']=='start_work']),
                           'stage_version':state['version'],'functions':[c['name'] for c in calls]})
    result = {'mode':mode,'baseline_commit':BASELINE,'type':'offline fixtures, full text; not audio or model evaluation',
              'judge_s':.15,'route_s':.15,'backend_request_s':.5,'read_s':.8,'rows':output}
    target = ROOT/'.tmp/voice-early'/('integration-'+mode+'.json')
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('baseline','after'): raise SystemExit('baseline|after')
    asyncio.run(main(sys.argv[1]))
