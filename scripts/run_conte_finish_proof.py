"""Two six-second comparisons; durable Google receipts prevent repeated charges."""
import json
from pathlib import Path
from app.services.google_video import generate

OUT=Path(__file__).resolve().parents[1]/'exports/conte-finish-proof'
PROMPT='''One continuous six-second photorealistic film shot inside a modest Japanese inventor's workshop. Preserve the same one Japanese male engineer in navy work jacket and khaki trousers, the same fabricated aluminum winged prototype car, workbench, daylight, materials and layout from the appearance image. At 0 seconds he stands on the left facing the vehicle. During 0-3 seconds he walks a short distance toward its nearest front wheel, without touching or crossing through the wing. During 3-4.5 seconds he smoothly crouches beside the wheel, facing it. During 4.5-6 seconds he holds that crouched inspection pose. The car and workbench remain completely stationary. Locked camera, single continuous shot, no cuts, no additional people, no text, no cartoon or clay geometry. Realistic foot contact and body mechanics. Quiet workshop room tone and footsteps, no speech or music.'''

if __name__=='__main__':
    cases=[('guided',dict(reference_path=str(OUT/'motion-guide.mp4'),reference_mode='edit',appearance_reference_path=str(OUT/'appearance.png'))),
           ('image_only',dict(reference_path=str(OUT/'appearance.png'),reference_mode='style'))]
    records={}
    for name,args in cases:
        print('Generating '+name,flush=True)
        result=generate(OUT,PROMPT,duration=6,**args)
        records[name]=result
        (OUT/(name+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        import shutil
        shutil.copyfile(result['path'],OUT/(name+'.mp4'))
        print(json.dumps({'case':name,'seconds':result['metadata']['duration'],'elapsed':result['metadata']['elapsed_seconds'],'reused':result['reused']},ensure_ascii=False),flush=True)
