"""Shared, persistent ceiling for this approved synthetic evaluation only."""
import json
from pathlib import Path

LEDGER=Path(__file__).resolve().parents[1]/'scratch/jev-speed-audit-20260917/api-budget.json'
APPROVED_USD=3.0

def reserve(state, questions):
    # Evaluate serially; reserve before sending, including timeouts/unavailable.
    # UTF-8 bytes + generous framing allowance upper-bound this test's token cost
    # under the published $0.042 / million input tokens, outputs free.
    size=len(json.dumps({'state':state,'questions':questions},ensure_ascii=False).encode('utf-8'))+4096
    data=json.loads(LEDGER.read_text(encoding='utf-8')) if LEDGER.exists() else {'attempts':0,'input_byte_allowance':0}
    if data['attempts']>=200 or (data['input_byte_allowance']+size)*.042/1_000_000 > APPROVED_USD:
        return False
    data['attempts']+=1
    data['approved_ceiling_usd']=APPROVED_USD
    data['input_byte_allowance']+=size
    data['conservative_cost_usd']=round(data['input_byte_allowance']*.042/1_000_000,6)
    data['basis']='Published input pricing; includes reserved failed attempts and framing allowance, not an invoice.'
    LEDGER.parent.mkdir(parents=True,exist_ok=True)
    LEDGER.write_text(json.dumps(data,indent=2),encoding='utf-8')
    return True
