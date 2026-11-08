"""Who said what in the lifelog (2026-11-08).

The owner asked whether the all-day recording knows who is talking, and then for more: a number for each voice, a name
as soon as the conversation gives one away (「本田です」, someone called 「スヤさん」, 「13時 スヤさん撮影」 in the
calendar), and the same name the next day from the voice alone. The phone and the Dan pin feed the same recordings,
so one voice book serves both. Everything stays on this Mac; nothing here is sent anywhere except the short text of a
conversation to the language model that reads names out of it.

How it goes, for one recording (one speech segment from the phone, up to 60 s):
  1. analyze(): pyannote segmentation + CAM++ voice embeddings (sherpa-onnx, local, free) cut the recording into
     turns of local speakers, with one voice embedding per local speaker.
  2. The words Whisper wrote (with word times) are given to the turn they fall in.
  3. place(): each local speaker is matched against the voice book (people known by name, any day) and today's
     numbered voices; close enough joins, otherwise a new number. A voice that joins a numbered voice moves its
     centre, so the day's numbers stay the same from morning to night.
  4. render(): the text of the row reads 「［みきさん］…［話者2］…」. Names given later (the naming pass, or the owner's
     correction) re-render the day's index, so every reader of the index sees the current names.

Naming (name_day): the numbered voices of the day that have spoken for a while are shown to the language model with
the lines where names appear and the day's calendar. It answers a name per voice with the quote it rests on and
whether it is sure (introduced themselves, or called by that name more than once) or a guess. A guess shows as
「スヤさん？」. A sure name, or the owner's correction, puts the voice into the voice book, so the next day the voice
alone brings the name.

Files (all under ~/.dan/lifelog, outside releases):
  speakers/<day>.json  today's voices: {"voices": {"3": {"c": centre, "s": seconds, "who": person id, "guess": ...}}}
  people.json          the voice book: {"people": {"p_ab12": {"name": "スヤさん", "owner": false, "x": [examples]}}}
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import types
import uuid
import functools
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.services import lifelog

MODELS = Path(os.environ.get("DAN_LIFELOG_MODELS") or lifelog.STATE_ROOT / "models")
SEGMENTATION = "pyannote-seg-3.0.onnx"
EMBEDDING = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
SPEAKERS_ROOT = lifelog.STATE_ROOT / "speakers"
PEOPLE = lifelog.STATE_ROOT / "people.json"
RATE = 16000
VERSION = 3   # 3: stricter outro filter (2026-11-08); recordings written by 2 are written again

LOCAL_THRESHOLD = 0.6     # sherpa's clustering inside one recording (larger = fewer speakers)
JOIN_DAY = 0.45           # cosine to a numbered voice's centre to be that voice
# Cosine to one example in the voice book to be that person (a name is a stronger claim than a number). Measured on
# 11/7 17:18-17:30 against the owner's example: his own pieces 0.63-0.89, the other man's 0.12-0.47 (0.65-0.72 only
# where the two were mixed in one piece). 0.55 let the other man, a woman and the owner's brother into 「みきさん」.
JOIN_PERSON = 0.62
JOIN_PERSON_CENTRE = 0.62  # the same, for the centre of a numbered voice that has talked 30 s
MIN_VOICE_SECONDS = 0.8   # shorter speech gives no usable embedding; it keeps the label of the turn next to it
SHORT_SECONDS = 2.5       # under this, an embedding is noisy (「はい」「そのまま」): see place()
SHORT_JOIN = 0.35
SHORT_MARGIN = 0.07
MAX_EXAMPLES = 24
OWNER_NAME = "みきさん"
MEDIA = "動画・放送の音"   # TV, a video, a station announcement: shown as 「動画・放送の音？」, never put in the voice book

# Whisper writes these over silence, music and noise (YouTube outros). A part made only of them, with no speech under
# it, is dropped.
PHANTOMS = ("ご視聴ありがとうございました", "ご覧いただきありがとうございます", "ご覧いただきありがとうございました",
            "チャンネル登録", "次の動画でお会いしましょう", "おやすみなさい", "最後までご視聴",
            "字幕視聴ありがとうございました", "お疲れ様でした", "それでは", "では")

_lock = lifelog.state_lock


# ---------------------------------------------------------------- models

@lru_cache(None)
def _diarizer():
    import sherpa_onnx
    cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(MODELS / SEGMENTATION)),
            num_threads=2),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(MODELS / EMBEDDING), num_threads=2),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=LOCAL_THRESHOLD),
        min_duration_on=0.3, min_duration_off=0.5)
    return sherpa_onnx.OfflineSpeakerDiarization(cfg)


@lru_cache(None)
def _extractor():
    import sherpa_onnx
    return sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(MODELS / EMBEDDING), num_threads=2))


def available() -> bool:
    return (MODELS / SEGMENTATION).exists() and (MODELS / EMBEDDING).exists()


def embed(samples: np.ndarray) -> np.ndarray:
    ex = _extractor()
    s = ex.create_stream()
    s.accept_waveform(RATE, samples)
    s.input_finished()
    v = np.asarray(ex.compute(s), dtype=np.float32)
    return v / (np.linalg.norm(v) or 1)


def load_audio(path) -> np.ndarray:
    import subprocess
    ffmpeg = os.environ.get("FFMPEG") or ("/opt/homebrew/bin/ffmpeg" if Path("/opt/homebrew/bin/ffmpeg").exists() else "ffmpeg")
    out = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32).copy()


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    return v / (np.linalg.norm(v) or 1)


# ---------------------------------------------------------------- one recording

def analyze(samples: np.ndarray) -> tuple[list[dict], dict]:
    """Turns [{start, end, local}] and {local: (embedding, seconds, loudness dBFS)} for one recording."""
    if len(samples) < RATE:
        return [], {}
    result = _diarizer().process(samples).sort_by_start_time()
    turns = [{"start": round(r.start, 2), "end": round(r.end, 2), "local": int(r.speaker)} for r in result]
    voices = {}
    for local in {t["local"] for t in turns}:
        pieces = [samples[int(t["start"] * RATE):int(t["end"] * RATE)] for t in turns if t["local"] == local]
        y = np.concatenate(pieces) if pieces else np.zeros(0, np.float32)
        if len(y) >= MIN_VOICE_SECONDS * RATE:
            loud = float(20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-9))
            voices[local] = (embed(y), len(y) / RATE, loud)
    return turns, voices


def is_phantom(text: str, covered: float, seconds: float = 0.0, logprob: float | None = None) -> bool:
    """A Whisper part that is only a YouTube outro written over noise, music or silence. On 11/7 these came as
    「ご視聴ありがとうございました」 stretched over 30 s (under 1 character a second), or as a short outro Whisper
    was unsure of (average log-probability below -0.85); someone really saying it speaks it at a normal speed."""
    t = re.sub(r"[\s。、．，,.!！?？]", "", text or "")
    if not t:
        return True
    left = t
    for p in PHANTOMS:
        left = left.replace(p, "")
    if left:
        return False
    slow = seconds > 0 and len(t) / seconds < 2.0
    unsure = logprob is not None and logprob < -0.85
    return covered < 0.3 or slow or unsure


def words_to_turns(words: list[dict], turns: list[dict]) -> list[dict]:
    """Give each word to the turn it falls in (or the nearest one); consecutive turns of one speaker are joined."""
    if not turns:
        return [{"start": words[0]["start"], "end": words[-1]["end"], "local": None,
                 "text": "".join(w["word"] for w in words).strip()}] if words else []
    out = []
    for w in words:
        mid = (w["start"] + w["end"]) / 2
        inside = [t for t in turns if t["start"] - 0.15 <= mid <= t["end"] + 0.15]
        if inside:
            # Under overlapping speech the words are nearly always the main speaker's (Whisper rarely writes the
            # 「うん」 said under someone's sentence): the turn covering most of the word, then the longer turn.
            t = max(inside, key=lambda t: (round(min(w["end"], t["end"]) - max(w["start"], t["start"]), 1),
                                           t["end"] - t["start"]))
        else:
            t = min(turns, key=lambda t: min(abs(mid - t["start"]), abs(mid - t["end"])))
        if out and out[-1]["local"] == t["local"]:
            out[-1]["end"] = max(out[-1]["end"], w["end"])
            out[-1]["text"] += w["word"]
        else:
            out.append({"start": w["start"], "end": w["end"], "local": t["local"], "text": w["word"]})
    for o in out:
        o["text"] = o["text"].strip()
        o["start"], o["end"] = round(o["start"], 2), round(o["end"], 2)
    return [o for o in out if o["text"]]


def speech_cover(turns: list[dict], start: float, end: float) -> float:
    span = max(end - start, 1e-3)
    got = sum(max(0.0, min(end, t["end"]) - max(start, t["start"])) for t in turns)
    return min(1.0, got / span)


# ---------------------------------------------------------------- storage

def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, suffix=".tmp", delete=False, encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        tmp = Path(f.name)
    tmp.replace(path)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def day_state(day: str) -> dict:
    s = _read_json(SPEAKERS_ROOT / f"{day}.json", {})
    s.setdefault("voices", {})
    s.setdefault("next", 1)
    return s


def save_day(day: str, state: dict) -> None:
    _write_json(SPEAKERS_ROOT / f"{day}.json", state)


def people() -> dict:
    p = _read_json(PEOPLE, {})
    p.setdefault("people", {})
    return p


def save_people(book: dict) -> None:
    _write_json(PEOPLE, book)


def _round(v) -> list:
    return [round(float(x), 4) for x in v]


# ---------------------------------------------------------------- placing voices

def best_person(v: np.ndarray, book: dict) -> tuple[str | None, float]:
    best, score = None, -1.0
    for pid, p in book["people"].items():
        xs = p.get("x") or []
        if not xs:
            continue
        s = float(np.max(np.asarray(xs, dtype=np.float32) @ v))
        if s > score:
            best, score = pid, s
    return best, score


def _near(vo: dict, at: float | None, minutes: float = 15) -> bool:
    if at is None or "t" not in vo:
        return True
    a, b = vo["t"]
    return a - minutes * 60 <= at <= b + minutes * 60


def place(day: str, v: np.ndarray, seconds: float, state: dict, book: dict, at: float | None = None) -> str | None:
    """The day's voice number for one embedding; joins a person of the voice book or a numbered voice, or starts one.

    A short piece of speech (under SHORT_SECONDS) gives a noisy embedding: it joins only a voice heard around the same
    time that it is clearly closest to, and otherwise stays unnumbered (None, shown as ［？］) instead of starting a new
    number for every 「はい」."""
    short = seconds < SHORT_SECONDS
    pid, ps = best_person(v, book)
    scores = sorted(((float(_unit(vo["c"]) @ v), key) for key, vo in state["voices"].items()
                     if not short or _near(vo, at)), reverse=True)
    score, best = scores[0] if scores else (-1.0, None)
    second = scores[1][0] if len(scores) > 1 else -1.0
    if short:
        if best is not None and score >= SHORT_JOIN and score - second >= SHORT_MARGIN:
            key = best
        else:
            return None
    elif pid and ps >= JOIN_PERSON:
        # the person's voice of today, if there is one; otherwise a new number already named
        mine = [k for k, vo in state["voices"].items() if vo.get("who") == pid]
        if mine:
            key = max(mine, key=lambda k: float(_unit(state["voices"][k]["c"]) @ v))
        elif best is not None and score >= JOIN_DAY and not state["voices"][best].get("who"):
            key = best
            state["voices"][key]["who"] = pid
        else:
            key = str(state["next"])
            state["next"] += 1
            state["voices"][key] = {"c": _round(v), "s": 0.0, "who": pid}
    elif best is not None and score >= JOIN_DAY:
        key = best
    else:
        key = str(state["next"])
        state["next"] += 1
        state["voices"][key] = {"c": _round(v), "s": 0.0}
    vo = state["voices"][key]
    if at is not None:
        a, b = vo.get("t", (at, at))
        vo["t"] = [min(a, at), max(b, at)]
    if not short:   # a short piece joins but does not move the centre
        total = vo["s"] + seconds
        c = _unit(vo["c"]) * vo["s"] + v * seconds
        vo["c"], vo["s"] = _round(_unit(c)), round(total, 1)
        # a numbered voice that has talked a while is a steadier picture of the voice: look it up in the voice book
        if not vo.get("who") and vo["s"] >= 30 and vo["s"] - vo.get("looked", 0) >= 30:
            vo["looked"] = vo["s"]
            pid, ps = best_person(_unit(vo["c"]), book)
            # one person may be two numbers in a day (home and outside sound different): both get the name
            if pid and ps >= JOIN_PERSON_CENTRE and pid not in vo.get("not", []):
                vo["who"] = pid
                state["renamed"] = True
    return key


def label(day: str, key: str | None, state: dict | None = None, book: dict | None = None) -> str:
    if key is None:
        return "？"
    state = state or day_state(day)
    book = book or people()
    vo = state["voices"].get(str(key)) or {}
    who = vo.get("who")
    if who and who in book["people"]:
        return book["people"][who]["name"]
    g = vo.get("guess")
    if g and g.get("name"):
        return g["name"] + "？"
    return f"話者{key}"


def render(turns: list[dict], day: str, state=None, book=None) -> str:
    state = state or day_state(day)
    book = book or people()
    out, last = [], None
    for t in turns:
        name = label(day, t.get("voice"), state, book)
        if name != last:   # two numbers of one person (named the same) read as one speaker
            out.append(f"［{name}］")
            last = name
        out.append(t["text"])
    return "".join(out).strip()


def plain(turns: list[dict]) -> str:
    return "".join(t["text"] for t in turns).strip()


# ---------------------------------------------------------------- the whole entry for one recording

def transcribe(model, audio: Path, old: dict | None = None) -> dict:
    """The index entry for one recording: text with speakers, turns, voices.

    old: the entry written before speakers existed. When only one voice speaks in the recording its words need no
    times, so its old text is kept and Whisper is not run again (about half of a day's recordings; writing a past
    day again takes half the time)."""
    samples = load_audio(audio)
    turns, voices = analyze(samples) if available() else ([], {})
    duration = len(samples) / RATE
    outro = any(not re.sub(r"[\s。、．，,.!！?？]", "", functools.reduce(lambda a, b: a.replace(b, ""), PHANTOMS, p["text"]))
                for p in (old or {}).get("parts") or [])
    if (old is not None and old.get("parts") is not None and not outro   # an outro needs Whisper's own certainty
            and len(voices) <= 1 and len({t["local"] for t in turns}) <= 1):
        segments = [types.SimpleNamespace(start=p["start"], end=p["end"], text=p["text"], words=None, avg_logprob=None)
                    for p in old["parts"]]
        reuse = True
    else:
        segments, info = model.transcribe(samples, language="ja", vad_filter=True, beam_size=5,
                                          condition_on_previous_text=False, word_timestamps=True)
        segments, duration, reuse = list(segments), info.duration, False
    words, parts = [], []
    for s in segments:
        text = s.text.strip()
        if is_phantom(text, speech_cover(turns, s.start, s.end) if turns else 1.0, s.end - s.start,
                      getattr(s, "avg_logprob", None)):
            continue
        parts.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": text})
        if reuse:   # one speaker: the part is one "word" spanning its time
            words.append({"start": s.start, "end": s.end, "word": text})
        else:
            words += [{"start": w.start, "end": w.end, "word": w.word} for w in (s.words or [])]
    if not turns and words and words[-1]["end"] - words[0]["start"] >= 1.0:
        # Whisper heard words where the segmentation found no speaker (quiet, far speech): one speaker over the words
        a, b = words[0]["start"], words[-1]["end"]
        y = samples[int(a * RATE):int(b * RATE)]
        if len(y) >= MIN_VOICE_SECONDS * RATE and available():
            turns = [{"start": round(a, 2), "end": round(b, 2), "local": 0}]
            voices = {0: (embed(y), len(y) / RATE, float(20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-9)))}
    said = words_to_turns(words, turns)
    n = audio.name
    start = f"{audio.parent.name}T{n[:2]}:{n[2:4]}:{n[4:6]}+09:00"
    day = audio.parent.name
    keys = {}
    with _lock:
        state, book = day_state(day), people()
        at = int(n[:2]) * 3600 + int(n[2:4]) * 60 + int(n[4:6])
        for local, (v, secs, loud) in voices.items():
            keys[local] = place(day, v, secs, state, book, at)
        if voices:
            state["spoken_at"] = time.time()
        renamed = state.pop("renamed", False)
        save_day(day, state)
    if renamed:
        rerender_day(day)   # earlier rows of a voice that just got its name
    # a local speaker with too little speech for an embedding (not in voices) takes the label of the turn next to it;
    # one whose short embedding matched nobody stays None (［？］)
    for t in said:
        local = t.pop("local")
        t["voice"] = keys.get(local) if local in keys else "near"
    for i, t in enumerate(said):
        if t["voice"] == "near":
            near = [u["voice"] for u in said[i - 1::-1] if u["voice"] not in (None, "near")] if i else []
            near = near or [u["voice"] for u in said[i + 1:] if u["voice"] not in (None, "near")]
            t["voice"] = near[0] if near else None
    if not voices:
        for t in said:
            t["voice"] = None
    entry = {"start": start, "seconds": round(duration, 2), "text": render(said, day, state, book) if voices else plain(said),
             "plain": plain(said), "audio": str(audio), "parts": parts, "turns": said, "v": VERSION,
             "voices": {k: {"day_voice": keys[k], "s": round(secs, 1), "db": round(loud, 1), "e": _round(v)}
                        for k, (v, secs, loud) in voices.items()}}
    return entry


# ---------------------------------------------------------------- place a whole day again

def replace_day(day: str) -> int:
    """Number the day's voices again from the voice pieces kept with each recording, in time order (after the
    thresholds change, or the voice book learned someone). No audio is read: minutes for a whole day."""
    folder = lifelog.AUDIO_ROOT / day
    with _lock:
        old = day_state(day)
        state = {"voices": {}, "next": 1, "named_at": 0, "spoken_at": time.time()}
        book = people()
        entries = []
        for f in sorted(folder.glob("*.json")):
            try:
                e = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if e.get("v", 1) < 3 or not e.get("voices"):
                continue
            n = f.name
            at = int(n[:2]) * 3600 + int(n[2:4]) * 60 + int(n[4:6])
            moved, size = {}, {}
            for local, v in e["voices"].items():
                key = place(day, _unit(v["e"]), v["s"], state, book, at)
                old_key = v.get("day_voice")
                if old_key is not None and v["s"] > size.get(old_key, -1):   # two pieces that were one voice: the longer
                    moved[old_key], size[old_key] = key, v["s"]
                v["day_voice"] = key
            for t in e.get("turns") or []:
                t["voice"] = moved.get(t.get("voice"))
            e["text"] = render(e["turns"], day, state, book) if e.get("turns") else e.get("text", "")
            tmp = f.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(e, ensure_ascii=False), encoding="utf-8")
            tmp.replace(f)
            entries.append(e)
        state.pop("renamed", None)
        # the owner's corrections of that day are kept as far as they still point at a voice heard at that time
        save_day(day, state)
        lifelog._upsert(day, entries)
    rerender_day(day)
    return len(entries)


# ---------------------------------------------------------------- re-render the day's index

def rerender_day(day: str) -> int:
    """Rewrite the text of every row of the day from its turns and today's names. Returns rows changed."""
    path = lifelog.index_file(day)
    if not path.exists():
        return 0
    state, book = day_state(day), people()
    changed, out = 0, []
    with _lock:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("turns") and any(t.get("voice") for t in r["turns"]):
                text = render(r["turns"], day, state, book)
                if text != r.get("text"):
                    r["text"] = text
                    changed += 1
            out.append(json.dumps(r, ensure_ascii=False))
        if changed:
            with tempfile.NamedTemporaryFile("w", dir=path.parent, suffix=".tmp", delete=False, encoding="utf-8") as f:
                f.write("\n".join(out) + "\n")
                tmp = Path(f.name)
            tmp.replace(path)
    return changed


