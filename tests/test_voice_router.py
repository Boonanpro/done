"""The call's requests routed by Jev (voice_router, 2026-11-05). In the owner's 0:59 call a salon's free slots went to
the short web lookup three times and came back 「確認できなかった」; 「今どういう状況？」 took a 6 s backend round and was
answered twice. Here: where each request goes, what the call hears, and what it does not."""
import asyncio
import io
import json
import time
from types import SimpleNamespace

import pytest

from app.services import voice_router, voice_lookup
from app.services.voice_sideband import Dialogue


@pytest.fixture(autouse=True)
def router_on(monkeypatch):
    monkeypatch.setenv('DAN_VOICE_ROUTER', '1')
    monkeypatch.setenv('DAN_VOICE_PLAIN', '1')
    monkeypatch.delenv('DAN_VOICE_BACKGROUND', raising=False)


def answer(choice, p, kind='choice'):
    return {'type': kind, 'choice': choice, 'probabilities': {choice: p}, 'confidence': p}


class Judge:
    """Jev's answers given in order; the state and questions it was asked are kept."""
    def __init__(self, *answers, available=True):
        self.answers, self.available, self.asked = list(answers), available, []

    async def choose(self, state, questions):
        self.asked.append((state, questions))
        if not self.available:
            return {'available': False, 'elapsed_ms': 1}
        return {'available': True, 'answers': self.answers.pop(0), 'elapsed_ms': 150}

    async def __aexit__(self, *a):
        return None


def router(monkeypatch, judge, *, jobs=(), backend=None, said=('尼崎駅の近くでプールのあるジムを探して',)):
    sent, log = [], []
    async def send(event): sent.append(event)
    dialogue = Dialogue()
    for text in said:
        dialogue.add('user', text)
    dialogue.heard_at = 0.0
    r = voice_router.Router('s', 'u', 'r', dialogue, send, lambda phase, **f: log.append((phase, f)), {}, backend=backend)
    r.judge = judge
    r.targets = {'X運用室': '/artifacts/x-operation'}
    monkeypatch.setattr('app.services.command_job_state.list_owned', lambda user, room: list(jobs))
    return r, sent, log


def test_the_session_hands_its_delegations_to_this_server():
    from app.services import voice_live
    config = voice_live.session_config(room_id='r', user_id='u')
    assert config['delegation'] == {'type': 'client', 'acknowledgement_delay_ms': 800}
    assert config['_backend']['model'] and any(t['name'] == 'run_in_background' for t in config['_backend']['tools'])
    assert 'latest work state' in config['instructions']   # 「今どう？」 is answered from the state given silently


def test_a_word_about_running_work_wins_over_a_new_route():
    running = [{'label': 'しゅんさんとみひろさんの空き', 'kind': 'job', 'id': 'j1'}]
    # 「ホットペッパーで確認するんだって」: as a route it was a new site job; asked about the running work it is its correction
    route, p = voice_router.decide({'route': answer('site', .96), 'work_0': answer('change', .9)}, running)
    assert route == 'change:job:j1'
    route, p = voice_router.decide({'route': answer('other', .4), 'work_0': answer('status', .9)}, running)
    assert route == 'status'
    route, p = voice_router.decide({'route': answer('lookup', .9), 'work_0': answer('new', .9)}, running)
    assert route == 'lookup'
    route, p = voice_router.decide({'route': answer('site', .5)}, [])
    assert route == 'other'   # unsure: the earlier backend decides


@pytest.mark.asyncio
async def test_status_is_answered_at_once_from_the_job_files_as_the_one_thing_said(monkeypatch):
    job = {'id': 'j1', 'state': 'running', 'task': '今回のユーザー発言（原文）:\nしゅんさんとみひろさんの空き' + voice_router.TRANSCRIPT + '…',
           'created_at': '2026-11-05T00:00:00+00:00', 'last_tool': {'name': 'browser', 'action': 'open_target'},
           'last_observation': {'text': 'URL: https://beauty.hotpepper.jp/slnH000000/\nタイトル: LIPPS hair 梅田annex'},
           'events': [{'seq': 1, 'kind': 'progress', 'text': '【途中】みひろさんは6日15:30から予約が入っている', 'at': ''},
                      {'seq': 2, 'kind': 'tool', 'text': 'browser', 'label': 'browser:open_target', 'at': ''}]}
    r, sent, log = router(monkeypatch, Judge({'route': answer('status', .97), 'calendar': answer('other', .9), 'work_0': answer('status', .97)}),
                          jobs=[job], said=['今どういう状況？'])
    await r.answer('del_1', time.monotonic())
    assert [e['type'] for e in sent] == ['session.commentary.append']
    assert sent[0]['delegation_id'] == 'del_1'
    said = sent[0]['content']
    assert 'しゅんさんとみひろさんの空き' in said and 'LIPPS hair 梅田annex' in said and 'みひろさんは6日15:30から' in said
    assert 'browser' not in said and 'open_target' not in said   # no tool names in what is said
    assert ('route_chosen', ) == (log[0][0],) and log[0][1]['route'] == 'status'


