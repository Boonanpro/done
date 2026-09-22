"""Local, offline review of real editor recordings; no publication."""
import html,json,sys
from pathlib import Path

folder=Path(sys.argv[1])
result=json.loads((folder/'summary.json').read_text(encoding='utf8'))
titles={'caption':'字幕の雰囲気','motion':'情報が集まる動き','film':'人物の表情と映像のタッチ','lifestyle':'理想の暮らしの距離感'}
cards=[]
for row in result['cases']:
    name=row['case']
    first=' / '.join(f'{v/1000:.2f}秒' for v in row['first_display_ms'])
    final=' / '.join(f'{v/1000:.2f}秒' for v in row['last_update_ms'])
    cards.append(f'''<section><h2>{html.escape(titles.get(name,name))}</h2>
    <video controls preload="metadata" playsinline poster="{html.escape(name)}/step-2.png" src="{html.escape(name)}/conversation.mp4"></video>
    <p>各比較の表示待ち：{first}<br>最後の更新まで：{final}</p></section>''')
page=f'''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dan — 会話で見た目を絞るテスト</title><style>
body{{margin:0;background:#111315;color:#eceeef;font:16px/1.7 system-ui,sans-serif}}main{{max-width:1400px;margin:auto;padding:40px 24px}}
h1{{font-size:28px;line-height:1.4}}h2{{font-size:19px}}p{{color:#b8bec5}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,480px),1fr));gap:32px}}
section{{min-width:0}}video{{width:100%;background:#000;border-radius:12px}}.stats{{padding:18px 0;font-size:20px}}small{{color:#a3abb5}}</style>
<main><h1>会話で、欲しい見た目へ近づける</h1>
<p>実際のDanエディターに音声で相談した録画です。新しい動画の本編制作ではなく、既存の参考を見比べて絞り込むテストです。</p>
<div class="stats">表示待ちの中央値 {result['median_display_ms']/1000:.2f}秒 · 90％点 {result['p90_display_ms']/1000:.2f}秒</div>
<small>発言終了から計測。発言中に表示済み、または適切な既存候補をそのまま表示している場合は0秒。最後の更新までの時間は別記しています。生成時間の計測ではありません。</small>
<div class="grid">{''.join(cards)}</div>
<p>候補が目的に合っているか、実物の違いを選びやすいか、声と画面が合っているかを確認できます。</p></main></html>'''
(folder/'review.html').write_text(page,encoding='utf8')
print(str((folder/'review.html').resolve()))
