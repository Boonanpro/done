"""Local, lightweight gallery. No API, no autoplay, no generation."""
import html,json
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'scratch/component-expansion'
TITLES={
 'data-chart':'棒グラフと折れ線','flowchart':'分岐するフローチャート','apple-money-count':'数字と立体の紙幣',
 'code-3d-extrude':'立体的なコード','code-diff':'変更前後のコード','code-highlight':'コードの一部を強調','code-morph':'コードの変形','code-particle-assemble':'粒子から文字へ','code-scroll':'コードのスクロール','code-shader-dissolve':'溶けて現れるコード','code-typing':'コードの入力',
 'cinematic-zoom':'ズームで切り替え','whip-pan':'カメラを振って切り替え','ui-3d-reveal':'画面を立体的に紹介','app-showcase':'スマホのアプリ紹介',
 'chromatic-radial-split':'色ずれと放射','cross-warp-morph':'ゆがみで切り替え','domain-warp-dissolve':'流れる模様の切り替え','flash-through-white':'白い閃光','glitch':'デジタルノイズ','gravitational-lens':'レンズ状のゆがみ','ridged-burn':'燃える境界','ripple-waves':'波紋で切り替え','sdf-iris':'光る開口部','swirl-vortex':'渦で切り替え','thermal-distortion':'熱によるゆがみ','transitions-3d':'立体の場面転換','transitions-grid':'格子の場面転換','transitions-mechanical':'機械的な場面転換','transitions-radial':'放射状の場面転換',
 'camcorder-hud':'ビデオカメラの表示','editorial-flash-overlay':'実写に閃光を重ねる','freeze-frame-dressing':'人物の切り抜きと静止','light-leak':'光漏れの場面転換','organic-light-leak-overlay':'実写に光漏れを重ねる',
 'ios26-liquid-glass':'ガラスのスマホ画面','liquid-glass-context-menu':'ガラスのメニュー','liquid-glass-media-controls':'ガラスの再生操作','liquid-glass-notification':'ガラスの通知','liquid-glass-widgets':'ガラスのウィジェット','macos-notification':'デスクトップの通知',
 'nyc-paris-flight':'都市を結ぶ飛行機','spain-map':'地域別の色分け地図','us-map':'州別の色分け地図','us-map-bubble':'都市のバブル地図','us-map-flow':'地域間の流れ','us-map-hex':'六角形のデータ地図','world-map':'世界のデータ地図',
 'reddit-post':'掲示板の投稿','spotify-card':'音楽のカード','x-post':'Xの投稿','yt-lower-third':'チャンネル登録表示','instagram-follow':'フォロー表示',
 'vfx-liquid-background':'液体の背景','vfx-liquid-glass':'立体ガラスの背景','vfx-magnetic':'磁力のようなゆがみ','vfx-portal':'穴を通る場面転換','vfx-shatter':'画面が砕ける','vfx-text-cursor':'質感のある文字演出','logo-outro':'ロゴで締める',
 'caption-clip-wipe':'字幕を横から現す','caption-editorial-emphasis':'書体と大きさで強調','caption-emoji-pop':'絵文字つき字幕','caption-glitch-rgb':'色ずれする字幕','caption-kinetic-slam':'勢いよく飛び込む字幕','caption-matrix-decode':'解読される字幕','caption-parallax-layers':'奥行きのある大きな字幕','caption-particle-burst':'粒子が弾ける字幕','caption-pill-karaoke':'単語を丸い背景で強調','caption-weight-shift':'太さが変わる字幕'}
FAMILIES={'captions':'字幕','data':'データ図解','code':'コード・文字','camera':'カメラ・紹介','transition':'場面転換','editorial':'実写への演出','interface':'画面・通知','geography':'地図','social':'投稿・音楽','vfx':'映像効果','brand':'ロゴ'}
manifest=ROOT/'docs/component-library.json';rows=json.loads(manifest.read_text(encoding='utf-8'));cards=[]
for row in rows:
 if row.get('inspection')=='pending':continue
 name=row['component'];title=TITLES.get(name,row['title']);row.setdefault('upstream_title',row['title']);row['title']=title
 picture=OUT/(row['id']+'-1.png');poster=OUT/(row['id']+'-poster.jpg')
 if picture.exists():
  im=Image.open(picture);im.thumbnail((480,270));im.convert('RGB').save(poster,quality=85)
 media=(ROOT/'uploads/reference-library'/(row['id']+'.mp4')).as_uri()
 cards.append(f'<article data-family="{row["family"]}"><div class="player"><video playsinline preload="none" poster="{poster.name}" data-src="{media}"></video><button aria-label="{html.escape(title)}を再生">▶</button></div><p>{html.escape(title)}</p></article>')
manifest.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
options=''.join(f'<option value="{k}">{v}</option>' for k,v in FAMILIES.items())
page='''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>ダンの動く部品</title><style>
body{background:#101418;color:#f1f3f5;margin:28px;font-family:Meiryo,sans-serif}header{display:flex;align-items:center;gap:24px;margin-bottom:28px}h1{font-size:23px;font-weight:500}select{background:#202830;color:inherit;border:1px solid #46515d;border-radius:8px;padding:10px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:24px}article{min-width:0}.player{position:relative}.player button{position:absolute;left:calc(50% - 23px);top:calc(50% - 23px);width:46px;height:46px;border-radius:50%;border:1px solid #ffffff66;background:#101820b0;color:white;cursor:pointer}.player button[hidden]{display:none}video{display:block;width:100%;aspect-ratio:16/9;background:#080b0e;border-radius:10px;object-fit:contain}p{font-size:13px;color:#bec7ce;margin-top:9px}article[hidden]{display:none}
</style><header><h1>動く部品 · '''+str(len(cards))+'''点</h1><select aria-label="種類"><option value="">すべて</option>'''+options+'''</select></header><main>'''+''.join(cards)+'''</main><script>
document.querySelector('select').onchange=e=>document.querySelectorAll('article').forEach(a=>{a.hidden=!!e.target.value&&a.dataset.family!==e.target.value;if(a.hidden)a.querySelector('video').pause()});
document.querySelectorAll('.player button').forEach(button=>button.onclick=()=>{const v=button.previousElementSibling;v.src=v.dataset.src;v.controls=true;v.play();button.hidden=true;});
document.querySelectorAll('video').forEach(v=>v.addEventListener('play',()=>document.querySelectorAll('video').forEach(other=>{if(other!==v)other.pause()})));
</script></html>'''
(OUT/'gallery.html').write_text(page,encoding='utf-8');print(str(OUT/'gallery.html'))
