"""Writes down the Dan pin's lifelog segments (app/services/lifelog.py) with Whisper on this PC's GPU.

Watches the NAS lifelog folders of the last two days for .ogg files without a .json beside them, transcribes each
(Japanese, large-v3, VAD on), writes <file>.json and appends the text to the day's local index. Files older than
KEEP_DAYS are removed. One process; started hidden by the DanLifelogWorker task (scripts/run_hidden.vbs).
Log: .tmp/lifelog_worker.log
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
LOG = ROOT / ".tmp" / "lifelog_worker.log"


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def cuda_dlls() -> None:
    # cuBLAS / cuDNN come from the nvidia-*-cu12 wheels; Windows needs their bin folders on the DLL path
    for sp in site.getsitepackages() + [site.getusersitepackages()]:
        for d in glob.glob(os.path.join(sp, "nvidia", "*", "bin")):
            os.add_dll_directory(d)
            os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]


def main() -> None:
    from app.services import lifelog
    cuda_dlls()
    from faster_whisper import WhisperModel
    try:
        model = WhisperModel("large-v3", device="cuda", compute_type="int8_float16")   # shares the 8 GB GPU with other work
        log("model on GPU")
    except Exception as exc:  # no GPU: slower, still works
        log(f"GPU unavailable ({exc}); CPU int8")
        model = WhisperModel("large-v3", device="cpu", compute_type="int8")
    last_cleanup = 0.0
    while True:
        done = 0
        for back in (1, 0):
            day = (datetime.now(lifelog.JST) - timedelta(days=back)).strftime("%Y-%m-%d")
            folder = lifelog.AUDIO_ROOT / day
            if not folder.exists():
                continue
            for audio in sorted(folder.glob("*.ogg")):
                out = audio.with_suffix(".json")
                if out.exists():
                    continue
                try:
                    started = time.time()
                    segments, info = model.transcribe(str(audio), language="ja", vad_filter=True, beam_size=5,
                                                      condition_on_previous_text=False)
                    parts = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments]
                    text = "".join(p["text"] for p in parts).strip()
                    hh, mm, ss = audio.name[0:2], audio.name[2:4], audio.name[4:6]
                    start = datetime.fromisoformat(f"{day}T{hh}:{mm}:{ss}").replace(tzinfo=lifelog.JST)
                    entry = {"start": start.isoformat(), "seconds": round(info.duration, 2), "text": text,
                             "audio": str(audio), "parts": parts}
                    out.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
                    if text:
                        lifelog.add_transcript({k: entry[k] for k in ("start", "seconds", "text", "audio")})
                    done += 1
                    log(f"{audio.name} {info.duration:.1f}s -> {len(text)} chars in {time.time() - started:.1f}s")
                except Exception:
                    log(f"{audio.name} failed: {traceback.format_exc(limit=2)}")
                    out.write_text(json.dumps({"error": True}), encoding="utf-8")
        if time.time() - last_cleanup > 6 * 3600:
            last_cleanup = time.time()
            cutoff = (datetime.now(lifelog.JST) - timedelta(days=lifelog.KEEP_DAYS)).strftime("%Y-%m-%d")
            for folder in lifelog.AUDIO_ROOT.glob("20??-??-??"):
                if folder.name < cutoff:
                    for f in folder.iterdir():
                        f.unlink(missing_ok=True)
                    folder.rmdir()
                    log(f"removed {folder.name}")
        if not done:
            time.sleep(5)


if __name__ == "__main__":
    log("start")
    try:
        main()
    except Exception:
        log("crashed: " + traceback.format_exc())
        raise
