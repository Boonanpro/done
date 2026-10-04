import base64,json
from io import BytesIO
from types import SimpleNamespace
import pytest
from PIL import Image
from app.services import timeline_draft as td,editor_look_frame as look

@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(td,'UPLOAD_ROOT',tmp_path)
    folder=tmp_path/'room';folder.mkdir()
    td._write_contents_raw('room',[{'id':'one','timeline':{'sequence':{'tracks':[]}}},{'id':'two'}])
    from app.config import settings
    monkeypatch.setattr(settings,'OPENAI_API_KEY','test')
    buf=BytesIO();Image.new('RGB',(64,64),'blue').save(buf,format='PNG')
    calls=[]
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def post(self,url,**kwargs):
            calls.append((url,kwargs))
            return SimpleNamespace(status_code=200,raise_for_status=lambda:None,json=lambda:{'data':[{'b64_json':base64.b64encode(buf.getvalue()).decode()}],'usage':{}})
    monkeypatch.setattr(look.httpx,'Client',Client)
    return calls

def test_new_edit_ancestry_and_retry(setup):
    first=look.generate('room','one','A workshop')
    assert first['model']=='gpt-image-2.5-flare'
    again=look.generate('room','one','A workshop')
    assert again['reused'] and len(setup)==1
    assert again['presentation']['items'][0]['id']==first['presentation']['items'][0]['id']
    old=first['presentation']['items'][0]['id']
    revised=look.generate('room','one','Only darken the lighting',revises=old)
    assert revised['model']=='gpt-image-2.5-sunburst'
    assert setup[1][0].endswith('/edits') and len(setup[1][1]['files'])==1
    content=td._find_content(td._read_contents_raw('room'),'one')
    assert len(content['look_frames'])==2
    assert content['look_frames'][1]['reference_asset_ids']==[first['asset_id']]
    assert content['look_frames'][1]['revises']==old
    assert content['timeline']['sequence']['tracks']==[]
    assert 'look_frames' not in td._find_content(td._read_contents_raw('room'),'two')

def test_other_project_reference_and_invalid_model_do_not_spend(setup):
    first=look.generate('room','one','Workshop')
    with pytest.raises(ValueError,match='Original look'):
        look.generate('room','two','Change it',revises=first['presentation']['items'][0]['id'])
    with pytest.raises(ValueError,match='GPT Image'):
        look.generate('room','one','Other',model='unapproved-model')
    assert len(setup)==1

def test_uncertain_request_not_repeated(setup,monkeypatch):
    def broken(*a,**k):raise TimeoutError('unknown provider outcome')
    monkeypatch.setattr(look.httpx.Client,'post',broken)
    with pytest.raises(TimeoutError):look.generate('room','one','Timeout')
    with pytest.raises(ValueError,match='Previous generation'):look.generate('room','one','Timeout')
