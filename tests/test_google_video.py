import base64
import json
from types import SimpleNamespace
import pytest
from app.services import google_video as gv
from app.config import settings


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(settings,'GOOGLE_GEMINI_API_KEY','test-key')
    monkeypatch.setattr(gv,'probe',lambda p:{'duration':3.,'width':1280,'height':720})
    calls=[]
    def post(url,**kwargs):
        calls.append((url,kwargs))
        data={'steps':[{'type':'model_output','content':[{'type':'video','data':base64.b64encode(b'video').decode()}]}],'usage':{'total_tokens':100}}
        return SimpleNamespace(status_code=200,raise_for_status=lambda:None,json=lambda:data)
    monkeypatch.setattr(gv.httpx,'post',post)
    return calls


def test_style_edit_and_reuse(tmp_path,provider):
    source=tmp_path/'source.mp4';source.write_bytes(b'reference')
    a=gv.generate(tmp_path,'new subject',reference_path=str(source),reference_mode='style')
    again=gv.generate(tmp_path,'new subject',reference_path=str(source),reference_mode='style')
    assert again['reused'] and a['path']==again['path'] and len(provider)==1
    gv.generate(tmp_path,'fix subject',reference_path=str(source),reference_mode='edit')
    assert '[# References <VIDEO_REF_0>' in provider[0][1]['json']['input'][-1]['text']
    assert '[# Sources <VIDEO_0>' in provider[1][1]['json']['input'][-1]['text']
    receipt=json.loads(__import__('pathlib').Path(a['metadata']['receipt']).read_text())
    assert receipt['response']['steps'][0]['content'][0]['data']=='[media omitted]'


def test_timeout_does_not_repeat_paid_request(tmp_path,provider,monkeypatch):
    def timeout(*a,**k):
        raise TimeoutError('unknown result')
    monkeypatch.setattr(gv.httpx,'post',timeout)
    with pytest.raises(TimeoutError):gv.generate(tmp_path,'test')
    with pytest.raises(FileExistsError):gv.generate(tmp_path,'test')


def test_long_style_reference_fails_before_spend(tmp_path,provider,monkeypatch):
    source=tmp_path/'source.mp4';source.write_bytes(b'reference')
    monkeypatch.setattr(gv,'probe',lambda p:{'duration':5})
    with pytest.raises(ValueError,match='3s'):
        gv.generate(tmp_path,'test',reference_path=str(source))
    assert not provider


def test_motion_and_appearance_are_separate_and_both_affect_cache(tmp_path,provider):
    source=tmp_path/'motion.mp4';source.write_bytes(b'motion')
    look=tmp_path/'look.png';look.write_bytes(b'appearance one')
    args=dict(reference_path=str(source),reference_mode='edit',appearance_reference_path=str(look))
    first=gv.generate(tmp_path,'Finish scene',**args)
    inputs=provider[0][1]['json']['input']
    assert [x['type'] for x in inputs]==['video','image','text']
    assert '<VIDEO_0>@Video1' in inputs[-1]['text'] and '<IMAGE_REF_0>@Image1' in inputs[-1]['text']
    assert gv.generate(tmp_path,'Finish scene',**args)['reused']
    look.write_bytes(b'appearance two')
    assert gv.generate(tmp_path,'Finish scene',**args)['path']!=first['path']
    assert len(provider)==2


def test_appearance_requires_video_before_spend(tmp_path,provider):
    look=tmp_path/'look.png';look.write_bytes(b'appearance')
    with pytest.raises(ValueError,match='edit source video'):
        gv.generate(tmp_path,'test',appearance_reference_path=str(look))
    assert not provider
