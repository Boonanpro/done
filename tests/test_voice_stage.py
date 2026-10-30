"""The call's stage (voice_stage): the listener decides at pauses in Dan's speech, the newest decision wins, only programs
the screen can draw travel, and the call leaves one chat message with the scenes it showed."""
import asyncio
import json

import pytest

from app.services import voice_stage as S
from app.services.voice_sideband import Dialogue

FLOW = 'root = Column([Heading("支払いの流れ"), Flow([{id: "a", label: "本人", icon: "person"}, {id: "b", label: "Stripe", icon: "card", tone: "now"}, {id: "c", label: "口座", icon: "bank"}])])'


@pytest.fixture
def room(tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'ROOT', tmp_path)
    monkeypatch.setattr(S, 'CLAUSE_S', .02)   # the tests' sentences have clauses; they wait on QUIET_S / SENTENCE_S as written
    S._stages.clear()
    return 'room-1'


def test_part_lines_come_from_the_screen_definitions_without_chat_only_parts():
    names = S.part_names()
    assert {'Flow', 'Stat', 'Compare', 'Chart', 'Steps', 'Card', 'Heading'} <= names
    assert not names & {'Choice', 'Input', 'Button'}
    assert 'Flow(' in S.instructions() and 'Choice(' not in S.instructions()


def test_well_formed_accepts_what_the_screen_can_draw_and_refuses_the_rest():
    assert S.well_formed(FLOW)
    assert S.well_formed('root = Stat("合計", 1135, "円")')
    assert not S.well_formed('Stat("合計", 1135)')                       # no root
    assert not S.well_formed('root = Choice("どっち", ["a", "b"])')         # chat-only part
    assert not S.well_formed('root = Table([1, 2])')                      # unknown part
    assert not S.well_formed('root = Stat("合計", 1135')                   # unbalanced
    assert S.well_formed('root = Stat("合計)", 1135)')                   # a bracket inside a string is text
    assert not S.well_formed('x' * 7000)
    assert not S.well_formed('root = Stat("Done 側", 59, "表", tone: "good")')   # a named argument (deepseek, 2026-10-25)
    assert S.well_formed('root = Flow([{id: "a", label: "A", tone: "now"}, {id: "b", label: "B"}], [{from: "a", to: "b", label: "x: y"}])')


async def _answer(answers):
    return (answers.pop(0) if answers else {'action': 'keep', 'caption': ''}), {'input_tokens': 10, 'output_tokens': 5}


def make_stage(room, answers, record=None):
    seen = []
    async def ask(system, user):
        seen.append(user)
        data = answers.pop(0) if answers else {'action': 'keep', 'caption': ''}
        if asyncio.iscoroutinefunction(data): return await data()
        return data, {'input_tokens': 10, 'output_tokens': 5}
    log = []
    stage = S.Stage(room, 'sess-1', Dialogue(), record or (lambda phase, **f: log.append((phase, f))), ask=ask)
    return stage, seen, log


@pytest.mark.asyncio
async def test_a_pause_in_dans_speech_draws_and_the_file_is_what_the_screen_reads(room, monkeypatch):
    monkeypatch.setattr(S, 'QUIET_S', .02); monkeypatch.setattr(S, 'SENTENCE_S', .01)
    stage, seen, log = make_stage(room, [{'action': 'replace', 'caption': '支払いの流れ', 'program': FLOW}])
    assert S.read_state(room) == stage.state(True) and S.read_state(room)['active'] and S.read_state(room)['version'] == 0
    for delta in ('まず本人がカードで払うと、', 'Stripe を通って口座に入ります。'):
        stage.dialogue.add('assistant', delta); stage.heard('assistant', delta)
    await asyncio.sleep(.15)
    state = S.read_state(room)
    assert state['version'] == 1 and state['caption'] == '支払いの流れ' and state['program'] == FLOW and state['active']
    assert 'Dan: まず本人がカードで払うと、Stripe を通って口座に入ります。' in seen[0] and '今の画面の札: （まだ無い）' in seen[0]
    assert [p for p, _ in log] == ['stage_scene'] and log[0][1]['version'] == 1 and log[0][1]['input_tokens'] == 10
    assert stage.scenes[0]['program'] == FLOW


@pytest.mark.asyncio
async def test_backchannels_do_not_ask_the_model(room, monkeypatch):
    monkeypatch.setattr(S, 'QUIET_S', .02)
    stage, seen, _ = make_stage(room, [])
    stage.dialogue.add('assistant', 'はい。'); stage.heard('assistant', 'はい。')
    await asyncio.sleep(.1)
    assert seen == []


@pytest.mark.asyncio
async def test_caption_only_and_keep_leave_the_scene(room, monkeypatch):
    monkeypatch.setattr(S, 'QUIET_S', .02); monkeypatch.setattr(S, 'HOLD_S', 0)   # the hold after a replace has its own test
    stage, _, log = make_stage(room, [{'action': 'replace', 'caption': 'A', 'program': FLOW}, {'action': 'caption', 'caption': 'B'}, {'action': 'keep', 'caption': 'B'}])
    for text in ('一つ目の説明をここでします。', '二つ目の話題に少し動きました。', '同じ話を続けています、はい。'):
        stage.dialogue.add('assistant', text); stage.heard('assistant', text)
        await asyncio.sleep(.1)
    state = S.read_state(room)
    assert state['version'] == 2 and state['caption'] == 'B' and state['program'] == FLOW
    assert [p for p, _ in log] == ['stage_scene', 'stage_caption', 'stage_keep'] and len(stage.scenes) == 1


@pytest.mark.asyncio
async def test_the_newest_decision_wins_over_a_late_older_answer(room, monkeypatch):
    monkeypatch.setattr(S, 'QUIET_S', .02)
    gate = asyncio.Event()
    async def slow():
        await gate.wait()
        return {'action': 'replace', 'caption': 'old', 'program': 'root = Stat("古い", 1)'}, {}
    stage, _, log = make_stage(room, [slow, {'action': 'replace', 'caption': 'new', 'program': 'root = Stat("新しい", 2)'}])
    stage.dialogue.add('assistant', '最初の説明をしています、長めに。'); stage.heard('assistant', '最初の説明をしています、長めに。')
    await asyncio.sleep(.06)
    stage.dialogue.add('assistant', '次の説明に移りました、こちらも長めに。'); stage.heard('assistant', '次の説明に移りました、こちらも長めに。')
    await asyncio.sleep(.06)
    assert S.read_state(room)['caption'] == 'new'
    gate.set(); await asyncio.sleep(.03)
    assert S.read_state(room)['caption'] == 'new' and S.read_state(room)['version'] == 1
    assert ('stage_stale', {'action': 'replace', 'elapsed_ms': log[-1][1]['elapsed_ms']}) == log[-1]


@pytest.mark.asyncio
async def test_a_program_the_screen_cannot_draw_does_not_travel(room, monkeypatch):
    monkeypatch.setattr(S, 'QUIET_S', .02)
    stage, _, log = make_stage(room, [{'action': 'replace', 'caption': 'x', 'program': 'root = Choice("q", ["a", "b"])'}])
    stage.dialogue.add('assistant', '選んでもらう話をしています、長めに。'); stage.heard('assistant', '選んでもらう話をしています、長めに。')
    await asyncio.sleep(.1)
    assert S.read_state(room)['program'] == '' and S.read_state(room)['caption'] == 'x'   # the caption still moves
    assert log[0][0] == 'stage_rejected'


