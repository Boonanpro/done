"""Stop hook: みきさんの不具合の知らせに、同じ崩れを出さずに「直しました」と返せない（2026-10-27 付箋「不具合を先に再現する」）。"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_artifact_verify_gate import LIVE, SEEN_OK, claude_result, claude_text, claude_tool, mapcheck, run

ROOT = Path(__file__).resolve().parents[1]


def owner(text, wrapped=True):
    body = (f'<place>\nこの部屋が出る場所: 成果物タブ\n</place>\n<conversation_so_far>前の話: 開けない件</conversation_so_far>\n'
            f'<latest_user_message>\n{text}\n</latest_user_message>') if wrapped else text
    return {'type': 'user', 'message': {'role': 'user', 'content': body}}


def shot(tag, result='OK', repro=None, place='artifact:x-operation', root='D:/done', tid='s'):
    extra = f' expect=1 repro={repro}' if repro else ''
    return [claude_tool('Bash', {'command': f'python {root}/scripts/place_shot.py {place} --tag {tag} --expect-shows 番号の並び'}, tid),
            claude_result(tid, f'[place_shot] place={place} covers= tag={tag} result={result} root={root}{extra}')]


EDIT = claude_tool('Edit', {'file_path': LIVE + '/x-operation/comment-content.module.css'}, 'e')
SEEN = [claude_tool('Bash', {'command': 'python D:/done/scripts/artifact_seen.py --slug x-operation --wait 90'}, 'v'),
        claude_result('v', SEEN_OK)]
PIC = '[添付画像: /api/v1/files/compare.png]'


def test_fix_without_reproducing_blocks(tmp_path):
    rows = [owner('X運用室のコメントで番号が出てないよ'), EDIT, *SEEN, *mapcheck(), *shot('after', repro='NO'),
            claude_text('番号が出るように直しました。' + PIC)]
    r = run(tmp_path, rows)
    assert r['decision'] == 'block' and '同じ崩れをこちらで出して' in r['reason'] and '書き換える前に必ず撮る' in r['reason']
    # 直す前は後から撮れないので1回だけ（その後は地図と撮影の関所だけが見る）
    again = run(tmp_path, rows)
    assert again is None or '同じ崩れ' not in again['reason']


def test_claim_without_edit_or_shot_blocks(tmp_path):
    r = run(tmp_path, [owner('表紙の×が出ない'), claude_text('直りました。')])
    assert r['decision'] == 'block' and '--tag before' in r['reason'] and '--expect-visible' in r['reason']


def test_reproduce_fix_after_and_picture_passes(tmp_path):
    rows = [owner('X運用室のコメントで番号が出てないよ'), *shot('before', 'NG', 'YES', tid='b'), EDIT, *SEEN, *mapcheck(),
            *shot('after', 'OK', 'NO', tid='a'), claude_text('番号が消えていたので出るように直しました。' + PIC)]
    assert run(tmp_path, rows) is None


def test_reproduced_but_no_picture_blocks(tmp_path):
    rows = [owner('番号が出てない'), *shot('before', 'NG', 'YES', tid='b'), EDIT, *SEEN, *mapcheck(),
            *shot('after', 'OK', 'NO', tid='a'), claude_text('直しました。')]
    r = run(tmp_path, rows)
    assert r['decision'] == 'block' and 'attach_image' in r['reason'] and 'compare.png' in r['reason']


def test_after_without_the_same_expectation_blocks(tmp_path):
    rows = [owner('番号が出てない'), *shot('before', 'NG', 'YES', tid='b'), EDIT, *SEEN, *mapcheck(),
            *shot('after', 'OK', None, tid='a'), claude_text('直しました。' + PIC)]
    r = run(tmp_path, rows)
    assert r['decision'] == 'block' and '--tag after' in r['reason']


def test_not_reproduced_needs_owner_screen_check(tmp_path):
    rows = [owner('表紙の×が出ない'), *shot('before', 'OK', 'NO', tid='b'),
            claude_text('こちらでは×が出ています。みきさんの画面が古い版のままでした。' + PIC)]
    r = run(tmp_path, rows)
    # 直したとは言っていないので止めない（調べて答えただけ）
    assert r is None
    rows[-1] = claude_text('×が出るように直してあります。' + PIC)
    r = run(tmp_path, rows)
    assert r['decision'] == 'block' and 'artifact_seen.py' in r['reason'] and 'repro=NO' in r['reason']
    assert run(tmp_path, rows[:-1] + SEEN + [rows[-1]]) is None


def test_photo_only_counts_as_a_bug_report(tmp_path):
    r = run(tmp_path, [owner('[添付画像: /api/v1/files/a.png] ？？？'), EDIT, *SEEN, claude_text('直しました')])
    assert r['decision'] == 'block' and '同じ崩れ' in r['reason']


def test_phone_look_counts_for_the_mobile_app(tmp_path):
    rows = [owner('アプリで通話の玉が出ない'),
            claude_tool('mcp__dan-tools__phone', {'action': 'screenshot'}, 'p1'), claude_result('p1', 'ok'),
            claude_tool('Edit', {'file_path': 'D:/done/mobile/app/src/Call.kt'}, 'e2'),
            claude_tool('mcp__dan-tools__phone', {'action': 'read'}, 'p2'), claude_result('p2', 'ok'),
            claude_text('玉が出るように直しました。' + PIC)]
    assert run(tmp_path, rows) is None


def test_not_a_bug_report_or_no_fix_passes(tmp_path):
    # 不具合の知らせではない頼み（地図と撮影の関所だけが見る）
    assert run(tmp_path, [owner('X運用室に新しい欄を足して'), *shot('before', tid='b'), EDIT, *SEEN, *mapcheck(),
                          *shot('after', tid='a'), claude_text('足しました')]) is None
    assert run(tmp_path, [owner('番号が出てないのはなぜ？'), claude_text('CSS で番号の印を消していたからです。')]) is None
    # 仕組みの起床・文脈の読み込みは本人の言葉ではない
    assert run(tmp_path, [owner('[CONTEXT PRELOAD] READY とだけ返して。前の話: 開けない'), claude_text('直しました')]) is None
    # 古い話の中の言葉は数えない
    assert run(tmp_path, [owner('進めて'), claude_text('直しました')]) is None


def test_backend_only_fix_with_claim_blocks_once(tmp_path):
    rows = [owner('保存するとエラーが出る'), claude_tool('Edit', {'file_path': 'D:/done/app/services/mail.py'}, 'm'),
            claude_text('届くように直しました。')]
    assert run(tmp_path, rows)['decision'] == 'block'
    assert run(tmp_path, rows) is None


def test_place_shot_expect_options_parse():
    out = subprocess.run([sys.executable, str(ROOT / 'scripts/place_shot.py'), 'x-operation', '--expect-shows', 'ない物'],
                         capture_output=True, text=True)
    assert out.returncode == 2 and '--expect-shows の名前は' in out.stderr


def test_editing_only_the_map_after_the_fix_needs_no_new_shot(tmp_path):
    """10-27 試し: 直して撮った後に MAP.md だけ直したら、撮り直しを求められた。"""
    rows = [owner('番号が出てない'), *shot('before', 'NG', 'YES', tid='b'), EDIT, *SEEN, *shot('after', 'OK', 'NO', tid='a'),
            claude_tool('Edit', {'file_path': LIVE + '/x-operation/MAP.md'}, 'mp'), *mapcheck(),
            claude_text('直しました。' + PIC)]
    assert run(tmp_path, rows) is None
