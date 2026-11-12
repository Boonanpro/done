"""本人の動画への指摘の記録・学習の仕事・関所（app/services/video_learning.py, scripts/hook_video_feedback_gate.py）。"""
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.services import video_learning as V

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import hook_video_feedback_gate as G  # noqa: E402

ROOM = 'room-1'


def msg(i, who, text, at):
    return {'id': i, 'sender_type': who, 'content': text, 'created_at': f'2026-11-09T0{at}:00:00+00:00'}


MESSAGES = [
    msg('h1', 'human', '効果音を足して', 1),
    msg('a1', 'ai', 'v12です\n[添付動画: v12.mp4 (/api/v1/files/v12.mp4)]', 2),
    msg('h2', 'human', '動画が再生できない', 3),
    msg('a2', 'ai', '直しました', 4),
    msg('h3', 'human', '「中村さんのYouTube」はおかしい。視聴者からどう見えるか考えて', 5),
    msg('h4', 'human', '先の部分も共通の改善点があれば直して', 6),
]


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(V, 'ROOT', tmp_path)
    monkeypatch.setattr(V, 'LEDGER', tmp_path / 'ledger.json')
    return tmp_path


def test_only_owner_words_after_the_last_video_are_open(ledger):
    assert [m['id'] for m in V.pending(ROOM, MESSAGES)] == ['h2', 'h3', 'h4']
    assert V.pending(ROOM, MESSAGES[:1]) == []          # 動画をまだ渡していない部屋は何も求めない


def test_record_accounts_every_word_and_queues_one_job(ledger):
    started = []
    out = V.record(ROOM, ['h3', 'h4'], [], applied='札を全部「YouTube」に。3:10 と 9:42 も同じ型だったので直した',
                   video='v13', rest_other=True, messages=MESSAGES, start=lambda: started.append(1) or 'job')
    assert out['still_open'] == [] and out['other'] == 1 and out['job'] == 'job' and started == [1]
    assert V.pending(ROOM, MESSAGES) == []
    rec = V.load()['records'][0]
    assert [f['id'] for f in rec['feedback']] == ['h3', 'h4'] and '中村さんのYouTube' in rec['feedback'][0]['text']


def test_feedback_needs_where_it_was_applied(ledger):
    with pytest.raises(ValueError, match='applied'):
        V.record(ROOM, ['h3'], [], applied='', messages=MESSAGES, start=lambda: None)
    with pytest.raises(ValueError, match='本人の発言ではない'):
        V.record(ROOM, ['a2'], [], applied='どこにも当てはまらなかった。理由: …', messages=MESSAGES, start=lambda: None)


def test_other_talk_alone_starts_no_job(ledger):
    out = V.record(ROOM, [], ['h2', 'h3', 'h4'], messages=MESSAGES, start=lambda: pytest.fail('no job'))
    assert out['job'] is None


def test_one_job_at_a_time_and_three_a_day(ledger, monkeypatch):
    made = []
    monkeypatch.setattr(V, '_job_alive', lambda job: True)
    V.record(ROOM, ['h3'], [], applied='同じ型の札は他に無かった（全編を確認）', messages=MESSAGES, start=lambda: None)
    first = V.maybe_start(create=lambda j, r: made.append(j))
    assert first and made == [first]
    V.record(ROOM, ['h4'], [], applied='寄りの決まりを 5:02 と 11:40 にも当てはめた', messages=MESSAGES, start=lambda: None)
    assert V.maybe_start(create=lambda j, r: made.append(j)) is None          # 動いている間は起こさない
    monkeypatch.setattr(V, '_job_alive', lambda job: False)                  # 報告書を出さずに終わった
    second = V.maybe_start(create=lambda j, r: made.append(j))
    data = V.load()
    assert data['jobs'][first]['status'] == 'needs_attention'
    assert set(data['jobs'][second]['feedback']) == {'h3', 'h4'}             # 前の仕事の指摘も次へ回す
    assert V.maybe_start(today_max=2, create=lambda j, r: made.append(j)) is None


def _job(ledger):
    V.record(ROOM, ['h3'], [], applied='同じ型の札は他に無かった（全編を確認）', messages=MESSAGES, start=lambda: None)
    return V.maybe_start(create=lambda j, r: None)


