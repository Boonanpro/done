"""Editable caption studies over licensed footage, not quality certification."""
import json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.services.editor_presentation import clean_composition

def build():
    video={'type':'video','url':'/api/v1/editor-assistant/reference-library/media/stock-coffee-window',
           'width':1920,'height':1080,'objectFit':'cover','end':8}
    shade={'type':'rect','width':1920,'height':1080,
           'background':'linear-gradient(0deg,rgba(13,24,21,.68),transparent 65%)','end':8}
    fade=[{'offset':0,'opacity':0,'y':9},{'offset':.08,'opacity':1,'y':0},
          {'offset':.91,'opacity':1,'y':0},{'offset':1,'opacity':0,'y':0}]
    common={'type':'text','text':'忙しい日は、一杯ぶんの余白を。','x':100,'y':834,'width':1720,'height':110,
            'start':.5,'end':7.7,'fontSize':62,'fontWeight':'500','color':'#fffaf0',
            'lineHeight':1.45,'keyframes':fade}
    rows=[]
    variants=[
        ('dan-caption-reflective','余韻のある語り','caption-reflective',
         [{**common,'fontFamily':'Yu Mincho, serif','letterSpacing':5,'textAlign':'left',
           'textShadow':'0 2px 14px rgba(0,0,0,.55)'}],
         'Silent real coffee footage with restrained ivory Japanese Mincho on-screen captions low-left, generous tracking, soft shadow and slow entrance. Quiet observational memoir, personal documentary and reflective Vlog. No spoken narration. Not a comedy telop or word-by-word karaoke.',
         ['内省的なVlog','ドキュメンタリーの回想','生活の余韻を残す語り']),
        ('dan-caption-clear','すっと読める会話','caption-clear',
         [{**common,'x':192,'width':1536,'fontFamily':'Yu Gothic, sans-serif','fontWeight':'600','letterSpacing':1,
           'strokeWidth':2,'strokeColor':'rgba(15,22,20,.8)','textShadow':'0 3px 9px rgba(0,0,0,.7)'}],
         'Actual moving coffee footage with a clean centered Japanese Gothic caption, moderate size, fine dark edge and subtle shadow. Readable conversational explanation without a boxed panel or spectacle. Two timed sentences would use separate text layers.',
         ['会話主体の動画','解説','読みやすさを優先する字幕']),
        ('dan-caption-emphasis','ひと言を残す','caption-emphasis',
         [{'type':'text','text':'忙しい日は、','x':100,'y':708,'width':1000,'height':76,'fontSize':44,
           'fontFamily':'Yu Gothic, sans-serif','fontWeight':'600','letterSpacing':3,'textAlign':'left',
           'color':'#fffaf0','start':.5,'end':7.7,'keyframes':fade},
          {'type':'rect','x':100,'y':828,'width':650,'height':98,'background':'#e5efb6',
           'start':1.15,'end':7.7,'keyframes':[{'offset':0,'opacity':0,'x':-14},{'offset':.045,'opacity':1,'x':0},{'offset':.94,'opacity':1},{'offset':1,'opacity':0}]},
          {**common,'text':'一杯ぶんの余白を。','x':128,'y':828,'width':1200,'height':98,'start':1.15,
           'fontFamily':'Yu Gothic, sans-serif','fontSize':66,'fontWeight':'700','letterSpacing':1,'textAlign':'left',
           'color':'#152c23','keyframes':[{'offset':0,'opacity':0,'y':8},{'offset':.055,'opacity':1,'y':0},{'offset':.94,'opacity':1},{'offset':1,'opacity':0}]}],
         'Real lifestyle footage with editorial hierarchy: a small setup line, then a larger dark Japanese phrase arriving on a muted citron highlight. Asymmetric lower-left composition. Emphasis stays readable; no bouncing emojis or per-word animation.',
         ['短い暮らしの提案','言葉を印象づけるSNS動画','穏やかなブランド映像']),
    ]
    for ident,title,family,layers,description,uses in variants:
        composition=clean_composition('reference-library',{'width':1920,'height':1080,'duration':8,
            'background':'#10241e','layers':[video,shade,*layers]})
        rows.append({'id':ident,'title':title,'family':family,'kind':'composition','composition':composition,'reference_role':'text',
            'description':description,'use_cases':uses,'limitations':['無音の字幕デザイン見本。ナレーション音声は含まない','人物・台詞に合わせた完成編集ではない','フォントは端末の日本語フォントに依存。書き出す環境で字幅を確認する'],
            'source_url':'https://www.pexels.com/video/a-woman-pouring-coffee-7301093/',
            'license':'Original editable caption design. Footage: Taryn Elliott / Pexels, Pexels license.',
            'inspection':'pending','evidence_role':'design_study'})
    return rows

if __name__=='__main__':
    rows=build()
    out=ROOT/'scratch/purpose-intake/contextual-captions.json'
    out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    if '--register-inspected' in sys.argv:
        for row in rows:
            proof=ROOT/('scratch/purpose-intake/'+row['id']+'.png')
            if not proof.exists():raise RuntimeError('Inspect the actual editor preview before registration')
            row['inspection']='Actual editor playback and typography inspected at 3 seconds; text fits; source footage verified separately. Design study, not user-approved final quality.'
        path=ROOT/'docs/reference-library.json'
        current=json.loads(path.read_text(encoding='utf8'))
        ids={r['id'] for r in rows}
        path.write_text(json.dumps([r for r in current if r['id'] not in ids]+rows,ensure_ascii=False,indent=2),encoding='utf8')
    print(out)