# ---------------------------------------------------------------- the voice book

def person_by_name(book: dict, name: str) -> str | None:
    norm = lambda s: re.sub(r"(さん|ちゃん|くん|君|様|氏)$", "", (s or "").strip().rstrip("？?"))
    for pid, p in book["people"].items():
        if norm(p["name"]) == norm(name):
            return pid
    return None


def owner_id(book: dict) -> str | None:
    return next((pid for pid, p in book["people"].items() if p.get("owner")), None)


def remember_voice(day: str, key: str, name: str, *, owner: bool = False, by: str = "conversation") -> str:
    """Name today's voice `key` and keep its centre in the voice book under that name (a new person if unknown)."""
    with _lock:
        state, book = day_state(day), people()
        vo = state["voices"][str(key)]
        pid = owner_id(book) if owner else person_by_name(book, name)
        if not pid:
            pid = "p_" + uuid.uuid4().hex[:6]
            book["people"][pid] = {"name": name, "owner": owner, "x": [], "since": day}
        p = book["people"][pid]
        if by == "owner":
            p["name"] = name
        p.setdefault("x", []).append(vo["c"])
        p["x"] = _spread(p["x"])
        p["by"] = by
        vo["who"] = pid
        vo.pop("guess", None)
        # another voice of today that is this same person (split across the day) joins too
        save_day(day, state)
        save_people(book)
    rerender_day(day)
    return pid


