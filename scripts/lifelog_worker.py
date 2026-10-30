"""Persistent lifelog transcription worker; restart with launchd/Task Scheduler on exit.

Audio and text live outside releases. Failed audio remains pending, with bounded
retry delay. New speech is processed before the historical backlog.
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
LOG = lifelog.STATE_ROOT / 'worker.log'


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


def process_audio(audio, model):
    out = audio.with_suffix('.json')
    entry = None
    if out.exists():
        try:
            entry = json.loads(out.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            pass
    if not entry or entry.get('error'):
        segments, info = model.transcribe(str(audio), language='ja', vad_filter=True,
                                         beam_size=5, condition_on_previous_text=False)
        parts = [{'start': round(s.start, 2), 'end': round(s.end, 2), 'text': s.text.strip()} for s in segments]
        n = audio.name
        start = datetime.fromisoformat(f'{audio.parent.name}T{n[:2]}:{n[2:4]}:{n[4:6]}').replace(tzinfo=lifelog.JST)
        entry = {'start': start.isoformat(), 'seconds': round(info.duration, 2),
                 'text': ''.join(p['text'] for p in parts).strip(), 'audio': str(audio), 'parts': parts}
        tmp = out.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding='utf-8')
        tmp.replace(out)
    # Rebuild a missing index even after a crash between result and index writes.
    if entry.get('text'):
        rows = lifelog.read_day(entry['start'][:10])
        if not any(Path(r.get('audio', '').replace('\\', '/')).name == audio.name for r in rows):
            lifelog.add_transcript({k: entry[k] for k in ('start', 'seconds', 'text', 'audio')})
    return entry


def run_pass(model, completed, retries):
    now = time.time()
    pending = [p for p in lifelog.AUDIO_ROOT.glob('20??-??-??/*.ogg')
               if str(p) not in completed and retries.get(str(p), 0) <= now]
    # A bounded batch lets fresh uploads take priority on the next pass.
    for audio in sorted(pending, reverse=True)[:50]:
        try:
            entry = process_audio(audio, model)
            completed.add(str(audio))
            retries.pop(str(audio), None)
            log(f'{audio.parent.name}/{audio.name}: {len(entry.get("text", ""))} chars')
        except Exception:
            # Never write an error marker to the failed storage, or mark it done.
            retries[str(audio)] = time.time() + 60
            log(f'{audio.name}: retry in 60s: {traceback.format_exc(limit=2)}')
    return len(pending)


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
    log(f'model loaded: {name} {device}')
    completed, retries = set(), {}
    last_cleanup = 0
    while True:
        try:
            if time.time() - last_cleanup > 21600:
                cleanup_audio()
                last_cleanup = time.time()
            count = run_pass(model, completed, retries)
            (lifelog.STATE_ROOT / 'worker-status.json').write_text(json.dumps({'at': time.time(), 'pending': count, 'retrying': len(retries)}))
            time.sleep(1 if count else 5)
        except Exception:
            log('scan failed; retrying: ' + traceback.format_exc(limit=2))
            time.sleep(30)


if __name__ == '__main__':
    main()
