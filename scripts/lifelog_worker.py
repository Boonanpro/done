"""Persistent lifelog transcription worker; restart with launchd/Task Scheduler on exit.

Audio and text live outside releases. Failed audio remains pending, with bounded
retry delay. New speech is processed before the historical backlog.

Since 2026-11-08 every recording is also split by speaker (app/services/lifelog_speakers.py): the text says who spoke,
recordings of the last DAN_LIFELOG_BACKFILL_DAYS days written before that are written again, and after a pause in the
talk the day's new voices are given names from the conversation.
"""
from __future__ import annotations
import glob
import json
import os
import site
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services import lifelog
from app.services import lifelog_speakers as speakers
LOG = lifelog.STATE_ROOT / 'worker.log'
BACKFILL_DAYS = int(os.environ.get('DAN_LIFELOG_BACKFILL_DAYS', '7'))
NAME_AFTER_PAUSE = 300      # seconds without new speech before names are read from the talk
NAME_EVERY = 1200           # at most once in this many seconds per day


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a', encoding='utf-8') as f:
        f.write(f'{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n')


def cuda_dlls():
    if os.name != 'nt':
        return
    for sp in site.getsitepackages() + [site.getusersitepackages()]:
        for d in glob.glob(os.path.join(sp, 'nvidia', '*', 'bin')):
            os.add_dll_directory(d)
            os.environ['PATH'] = d + os.pathsep + os.environ['PATH']


def backfill_from():
    return (datetime.now(lifelog.JST) - timedelta(days=BACKFILL_DAYS)).strftime('%Y-%m-%d')


def write_plain(audio, model):
    """The text without speakers (no speaker models on this machine)."""
    segments, info = model.transcribe(str(audio), language='ja', vad_filter=True,
                                     beam_size=5, condition_on_previous_text=False)
    parts = [{'start': round(s.start, 2), 'end': round(s.end, 2), 'text': s.text.strip()} for s in segments]
    n = audio.name
    start = datetime.fromisoformat(f'{audio.parent.name}T{n[:2]}:{n[2:4]}:{n[4:6]}').replace(tzinfo=lifelog.JST)
    return {'start': start.isoformat(), 'seconds': round(info.duration, 2),
            'text': ''.join(p['text'] for p in parts).strip(), 'audio': str(audio), 'parts': parts}


def process_audio(audio, model, rows_of):
    """The recording's entry, and whether the day's index must take it (new, re-written, or its row is missing)."""
    out = audio.with_suffix('.json')
    entry = None
    if out.exists():
        try:
            entry = json.loads(out.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            pass
    stale = (entry and not entry.get('error') and entry.get('v', 1) < speakers.VERSION and speakers.available()
             and audio.parent.name >= backfill_from())
    if not entry or entry.get('error') or stale:
        entry = speakers.transcribe(model, audio) if speakers.available() else write_plain(audio, model)
        tmp = out.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding='utf-8')
        tmp.replace(out)
        return entry, True
    # Rebuild a missing (or older) index row even after a crash between result and index writes.
    row = rows_of(entry['start'][:10]).get(audio.name)
    if entry.get('text') and (row is None or (entry.get('turns') and not row)):
        return entry, True
    return entry, False


def run_pass(model, completed, retries):
    now = time.time()
    pending = [p for p in lifelog.AUDIO_ROOT.glob('20??-??-??/*.ogg')
               if str(p) not in completed and retries.get(str(p), 0) <= now]
    cache = {}

    def rows_of(day):   # {audio name: has turns} of the day's index, read once per pass
        if day not in cache:
            cache[day] = {Path(r.get('audio', '').replace('\\', '/')).name: bool(r.get('turns')) for r in lifelog.read_day(day)}
        return cache[day]

    touched = {}
    # A bounded batch lets fresh uploads take priority on the next pass.
    for audio in sorted(pending, reverse=True)[:50]:
        try:
            entry, changed = process_audio(audio, model, rows_of)
            completed.add(str(audio))
            retries.pop(str(audio), None)
            if changed:
                touched.setdefault(audio.parent.name, []).append(entry)
                log(f'{audio.parent.name}/{audio.name}: {len(entry.get("text", ""))} chars')
        except Exception:
            # Never write an error marker to the failed storage, or mark it done.
            retries[str(audio)] = time.time() + 60
            log(f'{audio.name}: retry in 60s: {traceback.format_exc(limit=2)}')
    for day, entries in touched.items():
        lifelog.upsert_rows(day, entries)
    return len(pending)


def name_voices():
    """After a pause in the talk, read the names of the day's new voices out of the conversation."""
    if not speakers.available():
        return
    for path in sorted(speakers.SPEAKERS_ROOT.glob('20??-??-??.json'))[-(BACKFILL_DAYS + 1):]:
        day = path.stem
        st = speakers.day_state(day)
        spoken, named = st.get('spoken_at', 0), st.get('named_at', 0)
        if spoken <= named or time.time() - spoken < NAME_AFTER_PAUSE or time.time() - named < NAME_EVERY:
            continue
        try:
            got = speakers.name_day(day)
            log(f'names {day}: ' + ', '.join(f'{n["voice"]}={n["name"]}{"" if n["sure"] else "?"}' for n in got))
        except Exception:
            log(f'names {day} failed: {traceback.format_exc(limit=2)}')
        speakers.mark_named(day)


def cleanup_audio():
    cutoff = (datetime.now(lifelog.JST) - timedelta(days=lifelog.KEEP_DAYS)).strftime('%Y-%m-%d')
    for folder in lifelog.AUDIO_ROOT.glob('20??-??-??'):
        if folder.name < cutoff:
            for f in folder.iterdir():
                if f.is_file():
                    f.unlink(missing_ok=True)
            folder.rmdir()


def main():
    lifelog.STATE_ROOT.mkdir(parents=True, exist_ok=True)
    lock = (lifelog.STATE_ROOT / 'worker.lock').open('w')
    if os.name == 'nt':
        import msvcrt
        lock.write('0'); lock.flush(); lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    cuda_dlls()
    from faster_whisper import WhisperModel
    name = os.environ.get('DAN_LIFELOG_MODEL', 'large-v3')
    device = os.environ.get('DAN_LIFELOG_DEVICE', 'cuda' if os.name == 'nt' else 'cpu')
    model = WhisperModel(name, device=device, compute_type='int8_float16' if device == 'cuda' else 'int8',
                         cpu_threads=4, num_workers=1)
    log(f'model loaded: {name} {device}; speakers {"on" if speakers.available() else "off (no models)"}')
    completed, retries = set(), {}
    last_cleanup = last_names = 0
    while True:
        try:
            if time.time() - last_cleanup > 21600:
                cleanup_audio()
                last_cleanup = time.time()
            count = run_pass(model, completed, retries)
            (lifelog.STATE_ROOT / 'worker-status.json').write_text(json.dumps({'at': time.time(), 'pending': count, 'retrying': len(retries)}))
            if time.time() - last_names > 60:
                name_voices()
                last_names = time.time()
            time.sleep(1 if count else 5)
        except Exception:
            log('scan failed; retrying: ' + traceback.format_exc(limit=2))
            time.sleep(30)


if __name__ == '__main__':
    main()