def _spread(xs: list) -> list:
    """Keep at most MAX_EXAMPLES examples, dropping the one most like the others (keeps different rooms/mics)."""
    while len(xs) > MAX_EXAMPLES:
        X = np.asarray(xs, dtype=np.float32)
        S = X @ X.T
        np.fill_diagonal(S, -1)
        xs.pop(int(np.argmax(S.max(axis=1))))
    return xs


def forget_name(day: str, key: str) -> None:
    """The owner says this voice is not who Dan said: take the name off (and the example out of the voice book)."""
    with _lock:
        state, book = day_state(day), people()
        vo = state["voices"][str(key)]
        pid = vo.pop("who", None)
        vo.pop("guess", None)
        vo["not"] = sorted(set(vo.get("not", []) + ([pid] if pid else [])))
        if pid and pid in book["people"]:
            c = _unit(vo["c"])
            xs = book["people"][pid].get("x", [])
            book["people"][pid]["x"] = [x for x in xs if float(_unit(x) @ c) < 0.98]
        save_day(day, state)
        save_people(book)
    rerender_day(day)


# ---------------------------------------------------------------- names from the conversation

NAME_RULES = """あなたは、常時録音の文字起こしを読んで、話者番号ごとに名前を推定する係です。
録音はスマホの持ち主「本田 樹（みきさん）」の1日です。［話者N］は声で分けた番号です（同じ番号は同じ声）。
声の分け方には少し間違いがあり、文字起こしには聞き間違いがあります。

名前の手がかり:
- 本人の名乗り（「本田です」「中村です」）: その行の話者がその名前。確か（sure）。
- 呼びかけ（「スヤさん」「シンちゃん」）: 呼ばれたのは、その行の話者ではなく相手。直後に返事をした話者か、話の相手。1回だけなら推測（guess）、別々の場面で2回以上合えば確か。
- 予定表: その時間に会う人の名前。推測の手がかりにだけ使う。
- 持ち主（みきさん）の声は、もう分かっていれば［みきさん］と出ています。
- みきさんや他の人と受け答えしている声は、その場にいる人（動画の撮影で話している人も、その場の人）。
- テレビ・動画・駅や店内の放送の声らしい番号（誰とも受け答えせず、話し方がナレーション・実況・アナウンス）は、名前ではなく
  {"voice": "8", "media": true, "quote": "根拠の行"} で返す。
- 「ママ」「店長」「先生」のような呼ばれ方も名前として使ってよい。
- 2人で話している所で呼びかけられた相手が分かれば、推測（sure=false）として出す。迷う時は推測で出してよい（画面には「？」付きで出る）。
- 文字に根拠の無い名前は付けない。分からない番号は出さない。

JSONだけで答える: {"names": [{"voice": "3", "name": "スヤさん", "sure": false, "quote": "根拠の行をそのまま"}]}
名前には「さん」等を付けて、本人の呼ばれ方に合わせる（例: スヤさん、シンちゃん、ママ）。"""


