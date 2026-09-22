"""Replace the known broad 0.7s mask using inspected composited-frame bounds."""
import json
import sys
from app.services import timeline_draft as td,timeline_scope as scope,timeline_context as tcx
room=sys.argv[1]
content=td._read_contents_raw(room)[0];seq=content['timeline']['sequence']
c=scope.clips(seq)['fx_ag_25d62c8285'][1]
# At 85.54, .64, ...86.24: measured plate bounds with a small interpolation margin.
bounds=[(0,.00,.35,.44,.48),(.1,.00,.30,.44,.47),(.2,.00,.14,.45,.50),
        (.3,.00,.00,.48,.44),(.4,.025,.00,.54,.33),(.5,.09,.00,.55,.31),
        (.6,.07,.00,.56,.32),(.7,.05,.00,.57,.40)]
keys=[{'t':t,'x':x,'y':y,'w':w,'h':h} for t,x,y,w,h in bounds]
c['region_keys']=keys+[k for k in c['region_keys'] if k['t']>.7]
c['region']={k:v for k,v in zip(('x','y','width','height'),bounds[0][1:])}
td._write_contents_raw(room,[content])
print(tcx.render_timeline_frames(seq,str(td._room_dir(room)),[85.54,85.69,85.84,85.99,86.14,86.24]))
