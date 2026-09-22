import pytest
from app.services import editor_presentation as presentation,editor_project as project
from tests.test_editor_project import room


def test_one_utterance_updates_one_comparison_without_touching_other_history(room):
    original=presentation.present('room','c',[{'kind':'text','text':'earlier'}])['presentation']
    first=presentation.present('room','c',[{'kind':'text','text':'draft'}],comparison_key='session:utterance')['presentation']
    final=presentation.present('room','c',[{'kind':'text','text':'refined'}],comparison_key='session:utterance')['presentation']
    assert first['id']==final['id']
    assert first['at']==final['at']
    assert final['revision']==2
    rows=presentation.history('room','c')['presentations']
    assert len(rows)==2 and rows[0]==original and rows[1]==final
    next_turn=presentation.present('room','c',[{'kind':'text','text':'next turn'}],comparison_key='session:next')['presentation']
    assert next_turn['id']!=first['id']
    assert len(presentation.history('room','c')['presentations'])==3


def test_executable_scene_is_preserved_and_never_changes_timeline(room):
    from app.services import timeline_live
    code='setFrame(t=>{stage.textContent=String(t);});'
    result=presentation.present('room','c',[{'title':'Scene','kind':'scene','scene':{'code':code,'duration':15}}])
    item=result['presentation']['items'][0]
    assert item['scene']['code']==code
    assert item['scene']['duration']==15
    revised=presentation.revise('room','c',item['id'],[{'path':'/scene/duration','value':10}])
    assert revised['presentation']['items'][0]['scene']['code']==code
    assert timeline_live.live_sequence('room','c')[1]==room[1]
    before=presentation.history('room','c')
    with pytest.raises(ValueError):
        presentation.present('room','c',[{'title':'Bad','kind':'scene','scene':{'code':code,'duration':-1}}])
    assert presentation.history('room','c')==before

def test_shared_layer_defaults_equal_explicit_authoring(room):
    shared={'color':'#ffeecc','fontSize':32,'keyframes':[{'offset':0,'opacity':0},{'offset':1,'opacity':1}]}
    compact={'defaults':shared,'layers':[{'text':'A'},{'text':'B','color':'#abcdef'}]}
    explicit={'layers':[{**shared,'text':'A'},{**shared,'text':'B','color':'#abcdef'}]}
    assert presentation.clean_composition('room',compact)==presentation.clean_composition('room',explicit)

def test_revision_preserves_other_fields_and_history(room):
    import copy
    original=presentation.present('room','c',[{'title':'A','kind':'composition','composition':{
        'layers':[{'type':'text','text':'Hello','color':'#ffaa00','keyframes':[{'offset':0,'opacity':0},{'offset':1,'opacity':1}]}]}}])['presentation']['items'][0]
    updated=presentation.revise('room','c',original['id'],[{'path':'/composition/layers/0/text','value':'World'}])['presentation']['items'][0]
    expected=copy.deepcopy(original['composition']);expected['layers'][0]['text']='World'
    assert updated['composition']==expected
    assert updated['revises']==original['id']
    assert presentation.history('room','c')['presentations'][0]['items'][0]==original

@pytest.mark.parametrize('path,value',[('/id','bad'),('/composition/layers/999/text','bad'),('/composition/layers/0/fontSize',-1)])
def test_invalid_revision_is_atomic(room,path,value):
    original=presentation.present('room','c',[{'title':'A','kind':'composition','composition':{'layers':[{'text':'Hello'}]}}])['presentation']['items'][0]
    before=presentation.history('room','c')
    with pytest.raises(ValueError):presentation.revise('room','c',original['id'],[{'path':path,'value':value}])
    assert presentation.history('room','c')==before

@pytest.mark.asyncio
async def test_resolve_and_present_keeps_actual_kind_and_original_timeline(room,monkeypatch):
    from app.services import editor_references,timeline_live
    def resolve(*args):return {'item':{'kind':'image','url':'https://example.com/preview.jpg','note':'ページの紹介画像。動画本編ではありません。'}}
    monkeypatch.setattr(editor_references,'resolve',resolve)
    result=await presentation.resolve_and_present('room','c',[
        {'source':'https://example.com/post','source_url':'https://example.com/author','kind':'video','title':'人物の参考','note':'動きの候補'},
        {'kind':'text','title':'比較','text':'別案'}])
    assert result['presentation']['items'][0]['kind']=='image'
    assert result['presentation']['items'][0]['source_url']=='https://example.com/author'
    assert '動画本編ではありません' in result['presentation']['items'][0]['note']
    assert len(result['presentation']['items'])==2
    assert timeline_live.live_sequence('room','c')[1]==room[1]