def test_complete_rejects_prose_and_missing_evidence(ledger, monkeypatch):
    monkeypatch.setattr(V, '_job_alive', lambda job: False)
    job = _job(ledger)
    with pytest.raises(ValueError, match='feedback_ids'):
        V.complete(job, {'outcome': 'no_lesson', 'feedback_ids': [], 'reason': 'x'})
    with pytest.raises(ValueError, match='候補版が勝った'):
        V.complete(job, {'outcome': 'promoted', 'feedback_ids': ['h3'], 'reason': 'x', 'commit': 'abc1234',
                         'skill_paths': [V.LOG], 'lessons': [{'rule': 'r', 'why': 'w', 'layer': 'skill', 'layer_reason': 'x',
                                                             'basis': 'inferred', 'evidence_ids': ['h3'],
                                                             'elsewhere': '別の案件の札'}], 'scene_fixes': []})
    assert V.complete(job, {'outcome': 'deferred', 'feedback_ids': ['h3'], 'reason': '比べで差が出ない'})['status'] == 'deferred'


def test_complete_checks_the_skill_was_saved_and_delivered(ledger, monkeypatch, tmp_path):
    monkeypatch.setattr(V, '_job_alive', lambda job: False)
    job = _job(ledger)
    repo, live = tmp_path / 'repo', tmp_path / 'live'
    for d in (repo, live):
        (d / V.SKILL / 'references').mkdir(parents=True)
        (d / V.SKILL / 'sources').mkdir(parents=True)
    log = f'## 11/9 札の書き方\n- 種類: 指摘の学習（仕事 {job}）\n'
    ref = '- 出どころの札は「YouTube」だけ\n'
    for d in (repo, live):
        (d / V.LOG).write_text(log)
        (d / V.SKILL / 'references/nakamura-line-gift.md').write_text(ref)
    subprocess.run(['git', 'init', '-q'], cwd=repo, check=True)
    subprocess.run(['git', 'add', '.'], cwd=repo, check=True)
    subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'x'], cwd=repo, check=True)
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo, capture_output=True, text=True).stdout.strip()
    monkeypatch.setenv('DAN_LIVE_TREE', str(live))
    report = {'outcome': 'case_only', 'feedback_ids': ['h3'], 'reason': '案件の札だけ', 'commit': commit,
              'repository': str(repo), 'skill_paths': [V.LOG, V.SKILL + 'references/nakamura-line-gift.md'],
              'scene_fixes': []}
    with pytest.raises(ValueError, match='references'):
        V.complete(job, {**report, 'skill_paths': [V.LOG, V.SKILL + 'SKILL.md']})
    (live / V.LOG).write_text('古いまま')
    with pytest.raises(ValueError, match='本番'):
        V.complete(job, report)
    (live / V.LOG).write_text(log)
    assert V.complete(job, report)['status'] == 'case_only'


# --- 関所 ------------------------------------------------------------------------------------------------------------

def _transcript(tmp_path, lines):
    p = tmp_path / 't.jsonl'
    p.write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in lines))
    return str(p)


def _turn(text):
    return {'type': 'user', 'message': {'content': [{'type': 'text', 'text': text}]}}


