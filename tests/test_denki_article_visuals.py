"""Regression checks for illustrated articles through review/citation processing."""
import copy
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import denki_seo_engines as e

SVG='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 480"><text x="30" y="40" font-size="24" fill="#123456">端子</text></svg>'
def page():
    return {'title':'接地抵抗測定の端子の違い','description':'説明'*40,'answer':'結論[3]', 'sections':[{'heading':'端子','paragraphs':['段落[1]'], 'visual':{'title':'対応','alt':'端子の対応','caption':'対応の出典[2]','svg':SVG}}], 'checklist':[], 'faq':[]}

def test_citation_remap_keeps_illustration_and_its_source():
    sources=[dict(title=str(i),url=f'https://example.com/{i}',source_name='資料',kind='blog') for i in range(3)]
    result,cites=e.finalize_citations(page(),sources)
    assert result['sections'][0]['visual']['svg']==SVG
    assert result['sections'][0]['visual']['caption']=='対応の出典[3]'
    assert [c['title'] for c in cites]==['2','0','1']

def test_reject_active_or_external_svg():
    for bad in ['<script>bad()</script>','<image href="https://example.com/x"/>','<foreignObject/>','<path onclick="bad()"/>']:
        p=page();p['sections'][0]['visual']['svg']=SVG.replace('</svg>',bad+'</svg>')
        assert e.visuals.validate(p)

def test_visual_review_failure_cannot_be_trimmed_into_approval():
    assert e.drop_flagged(page(),[{'type':'F','quote':'誤った図をここで指摘します'}]) is None

def test_old_articles_and_font_size():
    assert e.visuals.validate({'sections':[{'heading':'旧記事','paragraphs':['文章']} ]})==[]
    p=page();p['sections'][0]['visual']['svg']=SVG.replace('font-size="24"','font-size="12"')
    assert e.visuals.validate(p)

def test_actual_writer_and_reviewer_receive_visual_policy(monkeypatch):
    prompts=[]
    monkeypatch.setattr(e,'claude_json',lambda prompt,**kwargs:prompts.append(prompt))
    e.write_page('接地','端子',[])
    e.review_page('接地',page(),[])
    assert 'visual={title,alt,caption,svg}' in prompts[0]
    assert 'SVGの図形・線の接続' in prompts[1]
    assert 'viewBox' in prompts[1]
