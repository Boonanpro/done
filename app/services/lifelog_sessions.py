"""Who said what, decided again once a conversation is over (2026-11-09).

The owner asked for the speakers to be as right as possible, with every technique in scope. Measured on two scenes of
11/7 with hand-made answers (the Shibuya bar 21:00-21:36, four people; スヤさん's place 17:18-17:40, quiet), the
characters given the wrong person went from 31% to 7% in the bar and from 9% to 1% in the quiet room when a whole
conversation is split at once, instead of one recording (up to 60 s) at a time with the voices joined one by one
(~/dan-workspace/lifelog-spk-lab/v2, ev.py). Most of the old error was one person in several numbers: in a minute
of a noisy bar a voice is heard for a few seconds, too little to recognise it again.

So the recordings are still written as they come (lifelog_speakers.transcribe, for the live text), and once the talk
has paused for SESSION_GAP the recordings of that conversation are split again together:
  1. pyannote speaker-diarization-community-1 on the joined audio (scripts/lifelog_session_diar.py in its own Python;
     beat pyannote 3.1, NVIDIA Sortformer and a vote of the three on both scenes).
  2. The words of each recording are grouped into pieces (a breath of one speaker) and each piece gets the speaker
     covering most of it; then each piece of 0.7 s or more goes to the speaker whose CAM++ centre its own voice is
     clearly closer to (margin REASSIGN_MARGIN), which fixes short replies swallowed by the speaker around them.
  3. Each speaker of the conversation has one centre (all its pieces), which is what the day's numbering and the
     voice book see (lifelog_speakers.replace_day): a conversation's voice is placed with a whole conversation of
     speech behind it, and two speakers of one conversation never share a number.
Tried and not used: noise removal first (DeepFilterNet: the quiet room went from 1% to 20% wrong), the words alone
read by a local language model (gemma 4 / Qwen 3.8: 15% / 47% wrong), giving pyannote the number of people.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

from app.services import lifelog
from app.services import lifelog_speakers as speakers

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "lifelog_session_diar.py"
PYTHON = Path(os.environ.get("DAN_PYANNOTE_PYTHON") or Path.home() / "pya-venv" / "bin" / "python")
RATE = speakers.RATE
SESSION_GAP = 600        # seconds of no recording that end a conversation
SESSION_MAX = 5400       # a longer talk is split into parts of this length (joined again by their voices)
PIECE_GAP, PIECE_MAX = 0.25, 2.5   # a piece: words with no gap over 0.25 s, at most 2.5 s, cut at 。？！
EMBED_MIN = 0.7          # a piece this long has a usable voice embedding
CENTRE_MIN, CENTRE_PIECES = 1.2, 5
REASSIGN_MARGIN = 0.05   # 0.0-0.1 all helped on both scenes (bar 12% -> 7.4-8.1%, room 1.4% -> 1.0-3.3%)
STATE_SUFFIX = ".sessions.json"


def available() -> bool:
    return speakers.available() and PYTHON.exists() and SCRIPT.exists()


# ---------------------------------------------------------------- conversations of a day

def _at(name: str) -> int:
    return int(name[:2]) * 3600 + int(name[2:4]) * 60 + int(name[4:6])


def recordings(day: str) -> list[tuple[Path, dict]]:
    out = []
    for f in sorted((lifelog.AUDIO_ROOT / day).glob("*.json")):
        try:
            e = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        audio = f.with_suffix(".ogg")
        if e.get("v", 1) >= 3 and audio.exists() and (e.get("turns") or e.get("voices")):
            out.append((audio, e))
    return out


def conversations(day: str) -> list[list[tuple[Path, dict]]]:
    groups, last_end, first = [], None, None
    for audio, e in recordings(day):
        at = _at(audio.name)
        if not groups or at - last_end > SESSION_GAP or at - first > SESSION_MAX:
            groups.append([])
            first = at
        groups[-1].append((audio, e))
        last_end = at + float(e.get("seconds") or 0)
    return groups


def key(group) -> str:
    return hashlib.sha1("|".join(a.name for a, _ in group).encode()).hexdigest()[:12]


def _state_path(day: str) -> Path:
    return speakers.SPEAKERS_ROOT / f"{day}{STATE_SUFFIX}"


# ---------------------------------------------------------------- one conversation

def _write_wav(path: Path, y: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())


def diarize(samples: list[np.ndarray]) -> list[list]:
    """Speaker segments of each recording [[start, end, speaker], ...], from one pass over all of them joined
    with a second of silence between."""
    offs, parts, off = [], [], 0.0
    for y in samples:
        offs.append(off)
        parts += [y, np.zeros(RATE, np.float32)]
        off += len(y) / RATE + 1
    with tempfile.TemporaryDirectory() as d:
        wav, out = Path(d) / "talk.wav", Path(d) / "segs.json"
        _write_wav(wav, np.concatenate(parts))
        subprocess.run([str(PYTHON), str(SCRIPT), str(wav), str(out)], check=True, capture_output=True,
                       timeout=3600)
        segs = json.loads(out.read_text())
    per = [[] for _ in samples]
    for a, b, s in segs:
        for i, (o, y) in enumerate(zip(offs, samples)):
            lo, hi = max(a, o), min(b, o + len(y) / RATE)
            if hi > lo:
                per[i].append([round(lo - o, 3), round(hi - o, 3), s])
    return per


def pieces(entry: dict) -> list[dict]:
    """A breath of one speaker each: the recording's words (written since 2026-11-09), else its turns."""
    words = entry.get("words")
    if not words:
        return [{"s": t["start"], "e": t["end"], "t": t["text"]} for t in entry.get("turns") or [] if t.get("text")]
    out, cur = [], None
    for s, e, w in words:
        if cur and (s - cur["e"] > PIECE_GAP or cur["e"] - cur["s"] > PIECE_MAX or cur["t"][-1:] in "。？?!！"):
            out.append(cur)
            cur = None
        if cur is None:
            cur = {"s": s, "e": e, "t": w.strip()}
        else:
            cur["e"], cur["t"] = e, cur["t"] + w.strip()
    if cur:
        out.append(cur)
    return [p for p in out if p["t"]]


