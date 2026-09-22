"""Exercise the real selected editing model on an isolated, protected timeline."""
import argparse
import copy
import json
import uuid

from app.services import timeline_draft as td
from app.services.timeline_agent import run_timeline_agent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='gpt-6-astra')
    args = parser.parse_args()
    room = 'assistant-model-test-' + uuid.uuid4().hex[:8]
    cid = str(uuid.uuid4())
    folder = td._room_dir(room)
    folder.mkdir(parents=True, exist_ok=True)
    source = td._read_contents_raw('a3970e0b-f7dc-472e-ad63-e8c51382ddb3')[0]
    content = copy.deepcopy(source)
    content['id'] = cid
    seq = td._content_sequence(content)
    seq['duration'] = 6
    seq['tracks'] = [{'id': 'v1', 'type': 'video', 'clips': [
        {'id': 'target', 'text': '直す字幕', 'timeline_start': 0, 'timeline_end': 3},
        {'id': 'protected', 'text': '変更しない字幕', 'timeline_start': 3, 'timeline_end': 6, 'approved': True},
    ]}]
    original = copy.deepcopy(seq['tracks'][0]['clips'][1])
    (folder / 'contents.json').write_text(json.dumps([content], ensure_ascii=False), encoding='utf-8')
    (folder / 'assets.json').write_text('[]', encoding='utf-8')
    result = run_timeline_agent(room_id=room, user_id='editor-model-test', content_id=cid,
        job_id=uuid.uuid4().hex, model=args.model, expected_hash=td.sequence_hash(seq),
        selected_clips=[seq['tracks'][0]['clips'][0]],
        instruction='targetの字幕を「モデル切替テスト」に変更してください。他は変更しない。素材生成も描画も不要。set_clipとvalidate_draftを使って終了してください。',
        on_event=lambda event: print(json.dumps(event, ensure_ascii=False), flush=True))
    print(json.dumps({'room': room, 'model': args.model, 'result': result}, ensure_ascii=False), flush=True)
    assert result['committed'], result
    clips = td._content_sequence(td._read_contents_raw(room)[0])['tracks'][0]['clips']
    assert clips[0]['text'] == 'モデル切替テスト'
    assert clips[1] == original
    print('selected_edit_and_approved_neighbor_preserved', flush=True)


if __name__ == '__main__':
    main()
