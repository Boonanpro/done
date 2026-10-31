from types import SimpleNamespace
import pytest
from app.services import voice_phone_stream as P

@pytest.mark.asyncio
async def test_capture_bound_to_exact_serial_and_stops_only_own_worker(tmp_path,monkeypatch):
    monkeypatch.setenv('DAN_TOOL_HOST','1');monkeypatch.setenv('DAN_SESSION_ID','room')
    monkeypatch.setattr(P,'_stream',None)
    monkeypatch.setattr(P.shutil,'which',lambda n:'/bin/'+n)
    monkeypatch.setattr(P,'frame_path',lambda room,key:tmp_path/(key+'.jpg'))
    processes=[]
    class Process:
        def __init__(self,args,**kw):self.args=args;self.stopped=False;processes.append(self)
        def poll(self):return 0 if self.stopped else None
        def terminate(self):self.stopped=True
    monkeypatch.setattr(P.subprocess,'Popen',Process)
    assert await P.follow('device-one') == ''
    path=P.frame_path('room',P._stream['key']);path.write_bytes(b'image')
    assert (await P.follow('device-one')).endswith('.mjpeg')
    assert len(processes)==1
    await P.follow('device-two')
    assert processes[0].stopped and not processes[1].stopped
    assert processes[0].args[4]=='device-one'
    assert processes[1].args[4]=='device-two'

@pytest.mark.asyncio
async def test_non_voice_host_never_starts_recording(monkeypatch):
    monkeypatch.delenv('DAN_TOOL_HOST',raising=False)
    monkeypatch.setattr(P.subprocess,'Popen',lambda *a,**k:pytest.fail('unexpected capture'))
    assert await P.follow('device') == ''

@pytest.mark.parametrize('ending', ['parent_exit', 'viewer_expired', 'decoder_exit'])
def test_capture_failure_cleans_only_owned_children_and_frames(tmp_path, monkeypatch, ending):
    import io
    path = tmp_path/'stream.jpg'
    path.write_bytes(b'old')
    monkeypatch.setattr(P, 'frame_path', lambda *a: path)
    monkeypatch.setattr(P.shutil, 'which', lambda n: '/bin/'+n)
    monkeypatch.setattr(P, 'write_frame', lambda *a: path.write_bytes(a[-1]))
    monkeypatch.setattr(P.time, 'time', lambda: 100)
    if ending == 'viewer_expired':
        lease=path.with_suffix('.watch');lease.touch()
        P.os.utime(lease,(1,1))
    def alive(*args):
        if ending == 'parent_exit': raise ProcessLookupError()
    monkeypatch.setattr(P.os, 'kill', alive)
    children=[]
    class Child:
        def __init__(self, *args, **kwargs):
            self.stdout=io.BytesIO();self.stopped=False;children.append(self)
        def poll(self): return 0 if self.stopped or (ending=='decoder_exit' and self is children[-1] and len(children)==2) else None
        def terminate(self): self.stopped=True
        def wait(self, **kw): return 0
    monkeypatch.setattr(P.subprocess, 'Popen', Child)
    monkeypatch.setattr(P.subprocess, 'run', lambda *a,**kw: SimpleNamespace(returncode=0,stdout=b'actual-image'))
    class Selector:
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def register(self,*a): pass
        def select(self,**kw): return []
    monkeypatch.setattr(P.selectors,'DefaultSelector',Selector)
    import signal
    previous=signal.getsignal(signal.SIGTERM)
    try: P.capture('room','exact-device','key',123)
    finally: signal.signal(signal.SIGTERM,previous)
    assert len(children)==2  # failed encoders are never restarted
    assert children[0].stopped
    assert children[1].poll() is not None
    assert not path.exists() and not path.with_suffix('.watch').exists()