@pytest.mark.asyncio
async def test_the_owners_request_is_drawn_now(room):
    stage, seen, _ = make_stage(room, [{'action': 'replace', 'caption': '3つの案', 'program': 'root = Compare(["案", "値段"], [["A", "1万"], ["B", "2万"]])'}])
    stage.dialogue.add('user', 'それ図にして'); stage.dialogue.add('assistant', 'はい。')
    out = await stage.show('今の3つの案を比べて')
    assert out == {'shown': True, 'caption': '3つの案', 'reason': None}
    assert '本人からの明示の頼み（必ず replace で描く）: 今の3つの案を比べて' in seen[0]
    assert S.for_room(room) is stage


@pytest.mark.asyncio
async def test_a_model_failure_leaves_the_stage_as_it_was(room, monkeypatch):
    async def boom(): raise RuntimeError('down')
    stage, _, log = make_stage(room, [boom])
    stage.dialogue.add('assistant', 'x')
    assert await stage.decide(request='図にして') is None
    assert log[0][0] == 'stage_failed' and log[0][1]['error_type'] == 'RuntimeError'
    assert S.read_state(room)['version'] == 0


def test_close_marks_the_file_inactive_and_the_summary_is_one_message_with_the_scenes(room):
    stage, _, _ = make_stage(room, [])
    stage._apply('支払いの流れ', FLOW)
    stage._apply('3つの案', 'root = Stat("合計", 3, "案")')
    stage.close()
    assert S.read_state(room)['active'] is False and S.for_room(room) is None
    text = stage.summary()
    assert text.startswith('🖼 通話中に出した画面（2枚）') and text.count('```openui-lang') == 2 and FLOW in text and '支払いの流れ' in text
    assert S.Stage(room, 's', Dialogue(), lambda *a, **k: None, ask=None).summary() == ''


def test_stray_icons_become_known_ones_or_go(monkeypatch):
    # the screen refuses a whole scene for one unknown icon (2026-10-25: "ticket"/"gate" left the stage blank)
    assert 'icon: "doc"' in S.sanitize('root = Flow([{id: "a", label: "きっぷ", icon: "ticket", sub: "s"}])')
    assert 'icon: "check"' in S.sanitize('root = Flow([{id: "a", label: "改札", icon: "gate"}])')
    assert S.sanitize('root = Flow([{id: "a", label: "x", icon: "zzz", sub: "s"}, {id: "b", icon: "qqq"}])') == 'root = Flow([{id: "a", label: "x", sub: "s"}, {id: "b"}])'
    assert S.sanitize('root = Flow([{id: "a", icon: "train"}])') == 'root = Flow([{id: "a", icon: "train"}])'   # known: untouched
    assert S.well_formed(S.sanitize('root = Flow([{id: "a", label: "x", icon: "zzz"}])'))


@pytest.mark.asyncio
async def test_after_a_replace_dans_next_words_wait_for_the_hold(room, monkeypatch):
    monkeypatch.setattr(S, 'QUIET_S', .02); monkeypatch.setattr(S, 'SENTENCE_S', .01); monkeypatch.setattr(S, 'HOLD_S', .3)
    second = FLOW.replace('"a"', '"z"')
    stage, seen, log = make_stage(room, [{'action': 'replace', 'caption': '一', 'program': FLOW},
                                         {'action': 'replace', 'caption': '二', 'program': second}])
    stage.dialogue.add('assistant', 'まず予約をして、駅へ向かいます。'); stage.heard('assistant', 'まず予約をして、駅へ向かいます。')
    await asyncio.sleep(.1)
    assert S.read_state(room)['version'] == 1
    for delta in ('次に改札を通ります。', 'そしてホームに並びます。'):
        stage.dialogue.add('assistant', delta); stage.heard('assistant', delta)
        await asyncio.sleep(.08)
    assert len(seen) == 1                      # inside the hold: no second decision yet, the sentences pile up
    await asyncio.sleep(.35)
    assert len(seen) == 2 and S.read_state(room)['version'] == 2 and 'そしてホームに並びます。' in seen[1]


def test_a_new_call_counts_its_versions_on_from_the_rooms_last_call(room):
    # the screen waits for a version above the last one it saw; a call restarting at 1 would never reach it (2026-10-25)
    first = S.Stage(room, 'sess-1', Dialogue(), lambda *a, **k: None, ask=None)
    for _ in range(7): first._apply('c', FLOW)
    first.close()
    second = S.Stage(room, 'sess-2', Dialogue(), lambda *a, **k: None, ask=None)
    second._apply('d', FLOW)
    state = S.read_state(room)
    assert state['version'] == 8 and state['session_id'] == 'sess-2' and state['active']


# -- 2026-10-27: the drawing must not lag the talk; the stage draws more than the chat's parts ---------------------------

@pytest.mark.asyncio
async def test_a_clause_end_decides_before_the_sentence_ends(room, monkeypatch):
    monkeypatch.setattr(S, 'QUIET_S', 5.0); monkeypatch.setattr(S, 'CLAUSE_S', .02)
    stage, seen, _ = make_stage(room, [{'action': 'keep', 'caption': '予約の流れ'}])
    stage.dialogue.add('assistant', 'まず日付と時間を決めて、予約サイトでのぞみの指定席を買って、'); stage.heard('assistant', 'まず日付と時間を決めて、予約サイトでのぞみの指定席を買って、')
    await asyncio.sleep(.1)
    assert len(seen) == 1   # decided at the 、 (QUIET_S would have waited 5 s)


@pytest.mark.asyncio
async def test_dans_first_words_do_not_push_back_the_owners_decision(room, monkeypatch):
    monkeypatch.setattr(S, 'USER_S', .05); monkeypatch.setattr(S, 'QUIET_S', 5.0)
    stage, seen, _ = make_stage(room, [{'action': 'keep', 'caption': '料金'}])
    stage.dialogue.add('user', '料金と所要時間は？'); stage.heard('user', '料金と所要時間は？')
    await asyncio.sleep(.02)
    stage.dialogue.add('assistant', '目安ですが'); stage.heard('assistant', '目安ですが')   # would reschedule QUIET_S before
    await asyncio.sleep(.1)
    assert len(seen) == 1 and 'ユーザー: 料金と所要時間は？' in seen[0]


def test_clean_html_keeps_the_drawing_and_removes_what_could_run():
    svg = '<svg viewBox="0 0 640 360"><rect width="640" height="360" fill="#0a0a0a"/><text x="20" y="40" fill="#fff">机</text></svg>'
    assert S.clean_html(svg) == svg
    assert S.clean_html('```html\n' + svg + '\n```') == svg
    out = S.clean_html(svg + '<script>alert(1)</script><iframe src="https://x"></iframe><a href="javascript:alert(1)" onclick="x()">a</a>')
    assert 'script' not in out and 'iframe' not in out and 'onclick' not in out and 'javascript:' not in out and '<text' in out
    assert S.clean_html('') is None and S.clean_html('no tags') is None and S.clean_html('<svg>' + 'x' * 13000 + '</svg>') is None


def test_safe_image_takes_dans_files_and_https_only():
    assert S.safe_image('/api/v1/files/stage-abc-1.png') == '/api/v1/files/stage-abc-1.png'
    assert S.safe_image('https://example.com/a/b.png') == 'https://example.com/a/b.png'
    assert S.safe_image('javascript:alert(1)') is None and S.safe_image('/api/v1/files/../x') is None and S.safe_image('http://x/y') is None


