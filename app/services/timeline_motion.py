"""Reusable motion authoring for text, media and region clips."""
import math
from app.services import timeline_commands as tc


def compile_keys(poses, fps=30, easing='cubic_out'):
    if easing not in {'linear','cubic_out','cubic_in_out'}:
        raise ValueError('easing: linear, cubic_out, cubic_in_out')
    if not isinstance(poses,list) or not 2 <= len(poses) <= 100:
        raise ValueError('poses needs 2–100 time/position/size points')
    points=[]
    for pose in poses:
        if not isinstance(pose,dict) or any(not isinstance(pose.get(k),(int,float)) or not math.isfinite(pose[k]) for k in ('t','x','y','w','h')):
            raise ValueError('each pose needs finite t,x,y,w,h')
        if pose['t']<0 or pose['w']<=0 or pose['h']<=0:
            raise ValueError('t >= 0; w,h > 0')
        points.append({k:float(pose[k]) for k in ('t','x','y','w','h')})
    if any(b['t']<=a['t'] for a,b in zip(points,points[1:])):
        raise ValueError('pose times must increase')
    if points[-1]['t']*fps>18000:
        raise ValueError('motion span exceeds 18000 samples')
    result=[]
    for a,b in zip(points,points[1:]):
        count=max(1,math.ceil((b['t']-a['t'])*fps))
        for i in range(count):
            f=i/count
            e=f if easing=='linear' else 1-(1-f)**3 if easing=='cubic_out' else 4*f**3 if f<.5 else 1-(-2*f+2)**3/2
            result.append({'t':round(a['t']+(b['t']-a['t'])*f,4),**{k:round(a[k]+(b[k]-a[k])*e,5) for k in ('x','y','w','h')}})
    result.append(points[-1])
    return result


def animate(seq,assets,clip_id,poses,easing='cubic_out'):
    if any(tr.get('type')=='audio' and any(c.get('id')==clip_id for c in tr.get('clips',[])) for tr in seq.get('tracks',[])):
        return {'ok':False,'error':'motion requires a visual clip'}
    clip=next((c for tr in seq.get('tracks',[]) for c in tr.get('clips',[]) if c.get('id')==clip_id),None)
    if clip is None:return {'ok':False,'error':'clip not found'}
    try:
        keys=compile_keys(poses,easing=easing)
        if keys[-1]['t']>clip['timeline_end']-clip['timeline_start']+.001:
            raise ValueError('motion exceeds clip duration')
    except ValueError as exc:return {'ok':False,'error':str(exc)}
    if clip.get('region') is not None:
        return tc.set_region(seq,clip_id=clip_id,keys=keys)
    return tc.set_clip_props(seq,assets,clip_id=clip_id,props={'transform_keys':keys})
