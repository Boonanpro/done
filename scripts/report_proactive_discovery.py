"""Report recorded audio end-to-presentation timing without calling it playback."""
import json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
for name in (sys.argv[1:] or ('proactive-discovery-audio','proactive-discovery-final','proactive-discovery-verified')):
    folder=ROOT/'scratch'/name
    source=folder/'final.json'
    if not source.exists():continue
    data=json.loads(source.read_text(encoding='utf8'));events=data['events']
    inputs=[e for e in events if e['type']=='test_input'];turns=[]
    for n,utterance in enumerate(inputs):
        until=inputs[n+1]['at'] if n+1<len(inputs) else float('inf')
        within=[e for e in events if utterance['at']<=e['at']<until]
        end=utterance['at']+utterance['duration']*1000
        displays=[e for e in within if e['type']=='reference_library_displayed']
        turns.append({'index':n,'decision_requests':sum(e['type']=='visual_decision_started' for e in within),
          'astra_dispatches':sum(e['type']=='live_backend_started' for e in within),
          'audio_end_to_card_ms':[round(e['at']-end) for e in displays],
          'ranking_ms':[e.get('ranking_ms') for e in displays],
          'selected_ids':[e.get('selected_library_ids') for e in displays],
          'selection_saved':any(e['type']=='reference_selected' and e.get('saved') for e in within)})
    result={'room':data['room'],'synthetic_user':True,'notes':'Card insertion timing; YouTube playback readiness not measured. Natural voice quality needs human judgment.',
            'errors':data['errors'],'turns':turns}
    (folder/'evaluation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(name,json.dumps(turns))