@pytest.mark.asyncio
async def test_a_free_drawing_and_an_image_are_scenes_too(room, monkeypatch):
    monkeypatch.setattr(S, 'FLIP_HOLD_S', 0)
    svg = '<svg viewBox="0 0 640 360"><text x="10" y="30" fill="#fff">配置</text></svg>'
    stage, _, log = make_stage(room, [{'action': 'replace', 'caption': '配置', 'html': svg + '<script>x</script>'},
                                      {'action': 'replace', 'caption': '写真', 'image': '/api/v1/files/p.png'},
                                      {'action': 'replace', 'caption': 'だめ', 'image': 'javascript:x'}])
    stage.dialogue.add('assistant', '窓際に机、入口側にソファです。')
    assert await stage.decide() == 'replace'
    state = S.read_state(room)
    assert state['html'] == svg and state['program'] == '' and state['image'] == '' and log[-1][1]['kind'] == 'html'
    assert await stage.decide() == 'replace'
    state = S.read_state(room)
    assert state['image'] == '/api/v1/files/p.png' and state['html'] == '' and log[-1][1]['kind'] == 'image'
    assert await stage.decide() == 'rejected' and S.read_state(room)['image'] == '/api/v1/files/p.png'
    text = stage.summary()
    assert '```html' in text and svg in text and '[添付画像: /api/v1/files/p.png]' in text


@pytest.mark.asyncio
async def test_show_page_opens_this_sites_page_live_and_photographs_a_page_elsewhere(room, monkeypatch):
    calls = []
    from app.services import voice_tools
    class FakeHost:
        async def ask(self, op, **kw):
            calls.append(kw['arguments'])
            return {'stage_image':'/api/v1/files/stage-x.png','text':'画面'} if kw.get('with_media') else '開きました'
    monkeypatch.setattr(voice_tools,'host',lambda *_:FakeHost())
    monkeypatch.setattr(S, 'screens_base', lambda: 'https://dan.example')
    stage, _, log = make_stage(room, [])
    stage.user_id = 'u1'
    out = await stage.show_page(url='/artifacts/x-ops', note='X運用室の今の記事')
    assert out['shown'] and out['url'] == '/preview/x-ops' and calls == []   # the page itself, not its photograph
    state = S.read_state(room)
    assert state['frame'] == '/preview/x-ops' and state['image'] == '' and state['caption'] == 'X運用室の今の記事'
    assert log[-1][0] == 'stage_page' and log[-1][1]['live'] and '🖥 /preview/x-ops' in stage.summary()
    out = await stage.show_page(url='https://example.com/a', note='よその記事')
    assert out['shown'] and calls == [{'action':'open_target','url':'https://example.com/a','observation':'dom'},{'action':'screenshot'}]
    state = S.read_state(room)
    assert state['frame'] == '' and state['image'] == '/api/v1/files/stage-x.png' and stage._external_source == 'browser'
    assert '[添付画像: /api/v1/files/stage-x.png]' in stage.summary()


def test_frame_path_takes_only_this_sites_screens(monkeypatch):
    monkeypatch.setattr(S, 'screens_base', lambda: 'http://127.0.0.1:3000')
    assert S.frame_path('http://127.0.0.1:3000/artifacts/x-operation') == '/preview/x-operation'
    assert S.frame_path('https://dan.paina.info/preview/script-room?script=1') == '/preview/script-room?script=1'
    assert S.frame_path('/preview/x-operation?article=a') == '/preview/x-operation?article=a'
    assert S.frame_path('https://example.com/preview/x') == '' and S.frame_path('/api/v1/files/a.png') == '' and S.frame_path('/preview/../api') == ''


@pytest.mark.asyncio
async def test_resolve_page_finds_the_owners_artifact_by_words(monkeypatch):
    async def rows(user_id):
        return [{'label': 'X運用室', 'slug': 'x-operation-room', 'preview_url': '/artifacts/x-operation-room'},
                {'label': '台本室', 'slug': 'script-room', 'preview_url': '/artifacts/script-room'}]
    monkeypatch.setattr(S, 'artifact_rows', rows)
    monkeypatch.setattr(S, 'screens_base', lambda: 'https://dan.example')
    assert await S.resolve_page('u1', artifact='X運用室を出して') == ('https://dan.example/artifacts/x-operation-room', 'X運用室')
    assert await S.resolve_page('u1', artifact='台本') == ('https://dan.example/artifacts/script-room', '台本室')
    assert await S.resolve_page('u1', url='https://example.com/a') == ('https://example.com/a', '')
    assert await S.resolve_page('u1', artifact='全然違う物') == (None, '')


@pytest.mark.asyncio
async def test_a_flip_right_after_a_scene_only_moves_the_caption_but_growth_passes(room, monkeypatch):
    monkeypatch.setattr(S, 'FLIP_HOLD_S', 5.0)
    grown = FLOW.replace('{id: "c", label: "口座", icon: "bank"}', '{id: "c", label: "口座", icon: "bank"}, {id: "d", label: "明細", icon: "doc"}')
    stage, _, log = make_stage(room, [{'action': 'replace', 'caption': '支払いの流れ', 'program': FLOW},
                                      {'action': 'replace', 'caption': '手数料', 'program': 'root = Stat("手数料", 360, "円")'},
                                      {'action': 'replace', 'caption': '支払いの流れ（4段階）', 'program': grown}])
    stage.dialogue.add('assistant', 'まず本人がカードで払うと、Stripe を通って口座に入ります。')
    assert await stage.decide() == 'replace'
    assert await stage.decide() == 'held'                      # flow -> numbers 0 s later: the caption moves, the flow stays
    state = S.read_state(room)
    assert state['program'] == FLOW and state['caption'] == '手数料' and log[-1][0] == 'stage_flip_held'
    assert await stage.decide() == 'replace'                   # the same flow with one more box: growth, drawn at once
    assert S.read_state(room)['program'] == grown
    stage.dialogue.add('user', '手数料は？'); stage.heard('user', '手数料は？')
    stage.ask = (lambda answers: (lambda system, user: _answer(answers)))([{'action': 'caption', 'caption': '手数料の話'},
                                                                         {'action': 'replace', 'caption': '手数料', 'program': 'root = Stat("手数料", 360, "円")'}])
    assert await stage.decide() == 'caption'                   # the question itself: the caption moves first
    assert await stage.decide() == 'replace'                   # then Dan's answer: the owner asked, so it is a real change of topic, not a flip
    assert S.read_state(room)['program'] == 'root = Stat("手数料", 360, "円")'
    assert S.family('program', FLOW) == S.family('program', grown) == ('program', 'Flow')
    assert S.family('program', 'root = Stat("x", 1)') != S.family('program', FLOW) and S.family('html', '<svg/>') == ('html',)


@pytest.mark.asyncio
async def test_back_shows_an_earlier_scene_again_without_drawing(room, monkeypatch):
    monkeypatch.setattr(S, 'FLIP_HOLD_S', 0)
    stat = 'root = Stat("合計", 3, "案")'
    stage, seen, log = make_stage(room, [{'action': 'replace', 'caption': '流れ', 'program': FLOW},
                                         {'action': 'replace', 'caption': '合計', 'program': stat},
                                         {'action': 'back', 'caption': '流れに戻る', 'version': 1},
                                         {'action': 'back', 'version': 99}])
    stage.dialogue.add('assistant', 'x')
    await stage.decide(); await stage.decide()
    assert 'これまで出した図（version: 札）: 1: 流れ' in seen[1]
    assert await stage.decide() == 'replace'
    state = S.read_state(room)
    assert state['program'] == FLOW and state['caption'] == '流れに戻る' and state['version'] == 3 and log[-1][0] == 'stage_back'
    assert await stage.decide() == 'keep'                      # an unknown version: nothing changes
    assert '新しく届いた言葉（前回の判断の後）' not in seen[0]  # nothing had arrived through heard()


