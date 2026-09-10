import copy
import math
from app.services import timeline_commands as tc
from app.services.timeline_motion import animate


def test_edit_and_split_animated_text_preserve_motion_and_other_clips():
    seq={'tracks':[]}
    result=tc.add_caption(seq,text='Editable',timeline_start=2,timeline_end=6,lane=0)
    cid=result['clip_id']
    keys=[{'t':0,'x':-.2,'y':.1},{'t':4,'x':.2,'y':.3,'w':2,'h':2}]
    assert tc.set_clip_props(seq,{},clip_id=cid,props={'transform_keys':keys})['ok']
    other=tc.add_caption(seq,text='Unchanged',timeline_start=2,timeline_end=6,lane=1)
    untouched=copy.deepcopy(seq['tracks'][1])
    assert tc.set_clip(seq,clip_id=cid,text='New words')['ok']
    assert len(seq['tracks'][0]['clips'])==1
    assert seq['tracks'][0]['clips'][0]['transform_keys']==keys
    assert tc.split_clip(seq,clip_id=cid,at=4)['ok']
    clips=seq['tracks'][0]['clips']
    assert len(clips)==2 and all(c['text']=='New words' for c in clips)
    assert clips[0]['transform_keys'][-1]['x']==clips[1]['transform_keys'][0]['x']==0
    assert seq['tracks'][1]==untouched


def test_bad_motion_does_not_modify_text_and_locked_lane_rejects_placement():
    seq={'tracks':[]}
    cid=tc.add_caption(seq,text='Title',timeline_start=0,timeline_end=3,lane=0)['clip_id']
    before=copy.deepcopy(seq)
    for keys in [[{'t':0,'x':math.nan,'y':0}],[{'t':0,'x':0,'y':0,'w':0}],[{'t':0,'y':0}]]:
        assert not tc.set_clip_props(seq,{},clip_id=cid,props={'transform_keys':keys})['ok']
        assert seq==before
    seq['tracks'][0]['locked']=True
    assert not tc.add_caption(seq,text='Other',timeline_start=4,timeline_end=5,lane=0)['ok']


def test_motion_authoring_supports_text_and_offscreen_regions_without_fragmenting():
    seq={'tracks':[]}
    cap=tc.add_caption(seq,text='Title',timeline_start=0,timeline_end=2,lane=0)['clip_id']
    poses=[{'t':0,'x':-.4,'y':0,'w':1,'h':1},{'t':1,'x':0,'y':0,'w':1,'h':1}]
    assert animate(seq,{},cap,poses)['ok']
    assert len(seq['tracks'][0]['clips'])==1
    keys=seq['tracks'][0]['clips'][0]['transform_keys']
    assert keys[0]['x']==-.4 and keys[-1]['x']==0
    assert keys[15]['x']>-.2  # ease-out has passed the linear midpoint
    region=tc.add_region(seq,timeline_start=0,timeline_end=2,x=0,y=0,width=.2,height=.2,lane=1)['clip_id']
    assert animate(seq,{},region,poses)['ok']
    assert seq['tracks'][1]['clips'][0]['region_keys'][0]['x']==-.4
    before=copy.deepcopy(seq)
    assert not animate(seq,{},cap,[poses[1],poses[0]])['ok']
    assert seq==before
