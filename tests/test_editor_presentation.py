import pytest
from app.services import editor_presentation as presentation,editor_project as project
from tests.test_editor_project import room

def test_present_references_persists_without_changing_video(room):
    p,seq=room
    result=presentation.present('room','c',[{'title':'Quiet','url':'https://youtu.be/dT5-x3u5nCg','start':3,'end':8}])
    state=project.status('room','c')
    assert state['presentation']==result['presentation']
    from app.services import timeline_live
    assert timeline_live.live_sequence('room','c')[1]==seq

@pytest.mark.parametrize('item',[{'url':'javascript:alert(1)'},{'url':'file:///D:/private'},{'url':'https://example.com/v.mp4','start':5,'end':2}])
def test_invalid_reference_is_rejected(room,item):
    with pytest.raises(ValueError):presentation.present('room','c',[item])

def test_local_motion_and_choice_survive_replacement_without_editing(room):
    from app.services import timeline_live, timeline_draft as td
    p,seq=room
    proposal={'title':'Readable guide','kind':'composition','composition':{
        'duration':4,'layers':[{'type':'text','text':'Five details',
            'keyframes':[{'offset':0,'opacity':0},{'offset':1,'opacity':1}]}]}}
    result=presentation.present('room','c',[proposal])
    item=result['presentation']['items'][0]
    presentation.present('room','c',[{'title':'Alternative','kind':'text','text':'Other direction'}])
    chosen=presentation.choose('room','c',item['id'],'Keep the slower movement')
    assert chosen['chosen_proposal']['item']==item
    assert len(td._read_contents_raw('room')[0]['proposal_history'])==2
    assert timeline_live.live_sequence('room','c')[1]==seq

@pytest.mark.parametrize('composition',[
    {'layers':[]}, {'duration':float('nan'),'layers':[{'text':'x'}]},
    {'layers':[{'type':'video','url':'file:///private.mp4'}]},
    {'duration':2,'layers':[{'end':3}]},
])
def test_invalid_composition_is_rejected(room,composition):
    with pytest.raises(ValueError):
        presentation.present('room','c',[{'kind':'composition','composition':composition}])