# -- a message on the stage: drafted, revised and sent by voice (2026-10-27) ------------------------------------------

class FakeMessages:
    """The outbound message service as the stage uses it: one draft, revised, sent or discarded."""
    def __init__(self):
        self.rows, self.sent, self.released = {}, [], []

    def create_draft(self, **kw):
        row = {'id': 'p1', 'status': 'pending', 'content': kw['body'], 'source_room_id': kw['room_id'],
               'action_data': {'channel': kw['channel'], 'to': kw['to'], 'to_name': kw.get('to_name'), 'subject': kw.get('subject'), 'intent': kw.get('intent'), 'revision': 1}}
        self.rows['p1'] = row
        return row

    def revise_draft(self, pid, user_id, body=None, subject=None, to=None, to_name=None, intent=None):
        row = self.rows[pid]
        if body: row['content'] = body
        if subject is not None: row['action_data']['subject'] = subject
        row['action_data']['revision'] += 1
        return row

    async def send(self, pid, user_id, sent_by):
        row = self.rows[pid]
        if row['action_data']['channel'] == 'line':
            row['status'] = 'sending'; return row
        row['status'] = 'sent'; row['action_data']['sent_at'] = '2026-10-27T03:00:00+00:00'; self.sent.append((pid, sent_by))
        return row

    def release(self, pid, user_id):
        self.rows[pid]['status'] = 'pending'; self.released.append(pid); return self.rows[pid]

    def discard(self, pid, user_id, by):
        self.rows[pid]['status'] = 'rejected'; return self.rows[pid]


def make_message_stage(room, monkeypatch, answers=None):
    fake = FakeMessages()
    monkeypatch.setattr(S, '_message_service', lambda: fake)
    stage, seen, log = make_stage(room, answers or [])
    stage.user_id = 'owner-1'
    return stage, fake, log


def owner_says(stage, text): stage.dialogue.add('user', text)
def dan_says(stage, text): stage.dialogue.add('assistant', text)


@pytest.mark.asyncio
async def test_a_draft_is_a_scene_the_screen_reads_and_a_revision_changes_it_in_place(room, monkeypatch):
    stage, fake, log = make_message_stage(room, monkeypatch)
    out = await stage.draft_message('email', 'dan-test@example.com', '田中様\n明日の打ち合わせは15時に変更でお願いします。\n本田', subject='打ち合わせの時間', to_name='田中様', intent='打ち合わせの日程変更')
    assert out['shown'] and out['proposal_id'] == 'p1' and out['sendable_now']
    state = S.read_state(room)
    assert state['version'] == 1 and state['card']['proposal_id'] == 'p1' and state['card']['status'] == 'pending' and state['card']['to_name'] == '田中様'
    assert state['caption'] == '打ち合わせの日程変更' and state['program'] == '' and len(stage.scenes) == 1
    out = await stage.revise_message('p1', body='田中様\n明日の打ち合わせは15時でお願いします。\n本田')
    assert out['revised'] and '15時で' in out['body']
    state = S.read_state(room)
    assert state['version'] == 2 and state['card']['revision'] == 2 and '15時で' in state['card']['body'] and len(stage.scenes) == 1
    assert [p for p, _ in log] == ['stage_draft', 'stage_revise']
    assert '✉ メール 宛先: 田中様（下書き）' in stage.summary() and '件名: 打ち合わせの時間' in stage.summary()


@pytest.mark.asyncio
async def test_while_a_draft_is_pending_the_listener_does_not_draw_over_it(room, monkeypatch):
    monkeypatch.setattr(S, 'QUIET_S', .02); monkeypatch.setattr(S, 'SENTENCE_S', .01); monkeypatch.setattr(S, 'HOLD_S', 0)
    stage, fake, log = make_message_stage(room, monkeypatch, [{'action': 'replace', 'caption': '支払いの流れ', 'program': FLOW}])
    await stage.draft_message('email', 'dan-test@example.com', 'こんにちは。', subject='件', to_name='田中様')
    for delta in ('まず本人がカードで払うと、', 'Stripe を通って口座に入ります。'):
        stage.dialogue.add('assistant', delta); stage.heard('assistant', delta)
    await asyncio.sleep(.15)
    state = S.read_state(room)
    assert state['card']['proposal_id'] == 'p1' and state['program'] == '' and state['version'] == 1
    assert ('stage_keep', ) == tuple(p for p, f in log if f.get('held_for') == 'card')[:1]


@pytest.mark.asyncio
async def test_sending_needs_dans_read_back_and_then_the_owners_approval_in_the_transcript(room, monkeypatch):
    stage, fake, log = make_message_stage(room, monkeypatch)
    owner_says(stage, 'いいよ、田中さんにメール送って')   # words before the draft never count as an approval of it
    await stage.draft_message('email', 'dan-test@example.com', '田中様\n明日は15時でお願いします。', subject='時間', to_name='田中様')
    out = await stage.send_message('p1')
    assert not out['sent'] and '読み上げ' in out['reason'] and '田中様さん宛てのメール' in out['read_back'] and fake.sent == []
    dan_says(stage, '田中様さん宛てのメール。件名は「時間」。本文は「明日は15時でお願いします。」。これで送っていいですか。')
    out = await stage.send_message('p1')
    assert not out['sent'] and '返事' in out['reason'] and fake.sent == []
    owner_says(stage, 'うーん、ちょっと待って')
    out = await stage.send_message('p1')
    assert not out['sent'] and 'ちょっと待って' in out['reason'] and fake.sent == []
    owner_says(stage, 'やっぱりいいよ、送って')
    out = await stage.send_message('p1')
    assert not out['sent'] and fake.sent == []   # 「やっぱり」 leans to hesitation: a clear word is asked for
    owner_says(stage, 'いいよ、送って')
    out = await stage.send_message('p1')
    assert out['sent'] and fake.sent == [('p1', 'dan')]
    state = S.read_state(room)
    assert state['card']['status'] == 'sent' and state['version'] == 2
    assert [p for p, _ in log] == ['stage_draft', 'stage_send_refused', 'stage_send_refused', 'stage_send_refused', 'stage_send_refused', 'stage_sent']
    out = await stage.send_message('p1')
    assert not out['sent'] and 'もう送った' in out['reason']
    assert '（送信済み）' in stage.summary()


@pytest.mark.asyncio
async def test_a_revision_asks_for_the_read_back_again(room, monkeypatch):
    stage, fake, log = make_message_stage(room, monkeypatch)
    await stage.draft_message('email', 'dan-test@example.com', '明日は15時で。', subject='時間', to_name='田中様')
    dan_says(stage, '田中様さん宛てのメールです。送っていいですか。'); owner_says(stage, 'もっと短くして')
    await stage.revise_message('p1', body='明日15時で。')
    owner_says(stage, 'いいよ')   # an approval of what? the revised text was not read back
    out = await stage.send_message('p1')
    assert not out['sent'] and '読み上げ' in out['reason']
    dan_says(stage, '田中様さん宛て、明日15時で、の一文です。送っていいですか。'); owner_says(stage, 'はい')
    assert (await stage.send_message('p1'))['sent']


