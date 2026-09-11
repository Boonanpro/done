import os,time
import pytest
from app.services.gpu_lock import GpuLock

def test_live_gpu_owner_is_not_displaced_by_elapsed_time(tmp_path):
    path=tmp_path/'gpu';path.write_text(str(os.getpid())+' active')
    os.utime(path,(1,1))
    with pytest.raises(TimeoutError):
        with GpuLock(path=path,timeout=0,stale_s=1):pass
    assert path.exists()

def test_dead_gpu_owner_does_not_make_next_job_wait(tmp_path,monkeypatch):
    import psutil
    path=tmp_path/'gpu';path.write_text('123 dead')
    monkeypatch.setattr(psutil,'pid_exists',lambda _:False)
    with GpuLock(path=path,timeout=0):assert path.exists()
    assert not path.exists()
