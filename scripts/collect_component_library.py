"""Offline import of upstream reusable blocks, pinned to one source revision."""
import asyncio,json,sys,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'scratch/component-expansion';OUT.mkdir(parents=True,exist_ok=True)

async def discover():
 import httpx
 async with httpx.AsyncClient(timeout=30,follow_redirects=True) as client:
  r=await client.get('https://api.github.com/repos/heygen-com/hyperframes/commits/main');r.raise_for_status();sha=r.json()['sha']
  base=f'https://raw.githubusercontent.com/heygen-com/hyperframes/{sha}'
  r=await client.get(base+'/registry/registry.json');r.raise_for_status();registry=r.json()
  sem=asyncio.Semaphore(8)
  async def get(row):
   async with sem:
    r=await client.get(base+'/registry/blocks/'+row['name']+'/registry-item.json')
    if r.status_code==200:return r.json()
  rows=await asyncio.gather(*(get(r) for r in registry['items'] if r['type']=='hyperframes:block'))
  data={'revision':sha,'base':base,'items':[r for r in rows if r]};(OUT/'discovered.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
  usable=[r for r in data['items'] if r.get('preview',{}).get('video')]
  print(json.dumps({'revision':sha,'blocks':len(data['items']),'with_video':len(usable),'names':[r['name'] for r in usable]}))

GROUPS={
 'captions':['caption-blend-difference','caption-camera-follow','caption-clip-wipe','caption-editorial-emphasis','caption-emoji-pop','caption-glitch-rgb','caption-kinetic-slam','caption-matrix-decode','caption-parallax-layers','caption-particle-burst','caption-pill-karaoke','caption-weight-shift'],
 'data':['data-chart','flowchart','oscilloscope-trace','apple-money-count'],
 'code':['code-3d-extrude','code-diff','code-highlight','code-morph','code-particle-assemble','code-scroll','code-shader-dissolve','code-typing'],
 'camera':['cinematic-zoom','whip-pan','ui-3d-reveal','app-showcase'],
 'transition':['chromatic-radial-split','cross-warp-morph','domain-warp-dissolve','flash-through-white','glitch','gravitational-lens','ridged-burn','ripple-waves','sdf-iris','swirl-vortex','thermal-distortion','transitions-3d','transitions-grid','transitions-mechanical','transitions-radial'],
 'editorial':['camcorder-hud','editorial-flash-overlay','freeze-frame-dressing','light-leak','organic-light-leak-overlay'],
 'interface':['ios26-liquid-glass','liquid-glass-context-menu','liquid-glass-media-controls','liquid-glass-notification','liquid-glass-widgets','macos-notification'],
 'geography':['nyc-paris-flight','spain-map','us-map','us-map-bubble','us-map-flow','us-map-hex','world-map'],
 'social':['reddit-post','spotify-card','x-post','yt-lower-third','instagram-follow'],
 'vfx':['vfx-liquid-background','vfx-liquid-glass','vfx-magnetic','vfx-portal','vfx-shatter','vfx-text-cursor'],
 'brand':['logo-outro'],
}

async def collect():
 import httpx
 data=json.loads((OUT/'discovered.json').read_text(encoding='utf-8'));rows={r['name']:r for r in data['items']}
 dest=ROOT/'app/data/component-library';dest.mkdir(parents=True,exist_ok=True)
 media=ROOT/'uploads/reference-library';media.mkdir(parents=True,exist_ok=True)
 sem=asyncio.Semaphore(6);failures=[]
 async with httpx.AsyncClient(timeout=60,follow_redirects=True) as client:
  existing_manifest=ROOT/'docs/component-library.json'
  existing={r['id']:r for r in json.loads(existing_manifest.read_text(encoding='utf-8'))} if existing_manifest.exists() else {}
  license_response=await client.get(data['base']+'/LICENSE');license_response.raise_for_status();(dest/'LICENSE').write_bytes(license_response.content)
  async def fetch(name,family):
   async with sem:
    try:
     category='components' if name.startswith('caption-') else 'blocks'
     if name not in rows:
      r=await client.get(data['base']+'/registry/'+category+'/'+name+'/registry-item.json');r.raise_for_status();rows[name]=r.json()
     row=rows[name];folder=dest/name;folder.mkdir(parents=True,exist_ok=True)
     sources=[]
     for f in row['files']:
      relative=Path(f['path'])
      if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe source path')
      target=folder/relative;target.parent.mkdir(parents=True,exist_ok=True)
      url=data['base']+'/registry/'+category+'/'+name+'/'+f['path']
      if not target.exists():
       r=await client.get(url);r.raise_for_status();target.write_bytes(r.content)
      sources.append({'file':f['path'],'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
     ident='hf-'+name;path=media/(ident+'.mp4')
     if not path.exists():
      r=await client.get(row['preview']['video']);r.raise_for_status();path.write_bytes(r.content)
     (folder/'registry-item.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
     record={'id':ident,'title':row['title'],'description':row['description'],'family':family,'kind':'video','extension':'.mp4','inspection':'pending',
       'source_url':f'https://github.com/heygen-com/hyperframes/tree/{data["revision"]}/registry/{category}/{name}',
       'url':row['preview']['video'],'revision':data['revision'],'license':'Apache-2.0; retain upstream notices; verify referenced external media when adapting',
       'component':name,'tags':row.get('tags',[]),'variables':row.get('variables',row.get('params',[])),
       'dimensions':row.get('dimensions'),'duration':row.get('duration'),'files':sources,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
     old=existing.get(ident,{})
     if old.get('sha256')==record['sha256'] and old.get('files')==sources:
      record['inspection']=old['inspection']
      if old.get('measured'):record['measured']=old['measured']
     return record
    except Exception as e:failures.append({'name':name,'error':str(e)});return None
  found=await asyncio.gather(*(fetch(n,g) for g,ns in GROUPS.items() for n in ns))
  catalog=[r for r in found if r]
  (ROOT/'docs/component-library.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')
  (OUT/'import-results.json').write_text(json.dumps({'imported':len(catalog),'failures':failures},indent=2),encoding='utf-8')
  print(json.dumps({'imported':len(catalog),'families':len({r['family'] for r in catalog}),'failures':failures}))

if __name__=='__main__':asyncio.run(collect() if '--collect' in sys.argv else discover())
