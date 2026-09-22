"""Explicit offline curation. Reuses existing previews; never runs in a conversation."""
import asyncio,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

async def main():
 import httpx
 from app.services.editor_reference_library import CATALOG,MEDIA
 rows=json.loads(CATALOG.read_text(encoding='utf-8'));existing={r['id'] for r in rows}
 sources=[
 ('visual-voice-06ce5f6b','5635b8785a8d','caption-serif','Warm ivory Japanese serif title on charcoal and muted gold. One line, gentle upward fade. No bounce. 6-second editable typography sample.'),
 ('visual-voice-06ce5f6b','971e7dcd8907','caption-sans','Warm ivory Japanese sans-serif single line on charcoal. Small horizontal fade-in, no bounce. 6-second editable typography sample.'),
 ('visual-voice-06ce5f6b','e5c4eac9c3f2','caption-two-line','Two Japanese lines, second phrase larger and appears later. Warm ivory, charcoal background, subtle rise/fade. 6-second typography comparison, not footage.'),
 ('visual-voice-06ce5f6b','ec6dcb660f83','caption-serif','Japanese serif caption with only the phrase ひと息 highlighted in gold, other text ivory. Slow soft fade-in over 2.9 seconds, charcoal background. No bounce. Local editable sample.'),
 ('visual-voice-96dc804c','e34609f1898f','diagram-chat','Animated before/after comparison: orange incomplete messages repeatedly travel back and forth on top; one complete teal message travels once below. Minimal flat explanatory graphics, no live people.'),
 ('visual-voice-96dc804c','7804f32b28a1','diagram-bridge','Animated before/after: a person icon cannot cross an incomplete bridge above; information tiles form a complete bridge below allowing the icon to cross. Flat conceptual metaphor, not live action.'),
 ('visual-voice-96dc804c','6773c9ff7c1f','diagram-chat','Before/after: repeated questions above; five numbered teal pieces gather into one message below, pause, then travel to recipient in 1.8 seconds. Minimal flat animation, no live action.'),
 ('visual-voice-96dc804c','5456bbb95d3c','diagram-chat','Same five-piece gathering and repeated questions comparison, but completed message travels slowly over 3 seconds. Only travel speed differs from 6773c9ff7c1f. Minimal flat animation.'),
 ]
 for room,ident,family,description in sources:
  if ident in existing:continue
  contents=json.loads((ROOT/'uploads/production-assets'/room/'contents.json').read_text(encoding='utf-8'))
  item=next(i for c in contents for g in c.get('proposal_history',[]) for i in g['items'] if i['id']==ident)
  kind=item['kind']
  rows.append({'id':ident,'title':item['title'],'description':description,'family':family,'kind':kind,kind:item[kind],
    'source_url':'','inspection':'Existing Dan generic test sample, previously rendered; recheck at multiple times before accepting.','origin':{'room':room,'item':ident}})
 media=[('mdn-flower','静かな花の接写','https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4','https://interactive-examples.mdn.mozilla.net/pages/tabbed/video.html'),
        ('samplelib-road','街の道路','https://download.samplelib.com/mp4/sample-5s.mp4','https://samplelib.com/sample-mp4.html')]
 async with httpx.AsyncClient(timeout=30,follow_redirects=True) as client:
  for ident,title,url,source in media:
   if ident in existing:continue
   path=MEDIA/(ident+'.mp4')
   if not path.exists():
    response=await client.get(url);response.raise_for_status();path.write_bytes(response.content)
   rows.append({'id':ident,'title':title,'description':'Pending visual inspection; exclude from decisions until inspected.','family':ident,'kind':'video','extension':'.mp4','source_url':source,'url':url,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'inspection':'pending'})
 descriptions={
  'mdn-flower':'Five-second live-action time-lapse close-up of a pink flower opening, shallow depth of field and green leaves. Fixed viewpoint, no people, no CGI. Motion of petals is visible; this is accelerated natural motion, not real-time.',
  'samplelib-road':'5.7-second real outdoor video looking across a leafy park toward a street. Cars and a bus move behind trees; slight handheld camera movement and daylight shadows. Not CGI, not an indoor or people-focused scene.'}
 for row in rows:
  if row['id'] in descriptions:
   row['description']=descriptions[row['id']];row['inspection']='Frames inspected at start, middle and end, duration measured; playback checked separately.'
 CATALOG.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'references':len(rows),'new':len(rows)-len(existing)}))

if __name__=='__main__':asyncio.run(main())
