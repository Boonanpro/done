"""Kill a disposable parent with the same tree-kill routine used by core restart."""
import json,subprocess,sys,time,uuid
from pathlib import Path
from app.services import timeline_draft as td
from app.core.sandbox_manager import SandboxManager

room='worker-restart-test-'+uuid.uuid4().hex[:8];folder=td._room_dir(room);folder.mkdir(parents=True)
(folder/'contents.json').write_text(json.dumps([{'id':'c','status':'ready','timeline':{'sequence':{'duration':1,'format':'16:9','tracks':[]}}}]))
(folder/'assets.json').write_text('[]')
(folder/'jobs.json').write_text(json.dumps([{'id':'j','content_id':'c','status':'queued','instruction':{'mode':'handoff_test'}}]))
script=folder/'parent.py';script.write_text('''import sys,time
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from app.services.production_worker import launch
room=sys.argv[1]
launch(room,'j','c',{'mode':'handoff_test'},'fixture')
Path(sys.argv[2]).touch()
time.sleep(60)
''')
ready=folder/'parent-ready'
parent=subprocess.Popen([sys.executable,str(script),room,str(ready)],stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
try:
    deadline=time.monotonic()+20
    while not ready.exists() and time.monotonic()<deadline:
        assert parent.poll() is None,parent.stderr.read().decode(errors='replace')
        time.sleep(.1)
    assert ready.exists()
    from app.services.production_worker import alive
    job=json.loads((folder/'jobs.json').read_text())[0]
    assert alive(job) and job['status']=='queued'
    SandboxManager._kill_tree(parent.pid)
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        job=json.loads((folder/'jobs.json').read_text(encoding='utf-8'))[0]
        if job['status'] in ('done','failed'):break
        time.sleep(.25)
    assert job['status']=='done',job
    print('PASS production worker survived parent tree shutdown and completed',room)
finally:
    if parent.poll() is None:parent.kill()
