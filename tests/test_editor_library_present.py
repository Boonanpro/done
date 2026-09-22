from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from app.api import editor_assistant_routes as routes
from app.services import editor_reference_library as library


def test_reference_display_authenticates_and_does_not_begin_editing(monkeypatch):
    app=FastAPI();app.include_router(routes.router);client=TestClient(app)
    body={'room_id':'test','content_id':'content','ids':['known'],'comparison_key':'session:utterance'}
    def deny(request):raise HTTPException(401,'Not authenticated')
    monkeypatch.setattr(routes,'_get_user',deny)
    assert client.post('/editor-assistant/reference-library/present',json=body).status_code==401
    monkeypatch.setattr(routes,'_get_user',lambda request:object())
    def unexpected(*args,**kwargs):raise AssertionError('Reference display must not assemble an editing context')
    monkeypatch.setattr(routes.workflows,'compact_state',unexpected)
    calls=[]
    def show(*args):calls.append(args);return {'presentation':{'id':'p','items':[]}}
    monkeypatch.setattr(library,'show',show)
    result=client.post('/editor-assistant/reference-library/present',json=body)
    assert result.status_code==200
    assert calls==[('test','content',['known'],'session:utterance')]
    assert client.post('/editor-assistant/reference-library/present',json={**body,'room_id':'../bad'}).status_code==422


def test_unknown_catalog_entry_is_a_readable_error(monkeypatch):
    app=FastAPI();app.include_router(routes.router);client=TestClient(app)
    monkeypatch.setattr(routes,'_get_user',lambda request:object())
    monkeypatch.setattr(library,'catalog',lambda:[])
    result=client.post('/editor-assistant/reference-library/present',json={
        'room_id':'test','content_id':'content','ids':['not-real'],'comparison_key':'u'})
    assert result.status_code==400
    assert result.json()['detail']=='Unknown reference'
