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


def mapped(slug, tid='m', shot='OK'):
    """画面を書き換えた後の、地図の stamp と画面を撮った結果（2026-10-25 場所の地図）。"""
    return [claude_tool('Bash', {'command': f'python D:/done/scripts/place_map.py stamp {slug}'}, tid + '1'),
            claude_result(tid + '1', f'[place_map] slug={slug} result=FRESH'),
            claude_tool('Bash', {'command': f'python D:/done/scripts/place_shot.py artifact:{slug} --tag after'}, tid + '2'),
            claude_result(tid + '2', f'[place_shot] place=artifact:{slug} tag=after result={shot}')]


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
            claude_result('2', SEEN_OK), *mapped('x-operation'), claude_text('本人の画面でも新しい版です')]
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
            claude_result('2', ng), *mapped('x-operation')]
    r = run(tmp_path, rows + [claude_text('直しました。')])
    assert r['decision'] == 'block' and 'NG' in r['reason']
    assert run(tmp_path, rows + [claude_text('裏側が再起動待ちのため、まだ直っていません。')]) is None


def test_unchecked_with_ack_passes(tmp_path):
    rows = [claude_tool('Edit', {'file_path': LIVE + '/x-operation/a.tsx'}, '1'),
            claude_tool('Bash', {'command': 'python D:/done/scripts/artifact_seen.py --slug x-operation'}, '2'),
            claude_result('2', '[artifact_seen] slug=x-operation result=UNCHECKED（本人の画面では未確認）'),
            *mapped('x-operation'), claude_text('みきさんの画面ではまだ確かめていません。')]
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
            codex_out('[artifact_seen] slug=fukurou-inbox result=OK（本人の画面と裏側が今の版）'),
            codex_call('text(await tools.exec_command({cmd: "python D:/done/scripts/place_map.py stamp fukurou-inbox && python D:/done/scripts/place_shot.py fukurou-inbox"}));'),
            codex_out('[place_map] slug=fukurou-inbox result=FRESH\n[place_shot] place=artifact:fukurou-inbox tag=now result=OK')]
    assert run(tmp_path, rows, last_assistant_message='直しました') is None


def test_data_heredoc_body_is_not_an_edit(tmp_path):
    body = ("cat > tests/t.py <<'EOF'\n"
            "LIVE = 'D:/done/frontend/src/app/artifacts/x-operation'\n"
            "open(LIVE + '/a.tsx', 'w')\n"
            "EOF\n"
            "echo ok")
    assert run(tmp_path, [claude_tool('Bash', {'command': body}, '1')]) is None
    into_artifact = "cat > D:/done/frontend/src/app/artifacts/x-operation/a.tsx <<'EOF'\nx\nEOF"
    assert run(tmp_path, [claude_tool('Bash', {'command': into_artifact}, '1')])['decision'] == 'block'
    code = "python - <<'EOF'\nopen('D:/done/frontend/src/app/artifacts/x-operation/a.tsx','w').write('x')\nEOF"
    assert run(tmp_path, [claude_tool('Bash', {'command': code}, '1')])['decision'] == 'block'


def test_ng_word_next_to_japanese_counts_as_reported(tmp_path):
    rows = [claude_tool('Edit', {'file_path': LIVE + '/x-operation/a.tsx'}, '1'),
            claude_tool('Bash', {'command': 'python D:/done/scripts/artifact_seen.py --slug x-operation'}, '2'),
            claude_result('2', '[artifact_seen] slug=x-operation result=NG（まだ古い所がある）'),
            *mapped('x-operation'), claude_text('確認の結果はNGでした。')]
    assert run(tmp_path, rows) is None


# --- 場所の地図（2026-10-25）: 画面を書き換えたら、地図を直して（FRESH）画面を撮るまで終われない ---

def edited_and_seen(path='/x-operation/a.tsx'):
    return [claude_tool('Edit', {'file_path': LIVE + path}, '1'),
            claude_tool('Bash', {'command': 'python D:/done/scripts/artifact_seen.py --slug x-operation'}, '2'),
            claude_result('2', SEEN_OK)]


def test_screen_edit_without_map_blocks(tmp_path):
    r = run(tmp_path, edited_and_seen() + [claude_text('直しました')])
    assert r['decision'] == 'block' and 'place_map.py check x-operation' in r['reason'] and 'place_shot.py artifact:x-operation' in r['reason']


def test_stale_map_still_blocks(tmp_path):
    rows = edited_and_seen() + [claude_tool('Bash', {'command': 'python D:/done/scripts/place_map.py check x-operation'}, '3'),
                                claude_result('3', '[place_map] slug=x-operation result=STALE')]
    r = run(tmp_path, rows + [claude_text('直しました')])
    assert r['decision'] == 'block' and 'place_map.py check' in r['reason']


def test_map_before_last_screen_edit_does_not_count(tmp_path):
    rows = edited_and_seen() + mapped('x-operation') + [claude_tool('Edit', {'file_path': LIVE + '/x-operation/b.tsx'}, '9'),
                                                       claude_tool('Bash', {'command': 'python D:/done/scripts/artifact_seen.py --slug x-operation'}, '10'),
                                                       claude_result('10', SEEN_OK)]
    assert run(tmp_path, rows)['decision'] == 'block'


def test_server_and_map_only_edits_need_no_map(tmp_path):
    for path in ('/x-operation/_server/routes.py', '/x-operation/MAP.md', '/x-operation/PRODUCT.md'):
        assert run(tmp_path, edited_and_seen(path) + [claude_text('直しました')]) is None, path


def test_shell_write_to_map_only_needs_no_map(tmp_path):
    rows = [claude_tool('Bash', {'command': "cat > D:/done/frontend/src/app/artifacts/x-operation/MAP.md <<'EOF'\nx\nEOF"}, '1'),
            claude_tool('Bash', {'command': 'python D:/done/scripts/artifact_seen.py --slug x-operation'}, '2'),
            claude_result('2', SEEN_OK)]
    assert run(tmp_path, rows) is None


def test_shot_ng_must_be_reported(tmp_path):
    rows = edited_and_seen() + mapped('x-operation', shot='NG')
    r = run(tmp_path, rows + [claude_text('直しました')])
    assert r['decision'] == 'block' and '撮った結果' in r['reason']
    assert run(tmp_path, rows + [claude_text('番号の並びがまだ見えていません（NG）。')]) is None


def test_map_block_is_capped(tmp_path):
    rows = edited_and_seen()
    got = [run(tmp_path, rows) for _ in range(5)]
    assert [g is not None for g in got] == [True, True, True, False, False]
