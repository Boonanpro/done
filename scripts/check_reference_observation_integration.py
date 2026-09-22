import json,sys
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from datetime import timedelta
from app.services.auth_service import create_access_token

token=create_access_token('2582a188-ff24-4a4f-b989-6063034d90b2','',timedelta(minutes=5))
body={'dialogue':[{'role':'user','text':'AIの紹介動画を作りたい。個人で仕事をしている人向け。普通の部屋で人が働いている静かな実写の参考を見せて。'}]}
if '--cooking' in sys.argv:
 body={'dialogue':[{'role':'user','text':'料理の手元を中心にした、落ち着いた縦の動画をInstagramに出したい。参考を見せて。'}]}
response=httpx.post('http://127.0.0.1:8000/api/v1/editor-assistant/visual-decision',
 headers={'Authorization':'Bearer '+token},json=body,timeout=40)
response.raise_for_status()
value=response.json()
out=ROOT/('scratch/reference-routing/production-cooking-decision.json' if '--cooking' in sys.argv else 'scratch/reference-routing/production-decision.json')
out.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'status':response.status_code,'action':value.get('action'),
 'ids':value.get('selected_library_ids'),'ms':value.get('elapsed_ms'),
 'observed_search_context':'Video observation:' in json.dumps(value.get('url_retrieval',{})),
 'routing':value.get('url_retrieval',{}).get('routing')}))
