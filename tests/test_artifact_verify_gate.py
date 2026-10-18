"""Stop hook: a turn that changed an artifact cannot end before artifact_seen ran after the change (2026-10-18)."""
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1]/'scripts'/'hook_artifact_verify_gate.py'
LIVE = 'D:/done/frontend/src/app/artifacts'


def claude_tool(name, inp, tid):
    return {'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': tid, 'name': name, 'input': inp}]}}


def claude_result(tid, text):
    return {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': tid, 'content': text}]}}


def claude_text(text):
    return {'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}}


def codex_call(inp):
    return {'type': 'response_item', 'payload': {'type': 'custom_tool_call', 'name': 'exec', 'call_id': 'c', 'input': inp}}


def codex_out(text):
    return {'type': 'response_item', 'payload': {'type': 'custom_tool_call_output', 'call_id': 'c', 'output': [{'type': 'input_text', 'text': text}]}}


def run(tmp_path, rows, **extra):
    t = tmp_path/'t.jsonl'
    t.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows), encoding='utf-8')
    payload = {'hook_event_name': 'Stop', 'transcript_path': str(t), 'session_id': 's1', 'stop_hook_active': False, **extra}
    env = dict(os.environ, DAN_ARTIFACT_GATE_DIR=str(tmp_path/'store'), DAN_ARTIFACT_GATE_LIVE='D:/done')
    p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload).encode(), capture_output=True, env=env)
    assert p.returncode == 0, p.stderr
    out = p.stdout.decode('utf-8').strip()
    return json.loads(out) if out else None


SEEN_OK = '...\n[artifact_seen] slug=x-operation result=OK（本人の画面と裏側が今の版）'


def test_no_artifact_edit_passes(tmp_path):
    assert run(tmp_path, [claude_tool('Edit', {'file_path': 'D:/done/app/x.py'}, '1'), claude_text('done')]) is None


def test_edit_without_check_blocks(tmp_path):
    r = run(tmp_path, [claude_tool('Edit', {'file_path': LIVE + '/x-operation/page-body.tsx'}, '1'), claude_text('直しました')])
    assert r['decision'] == 'block' and 'x-operation' in r['reason'] and 'artifact_seen.py --slug x-operation' in r['reason']


def test_windows_path_and_mcp_tool_blocks(tmp_path):
    r = run(tmp_path, [claude_tool('mcp__dan-tools__write_file', {'path': 'D:\\done\\frontend\\src\\app\\artifacts\\fukurou-inbox\\_server\\routes.py'}, '1')])
    assert r and 'fukurou-inbox' in r['reason']


def test_check_after_edit_passes(tmp_path):
    rows = [claude_tool('Edit', {'file_path': LIVE + '/x-operation/a.tsx'}, '1'),
            claude_tool('Bash', {'command': 'python D:/done/scripts/artifact_seen.py --slug x-operation --wait 90'}, '2'),
            claude_result('2', SEEN_OK), claude_text('本人の画面でも新しい版です')]
    assert run(tmp_path, rows) is None


def test_check_before_last_edit_blocks(tmp_path):
    rows = [claude_tool('Edit', {'file_path': LIVE + '/x-operation/a.tsx'}, '1'),
            claude_tool('Bash', {'command': 'python D:/done/scripts/artifact_seen.py --slug x-operation'}, '2'),
            claude_result('2', SEEN_OK),
            claude_tool('Edit', {'file_path': LIVE + '/x-operation/b.tsx'}, '3')]
    assert run(tmp_path, rows)['decision'] == 'block'


def test_shell_write_counts_and_read_does_not(tmp_path):
    read = [claude_tool('Bash', {'command': 'cd /d/done && sed -n 1,40p frontend/src/app/artifacts/x-operation/page.tsx'}, '1')]
    assert run(tmp_path, read) is None
    write = [claude_tool('Bash', {'command': "python - <<'EOF'\nopen('D:/done/frontend/src/app/artifacts/x-operation/a.tsx','w').write('x')\nEOF"}, '1')]
    assert run(tmp_path, write)['decision'] == 'block'
    msys = [claude_tool('Bash', {'command': 'echo x > /d/done/frontend/src/app/artifacts/x-operation/a.tsx'}, '1')]
    assert run(tmp_path, msys)['decision'] == 'block'


def test_worktree_paths_are_not_live(tmp_path):
    rows = [claude_tool('Edit', {'file_path': 'D:/dan-workspace/wt/frontend/src/app/artifacts/x-operation/a.tsx'}, '1'),
            claude_tool('Bash', {'command': 'cd /d/dan-workspace/wt && echo x > frontend/src/app/artifacts/x-operation/a.tsx'}, '2')]
    assert run(tmp_path, rows) is None


def test_ng_result_must_be_reported(tmp_path):
    ng = '[artifact_seen] slug=x-operation result=NG（まだ古い所がある）'
    rows = [claude_tool('Edit', {'file_path': LIVE + '/x-operation/a.tsx'}, '1'),
            claude_tool('Bash', {'command': 'python D:/done/scripts/artifact_seen.py --slug x-operation'}, '2'),
            claude_result('2', ng)]
    r = run(tmp_path, rows + [claude_text('直しました。')])
    assert r['decision'] == 'block' and 'NG' in r['reason']
    assert run(tmp_path, rows + [claude_text('裏側が再起動待ちのため、まだ直っていません。')]) is None


def test_unchecked_with_ack_passes(tmp_path):
    rows = [claude_tool('Edit', {'file_path': LIVE + '/x-operation/a.tsx'}, '1'),
            claude_tool('Bash', {'command': 'python D:/done/scripts/artifact_seen.py --slug x-operation'}, '2'),
            claude_result('2', '[artifact_seen] slug=x-operation result=UNCHECKED（本人の画面では未確認）'),
            claude_text('みきさんの画面ではまだ確かめていません。')]
    assert run(tmp_path, rows) is None


def test_block_is_capped(tmp_path):
    rows = [claude_tool('Edit', {'file_path': LIVE + '/x-operation/a.tsx'}, '1')]
    got = [run(tmp_path, rows, stop_hook_active=True) for _ in range(5)]
    assert [g is not None for g in got] == [True, True, True, False, False]


def test_codex_apply_patch_and_output(tmp_path):
    patch = 'text(await tools.apply_patch("*** Begin Patch\\n*** Update File: D:/done/frontend/src/app/artifacts/fukurou-inbox/page-body.tsx\\n@@\\n+x\\n*** End Patch"));'
    assert 'fukurou-inbox' in run(tmp_path, [codex_call(patch)])['reason']
    rows = [codex_call(patch),
            codex_call('text(await tools.exec_command({cmd: "python D:/done/scripts/artifact_seen.py --slug fukurou-inbox --wait 90"}));'),
            codex_out('[artifact_seen] slug=fukurou-inbox result=OK（本人の画面と裏側が今の版）')]
    assert run(tmp_path, rows, last_assistant_message='直しました') is None
