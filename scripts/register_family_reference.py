"""Register an inspected, licensed family-life reference for personal Dan use."""
import hashlib,json,shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    source=ROOT/'scratch/purpose-intake/family-preview.mp4'
    if not (ROOT/'scratch/purpose-intake/family-contact.jpg').exists():raise RuntimeError('Inspect contact sheet first')
    target=ROOT/'uploads/reference-library/stock-family-kitchen.mp4';shutil.copyfile(source,target)
    entry={'id':'stock-family-kitchen','title':'家族の小さなやり取り','family':'observational-family-life',
        'kind':'video','extension':'.mp4','reference_role':'scene',
        'description':'Naturalistic live-action mother and toddler at a kitchen counter by a large window. Medium two-shot from beside the window, soft daylight, neutral grey clothing and a pale green mixing bowl. The child tastes a spoon while the mother bends toward him; both turn toward each other and smile. Mostly static camera; affection emerges through small gestures and changing facial expressions. No captions, graphic effects, montage or narration.',
        'use_cases':['家族の日常の記録','将来見返す私的な思い出','親子の自然なやり取り','人の表情を見せる静かな生活映像'],
        'limitations':['既存の撮影素材。ユーザー本人の家族を撮った映像ではない','単一ショット。完成した家族動画の構成や音楽の見本ではない','自然な印象の撮影だが、撮影時に演出がなかったとは断定しない'],
        'source_url':'https://www.pexels.com/video/mother-and-son-spending-time-together-4941885/',
        'download_url':'https://videos.pexels.com/video-files/4941885/4941885-hd_1920_1080_25fps.mp4',
        'attribution':'Taryn Elliott / Pexels','license':'Pexels License','license_source':'https://www.pexels.com/license/',
        'source_range':{'start':0,'duration':8},'inspection':'Eight one-second samples visually inspected for framing, light and changing expressions.',
        'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'reproduction_status':'reference_only','original_work':False}
    path=ROOT/'docs/reference-library.json';rows=json.loads(path.read_text(encoding='utf8'))
    rows=[r for r in rows if r['id']!=entry['id']]+[entry]
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(path)
    print(entry['id'])

if __name__=='__main__':main()
