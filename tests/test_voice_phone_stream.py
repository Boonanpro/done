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
