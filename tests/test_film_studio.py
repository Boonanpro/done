import asyncio
import copy
import pytest
from app.services import film_studio as studio,timeline_draft as td

@pytest.fixture
def project(tmp_path,monkeypatch):
    monkeypatch.setattr(td,'UPLOAD_ROOT',tmp_path)
    studio.initialize('test')
    return 'test'

def test_new_project_is_two_minutes_without_invented_plot(project):
    s=studio.state(project)
    assert s['sheet']['尺'].startswith('2分')
    assert not s['film_plan']['story'] and not s['film_plan']['scenes']
    assert not s['dialogue'] and not s['items']
    studio.dialogue('user','まだ飛ばさず終わりたい',project)
    studio.initialize(project)
    assert studio.state(project)['dialogue'][0]['text']=='まだ飛ばさず終わりたい'

def test_partial_scene_edit_keeps_other_decisions(project):
    asyncio.run(studio.execute('update_film_plan',{'base_revision':0,'changes':[
        {'op':'scene','id':'a','title':'試験','duration':10},
        {'op':'scene','id':'b','title':'発見','duration':8}], 'evidence':'テストで明示した案'},project))
    before=copy.deepcopy(studio.state(project)['film_plan']['scenes'][1])
    asyncio.run(studio.execute('update_film_plan',{'base_revision':1,'changes':[
        {'op':'scene','id':'a','camera':'手元へ寄る'}], 'evidence':'ユーザーの変更'},project))
    assert studio.state(project)['film_plan']['scenes'][1]==before

def test_recipe_requires_real_scene_and_visual(project):
    args={'scene_id':'absent','model':'unverified','prompt':'test','visual_ids':[],'audio':'','unresolved':['未定']}
    with pytest.raises(ValueError):asyncio.run(studio.execute('save_recipe',args,project))
    assert not studio.state(project)['recipes']

def test_tools_have_no_final_generation_or_arbitrary_execution():
    names={t['name'] for t in studio.tools()}
    assert {'generate_look','show_consultation_visual','revise_consultation_visual','save_recipe'}<=names
    assert 'run_editor_task' not in names

def test_scene_change_marks_saved_recipe_for_review(project):
    asyncio.run(studio.execute('update_film_plan',{'base_revision':0,'changes':[{'op':'scene','id':'a','title':'場面'}],'evidence':'案'},project))
    asyncio.run(studio.execute('save_recipe',{'scene_id':'a','model':'to-be-verified','prompt':'scene','visual_ids':[],'audio':'未定','unresolved':['音']},project))
    asyncio.run(studio.execute('update_film_plan',{'base_revision':1,'changes':[{'op':'scene','id':'a','camera':'寄る'}],'evidence':'変更'},project))
    assert studio.state(project)['recipes']['a']['needs_review']

def test_image_routing_fallback_is_explicit(monkeypatch):
    from app.services import editor_jev
    async def unavailable(*a,**k):return {'available':False,'reason':'timeout'}
    monkeypatch.setattr(editor_jev,'judge',unavailable)
    model,route=asyncio.run(studio.image_route('new image',None))
    assert model=='gpt-image-2' and route['selected_by']=='configured_default'