def _tool(i, name, inp, out):
    return [{'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': i, 'name': name, 'input': inp}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': i, 'content': out}]}}]


def _run(monkeypatch, path, room='room-1', last='', lock_owner=None):
    monkeypatch.setenv('DAN_ROOM_ID', room)
    monkeypatch.delenv('DAN_SESSION_ID', raising=False)
    if lock_owner is None:
        monkeypatch.delenv('DAN_LOCK_OWNER', raising=False)
    else:
        monkeypatch.setenv('DAN_LOCK_OWNER', lock_owner)
    monkeypatch.setattr(sys, 'stdin', io.TextIOWrapper(io.BytesIO(json.dumps(
        {'hook_event_name': 'Stop', 'transcript_path': path, 'session_id': 's', 'last_assistant_message': last}).encode())))
    out = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', out)
    G.main()
    return out.getvalue()


@pytest.fixture
def gate(tmp_path, monkeypatch):
    monkeypatch.setattr(G, 'STORE', tmp_path / 'gate')
    monkeypatch.setattr(G, 'seconds', lambda url: 5.0 if 'clip' in url else 600.0)
    return tmp_path


SKILL_TEXT = (ROOT / '.claude/skills/talking-demo-editing/SKILL.md').read_text(encoding='utf-8')
VIDEO = '[添付動画: 中村さんLINE特典_全編v13.mp4 (/api/v1/files/v13.mp4)]'


def test_gate_stops_a_video_delivered_without_reading_the_skill(gate, monkeypatch):
    monkeypatch.setattr(G, 'open_feedback', lambda room: [])
    lines = [_turn('直して'), *_tool('1', 'mcp__dan-tools__attach_image', {'source': 'v13.mp4'}, VIDEO)]
    out = _run(monkeypatch, _transcript(gate, lines))
    assert '"block"' in out and 'talking-demo-editing' in out


def test_gate_passes_after_reading_and_recording(gate, monkeypatch):
    monkeypatch.setattr(G, 'open_feedback', lambda room: [])
    lines = [_turn('直して'), *_tool('0', 'Read', {'file_path': 'SKILL.md'}, SKILL_TEXT),
             *_tool('1', 'mcp__dan-tools__attach_image', {'source': 'v13.mp4'}, VIDEO)]
    assert _run(monkeypatch, _transcript(gate, lines)) == ''


def test_gate_asks_to_record_open_feedback(gate, monkeypatch):
    monkeypatch.setattr(G, 'open_feedback', lambda room: [{'id': 'h3', 'created_at': '2026-11-09T06:57', 'content': '視聴者からどう見えるか'}])
    lines = [_turn('直して'), *_tool('0', 'Read', {'file_path': 'SKILL.md'}, SKILL_TEXT)]
    out = _run(monkeypatch, _transcript(gate, lines), last='v13です\n' + VIDEO)
    assert '"block"' in out and 'h3' in out and 'record' in out
    # 同じ理由で止めるのは2回まで
    _run(monkeypatch, _transcript(gate, lines), last='v13です\n' + VIDEO)
    assert _run(monkeypatch, _transcript(gate, lines), last='v13です\n' + VIDEO) == ''


def test_gate_ignores_old_videos_seen_in_lookups_and_short_clips(gate, monkeypatch):
    monkeypatch.setattr(G, 'open_feedback', lambda room: pytest.fail('should not ask'))
    lines = [_turn('前の動画どこ？'), *_tool('0', 'mcp__dan-tools__lookup', {'source': 'messages'}, '過去: ' + VIDEO),
             *_tool('1', 'mcp__dan-tools__attach_image', {'source': 'clip.mp4'}, '[添付動画: 声 (/api/v1/files/clip.mp4)]')]
    assert _run(monkeypatch, _transcript(gate, lines)) == ''
    # 前のターンで渡した動画は、次のターンでは数えない
    lines = [_turn('直して'), *_tool('1', 'mcp__dan-tools__attach_image', {}, VIDEO), _turn('ありがとう')]
    assert _run(monkeypatch, _transcript(gate, lines)) == ''


def test_gate_reads_codex_rollouts(gate, monkeypatch):
    monkeypatch.setattr(G, 'open_feedback', lambda room: [])
    lines = [{'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': '直して'}]}},
             {'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': 'c1', 'name': 'mcp__dan_tools__attach_image', 'arguments': '{}'}},
             {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'c1', 'output': VIDEO}}]
    out = _run(monkeypatch, _transcript(gate, lines))
    assert '"block"' in out


def test_gate_without_room_passes(gate, monkeypatch):
    lines = [_turn('直して'), *_tool('1', 'mcp__dan-tools__attach_image', {}, VIDEO)]
    assert _run(monkeypatch, _transcript(gate, lines), room='') == ''


def test_changing_the_body_needs_a_comparison_on_another_case(ledger, monkeypatch, tmp_path):
    monkeypatch.setattr(V, '_job_alive', lambda job: False)
    job = _job(ledger)
    files = {k: tmp_path / f'{k}.md' for k in ('req', 'old', 'new')}
    for f in files.values():
        f.write_text('x')
    lesson = {'rule': 'r', 'why': 'w', 'layer': 'skill', 'layer_reason': '2案件', 'basis': 'inferred', 'evidence_ids': ['h3'],
              'elsewhere': '料理の動画の材料の札'}
    same_case = {'held_out': True, 'winner': 'candidate', 'reason': 'r', 'request_path': str(files['req']),
                 'old_output_path': str(files['old']), 'new_output_path': str(files['new'])}
    report = {'outcome': 'promoted', 'feedback_ids': ['h3'], 'reason': 'x', 'commit': 'abc1234', 'repository': str(tmp_path),
              'skill_paths': [V.SKILL + 'SKILL.md', V.LOG], 'lessons': [lesson], 'evaluations': [same_case],
              'scene_fixes': []}
    with pytest.raises(ValueError, match='別の案件'):
        V.complete(job, report)
    with pytest.raises(ValueError, match='layer'):
        V.complete(job, {**report, 'lessons': [{**lesson, 'layer': 'everywhere'}]})


