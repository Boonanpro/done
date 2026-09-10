import copy
from app.services.timeline_commands import set_clip_props


def test_slowing_preserves_last_words_and_linked_video():
    clip={'id':'audio','asset_id':'media','link_id':'pair','timeline_start':2,'timeline_end':9,'source_start':3,'source_end':10}
    video=dict(clip,id='video')
    seq={'duration':12,'tracks':[{'type':'audio','clips':[clip]},{'type':'video','clips':[video]}]}
    assets={'media':{'id':'media','kind':'video','metadata':{'duration':30}}}
    result=set_clip_props(seq,assets,clip_id='audio',props={'speed':.5})
    assert result['ok']
    for c in (clip,video):
        assert (c['source_start'],c['source_end'])==(3,10)
        assert c['timeline_end']==16 and c['speed']==.5
    assert seq['duration']==16


def test_fixed_duration_requires_explicit_choice():
    clip={'id':'a','asset_id':'media','timeline_start':2,'timeline_end':9,'source_start':3,'source_end':10}
    seq={'duration':12,'tracks':[{'type':'audio','clips':[clip]}]}
    assets={'media':{'id':'media','kind':'audio','metadata':{'duration':30}}}
    assert set_clip_props(seq,assets,clip_id='a',props={'speed':.5,'keep_duration':True})['ok']
    assert clip['timeline_end']==9 and clip['source_end']==6.5