def _cover(p: dict, segs: list) -> str | None:
    got = {}
    for a, b, s in segs:
        o = min(b, p["e"]) - max(a, p["s"])
        if o > 0:
            got[s] = got.get(s, 0) + o
    if got:
        return max(got, key=got.get)
    near = [(min(abs(a - p["e"]), abs(b - p["s"])), s) for a, b, s in segs]
    near = [x for x in near if x[0] <= 0.5]
    return min(near)[1] if near else None


def label_pieces(samples: list[np.ndarray], segs: list[list], entries: list[dict]) -> list[list[dict]]:
    """Pieces of each recording with the conversation's speaker; short replies go to the voice they sound like."""
    all_p = []
    for y, sg, e in zip(samples, segs, entries):
        ps = pieces(e)
        for p in ps:
            p["spk"] = _cover(p, sg)
            seg = y[int(p["s"] * RATE):int(p["e"] * RATE)]
            p["v"] = speakers.embed(seg) if p["e"] - p["s"] >= EMBED_MIN and len(seg) >= EMBED_MIN * RATE else None
        all_p.append(ps)
    flat = [p for ps in all_p for p in ps]
    for _ in range(2):
        cen = centres(flat, CENTRE_MIN, CENTRE_PIECES)
        if len(cen) < 2:
            break
        for p in flat:
            if p["v"] is None or p["spk"] not in cen:
                continue
            best = max(cen, key=lambda k: float(cen[k] @ p["v"]))
            if best != p["spk"] and float(cen[best] @ p["v"]) - float(cen[p["spk"]] @ p["v"]) >= REASSIGN_MARGIN:
                p["spk"] = best
    return all_p


