import json
from app.services import editor_project as p, timeline_draft as td


def test_dialogue_preserves_roles_scope_and_older_pages(tmp_path,monkeypatch):
    monkeypatch.setattr(td,'UPLOAD_ROOT',tmp_path)
    folder=tmp_path/'r'/'assistant';(folder/'events').mkdir(parents=True)
    (folder/'t.json').write_text(json.dumps({'created_at':2,'context':{'content_id':'c','utterance':'それで','playhead':4}}))
    events=[{'at':1,'type':'assistant_transcript','turn_id':'t','text':'Google直結で短い見本を作りますか？'},
            {'at':2,'type':'user_transcript','turn_id':'t','text':'それで'},
            {'at':3,'type':'assistant_transcript','content_id':'other','text':'別の作品'},
            {'at':4,'type':'assistant_transcript','content_id':'c','text':'作成します'}]
    (folder/'events'/'s.jsonl').write_text('\n'.join(json.dumps(e) for e in events)+'\n{',encoding='utf-8')
    result=p.dialogue('r','c',2)
    assert [m['role'] for m in result['messages']]==['user','assistant']
    assert len(result['messages'])==2
    older=p.dialogue('r','c',2,result['before'])
    assert older['messages'][0]['role']=='assistant'
    assert older['before'] is None


def test_runtime_and_voice_share_budget_without_fixed_ban(monkeypatch):
    from app.services import editor_runtime,editor_conversation
    from app.services.editor_production_contract import BUDGET
    from app.agent import cli_runner
    captured=[]
    monkeypatch.setattr(cli_runner,'_build_system_prompt',lambda *a,**k:'normal')
    async def run(**kwargs):
        captured.append(kwargs)
        yield {'type':'result','text':'ok'}
    monkeypatch.setattr(cli_runner,'process_message_cli',run)
    editor_runtime.run('none','u','c','j','instruction','mcp',lambda e:None,'gpt-6-astra')
    assert BUDGET in captured[0]['system_prompt'] and BUDGET in editor_conversation.INSTRUCTIONS
    assert '有料の動画生成や有料音声生成は現在使わない' not in captured[0]['system_prompt']


def test_reasoning_reply_is_available_before_browser_audit_arrives(tmp_path,monkeypatch):
    monkeypatch.setattr(td,'UPLOAD_ROOT',tmp_path)
    folder=tmp_path/'r'/'assistant';folder.mkdir(parents=True)
    (folder/'t.json').write_text(json.dumps({'created_at':1,'context':{'content_id':'c','utterance':'見本を考えて'},
        'reasoning':{'reply_text':'人物の表情と料理を組み合わせる案はどうですか？','reply_at':2}}),encoding='utf-8')
    rows=p.dialogue('r','c')['messages']
    assert [r['role'] for r in rows]==['user','assistant']
    (folder/'events').mkdir()
    (folder/'events'/'s.jsonl').write_text(json.dumps({'at':2,'type':'assistant_transcript','turn_id':'t','text':rows[-1]['text']})+'\n',encoding='utf-8')
    assert len(p.dialogue('r','c')['messages'])==2
