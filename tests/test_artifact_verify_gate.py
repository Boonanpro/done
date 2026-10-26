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


def run(tmp_path, rows, env_extra=None, **extra):
    t = tmp_path/'t.jsonl'
    t.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows), encoding='utf-8')
    payload = {'hook_event_name': 'Stop', 'transcript_path': str(t), 'session_id': 's1', 'stop_hook_active': False, **extra}
    env = dict(os.environ, DAN_ARTIFACT_GATE_DIR=str(tmp_path/'store'), DAN_ARTIFACT_GATE_LIVE='D:/done', **(env_extra or {}))
    p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload).encode(), capture_output=True, env=env)
    assert p.returncode == 0, p.stderr
    out = p.stdout.decode('utf-8').strip()
    return json.loads(out) if out else None


SEEN_OK = '...\n[artifact_seen] slug=x-operation result=OK（本人の画面と裏側が今の版）'


def shot(tag, place='artifact:x-operation', root='D:/done', tid='s', result='OK', covers=''):
    """場所を撮った結果（2026-10-25 場所の地図）。"""
    return [claude_tool('Bash', {'command': f'python {root}/scripts/place_shot.py {place} --tag {tag}'}, tid),
            claude_result(tid, f'[place_shot] place={place} covers={covers} tag={tag} result={result} root={root}')]


def mapcheck(place='artifact:x-operation', root='D:/done', tid='m', result='FRESH'):
    return [claude_tool('Bash', {'command': f'python {root}/scripts/place_map.py stamp {place}'}, tid),
            claude_result(tid, f'[place_map] place={place} result={result} root={root}')]


def after(place='artifact:x-operation', root='D:/done', tid='a'):
    return mapcheck(place, root, tid + 'm') + shot('after', place, root, tid + 's')


def test_no_artifact_edit_passes(tmp_path):
    assert run(tmp_path, [claude_tool('Edit', {'file_path': 'D:/done/app/x.py'}, '1'), claude_text('done')]) is None


def test_edit_without_check_blocks(tmp_path):
    r = run(tmp_path, [claude_tool('Edit', {'file_path': LIVE + '/x-operation/page-body.tsx'}, '1'), claude_text('直しました')])
    assert r['decision'] == 'block' and 'x-operation' in r['reason'] and 'artifact_seen.py --slug x-operation' in r['reason']


def test_windows_path_and_mcp_tool_blocks(tmp_path):
    r = run(tmp_path, [claude_tool('mcp__dan-tools__write_file', {'path': 'D:\\done\\frontend\\src\\app\\artifacts\\fukurou-inbox\\_server\\routes.py'}, '1')])
    assert r and 'fukurou-inbox' in r['reason']


def test_check_after_edit_passes(tmp_path):
    rows = [*shot('before'), claude_tool('Edit', {'file_path': LIVE + '/x-operation/a.tsx'}, '1'),
            claude_tool('Bash', {'command': 'python D:/done/scripts/artifact_seen.py --slug x-operation --wait 90'}, '2'),
            claude_result('2', SEEN_OK), *after(), claude_text('直しました')]
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


def test_worktree_paths_need_no_owner_check_but_need_the_map(tmp_path):
    """作業場所の書き換えは本人の画面の確認（artifact_seen）は要らないが、地図と撮影は要る（10-25 確かめ役の指摘）。"""
    rows = [claude_tool('Edit', {'file_path': 'D:/dan-workspace/wt/frontend/src/app/artifacts/x-operation/a.tsx'}, '1'),
            claude_tool('Bash', {'command': 'cd /d/dan-workspace/wt && echo x > frontend/src/app/artifacts/x-operation/a.tsx'}, '2')]
    r = run(tmp_path, rows)
    assert r['decision'] == 'block' and 'artifact_seen' not in r['reason'] and 'd:/dan-workspace/wt/scripts/place_map.py' in r['reason']


def test_ng_result_blocks_once_to_wait_not_to_report(tmp_path):
    """10-25: NG は「本人に伝えさせる」ためではなく、待って確かめ直させるために1回だけ止める。書き方では通さない。"""
    ng = '[artifact_seen] slug=x-operation result=NG（まだ古い所がある）'
    rows = [*shot('before'), claude_tool('Edit', {'file_path': LIVE + '/x-operation/a.tsx'}, '1'), *after(),
            claude_tool('Bash', {'command': 'python D:/done/scripts/artifact_seen.py --slug x-operation'}, '2'),
            claude_result('2', ng)]
    r = run(tmp_path, rows + [claude_text('裏側が再起動待ちのため、まだ直っていません。')])
    assert r['decision'] == 'block' and '--wait 90' in r['reason']
    assert run(tmp_path, rows + [claude_text('はい、押すとその場で書き換えられます。')], stop_hook_active=True) is None


