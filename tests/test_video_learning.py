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
                                                             'basis': 'inferred', 'evidence_ids': ['h3']}]})
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
              'repository': str(repo), 'skill_paths': [V.LOG, V.SKILL + 'references/nakamura-line-gift.md']}
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


def _run(monkeypatch, path, room='room-1', last=''):
    monkeypatch.setenv('DAN_ROOM_ID', room)
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
    lesson = {'rule': 'r', 'why': 'w', 'layer': 'skill', 'layer_reason': '2案件', 'basis': 'inferred', 'evidence_ids': ['h3']}
    same_case = {'held_out': True, 'winner': 'candidate', 'reason': 'r', 'request_path': str(files['req']),
                 'old_output_path': str(files['old']), 'new_output_path': str(files['new'])}
    report = {'outcome': 'promoted', 'feedback_ids': ['h3'], 'reason': 'x', 'commit': 'abc1234', 'repository': str(tmp_path),
              'skill_paths': [V.SKILL + 'SKILL.md', V.LOG], 'lessons': [lesson], 'evaluations': [same_case]}
    with pytest.raises(ValueError, match='別の案件'):
        V.complete(job, report)
    with pytest.raises(ValueError, match='layer'):
        V.complete(job, {**report, 'lessons': [{**lesson, 'layer': 'everywhere'}]})
