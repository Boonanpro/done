"""Recover only geometry damaged by the observed missing-format conversion.

The matching committed draft is the source, and every restored property must
match the known 9:16 -> 16:9 conversion first. Refuse unrelated edits.
"""
import copy
import json
import math
import sys
import time
from app.services import timeline_draft as td, timeline_scope as scope

ROOM='a3970e0b-f7dc-472e-ad63-e8c51382ddb3'
CONTENT='277f96d8-2609-43e9-ba18-bcf3ea37f576'
DRAFT='c1e63b4ae8cb'

def equal(a,b):
    if isinstance(a,(int,float)) and isinstance(b,(int,float)):return math.isclose(a,b,abs_tol=1e-9)
    if isinstance(a,dict) and isinstance(b,dict):return a.keys()==b.keys() and all(equal(a[k],b[k]) for k in a)
    if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
    return a==b

def damaged_geometry(original):
    c=copy.deepcopy(original);k=81/256
    p=c.get('position')
    if p:
        x,w=p.get('x',0),p.get('width',1)
        p['x']=x+w/2-w*k/2;p['width']=w*k
    for key in c.get('transform_keys',[]):
        w=key.get('w',(original.get('position') or {}).get('width',1))
        key['x']=key['x']+w/2-w*k/2
        if 'w' in key:key['w']=w*k
    if 'text' in c:
        style=c.setdefault('style',{});style['fontSize']=style.get('fontSize',1)*16/9
    return c

def restore(sequence, source):
    out=copy.deepcopy(sequence);old=scope.clips(source);count=0
    for cid,(_,c) in scope.clips(out).items():
        if cid not in old:continue
        ref=old[cid][1];bad=damaged_geometry(ref)
        for key in ('position','transform_keys','style'):
            if equal(c.get(key),ref.get(key)):continue
            if not equal(c.get(key),bad.get(key)):
                raise ValueError(f'Unrelated change at {cid}.{key}; refusing automatic recovery')
            if key in ref:c[key]=copy.deepcopy(ref[key])
            else:c.pop(key,None)
            count+=1
    return out,count

if __name__=='__main__':
    with td.ContentsLock(ROOM):
        contents=td._read_contents_raw(ROOM);content=td._find_content(contents,CONTENT)
        source=td.load_draft(ROOM,DRAFT)['sequence']
        fixed,count=restore(content['timeline']['sequence'],source)
        print('geometry_properties_to_restore',count)
        if '--apply' in sys.argv and count:
            folder=td._room_dir(ROOM)/'recovery';folder.mkdir(exist_ok=True)
            backup=folder/f'before-aspect-recovery-{int(time.time())}.json'
            backup.write_text(json.dumps(contents,ensure_ascii=False,indent=2),encoding='utf-8')
            content['timeline']['sequence']=fixed
            content['timeline']['format']='16:9';content['format']='16:9'
            td._write_contents_raw(ROOM,contents)
            print('restored; backup',backup)
