"""In a real room, on every engine: is a message sent while Dan works read by Dan, and is the work so far kept above it?

docs/current/chat-timeline-definition.md §6. The unit tests (tests/test_turn_flow_engines.py) check the rules on each
engine's code; this checks them through the real send entrance, the real CLI of each engine and the saved rows, in the
test room. For each engine in app/agent/turn_flow.ENGINES it sets the room to a model of that engine, sends a first
message that makes Dan wait a while, sends a follow-up while Dan waits, and reads the saved rows.

Usage: python scripts/verify_chat_engines.py [engine ...]     exit 0 = passed, 1 = failed (the reason is printed)
       --after 15    seconds between the first message and the follow-up (default 15)
The room's own model choice is put back at the end. Takes about two minutes per engine.
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')

import httpx

USER = '2582a188-ff24-4a4f-b989-6063034d90b2'
TEST_ROOM = '38461f5a-6ded-464a-adb9-92a7de46b288'   # 「Epic Gamesログインと認証設定」: the room tests may use
API = 'http://127.0.0.1:9000/api/v1/chat'
STARTED, READ = '始めます', '追い連絡も読んだ'
WAIT = 45
FIRST = f'動作確認1通目: まず「{STARTED}」と一言書き、次にコマンドで {WAIT} 秒待ち（sleep {WAIT} / Start-Sleep {WAIT}）、終わったら「1通目終わり」とだけ答えて。'
FOLLOW = f'動作確認の追い連絡: 最後の答えに「{READ}」と付け足して。'


def signed_in():
    from app.services.auth_service import create_access_token
    from app.services.supabase_client import get_supabase_client
    sb = get_supabase_client().client
    email = (sb.table('users').select('email').eq('id', USER).limit(1).execute().data or [{}])[0].get('email') or ''
    return sb, {'Authorization': f'Bearer {create_access_token(USER, email)}'}


def model_for(engine):
    from app.agent import cli_runner
    return next(o['id'] for o in cli_runner.CLI_MODEL_OPTIONS if o['backend'] == engine)


def busy(headers):
    return bool(httpx.get(f'{API}/dan/sessions/{TEST_ROOM}/active', headers=headers, timeout=20).json().get('active'))


def set_model(headers, model):
    for _ in range(36):
        code = httpx.patch(f'{API}/dan/sessions/{TEST_ROOM}/model', headers=headers, json={'model': model}, timeout=30).status_code
        if code != 409:     # 409 = Dan is still working in the room
            return code
        time.sleep(5)
    return code


def send(headers, content):
    with httpx.Client(timeout=httpx.Timeout(600, connect=10)) as client:
        with client.stream('POST', f'{API}/dan/messages/stream', headers=headers, json={'content': content, 'session_id': TEST_ROOM}) as r:
            for line in r.iter_lines():
                if line.startswith('data: ') and json.loads(line[6:]).get('type') == 'done':
                    return


def check(sb, headers, engine, after):
    """The reasons this engine fails, empty when it passes."""
    since = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(time.time() - 2))
    first = threading.Thread(target=send, args=(headers, FIRST))
    first.start()
    time.sleep(after)
    follow = threading.Thread(target=send, args=(headers, FOLLOW))
    follow.start()
    first.join(); follow.join()
    for _ in range(60):
        time.sleep(3)
        if not busy(headers):
            break
    time.sleep(4)
    rows = sb.table('chat_messages').select('sender_type,content,created_at,ai_context').eq('room_id', TEST_ROOM) \
        .gte('created_at', since).order('created_at').execute().data
    for r in rows:
        steps = len((r.get('ai_context') or {}).get('blocks') or [])
        print('   ', r['created_at'][11:23], 'ダン' if r['sender_type'] == 'ai' else '本人', f'（作業 {steps} 手）' if steps else '',
              '|', (r['content'] or '（本文なし）')[:60].replace('\n', ' '))
    at = next((i for i, r in enumerate(rows) if r['sender_type'] == 'human' and r['content'] == FOLLOW), None)
    if at is None:
        return ['the follow-up was not saved']
    reasons = []
    dan = lambda r: r['sender_type'] == 'ai'
    text = lambda r: (r['content'] or '') + json.dumps((r.get('ai_context') or {}).get('blocks') or [], ensure_ascii=False)
    if not any(dan(r) and READ in (r['content'] or '') for r in rows[at + 1:]):
        reasons.append('Dan did not read the follow-up (no answer to it below it)')
    below = [r for r in rows[at + 1:] if dan(r) and STARTED in text(r) and READ not in text(r)]
    if below:
        reasons.append('the record of the work done before the follow-up is below it (looks like two messages in a row)')
    if not any(dan(r) and STARTED in text(r) for r in rows[:at]):
        reasons.append('no record of the work done before the follow-up is above it')
    return reasons


def main():
    from app.agent import turn_flow
    parser = argparse.ArgumentParser()
    parser.add_argument('engines', nargs='*', default=sorted(turn_flow.ENGINES))
    parser.add_argument('--after', type=float, default=15)
    args = parser.parse_args()
    sb, headers = signed_in()
    if busy(headers):
        print('FAILED: Dan is working in the test room; not touching it')
        return 1
    project = sb.table('projects').select('id,metadata').eq('room_id', TEST_ROOM).limit(1).execute().data[0]
    own_choice = (project.get('metadata') or {}).get('model')
    failed = {}
    try:
        for engine in args.engines:
            model = model_for(engine)
            print(f'{engine} ({model}): the follow-up goes {args.after:.0f} s after the first message')
            if set_model(headers, model) != 200:
                failed[engine] = ['the room could not be set to this model']
                continue
            failed[engine] = check(sb, headers, engine, args.after)
            print('    ->', 'passed' if not failed[engine] else 'FAILED: ' + '; '.join(failed[engine]))
    finally:
        # Back through the API (it clears the core's memory of the choice); a room that had no choice of its own gets the
        # key taken out again so it follows the default model.
        from app.agent import cli_runner
        set_model(headers, own_choice or cli_runner._resolve_cli_model_raw(None))
        if own_choice is None:
            meta = sb.table('projects').select('metadata').eq('id', project['id']).limit(1).execute().data[0].get('metadata') or {}
            sb.table('projects').update({'metadata': {k: v for k, v in meta.items() if k != 'model'}}).eq('id', project['id']).execute()
        print('the room\'s model choice is back to:', own_choice or 'none (the default)')
    return 1 if any(failed.values()) else 0


if __name__ == '__main__':
    sys.exit(main())
