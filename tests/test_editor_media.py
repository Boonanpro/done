import json,wave
from app.services import editor_media as m,timeline_draft as td


def test_media_intake_probes_and_preserves_source(tmp_path,monkeypatch):
    monkeypatch.setattr(td,'UPLOAD_ROOT',tmp_path/'rooms')
    source=tmp_path/'source.wav'
    with wave.open(str(source),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(bytes(32000))
    before=source.read_bytes()
    result=m.import_media('room',str(source))
    assert result['ok'] and result['metadata']['duration']==1
    assert result['metadata']['has_audio'] and not result['metadata']['has_video']
    rows=json.loads((td._room_dir('room')/'assets.json').read_text())
    assert rows[0]['id']==result['asset_id'] and source.read_bytes()==before
    assert not (td._room_dir('room')/'contents.json').exists()
