"""Inspected excerpts, not Dan creations. Source + attribution stay with each row."""
import json,subprocess,hashlib
from pathlib import Path
import imageio_ffmpeg
ROOT=Path(__file__).resolve().parents[1]
SOURCES=ROOT/'scratch/visual-decision/sources'
MEDIA=ROOT/'uploads/reference-library'
CASES=[
 ('sintel','snow',1,7,'雪山の冒険','Wide snowy mountains to a stylized young woman traveling in a blizzard. Muted grey light, environmental scale, cinematic fantasy adventure. 3D animation, not live action.'),
 ('sintel','dialogue',12,4,'暖かな室内の対話','Alternating close shots of an older bearded man and a young woman in a dim warm interior. Stylized 3D dramatic dialogue, weathered face and controlled shadows.'),
 ('sintel','emotion',27,5,'夕日の表情','A young animated woman reacts and reaches toward a small dragon against a golden sunset. Close-ups and reverse views with short dark fades, warm rim light, emotional character focus, polished stylized 3D fantasy.'),
 ('sintel','landscape',36,4,'砂丘の広がり','Wide golden dunes under a pale sky, an isolated traveler gives scale. Quiet expansive fantasy landscape, stylized 3D, not footage of a real mountain villa.'),
 ('tears','human',1,3,'実写の表情と距離','Live-action woman followed by a young man in close-up outdoors by a canal. Shallow depth of field, natural skin, restrained serious emotion and warm greenery. Cinematic conversation reference, not an animated avatar.'),
 ('tears','scifi',6,8,'実写とSFの融合','Dark live-action science-fiction teaser montage with mechanical equipment and a hologram-like futuristic display. Cool desaturated tones, detailed practical surfaces and composited VFX. Not peaceful lifestyle footage.'),
 ('tears','interior',32,2,'静かな室内の緊張','Live-action dim blue-grey industrial interior with people, foreground silhouettes and window light. Restrained cinematic tension, deep layered framing, not colorful cartoon.'),
 ('bunny','comedy',19,4,'森のキャラクターアニメ','A group of small cartoon animals in a lush green forest. Polished stylized 3D, dappled shadows and comic character acting. Animated comedy, not live action.'),
]

def main():
 catalog=ROOT/'docs/reference-library.json';rows=json.loads(catalog.read_text(encoding='utf8'));known={r['id'] for r in rows}
 ff=imageio_ffmpeg.get_ffmpeg_exe()
 for film,name,start,duration,title,description in CASES:
  ident='film-'+film+'-'+name;source=SOURCES/(film+('.mov' if film=='bunny' else '.mp4'));out=MEDIA/(ident+'.mp4')
  subprocess.run([ff,'-v','error','-y','-ss',str(start),'-i',str(source),'-t',str(duration),'-vf','scale=640:-2','-c:v','libx264','-crf','22','-preset','fast','-c:a','aac','-b:a','96k','-movflags','+faststart',str(out)],check=True)
  rows=[r for r in rows if r['id']!=ident]
  project={'sintel':'sintel','tears':'tears-of-steel','bunny':'big-buck-bunny'}[film]
  rows.append({'id':ident,'title':title,'description':description,'family':'film-'+name,'kind':'video','extension':'.mp4',
   'source_url':'https://studio.blender.org/films/'+project+'/', 'attribution':'Blender Foundation / '+project,
   'license':'CC BY (see original film attribution)', 'license_source':'https://studio.blender.org/remixing/',
   'source_range':{'start':start,'duration':duration},'inspection':'Contact sheet visually inspected; excerpt playback verification pending',
   'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'reproduction_status':'reference_only',
   'technique_notes':description,'original_work':False})
 catalog.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8');print('added',len(CASES),'total',len(rows))

if __name__=='__main__':main()