@pytest.mark.asyncio
async def test_canceled_intake_does_not_display(room,monkeypatch):
    from app.services import editor_references
    monkeypatch.setattr(editor_references,'resolve',lambda *args:{'item':{'kind':'image','url':'https://example.com/a.jpg'}})
    result=await presentation.resolve_and_present('room','c',[{'source':'https://example.com','kind':'image','title':'A'}],lambda:False)
    assert result=={'ok':False,'canceled':True}
    assert not presentation.history('room','c')['presentations']

@pytest.mark.asyncio
async def test_worker_tool_uses_same_source_intake_as_conversation(room,monkeypatch):
    import json
    from app import timeline_mcp_server as server
    from app.services import editor_references
    monkeypatch.setattr(server,'ROOM_ID','room')
    monkeypatch.setattr(server,'_load',lambda:{'content_id':'c','sequence':room[1]})
    monkeypatch.setattr(server,'_assets',lambda:{})
    monkeypatch.setattr(editor_references,'resolve',lambda *args:{'item':{'kind':'image','url':'https://example.com/a.jpg'}})
    result=await server._dispatch('present_references',{'items':[{'source':'https://example.com/post','kind':'image','title':'A'}]})
    assert json.loads(result[0].text)['presentation']['items'][0]['url']=='https://example.com/a.jpg'

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


def test_mixed_feed_pagination_keeps_old_items_and_revision_links(room):
    original=presentation.present('room','c',[{'kind':'text','title':'Original','text':'A'}])['presentation']['items'][0]
    for i in range(33):presentation.present('room','c',[{'kind':'link','title':str(i),'url':'https://example.com'}])
    result=presentation.present('room','c',[{'kind':'model','title':'Character','url':'https://example.com/character.glb','revises':original['id']}])
    assert result['presentation']['items'][0]['revises']==original['id']
    page=presentation.history('room','c',limit=12);rows=list(page['presentations'])
    while page['before'] is not None:
        page=presentation.history('room','c',page['before'],12);rows+=page['presentations']
    assert len(rows)==35
    assert len({r['id'] for r in rows})==35
    assert any(i['id']==original['id'] for r in rows for i in r['items'])

def test_scene_variants_and_parameter_edit_preserve_program_and_other_values(room):
    code="stage.style.background=params.color;setFrame(t=>{});"
    result=presentation.present('room','c',[
        {'title':'Warm','kind':'scene','scene':{'code':code,'duration':5,'params':{'color':'#ffaa55','speed':1}}},
        {'title':'Cool','kind':'scene','scene':{'reuse':0,'params':{'color':'#4466aa'}}}])
    first,second=result['presentation']['items']
    assert second['scene']['code']==first['scene']['code']==code
    assert second['scene']['params']=={'color':'#4466aa','speed':1}
    revised=presentation.revise('room','c',second['id'],[{'path':'/scene/params/speed','value':.5}])['presentation']['items'][0]
    assert revised['scene']['code']==code
    assert revised['scene']['params']=={'color':'#4466aa','speed':.5}
    assert presentation.history('room','c')['presentations'][0]['items'][1]==second
    reuse=presentation.present('room','c',[{'title':'Third','kind':'scene','scene':{'reuse':revised['id'],'params':{'speed':2}}}])['presentation']['items'][0]
    assert reuse['scene']['params']=={'color':'#4466aa','speed':2}
    added=presentation.revise('room','c',reuse['id'],[{'path':'/scene/params/lampWarmth','value':.7}])['presentation']['items'][0]
    assert added['scene']['params']=={'color':'#4466aa','speed':2,'lampWarmth':.7}
    assert added['scene']['code']==code