@pytest.mark.asyncio
async def test_a_channel_dan_sends_by_hand_is_not_sent_from_the_call(room, monkeypatch):
    stage, fake, log = make_message_stage(room, monkeypatch)
    out = await stage.draft_message('line', '田中', 'こんにちは', to_name='田中さん')
    assert out['shown'] and not out['sendable_now']
    dan_says(stage, '田中さん宛ての LINE です。送っていいですか。'); owner_says(stage, 'いいよ')
    out = await stage.send_message('p1')
    assert not out['sent'] and 'LINE' in out['reason'] and fake.sent == [] and fake.released == []
    out = await stage.discard_message('p1')
    assert out['discarded'] and S.read_state(room)['card']['status'] == 'rejected'


def test_approval_and_hesitation_words():
    card = {'to_name': '田中様', 'to': 'tanaka@example.com'}
    hist = [{'role': 'user', 'text': 'メール送って'}, {'role': 'assistant', 'text': '田中様さん宛てのメール。送っていいですか。'}, {'role': 'user', 'text': 'いいよ'}]
    assert S.approval_heard(hist, (1, len('メール送って')), card)[0]
    assert not S.approval_heard(hist, (3, 3), card)[0]          # nothing after the mark
    for words in ('まだ', 'やめて', '送らないで', 'もう一回読んで', '送っていい？', 'どうしようかな'):
        assert not S.approval_heard(hist[:2] + [{'role': 'user', 'text': words}], (0, 0), card)[0], words
    for words in ('OK', 'お願い', 'それで送って', 'はい', 'うん'):
        assert S.approval_heard(hist[:2] + [{'role': 'user', 'text': words}], (0, 0), card)[0], words
    assert S.words_since(hist, (1, 3)) == [{'role': 'user', 'text': '送って'}, hist[1], hist[2]]


@pytest.mark.asyncio
async def test_the_voice_functions_reach_the_stage(room, monkeypatch):
    from app.services import voice_responses as R
    stage, fake, log = make_message_stage(room, monkeypatch)
    out = await R.run_function('draft_message_on_stage', {'channel': 'email', 'to': 'dan-test@example.com', 'body': 'こんにちは', 'subject': '件', 'to_name': '田中様'}, 'owner-1', room, [])
    assert out['shown'] and out['proposal_id'] == 'p1'
    out = await R.run_function('send_message_on_stage', {}, 'owner-1', room, [])
    assert not out['sent'] and out['read_back']
    assert {t['name'] for t in R.TOOLS} >= {'draft_message_on_stage', 'revise_message_on_stage', 'send_message_on_stage', 'discard_message_on_stage'}
    stage.close()
    out = await R.run_function('send_message_on_stage', {}, 'owner-1', room, [])
    assert not out['sent'] and '画面' in out['reason']


@pytest.mark.asyncio
async def test_with_the_calls_voice_the_delivery_runs_behind_and_the_result_is_spoken(room, monkeypatch):
    stage, fake, log = make_message_stage(room, monkeypatch)
    said = []
    async def speak(text): said.append(text)
    await stage.draft_message('email', 'dan-test@example.com', '明日は15時で。', subject='時間', to_name='田中様')
    dan_says(stage, '田中様さん宛てのメールです。送っていいですか。'); owner_says(stage, 'いいよ')
    out = await stage.send_message('p1', speak=speak)
    assert out['sent'] == 'sending' and fake.sent == []
    assert (await stage.send_message('p1', speak=speak))['sent'] == 'sending'   # not twice
    await asyncio.sleep(.05)
    assert fake.sent == [('p1', 'dan')] and said == ['送りました。'] and S.read_state(room)['card']['status'] == 'sent'


# -- the owner's words about the draft, heard by the server itself (2026-10-27: the speech model handed nothing over) ---

def make_flow_stage(room, monkeypatch, flow_answers):
    """A stage whose model answers the flow's question from `flow_answers` and keeps everything else."""
    fake = FakeMessages()
    monkeypatch.setattr(S, '_message_service', lambda: fake)
    monkeypatch.setattr(S, 'FLOW_S', .02); monkeypatch.setattr(S, 'USER_S', .5)   # the listener's own decision stays out of the way
    asked, said, log = [], [], []
    async def ask(system, user):
        if system == S.FLOW_INSTRUCTIONS:
            asked.append(user)
            return (flow_answers.pop(0) if flow_answers else {'intent': 'other'}), {'input_tokens': 10, 'output_tokens': 5}
        return {'action': 'keep', 'caption': ''}, {'input_tokens': 10, 'output_tokens': 5}
    async def speak(text): said.append(text)
    stage = S.Stage(room, 'sess-1', Dialogue(), lambda phase, **f: log.append((phase, f)), ask=ask, user_id='owner-1', speak=speak)
    return stage, fake, asked, said, log


def owner_heard(stage, text):
    stage.dialogue.add('user', text); stage.heard('user', text)


@pytest.mark.asyncio
async def test_the_server_revises_reads_back_and_sends_on_the_owners_words_alone(room, monkeypatch):
    stage, fake, asked, said, log = make_flow_stage(room, monkeypatch, [
        {'intent': 'revise', 'body': '明日15時で。'},
        {'intent': 'send'},
        {'intent': 'stop'},
        {'intent': 'approve'},
    ])
    await stage.draft_message('email', 'dan-test@example.com', '田中様\n明日は15時でお願いします。', subject='時間', to_name='田中様')
    owner_heard(stage, 'もっと短くして')
    await asyncio.sleep(.1)
    assert fake.rows['p1']['content'] == '明日15時で。' and S.read_state(room)['card']['revision'] == 2
    assert '本人の新しい言葉: もっと短くして' in asked[0] and '今の下書き:' in asked[0]
    owner_heard(stage, '送って')
    await asyncio.sleep(.1)
    assert said == ['田中様さん宛てのメール。件名は「時間」。本文は「明日15時で。」。これで送っていいですか。'] and fake.sent == []
    assert stage.dialogue.history[-1]['role'] == 'assistant' and '送っていいですか' in stage.dialogue.history[-1]['text']
    owner_heard(stage, 'うーん、ちょっと待って')
    await asyncio.sleep(.1)
    assert fake.sent == [] and len(said) == 1
    owner_heard(stage, 'いいよ')
    await asyncio.sleep(.15)
    assert fake.sent == [('p1', 'dan')] and said[-1] == '送りました。' and S.read_state(room)['card']['status'] == 'sent'
    flow = [f for p, f in log if p == 'stage_flow']
    assert [f['result'] for f in flow] == ['revised', 'read_back', 'held', 'send']


@pytest.mark.asyncio
async def test_an_approval_without_a_read_back_only_reads_back_and_dans_own_read_back_is_not_repeated(room, monkeypatch):
    stage, fake, asked, said, log = make_flow_stage(room, monkeypatch, [{'intent': 'approve'}, {'intent': 'send'}, {'intent': 'approve'}])
    await stage.draft_message('email', 'dan-test@example.com', '明日15時で。', subject='時間', to_name='田中様')
    owner_heard(stage, 'いいよ、送って')      # nothing was read back yet: the server reads back, does not send
    await asyncio.sleep(.1)
    assert fake.sent == [] and len(said) == 1 and '送っていいですか' in said[0]
    await stage.draft_message('email', 'dan-test@example.com', '明日15時で。宜しく。', subject='時間', to_name='田中様')   # a new draft: read back again
    owner_heard(stage, '送って')
    stage.dialogue.add('assistant', '田中様さん宛てのメールです。送っていいですか。')   # the speech model read it back itself meanwhile
    await asyncio.sleep(.1)
    assert len(said) == 1 and [f['result'] for p, f in log if p == 'stage_flow'][-1] == 'read_back_by_dan'
    owner_heard(stage, 'はい')
    await asyncio.sleep(.15)
    assert fake.sent == [('p1', 'dan')] and said[-1] == '送りました。'


