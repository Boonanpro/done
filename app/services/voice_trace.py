"""Bounded local metadata for voice requests; no transcripts or tool arguments."""
import contextvars
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

scope = contextvars.ContextVar('voice_trace_scope', default={})
PATH = Path(__file__).resolve().parents[2] / '.tmp' / 'voice-backend-events.jsonl'
_lock = threading.Lock()


def record(phase, **fields):
    allowed = {'route','tool','call_id','elapsed_ms','error_type','output_count','result_chars','message_count'}
    row = {**scope.get(), 'at':datetime.now(timezone.utc).isoformat(), 'phase':phase,
           **{k:v for k,v in fields.items() if k in allowed}}
    try:
        with _lock:
            PATH.parent.mkdir(parents=True, exist_ok=True)
            if PATH.exists() and PATH.stat().st_size > 4 * 1024 * 1024:
                PATH.replace(PATH.with_suffix('.previous.jsonl'))
            with PATH.open('a',encoding='utf-8') as out:
                out.write(json.dumps(row,ensure_ascii=False)+'\n')
    except OSError:
        logging.getLogger(__name__).warning('voice metadata persistence unavailable')
