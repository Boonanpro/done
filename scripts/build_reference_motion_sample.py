"""Editable eight-second reference-led motion acceptance sample (no paid generation).

Run with python -m scripts.build_reference_motion_sample. Original user content is
never modified. All typography remains text clips, artwork is region clips, and
audio is an original deterministic score. The MP4 is an export, not editing source.
"""
import json
import time
import uuid
import wave
from pathlib import Path

import numpy as np
from app.services import timeline_commands as tc, timeline_draft as td
from app.services.timeline_motion import compile_keys


def curve(poses, fps=30):
    """Clip-relative poses, cubic ease-out between each pair; seekable numeric keys."""
    return compile_keys([dict(zip(('t','x','y','w','h'),p)) for p in poses],fps=fps)


def build():
    started=time.monotonic()
    room='reference-motion-'+uuid.uuid4().hex[:8]; cid=str(uuid.uuid4())
    folder=td._room_dir(room);folder.mkdir(parents=True)
    seq={'format':'16:9','frame_rate':30,'duration':8,'tracks':[]}
    ink,paper,blue,lime,coral='#17263C','#F4F1E8','#4169E1','#DFFF70','#FF795D'
    def rectangle(name,start,end,x,y,w,h,color,poses=None):
        result=tc.add_region(seq,timeline_start=start,timeline_end=end,x=x,y=y,width=w,height=h,style='solid',color=color,lane=len(seq['tracks']))
        assert result['ok'],result
        c=next(c for tr in seq['tracks'] for c in tr['clips'] if c['id']==result['clip_id']);c['label']=name
        if poses: c['region_keys']=curve(poses)
        return c
    def text(name,words,start,end,x,y,size,color,poses=None,font='noto-sans'):
        result=tc.add_caption(seq,text=words,timeline_start=start,timeline_end=end,
            style={'font':font,'fontSize':size,'color':color,'outlineWidth':0,'x':x,'y':y,'maxWidth':.96},lane=len(seq['tracks']))
        assert result['ok'],result
        c=next(c for tr in seq['tracks'] for c in tr['clips'] if c['id']==result['clip_id']);c['label']=name
        if poses:
            result=tc.set_clip_props(seq,{},clip_id=c['id'],props={'transform_keys':curve(poses)})
            assert result['ok'],result
        return c

    # 0–2s: word additions cause a re-layout, then a scale/position hand-off.
    rectangle('paper',0,2,0,0,1,1,paper)
    text('opening label','余白書店  /  帰り道の、小さな寄り道。',0,1.5,0,.85,.38,ink)
    text('phrase one','帰り道に、',0,2,0,.45,2.3,ink,
         [(0,0,.32,1,1),(.3,0,0,1,1),(.5,0,0,1,1),(.82,-.20,-.10,1,1),(1.5,-.20,-.10,1,1),(2,-.45,-.65,1.6,1.6)])
    text('phrase two','ひとつの',.5,2,.18,.35,2.3,ink,
         [(0,0,.55,1,1),(.32,0,0,1,1),(1,0,0,1,1),(1.5,-.3,-.65,1.6,1.6)])
    rectangle('accent rule',1,2,.16,.68,.68,.012,blue,
              [(0,.16,.68,.002,.012),(.32,.16,.68,.68,.012),(1,.16,.68,.68,.012)])
    text('phrase three','出会いを。',1,2,0,.16,2.3,blue,
         [(0,0,.35,1,1),(.3,0,0,1,1),(.55,0,0,1,1),(1,-.3,-.7,1.6,1.6)])

    # 2–5s: three editorial book covers arrive in stagger; the chosen book expands.
    rectangle('book stage',2,5,0,0,1,1,ink)
    text('shelf heading','今日の気分で、選ぶ。',2,5,0,.82,.65,paper,
         [(0,0,-.20,1,1),(.35,0,0,1,1),(3,0,0,1,1)])
    for i,(label,color) in enumerate([('物語',coral),('詩集',blue),('旅',lime)]):
        start=2.12+i*.12;duration=5-start;x=.13+i*.27
        poses=[(0,x,1.05,.20,.48),(.45,x,.27,.20,.48),(1.55,x,.27,.20,.48)]
        # The center cover grows toward the viewer; flank covers leave the frame.
        if i==1:
            poses += [(2.05,.34,.18,.32,.65),(2.25,.34,.18,.32,.65),(duration,0,0,1,1)]
        else:
            poses += [(2.05,-.26 if i==0 else 1.06,.32,.20,.48),(duration,-.26 if i==0 else 1.06,.32,.20,.48)]
        rectangle('book '+label,start,5,x,.27,.20,.48,color,poses)
        # Decorations and type move on the same authored plane as each cover.
        def plane(p):
            t,xx,yy,w,h=p
            sx=w/.20;sy=h/.48
            return (t,xx-x*sx,yy-.27*sy,sx,sy)
        motion=[plane(p) for p in poses]
        text('book title '+label,label,start,5,x+.10-.5,.44,1.35,paper if i!=2 else ink,motion,font='mincho')
        text('book index '+label,f'0{i+1}  /  YOHAKU',start,5,x+.10-.5,.64,.24,paper if i!=2 else ink,motion)
        text('book subtitle '+label,['まだ知らない、誰かへ。','言葉の間に、ひと息。','ここではない、どこかへ。'][i],start,5,x+.10-.5,.29,.22,paper if i!=2 else ink,motion)

    # 5–8s: one continuous type reveal and a readable final hold.
    rectangle('final blue',5,8,0,0,1,1,blue)
    rectangle('final accent',5.1,8,.065,.18,.02,.62,lime,
              [(0,.065,.8,.02,.002),(.45,.065,.18,.02,.62),(2.9,.065,.18,.02,.62)])
    text('brand','余白書店',5,8,0,.37,3,paper,
         [(0,-.70,-.8,2.4,2.4),(.55,0,0,1,1),(3,0,0,1,1)],font='dela-gothic')
    text('brand eyebrow','本と出会う。自分に戻る。',5.35,8,0,.69,.57,lime,
         [(0,0,.14,1,1),(.35,0,0,1,1),(2.65,0,0,1,1)])
    text('invitation','いつもの帰り道に、寄り道を。',5.7,8,0,.19,.65,paper,
         [(0,0,.2,1,1),(.4,0,0,1,1),(2.3,0,0,1,1)])

    # Original restrained percussive score; onset array is shared with picture beats.
    sr=24000; audio=np.zeros(sr*8,dtype=np.float64);rng=np.random.default_rng(17)
    def add(at,freq,dur,gain,pluck=True):
        t=np.arange(round(sr*dur))/sr
        env=(1-np.exp(-t*180))*np.exp(-t*(5 if pluck else 1.7))
        signal=(np.sin(2*np.pi*freq*t)+.2*np.sin(4*np.pi*freq*t))*env*gain
        j=round(at*sr);n=min(len(signal),len(audio)-j)
        if n>0:audio[j:j+n]+=signal[:n]
    for beat in np.arange(0,7.6,.5):
        add(float(beat),65.406 if beat<5 else 87.307,.32,.20)
    for at,f in [(0,261.626),(.5,329.628),(1,391.995),(2,293.665),(2.12,329.628),(2.24,391.995),(2.36,493.883),(4,523.251),(5,349.228),(5,440),(5,523.251),(6,659.255)]:
        add(at,f,1.2,.075)
    for at in [1.75,4.75]:
        n=int(sr*.25);t=np.linspace(0,1,n);noise=rng.normal(0,1,n);noise=np.convolve(noise,np.ones(12)/12,mode='same')
        audio[round(at*sr):round(at*sr)+n]+=noise*np.sin(t*np.pi)**2*.16
    audio[-sr:]*=np.linspace(1,0,sr);audio=np.clip(audio,-.9,.9)
    wav=folder/'original-score.wav'
    with wave.open(str(wav),'wb') as f:
        f.setparams((1,2,sr,0,'NONE','not compressed'));f.writeframes((audio*32767).astype('<i2').tobytes())
    aid=str(uuid.uuid4());assets=[{'id':aid,'kind':'audio','filename':wav.name,'local_path':str(wav.resolve()),'duration':8}]
    tc.add_audio(seq,{aid:assets[0]},asset_id=aid,source_start=0,duration=8,at=0,volume=.9,role='music')
    content={'id':cid,'room_id':room,'title':'余白書店 — 動きと音の8秒見本','format':'16:9','timeline':{'format':'16:9','sequence':seq},'asset_ids':[aid],
        'creative_brief':{'intent':'仕事帰りに一冊と出会う寄り道をしたくなる。','references':'①の単語追加による配置変化、緩急、拡大から引く切替を別内容に適用。','constraints':'有料生成なし。文字・図形は個別編集可能。'}}
    (folder/'contents.json').write_text(json.dumps([content],ensure_ascii=False),encoding='utf-8')
    (folder/'assets.json').write_text(json.dumps(assets,ensure_ascii=False),encoding='utf-8')
    result={'room_id':room,'content_id':cid,'seconds_to_assemble':round(time.monotonic()-started,3),'text_clips':sum(bool(c.get('text')) for tr in seq['tracks'] for c in tr['clips'])}
    Path('uploads/reference-motion-latest.json').write_text(json.dumps(result),encoding='utf-8')
    print(json.dumps(result),flush=True)
    return result


if __name__=='__main__':build()
