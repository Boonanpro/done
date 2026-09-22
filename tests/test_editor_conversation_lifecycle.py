import json
from app.services.editor_conversation_lifecycle import purge


def test_delete_removes_only_owned_turns_and_events(tmp_path):
    folder=tmp_path/'assistant';(folder/'events').mkdir(parents=True)
    for cid in ['deleted','kept']:
        (folder/f'{cid}.json').write_text(json.dumps({'context':{'content_id':cid}}))
    mixed=folder/'events'/'mixed.jsonl'
    mixed.write_text('\n'.join(json.dumps({'content_id':c,'text':c}) for c in ['deleted','kept'])+'\n')
    only=folder/'events'/'only.jsonl'
    only.write_text(json.dumps({'content_id':'deleted'})+'\n')
    (folder/'unrelated.json').write_text('{}')
    purge(tmp_path,'deleted')
    assert not (folder/'deleted.json').exists()
    assert (folder/'kept.json').exists()
    assert (folder/'unrelated.json').exists()
    assert not only.exists()
    assert json.loads(mixed.read_text())['content_id']=='kept'
