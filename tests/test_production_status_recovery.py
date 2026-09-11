from app.api import production_asset_routes as api


def test_recovery_does_not_fail_a_live_worker(tmp_path,monkeypatch):
    import json,os,psutil
    room=tmp_path/'room';room.mkdir()
    jobs=[{'id':'active','status':'running','worker_pid':os.getpid(),'worker_started_at':psutil.Process().create_time()},
          {'id':'dead','status':'running','worker_pid':os.getpid(),'worker_started_at':0}]
    (room/'jobs.json').write_text(json.dumps(jobs),encoding='utf-8')
    monkeypatch.setattr(api,'ASSET_ROOT',tmp_path)
    monkeypatch.setattr(api,'_repair_terminal_content_status',lambda *_:None)
    api._recover_stale_running_jobs()
    result=json.loads((room/'jobs.json').read_text(encoding='utf-8'))
    assert result[0]['status']=='running'
    assert result[1]['status']=='failed'


def test_terminal_job_unlocks_document_without_changing_timeline(monkeypatch):
    content = {'id': 'video', 'status': 'running', 'timeline': {'sequence': {'duration': 3}}}
    monkeypatch.setattr(api, '_read_contents', lambda _: [content])
    updates = []
    monkeypatch.setattr(api, '_update_content', lambda room, cid, patch: updates.append((cid, patch)))
    api._repair_terminal_content_status('room', [{'content_id': 'video', 'status': 'failed'}])
    assert updates == [('video', {'status': 'failed'})]
    assert content['timeline'] == {'sequence': {'duration': 3}}
    updates.clear()
    api._repair_terminal_content_status('room', [
        {'content_id': 'video', 'status': 'failed'}, {'content_id': 'video', 'status': 'running'}])
    assert updates == []


def test_independent_worker_resumes_checkpoint_without_overwriting_live_worker(tmp_path, monkeypatch):
    import json
    from app.services import timeline_draft as td, production_worker as worker
    room=tmp_path/'room';room.mkdir();(room/'drafts').mkdir()
    jobs=[{'id':'j','content_id':'c','status':'running','execution':'independent','user_id':'owner','draft_id':'saved','instruction':{}}]
    (room/'jobs.json').write_text(json.dumps(jobs))
    (room/'drafts/saved.json').write_text(json.dumps({'draft_id':'saved'}))
    monkeypatch.setattr(api,'ASSET_ROOT',tmp_path);monkeypatch.setattr(td,'UPLOAD_ROOT',tmp_path)
    monkeypatch.setattr(api,'_repair_terminal_content_status',lambda *_:None)
    launches=[];monkeypatch.setattr(worker,'launch',lambda *args:launches.append(args))
    api._recover_stale_running_jobs()
    assert launches[0][3]['resume_draft_id']=='saved'
    assert api._read_jobs('room')[0]['recovery_attempts']==1
    pending=api._read_jobs('room');pending[0]['worker_started_at']=0
    (room/'jobs.json').write_text(json.dumps(pending))
    (room/'drafts/saved.json').write_text(json.dumps({'draft_id':'saved','committed_at':123}))
    api._recover_stale_running_jobs()
    assert len(launches)==1 and api._read_jobs('room')[0]['status']=='done'
