"""Record a room-scoped work checkpoint using JSON on stdin (never shell-interpolate content)."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import work_continuity as work


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--room', required=True)
    args = parser.parse_args()
    if os.environ.get('DAN_ROOM_ID') and os.environ['DAN_ROOM_ID'] != args.room:
        raise ValueError('another room cannot be changed')
    data = json.load(sys.stdin)
    if data.get('action') == 'list':
        return work.room_work(args.room)
    if data.get('action') == 'create':
        for field in ('goal','authority','criteria','next_step','evidence'):
            if not isinstance(data.get(field), str) or not data[field].strip():
                raise ValueError(field + ' is required')
        if data.get('status', 'ready') not in {'ready','waiting','blocked'}:
            raise ValueError('invalid initial state')
        from app.services.owner import resolve_owner_user_id
        key = work.key_for('commitment', args.room, data['goal'])
        work.enqueue(key=key, room_id=args.room, user_id=resolve_owner_user_id(),
                     source='commitment', prompt=data['goal'], goal=data['goal'],
                     authority=data['authority'], criteria=data['criteria'],
                     status=data.get('status','ready'), evidence=data['evidence'],
                     next_step=data['next_step'], wake_at=float(data.get('wake_at',0)))
        return {'id':key, 'status':work.get(key)['status']}
    elif data.get('action') == 'checkpoint':
        key = data['id']
    else:
        raise ValueError('unknown action')
    work.checkpoint(key, args.room, status=data.get('status','ready'), evidence=data['evidence'],
                    next_step=data.get('next_step',''), wake_at=data.get('wake_at',0), token=data.get('token'))
    return {'id':key, 'status':work.get(key)['status']}


if __name__ == '__main__':
    print(json.dumps(main(), ensure_ascii=False))
