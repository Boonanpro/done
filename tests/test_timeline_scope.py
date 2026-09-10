import copy
import json

import pytest

from app.services import timeline_draft as td, timeline_scope as scope, timeline_live as live


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(td, 'UPLOAD_ROOT', tmp_path)
    room = tmp_path / 'room'
    room.mkdir()
    seq = {'duration': 10, 'format': '16:9', 'frame_rate': 30, 'tracks': [
        {'id': 'v', 'type': 'video', 'clips': [
            {'id': 'a', 'text': '変更する字幕', 'timeline_start': 0, 'timeline_end': 5},
            {'id': 'b', 'text': '触らない字幕', 'timeline_start': 5, 'timeline_end': 10}]}]}
    (room / 'contents.json').write_text(json.dumps([{'id': 'content', 'timeline': {'sequence': seq}}]), encoding='utf-8')
    (room / 'assets.json').write_text('[]', encoding='utf-8')
    return seq


def test_selected_caption_changes_and_neighbor_is_identical(project):
    result = live.apply_edit('room', 'content', 'set_clip', {'clip_id': 'a', 'text': '修正後'},
                             scope.make_scope(project, ['a']), td.sequence_hash(project))
    assert result['committed']
    after = live.live_sequence('room', 'content')[1]
    assert after['tracks'][0]['clips'][0]['text'] == '修正後'
    assert after['tracks'][0]['clips'][1] == project['tracks'][0]['clips'][1]


def test_outside_selection_is_rejected_without_writing(project):
    result = live.apply_edit('room', 'content', 'set_clip', {'clip_id': 'b', 'text': '事故'},
                             scope.make_scope(project, ['a']))
    assert not result['ok']
    assert live.live_sequence('room', 'content')[1] == project


def test_manual_edit_after_utterance_is_preserved(project):
    old_hash = td.sequence_hash(project)
    live.apply_edit('room', 'content', 'set_clip', {'clip_id': 'b', 'text': '手編集'})
    result = live.apply_edit('room', 'content', 'set_clip', {'clip_id': 'a', 'text': '遅れたAI'},
                             scope.make_scope(project, ['a']), old_hash)
    assert result['conflict']
    assert live.live_sequence('room', 'content')[1]['tracks'][0]['clips'][1]['text'] == '手編集'


def test_split_stays_inside_selection(project):
    result = live.apply_edit('room', 'content', 'split_clip', {'clip_id': 'a', 'at': 2},
                             scope.make_scope(project, ['a']))
    assert result['committed']
    after = live.live_sequence('room', 'content')[1]
    assert scope.clips(after)['b'] == scope.clips(project)['b']


def test_no_selection_cannot_edit(project):
    after = copy.deepcopy(project)
    after['tracks'][0]['clips'][0]['text'] = '事故'
    assert scope.violations(project, after, scope.make_scope(project, []))


def test_approved_clip_cannot_change_even_when_selected(project):
    project['tracks'][0]['clips'][0]['approved'] = True
    after = copy.deepcopy(project)
    after['tracks'][0]['clips'][0]['text'] = '事故'
    assert scope.violations(project, after, scope.make_scope(project, ['a']))


def test_layer_and_project_changes_are_rejected(project):
    after = copy.deepcopy(project)
    after['tracks'][0]['hidden'] = True
    after['format'] = '9:16'
    assert len(scope.violations(project, after, scope.make_scope(project, ['a']))) >= 2


def test_new_effect_outside_selected_time_is_rejected(project):
    after = copy.deepcopy(project)
    after['tracks'].append({'id': 'fx', 'type': 'video', 'clips': [
        {'id': 'new', 'timeline_start': 0, 'timeline_end': 10, 'region': {'width': 1}}]})
    assert scope.violations(project, after, scope.make_scope(project, ['a']))


def test_linked_audio_is_included(project):
    project['tracks'][0]['clips'][0]['link_id'] = 'linked'
    project['tracks'].append({'id': 'audio', 'type': 'audio', 'clips': [
        {'id': 'sound', 'link_id': 'linked', 'timeline_start': 0, 'timeline_end': 5}]})
    assert scope.make_scope(project, ['a'])['clip_ids'] == ['a', 'sound']


def test_whole_project_cannot_cover_approved_shot(project):
    project['tracks'][0]['clips'][0]['approved'] = True
    after = copy.deepcopy(project)
    after['tracks'].append({'id': 'cover', 'type': 'video', 'clips': [
        {'id': 'overlay', 'timeline_start': 1, 'timeline_end': 4, 'region': {'width': 1}}]})
    assert scope.violations(project, after)


def test_whole_project_can_edit_unapproved_later_shot(project):
    project['tracks'][0]['clips'][0]['approved'] = True
    after = copy.deepcopy(project)
    after['tracks'][0]['clips'][1]['text'] = '新しい字幕'
    assert not scope.violations(project, after)


def test_draft_scope_is_enforced_at_final_commit(project):
    draft = td.create_draft('room', 'content')
    scope.attach(draft, ['a'])
    draft['sequence']['tracks'][0]['clips'][1]['text'] = 'エージェントの対象外変更'
    td.save_draft(draft)
    assert not td.commit_draft('room', draft['draft_id'], lambda *_: [])['ok']
    assert live.live_sequence('room', 'content')[1] == project


def test_legacy_lanes_allow_scoped_grade_but_protect_other_lanes(project):
    project['tracks'][0].pop('id')
    project['tracks'].append({'type': 'audio', 'clips': [
        {'id': 'sound', 'timeline_start': 0, 'timeline_end': 10}]})
    selected = scope.make_scope(project, ['a'])
    after = copy.deepcopy(project)
    after['tracks'][0]['clips'][0]['grade'] = {'ev': 0.7}
    assert not scope.violations(project, after, selected)
    after['tracks'][1]['muted'] = True
    assert scope.violations(project, after, selected)
    after = copy.deepcopy(project)
    after['tracks'].reverse()
    assert scope.violations(project, after, selected)


def test_invalid_grade_does_not_clear_existing_adjustments(project):
    from app.services import timeline_commands as commands
    project['tracks'][0]['clips'][0]['grade'] = {'ev': 0.4, 'contrast': 0.96}
    before = copy.deepcopy(project)
    result = commands.set_clip_props(project, {}, clip_id='a', props={'grade': {'brightness': 0.2}})
    assert not result['ok']
    assert project == before


def test_live_grade_on_legacy_lanes_commits_only_selected_clip(project):
    from app.services import editor_workflows
    project['tracks'][0].pop('id')
    project['tracks'][0]['clips'][0]['grade'] = {'ev': 0.4, 'contrast': 0.96}
    project['tracks'].append({'type': 'audio', 'clips': [
        {'id': 'sound', 'timeline_start': 0, 'timeline_end': 10}]})
    (td._room_dir('room') / 'contents.json').write_text(json.dumps([{'id':'content','timeline':{'sequence':project}}]), encoding='utf-8')
    state = editor_workflows.compact_state('room', 'content', 0)
    assert state['clips'][0]['grade'] == {'ev': 0.4, 'contrast': 0.96}
    result = live.apply_edit('room', 'content', 'set_clip_props',
        {'clip_id':'a', 'props':{'grade':{'ev':0.65,'contrast':0.96}}},
        scope.make_scope(project, ['a']), td.sequence_hash(project))
    assert result['committed']
    after = live.live_sequence('room', 'content')[1]
    expected = copy.deepcopy(project)
    expected['tracks'][0]['clips'][0]['grade']['ev'] = 0.65
    assert after == expected
