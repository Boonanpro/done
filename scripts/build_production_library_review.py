"""Build a local review artifact, not a production UI or quality approval."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.enrich_production_library import OUT, read


def main():
    observations = read(ROOT / 'docs/reference-index/visual-observations.json', {})
    works = read(ROOT / 'docs/reference-index/videos.json')['references']
    records = []
    for row in works:
        observed = observations.get(row['id'], {})
        if not observed.get('facets'): continue
        records.append({'type': '参考動画', 'title': row['title'], 'url': row['url'],
                        'image': row.get('thumbnail_url'), 'group': row['labels']['primary_genre'],
                        'labels': [e['label'] for entries in observed['facets'].values() for e in entries],
                        'status': '映像をモデル分析済み・品質承認ではありません'})
    for row in read(ROOT / 'docs/reference-index/production-assets.json', {}).get('assets', []):
        records.append({'type': '制作素材', 'title': row['title'], 'url': row['source_url'],
                        'image': row.get('preview_url'), 'group': row['kind'],
                        'labels': row['tags'] + row['categories'], 'status': '配布元の情報・品質未審査'})
    for row in read(ROOT / 'docs/component-library.json', []):
        review = read(OUT / 'component-reviews' / (row['id'] + '.json'), {})
        records.append({'type': '既存部品', 'title': row['title'], 'url': row['source_url'],
                        'video': (ROOT / 'uploads/reference-library' / (row['id']+'.mp4')).as_uri(),
                        'group': row['family'], 'labels': row.get('tags', []),
                        'status': 'この見本は以前ユーザー確認済み' if row.get('quality_status') == 'reference_approved' else {'reject': '品質再審査：不採用候補', 'needs_design_work': '品質再審査：作り込みが必要',
                                   'polished_candidate': '品質再審査：候補・編集耐性は未確認'}.get(
                                       review.get('review', {}).get('verdict'), '品質審査未完了')})
    data = json.dumps(records, ensure_ascii=False).replace('<', '\\u003c')
    page = '''<!doctype html><html lang="ja"><meta charset="utf-8"><title>Dan 制作ライブラリ確認</title>
<style>body{margin:0;background:#111416;color:#ecf0f1;font:15px system-ui}header{padding:24px;position:sticky;top:0;background:#111416;z-index:1;border-bottom:1px solid #333}h1{font-size:21px;margin:0 0 14px}input,select,button{font:inherit;padding:10px;background:#25292c;color:inherit;border:1px solid #555;border-radius:6px}input{width:35vw}main{padding:24px;display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:20px}article{background:#202528;border-radius:8px;overflow:hidden}img,video{display:block;width:100%;height:190px;object-fit:contain;background:#090b0d}a{color:inherit;text-decoration:none}h2{font-size:14px;padding:12px;margin:0}small{display:block;color:#aeb8bd;padding:0 12px 12px}footer{padding:20px;text-align:center}#count{margin-left:12px}</style>
<header><h1>制作ライブラリ確認</h1><select id="kind"><option>参考動画</option><option>既存部品</option><option>制作素材</option></select> <input id="query" placeholder="名前・特徴で検索"><span id="count"></span></header><main></main><footer><button id="prev">前へ</button> <button id="next">次へ</button></footer>
<script>const data=__DATA__;let page=0;const kind=document.querySelector('#kind'),query=document.querySelector('#query');
function render(){const words=query.value.toLowerCase().split(/\\s+/).filter(Boolean);const rows=data.filter(r=>r.type===kind.value&&words.every(w=>(r.title+' '+r.group+' '+r.labels.join(' ')).toLowerCase().includes(w)));const root=document.querySelector('main');root.replaceChildren();for(const r of rows.slice(page*24,page*24+24)){const card=document.createElement('article');const media=document.createElement(r.video?'video':'img');if(r.video){media.controls=true;media.preload='none';media.src=r.video}else{media.loading='lazy';media.src=r.image||'';media.alt=r.title}card.append(media);const link=document.createElement('a');link.href=r.url;link.target='_blank';link.rel='noopener noreferrer';const title=document.createElement('h2');title.textContent=r.title;link.append(title);card.append(link);const status=document.createElement('small');status.textContent=r.status;card.append(status);root.append(card)}document.querySelector('#count').textContent=rows.length+'件 / '+(page+1)+'ページ';document.querySelector('#prev').disabled=page===0;document.querySelector('#next').disabled=(page+1)*24>=rows.length}
kind.onchange=query.oninput=()=>{page=0;render()};document.querySelector('#prev').onclick=()=>{page--;render()};document.querySelector('#next').onclick=()=>{page++;render()};render();</script></html>'''.replace('__DATA__', data)
    target = OUT / 'review.html'
    target.write_text(page, encoding='utf8')
    print(target)


if __name__ == '__main__': main()