def test_gate_keeps_the_turn_across_image_notes_and_task_notices(gate, monkeypatch):
    monkeypatch.setattr(G, 'open_feedback', lambda room: [])
    note = {'type': 'user', 'isMeta': True, 'turnCompanion': True,
            'message': {'content': [{'type': 'text', 'text': '[Image: original 2400x2700, displayed at 1817x2044.]'}]}}
    notice = {'type': 'user', 'origin': {'kind': 'task-notification'},
              'message': {'content': '<task-notification><status>stopped</status></task-notification>'}}
    lines = [_turn('直して'), *_tool('1', 'mcp__dan-tools__attach_image', {}, VIDEO), note, notice]
    assert '"block"' in _run(monkeypatch, _transcript(gate, lines))


# --- 2026-11-12: 部屋の見分け・作る前の指示・エディターの部屋の裏の仕分け ---------------------------------------------

def test_room_comes_from_the_lock_owner_of_a_resident_claude_session(monkeypatch):
    monkeypatch.delenv('DAN_ROOM_ID', raising=False)
    monkeypatch.delenv('DAN_SESSION_ID', raising=False)
    monkeypatch.setenv('DAN_LOCK_OWNER', 'room:abc-123')
    assert V.room_from_env() == 'abc-123'
    monkeypatch.setenv('DAN_ROOM_ID', 'xyz')
    assert V.room_from_env() == 'xyz'


def test_gate_in_a_resident_claude_room_asks_to_record(gate, monkeypatch):
    seen = []
    monkeypatch.setattr(G, 'open_feedback', lambda room: seen.append(room) or [{'id': 'h1', 'created_at': '', 'content': 'マーカー要らない'}])
    lines = [_turn('直して'), *_tool('0', 'Read', {'file_path': 'SKILL.md'}, SKILL_TEXT)]
    out = _run(monkeypatch, _transcript(gate, lines), room='', last='v15です\n' + VIDEO, lock_owner='room:dc33')
    assert '"block"' in out and 'h1' in out and seen == ['dc33']


PRE = [
    msg('h0', 'human', 'この参考動画のサムネと編集を参考にして [添付動画: ref.mp4 (/api/v1/files/ref.mp4)]', 1),
    msg('a0', 'ai', '見ました', 2),
    msg('h5', 'human', 'うん進めて', 3),
]


def test_first_video_also_sees_the_words_before_it(ledger):
    assert V.pending(ROOM, PRE) == []
    assert [m['id'] for m in V.pending(ROOM, PRE, before_first=True)] == ['h0', 'h5']


def test_direction_is_learned_without_applied(ledger):
    started = []
    out = V.record(ROOM, [], [], direction=['h0'], rest_other=True, messages=PRE, start=lambda: started.append(1) or 'job')
    assert out['job'] == 'job' and out['still_open'] == [] and out['other'] == 1
    rec = V.load()['records'][0]
    assert rec['feedback'][0]['kind'] == 'direction' and 'サムネ' in rec['feedback'][0]['text']


def test_no_jobs_flag_keeps_dry_runs_out_of_the_queue(ledger, monkeypatch):
    monkeypatch.setenv('DAN_VIDEO_LEARNING_NO_JOBS', '1')
    V.record(ROOM, [], [], direction=['h0'], messages=PRE, start=None)
    assert V.load()['jobs'] == {}


def test_sweep_classifies_and_records(ledger):
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return '仕分けました {"feedback": [], "direction": ["h0"], "other": ["h5"]}'
    out = V.sweep(ROOM, messages=PRE, ask=ask, start=lambda: 'job')
    assert out['job'] == 'job' and 'id=h0' in asked[0] and 'id=h5' in asked[0]
    assert V.pending(ROOM, PRE, before_first=True) == []
    assert V.load()['records'][0]['by'] == 'sweep'
    assert V.sweep(ROOM, messages=PRE, ask=lambda p: pytest.fail('nothing open')) == {'open': 0}


