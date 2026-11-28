from app.services.visual_lane_layout import assign_added, compact


def test_reuse_role_lanes_without_reordering_overlapping_images_and_words():
    def clip(key, a, b, layer, **more):
        return dict(id=key, timeline_start=a, timeline_end=b, layer=layer, **more)
    pic = clip('page', 0, 4, 5)
    other = clip('next', 4, 7, 9)
    word = clip('question', 0, 4, 11, track='caption')
    seal = clip('seal', 1, 2, 13)
    seq = {'tracks': [{'type': 'video', 'clips': [pic, other, seal]}, {'type': 'caption', 'clips': [word]}]}
    assert compact(seq)['moved'] == 4
    assert [c['layer'] for c in [pic, other, word, seal]] == [1, 1, 2, 3]
    assert compact(seq)['moved'] == 0
    later = clip('later', 7, 8, 14, track='caption')
    seq['tracks'][1]['clips'].append(later)
    assign_added(seq, 'later', front=True)
    assert later['layer'] == 2


def test_draft_collision_moves_the_added_clip_even_when_it_starts_first(tmp_path, monkeypatch):
    import json
    from app.services import timeline_commands as commands, timeline_draft as drafts, timeline_live

    monkeypatch.setattr(drafts, 'UPLOAD_ROOT', tmp_path)
    room = tmp_path / 'test'
    room.mkdir()
    old = dict(id='old', text='先に置いた字幕', layer=2, timeline_start=2, timeline_end=5)
    seq = {'duration': 5, 'tracks': [{'type': 'caption', 'id': 'sub', 'clips': [old]}]}
    (room / 'contents.json').write_text(json.dumps([{'id': 'work', 'timeline': {'sequence': seq}}]))
    draft = drafts.create_draft('test', 'work')
    new = dict(id='added', text='重ねて出す字幕', layer=2, timeline_start=0, timeline_end=4)
    draft['sequence']['tracks'][0]['clips'].insert(0, new)
    drafts.save_draft(draft)
    result = drafts.commit_draft('test', draft['draft_id'], lambda s, _: commands.validate_sequence(s, {}))
    assert result['ok'], result
    saved = timeline_live.live_sequence('test', 'work')[1]
    assert saved['tracks'][0]['clips'] == [old]
    assert saved['tracks'][1]['clips'] == [{**new, 'layer': 3}]


def test_live_tool_can_place_a_caption_over_an_occupied_display_lane(tmp_path, monkeypatch):
    import json
    from app.services import timeline_draft as drafts, timeline_live

    monkeypatch.setattr(drafts, 'UPLOAD_ROOT', tmp_path)
    room = tmp_path / 'test'
    room.mkdir()
    old = dict(id='old', text='元の字幕', layer=2, timeline_start=0, timeline_end=5)
    seq = {'duration': 5, 'tracks': [{'type': 'caption', 'clips': [old]}]}
    (room / 'contents.json').write_text(json.dumps([{'id': 'work', 'timeline': {'sequence': seq}}]))
    result = timeline_live.apply_edit('test', 'work', 'add_caption', dict(
        text='新しい字幕', timeline_start=1, timeline_end=3, style={'outlineOpacity': 0.35}))
    assert result.get('committed'), result
    tracks = timeline_live.live_sequence('test', 'work')[1]['tracks']
    assert tracks[0]['clips'] == [old]
    added = tracks[1]['clips'][0]
    assert (added['layer'], added['timeline_start'], added['timeline_end']) == (3, 1, 3)
    assert added['style']['outlineOpacity'] == .35
