"""Claude Code PreToolUse hook for Dan's CLIs (chat Dan's room turn and parallel jobs): before a file is written, take
that file for this piece of work (app/services/work_locks.py). If another piece of work in progress holds it, wait for
it to finish; the job's line in the room's work list says what it is waiting for. Still held after the wait limit:
refuse this write with the reason, so the model does the rest of its work and comes back to it.
Outside Dan (no DAN_LOCK_OWNER / DAN_COMMAND_JOB_ID) it does nothing.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path


def main():
    if not (os.environ.get('DAN_LOCK_OWNER') or os.environ.get('DAN_COMMAND_JOB_ID')):
        return
    try:
        data = json.loads(sys.stdin.buffer.read().decode('utf-8') or '{}')
    except ValueError:
        return
    args = data.get('tool_input') or {}
    path = args.get('file_path') or args.get('notebook_path') or args.get('path')
    spec = importlib.util.spec_from_file_location(
        '_dan_work_locks', Path(__file__).resolve().parents[1] / 'app' / 'services' / 'work_locks.py')
    locks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(locks)
    key = locks.file_key(path, os.environ.get('DAN_WORK_DIR', ''))
    owner = locks.current_owner()
    if not key or not owner:
        return
    waited = []

    def on_wait(record):
        waited.append(record)
        locks.note_waiting(owner, record)
    other = locks.acquire(key, owner, locks.current_title(), on_wait=on_wait, limit=locks.wait_limit(owner))
    locks.clear_waiting(owner)
    if other:
        reason = (f'{locks.label(key)} は{locks.waiting_text(other)}で、まだ使われています。'
                  'この変更は今は行わず、ほかの部分を先に進めてから、あとでもう一度試してください。'
                  'それでも空かなければ、報告でその旨を伝えてください。')
    elif waited:
        # The other work changed the file while this change waited: it was prepared on what the file used to be
        # (2026-10-08 test: an append written after the wait landed in the middle). Now it is this work's turn.
        reason = locks.changed_while_waiting(key, waited[0])
    else:
        return
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                             'permissionDecisionReason': reason}}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:  # a broken lock must never stop Dan's work
        print(f'work_lock_hook: {exc}', file=sys.stderr)
