"""Descriptive results and a local audio review page; no automatic quality score."""
import html, json, statistics
from pathlib import Path
import jsonschema

OUT=Path('exports/minimal-conversation-comparison-20260910')
rows=[];invalid=[]
for p in sorted([*OUT.glob('text-*.json'), *OUT.glob('audio-*.json')]):
    r=json.loads(p.read_text(encoding='utf-8'))
    if not all(k in r for k in ('id','arm','calls','case')):continue
    schemas={t['name']:t['parameters'] for t in r['configuration'][1]}
    for c in r['calls']:
        try:jsonschema.validate(c['args'],schemas[c['name']])
        except Exception as e:invalid.append({'id':r['id'],'tool':c['name'],'error':str(e)[:250]})
    rows.append(r)

summary=[]
for phase in ['text','audio']:
    for case in sorted({r['case']['id'] for r in rows if r['phase']==phase}):
        for arm in ['rt_old','rt_lean','gpt_lean']:
            rs=[r for r in rows if r['phase']==phase and r['case']['id']==case and r['arm']==arm]
            if not rs:continue
            s={'phase':phase,'case':case,'arm':arm,'n':len(rs),'ok':sum(r['ok'] for r in rs)}
            for key in ['elapsed_seconds','first_text_seconds','first_audio_seconds','decision_seconds','asr_seconds']:
                vals=[r[key] for r in rs if key in r]
                if vals:s[key+'_median']=round(statistics.median(vals),3)
            s['production_calls']=[sum(c['name'] in {'request_production','delegate_edit'} for c in r['calls']) for r in rs]
            summary.append(s)
(OUT/'summary.json').write_text(json.dumps({'summary':summary,'schema_errors':invalid,'errors':[{'id':r['id'],'error':r.get('error')} for r in rows if not r['ok']]},ensure_ascii=False,indent=2),encoding='utf-8')

parts=['<!doctype html><meta charset="utf-8"><title>会話比較 2026-09-10</title><style>body{font:16px system-ui;max-width:1050px;margin:40px auto;padding:20px;background:#f6f6f6;color:#222}article{background:white;padding:24px;margin:20px 0;border-radius:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere}audio{width:100%}summary{cursor:pointer}</style><h1>会話比較</h1><p>実モデル・模擬ツール。音声入力は合成音声で、自然な割り込みの比較ではありません。音声GPT条件は認識→全文生成→読み上げの順であり、最適化した実装の速さを表すものではありません。</p>']
for r in rows:
    parts+=['<article><h2>'+html.escape(r['id'])+'</h2><p>'+html.escape(r['case']['messages'][-1][1])+'</p>']
    if (OUT/(r['id']+'.wav')).exists():parts+=['<audio controls preload="none" src="'+r['id']+'.wav"></audio>']
    parts+=['<pre>'+html.escape('\n'.join(r.get('answers',[])))+'</pre><details><summary>道具・時刻・認識結果</summary><pre>'+html.escape(json.dumps({'calls':r['calls'],'asr':r.get('asr'),'elapsed':r.get('elapsed_seconds'),'first_audio':r.get('first_audio_seconds'),'error':r.get('error')},ensure_ascii=False,indent=2))+'</pre></details></article>']
(OUT/'review.html').write_text(''.join(parts),encoding='utf-8')
print(json.dumps({'records':len(rows),'errors':sum(not r['ok'] for r in rows),'schema_errors':len(invalid),'summary':summary},ensure_ascii=False,indent=2))
