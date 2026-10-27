"""Cross-process restart drain lease and completion notifications.

Only a live, identity-checked helper can hold automatic work. UDP is a wake-up
hint, never proof that work is idle; the helper rechecks the existing guards.
A bounded timeout covers dropped hints and old processes without these hooks.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import time
import uuid

import psutil

ROOT = Path.home() / '.dan' / 'restart-waiters'


def leases():
    if not ROOT.exists():
        return
    for path in ROOT.glob('*.json'):
        try:
            row = json.loads(path.read_text())
            if (not isinstance(row, dict) or not isinstance(row.get('pid'), int) or row['pid'] <= 0
                    or not isinstance(row.get('port'), int) or not 0 < row['port'] < 65536):
                continue
            p = psutil.Process(row['pid'])
            if (row['expires'] > time.time() and p.create_time() == row['started']
                    and p.status() != psutil.STATUS_ZOMBIE):
                yield row
        except (OSError, ValueError, TypeError, KeyError, psutil.Error):
            continue


def draining():
    return any(leases())


def notify():
    # Never fail the work whose state just changed.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setblocking(False)
            for row in leases():
                try:
                    sock.sendto(b'changed', ('127.0.0.1', row['port']))
                except OSError:
                    pass
    except OSError:
        pass


@contextmanager
def waiting(seconds):
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / (str(uuid.uuid4()) + '.json')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('127.0.0.1', 0))
        row = dict(pid=os.getpid(), started=psutil.Process().create_time(),
                   expires=time.time() + seconds, port=sock.getsockname()[1])
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(row))
        temp.replace(path)
        try:
            yield sock
        finally:
            path.unlink(missing_ok=True)


def wait(sock, seconds):
    sock.settimeout(max(.001, seconds))
    try:
        sock.recv(128)
    except socket.timeout:
        pass