@pytest.mark.asyncio
async def test_words_unrelated_to_the_draft_and_a_discard(room, monkeypatch):
    stage, fake, asked, said, log = make_flow_stage(room, monkeypatch, [{'intent': 'other'}, {'intent': 'discard'}])
    await stage.draft_message('email', 'dan-test@example.com', '明日15時で。', subject='時間', to_name='田中様')
    owner_heard(stage, 'ところで明日の天気は？')
    await asyncio.sleep(.1)
    assert fake.rows['p1']['status'] == 'pending' and said == []
    owner_heard(stage, 'やっぱり送らないで')
    await asyncio.sleep(.1)
    assert fake.rows['p1']['status'] == 'rejected' and S.read_state(room)['card']['status'] == 'rejected'
    owner_heard(stage, 'いいよ')   # no pending draft: nothing is asked
    await asyncio.sleep(.1)
    assert len(asked) == 2


def test_the_announcement_of_a_draft_is_not_a_read_back():
    card = {'to_name': '田中様', 'to': 'tanaka@example.com'}
    assert not S.mention_of(card, '田中様さん宛てに、打ち合わせの件の文面を出しました。')
    assert not S.mention_of(card, 'はい、今送信します。宛先 tanaka@example.com、件名「打ち合わせの時間」です。')
    assert S.mention_of(card, '宛先 tanaka@example.com、件名「時間」、本文は「明日15時で」。今から送っていい?')
    assert S.mention_of(card, S.spoken_summary(card | {'channel': 'email', 'body': '明日15時で。'}))
    hist = [{'role': 'assistant', 'text': '田中様さん宛てにメールの文面を出しました。'}, {'role': 'user', 'text': '送って'}]
    assert not S.approval_heard(hist, (0, 0), card)[0]


@pytest.mark.asyncio
async def test_the_server_reads_back_first_and_a_backend_call_meanwhile_does_not_repeat_it(room, monkeypatch):
    stage, fake, asked, said, log = make_flow_stage(room, monkeypatch, [{'intent': 'send'}])
    await stage.draft_message('email', 'dan-test@example.com', '明日15時で。', subject='時間', to_name='田中様')
    owner_heard(stage, '送って')
    await asyncio.sleep(.1)
    assert len(said) == 1 and '送っていいですか' in said[0]
    out = await stage.send_message('p1', speak=None)   # the backend's call for the same words: told it was read already
    assert not out['sent'] and out.get('read_back_done') and 'read_back' not in out
    monkeypatch.setattr(S, 'READ_BACK_FRESH_S', 0)
    out = await stage.send_message('p1', speak=None)   # later, the backend reads back itself
    assert not out['sent'] and '送っていいですか' in out['read_back']


# -- a document of a site and a picture on the stage: written, revised, published / redone by voice (2026-10-27) --------

class FakeDocs:
    """A site's STAGE_DOCUMENTS as the stage reaches it: one kind that publishes, one that does not."""
    def __init__(self):
        self.rows, self.published = {}, []
        self.spec = {'kinds': {'x_article': {'label': 'X の記事', 'publish': 'X に記事を投稿', 'accounts': ['OYmpa7']}},
                     'create': self.create, 'read': self.read, 'revise': self.revise, 'publish': self.publish}
        self.plain = {'kinds': {'script': {'label': '台本', 'publish': ''}}, 'create': self.create, 'read': self.read, 'revise': self.revise}

    def create(self, uid, kind, title, body, account, note):
        doc = {'id': 'd1', 'kind': kind, 'title': title, 'body': body, 'status': 'draft', 'revision': 1, 'account': account}
        self.rows['d1'] = doc
        return doc

    def read(self, uid, doc_id): return self.rows[doc_id]

    def revise(self, uid, doc_id, title, body):
        doc = self.rows[doc_id]
        if body: doc['body'] = body
        if title: doc['title'] = title
        doc['revision'] += 1
        return doc

    async def publish(self, uid, doc_id):   # async, like the X room's own send path
        doc = self.rows[doc_id]
        doc['status'], doc['url'] = 'published', 'https://x.com/OYmpa7/status/1'
        self.published.append(doc_id)
        return doc


def make_doc_stage(room, monkeypatch, answers=None):
    from app.services import voice_stage_docs as D
    fake = FakeDocs()
    monkeypatch.setattr(D, '_extra', {'x_article': fake.spec, 'script': fake.plain})
    stage, seen, log = make_stage(room, answers or [])
    stage.user_id = 'owner-1'
    return stage, fake, log


@pytest.mark.asyncio
async def test_a_document_is_a_scene_revised_in_place_and_published_only_on_the_owners_spoken_approval(room, monkeypatch):
    stage, fake, log = make_doc_stage(room, monkeypatch)
    out = await stage.draft_document('x_article', '声だけで仕事を終わらせる', '通話で頼む。\n画面に出る。\n声で直す。', account='OYmpa7')
    assert out['shown'] and out['doc_id'] == 'd1' and out['publishable_now']
    state = S.read_state(room)
    assert state['version'] == 1 and state['doc']['id'] == 'd1' and state['doc']['label'] == 'X の記事' and state['doc']['status'] == 'draft'
    assert state['caption'] == '声だけで仕事を終わらせる' and state['card'] is None and state['program'] == ''
    out = await stage.revise_document(body='通話で頼む。\n画面に出る。\n声で直して、投稿する。')
    assert out['revised'] and out['revision'] == 2
    state = S.read_state(room)
    assert state['version'] == 2 and state['doc']['revision'] == 2 and '投稿する' in state['doc']['body'] and len(stage.scenes) == 1
    out = await stage.publish_document()
    assert not out['published'] and '読み上げ' in out['reason'] and 'X に記事を投稿' in out['read_back'] and fake.published == []
    dan_says(stage, 'X に記事を投稿、@OYmpa7 で。題は「声だけで仕事を終わらせる」。これで投稿していいですか。')
    owner_says(stage, 'うーん、ちょっと待って')
    out = await stage.publish_document()
    assert not out['published'] and fake.published == []
    owner_says(stage, 'いいよ、投稿して')
    out = await stage.publish_document()
    assert out['published'] is True and fake.published == ['d1'] and out['url'].startswith('https://x.com/')
    state = S.read_state(room)
    assert state['doc']['status'] == 'published' and state['doc']['url'] and state['version'] == 3
    assert [p for p, _ in log] == ['stage_doc', 'stage_doc_revise', 'stage_publish_refused', 'stage_publish_refused', 'stage_published']
    assert '📝 X の記事 @OYmpa7（投稿済み）' in stage.summary() and '題: 声だけで仕事を終わらせる' in stage.summary()
    out = await stage.publish_document()
    assert not out['published'] and 'もう投稿した' in out['reason']


@pytest.mark.asyncio
async def test_a_kind_without_a_publish_path_is_written_and_revised_but_never_published(room, monkeypatch):
    stage, fake, log = make_doc_stage(room, monkeypatch)
    out = await stage.draft_document('script', 'LINE 特典動画', 'こんにちは。\n今日は3つ話します。')
    assert out['shown'] and not out['publishable_now']
    dan_says(stage, '台本を投稿していいですか。'); owner_says(stage, 'いいよ')
    out = await stage.publish_document()
    assert not out['published'] and '通話からは投稿できない' in out['reason'] and fake.published == []
    out = await stage.draft_document('unknown', 'x', 'y')
    assert not out['shown'] and '出せるのは' in out['reason']


