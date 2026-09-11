"""Durable editor execution, orphaned from the web server through a short launcher."""
import json,os,subprocess,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def alive(job):
    import psutil
    try:
        if int(job.get('worker_pid') or 0)<=0 or float(job.get('worker_started_at') or 0)<=0:return False
        return abs(psutil.Process(int(job['worker_pid'])).create_time()-float(job['worker_started_at']))<.01
    except (psutil.Error,ValueError,TypeError):return False

def launch(room,job,content,instruction,user):
    from app.api import production_asset_routes as api
    folder=api._room_dir(room)/'jobs'/job;folder.mkdir(parents=True,exist_ok=True)
    request=folder/'worker-request.json'
    request.write_text(json.dumps({'room':room,'job':job,'content':content,'instruction':instruction,'user':user},ensure_ascii=False),encoding='utf-8')
    receipt=folder/'worker-owner.json';receipt.unlink(missing_ok=True)
    result=subprocess.run([sys.executable,'-m','app.services.production_worker','launch',str(request)],cwd=ROOT,
        stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise RuntimeError('制作プロセスを起動できませんでした: '+result.stderr.decode(errors='replace')[-400:])
    owner=json.loads(receipt.read_text(encoding='utf-8'))
    api._update_job(room,job,{**owner,'execution':'independent','user_id':user})
    (folder/'worker-ready').touch()
    return owner

def checkpoint(room,job,draft_id):
    from app.api.production_asset_routes import _update_job
    _update_job(room,job,{'draft_id':draft_id})

def saved_draft(room,job):
    from app.services import timeline_draft as td
    found=job.get('draft_id') or (job.get('result') or {}).get('draft_id')
    if found:return found
    for p in (td._room_dir(room)/'drafts').glob('*.json'):
        try:
            d=json.loads(p.read_text(encoding='utf-8'))
            if d.get('job_id')==job['id'] and not d.get('committed_at'):return d['draft_id']
        except (OSError,ValueError,KeyError):pass

def cancel(job):
    if not alive(job):return False
    import psutil
    process=psutil.Process(job['worker_pid'])
    for child in reversed(process.children(recursive=True)):
        try:child.kill()
        except psutil.Error:pass
    process.kill();return True

def main():
    mode,path=sys.argv[1:3];request=Path(path);folder=request.parent
    if mode=='launch':
        import psutil
        (folder/'worker-ready').unlink(missing_ok=True)
        with (folder/'worker.log').open('ab') as log:
            p=subprocess.Popen([sys.executable,'-m','app.services.production_worker','run',str(request)],cwd=ROOT,
                stdin=subprocess.DEVNULL,stdout=log,stderr=log,close_fds=True,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),start_new_session=os.name!='nt')
        (folder/'worker-owner.json').write_text(json.dumps({'worker_pid':p.pid,'worker_started_at':psutil.Process(p.pid).create_time()}))
        return
    deadline=time.monotonic()+30
    while not (folder/'worker-ready').exists():
        if time.monotonic()>deadline:return
        time.sleep(.1)
    from app.api.production_asset_routes import _run_production_job,_read_jobs
    spec=json.loads(request.read_text(encoding='utf-8'))
    row=next((j for j in _read_jobs(spec['room']) if j['id']==spec['job']),{})
    if row.get('status') not in ('queued','running'):return
    _run_production_job(spec['room'],spec['job'],spec['content'],spec['instruction'],spec['user'])

if __name__=='__main__':main()
