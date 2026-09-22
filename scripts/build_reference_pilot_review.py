"""Standalone, local-file-readable review of the experimental URL index."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / 'scratch/reference-url-pilot/review.html'
index = json.loads((ROOT / 'docs/reference-index/videos.json').read_text(encoding='utf8'))
deep = json.loads((ROOT / 'docs/reference-index/openai-gpt6-astra.json').read_text(encoding='utf8'))
payload = json.dumps({'rows': index['references'], 'segments': deep['segments']}, ensure_ascii=False).replace('<', '\\u003c')
html = '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dan 参考ライブラリ実験</title><style>
body{margin:0;background:#111316;color:#edf0f4;font:16px system-ui,sans-serif}main{max-width:1350px;margin:auto;padding:32px}h1{font-size:26px}p{color:#abb5c2;line-height:1.6}nav{display:flex;gap:12px;flex-wrap:wrap;margin:24px 0}input,select,button{font:inherit;padding:12px;background:#222831;color:inherit;border:1px solid #465260;border-radius:8px}input{flex:1;min-width:180px}button{cursor:pointer}#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:22px}a{color:inherit;text-decoration:none}article{background:#1d2229;border-radius:10px;overflow:hidden}img{width:100%;aspect-ratio:16/9;object-fit:cover;background:#282f38}h2{font-size:15px;margin:12px;line-height:1.5}small{display:block;color:#adb7c4;margin:12px}footer{display:flex;justify-content:center;gap:20px;padding:30px}#detail{display:grid;gap:12px}#detail a{padding:16px;background:#1d2229;border-radius:8px}button:disabled{opacity:.35}
</style><main><h1>参考ライブラリ · 1,178本</h1><p>URLと仮ラベルの実験版。タイトル等から分類しています。全作品の画質・演出を確認済みではありません。作品検索はエディターに接続済みです。</p>
<nav><button id="works">作品一覧</button><button id="cuts">1本を詳しく見る · 29区間</button></nav>
<nav id="filters"><input id="query" aria-label="タイトル・作者を検索" placeholder="タイトル・作者を検索"><select id="genre" aria-label="ジャンル"><option value="">すべてのジャンル</option></select></nav>
<p id="count"></p><section id="grid"></section><section id="detail" hidden></section><footer><button id="prev">前へ</button><span id="page"></span><button id="next">次へ</button></footer></main>
<script>const data=DATA;let page=0;const $=id=>document.getElementById(id);const genres=[...new Set(data.rows.map(r=>r.labels.primary_genre))].sort();for(const g of genres){const o=document.createElement('option');o.value=g;o.textContent=g;$('genre').append(o)}
function draw(){const q=$('query').value.toLowerCase(),g=$('genre').value;const rows=data.rows.filter(r=>(!g||r.labels.primary_genre===g)&&(!q||(r.title+' '+r.publisher).toLowerCase().includes(q)));const pages=Math.max(1,Math.ceil(rows.length/36));page=Math.min(page,pages-1);$('grid').replaceChildren();for(const r of rows.slice(page*36,page*36+36)){const a=document.createElement('a');a.href=r.url;a.target='_blank';a.rel='noopener';const card=document.createElement('article'),im=document.createElement('img'),h=document.createElement('h2'),s=document.createElement('small');im.src=r.thumbnail_url||'';im.loading='lazy';im.alt='';h.textContent=r.title;s.textContent=r.publisher+' · '+r.labels.primary_genre;card.append(im,h,s);a.append(card);$('grid').append(a)}$('count').textContent=rows.length+'本';$('page').textContent=(page+1)+' / '+pages;$('prev').disabled=page===0;$('next').disabled=page===pages-1}
for(const id of ['query','genre'])$(id).addEventListener('input',()=>{page=0;draw()});$('prev').onclick=()=>{page--;draw()};$('next').onclick=()=>{page++;draw()};
function mode(cuts){$('grid').hidden=cuts;$('detail').hidden=!cuts;$('filters').hidden=cuts;document.querySelector('footer').hidden=cuts;if(cuts){$('count').textContent='GPT-6発表映像 · 動画分析＋再確認。各区間をクリックすると元動画の該当時刻を開きます。';$('detail').replaceChildren();for(const s of data.segments){const a=document.createElement('a');const u=new URL(s.source_url);u.searchParams.set('t',Math.floor(s.start)+'s');a.href=u;a.target='_blank';a.rel='noopener';a.textContent=s.start.toFixed(1)+'–'+s.end.toFixed(1)+'秒 · '+s.visual;$('detail').append(a)}}else draw()}
$('works').onclick=()=>mode(false);$('cuts').onclick=()=>mode(true);draw();</script></html>'''.replace('DATA', payload)
# Explicit hidden beats display:grid for the two views.
html = html.replace('</style>', '[hidden]{display:none!important}</style>')
out.write_text(html, encoding='utf8')
print(out)
