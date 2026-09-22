"""Summarize observed timings; never count a courtesy acknowledgement as a result."""
import json
from pathlib import Path

root=Path('.tmp/voice-conversation-trial')
for path in sorted(root.glob('*.json')):
    events=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(events,list):continue
    starts=[(i,e) for i,e in enumerate(events) if e.get('kind')=='input_end']
    rows=[]
    for n,(index,event) in enumerate(starts):
        stop=starts[n+1][0] if n+1<len(starts) else len(events)
        following=events[index+1:stop]
        audio=next((e for e in following if e.get('type')=='audio_start'),None)
        reports=[e for e in following if e.get('type')=='backend_report']
        meaningful=next((e for e in reports if not e.get('text','').strip().rstrip('。') in ('記録を確認したよ','うん、記録を確認したよ','記録を確認しました')),None)
        spoken=''.join(e.get('delta','') for e in following if e.get('type')=='session.output_transcript.delta')
        # Transcript alignment is a conservative proxy for the first factual
        # spoken word, separately from the PCM onset of a courtesy reply.
        factual=None
        if meaningful and event['case']=='reservation':
            parts=[e for e in following if e.get('type')=='session.output_transcript.delta' and e['at']>=meaningful['at']]
            joined=''.join(e.get('delta','') for e in parts)
            pos=joined.find('予約');offset=0
            if pos>=0:
                for part in parts:
                    if offset<=pos<offset+len(part['delta']):factual=part['at']-event['at'];break
                    offset+=len(part['delta'])
        rows.append({'case':event['case'],'reply_audio_seconds':round(audio['at']-event['at'],3) if audio else None,
            'backend_result_seconds':round(meaningful['at']-event['at'],3) if meaningful else None,
            'factual_transcript_seconds':round(factual,3) if factual is not None else None,
            'spoken':spoken})
    print(json.dumps({'trial':path.stem,'cases':rows},ensure_ascii=False))
