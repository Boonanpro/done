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

LEDGER = {
    'roots': [
        {'id': 'less-text', 'rule': '要らない文字を出さない。返事は短く、画面に案内文を出さない。', 'kind': 'machine',
         'check': {'state': '文章だけ', 'by': ['SOUL.md']}, 'next': '宣言文を数える点検を足す',
         'items': [{'id': 'I001', 'date': '2026-10-23', 'where': 'チャット', 'saw': '見本', 'quote': '宣言も要らない', 'src': 'memory/feedback-chat-short-like-human.md'}]},
        {'id': 'dont-break-shared', 'rule': '本人の編集を上書きしない。動いているダンを止めない。', 'kind': 'machine',
         'check': {'state': '一部', 'by': ['hook_live_tree_guard.py']}, 'next': '',
         'items': [{'id': 'I002', 'date': '2026-10-22', 'where': 'Google ドキュメント', 'saw': '全文の貼り直し', 'quote': '俺の編集がお前の上書きで消えないように', 'src': 'memory/feedback-gdoc-partial-edit.md'}]},
    ],
    'unsure': [], 'not_owner': [], 'subtract': [],
}


def env_for(tmp_path):
    ws = tmp_path / 'ws'
    (ws / 'lessons').mkdir(parents=True, exist_ok=True)
    (ws / 'memory').mkdir(exist_ok=True)
    ledger = ws / 'lessons' / 'ledger.json'
    if not ledger.exists():
        ledger.write_text(json.dumps(LEDGER, ensure_ascii=False), encoding='utf-8')
    return ws, dict(os.environ, DAN_WORKSPACE_DIR=str(ws), DAN_LESSONS_JUDGE='off')


def lessons(env, *args):
    p = subprocess.run([sys.executable, str(LESSONS), *args], capture_output=True, env=env)
    return p.returncode, p.stdout.decode('utf-8'), p.stderr.decode('utf-8')


def claude_tool(name, inp, tid):
    return {'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': tid, 'name': name, 'input': inp}]}}


def claude_result(tid, text):
    return {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': tid, 'content': text}]}}


def gate(tmp_path, env, rows, tool_input):
    t = tmp_path / 't.jsonl'
    t.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows), encoding='utf-8')
    payload = {'hook_event_name': 'PreToolUse', 'tool_name': 'Write', 'tool_input': tool_input, 'transcript_path': str(t)}
    p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload, ensure_ascii=False).encode(), capture_output=True, env=env)
    return p.returncode, p.stderr.decode('utf-8')


def test_feedback_memory_blocks_without_ledger(tmp_path):
    ws, env = env_for(tmp_path)
    code, err = gate(tmp_path, env, [], {'file_path': str(ws / 'memory' / 'feedback-new.md'), 'content': 'x'})
    assert code == 2 and 'lessons.py find' in err and '--src memory/feedback-new.md' in err


def test_find_then_add_passes(tmp_path):
    ws, env = env_for(tmp_path)
    code, out, _ = lessons(env, 'find', 'チャットの返事に「見張りを登録しました」と書かないで')
    assert code == 0 and 'less-text' in out and '[lessons] find' in out
    code, added, _ = lessons(env, 'add', '--root', 'less-text', '--quote', '宣言いらない', '--saw', '返事の最後の宣言',
                             '--where', 'チャット', '--src', str(ws / 'memory' / 'feedback-new.md'))
    assert code == 0 and '[lessons] added' in added and 'src=memory/feedback-new.md' in added
    assert 'まだ文章だけ' in added
    rows = [claude_tool('Bash', {'command': 'find'}, '1'), claude_result('1', out),
            claude_tool('Bash', {'command': 'add'}, '2'), claude_result('2', added)]
    code, err = gate(tmp_path, env, rows, {'file_path': str(ws / 'memory' / 'feedback-new.md'), 'content': 'x'})
    assert code == 0, err
    other = gate(tmp_path, env, rows, {'file_path': str(ws / 'memory' / 'feedback-other.md'), 'content': 'x'})
    assert other[0] == 2


def test_add_without_find_still_blocks(tmp_path):
    ws, env = env_for(tmp_path)
    _, added, _ = lessons(env, 'add', '--root', 'less-text', '--quote', 'q', '--saw', 's', '--where', 'w', '--src', 'memory/feedback-a.md')
    code, err = gate(tmp_path, env, [claude_result('1', added)], {'file_path': str(ws / 'memory' / 'feedback-a.md'), 'content': 'x'})
    assert code == 2 and 'find' in err


def test_structural_root_says_fix_the_check(tmp_path):
    ws, env = env_for(tmp_path)
    _, out, _ = lessons(env, 'add', '--root', 'dont-break-shared', '--quote', 'q', '--saw', 's', '--where', 'w', '--src', 'memory/feedback-b.md')
    assert 'hook_live_tree_guard.py が止めているはず' in out


