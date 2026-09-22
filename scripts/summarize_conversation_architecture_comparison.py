"""Summarize isolated conversation trials, retaining per-case timings and audio."""
import html,json,statistics
from pathlib import Path
ROOT=Path('exports/conversation-architecture-comparison-20260909-v2')
NAMES={'soccer':'サッカー制作','tentative':'未合意の人物なしを否定','budget_change':'予算条件の変更','memory':'会話で伝えた目的を尋ねる','search':'参考を二つ検索・提示','stop':'制作だけ停止'}
TARGET={'soccer':'delegate_edit','tentative':'delegate_edit','budget_change':'delegate_edit','search':'present_references','stop':'stop_production'}
def summarize():
    records=[json.loads(p.read_text(encoding='utf-8')) for p in ROOT.glob('*-*.json') if p.name!='protocol.json']
    records=[r for r in records if 'arm' in r]
    rows=[];sections=[]
    for case,label in NAMES.items():
        for arm in ['current','astra_raw']:
            rs=sorted([r for r in records if r['case']['id']==case and r['arm']==arm],key=lambda r:r['repeat'])
            speech=[r['first_audio_seconds'] for r in rs if r.get('ok') and 'first_audio_seconds' in r]
            actions=[next((c['at_seconds'] for c in r['calls'] if c['name']==TARGET.get(case)),None) for r in rs]
            actions=[t for t in actions if t is not None]
            rows.append({'case':case,'label':label,'arm':arm,'ok':sum(bool(r.get('ok')) for r in rs),'trials':len(rs),
                'speech_seconds':speech,'speech_median':statistics.median(speech) if speech else None,
                'target':TARGET.get(case),'target_calls':len(actions),'target_seconds':actions,
                'target_median':statistics.median(actions) if actions else None})
            for r in rs:
                e=html.escape
                transcript='\n'.join(r.get('spoken',[]))
                calls='\n'.join(f"{c['at_seconds']:.2f}s {c['name']} {json.dumps(c['args'],ensure_ascii=False)}" for c in r['calls'])
                sections.append(f'<article><h2>{e(label)} / {e(arm)} / {r["repeat"]+1}</h2><p>{e(str(r.get("error","")))}</p><audio controls preload="none" src="{e(r["id"])}.wav"></audio><h3>入力</h3><pre>{e(json.dumps(r["case"]["messages"],ensure_ascii=False,indent=2))}</pre><h3>音声の文字起こし</h3><pre>{e(transcript)}</pre><details><summary>ツール呼び出し</summary><pre>{e(calls)}</pre></details></article>')
    (ROOT/'summary.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    table='<table><tr><th>ケース</th><th>方式</th><th>初音声・中央値</th><th>対象操作・中央値</th><th>対象操作到達</th></tr>'+''.join(f'<tr><td>{r["label"]}</td><td>{r["arm"]}</td><td>{r["speech_median"]}</td><td>{r["target_median"]}</td><td>{r["target_calls"]}/{r["trials"]}</td></tr>' for r in rows)+'</table>'
    (ROOT/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>音声構成比較</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:20px;line-height:1.7}pre{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #ccc;margin-top:32px}td,th{text-align:left;padding:8px;border-bottom:1px solid #ddd}audio{width:100%}</style><h1>音声構成比較</h1><p>current：現行Realtime。astra_raw：GPT6が会話原文から判断し、Realtimeが返答を読み上げる試験接続。入力は文字。検索・制作・表示は固定した模擬結果で、実際の動画制作は実行していません。初音声には相づちを含みます。GPT6側は全文完成後に音声接続するため、最適化前の時間です。</p>'+table+''.join(sections),encoding='utf-8')
    print(json.dumps(rows,ensure_ascii=False,indent=2))
if __name__=='__main__':summarize()
