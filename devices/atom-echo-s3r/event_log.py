"""Bounded diagnostic event logs. Never pass audio, transcripts, or credentials."""
import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def event_logger(name):
    log = logging.getLogger('dan.atom.' + name)
    if not log.handlers:
        directory = Path(__file__).resolve().parents[2] / '.tmp/atom-logs'
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(directory / (name + '.jsonl'), maxBytes=1024*1024, backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(message)s'))
        log.addHandler(handler);log.setLevel(logging.INFO);log.propagate=False
    def write(event, **fields):
        log.info(json.dumps({'at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'event': event, **fields}, ensure_ascii=False))
    return write
