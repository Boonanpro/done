"""Measure real injected audio end to actual media-ready events, including misses."""
import json, math, sys
from pathlib import Path

def summarize(folder):
    data=json.loads((folder/'final.json').read_text(encoding='utf8'))
    events=data['events']; inputs=[e for e in events if e['type']=='test_input']; rows=[]
    for n,utterance in enumerate(inputs):
        end=utterance['at']+utterance['duration']*1000
        until=inputs[n+1]['at'] if n+1<len(inputs) else float('inf')
        relevant=[e for e in events if utterance['at']<=e['at']<until]
        displays=[e for e in relevant if e['type'] in ('reference_library_displayed','references_displayed','reference_library_reused') and e.get('ok')]
        # Reuse is a measured decision to retain the already visible example,
        # not a newly decoded frame. Keep it distinguishable in the evidence.
        def actual_ready(e):
            if e['type']!='reference_library_reused':return e
            prior=[p for p in events if p['at']<=e['at'] and p['type']=='reference_library_displayed'
                   and p.get('ok') and p.get('presentation_id')==e.get('presentation_id')
                   and p.get('selected_library_ids')==e.get('selected_library_ids')]
            # Do not pretend a within-turn reuse was already visible before
            # the user spoke: link it to the actual prior rendered-frame event.
            return {**e,'at':prior[-1]['at']} if prior else e
        displays=[actual_ready(e) for e in displays]
        displays.sort(key=lambda e:e['at'])
        after=[e for e in displays if e['at']>=end]
        # Report both readiness before speech ended and subsequent changes.
        ready=displays[0]['at'] if displays else None
        rows.append({'input':utterance['index'], 'speech_seconds':utterance['duration'],
            'first_ready_relative_to_speech_end_ms':round(displays[0]['at']-end) if displays else None,
            'first_ready_after_speech_end_ms':round(after[0]['at']-end) if after else None,
            'display_wait_ms':max(0,round(ready-end)) if ready else None,
            'last_update_after_speech_end_ms':max(0,round(displays[-1]['at']-end)) if displays else None,
            'presentations':len(displays),
            'reused_existing':sum(e['type']=='reference_library_reused' for e in displays),
            'spoken_reports':sum(e['type']=='reference_report_delivered' and e.get('speaking') for e in relevant),
            'backend_started':sum(e['type']=='live_backend_started' for e in relevant)})
    times=sorted(r['display_wait_ms'] for r in rows if r['display_wait_ms'] is not None)
    final_times=sorted(r['last_update_after_speech_end_ms'] for r in rows if r['last_update_after_speech_end_ms'] is not None)
    return {'room':data['room'],'rows':rows,
        'p50_display_wait_ms':times[math.ceil(len(times)*.5)-1] if times else None,
        'p90_display_wait_ms':times[math.ceil(len(times)*.9)-1] if times else None,
        'p50_final_update_ms':final_times[math.ceil(len(final_times)*.5)-1] if final_times else None,
        'p90_final_update_ms':final_times[math.ceil(len(final_times)*.9)-1] if final_times else None,
        'warning':'Timing is not a relevance or conversational-quality pass. Nonvisual utterances legitimately have no display.',
        'messages':[{'role':m['role'],'text':m['text']} for m in data['messages']], 'browser_errors':data['errors']}

if __name__=='__main__':
    folder=Path(sys.argv[1]);result=summarize(folder)
    (folder/'measurement.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='messages'},ensure_ascii=False))