def test_sweep_puts_forgotten_ids_into_other_and_rejects_prose(ledger):
    out = V.sweep(ROOM, messages=PRE, ask=lambda p: '{"feedback": ["h0"]}', start=lambda: None)
    assert out['feedback'] == 1 and out['other'] == 1
    with pytest.raises(ValueError):
        V.classify(PRE[:1], [], ask=lambda p: 'わかりません')


def test_editor_rooms_are_remembered(ledger):
    V.remember_editor_room('ed-1')
    V.remember_editor_room('ed-1')
    assert V.editor_rooms() == ['ed-1']


def test_gate_starts_a_sweep_in_editor_rooms_without_blocking(gate, monkeypatch):
    started = []
    monkeypatch.setattr(G, 'start_sweep', lambda room: started.append(room))
    monkeypatch.setattr(G, 'is_editor_room', lambda room: room == 'ed-1')
    lines = [_turn('このテロップ要らない')]
    assert _run(monkeypatch, _transcript(gate, lines), room='ed-1') == '' and started == ['ed-1']
    assert _run(monkeypatch, _transcript(gate, lines), room='room-1') == '' and started == ['ed-1']


def test_scene_fixes_are_not_written_as_rules(ledger, monkeypatch, tmp_path):
    """2026-11-12: 「沖縄に着いた絵を4秒」「中性脂肪にマーカーを引かない」が中村さんの決まりとして書かれた件。"""
    monkeypatch.setattr(V, '_job_alive', lambda job: False)
    job = _job(ledger)
    repo, live = tmp_path / 'repo', tmp_path / 'live'
    for d in (repo, live):
        (d / V.SKILL / 'references').mkdir(parents=True)
        (d / V.SKILL / 'sources').mkdir(parents=True)
    log = f'## 11/12 絵の長さ\n- 種類: 指摘の学習（仕事 {job}）\n'

    def commit(ref):
        for d in (repo, live):
            (d / V.LOG).write_text(log)
            (d / V.SKILL / 'references/nakamura-line-gift.md').write_text(ref)
        if not (repo / '.git').exists():
            subprocess.run(['git', 'init', '-q'], cwd=repo, check=True)
        subprocess.run(['git', 'add', '.'], cwd=repo, check=True)
        subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'x'], cwd=repo, check=True)
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo, capture_output=True, text=True).stdout.strip()

    monkeypatch.setenv('DAN_LIVE_TREE', str(live))
    lesson = {'rule': '絵は4秒以上', 'why': '見えない', 'layer': 'case', 'layer_reason': '中村さんのテイスト',
              'basis': 'explicit', 'evidence_ids': ['h3']}
    fix = {'feedback_id': 'h3', 'fix': '沖縄に着いた絵を4秒見せた', 'why_not_rule': '裏の判断は本文の「読める長さ」にある'}
    sha = commit('- 沖縄に着いた絵は v14 で一瞬だったので4秒以上見せる\n')
    report = {'outcome': 'case_only', 'feedback_ids': ['h3'], 'reason': 'x', 'commit': sha, 'repository': str(repo),
              'skill_paths': [V.LOG, V.SKILL + 'references/nakamura-line-gift.md'], 'lessons': [lesson]}
    with pytest.raises(ValueError, match='elsewhere'):                 # 別の場面を挙げられない決まり
        V.complete(job, {**report, 'scene_fixes': [fix]})
    lesson['elsewhere'] = '次の動画の場所の話の絵'
    with pytest.raises(ValueError, match='scene_fixes'):                # 場面の直しを分けていない
        V.complete(job, report)
    with pytest.raises(ValueError, match='scene_fixes'):
        V.complete(job, {**report, 'scene_fixes': [{**fix, 'feedback_id': 'other'}]})
    with pytest.raises(ValueError, match='版の名前'):                     # 版を名指す行は場面の直し
        V.complete(job, {**report, 'scene_fixes': [fix]})
    sha = commit('- 場所の話では、その場所と分かる実物の写真を、読める長さで出す\n- 書き出しは build_full_v15.py の形\n')
    assert V.complete(job, {**report, 'commit': sha, 'scene_fixes': [fix]})['status'] == 'case_only'