def test_new_root_needs_reason(tmp_path):
    ws, env = env_for(tmp_path)
    code, _, err = lessons(env, 'add', '--new-root', '番号は全桁写す', '--kind', 'machine', '--quote', 'q', '--saw', 's', '--where', 'w', '--src', 'memory/feedback-c.md')
    assert code == 1 and '--why-new' in err
    code, out, _ = lessons(env, 'add', '--new-root', '番号は全桁写す', '--id', 'exact-strings', '--kind', 'machine', '--why-new', '文字を減らす話ではない',
                           '--quote', 'q', '--saw', 's', '--where', 'w', '--src', 'memory/feedback-c.md')
    assert code == 0 and 'root=exact-strings' in out
    data = json.loads((ws / 'lessons' / 'ledger.json').read_text(encoding='utf-8'))
    assert [r['id'] for r in data['roots']][-1] == 'exact-strings'


def test_touch_lets_a_plain_edit_through(tmp_path):
    ws, env = env_for(tmp_path)
    _, out, _ = lessons(env, 'touch', '--src', 'memory/feedback-gdoc-partial-edit.md', '--why', '関連の書き足し')
    code, _ = gate(tmp_path, env, [claude_result('1', out)], {'file_path': str(ws / 'memory' / 'feedback-gdoc-partial-edit.md'), 'new_string': 'x'})
    assert code == 0


def test_other_memory_and_plain_rule_edits_pass(tmp_path):
    ws, env = env_for(tmp_path)
    assert gate(tmp_path, env, [], {'file_path': str(ws / 'memory' / 'project-x.md'), 'content': 'type: project'})[0] == 0
    assert gate(tmp_path, env, [], {'file_path': str(ws / 'memory' / 'MEMORY.md'), 'content': 'x'})[0] == 0
    assert gate(tmp_path, env, [], {'file_path': str(ws / 'RULES.md'), 'new_string': '- 公開は確かめる'})[0] == 0
    assert gate(tmp_path, env, [], {'file_path': str(ws / 'lessons' / 'ledger.json'), 'content': '{}'})[0] == 0


def test_feedback_type_in_other_name_and_owner_quote_in_rules_block(tmp_path):
    ws, env = env_for(tmp_path)
    assert gate(tmp_path, env, [], {'file_path': str(ws / 'memory' / 'lesson-x.md'), 'content': '---\ntype: feedback\n---'})[0] == 2
    assert gate(tmp_path, env, [], {'file_path': str(ws / 'dev-lead' / 'PATROL.md'), 'new_string': '本人:「文字だけだと分かりにくい」'})[0] == 2
    assert gate(tmp_path, env, [], {'file_path': '/Users/x/dan-workspace/CLAUDE.md', 'new_string': '（10-25 本人「聞かずに直せ」）'})[0] == 2


def test_compact_forgets_earlier_markers(tmp_path):
    ws, env = env_for(tmp_path)
    _, out, _ = lessons(env, 'find', '返事を短く')
    _, added, _ = lessons(env, 'add', '--root', 'less-text', '--quote', 'q', '--saw', 's', '--where', 'w', '--src', 'memory/feedback-d.md')
    rows = [claude_result('1', out), claude_result('2', added), {'type': 'system', 'subtype': 'compact_boundary'}]
    assert gate(tmp_path, env, rows, {'file_path': str(ws / 'memory' / 'feedback-d.md'), 'content': 'x'})[0] == 2


def test_table_and_weekly(tmp_path):
    ws, env = env_for(tmp_path)
    (ws / 'memory' / 'feedback-loose.md').write_text('x', encoding='utf-8')
    lessons(env, 'add', '--root', 'less-text', '--quote', 'q', '--saw', 's', '--where', 'w', '--src', 'memory/feedback-e.md')
    code, out, _ = lessons(env, 'table')
    table = (ws / 'lessons' / 'TABLE.md').read_text(encoding='utf-8')
    assert code == 0 and '| 決まり（同じ根っこ）' in table and '機械で止める' in table and '3 件を、同じ根っこごとに 2 件' in table
    code, out, _ = lessons(env, 'weekly')
    assert code == 0 and '効いていない: less-text' in out and '台帳を通らずにある記憶: memory/feedback-loose.md' in out
    assert '[lessons] weekly' in out


def test_real_ledger_is_well_formed():
    real = Path.home() / '.dan' / 'workspace' / 'lessons' / 'ledger.json'
    if not real.exists():
        return
    data = json.loads(real.read_text(encoding='utf-8'))
    ids = [i['id'] for r in data['roots'] for i in r['items']]
    assert len(ids) == len(set(ids))
    for r in data['roots']:
        assert r['kind'] in ('machine', 'skill', 'owner', 'spec') and r['items'] and r['rule']
        assert r['check']['state'] in ('守れている', '一部', '文章だけ', '無し')
        for i in r['items']:
            assert i['quote'] and i['src'] and i['where'] and i['saw']
            assert i.get('date') is None or date.fromisoformat(i['date'])
