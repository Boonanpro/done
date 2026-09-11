import asyncio,json
from app.services import timeline_draft as td,editor_job_updates as updates,editor_activity as activity
from app.api import editor_assistant_routes as api
from tests.test_editor_assistant_routes import project

def test_update_reaches_running_job_even_without_new_selection(project,monkeypatch):
    from app.services import timeline_agent
    monkeypatch.setattr(timeline_agent,'content_busy',lambda _: 'active-job')
    begun=api.begin(None,api.Context(room_id='room',content_id=project,input_mode='voice',utterance='HeyGenで声を作って'))
    result=asyncio.run(api.tool(None,api.ToolRequest(room_id='room',turn_id=begun['turn_id'],name='delegate_edit',args={'instruction':'背景4つ全部を動画化'})))
    assert result['job_id']=='active-job' and result['state']=='instruction_pending'
    rows=updates.pending('room','active-job')
    assert 'HeyGen' in rows[0]['instruction'] and '4つ全部' in rows[0]['instruction']
    assert updates.receive('room','active-job')==rows
    assert updates.pending('room','active-job')==[]

def test_failed_worker_cannot_leave_animated_running_operations(tmp_path,monkeypatch):
    monkeypatch.setattr(td,'UPLOAD_ROOT',tmp_path)
    op=activity.start('r','j','generate_video',{'model':'gemini_omni','clip_ids':['a']})
    assert activity.read('r','j','running')[0]['state']=='running'
    assert activity.read('r','j','failed')[0]['state']=='interrupted'
    activity.finish(op,True,'invalid media')
    row=activity.read('r','j','running')[0]
    assert row['state']=='failed' and row['error']=='invalid media'

def test_timeout_continues_same_saved_draft_without_repeating_completed_work(project,monkeypatch):
    from app.services import timeline_agent as agent
    attempts=[]
    def session(room,user,cid,job,draft,instruction,annotations,selection,emit,model):
        attempts.append(draft['draft_id'])
        if len(attempts)==1:
            draft['checkpoint_test']='generated asset ready';td.save_draft(draft)
            return {'ok':False,'retryable':True,'summary':'生成済みの素材を配置するだけです。'}
        assert draft['checkpoint_test']=='generated asset ready'
        assert '生成済み' in instruction
        return {'ok':True,'committed':False,'draft_id':draft['draft_id']}
    monkeypatch.setattr(agent,'_run_session',session)
    result=agent.run_timeline_agent(room_id='room',user_id='owner',content_id=project,job_id='j',instruction='背景4つ全部',model='fable')
    assert result['ok'] and len(attempts)==2 and attempts[0]==attempts[1]

def test_explicit_resume_reuses_checkpoint_and_keeps_original_validation_baseline(project,monkeypatch):
    from app.services import timeline_agent as agent
    draft=td.create_draft('room',project,'old')
    draft['baseline_problems']=['original'];draft['checkpoint']='keep';td.save_draft(draft)
    def session(*args):
        d=args[4]
        assert d['checkpoint']=='keep' and d['baseline_problems']==['original']
        assert d['job_id']=='new'
        return {'ok':True,'committed':False}
    monkeypatch.setattr(agent,'_run_session',session)
    assert agent.run_timeline_agent(room_id='room',user_id='owner',content_id=project,job_id='new',instruction='続けて',model='fable',resume_draft_id=draft['draft_id'])['ok']

def test_pending_instruction_is_read_before_next_generation(project,monkeypatch):
    import app.timeline_mcp_server as m
    draft=td.create_draft('room',project,'j')
    monkeypatch.setattr(m,'ROOM_ID','room');monkeypatch.setattr(m,'JOB_ID','j');monkeypatch.setattr(m,'DRAFT_ID',draft['draft_id'])
    called=[]
    async def dispatch(name,args):called.append(name);return m._ok({'ok':True})
    monkeypatch.setattr(m,'_dispatch',dispatch)
    updates.submit('room','j','HeyGenを使う。Qwenで代替しない。')
    reply=json.loads(asyncio.run(m.call_tool('generate_speech',{'text':'test'}))[0].text)
    assert reply['instruction_updated'] and not called
    assert 'HeyGen' in reply['updates'][0]['instruction']
    asyncio.run(m.call_tool('list_assets',{}))
    assert called==['list_assets']

def test_service_preparation_accepts_no_clip_selection(project,monkeypatch):
    from app.api import production_asset_routes as production
    recorded=[]
    async def create(req,bg,user):
        recorded.append(req.instruction)
        return {'id':'prepare-job'}
    monkeypatch.setattr(production,'create_job',create)
    b=api.begin(None,api.Context(room_id='room',content_id=project,input_mode='voice',utterance='HeyGenの接続から進めて'))
    result=asyncio.run(api.tool(None,api.ToolRequest(room_id='room',turn_id=b['turn_id'],name='delegate_edit',args={'task_kind':'prepare','instruction':'接続状況を調べて準備して'})))
    assert result['ok'] and recorded[0]['preparation_only']
    assert recorded[0]['selected_clips']==[] and recorded[0]['editor_expected_hash'] is None
    assert 'HeyGen' in recorded[0]['revision_text']

def test_preparation_draft_preserves_video_scope(project,monkeypatch):
    from app.services import timeline_agent as agent
    def session(*args):
        assert args[4]['edit_scope']=={'clip_ids':[],'spans':[]}
        assert '準備' in args[5]
        return {'ok':True,'committed':False}
    monkeypatch.setattr(agent,'_run_session',session)
    assert agent.run_timeline_agent(room_id='room',user_id='owner',content_id=project,job_id='prep',instruction='接続',preparation_only=True)['ok']