def test_block_reason_keeps_the_answer_and_hides_the_check(tmp_path):
    """止めた後の文だけが返事になるので、前の答えを全部書き直させ、確かめた結果は書かせない（10-25 答えが消えた件）。"""
    r = run(tmp_path, [claude_tool('Edit', {'file_path': LIVE + '/x-operation/a.tsx'}, '1')])
    assert '返事に書かない' in r['reason'] and 'そのまま全部もう一度書いて' in r['reason']
    assert '出た結果どおりに報告' not in r['reason']


def test_ng_from_an_earlier_turn_does_not_stop_the_next_turn(tmp_path):
    """10-25: 前のターンの NG のまま、次の「READY」だけのターンが止められた。"""
    rows = [claude_tool('Edit', {'file_path': LIVE + '/x-operation/a.tsx'}, '1'),
            claude_tool('Bash', {'command': 'python D:/done/scripts/artifact_seen.py --slug x-operation'}, '2'),
            claude_result('2', '[artifact_seen] slug=x-operation result=NG（まだ古い所がある）'),
            claude_text('はい、押すとその場で書き換えられます。'),
            {'type': 'user', 'message': {'role': 'user', 'content': 'Stop hook feedback: [成果物の確認の関所] …'}},
            claude_text('はい、押すとその場で書き換えられます。'),
            {'type': 'user', 'message': {'role': 'user', 'content': '[CONTEXT PRELOAD] READY とだけ返して'}},
            claude_text('READY')]
    assert run(tmp_path, rows) is None


def test_unchecked_with_ack_passes(tmp_path):
    rows = [*shot('before'), claude_tool('Edit', {'file_path': LIVE + '/x-operation/a.tsx'}, '1'),
            claude_tool('Bash', {'command': 'python D:/done/scripts/artifact_seen.py --slug x-operation'}, '2'),
            claude_result('2', '[artifact_seen] slug=x-operation result=UNCHECKED（本人の画面では未確認）'),
            *after(), claude_text('はい、押すとその場で書き換えられます。')]
    assert run(tmp_path, rows) is None


def test_block_is_capped(tmp_path):
    rows = [claude_tool('Edit', {'file_path': LIVE + '/x-operation/a.tsx'}, '1')]
    got = [run(tmp_path, rows, stop_hook_active=True) for _ in range(5)]
    assert [g is not None for g in got] == [True, True, True, False, False]


def test_codex_apply_patch_and_output(tmp_path):
    patch = 'text(await tools.apply_patch("*** Begin Patch\\n*** Update File: D:/done/frontend/src/app/artifacts/fukurou-inbox/page-body.tsx\\n@@\\n+x\\n*** End Patch"));'
    assert 'fukurou-inbox' in run(tmp_path, [codex_call(patch)])['reason']
    rows = [codex_call('text(await tools.exec_command({cmd: "python D:/done/scripts/place_shot.py fukurou-inbox --tag before"}));'),
            codex_out('[place_shot] place=artifact:fukurou-inbox covers= tag=before result=OK root=D:/done'),
            codex_call(patch),
            codex_call('text(await tools.exec_command({cmd: "python D:/done/scripts/artifact_seen.py --slug fukurou-inbox --wait 90"}));'),
            codex_out('[artifact_seen] slug=fukurou-inbox result=OK（本人の画面と裏側が今の版）'),
            codex_call('text(await tools.exec_command({cmd: "python D:/done/scripts/place_map.py stamp fukurou-inbox && python D:/done/scripts/place_shot.py fukurou-inbox --tag after"}));'),
            codex_out('[place_map] place=artifact:fukurou-inbox result=FRESH root=D:/done\n[place_shot] place=artifact:fukurou-inbox covers= tag=after result=OK root=D:/done')]
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


# --- 場所の地図と画面の見え方（2026-10-25 確かめ役の指摘 3・6） ---------------------------------------------------------

def edited_and_seen(path='/x-operation/a.tsx'):
    return [claude_tool('Edit', {'file_path': LIVE + path}, '1'),
            claude_tool('Bash', {'command': 'python D:/done/scripts/artifact_seen.py --slug x-operation'}, '2'),
            claude_result('2', SEEN_OK)]


