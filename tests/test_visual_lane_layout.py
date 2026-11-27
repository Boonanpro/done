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
