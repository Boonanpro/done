"""Prepare or apply frame-reviewed, editable finishing repairs."""
import copy,json,sys,time
from app.services import timeline_live as tl,timeline_draft as td,timeline_commands as tc,timeline_context as ctx
R='a3970e0b-f7dc-472e-ad63-e8c51382ddb3'; C='277f96d8-2609-43e9-ba18-bcf3ea37f576'
folder=td._room_dir(R)/'recovery'; state=folder/'finishing-draft.json'
if '--apply' in sys.argv:
    d=json.loads(state.read_text(encoding='utf-8'))
    _,live=tl.live_sequence(R,C)
    assert td.sequence_hash(live)==d['base_hash'],'Concurrent user edit'
    backup=folder/f'before-finishing-{int(time.time())}.json'
    backup.write_text(json.dumps(td._read_contents_raw(R),ensure_ascii=False),encoding='utf-8')
    result=td.commit_draft(R,d['draft_id'],lambda s,r:tc.validate_sequence(s,tl._assets(r),asset_dir=str(td._room_dir(r))))
    assert result['ok'],result
    print(result,backup)
else:
    d=td.create_draft(R,C);s=d['sequence']
    clips={c['id']:c for t in s['tracks'] for c in t['clips']}
    def keys(rows): return [dict(zip(('t','x','y','w','h'),r)) for r in rows]
    clips['fx_ag_12048ee972']['region_keys']=keys([
        (0,.245,.745,.105,.16),(.5,.248,.74,.11,.16),(1.2,.275,.73,.115,.17),
        (1.4,.305,.77,.12,.18),(1.6,.34,.72,.16,.25),(1.8,.40,.79,.15,.20),(2.1,.43,.87,.16,.13),(2.133,.43,.87,.17,.13)])
    c=clips['fx_ag_25d62c8285']
    c['region_keys']=[k for k in c['region_keys'] if k['t']<=.7]+keys([
        (.767,.10,0,.56,.44),(.967,.14,0,.60,.39),(1.167,.17,.06,.61,.59),
        (1.667,.36,.27,.57,.53),(2.067,.42,.22,.52,.51)])
    bg={'id':'repair_background_plate','style':'mosaic','effect_strength':22.,'timeline_start':83.4,'timeline_end':85.,
        'region':{'x':.88,'y':.40,'width':.075,'height':.07},
        'region_keys':keys([(0,.88,.40,.075,.07),(.5,.88,.40,.075,.07),(1.2,.91,.375,.07,.085),(1.4,.95,.37,.05,.085),(1.6,.99,.37,.01,.085)])}
    s['tracks'].insert(6,{'id':'repair_background_plate_lane','type':'video','clips':[bg]})
    for name,x,y,w,h in [('wall',.008,.414,.05,.056),('shirt',.485,.873,.03,.04)]:
        c=copy.deepcopy(clips['repair_pause_ending']);p=c['position']
        c.update(id='repair_screen_ui_'+name,timeline_start=167.2,timeline_end=168.7,source_start=180.396625,source_end=180.396625)
        if name=='shirt': c.update(source_start=178.196625,source_end=178.196625)
        c['crop']={'left':(x-p['x'])/p['width'],'top':(y-p['y'])/p['height'],
            'right':1-(x+w-p['x'])/p['width'],'bottom':1-(y+h-p['y'])/p['height']}
        s['tracks'].insert(6,{'id':'repair_ui_'+name+'_lane','type':'video','clips':[c]})
    errors=tc.validate_sequence(s,tl._assets(R),asset_dir=str(td._room_dir(R)))
    assert not errors,errors
    td.save_draft(d);state.write_text(json.dumps(d,ensure_ascii=False),encoding='utf-8')
    result=ctx.render_timeline_frames(s,str(td._room_dir(R)),[84.8,85.,85.2,86.4,86.5,86.6,167.5,168.3],out_dir=str(folder))
    print(json.dumps(result,ensure_ascii=True))