def test_screen_edit_without_map_blocks(tmp_path):
    r = run(tmp_path, [*shot('before')] + edited_and_seen() + [claude_text('直しました')])
    assert r['decision'] == 'block' and 'place_map.py check artifact:x-operation' in r['reason'] and '--tag after' in r['reason']
    assert '返事に書かない' in r['reason']


def test_after_only_without_before_blocks_once(tmp_path):
    rows = edited_and_seen() + after() + [claude_text('直しました')]
    r = run(tmp_path, rows)
    assert r['decision'] == 'block' and '--tag before' in r['reason']
    assert run(tmp_path, rows) is None          # 後からは撮れないので1回だけ


def test_latest_map_must_be_fresh(tmp_path):
    rows = [*shot('before')] + edited_and_seen() + after() + mapcheck(result='STALE', tid='late')
    r = run(tmp_path, rows + [claude_text('直しました')])
    assert r['decision'] == 'block' and 'place_map.py check' in r['reason']


def test_map_and_shot_before_last_screen_edit_do_not_count(tmp_path):
    rows = [*shot('before')] + edited_and_seen() + after() + [claude_tool('Edit', {'file_path': LIVE + '/x-operation/b.tsx'}, '9'),
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


def test_shot_ng_blocks_to_fix(tmp_path):
    rows = [*shot('before')] + edited_and_seen() + mapcheck() + shot('after', result='NG', tid='ng')
    r = run(tmp_path, rows + [claude_text('直しました')])
    assert r['decision'] == 'block' and '見えなかった物を直してから撮り直す' in r['reason']


def test_dev_lead_room_shot_counts_for_the_board(tmp_path):
    rows = [*shot('before', 'dev-lead-room', covers='artifact:dev-lead'),
            claude_tool('Edit', {'file_path': LIVE + '/dev-lead/style.module.css'}, '1'),
            claude_tool('Bash', {'command': 'python D:/done/scripts/artifact_seen.py --slug dev-lead'}, '2'),
            claude_result('2', '[artifact_seen] slug=dev-lead result=OK'),
            *mapcheck('artifact:dev-lead'), *shot('after', 'dev-lead-room', covers='artifact:dev-lead', tid='x')]
    assert run(tmp_path, rows) is None


def test_worktree_edit_needs_its_own_tree(tmp_path):
    wt = 'D:/dan-workspace/wt'
    edit = [claude_tool('Edit', {'file_path': wt + '/frontend/src/app/artifacts/x-operation/a.tsx'}, '1')]
    assert run(tmp_path, [*shot('before', root=wt)] + edit + after(root=wt)) is None
    assert run(tmp_path, [*shot('before')] + edit + after(), )['decision'] == 'block'   # 動いているダンで撮っても数えない


def test_codex_exec_edit_file_counts(tmp_path):
    call = codex_call('text(await tools.mcp__dan_job__edit_file({path: "D:/dan-workspace/wt/frontend/src/app/artifacts/x-operation/a.tsx", old_string: "a", new_string: "b"}));')
    r = run(tmp_path, [call])
    assert r and r['decision'] == 'block' and 'artifact:x-operation' in r['reason']


def test_relative_path_uses_cwd(tmp_path):
    row = claude_tool('Bash', {'command': 'echo x >> frontend/src/app/artifacts/x-operation/a.tsx'}, '1')
    row['cwd'] = 'D:/dan-workspace/wt'
    r = run(tmp_path, [row])
    assert r and 'd:/dan-workspace/wt/scripts/place_map.py' in r['reason']


def test_watched_file_of_a_common_place_needs_that_map(tmp_path):
    tree = tmp_path / 'wt'
    (tree / 'docs/places').mkdir(parents=True)
    (tree / 'docs/places/chat.md').write_text('---\nplace: chat\nwatches:\n  - frontend/src/components/layout/*.tsx\n---\n', encoding='utf-8')
    env = {'DAN_ARTIFACT_GATE_WORKTREES': str(tmp_path)}
    root = tree.as_posix()
    edit = [claude_tool('Edit', {'file_path': root + '/frontend/src/components/layout/project-chat-panel.tsx'}, '1')]
    r = run(tmp_path, edit, env_extra=env)
    assert r and 'place_map.py check chat' in r['reason']
    assert run(tmp_path, [*shot('before', 'chat', root)] + edit + after('chat', root), env_extra=env) is None
