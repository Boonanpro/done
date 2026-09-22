"""Register reviewed reference footage with purpose evidence, not quality claims."""
import hashlib
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    source=ROOT/'scratch/purpose-intake/coffee-preview.mp4'
    target=ROOT/'uploads/reference-library/stock-coffee-window.mp4'
    shutil.copyfile(source,target)
    path=ROOT/'docs/reference-library.json'
    rows=json.loads(path.read_text(encoding='utf8'))
    ident='stock-coffee-window'
    entry={
        'id':ident,'title':'窓辺でコーヒーを注ぐ','family':'observational-daily-ritual',
        'kind':'video','extension':'.mp4','reference_role':'scene',
        'description':'A woman partly cropped at the right pours coffee from a French press into a white mug on a dark wooden tray beside a large window. Backlit steam, soft green hills outside, gentle shallow focus, restrained lateral camera drift. Warm naturalistic live-action domestic ritual; no titles, effects or fast cuts.',
        'use_cases':['生活Vlogの小さな楽しみ','飲み物と手元の撮影','自然光と静かな時間','日常のBロール'],
        'limitations':['単一ショット。完成したVlogの構成・字幕・音の見本ではない','朝の自然光。夜の帰宅シーンの実物ではない'],
        'source_url':'https://www.pexels.com/video/a-woman-pouring-coffee-7301093/',
        'download_url':'https://videos.pexels.com/video-files/7301093/7301093-uhd_3840_2160_25fps.mp4',
        'attribution':'Taryn Elliott / Pexels','license':'Pexels License',
        'license_source':'https://www.pexels.com/license/',
        'source_range':{'start':5,'duration':8},
        'inspection':'8 sampled frames visually inspected; actual editor playback verified at 960x540 for 8 seconds without media errors.',
        'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
        'reproduction_status':'reference_only','original_work':False}
    rows=[r for r in rows if r['id']!=ident]+[entry]
    path.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    print(ident)

if __name__=='__main__':main()
