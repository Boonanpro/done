import threading, time
from app.api import production_asset_routes as par
def test_one_run_at_a_time(monkeypatch):
    running=[0]; peak=[0]
    def fake(room, ids):
        running[0]+=1; peak[0]=max(peak[0],running[0]); time.sleep(0.2); running[0]-=1; return {}
    monkeypatch.setattr(par,'_ensure_audio_analysis_locked',fake)
    ts=[threading.Thread(target=par._ensure_audio_analysis,args=('r1',['a'])) for _ in range(6)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert peak[0]==1
