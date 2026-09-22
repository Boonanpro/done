"""Real CLI + timeline MCP; isolated project, no media generation."""
import asyncio
import json
import time
import uuid
import sys
from pathlib import Path
from app.services import timeline_draft as td, editor_production_session as session, editor_job_updates


async def main():
    room = 'production-stream-test-' + uuid.uuid4().hex[:8]
    folder = td._room_dir(room)
    folder.mkdir(parents=True)
    seq = {'duration': 8, 'format': '16:9', 'frame_rate': 30,
           'tracks': [{'id': 'v', 'type': 'video', 'clips': []}]}
    (folder / 'contents.json').write_text(json.dumps([{'id': 'test', 'timeline': {'sequence': seq}}]))
    (folder / 'assets.json').write_text('[]')
    job = 'stream-test'
    draft = td.create_draft(room, 'test', job_id=job)
    draft['live_updates'] = True
    td.save_draft(draft)
    jobdir = folder / 'jobs' / job
    jobdir.mkdir(parents=True)
    config = jobdir / 'mcp.json'
    config.write_text(json.dumps({'mcpServers': {'timeline': {
        'command': 'python', 'args': [str(Path.cwd() / 'app/timeline_mcp_server.py')],
        'env': {'DAN_ROOM_ID': room, 'DAN_DRAFT_ID': draft['draft_id'],
                'DAN_JOB_ID': job, 'DAN_CONTENT_ID': 'test', 'PYTHONIOENCODING': 'utf-8'}}}}))
    started = time.monotonic()
    sent = False
    observations = []
    def emit(event):
        nonlocal sent
        live = td._content_sequence(td._read_contents_raw(room)[0])
        clips = [c for t in live['tracks'] for c in t.get('clips', [])]
        row = {'elapsed': round(time.monotonic()-started, 3), **event}
        with (jobdir / 'acceptance.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False)+'\n')
        if clips and not sent:
            sent = True
            observations.append({'first_visible_seconds': row['elapsed'], 'first_clip': clips[0]})
            editor_job_updates.submit(room, job,
                '追加指示です。最初の字幕は残してください。2つ目の字幕の文言を「変更が届いた」にして4〜8秒に追加してください。最初の字幕の変更や全削除はしないでください。')
        if event['type'] in ('instruction_received', 'text'):
            print(row['elapsed'], event['type'], event.get('latency_ms', ''), event.get('text','')[:120], flush=True)
    prompt = 'タイムラインに字幕「最初の場面」を0〜4秒に追加して反映してください。その後シェルで5秒待ち、2つ目の字幕「次の場面」を4〜8秒に追加してください。既存の素材は不要です。最後に結果を報告してください。'
    if '--runtime' in sys.argv:
        from app.services import editor_runtime
        operation = asyncio.to_thread(editor_runtime.run,room,'test','test',job,prompt,config,emit,'gpt-6-astra')
    else:
        operation = session.run(room, 'test', job, prompt,
        'これは隔離した編集テストです。timelineの道具で依頼を実行してください。追加指示を優先。ファイルの直接編集・生成・検索は不要です。',
        config, 'gpt-6-astra', emit)
    result = await asyncio.wait_for(operation, timeout=180)
    live = td._content_sequence(td._read_contents_raw(room)[0])
    clips = [c for t in live['tracks'] for c in t.get('clips', [])]
    assert not result['is_error'], result
    assert [c['text'] for c in sorted(clips, key=lambda c:c['timeline_start'])] == ['最初の場面','変更が届いた'], clips
    assert next(c for c in clips if c['text']=='最初の場面') == observations[0]['first_clip']
    print(json.dumps({'room': room, 'observations': observations, 'total_seconds': time.monotonic()-started}, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
