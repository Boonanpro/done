"""Portable, local visual review of tested plans; no services or API calls."""
import html,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.services.editor_direction_library import PROGRAM
from scripts.test_direction_transfer import CASES,OUT

cards=[]
for name,facts,purpose in CASES:
 data=json.loads((OUT/(name+'.json')).read_text(encoding='utf-8'))
 params=json.dumps(data['plan'],ensure_ascii=False).replace('<','\\u003c')
 code=PROGRAM.read_text(encoding='utf-8')
 document='''<!doctype html><meta charset="utf-8"><style>html,body,#stage{margin:0;width:100%;height:100%;overflow:hidden}</style><div id="stage"></div><script>
 const stage=document.getElementById('stage');const params='''+params+''';let draw,t=0,last=0,paused=false;
 function setFrame(f){draw=f;f(0)}
 '''+code+'''
 function tick(now){if(!paused){t=(t+(last?(now-last)/1000:0))%12;draw(t);}last=now;requestAnimationFrame(tick)}requestAnimationFrame(tick);
 addEventListener('click',()=>paused=!paused);
 </script>'''
 cards.append('<article><h2>'+html.escape(data['plan']['title'])+'</h2><p>'+html.escape(purpose)+'</p><iframe title="'+html.escape(name)+'" sandbox="allow-scripts" srcdoc="'+html.escape(document,quote=True)+'"></iframe></article>')
 output='''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>演出の作り分け・検証</title><style>
 body{margin:32px;background:#11161a;color:#e9eded;font-family:Meiryo,sans-serif}h1{font-size:24px}main{display:grid;grid-template-columns:1fr 1fr;gap:32px 20px}article{min-width:0}h2{font-size:17px;font-weight:500}p{font-size:13px;line-height:1.7;color:#aab8bd;min-height:44px}iframe{display:block;width:100%;aspect-ratio:16/9;border:0;border-radius:12px}header p{min-height:0}@media(max-width:800px){main{grid-template-columns:1fr}}
 </style><header><h1>同じ内容、違う目的。</h1><p>左右が同じ題材の比較。各12秒・無音。画面をクリックすると再生／停止します。</p></header><main>'''+''.join(cards)+'</main></html>'
(OUT/'review.html').write_text(output,encoding='utf-8')
print(OUT/'review.html')