def centres(flat: list[dict], min_len: float = 0.0, min_pieces: int = 1) -> dict:
    acc, n = {}, {}
    for p in flat:
        if p["spk"] is None or p["v"] is None or p["e"] - p["s"] < min_len:
            continue
        w = p["e"] - p["s"]
        acc[p["spk"]] = acc.get(p["spk"], 0) + p["v"] * w
        n[p["spk"]] = n.get(p["spk"], 0) + 1
    return {k: speakers._unit(v) for k, v in acc.items() if n[k] >= min_pieces}


def write(group, labelled, k: str) -> list[dict]:
    """The recordings' entries with the conversation's speakers: turns say which speaker ("spk"), voices hold the
    speaker's centre over the whole conversation ("e"), its seconds in this recording ("s") and in all ("ss")."""
    flat = [p for ps in labelled for p in ps]
    cen = centres(flat)
    total = {}
    for p in flat:
        if p["spk"] in cen:
            total[p["spk"]] = total.get(p["spk"], 0) + p["e"] - p["s"]
    out = []
    for (audio, e), ps in zip(group, labelled):
        for i, p in enumerate(ps):   # a piece no speaker covers, or one with no centre, takes its neighbour's
            if p["spk"] not in cen:
                near = [q["spk"] for q in ps[i - 1::-1] if q["spk"] in cen] if i else []
                near = near or [q["spk"] for q in ps[i + 1:] if q["spk"] in cen]
                p["spk"] = near[0] if near else None
        turns = []
        for p in ps:
            if turns and turns[-1]["spk"] == p["spk"]:
                turns[-1]["end"], turns[-1]["text"] = p["e"], turns[-1]["text"] + p["t"]
            else:
                turns.append({"start": p["s"], "end": p["e"], "text": p["t"], "spk": p["spk"], "voice": None})
        here = {}
        for p in ps:
            if p["spk"] is not None:
                here[p["spk"]] = here.get(p["spk"], 0) + p["e"] - p["s"]
        e = dict(e)
        e["turns"] = [{**t, "start": round(t["start"], 2), "end": round(t["end"], 2)} for t in turns]
        e["voices"] = {s: {"s": round(secs, 1), "ss": round(total[s], 1), "e": speakers._round(cen[s])}
                       for s, secs in here.items()}
        e["session"] = k
        tmp = audio.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(e, ensure_ascii=False), encoding="utf-8")
        tmp.replace(audio.with_suffix(".json"))
        out.append(e)
    return out


def run_conversation(group) -> list[dict]:
    samples = [speakers.load_audio(a) for a, _ in group]
    segs = diarize(samples)
    labelled = label_pieces(samples, segs, [e for _, e in group])
    return write(group, labelled, key(group))


def run_day(day: str, *, force: bool = False, now: float | None = None) -> int:
    """Split again every conversation of the day that has ended and was not done in this form; then number the day's
    voices again. Returns the conversations done."""
    if not available():
        return 0
    now = time.time() if now is None else now
    done = speakers._read_json(_state_path(day), {})
    folder = lifelog.AUDIO_ROOT / day
    latest = max((f.stat().st_mtime for f in folder.glob("*.json")), default=0)
    if not force and latest <= done.get("_checked", 0):
        return 0   # nothing written since the last look, and no talk was waiting then
    waiting = False
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    count = 0
    for group in conversations(day):
        k = key(group)
        if k in done and not force:
            continue
        last = group[-1][0].name
        end = time.mktime(time.strptime(f"{day} {last[:6]}", "%Y-%m-%d %H%M%S")) + float(group[-1][1].get("seconds") or 0)
        if day == today and now - end < SESSION_GAP:
            waiting = True
            continue   # the talk may go on
        if len(group) == 1 and len(group[0][1].get("voices") or {}) <= 1:
            done[k] = {"at": now, "skipped": "one voice"}
            continue
        run_conversation(group)
        done[k] = {"at": now, "recordings": len(group)}
        count += 1
    if count:
        speakers.replace_day(day)
    if not waiting:
        done["_checked"] = max((f.stat().st_mtime for f in folder.glob("*.json")), default=0)
    speakers._write_json(_state_path(day), done)
    return count