@pytest.mark.asyncio
async def test_site_work_goes_to_chat_dan_with_the_calls_transcript(monkeypatch):
    started = []
    async def execute(params, room_id, user_id, voice_handoff=False):
        started.append((params, voice_handoff))
        return {'accepted': True, 'receipt': {'id': 'job-1'}}
    monkeypatch.setattr('app.services.command_center.execute', execute)
    monkeypatch.setattr('app.services.parallel_job_runner.room_model', lambda room: 'opus')
    r, sent, log = router(monkeypatch, Judge({'route': answer('site', .9), 'calendar': answer('other', .9)}),
                          said=['しゅんさんとみひろさんなんですけど', '六日までに両方空いてる時間を、続けて入れられる所で'])
    created = time.monotonic()
    await r.answer('del_2', created)
    params, handoff = started[0]
    assert params['engine'] == 'make' and params['model'] == 'opus' and handoff
    head, transcript = params['task'].split(voice_router.TRANSCRIPT, 1)
    assert 'しゅんさんとみひろさんなんですけど' in head and '六日までに' in head   # the request said over two turns
    assert '本人: しゅんさんとみひろさんなんですけど' in transcript and '【途中】' in transcript
    assert sent[-1]['type'] == 'session.commentary.append' and sent[-1]['delegation_id'] == 'del_2'   # before the acknowledgement: said once
    assert r.jobs == {'job-1': voice_router.label_of('しゅんさんとみひろさんなんですけど六日までに両方空いてる時間を、続けて入れられる所で')}


@pytest.mark.asyncio
async def test_past_the_acknowledgement_a_notice_of_work_begun_is_silent(monkeypatch):
    async def execute(params, room_id, user_id, voice_handoff=False): return {'accepted': True, 'receipt': {'id': 'job-2'}}
    monkeypatch.setattr('app.services.command_center.execute', execute)
    monkeypatch.setattr('app.services.parallel_job_runner.room_model', lambda room: 'opus')
    r, sent, log = router(monkeypatch, Judge({'route': answer('app', .9), 'calendar': answer('other', .9)}), said=['LINEでこすもすさんに送っておいて'])
    await r.answer('del_3', time.monotonic() - 2)   # the speech model was asked for its own 「やっとくね」 already
    assert [e['type'] for e in sent] == ['session.thinking.append']


@pytest.mark.asyncio
async def test_a_correction_replaces_the_running_lookup(monkeypatch):
    starts = []
    class Call:
        closed = False
        lookups = {'bg_1': SimpleNamespace(id='bg_1', state='running', label='プールのあるジム', task='頼み: この辺でプールのあるジム', progress=[], started=time.monotonic())}
        def start(self, task, label, replaces=''):
            starts.append((task, label, replaces))
    monkeypatch.setattr(voice_lookup, 'for_call', lambda u, r: Call())
    r, sent, log = router(monkeypatch, Judge({'route': answer('lookup', .9), 'calendar': answer('other', .9), 'work_0': answer('change', .9)}),
                          said=['あまがさきなんですけど俺が住んでるの'])
    await r.answer('del_4', time.monotonic())
    task, label, replaces = starts[0]
    assert replaces == 'bg_1' and 'あまがさき' in task and 'プールのあるジム' in task


