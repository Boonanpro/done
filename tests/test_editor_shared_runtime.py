import asyncio,json
from app.agent import cli_runner
from app.services import editor_runtime,editor_questions,timeline_draft as td
from app.services import editor_production_session

def test_editor_session_is_persistent_and_does_not_use_chat_session(tmp_path,monkeypatch):
    monkeypatch.setattr(cli_runner,'PROJECT_ROOT',tmp_path)
    name=editor_runtime.session_room('room','content')
    cli_runner._cli_sessions['room']='chat-session'
    cli_runner._save_session(name,'codex:editor-session')
    cli_runner._cli_sessions.pop(name)
    assert cli_runner._load_session(name)=='codex:editor-session'
    cli_runner._clear_cli_session(name)
    assert cli_runner._load_session(name) is None
    assert cli_runner._cli_sessions['room']=='chat-session'

def test_shared_runtime_uses_normal_prompt_tools_but_not_chat_history(monkeypatch):
    calls=[]
    monkeypatch.setattr(cli_runner,'_build_system_prompt',lambda *a,**kw:'normal-prompt')
    async def process(room,content,job,prompt,system,path,model,emit):
        calls.append(dict(room=room,content=content,prompt=prompt,system=system,path=path))
        return {'text':'done','is_error':False}
    monkeypatch.setattr(editor_production_session,'run',process)
    r=editor_runtime.run('room','user','content','job','request','mcp.json',lambda _:None,'gpt-6-astra')
    assert r['text']=='done'
    c=calls[0]
    assert c['system'].startswith('normal-prompt')
    assert c['path']=='mcp.json' and c['content']=='content'
    assert 'chat-session' not in c['prompt']

def test_question_waits_and_resumes_with_same_answer(tmp_path,monkeypatch):
    monkeypatch.setattr(td,'UPLOAD_ROOT',tmp_path)
    async def scenario():
        task=asyncio.create_task(editor_questions.ask('room','job','どちら？'))
        await asyncio.sleep(.01)
        q=editor_questions.read('room','job')
        assert q and not task.done()
        editor_questions.answer('room','job',q['id'],'右')
        assert editor_questions.read('room','job') is None
        assert (await task)['answer']=='右'
    asyncio.run(scenario())


def test_external_activity_stays_running_until_actual_completion(tmp_path,monkeypatch):
    from app.services import editor_activity
    monkeypatch.setattr(td,'UPLOAD_ROOT',tmp_path)
    monkeypatch.setattr(cli_runner,'_build_system_prompt',lambda *a,**kw:'normal-prompt')
    async def process(room,content,job,prompt,system,path,model,emit):
        emit({'type':'tool_progress','id':'file','name':'Write','input':{},'state':'running'})
        assert editor_activity.read('room','job','running')[0]['state']=='running'
        emit({'type':'tool_progress','id':'file','name':'Write','input':{},'state':'done'})
        assert editor_activity.read('room','job','running')[0]['state']=='done'
        return {'text':'done','is_error':False}
    monkeypatch.setattr(editor_production_session,'run',process)
    editor_runtime.run('room','user','content','job','request','mcp.json',lambda _:None,'gpt-6-astra')
