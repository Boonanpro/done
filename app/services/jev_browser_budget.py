"""Owner-approved, persistent spending ceiling shared by browser MCP workers.

Only aggregate reservations are stored. Reserve before sending; failures are
not refunded. Byte accounting plus framing deliberately overestimates tokens.
"""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import time

PATH = Path.home()/'.dan'/'jev-browser-budget.json'
USD_PER_MILLION = .042


def read():
    try:
        data=json.loads(PATH.read_text(encoding='utf-8'))
        if not isinstance(data,dict):return None
        for key in ('approved_usd','reserved_usd'):
            if type(data.get(key)) not in (float,int) or not math.isfinite(data[key]) or data[key]<0:return None
        if type(data.get('requests')) is not int or type(data.get('max_requests')) is not int:return None
        return data
    except (OSError,ValueError,TypeError):return None


def enabled():
    override=os.getenv('DAN_JEV_BROWSER_ENABLED')
    if override is not None:return override=='1'
    data=read()
    return bool(data and data.get('enabled') is True and data.get('publish') is True and data['reserved_usd']<data['approved_usd']
                and 0<=data['requests']<data['max_requests'])


@contextmanager
def locked():
    import msvcrt
    PATH.parent.mkdir(parents=True,exist_ok=True)
    with PATH.with_suffix('.lock').open('a+b') as lock:
        if lock.tell()==0:lock.write(b'0');lock.flush()
        deadline=time.monotonic()+.1
        while True:
            try:
                lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);break
            except OSError:
                if time.monotonic()>=deadline:raise TimeoutError('budget_lock_busy')
                time.sleep(.005)
        try:yield
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)


def reserve(body,user_id):
    """Fail closed on missing/corrupt/unapproved/exhausted budgets."""
    size=len(json.dumps(body,ensure_ascii=False).encode('utf-8'))+4096
    cost=size*USD_PER_MILLION/1_000_000
    try:
        with locked():
            data=read()
            if not data or data.get('enabled') is not True or data.get('user_id')!=user_id:return False
            if not 0<=data['requests']<data['max_requests'] or data['reserved_usd']+cost>data['approved_usd']:return False
            data['reserved_usd']=round(data['reserved_usd']+cost,9)
            data['requests']+=1
            temp=PATH.with_suffix('.tmp')
            temp.write_text(json.dumps(data,indent=2),encoding='utf-8')
            os.replace(temp,PATH)
            return True
    except (OSError,TimeoutError,ValueError,TypeError):return False
