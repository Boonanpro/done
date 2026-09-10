import json
import wave

from app.services import timeline_speech as speech, cloud_speech


def configure(tmp_path, monkeypatch):
    monkeypatch.setattr(speech, 'ROOT', tmp_path)
    monkeypatch.setattr(speech, 'VOICE_ROOT', tmp_path/'voice')
    monkeypatch.setattr(speech, 'VENV_PY', tmp_path/'no-local-python')
    profile = tmp_path/'voice/owner';profile.mkdir(parents=True)
    (profile/'profile.json').write_text(json.dumps({'ref_audio':'ref.wav'}))
    (profile/'ref.wav').write_bytes(b'test reference')
    monkeypatch.setattr(cloud_speech, 'settings', lambda: {'enabled':True})


def test_cloud_result_is_cached_and_returned_as_local_asset(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    calls = []
    def remote(config, profile, lines, out_dir, timeout):
        calls.append(lines)
        dest=out_dir/'line.wav'
        with wave.open(str(dest),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(b'\0\0'*2400)
        return {'ok':True,'files':{'line':{'path':str(dest),'duration':.1,'spoken':lines['line']}},'backend':'cloud'}
    monkeypatch.setattr(cloud_speech,'synthesize',remote)
    result=speech.synthesize_many({'line':'hello'},tmp_path/'first')
    assert result['ok'] and result['backend']=='cloud'
    again=speech.synthesize_many({'line':'hello'},tmp_path/'second')
    assert again['cached'] and len(calls)==1
    assert (tmp_path/'second/line.wav').exists()


def test_cloud_error_does_not_silently_start_local_generation(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    def unavailable(*args):raise TimeoutError('connection failed')
    monkeypatch.setattr(cloud_speech,'synthesize',unavailable)
    result=speech.synthesize_many({'line':'hello'},tmp_path/'out')
    assert not result['ok'] and result['backend']=='cloud'
    assert 'connection failed' in result['error']
