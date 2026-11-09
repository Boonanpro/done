"""Each step Dan publishes is recorded so an open editor can replay it as visible motion."""
import json
import pytest
from fastapi.testclient import TestClient
from app.services import timeline_draft as td
import app.timeline_mcp_server as m
from tests.test_editor_live_checkpoints import tool, live


@pytest.fixture
def draft(tmp_path, monkeypatch):
    monkeypatch.setattr(td, 'UPLOAD_ROOT', tmp_path)
    room = tmp_path / 'room'; room.mkdir()
    seq = {'duration': 6, 'format': '16:9', 'frame_rate': 30, 'tracks': [
        {'id': 'v', 'type': 'video', 'clips': [
            {'id': 'a', 'text': 'before', 'timeline_start': 0, 'timeline_end': 3},
            {'id': 'b', 'text': 'keep', 'timeline_start': 3, 'timeline_end': 6}]}]}
    (room / 'contents.json').write_text(json.dumps([{'id': 'c', 'timeline': {'sequence': seq}}]))
    (room / 'assets.json').write_text('[]')
    d = td.create_draft('room', 'c', 'job'); d['live_updates'] = True; td.save_draft(d)
    monkeypatch.setattr(m, 'ROOM_ID', 'room'); monkeypatch.setattr(m, 'DRAFT_ID', d['draft_id'])
    monkeypatch.setattr(m, 'JOB_ID', 'job'); monkeypatch.setattr(m, 'CONTENT_ID', 'c')
    return d


def test_each_published_tool_call_is_one_feed_entry_in_order(draft):
    assert td.read_edit_feed('room', 'c', -1) == (0, [])
    assert tool('set_clip_props', {'clip_id': 'a', 'props': {'text': 'changed'}})['ok']
    assert tool('move_clip', {'clip_id': 'b', 'new_start': 4})['ok']
    last, rows = td.read_edit_feed('room', 'c', 0)
    assert len(rows) == 2 and rows[0]['n'] < rows[1]['n'] == last
    first, second = rows
    assert first['changes'] == [{'clip_id': 'a', 'text': 'changed', 'start': 0, 'end': 3, 'removed': False,
                                 'before': {'text': 'before'}, 'after': {'text': 'changed'}}]
    moved = second['changes'][0]
    assert moved['clip_id'] == 'b' and moved['after']['timeline_start'] == 4 and moved['before']['timeline_start'] == 3
    # The replay starts from what the editor shows and must end exactly on what is saved.
    assert live()['tracks'][0]['clips'][1]['timeline_start'] == 4
    # An editor that opens later does not replay old steps.
    assert td.read_edit_feed('room', 'c', last) == (last, [])


def test_failed_tool_call_records_nothing(draft):
    assert not tool('split_clip', {'clip_id': 'b', 'at': [2, 4]})['ok']
    assert td.read_edit_feed('room', 'c', 0) == (0, [])


def test_feed_endpoint(draft, monkeypatch):
    from fastapi import FastAPI
    from app.api import production_asset_routes as r
    monkeypatch.setattr(r, '_room_dir', td._room_dir)
    app = FastAPI(); app.include_router(r.router, prefix='/api/v1')
    get_current_user = r.get_current_user
    app.dependency_overrides[get_current_user] = lambda: None
    try:
        c = TestClient(app)
        url = '/api/v1/production-assets/contents/c/edit-feed'
        assert c.get(url, params={'room_id': 'room'}).json() == {'last': 0, 'entries': []}
        tool('set_clip_props', {'clip_id': 'a', 'props': {'text': 'changed'}})
        opened = c.get(url, params={'room_id': 'room'}).json()
        assert opened['entries'] == [] and opened['last'] > 0          # opening never replays history
        tool('move_clip', {'clip_id': 'b', 'new_start': 4})
        got = c.get(url, params={'room_id': 'room', 'after': opened['last']}).json()
        assert [e['changes'][0]['clip_id'] for e in got['entries']] == ['b']
        assert got['sequence'] == live()
    finally:
        app.dependency_overrides.clear()
