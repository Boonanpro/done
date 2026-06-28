import json
from collections import Counter
import poc1
from gi.repository import Gst, GES
Gst.init(None); GES.init()
class A: pass
a=A(); a.max=0; a.no_pip=False; a.no_audio=False; a.transform=True; a.width=1080; a.height=1920; a.fps=30
base='D:/done/uploads/production-assets/bd05fcc0-c143-4d1c-828e-7624e087b6c1'
by,_=poc1.load_clips(base+'/contents.json')
tl,counts,na=poc1.build_timeline(by, base, a)
p=GES.Pipeline(); p.set_timeline(tl)
p.set_property('video-sink', Gst.ElementFactory.make('fakesink'))
p.set_mode(GES.PipelineFlags.FULL_PREVIEW)
p.set_state(Gst.State.PAUSED); p.get_state(Gst.SECOND*10)
c=Counter()
it=p.iterate_recurse()
while True:
    ok,el=it.next()
    if ok==Gst.IteratorResult.DONE: break
    if ok!=Gst.IteratorResult.OK: continue
    f=el.get_factory()
    if f:
        n=f.get_name()
        if any(k in n for k in ('compositor','mixer','convert','scale','upload','download','videobox','aggregat','dec')):
            c[n]+=1
print(json.dumps(dict(c), indent=2))
p.set_state(Gst.State.NULL)
