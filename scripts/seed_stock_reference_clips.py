"""Register inspected, locally cached Pexels excerpts with source provenance."""
import json,hashlib,shutil
from pathlib import Path

ROWS=[
 ('villa','34667982','緑の山と白い家','just a hobby',
  'Vertical aerial video slowly moving sideways past a white modern house, green fields and wooded mountains under a clear blue sky. Bright natural daylight, calm architectural/lifestyle establishing shot. No people or fictional technology. Source location is not verified as Japan.'),
 ('car','3048178','車内で仕事をする距離感','fauxels',
  'Horizontal observational close video of a woman in a burgundy jacket typing on a laptop in a car back seat. Soft subdued daylight, slow downward camera movement towards her hands and computer. Realistic mobile-work detail shot, not a Cybercab or autonomous-driving demonstration.'),
 ('city','11933153','夜の都市を見渡す','Gerson Bahena',
  'Vertical high-angle night cityscape with illuminated dense buildings and long red traffic avenues under a dark purple sky. Very restrained camera movement, cinematic urban establishing view. Location is not verified as Osaka; no characters or interior scenes.'),
]

def main():
 path=Path('docs/reference-library.json');rows=json.loads(path.read_text(encoding='utf8'))
 for name,source,title,author,description in ROWS:
  ident='stock-'+name;src=Path('scratch/visual-decision/sources')/(ident+'.mp4')
  target=Path('uploads/reference-library')/(ident+'.mp4');shutil.copyfile(src,target)
  rows=[r for r in rows if r['id']!=ident]
  rows.append({'id':ident,'title':title,'description':description,'family':'lifestyle-'+name,
   'kind':'video','extension':'.mp4','source_url':'https://www.pexels.com/video/'+source+'/',
   'attribution':author+' / Pexels','license':'Pexels License','license_source':'https://www.pexels.com/license/',
   'source_range':{'start':0,'duration':7},'inspection':'One-second contact frames visually inspected; browser playback pending',
   'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'reproduction_status':'reference_only','original_work':False})
 path.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8');print('added',len(ROWS),'total',len(rows))

if __name__=='__main__':main()
