import sys

import psutil

from app.services.run_reconciler import owner_gone


def me():
    p = psutil.Process()
    return {'pid': p.pid, 'created': p.create_time()}


def test_owner_gone_only_for_a_dead_generation_on_this_machine():
    dead = {'pid': me()['pid'], 'created': 1.0}
    assert owner_gone({'metadata': {'machine': sys.platform + '@gen-a', 'process_owner': dead}})
    assert not owner_gone({'metadata': {'machine': sys.platform + '@gen-a', 'process_owner': me()}})
    assert not owner_gone({'metadata': {'machine': 'win32@gen-a', 'process_owner': dead}})
    assert not owner_gone({'metadata': {'machine': sys.platform, 'process_owner': dead}})
    assert not owner_gone({'metadata': {'machine': sys.platform + '@gen-a'}})
    assert not owner_gone({})


def test_generation_core_schedules_its_reconciler():
    src = open('app/core/main.py', encoding='utf-8').read()
    standby = src.index('if is_standby():')
    assert src.index('run_reconciler.loop()', standby) < src.index('else:', standby)