def _openai_key() -> str | None:
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if key:
        return key
    for env in (Path(__file__).resolve().parents[2] / ".env", Path.home() / "done" / ".env"):
        try:
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("OPENAI_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
    return None


def calendar_lines(day: str) -> str:
    try:
        from app.services.calendar_service import get_calendar_service
        from app.services.owner import resolve_owner_user_id
        events = get_calendar_service().get_events(resolve_owner_user_id(), days=1, max_results=30, start_date=day)
        return "\n".join(f"{(e.get('start') or '')[11:16]} {e.get('summary') or e.get('title') or ''}"
                         for e in events if isinstance(e, dict) and not e.get("error"))
    except Exception:
        return ""


# words that end like a name but are not one (「お客さん」「業者さん」「皆さん」)
NOT_NAMES = re.compile(r"(お客|業者|職人|皆|みな|奥|店員|運転手|お医者|看護師|大家|オーナー|お巡り|お隣|赤|お兄|お姉|おじ|おば|"
                       r"お父|お母|じい|ばあ|お坊|大工|美容師|先輩|後輩|編集者|視聴者|経営者|社員|担当者|お嬢|おにい|おねえ|"
                       r"親御|息子|娘|お子|子供|お友達|友達|彼女|彼氏|旦那|嫁|農家|漁師|社長|部長|課長|先生)(さん|ちゃん|くん|様)?$")


def has_name(text: str) -> bool:
    for m in NAME_HINT.finditer(text):
        word = m.group(0)
        stem = re.sub(r"(さん|ちゃん|くん|君|様|先生|社長)$", "", word)
        if m.group(1) and (NOT_NAMES.search(word) or NOT_NAMES.search(stem[-4:] + m.group(1))):
            continue
        return True
    return False


# a name said in a line: 「スヤさん」「シンちゃん」「ママ」, or a line that starts 「中村です」 (a self-introduction)
NAME_HINT = re.compile(r"[一-龥ァ-ヶーぁ-んA-Za-z]{1,8}(さん|ちゃん|くん|君|様|先生|社長)|ママ|パパ|と申します|って言います"
                       r"|］[一-龥ァ-ヶー]{1,6}です")


def name_lines(day: str, rows: list[dict], state: dict, book: dict, voices: list[str] | None = None,
               limit: int = 18000) -> str:
    """The lines the language model needs to name the given voices: for each voice, the lines with a name in them
    said within 90 s of it speaking (by anyone: 「スヤさん、…」 is said by the other person), the lines around
    them, and some of its own back-and-forth. A whole day is several times the limit; cutting it evenly lost every
    line that named 「スヤさん」 on 11/7."""
    lines = []
    for r in rows:
        at = int(r["start"][11:13]) * 3600 + int(r["start"][14:16]) * 60 + int(r["start"][17:19])
        for t in r.get("turns") or []:
            if t.get("voice") and t.get("text"):
                lines.append((t["voice"], at, f"{r['start'][11:19]} ［{label(day, t['voice'], state, book)}］{t['text']}"))
    if voices is None or sum(len(l) for *_, l in lines) <= limit:
        return "\n".join(l for *_, l in lines)
    named = [i for i, (_, _, l) in enumerate(lines) if has_name(l.split("］", 1)[-1])]
    per = max(1500, limit // max(1, len(voices)))
    keep = set()
    for v in voices:
        mine = [i for i, (k, _, _) in enumerate(lines) if k == v]
        if not mine:
            continue
        times = [lines[i][1] for i in mine]
        got, size = set(), 0
        near = sorted((min(abs(lines[j][1] - t) for t in times), j) for j in named)
        for gap, j in near:   # the closest names first
            if gap <= 90:
                for k in range(max(0, j - 1), min(len(lines), j + 2)):
                    if k not in got:
                        got.add(k)
                        size += min(400, len(lines[k][2]))
            if size > per * 0.6:
                break
        for i in mine[:: max(1, len(mine) // 6)][:6]:   # its own talk across the day, with the line before it
            for k in (i - 1, i):
                if k >= 0 and k not in got and size < per:
                    got.add(k)
                    size += min(400, len(lines[k][2]))
        keep |= got
    out = [lines[i][2][:400] for i in sorted(keep)]
    while sum(len(l) for l in out) > limit:
        out.pop()
    return "\n".join(out)


def name_day(day: str, *, model: str = "gpt-6-luna", min_seconds: float = 15.0) -> list[dict]:
    """Ask the language model for names of today's numbered voices; store guesses, remember sure ones."""
    key = _openai_key()
    if not key:
        return []
    state, book = day_state(day), people()
    open_voices = [k for k, vo in state["voices"].items() if not vo.get("who") and vo["s"] >= min_seconds]
    if not open_voices:
        return []
    rows = lifelog.read_day(day)
    text = name_lines(day, rows, state, book, open_voices)
    cal = calendar_lines(day)
    from openai import OpenAI
    prompt = (f"{day} の録音。名前を推定してほしい番号: {', '.join('話者' + k for k in open_voices)}\n"
              + (f"\nこの日の予定表:\n{cal}\n" if cal else "") + "\n文字起こし:\n" + text + "\n\n答えは JSON で。")
    r = OpenAI(api_key=key).responses.create(model=model, instructions=NAME_RULES, input=prompt,
                                             reasoning={"effort": "low"}, text={"format": {"type": "json_object"}})
    try:
        names = json.loads(r.output_text).get("names") or []
    except ValueError:
        return []
    done = []
    with _lock:
        state, book = day_state(day), people()
        for n in names:
            k = str(n.get("voice", "")).replace("話者", "")
            name = MEDIA if n.get("media") else (n.get("name") or "").strip().rstrip("？?")
            vo = state["voices"].get(k)
            if not vo or vo.get("who") or not name or vo.get("by_owner"):
                continue
            pid = person_by_name(book, name)
            if pid and pid in vo.get("not", []):
                continue
            n = {"voice": k, "name": name, "sure": bool(n.get("sure")) and name != MEDIA, "quote": (n.get("quote") or "")[:200]}
            vo["guess"] = {"name": name, "quote": n["quote"], "at": time.time()}
            done.append(n)
        save_day(day, state)
    for n in done:
        if is_owner_name(n["name"]):
            if n["sure"]:
                remember_voice(day, n["voice"], OWNER_NAME, owner=True, by="conversation")
        elif n["sure"]:
            remember_voice(day, n["voice"], n["name"], by="conversation")
    rerender_day(day)
    return done


def is_owner_name(name: str) -> bool:
    return re.sub(r"(さん|ちゃん|くん|君|様)$", "", name.strip()) in ("みき", "ミキ", "本田", "本田樹", "本田 樹", "樹", "みきさん")


def mark_named(day: str) -> None:
    with _lock:
        state = day_state(day)
        state["named_at"] = time.time()
        save_day(day, state)
