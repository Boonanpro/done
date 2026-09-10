from app.services import timeline_commands as tc

def test_footage_created_after_caption_does_not_cover_it():
    seq={'tracks':[]}
    caption=tc.add_caption(seq,text='A quiet moment',timeline_start=12,timeline_end=15)
    assert caption['ok']
    footage=tc._track_of_type(seq,'video')
    footage['clips'].append({'id':'footage','timeline_start':0,'timeline_end':15})
    assert seq['tracks'][0] is footage
    assert seq['tracks'][-1]['clips'][0]['id']==caption['clip_id']

def test_existing_track_order_is_not_changed():
    video={'type':'video','clips':[]};caption={'type':'caption','clips':[]}
    seq={'tracks':[video,caption]}
    assert tc._track_of_type(seq,'video') is video
    assert seq['tracks']==[video,caption]
