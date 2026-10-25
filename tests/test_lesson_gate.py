"""The owner's corrections go through the lessons ledger before they are written to memory or rule documents (2026-10-25)."""
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
HOOK = SCRIPTS / 'hook_lesson_gate.py'
LESSONS = SCRIPTS / 'lessons.py'
sys.path.insert(0, str(SCRIPTS))

LEDGER = {
    'version': 2,
    'statements': [
        {'id': 'S001', 'date': '2026-10-23', 'where': 'チャット', 'saw': '見本', 'quote': '宣言も要らない', 'src': 'memory/feedback-chat-short-like-human.md', 'origin': 'owner', 'status': 'rule', 'tags': []},
        {'id': 'S002', 'date': '2026-10-16', 'where': 'Google ドキュメント', 'saw': '全文の貼り直し', 'quote': '俺の編集がお前の上書きで消えないように', 'src': 'memory/feedback-gdoc-partial-edit.md', 'origin': 'owner', 'status': 'rule', 'tags': []},
        {'id': 'S003', 'date': None, 'where': 'チャット', 'saw': 'パス', 'quote': '開ける形式で出せ', 'src': 'memory/feedback-windows-path-format.md', 'origin': 'owner', 'status': 'unsure', 'tags': [], 'question': '今も「\\」区切りで出しますか'},
        {'id': 'S004', 'date': '2026-10-16', 'where': '開発室', 'saw': '消し忘れ', 'quote': '（消し忘れ）', 'src': 'dev-lead/PATROL.md', 'origin': 'dan', 'status': 'rule', 'tags': []},
    ],
    'roots': [
        {'id': 'less-text', 'rule': '要らない文字を出さない。返事は短く、画面に案内文を出さない。', 'kind': 'machine',
         'check': {'state': '文章だけ', 'by': ['SOUL.md'], 'since': None}, 'next': '宣言文を数える点検を足す', 'statements': ['S001', 'S004']},
        {'id': 'dont-break-shared', 'rule': '本人の編集を上書きしない。動いているダンを止めない。', 'kind': 'machine',
         'check': {'state': '一部', 'by': ['hook_live_tree_guard.py'], 'since': '2026-10-17'}, 'next': '', 'statements': ['S002']},
    ],
    'subtract': [], 'not_owner': [], 'touches': [],
}


def env_for(tmp_path):
    ws = tmp_path / 'ws'
    (ws / 'lessons').mkdir(parents=True, exist_ok=True)
    (ws / 'memory').mkdir(exist_ok=True)
    ledger = ws / 'lessons' / 'ledger.json'
    if not ledger.exists():
        ledger.write_text(json.dumps(LEDGER, ensure_ascii=False), encoding='utf-8')
    return ws, dict(os.environ, DAN_WORKSPACE_DIR=str(ws), DAN_LESSONS_JUDGE='off')


def ledger_of(ws):
    return json.loads((ws / 'lessons' / 'ledger.json').read_text(encoding='utf-8'))


def lessons(env, *args):
    p = subprocess.run([sys.executable, str(LESSONS), *args], capture_output=True, env=env)
    return p.returncode, p.stdout.decode('utf-8'), p.stderr.decode('utf-8')


def add(env, root, quote, src, *extra):
    return lessons(env, 'add', '--root', root, '--quote', quote, '--saw', 's', '--where', 'w', '--src', src, *extra)


def result(text, tid='1'):
    return {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': tid, 'content': text}]}}


def gate(tmp_path, env, rows, tool_input, tool='Write'):
    t = tmp_path / 't.jsonl'
    t.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows), encoding='utf-8')
    payload = {'hook_event_name': 'PreToolUse', 'tool_name': tool, 'tool_input': tool_input, 'transcript_path': str(t)}
    p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload, ensure_ascii=False).encode(), capture_output=True, env=env)
    return p.returncode, p.stderr.decode('utf-8')


def sid_of(out):
    return out.split('[lessons] added id=')[1].split()[0]


def test_feedback_memory_blocks_without_ledger(tmp_path):
    ws, env = env_for(tmp_path)
    code, err = gate(tmp_path, env, [], {'file_path': str(ws / 'memory' / 'feedback-new.md'), 'content': '返事は短く'})
    assert code == 2 and 'lessons.py find' in err and '(lessons:S' in err


