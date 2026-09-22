import json
import pytest
from app.services import editor_component_library as lib
from app.services import editor_reference_library as refs


@pytest.fixture
def source(tmp_path,monkeypatch):
    root=tmp_path/'sources';folder=root/'sample';folder.mkdir(parents=True)
    (folder/'sample.html').write_text('<h1>元の部品</h1>',encoding='utf-8')
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps([{'id':'hf-sample','component':'sample','inspection':'verified','files':[{'file':'sample.html'}]}]),encoding='utf-8')
    monkeypatch.setattr(lib,'MANIFEST',manifest);monkeypatch.setattr(lib,'SOURCES',root)
    return manifest


def test_read_source_preserves_original_and_limits_files(source):
    assert lib.read('hf-sample')['files']==[{'file':'sample.html'}]
    assert lib.read('hf-sample','sample.html')['source']=='<h1>元の部品</h1>'
    for name in ['../secret','C:/secret','.env','sample.html/..']:
        with pytest.raises(ValueError):lib.read('hf-sample',name)
    with pytest.raises(ValueError):lib.read('unknown')


def test_unverified_source_excluded(source):
    rows=json.loads(source.read_text());rows[0]['inspection']='pending';source.write_text(json.dumps(rows))
    with pytest.raises(ValueError):lib.read('hf-sample')


def test_quality_hold_does_not_confuse_playback_with_approval(source):
    result=lib.read('hf-sample')
    assert result['quality_status']=='unreviewed'
    assert result['technical_inspection']=='verified'
    assert not refs.selectable({'quality_status':'quarantined'})
    assert refs.selectable({'quality_status':'reference_approved'})


def test_combined_catalog_preserves_old_entries_and_excludes_missing_media(tmp_path,monkeypatch):
    old=tmp_path/'old.json';new=tmp_path/'new.json'
    old.write_text(json.dumps([{'id':'old','kind':'scene'}]));new.write_text(json.dumps([
        {'id':'hf-a','kind':'video','extension':'.mp4','family':'camera','inspection':'verified'},
        {'id':'hf-b','kind':'video','extension':'.mp4','family':'camera','inspection':'pending'},
        {'id':'hf-missing','kind':'video','extension':'.mp4','family':'camera','inspection':'verified'}]))
    (tmp_path/'hf-a.mp4').write_bytes(b'test');(tmp_path/'hf-b.mp4').write_bytes(b'test')
    monkeypatch.setattr(refs,'CATALOG',old);monkeypatch.setattr(refs,'COMPONENTS',new);monkeypatch.setattr(refs,'MEDIA',tmp_path)
    rows=refs.catalog();assert [r['id'] for r in rows]==['old','hf-a']
    assert rows[1]['family']=='hf-a' and rows[1]['category']=='camera'
