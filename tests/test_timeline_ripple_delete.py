from app.services import timeline_commands as tc


def _seq():
    # base picture cut into frame-exact pieces (n/30 s), its linked sound, a caption plate
    # crossing the cut, a caption after it, and a still that starts inside the cut
    v = {'id': 'v', 'type': 'video', 'clips': [
        {'id': 'v1', 'asset_id': 'pic', 'link_id': 'l1', 'timeline_start': 0.0, 'timeline_end': 331.5,
         'source_start': 0.0, 'source_end': 331.5},
        {'id': 'v2', 'asset_id': 'pic', 'link_id': 'l2', 'timeline_start': 331.5, 'timeline_end': 340.1333,
         'source_start': 331.5, 'source_end': 340.1333},
        {'id': 'v3', 'asset_id': 'pic', 'link_id': 'l3', 'timeline_start': 340.1333, 'timeline_end': 341.2,
         'source_start': 340.1333, 'source_end': 341.2}]}
    a = {'id': 'a', 'type': 'audio', 'clips': [
        {'id': 'a1', 'asset_id': 'pic', 'link_id': 'l1', 'timeline_start': 0.0, 'timeline_end': 331.5,
         'source_start': 0.0, 'source_end': 331.5},
        {'id': 'a2', 'asset_id': 'pic', 'link_id': 'l2', 'timeline_start': 331.5, 'timeline_end': 340.1333,
         'source_start': 331.5, 'source_end': 340.1333},
        {'id': 'a3', 'asset_id': 'pic', 'link_id': 'l3', 'timeline_start': 340.1333, 'timeline_end': 341.2,
         'source_start': 340.1333, 'source_end': 341.2}]}
    c = {'id': 'c', 'type': 'caption', 'clips': [
        {'id': 'c1', 'asset_id': 'plate1', 'kind': 'image', 'timeline_start': 330.0, 'timeline_end': 333.0,
         'source_start': 0.0, 'source_end': 3.0},
        {'id': 'c2', 'asset_id': 'plate2', 'kind': 'image', 'timeline_start': 333.0, 'timeline_end': 334.0,
         'source_start': 0.0, 'source_end': 1.0}]}
    o = {'id': 'o', 'type': 'video', 'clips': [
        {'id': 's1', 'asset_id': 'still', 'kind': 'image', 'timeline_start': 331.8, 'timeline_end': 335.0,
         'source_start': 0.0, 'source_end': 3.2,
         'transform_keys': [{'t': 0, 'x': 0, 'y': 0, 'w': 1, 'h': 1}, {'t': 2.0, 'x': -0.1, 'y': -0.1, 'w': 1.2, 'h': 1.2}]}]}
    return {'tracks': [v, o, c, a]}


def test_ripple_delete_closes_the_gap_on_every_lane_and_keeps_sound_in_step():
    seq = _seq()
    a, b = 9945 / 30, 9968 / 30          # the misspoken word: 23 frames
    d = b - a
    r = tc.ripple_delete(seq, timeline_start=a, timeline_end=b)
    assert r['ok'], r
    v, o, c, au = seq['tracks']
    # the picture piece that held the word now starts after it in the source, at the cut point
    v2 = next(x for x in v['clips'] if x['id'] == 'v2')
    assert abs(v2['timeline_start'] - a) < 1e-3 and abs(v2['source_start'] - b) < 1e-3
    assert abs(v2['timeline_end'] - (340.1333 - d)) < 1e-3
    # linked sound moved exactly with its picture
    a2 = next(x for x in au['clips'] if x['id'] == 'a2')
    assert (a2['timeline_start'], a2['timeline_end'], a2['source_start']) == (v2['timeline_start'], v2['timeline_end'], v2['source_start'])
    # later clips shifted by the span length; no gaps on the base lane
    ends = sorted((x['timeline_start'], x['timeline_end']) for x in v['clips'])
    assert all(abs(p[1] - q[0]) < 1e-3 for p, q in zip(ends, ends[1:]))
    assert abs(seq['duration'] - (341.2 - d)) < 1e-3
    # caption crossing the cut got shorter, the next one moved up and still touches it
    c1, c2 = c['clips']
    assert abs(c1['timeline_end'] - (333.0 - d)) < 1e-3 and abs(c2['timeline_start'] - (333.0 - d)) < 1e-3
    # a still starting inside the span now starts at the cut, its motion re-based
    s1 = o['clips'][0]
    assert abs(s1['timeline_start'] - a) < 1e-3 and abs(s1['timeline_end'] - (335.0 - d)) < 1e-3
    assert s1['transform_keys'][0]['t'] == 0.0 and s1['transform_keys'][0]['w'] > 1.0


def test_moving_frame_exact_neighbours_one_by_one_does_not_collide():
    # the old 1e-6 test refused a move when ms rounding left a sub-millisecond overlap
    seq = _seq()
    d = 23 / 30
    seq['tracks'] = [seq['tracks'][0]]
    v = seq['tracks'][0]
    v['clips'] = [x for x in v['clips'] if x['id'] != 'v1']
    for cid in ('v2', 'v3'):
        clip = next(x for x in v['clips'] if x['id'] == cid)
        r = tc.move_clip(seq, clip_id=cid, new_start=clip['timeline_start'] - d)
        assert r['ok'], r


def test_one_frame_clip_is_a_valid_clip():
    seq = {'tracks': [{'id': 'v', 'type': 'video', 'clips': [
        {'id': 'f', 'asset_id': 'pic', 'timeline_start': 363.4333, 'timeline_end': 363.4666, 'source_start': 1.0, 'source_end': 1.0333}]}]}
    probs = tc.validate_sequence(seq, {'pic': {'id': 'pic', 'kind': 'video', 'metadata': {'duration': 10}}})
    assert not any('length' in p for p in probs), probs
