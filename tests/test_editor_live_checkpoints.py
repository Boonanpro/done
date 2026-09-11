import asyncio
import copy
import json
import pytest
from app.services import timeline_draft as td
import app.timeline_mcp_server as m


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


def live(): return td._read_contents_raw('room')[0]['timeline']['sequence']


def test_multiple_splits_publish_together_and_invalid_cut_rolls_back(draft):
    result = tool('split_clip', {'clip_id': 'a', 'at': [1, 2]})
    assert result['ok'] and result['timeline_updated'], result
    clips = live()['tracks'][0]['clips']
    assert sorted((c['timeline_start'], c['timeline_end']) for c in clips) == [(0, 1), (1, 2), (2, 3), (3, 6)]
    before = copy.deepcopy(live())
    result = tool('split_clip', {'clip_id': 'b', 'at': [2, 4]})
    assert not result['ok'] and result['rolled_back']
    assert live() == before


def test_caption_text_can_be_changed_through_property_tool(draft):
    result = tool('set_clip_props', {'clip_id': 'a', 'props': {'text': 'changed'}})
    assert result['ok'] and result['timeline_updated'], result
    assert live()['tracks'][0]['clips'][0]['text'] == 'changed'


def test_discard_keeps_assets_from_published_history(draft):
    tool('set_clip', {'clip_id': 'a', 'text': 'published'})
    d = td.load_draft('room', draft['draft_id'])
    d['generated_asset_ids'] = ['retained-for-undo']
    td.save_draft(d)
    deleted = []
    td.discard_draft('room', draft['draft_id'], lambda room, ids: deleted.extend(ids))
    assert not deleted


def test_redirect_delivers_actual_instruction_and_resolves_old_question(draft):
    from app.services import editor_questions as q, editor_job_updates as updates
    path = q.path('room', 'job'); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'id': 'q1', 'text': 'Purchase voice credits?'}))
    instruction = 'Show the draft first. Do not buy anything.'
    updates.submit('room', 'job', instruction)
    assert q.read('room', 'job') is None
    assert updates.pending('room', 'job')[0]['instruction'] == instruction
    answer = json.loads((path.parent / 'q1.answer.json').read_text(encoding='utf-8'))['text']
    assert instruction in answer


def tool(name, args): return json.loads(m._run_tool_thread(name, args)[0].text)


def test_edits_are_visible_before_job_finishes_and_final_commit_works(draft):
    result = tool('set_clip', {'clip_id': 'a', 'text': 'first'})
    assert result['timeline_updated'] and live()['tracks'][0]['clips'][0]['text'] == 'first'
    assert 'committed_at' not in td.load_draft('room', draft['draft_id'])
    tool('set_clip', {'clip_id': 'b', 'text': 'second'})
    assert live()['tracks'][0]['clips'][1]['text'] == 'second'
    assert td.commit_draft('room', draft['draft_id'], lambda *_: [])['ok']


def test_failed_batch_does_not_leak_partial_changes(draft):
    before = copy.deepcopy(live())
    result = tool('apply_edits', {'operations': [
        {'name': 'set_clip', 'args': {'clip_id': 'a', 'text': 'must roll back'}},
        {'name': 'set_clip', 'args': {'clip_id': 'missing', 'text': 'bad'}}]})
    assert result['rolled_back'] and live() == before


def test_human_save_is_received_and_preserved(draft):
    tool('set_clip', {'clip_id': 'a', 'text': 'AI'})
    contents = td._read_contents_raw('room')
    contents[0]['timeline']['sequence']['tracks'][0]['clips'][1]['text'] = 'Human'
    td._write_contents_raw('room', contents)
    assert tool('set_clip', {'clip_id': 'a', 'text': 'AI next'})['human_edit_received']
    assert tool('set_clip', {'clip_id': 'a', 'text': 'AI next'})['timeline_updated']
    assert [c['text'] for c in live()['tracks'][0]['clips']] == ['AI next', 'Human']


def test_racing_human_save_cannot_be_overwritten(draft):
    draft['sequence']['tracks'][0]['clips'][0]['text'] = 'pending AI'; td.save_draft(draft)
    contents = td._read_contents_raw('room')
    contents[0]['timeline']['sequence']['tracks'][0]['clips'][0]['text'] = 'Human'
    td._write_contents_raw('room', contents)
    assert td.publish_checkpoint('room', draft['draft_id'])['conflict']
    assert live()['tracks'][0]['clips'][0]['text'] == 'Human'


def test_approved_clip_is_protected_during_incremental_publication(draft):
    draft['sequence']['tracks'][0]['clips'][1]['approved'] = True
    draft['base_sequence'] = copy.deepcopy(draft['sequence']); td.save_draft(draft)
    result = tool('set_clip', {'clip_id': 'b', 'text': 'bad'})
    assert not result['ok'] and live()['tracks'][0]['clips'][1]['text'] == 'keep'


def test_limit_never_blocks_validation_or_reporting(draft, monkeypatch):
    monkeypatch.setattr(m, 'MAX_TOOL_CALLS', 1); monkeypatch.setattr(m, '_calls', 200)
    async def dispatch(name, args): return m._ok({'ok': True, 'name': name})
    monkeypatch.setattr(m, '_dispatch', dispatch)
    for name in ['validate_draft', 'report_result']:
        assert json.loads(asyncio.run(m.call_tool(name, {}))[0].text)['ok']

def test_batch_front_lane_survives_linked_audio_and_references_created_clip(draft, monkeypatch):
    (td._room_dir('room') / 'assets.json').write_text(json.dumps([{'id': 'v', 'kind': 'video', 'metadata': {'duration': 5}}]))
    result = tool('apply_edits', {'operations': [
        {'name': 'add_clip', 'args': {'asset_id': 'v', 'timeline_start': 0, 'duration': 5, 'lane': 'front', 'with_audio': True}},
        {'name': 'add_caption', 'args': {'text': 'created', 'timeline_start': 4, 'timeline_end': 5, 'lane': 'front'}},
        {'name': 'set_clip_props', 'args': {'clip_id': {'$result': 1, 'path': 'clip_id'}, 'props': {'text': 'finished'}}}
    ]})
    assert result['ok'] and result['timeline_updated'], result
    tracks = live()['tracks']
    assert tracks[-1]['clips'][0]['text'] == 'finished'
    assert any(t['type'] == 'audio' and t['clips'] for t in tracks)
    assert tracks[0]['clips'][0]['text'] == 'before'


@pytest.mark.parametrize('reference', [
    {'$result': 1, 'path': 'clip_id'},
    {'$result': 0, 'path': 'missing'},
    {'$result': True, 'path': 'clip_id'},
])
def test_invalid_batch_reference_rolls_back_published_timeline(draft, reference):
    before = copy.deepcopy(live())
    result = tool('apply_edits', {'operations': [
        {'name': 'set_clip', 'args': {'clip_id': 'a', 'text': 'must roll back'}},
        {'name': 'set_clip', 'args': {'clip_id': reference, 'text': 'bad'}}
    ]})
    assert result['rolled_back'] and live() == before
    assert td.load_draft('room', draft['draft_id'])['sequence'] == before