@pytest.mark.asyncio
async def test_without_jev_or_when_unsure_the_earlier_backend_answers(monkeypatch):
    calls = []
    class Client:
        def __init__(self): self.responses = self
        async def create(self, **kw):
            calls.append(kw)
            return SimpleNamespace(id='resp', output=[], output_text='郵便番号は660-0807です。')
    monkeypatch.setattr(voice_lookup, '_client', lambda: Client())
    backend = {'model': 'gpt-6-luna', 'instructions': 'i', 'tools': [], 'tool_choice': 'auto', 'parallel_tool_calls': True, 'reasoning': {'effort': 'low'}}
    r, sent, log = router(monkeypatch, Judge(available=False), backend=backend, said=['郵便番号なんだっけ'])
    await r.answer('del_5', time.monotonic())
    assert calls[0]['model'] == 'gpt-6-luna' and '郵便番号なんだっけ' in calls[0]['input'][0]['content']
    assert sent[-1] == {**sent[-1], 'type': 'session.commentary.append', 'delegation_id': 'del_5', 'content': '郵便番号は660-0807です。'}


@pytest.mark.asyncio
async def test_a_stuck_lookup_goes_to_chat_dan_and_says_nothing(monkeypatch):
    handed = []
    async def start_chat_dan(user_id, room_id, dialogue, words, carried=''):
        handed.append((words, carried))
        return {'accepted': True, 'receipt': {'id': 'job-9'}}
    monkeypatch.setattr(voice_router, 'start_chat_dan', start_chat_dan)
    monkeypatch.setattr(voice_lookup, 'SECONDS', .05)
    class Slow:
        def __init__(self): self.responses = self
        async def create(self, **kw):
            await asyncio.sleep(1)
    monkeypatch.setattr(voice_lookup, '_client', lambda: Slow())
    monkeypatch.setattr(voice_lookup, 'instructions', lambda: 'i')
    monkeypatch.setattr(voice_lookup, 'tools', lambda: [])
    sent = []
    async def send(event): sent.append(event)
    call = voice_lookup.Call('s', 'u', 'r', Dialogue(), send, lambda *a, **k: None)
    lookup, _ = call.start('この通話で本人が今頼んだこと（言葉のまま）: しゅんさんの6日の空き', 'しゅんさんの空き')
    await lookup.task_handle
    assert lookup.state == 'handed_over' and handed[0][0].startswith('しゅんさんの6日の空き')
    assert not [e for e in sent if e['type'] == 'session.commentary.append']   # no 「答えが出なかった」


def test_a_lookup_only_reads_when_the_call_is_routed():
    names = [t['name'] for t in voice_lookup.tools()]
    assert 'hand_over' in names and 'places' in names
    assert not {'browser', 'browser_plan', 'phone', 'dan_tool', 'dan_tool_help', 'show_external_screen'} & set(names)
    assert 'hand_over' in voice_lookup.instructions()


@pytest.mark.asyncio
async def test_job_state_reaches_the_call_silently_and_a_marked_finding_is_said():
    from app.services import voice_sideband
    sent, told, log = [], {}, []
    async def send(event): sent.append(event)
    job = {'id': 'j1', 'state': 'running', 'task': '今回のユーザー発言（原文）:\nしゅんさんの空き', 'events': []}
    fresh = [{'seq': 1, 'kind': 'tool', 'text': 'browser', 'label': 'browser:open_target'},
             {'seq': 2, 'kind': 'progress', 'text': '【途中】しゅんさんは6日の16時と17時が空いている'}]
    await voice_sideband.tell_state(send, job, fresh, told, lambda phase, **f: log.append(phase))
    kinds = [(e['type'], e['content']) for e in sent]
    assert kinds[0] == ('session.commentary.append', '作業「しゅんさんの空き」の途中で分かったこと: しゅんさんは6日の16時と17時が空いている')
    assert kinds[1][0] == 'session.thinking.append' and 'ページを開いている' in kinds[1][1] and 'browser' not in kinds[1][1]
    await voice_sideband.tell_state(send, job, [{'seq': 3, 'kind': 'tool', 'text': 'browser', 'label': 'browser:click'}], told, lambda *a, **k: None)
    assert len(sent) == 2   # not more often than STATE_EVERY_S


def test_the_screen_does_not_draw_the_talk_by_itself(monkeypatch, tmp_path):
    from app.services import voice_stage
    monkeypatch.setattr(voice_stage, 'ROOT', tmp_path)
    stage = voice_stage.Stage('room-x', 's', Dialogue(), lambda *a, **k: None, user_id='u')
    stage.heard('assistant', 'みひろさんのところで眉毛を整えてから、しゅんさんのところで髪を切る流れがいいと思う。')
    assert stage._timer is None and not stage.listening