def test_html_source_variants_and_partial_revision_preserve_source(room):
    source='<div data-composition-id="sample">日本語</div><script>window.__timelines={};</script>'
    first=presentation.present('room','c',[{'title':'HTML','kind':'scene','scene':{'html':source,'duration':10,'params':{'closing':'前'}}}])['presentation']['items'][0]
    revised=presentation.revise('room','c',first['id'],[{'path':'/scene/params/closing','value':'後'}])['presentation']['items'][0]
    assert revised['scene']['html']==source
    assert revised['scene']['params']['closing']=='後'
    assert first['scene']['params']['closing']=='前'
    clone=presentation.present('room','c',[{'title':'別案','kind':'scene','scene':{'reuse':revised['id']}}])['presentation']['items'][0]
    assert clone['scene']==revised['scene']
    for invalid in ({'html':source,'code':'x'},{'html':''},{'html':source,'reuse':first['id']}):
        with pytest.raises(ValueError):presentation.present('room','c',[{'kind':'scene','scene':invalid}])

@pytest.mark.parametrize('scene',[{'reuse':1},{'reuse':'missing'},{'code':'x','reuse':0},{'code':'x','params':[]}])
def test_invalid_scene_variant_does_not_append_partial_results(room,scene):
    before=presentation.history('room','c')
    with pytest.raises(ValueError):presentation.present('room','c',[{'title':'Invalid','kind':'scene','scene':scene}])
    assert presentation.history('room','c')==before

def test_typographic_controls_survive_creation_and_partial_revision(room):
    item=presentation.present('room','c',[{'kind':'composition','composition':{'layers':[
        {'text':'日常を、少し変える。','letterSpacing':3,'lineHeight':1.4,'strokeWidth':1.5,'strokeColor':'#10251c','textShadow':'0 2px 8px #0009'}]}}])['presentation']['items'][0]
    layer=item['composition']['layers'][0]
    assert layer['letterSpacing']==3 and layer['lineHeight']==1.4
    assert layer['strokeWidth']==1.5 and layer['strokeColor']=='#10251c'
    changed=presentation.revise('room','c',item['id'],[{'path':'/composition/layers/0/text','value':'次の言葉'}])['presentation']['items'][0]
    assert {k:v for k,v in changed['composition']['layers'][0].items() if k!='text'}=={k:v for k,v in layer.items() if k!='text'}
    with pytest.raises(ValueError):
        presentation.present('room','c',[{'kind':'composition','composition':{'layers':[{'text':'x','lineHeight':0}]}}])


def test_source_patch_preserves_other_code_and_failed_batch_is_atomic(room):
    html='<style>.title{color:red}.other{color:blue}</style><p>Keep</p>'
    original=presentation.present('room','c',[{'kind':'scene','scene':{'html':html,'duration':5}}])['presentation']['items'][0]
    revised=presentation.revise('room','c',original['id'],[{'path':'/scene/html','find':'.title{color:red}','value':'.title{color:gold}'}])['presentation']['items'][0]
    assert revised['scene']['html']==html.replace('color:red','color:gold')
    assert original['scene']['html']==html
    before=presentation.history('room','c')
    for change in (
        {'find':'color:','value':'background:'},
        {'find':'missing','value':'x'},
        {'find':'Keep','value':'x','expected_count':True},
        {'find':'','value':'x'},
    ):
        with pytest.raises(ValueError):
            presentation.revise('room','c',original['id'],[
                {'path':'/scene/duration','value':6}, {'path':'/scene/html',**change}])
        assert presentation.history('room','c')==before
    both=presentation.revise('room','c',original['id'],[{'path':'/scene/html','find':'color:','value':'background:','expected_count':2}])['presentation']['items'][0]
    assert both['scene']['html']==html.replace('color:','background:')


def test_revision_can_append_one_layer_without_rewriting_or_mutating_others(room):
    original=presentation.present('room','c',[{'kind':'composition','title':'Caption','composition':{'layers':[{'text':'Keep','color':'#ffffff'}]}}])['presentation']['items'][0]
    added=presentation.revise('room','c',original['id'],[{'path':'/composition/layers/-','value':{'text':'Accent','color':'#eecb77'}}])['presentation']['items'][0]
    assert added['composition']['layers'][0]==original['composition']['layers'][0]
    assert added['composition']['layers'][1]['text']=='Accent'
    assert len(presentation.history('room','c')['presentations'][0]['items'][0]['composition']['layers'])==1
    before=presentation.history('room','c')
    with pytest.raises(ValueError):
        presentation.revise('room','c',original['id'],[{'path':'/composition/layers/-','value':{'type':'video','url':'file:///private'}}])
    assert presentation.history('room','c')==before
