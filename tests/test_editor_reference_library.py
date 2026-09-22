import math
import json
import pytest
from app.services import editor_reference_library as lib
from app.services import editor_jev, timeline_live
from tests.test_editor_project import room


@pytest.fixture(autouse=True)
def local_catalog(tmp_path,monkeypatch):
    rows=[{'id':key,'family':key,'title':key,'description':'Test reference','source_url':'https://example.com','url':'https://example.com/image.jpg'} for key in ['a','b']]
    manifest=tmp_path/'catalog.json'
    manifest.write_text(json.dumps(rows),encoding='utf-8')
    for row in rows:(tmp_path/(row['id']+'.jpg')).write_bytes(b'test')
    monkeypatch.setattr(lib,'CATALOG',manifest)
    monkeypatch.setattr(lib,'COMPONENTS',tmp_path/'missing-components.json')
    monkeypatch.setattr(lib,'MEDIA',tmp_path)


def test_only_curated_local_media_is_allowed():
    from app.services.editor_presentation import media_url
    row=lib.catalog()[0]
    assert media_url('unused',lib.proposal(row)).endswith(row['id'])
    for ident in ['../secret','.env','unknown','9f5a2b9c0441?x=1']:
        with pytest.raises(ValueError):lib.media_path(ident)


def test_video_and_native_previews_have_real_media_types(tmp_path):
    rows=json.loads(lib.CATALOG.read_text())
    rows.extend([
        {'id':'film','kind':'video','extension':'.mp4','title':'Video','source_url':'https://example.com'},
        {'id':'native','kind':'composition','title':'Text','composition':{'duration':3,'layers':[]}},
        {'id':'unreviewed','kind':'image','inspection':'pending'},
    ])
    lib.CATALOG.write_text(json.dumps(rows))
    (tmp_path/'film.mp4').write_bytes(b'video')
    (tmp_path/'unreviewed.jpg').write_bytes(b'image')
    assert lib.media_path('film').suffix=='.mp4'
    assert lib.proposal(rows[2])['kind']=='video'
    result=lib.proposal(rows[3]);result['composition']['duration']=9
    assert rows[3]['composition']['duration']==3
    with pytest.raises(ValueError):lib.media_path('native')
    assert 'unreviewed' not in {r['id'] for r in lib.catalog()}


def test_style_diversity_and_invalid_scores():
    rows=[{'id':'a','family':'one'},{'id':'b','family':'one'},{'id':'c','family':'two'}]
    answers={'a':{'score':3},'b':{'score':2.9},'c':{'score':2.8}}
    assert [r['id'] for r in lib.rank(answers,rows,True)]==['a','c']
    assert [r['id'] for r in lib.rank(answers,rows,False)]==['a','b']
    assert lib.rank({'a':{'score':math.nan},'b':{'score':9}},rows,False)==[]
    assert [r['id'] for r in lib.rank({'a':{'score':2.9},'c':{'score':2.3}},rows,True)]==['a']


@pytest.mark.asyncio
async def test_uncertain_or_canceled_never_presents(room,monkeypatch):
    async def judge(*a,**kw):return {'answers':{},'elapsed_ms':1}
    monkeypatch.setattr(editor_jev,'judge',judge)
    result=await lib.suggest('u','room','c','参考を見たい',[])
    assert result['needs_judgment'] and not result['presented']
    assert timeline_live.live_sequence('room','c')[1]==room[1]


@pytest.mark.asyncio
async def test_diversity_uncertainty_does_not_block_same_valid_selection(monkeypatch):
    async def judge(*a,**kw):return {'answers':{'a':{'score':2.9},'different_styles':{'noul':.5},'reference_request':{'choice':'examples','confidence':.99}}}
    monkeypatch.setattr(editor_jev,'judge',judge)
    result=await lib.suggest('u',None,None,'reference',[],selection_only=True)
    assert result['handled'] and result['selected_library_ids']==['a']
    assert (await lib.suggest('u','room','c','参考を見たい',[],lambda:False))['canceled']


@pytest.mark.asyncio
async def test_direct_decision_requires_explicit_intent_and_preserves_timeline(room,monkeypatch):
    rows=lib.catalog()[:2]
    answers={r['id']:{'score':3} for r in rows}
    answers['different_styles']={'noul':0}
    async def judge(*a,**kw):return {'answers':answers,'elapsed_ms':1}
    monkeypatch.setattr(editor_jev,'judge',judge)
    assert not (await lib.suggest('u',None,None,'何ですか',[],selection_only=True))['handled']
    answers['reference_request']={'choice':'examples','confidence':.99}
    result=await lib.suggest('u',None,None,'参考を見せて',[],selection_only=True)
    assert result['handled']
    shown=lib.show('room','c',result['selected_library_ids'])
    assert len(shown['presentation']['items'])==2
    assert timeline_live.live_sequence('room','c')[1]==room[1]


@pytest.mark.asyncio
async def test_selector_has_only_selection_context_and_validates_ids(monkeypatch):
    from app.services import editor_codex
    captured={}
    class Owner:
        def __init__(self):self.events=[]
        async def start(self,inputs,tools,instructions,model,**kw):
            captured.update(tools=tools,instructions=instructions,config=kw['config_overrides'])
            self.events=[{'method':'item/agentMessage/delta','params':{'delta':'{"handled":true,"ids":["not-in-library"]}'}},
                         {'method':'turn/completed','params':{'turn':{'status':'completed'}}}]
        async def receive(self):return self.events.pop(0)
        def close(self):captured['closed']=True
    monkeypatch.setattr(editor_codex,'CodexTurn',Owner)
    with pytest.raises(ValueError):await lib.astra_select({'candidates':[{'id':'a'}]})
    assert captured['closed'] and captured['tools']==[]
    assert captured['config']['project_doc_max_bytes']==0
    assert captured['config']['model_reasoning_effort']=='medium'
def test_selection_evidence_distinguishes_mechanism_from_finished_work():
    from app.services.editor_reference_library import selection_description, proposal
    row = {'id':'example','title':'Example','kind':'composition','composition':{},
           'description':'Quiet type motion.','component':'type-motion',
           'use_cases':['compare title timing'], 'limitations':['not a spoken subtitle sample']}
    evidence = selection_description(row)
    assert 'compare title timing' in evidence
    assert 'not a spoken subtitle sample' in evidence
    assert 'not a finished film' in evidence
    assert proposal(row)['note'] == evidence