def test_a_flat_white_screenshot_is_not_shown(monkeypatch, tmp_path):
    from PIL import Image
    from app.services import voice_screen_media
    monkeypatch.setattr(voice_screen_media, 'ROOT', tmp_path)
    folder = tmp_path / 'room.screens'; folder.mkdir()
    Image.new('RGB', (400, 300), 'white').save(folder / ('a' * 32 + '.png'))
    page = Image.new('RGB', (400, 300), 'white')
    for x in range(0, 400, 20):
        for y in range(0, 300, 3): page.putpixel((x, y), (20, 20, 20))
    page.save(folder / ('b' * 32 + '.png'))
    assert voice_screen_media.blank('/api/v1/voicelog/stage/room/image/' + 'a' * 32 + '.png')
    assert not voice_screen_media.blank('/api/v1/voicelog/stage/room/image/' + 'b' * 32 + '.png')
    assert not voice_screen_media.blank('https://example.com/x.png')   # not judged


@pytest.mark.asyncio
async def test_the_room_shows_the_owners_words_not_the_transcript(monkeypatch):
    from app.services import make_job_runner
    posted, saved = [], {}
    task = '今回のユーザー発言（原文）:\nしゅんさんの空き' + voice_router.TRANSCRIPT + '…:\n本人: …' + voice_router.CALL_JOB_NOTE
    monkeypatch.setattr(make_job_runner.state, 'read', lambda job_id: {'task': task})
    monkeypatch.setattr(make_job_runner.state, 'change', lambda job_id, f: (f(saved), saved)[1])
    class Chat:
        async def send_message(self, room, user, text, sender_type=''): posted.append(text)
    monkeypatch.setattr('app.services.chat_service.ChatService', Chat)
    await make_job_runner.note_request({'id': 'j', 'room_id': 'r', 'user_id': 'u'})
    assert posted == ['📞 通話からの依頼: しゅんさんの空き']
    assert voice_router.TRANSCRIPT in saved['task'] and saved['title'] == 'しゅんさんの空き'


def test_the_routed_follower_comes_back_to_the_work_but_holds_a_page_just_shown():
    from app.services.voice_worker_screen import Follower
    class Stage:
        user_id, room_id, version, image, frame, listening, _last_replace = 'u', 'r', 1, '', '', False, -1e9
        def _live(self): return ''
        def _apply(self, caption, image):
            self.image = image; self.version += 1
    def job(at, url):
        return dict(id='j', user_id='u', origin_room_id='r', state='running', browser_room='w', screen=dict(at=at, url=url, browser_room='w'))
    stage = Stage(); f = Follower(stage, 'u', 'r', '2026-11-05T00:00:00')
    f.update([job('2026-11-05T00:01:00', '/api/v1/files/first.png')]); assert stage.image.endswith('first.png')
    stage._apply('a page the owner asked for', image='/api/v1/files/page.png'); stage._last_replace = time.monotonic()
    f.update([job('2026-11-05T00:02:00', '/api/v1/files/second.png')]); assert stage.image.endswith('page.png')   # held
    stage._last_replace = time.monotonic() - 60
    f.update([job('2026-11-05T00:03:00', '/api/v1/files/third.png')]); assert stage.image.endswith('third.png')   # follows the work again