@pytest.mark.asyncio
async def test_the_server_revises_reads_back_and_publishes_a_document_on_the_owners_words_alone(room, monkeypatch):
    monkeypatch.setattr(S, 'FLOW_S', .01)
    stage, fake, log = make_doc_stage(room, monkeypatch, [
        {'intent': 'revise', 'body': '通話で頼む。\n声で直す。'},
        {'intent': 'publish'},
        {'intent': 'approve'},
    ])
    said = []
    async def speak(text): said.append(text)
    stage.speak = speak
    await stage.draft_document('x_article', '題', '通話で頼む。\n画面に出る。\n声で直す。', account='OYmpa7')
    owner_says(stage, '2行目を消して'); stage.heard('user', '2行目を消して')
    await asyncio.sleep(.08)
    assert fake.rows['d1']['body'] == '通話で頼む。\n声で直す。' and S.read_state(room)['doc']['revision'] == 2
    owner_says(stage, '投稿して'); stage.heard('user', '投稿して')
    await asyncio.sleep(.08)
    assert fake.published == [] and said and '投稿していいですか' in said[-1] and stage.dialogue.history[-1]['role'] == 'assistant'
    owner_says(stage, 'いいよ'); stage.heard('user', 'いいよ')
    await asyncio.sleep(.08)
    assert fake.published == ['d1'] and said[-1] == '投稿しました。' and S.read_state(room)['doc']['status'] == 'published'
    flows = [f for p, f in log if p == 'stage_flow']
    assert [f['result'] for f in flows] == ['revised', 'read_back', 'publish']


@pytest.mark.asyncio
async def test_while_a_document_is_on_the_stage_the_listener_does_not_draw_over_it(room, monkeypatch):
    monkeypatch.setattr(S, 'QUIET_S', .02); monkeypatch.setattr(S, 'SENTENCE_S', .01); monkeypatch.setattr(S, 'HOLD_S', 0)
    stage, fake, log = make_doc_stage(room, monkeypatch, [{'action': 'replace', 'caption': '支払いの流れ', 'program': FLOW}])
    await stage.draft_document('x_article', '題', '本文。', account='OYmpa7')
    for delta in ('まず本人がカードで払うと、', 'Stripe を通って口座に入ります。'):
        stage.dialogue.add('assistant', delta); stage.heard('assistant', delta)
    await asyncio.sleep(.15)
    state = S.read_state(room)
    assert state['doc']['id'] == 'd1' and state['program'] == '' and state['version'] == 1
    assert [f.get('held_for') for p, f in log if p == 'stage_keep'] == ['doc']


class FakePictures:
    def __init__(self): self.calls, self.fail = [], False
    async def make(self, prompt, room_id, reference_url=None):
        self.calls.append((prompt, reference_url))
        if self.fail: raise RuntimeError('image API 402: credit')
        return f'/api/v1/files/stage-pic-{len(self.calls)}.png', 3.2, 0.011


def make_media_stage(room, monkeypatch, answers=None):
    from app.services import voice_stage_media as M
    fake = FakePictures()
    monkeypatch.setattr(M, 'make', fake.make)
    stage, seen, log = make_stage(room, answers or [])
    stage.user_id = 'owner-1'
    return stage, fake, log


@pytest.mark.asyncio
async def test_a_picture_shows_its_waiting_first_then_the_picture_and_a_revision_edits_it(room, monkeypatch):
    stage, fake, log = make_media_stage(room, monkeypatch)
    said = []
    async def speak(text): said.append(text)
    out = await stage.generate_image('夕暮れの尼崎の駅前', speak=speak)
    assert out['shown'] and out['media_id']
    state = S.read_state(room)
    assert state['media']['status'] == 'generating' and state['media']['image'] == '' and state['caption'] == '夕暮れの尼崎の駅前' and state['version'] == 1
    out = await stage.generate_image('別の絵')
    assert not out['shown'] and '作っている' in out['reason']
    await asyncio.sleep(.05)
    state = S.read_state(room)
    assert state['media']['status'] == 'done' and state['media']['image'] == '/api/v1/files/stage-pic-1.png' and state['version'] == 2 and said == ['できました。']
    assert fake.calls == [('夕暮れの尼崎の駅前', None)] and len(stage.scenes) == 1
    out = await stage.revise_image('もっと明るく', speak=speak)
    assert out['shown'] and out['revision'] == 2
    state = S.read_state(room)
    assert state['media']['status'] == 'generating' and state['media']['previous'] == '/api/v1/files/stage-pic-1.png' and state['media']['history'] == ['もっと明るく']
    await asyncio.sleep(.05)
    state = S.read_state(room)
    assert state['media']['status'] == 'done' and state['media']['image'] == '/api/v1/files/stage-pic-2.png' and state['media']['revision'] == 2 and said[-1] == '直しました。'
    assert fake.calls[-1] == ('もっと明るく', '/api/v1/files/stage-pic-1.png') and len(stage.scenes) == 1
    assert [p for p, _ in log] == ['stage_media_started', 'stage_media', 'stage_media_started', 'stage_media']
    assert '[添付画像: /api/v1/files/stage-pic-2.png]' in stage.summary() and '🎨 夕暮れの尼崎の駅前 → もっと明るく' in stage.summary()
    fake.fail = True
    await stage.revise_image('背景を青に', speak=speak)
    await asyncio.sleep(.05)
    state = S.read_state(room)
    assert state['media']['status'] == 'failed' and state['media']['image'] == '/api/v1/files/stage-pic-2.png' and said[-1] == '画像を作れませんでした。'


@pytest.mark.asyncio
async def test_the_server_redoes_the_picture_on_the_owners_words_alone(room, monkeypatch):
    monkeypatch.setattr(S, 'FLOW_S', .01)
    stage, fake, log = make_media_stage(room, monkeypatch, [{'intent': 'other'}, {'intent': 'revise', 'instruction': '空を夕焼けの色にする'}])
    await stage.generate_image('駅前の絵')
    owner_says(stage, 'お、いいね'); stage.heard('user', 'お、いいね')   # while it is being made: nothing yet
    await asyncio.sleep(.08)
    assert len(fake.calls) == 1
    owner_says(stage, '空を夕焼けにして'); stage.heard('user', '空を夕焼けにして')
    await asyncio.sleep(.1)
    assert fake.calls[-1] == ('空を夕焼けの色にする', '/api/v1/files/stage-pic-1.png') and S.read_state(room)['media']['revision'] == 2
    assert [f['result'] for p, f in log if p == 'stage_flow'] == ['none', 'revising']


@pytest.mark.asyncio
async def test_the_voice_functions_reach_the_documents_and_pictures(room, monkeypatch):
    from app.services import voice_responses as R
    stage, fake, log = make_doc_stage(room, monkeypatch)
    out = await R.run_function('draft_document_on_stage', {'kind': 'nope', 'body': 'x'}, 'owner-1', room, [])
    assert not out['shown'] and set(out['kinds']) == {'x_article', 'script'} and out['kinds']['x_article']['publishable'] and not out['kinds']['script']['publishable']
    out = await R.run_function('draft_document_on_stage', {'kind': 'x_article', 'title': '題', 'body': '本文', 'account': 'OYmpa7'}, 'owner-1', room, [])
    assert out['shown'] and out['doc_id'] == 'd1'
    out = await R.run_function('publish_document_on_stage', {}, 'owner-1', room, [])
    assert not out['published'] and out['read_back']
    out = await R.run_function('revise_document_on_stage', {'title': '新しい題'}, 'owner-1', room, [])
    assert out['revised'] and out['title'] == '新しい題'
    from app.services import voice_stage_media as M
    pics = FakePictures(); monkeypatch.setattr(M, 'make', pics.make)
    out = await R.run_function('generate_image_on_stage', {'prompt': '猫'}, 'owner-1', room, [])
    assert out['shown']
    assert {t['name'] for t in R.TOOLS} >= {'draft_document_on_stage', 'revise_document_on_stage', 'publish_document_on_stage', 'generate_image_on_stage', 'revise_image_on_stage'}
    stage.close()
    out = await R.run_function('generate_image_on_stage', {'prompt': '猫'}, 'owner-1', room, [])
    assert not out['shown'] and '画面' in out['reason']