def test_find_add_and_write_with_the_id_passes(tmp_path):
    ws, env = env_for(tmp_path)
    _, found, _ = lessons(env, 'find', 'チャットの返事に「見張りを登録しました」と書かないで')
    assert 'less-text' in found and '[lessons] find' in found
    code, added, _ = add(env, 'less-text', '宣言いらない', str(ws / 'memory' / 'feedback-new.md'))
    sid = sid_of(added)
    assert code == 0 and 'src=memory/feedback-new.md' in added and f'(lessons:{sid})' in added and 'まだ点検がありません' in added
    rows = [result(found), result(added, '2')]
    path = str(ws / 'memory' / 'feedback-new.md')
    assert gate(tmp_path, env, rows, {'file_path': path, 'content': f'返事に宣言を書かない (lessons:{sid})'})[0] == 0
    assert gate(tmp_path, env, rows, {'file_path': path, 'content': '返事に宣言を書かない'})[0] == 2


def test_second_correction_in_the_same_file_needs_its_own_entry(tmp_path):
    ws, env = env_for(tmp_path)
    path = ws / 'memory' / 'feedback-new.md'
    _, found, _ = lessons(env, 'find', '返事を短く')
    _, added, _ = add(env, 'less-text', '返事を短く', str(path))
    sid = sid_of(added)
    path.write_text(f'返事を短く (lessons:{sid})\n', encoding='utf-8')
    rows = [result(found), result(added, '2')]
    code, err = gate(tmp_path, env, rows, {'file_path': str(path), 'old_string': f'返事を短く (lessons:{sid})',
                                           'new_string': f'返事を短く (lessons:{sid})\n購入には承認を求める'}, 'Edit')
    assert code == 2 and '印がありません' in err
    code, _ = gate(tmp_path, env, rows, {'file_path': str(path), 'old_string': 'x',
                                         'new_string': f'購入には承認を求める (lessons:{sid})'}, 'Edit')
    assert code == 2


def test_id_from_another_file_or_not_added_in_this_work_blocks(tmp_path):
    ws, env = env_for(tmp_path)
    _, found, _ = lessons(env, 'find', '上書き')
    code, err = gate(tmp_path, env, [result(found)], {'file_path': str(ws / 'memory' / 'feedback-gdoc-partial-edit.md'),
                                                      'new_string': 'また上書きした (lessons:S002)'}, 'Edit')
    assert code == 2 and 'この作業で台帳に書いていません' in err
    code, err = gate(tmp_path, env, [result(found)], {'file_path': str(ws / 'memory' / 'feedback-x.md'), 'content': 'x (lessons:S002)'})
    assert code == 2 and '出どころ' in err


def test_unsure_statement_is_not_made_a_rule(tmp_path):
    ws, env = env_for(tmp_path)
    _, found, _ = lessons(env, 'find', 'パスは「\\」区切りで開ける形式で出せ')
    assert '確かめたい' in found and 'S003' in found
    code, _, err = add(env, 'less-text', '開ける形式で出せ', 'memory/feedback-windows-path-format.md')
    assert code == 1 and '確かめたい' in err
    assert ledger_of(ws)['roots'][0]['statements'] == ['S001', 'S004']
    code, err = gate(tmp_path, env, [result(found)], {'file_path': str(ws / 'memory' / 'feedback-windows-path-format.md'),
                                                      'new_string': '開ける形式 (lessons:S003)'}, 'Edit')
    assert code == 2 and '確かめたい' in err
    code, out, _ = lessons(env, 'add', '--unsure', '一度きりの話か', '--quote', '有料の予告は書かない', '--saw', 's', '--where', 'w', '--src', 'memory/feedback-p.md')
    assert code == 0 and '[lessons] unsure' in out and '[lessons] added' not in out


