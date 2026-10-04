import copy
import pytest
from tests.test_editor_project import room
from app.services import editor_film_plan as film, editor_presentation as presentation, timeline_draft as td


def test_scene_patch_preserves_other_scene_and_timeline(room):
    before = copy.deepcopy(td._read_contents_raw('room')[0]['timeline'])
    plan = film.update('room', 'c', 0, [
        {'op':'story','text':'飛行機の試験を繰り返す物語'},
        {'op':'scene','id':'a','title':'作業場','camera':'引き','status':'agreed'},
        {'op':'scene','id':'b','title':'飛行試験','status':'agreed'}], 'ユーザーが展開を指定')
    other = copy.deepcopy(plan['scenes'][1])
    plan = film.update('room', 'c', 1, [{'op':'scene','id':'a','camera':'主人公に寄る'}], 'ここは寄って')
    assert plan['scenes'][0]['status'] == 'proposed'
    assert plan['scenes'][1] == other
    assert td._read_contents_raw('room')[0]['timeline'] == before
    assert film.read('room','c') == plan


def test_conflicts_and_bad_batch_never_partially_save(room):
    plan = film.update('room','c',0,[{'op':'story','text':'案'}],'提案')
    with pytest.raises(ValueError):
        film.update('room','c',0,[{'op':'story','text':'古い変更'}],'古い依頼')
    with pytest.raises(ValueError):
        film.update('room','c',1,[{'op':'story','text':'失敗時は保存しない'},
                                 {'op':'scene','id':'s','visual_ids':['invented']}],'変更')
    assert film.read('room','c') == plan


def test_known_visuals_and_revision_handoff(room):
    visual = presentation.present('room','c',[{'kind':'scene','scene':{
        'code':'setFrame(t=>{stage.textContent=params.x;});','duration':5,'params':{'x':1,'color':'red'}}}])['presentation']['items'][0]
    film.update('room','c',0,[{'op':'scene','id':'s','visual_ids':[visual['id']]}],'構図の提案')
    revised = presentation.revise('room','c',visual['id'],[{'path':'/scene/params/x','value':2}])['presentation']['items'][0]
    plan = film.update('room','c',1,[{'op':'scene','id':'s','visual_ids':[revised['id']]}],'右へ')
    assert revised['scene']['params'] == {'x':2,'color':'red'}
    assert plan['scenes'][0]['visual_ids'] == [revised['id']]
    assert revised['id'] in film.production_context('room','c')
    assert 'decisions' not in film.production_context('room','c')


def test_deleted_work_is_not_recreated(room):
    with pytest.raises(ValueError):
        film.update('room','deleted',0,[{'op':'story','text':'案'}],'提案')
    assert film.read('room','c')['revision'] == 0


def test_visual_revision_follows_only_linked_scenes(room):
    item=presentation.present('room','c',[{'kind':'text','text':'before'}])['presentation']['items'][0]
    film.update('room','c',0,[{'op':'scene','id':'a','visual_ids':[item['id']],'status':'agreed'},
                            {'op':'scene','id':'b','title':'untouched','status':'agreed'}],'採用')
    revised=presentation.revise('room','c',item['id'],[{'path':'/text','value':'after'}])['presentation']['items'][0]
    old=film.read('room','c')['scenes'][1]
    plan=film.link_visual_revision('room','c',item['id'],revised['id'])
    assert plan['scenes'][0]['visual_ids']==[revised['id']]
    assert plan['scenes'][0]['status']=='proposed'
    assert plan['scenes'][1]==old
    assert film.link_visual_revision('room','c',item['id'],revised['id'])==plan


def test_live_backend_has_actual_plan_and_revision_tools():
    from app.services.editor_live import session_config
    config = session_config([],[])['delegation']['responses']
    names = {t.get('name') for t in config['tools']}
    assert {'update_film_plan','revise_consultation_visual'} <= names
    assert 'シート完成を長編生成の開始条件にはしません' in config['instructions']
    assert '展開' in config['instructions']


def test_publish_editable_scene_preserves_existing_clips_and_updates_in_place(room):
    before=copy.deepcopy(td._read_contents_raw('room')[0]['timeline']['sequence']['tracks'][0])
    film.update('room','c',0,[{'op':'scene','id':'s','title':'冒頭','duration':5}],'配置を確認')
    item=presentation.present('room','c',[{'kind':'scene','scene':{'code':'setFrame(t=>{stage.textContent=String(t)});','duration':5,'params':{'x':0}}}])['presentation']['items'][0]
    placed=film.place_scene('room','c','s',item['id'])
    assert placed['ok'],placed
    seq=td._read_contents_raw('room')[0]['timeline']['sequence']
    assert seq['tracks'][0]==before
    clip=seq['tracks'][-1]['clips'][0]
    assert (clip['timeline_start'],clip['timeline_end'])==(3,8)
    assert 'asset_id' not in clip and clip['scene']==item['scene']
    revised=presentation.revise('room','c',item['id'],[{'path':'/scene/params/x','value':2}])['presentation']['items'][0]
    assert film.place_scene('room','c','s',revised['id'])['ok']
    seq=td._read_contents_raw('room')[0]['timeline']['sequence']
    assert len(seq['tracks'][-1]['clips'])==1
    assert seq['tracks'][-1]['clips'][0]['id']==placed['clip_id']
    assert seq['tracks'][0]==before