def test_the_read_back_of_a_document_names_it_and_asks():
    doc = {'title': '声だけで仕事を終わらせる', 'body': 'x', 'label': 'X の記事', 'publish_label': 'X に記事を投稿', 'account': 'OYmpa7'}
    assert S.mention_of_doc(doc, 'X に記事を投稿、@OYmpa7 で。題は「声だけで仕事を終わらせる」。これで投稿していいですか。')
    assert S.mention_of_doc(doc, '記事を投稿していいですか')
    assert not S.mention_of_doc(doc, '記事の下書きを出しました')
    assert S.mention_of_doc(doc, 'これで投稿していいですか')   # the question with the document's word is enough (the document is on the screen)
    assert '投稿していいですか' in S.spoken_doc_summary(doc) and '@OYmpa7' in S.spoken_doc_summary(doc)


class FakeAssisted(FakeDocs):
    """A site with its own screen and editing assistant (the X room, the script room): the call hands it the owner's words;
    its suggestions are laid on its page, approved there."""
    def __init__(self):
        super().__init__()
        self.asked, self.states, self.pending = [], [], 0
        self.spec = dict(self.spec, page=lambda uid, doc_id: '/preview/x-operation?article=row-' + doc_id + '&assistant=open',
                         assist=self.assist, assist_state=self.assist_state)

    async def assist(self, uid, doc_id, instruction):
        self.asked.append(instruction)
        return {'request_id': f'r{len(self.asked)}', 'queued': False}

    def assist_state(self, uid, doc_id, request_id):
        if not request_id: return {'state': 'done', 'pending': self.pending}
        st = self.states.pop(0) if self.states else {'state': 'running'}
        if 'pending' in st: self.pending = st['pending']
        if st.get('body'): self.rows[doc_id]['body'] = st['body']
        return dict(st, pending=self.pending)


def make_assisted_stage(room, monkeypatch, answers=None):
    from app.services import voice_stage_docs as D
    fake = FakeAssisted()
    monkeypatch.setattr(D, '_extra', {'x_article': fake.spec})
    monkeypatch.setattr(S, 'ASSIST_POLL_S', .01)
    spoken = []
    async def speak(text): spoken.append(text)
    stage, seen, log = make_stage(room, answers or [])
    stage.user_id, stage.speak = 'owner-1', speak
    return stage, fake, log, spoken


async def settle(stage):
    for _ in range(200):
        if not stage._tasks: return
        await asyncio.sleep(.01)


@pytest.mark.asyncio
async def test_a_document_of_a_site_with_an_assistant_opens_its_own_screen_and_the_assistant_writes_it(room, monkeypatch):
    stage, fake, log, spoken = make_assisted_stage(room, monkeypatch)
    fake.states = [{'state': 'running'}, {'state': 'done', 'changes': True, 'pending': 0, 'laid': False}, {'state': 'done', 'changes': True, 'pending': 5, 'body': '書いた本文'}]
    out = await stage.draft_document('x_article', '声で書く', request='声だけで記事を書く話を、経営者向けに', account='OYmpa7')
    assert out['shown'] and out['writing'] and fake.asked == ['声だけで記事を書く話を、経営者向けに']
    assert fake.rows['d1']['body'] == ''   # the call wrote no text: the room's assistant does
    state = S.read_state(room)
    assert state['frame'] == state['doc']['page'] == '/preview/x-operation?article=row-d1&assistant=open'
    assert state['command']['action'] == 'open-assistant' and state['doc']['assist']['state'] == 'running'
    await settle(stage)
    assert spoken == ['書きました。よければ「反映して」と言ってください。']   # said once the page had laid the suggestions
    state = S.read_state(room)
    assert state['doc']['assist']['pending'] == 5 and state['doc']['body'] == '書いた本文' and len(stage.scenes) == 1


@pytest.mark.asyncio
async def test_a_revision_goes_to_the_sites_assistant_and_approval_presses_the_pages_own_button(room, monkeypatch):
    stage, fake, log, spoken = make_assisted_stage(room, monkeypatch)
    fake.states = [{'state': 'done', 'changes': True, 'pending': 0}]
    await stage.draft_document('x_article', '声で書く', request='記事を書いて')
    await settle(stage); spoken.clear()
    out = await stage.revise_document(body='自分で書き直した本文')
    assert not out['revised'] and 'instruction' in out['reason'] and fake.asked == ['記事を書いて']
    fake.states = [{'state': 'running'}, {'state': 'done', 'changes': True, 'pending': 2}]
    out = await stage.revise_document(instruction='2段落目を短く')
    assert out['revised'] == 'asked' and fake.asked[-1] == '2段落目を短く'
    await settle(stage)
    assert spoken == ['直しの案が出ました。よければ「反映して」と言ってください。']
    # publishing waits for the suggestions to be decided
    dan_says(stage, 'X に記事を投稿していいですか。'); owner_says(stage, 'いいよ')
    out = await stage.publish_document()
    assert not out['published'] and '反映していない直しの案が2件' in out['reason'] and fake.published == []
    async def press():
        await asyncio.sleep(.05); fake.pending = 0
    monkeypatch.setattr(S, 'DECIDE_WAIT_S', 3.0)
    asyncio.ensure_future(press())
    out = await stage.decide_suggestions(accept=True)
    assert out['decided'] and S.read_state(room)['command']['action'] == 'accept-all'
    assert S.read_state(room)['doc']['assist']['pending'] == 0   # the status line no longer shows the suggestions
    out = await stage.decide_suggestions(accept=True)
    assert not out['decided'] and '無い' in out['reason']


@pytest.mark.asyncio
async def test_the_server_hands_the_owners_words_to_the_assistant_and_approves_by_voice(room, monkeypatch):
    monkeypatch.setattr(S, 'FLOW_S', .01)
    stage, fake, log, spoken = make_assisted_stage(room, monkeypatch, [
        {'intent': 'revise', 'instruction': 'タイトルをもっと短くして'},
        {'intent': 'accept'},
    ])
    fake.states = [{'state': 'done', 'changes': False, 'message': '書く内容を教えてください。'}]
    await stage.draft_document('x_article', '声で書く', request='記事を書いて')
    await settle(stage)
    assert spoken == ['書く内容を教えてください。']   # the assistant's own answer, when it changed nothing
    spoken.clear()
    fake.states = [{'state': 'done', 'changes': True, 'pending': 1}]
    owner_says(stage, 'タイトルをもっと短くして')
    await stage.doc_flow(); await settle(stage)
    assert fake.asked[-1] == 'タイトルをもっと短くして' and spoken == ['直しの案が出ました。よければ「反映して」と言ってください。']
    async def press():
        await asyncio.sleep(.05); fake.pending = 0
    asyncio.ensure_future(press())
    owner_says(stage, 'それでいい、反映して')
    out = await stage.doc_flow()
    assert out['decided'] and spoken[-1] == '反映しました。'