def test_redo_after_compact_does_not_duplicate(tmp_path):
    ws, env = env_for(tmp_path)
    _, a1, _ = add(env, 'less-text', '宣言いらない', 'memory/feedback-new.md')
    _, a2, _ = add(env, 'less-text', '宣言いらない', 'memory/feedback-new.md')
    assert sid_of(a1) == sid_of(a2) and a2.rstrip().endswith('again')
    data = ledger_of(ws)
    assert sum(1 for s in data['statements'] if s['quote'] == '宣言いらない') == 1
    assert data['roots'][0]['statements'].count(sid_of(a1)) == 1
    _, found, _ = lessons(env, 'find', '宣言')
    rows = [result(found), result(a1, '2'), {'type': 'system', 'subtype': 'compact_boundary'}]
    path = str(ws / 'memory' / 'feedback-new.md')
    assert gate(tmp_path, env, rows, {'file_path': path, 'content': f'x (lessons:{sid_of(a1)})'})[0] == 2
    rows += [result(found, '3'), result(a2, '4')]
    assert gate(tmp_path, env, rows, {'file_path': path, 'content': f'x (lessons:{sid_of(a1)})'})[0] == 0


def test_two_adds_at_once_both_survive(tmp_path):
    ws, env = env_for(tmp_path)
    procs = [subprocess.Popen([sys.executable, str(LESSONS), 'add', '--root', 'less-text', '--quote', f'同時{i}', '--saw', 's',
                               '--where', 'w', '--src', f'memory/feedback-{i}.md'], env=env, stdout=subprocess.PIPE) for i in range(8)]
    outs = [p.communicate()[0].decode() for p in procs]
    assert all(p.returncode == 0 for p in procs)
    ids = [sid_of(o) for o in outs]
    data = ledger_of(ws)
    assert len(set(ids)) == 8 and len(data['statements']) == 4 + 8
    assert set(ids) <= set(data['roots'][0]['statements'])
    t = [subprocess.Popen([sys.executable, str(LESSONS), 'touch', '--src', f'memory/feedback-t{i}.md', '--why', 'w'], env=env) for i in range(4)]
    for p in t:
        p.wait()
    assert len(ledger_of(ws)['touches']) == 4
    assert not list((ws / 'lessons').glob('*.tmp'))


def test_recurrence_counts_only_after_the_check(tmp_path):
    ws, env = env_for(tmp_path)
    _, out, _ = add(env, 'dont-break-shared', '前の記録から', 'memory/feedback-old.md', '--date', '2026-10-01')
    assert '効いていません' not in out
    _, out, _ = add(env, 'dont-break-shared', 'また上書きした', 'memory/feedback-new.md', '--date', '2026-10-20')
    assert '効いていません' in out
    _, out, _ = add(env, 'less-text', '長い', 'memory/feedback-l.md')
    assert '効いていません' not in out
    import lessons as L
    os.environ['DAN_WORKSPACE_DIR'] = str(ws)
    data = ledger_of(ws)
    nw = L.not_working(data)
    assert [s['quote'] for _, s in nw] == ['また上書きした']
    assert not any(s.get('said_before') for s in data['statements'])


def test_touch_lets_exactly_one_plain_edit_through(tmp_path):
    ws, env = env_for(tmp_path)
    _, out, _ = lessons(env, 'touch', '--src', 'memory/feedback-gdoc-partial-edit.md', '--why', '関連の書き足し')
    inp = {'file_path': str(ws / 'memory' / 'feedback-gdoc-partial-edit.md'), 'old_string': 'a', 'new_string': '関連 [[x]]'}
    assert gate(tmp_path, env, [result(out)], inp, 'Edit')[0] == 0
    assert gate(tmp_path, env, [result(out)], inp, 'Edit')[0] == 2


def test_other_memory_deletions_and_plain_rule_edits_pass(tmp_path):
    ws, env = env_for(tmp_path)
    assert gate(tmp_path, env, [], {'file_path': str(ws / 'memory' / 'project-x.md'), 'content': 'type: project'})[0] == 0
    assert gate(tmp_path, env, [], {'file_path': str(ws / 'memory' / 'MEMORY.md'), 'content': 'x'})[0] == 0
    assert gate(tmp_path, env, [], {'file_path': str(ws / 'RULES.md'), 'new_string': '- 公開は確かめる'}, 'Edit')[0] == 0
    assert gate(tmp_path, env, [], {'file_path': str(ws / 'memory' / 'feedback-a.md'), 'old_string': '古い行', 'new_string': ''}, 'Edit')[0] == 0


