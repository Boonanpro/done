"""Register the existing inspected optical-type study and its editable sources.

No source project is changed. The reference soundtrack is excluded from preview
and source bundle: it was borrowed solely for the earlier visual comparison.
"""
import hashlib,json,shutil,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    original=ROOT/'videos/reference-01-finish'
    bundle=ROOT/'app/data/component-library/dan-optical-type'
    bundle.mkdir(parents=True,exist_ok=True)
    files=[]
    for name in ('index.html','design.md','RESEARCH.md','VALIDATION.md','assets/Inter.ttf','assets/Inter-OFL.txt','assets/gsap.min.js'):
        source=original/name;target=bundle/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
        files.append({'file':name,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    preview=ROOT/'uploads/reference-library/dan-optical-type.mp4'
    subprocess.run([r'C:\Users\Owner\ffmpeg\bin\ffmpeg.exe','-y','-hide_banner','-loglevel','error',
        '-i',str(original/'renders/video.mp4'),'-an','-c:v','copy','-movflags','+faststart',str(preview)],check=True)
    path=ROOT/'docs/component-library.json';rows=json.loads(path.read_text(encoding='utf8'))
    entry={'id':'dan-optical-type','title':'光と奥行きの文字演出','family':'kinetic-typography',
        'kind':'video','extension':'.mp4','component':'dan-optical-type','evidence_role':'finished_study','reference_role':'text',
        'description':'5.5-second optical kinetic typography study: mint-green glow, oversized translucent Meet letters, fast camera pullback into dark bold Your new AI and a depth-blurred scrolling role list, then large tell them text. Carefully layered blur, chromatic fringes, gradients and timing. Editable HTML/GSAP, not footage captured from the reference.',
        'use_cases':['製品ローンチの文字主導演出','文字の奥行き・フォーカス・光','短いキネティックタイポグラフィ'],
        'limitations':['会話字幕の読みやすさを評価する見本ではない','英字向け。日本語化は文字組みの再調整が必要','プレビューは無音。元研究の参考音源を制作素材に流用しない','HTMLソース中のreference-audio.m4aは収録せず。独自音源に置換するかaudio要素を削除する'],
        'source_url':'https://x.com/chddaniel/status/2096868384344526961',
        'license':'Local visual reconstruction study; reference is not owned. Font: Inter OFL; retain bundled notices. No soundtrack supplied.',
        'inspection':'Six frames visually inspected; previous rendered video reviewed by user; actual editor playback verified at 1280x720 for 5.5 seconds without media errors.',
        'quality_evidence':'User said this visual study was usable for production; this is not blanket approval of other components.',
        'revision':hashlib.sha256((original/'index.html').read_bytes()).hexdigest(),
        'variables':[],'dimensions':[1280,720],'duration':5.5,'files':files,
        'sha256':hashlib.sha256(preview.read_bytes()).hexdigest()}
    rows=[r for r in rows if r['id']!=entry['id']]+[entry]
    path.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    print(entry['id'])

if __name__=='__main__':main()