@pytest.mark.asyncio
async def test_a_client_delegation_on_the_real_sideband_is_answered_with_its_id(monkeypatch, tmp_path):
    """The real sideband loop with a fake socket: the owner's words, then a client delegation; the answer goes back on the
    same connection with the delegation's id, before the acknowledgement delay."""
    import websockets
    from app.services import voice_sideband as S, voice_stage, voice_calls, voice_prefetch, jev_decisions
    monkeypatch.setattr(voice_stage, 'ROOT', tmp_path)
    monkeypatch.setattr(voice_prefetch, 'enabled', lambda: False)
    monkeypatch.setattr(voice_calls, 'begin', lambda *a: None)
    monkeypatch.setattr(voice_calls, 'end', lambda *a: None)
    monkeypatch.setattr(S, 'note', lambda *a, **kw: None)
    async def idle(*a, **k): await asyncio.Event().wait()
    for name in ('job_feed', 'chat_feed', 'summon_feed', 'finish_call', 'call_log'):
        monkeypatch.setattr(S, name, idle if name.endswith('feed') else (lambda *a, **k: asyncio.sleep(0)))
    monkeypatch.setattr(voice_lookup, 'open_call', lambda *a, **k: SimpleNamespace(router=None, lookups={}, closed=False, close=lambda: None, user_id='u', room_id='r'))
    monkeypatch.setattr(voice_lookup, 'close_call', lambda call: None)
    monkeypatch.setattr('app.services.command_job_state.list_owned', lambda user, room: [])
    class Jev:
        def __init__(self, *a, **k): pass
        async def choose(self, state, questions):
            assert state['conversation'][-1] == {'role': '本人', 'text': '今どうなってる？'}
            return {'available': True, 'elapsed_ms': 150, 'answers': {'route': answer('status', .95), 'calendar': answer('other', .9)}}
        async def __aexit__(self, *a): return None
    monkeypatch.setattr(jev_decisions, 'Decisions', Jev)
    monkeypatch.setattr(voice_router.Router, 'targets_now', lambda self: asyncio.sleep(0, result={}))
    out = []
    class Socket:
        count = 0
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def send(self, text): out.append(json.loads(text))
        async def recv(self):
            self.count += 1
            if self.count == 1: return json.dumps({'type': 'session.input_transcript.delta', 'delta': '今どうなってる？'})
            if self.count == 2: return json.dumps({'type': 'session.delegation.created', 'delegation': {'id': 'item_x', 'type': 'delegation', 'target': 'client'}})
            for _ in range(40):
                if out: break
                await asyncio.sleep(.05)
            return json.dumps({'type': 'session.closed'})
    monkeypatch.setattr(websockets, 'connect', lambda *a, **kw: Socket())
    began = time.monotonic()
    await S._run('call-1', 'u', 'r', 'key', True, backend={'model': 'gpt-6-luna', 'instructions': 'i', 'tools': []})
    answers = [e for e in out if e.get('delegation_id') == 'item_x']
    assert answers and answers[0]['type'] == 'session.commentary.append' and '動いている作業や調べものは無い' in answers[0]['content']


@pytest.mark.asyncio
async def test_words_said_on_after_a_request_are_judged_alone(monkeypatch):
    """No words of Dan between the request and 「今どういう状況？」: the transcript keeps them as one turn. Judged as one,
    the request was started again (backend run 2026-11-05 salon2)."""
    async def execute(params, room_id, user_id, voice_handoff=False): return {'accepted': True, 'receipt': {'id': 'job-1'}}
    monkeypatch.setattr('app.services.command_center.execute', execute)
    monkeypatch.setattr('app.services.parallel_job_runner.room_model', lambda room: 'astra')
    judge = Judge({'route': answer('site', .9), 'calendar': answer('other', .9)},
                  {'route': answer('status', .9), 'calendar': answer('other', .9), 'work_0': answer('status', .95)})
    job = {'id': 'job-1', 'state': 'running', 'task': '今回のユーザー発言（原文）:\n髪と眉毛の空き', 'created_at': '2026-11-05T00:00:00+00:00', 'events': []}
    r, sent, log = router(monkeypatch, judge, jobs=[job], said=['しゅんさんとみひろさんの両方空いてる時間を探して'])
    await r.answer('d1', time.monotonic())
    r.dialogue.add('user', '今どういう状況？')
    await r.answer('d2', time.monotonic())
    second = judge.asked[1][0]['conversation']
    assert second[-1] == {'role': '本人', 'text': '今どういう状況？'} and second[-2]['text'].startswith('しゅんさん')
    assert [f['route'] for p, f in log if p == 'route_chosen'] == ['site', 'status']
    assert sent[-1]['type'] == 'session.commentary.append' and sent[-1]['delegation_id'] == 'd2' and 'しゅんさんとみひろさん' in sent[-1]['content']


def test_a_long_call_still_fits_in_one_request_to_jev():
    running = [{'label': '作業', 'kind': 'job', 'id': str(i)} for i in range(4)]
    asked = voice_router.questions(running, {f'成果物{i}' * 3: f'「成果物{i}」' for i in range(120)})
    state = {'conversation': [{'role': '本人', 'text': 'あ' * 600}] * 9 + [{'role': '本人', 'text': '今の頼み'}], 'running_work': [], 'screen': ''}
    voice_router.fit(state, asked)
    assert len(json.dumps({'model': 'jev-latest', 'state': state, 'questions': asked}, ensure_ascii=False).encode()) <= 24000
    assert state['conversation'][-1]['text'] == '今の頼み' and 'route' in asked