def test_feedback_header_is_read_from_the_file_and_owner_words_in_rules_block(tmp_path):
    ws, env = env_for(tmp_path)
    f = ws / 'memory' / 'lesson-x.md'
    f.write_text('---\nname: x\nmetadata:\n  type: feedback\n---\n本文\n', encoding='utf-8')
    assert gate(tmp_path, env, [], {'file_path': str(f), 'old_string': '本文', 'new_string': '本文\n購入は承認'}, 'Edit')[0] == 2
    assert gate(tmp_path, env, [], {'file_path': str(ws / 'dev-lead' / 'PATROL.md'), 'new_string': '本人:「文字だけだと分かりにくい」'}, 'Edit')[0] == 2
    assert gate(tmp_path, env, [], {'file_path': '/Users/x/dan-workspace/CLAUDE.md', 'new_string': '（10-25 本人「聞かずに直せ」）'}, 'Edit')[0] == 2


def test_codex_patch_keeps_the_text(tmp_path):
    import codex_hook_bridge as B
    ws, env = env_for(tmp_path)
    rules = ws / 'RULES.md'
    rules.write_text('# 決まり\n- 公開は確かめる\n', encoding='utf-8')
    patch = (f'*** Begin Patch\n*** Update File: {rules}\n@@\n # 決まり\n - 公開は確かめる\n+- 公開前に確かめる（本人「公開前に確かめて」）\n'
             f'*** Add File: {ws}/memory/lesson-y.md\n+---\n+type: feedback\n+---\n+本文\n*** End Patch')
    shaped = B._synthesize({'hook_event_name': 'PreToolUse', 'tool_name': 'apply_patch', 'tool_input': {'command': patch}})
    assert [p['tool_name'] for p in shaped] == ['Edit', 'Write']
    assert '本人「公開前に確かめて」' in shaped[0]['tool_input']['new_string']
    assert 'type: feedback' in shaped[1]['tool_input']['content']
    for p in shaped:
        assert gate(tmp_path, env, [], p['tool_input'], p['tool_name'])[0] == 2


def test_table_and_weekly(tmp_path):
    ws, env = env_for(tmp_path)
    (ws / 'memory' / 'feedback-loose.md').write_text('x', encoding='utf-8')
    add(env, 'dont-break-shared', 'また', 'memory/feedback-e.md', '--date', '2026-10-24')
    code, _, _ = lessons(env, 'table')
    table = (ws / 'lessons' / 'TABLE.md').read_text(encoding='utf-8')
    assert code == 0 and 'みきさんの指摘 3 件' in table and 'ダン自身の観察 1 件' in table and '確かめたい物 1 件' in table
    assert '点検を入れた後にまた来た物は 1 件' in table and '今も「\\」区切り' in table
    code, out, _ = lessons(env, 'weekly', '--days', '400')
    assert code == 0 and '効いていない: dont-break-shared' in out and '台帳を通らずにある記憶: memory/feedback-loose.md' in out


def test_real_ledger_is_well_formed():
    real = Path.home() / '.dan' / 'workspace' / 'lessons' / 'ledger.json'
    if not real.exists():
        return
    data = json.loads(real.read_text(encoding='utf-8'))
    ids = [s['id'] for s in data['statements']]
    assert len(ids) == len(set(ids))
    st = {s['id']: s for s in data['statements']}
    linked = set()
    for r in data['roots']:
        assert r['kind'] in ('machine', 'skill', 'owner') and r['statements'] and r['rule']
        assert r['check']['state'] in ('守れている', '一部', '文章だけ', '無し')
        assert len(r['statements']) == len(set(r['statements']))
        for i in r['statements']:
            assert st[i]['status'] == 'rule', i
        linked |= set(r['statements'])
    for s in data['statements']:
        assert s['quote'] and s['src'] and s['where'] and s['saw'] and s['status'] in ('rule', 'unsure', 'spec')
        assert s.get('date') is None or date.fromisoformat(s['date'])
        assert s['status'] != 'rule' or s['id'] in linked, s['id']
    pairs = [(s['src'], s['quote']) for s in data['statements']]
    assert len(pairs) == len(set(pairs))
