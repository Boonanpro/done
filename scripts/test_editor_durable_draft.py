"""New project -> remembered brief -> delegated editable draft (no paid media generation)."""
import json
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
room = 'editor-durable-draft-' + uuid.uuid4().hex[:8]
folder = ROOT / 'uploads/production-assets' / room
folder.mkdir(parents=True)
(folder / 'contents.json').write_text('[]', encoding='utf-8')
(folder / 'assets.json').write_text('[]', encoding='utf-8')
token = (Path.home() / '.done/native_token.txt').read_text().strip()
base = 'http://127.0.0.1:8022/api/v1'
with httpx.Client(headers={'Authorization': 'Bearer '+token}, timeout=30) as client:
    def post(path, value):
        r = client.post(base+'/editor-assistant/'+path, json=value)
        r.raise_for_status()
        return r.json()
    new = post('new', {'room_id': room})
    listing = client.get(base+'/production-assets/contents', params={'room_id': room})
    listing.raise_for_status()
    cid = new['content_id']
    turn = post('begin', {'room_id': room, 'content_id': cid, 'scope_mode': 'whole'})
    def tool(name, args):
        return post('tool', {'room_id': room, 'turn_id': turn['turn_id'], 'name': name, 'args': args})
    assert tool('save_brief', {'intent': '修理の問い合わせで必要な情報を先に揃えると、一度の連絡で話が進むことを伝える', 'taste': '簡潔な白い文字と黒い背景'})['ok']
    job = tool('delegate_edit', {'instruction': '隔離された制作経路のテストです。6秒の編集可能な下書きを作ってください。前半は文字「情報が足りないと、何度も確認」、後半は「五つの情報で、一度で伝わる」を字幕クリップで見せ、登録済みownerの無料Qwen音声で後半の一文だけ話す音声クリップを配置してください。図形を使うなら別クリップにしてください。字幕と声の一致とプレビューを確認してください。生成動画、画像生成、外部検索は不要。このテストはユーザーの本編完成や作品品質の合格を意味しません。'})
    assert job.get('job_id'), job
    print('job', job['job_id'], 'room', room, flush=True)
    deadline = time.monotonic() + 420
    while time.monotonic() < deadline:
        jobs = client.get(base+'/production-assets/jobs', params={'room_id': room}).json()
        status = next(j for j in jobs if j['id'] == job['job_id'])
        if status['status'] in {'done', 'failed'}:
            print('status', status['status'], 'error', status.get('error'), flush=True)
            break
        time.sleep(2)
    else:
        client.post(base+'/production-assets/jobs/'+job['job_id']+'/cancel', params={'room_id': room})
        raise SystemExit('creation test timed out')
    doc = json.loads((folder/'contents.json').read_text(encoding='utf-8'))[0]
    texts = [c.get('text') for t in doc['timeline']['sequence']['tracks'] for c in t['clips']]
    assert status['status'] == 'done' and any('五つ' in str(t) for t in texts), (status.get('error'), texts)
    assert doc['creative_brief']['taste'] == '簡潔な白い文字と黒い背景'
    print('editable_draft_and_brief', True)
