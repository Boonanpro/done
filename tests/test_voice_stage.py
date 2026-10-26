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
async def test_show_page_photographs_a_page_and_names_it_in_the_record(room, monkeypatch):
    calls = []
    async def fake_capture(url, user_id, room_id):
        calls.append((url, user_id, room_id)); return '/api/v1/files/stage-x.png'
    monkeypatch.setattr(S, 'capture_page', fake_capture)
    monkeypatch.setattr(S, 'screens_base', lambda: 'https://dan.example')
    stage, _, log = make_stage(room, [])
    stage.user_id = 'u1'
    out = await stage.show_page(url='/artifacts/x-ops', note='X運用室の今の記事')
    assert out['shown'] and out['url'] == 'https://dan.example/artifacts/x-ops' and calls == [('https://dan.example/artifacts/x-ops', 'u1', room)]
    state = S.read_state(room)
    assert state['image'] == '/api/v1/files/stage-x.png' and state['page_url'] == 'https://dan.example/artifacts/x-ops' and state['caption'] == 'X運用室の今の記事'
    assert log[-1][0] == 'stage_page' and '[添付画像: /api/v1/files/stage-x.png]' in stage.summary() and 'https://dan.example/artifacts/x-ops' in stage.summary()


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
