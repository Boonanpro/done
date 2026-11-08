"""The voices of a day that have no name yet, with a few seconds of each to listen to (2026-11-08).

The owner asked how to name 「話者75」: 「名前の無い人を出して」 in the chat (or in a call) should list the day's unnamed
voices, longest first, each with the time, a line they said and a short clip that plays in the chat; the owner answers
「これは吉田さん」 and Dan names the voice (scripts/lifelog_people.py name). The chat plays videos but not bare audio, so
a clip is a small MP4: a still card with who/when/what they said, and the recording's sound under it.

Used by scripts/lifelog_people.py (unnamed). Clips go to ~/.dan/lifelog/clips/<day>/ (outside releases).
"""
from __future__ import annotations

import glob
import json
import subprocess
import tempfile
from pathlib import Path

from app.services import lifelog, lifelog_speakers as sp

CLIPS_ROOT = lifelog.STATE_ROOT / "clips"
MIN_CLIP, MAX_CLIP = 2.5, 8.0   # seconds of one clip: long enough to know the voice, short enough to listen to many
GAP = 0.8                       # turns of the same voice closer than this are one stretch of speech
APART = 600                     # two clips of one voice at least 10 minutes apart (different scenes)


def unnamed(day: str, min_seconds: float = 20.0) -> list[dict]:
    """The day's voices without a sure name, longest first: {"voice", "label", "seconds"}. Media sound is left out."""
    state, book = sp.day_state(day), sp.people()
    out = []
    for key, vo in state["voices"].items():
        if vo.get("who") or vo["s"] < min_seconds or (vo.get("guess") or {}).get("name") == sp.MEDIA:
            continue
        out.append({"voice": key, "label": sp.label(day, key, state, book), "seconds": vo["s"]})
    return sorted(out, key=lambda v: -v["seconds"])


def stretches(day: str, voice: str) -> list[dict]:
    """Every stretch of speech of one voice: {"audio", "at" (seconds of the day), "start", "end", "text"}."""
    out = []
    for f in sorted((lifelog.AUDIO_ROOT / day).glob("*.json")):
        try:
            e = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        audio = Path(e.get("audio") or f.with_suffix(".ogg"))
        if not audio.exists():
            continue
        at = int(f.name[:2]) * 3600 + int(f.name[2:4]) * 60 + int(f.name[4:6])
        cur = None
        for t in e.get("turns") or []:
            if t.get("voice") == voice and cur and t["start"] - cur["end"] <= GAP:
                cur["end"], cur["text"] = t["end"], cur["text"] + t["text"]
            elif t.get("voice") == voice:
                cur = {"audio": str(audio), "at": at + t["start"], "start": t["start"], "end": t["end"], "text": t["text"]}
                out.append(cur)
            else:
                cur = None
    return out


def heard(s: dict) -> str:
    """What Whisper hears in the clip's seconds ('' when nothing trustworthy): a stretch whose words were guessed out
    of noise (11/7 21:50 「中村一応ずなったの中村…」) gives the owner nothing to recognise the voice by."""
    from app.services import voice_whisper
    start = max(0.0, s["start"] - 0.2)
    length = min(s["end"] - s["start"], MAX_CLIP) + 0.4
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", s["audio"],
                          "-ac", "1", "-ar", "24000", "-f", "f32le", "-"], capture_output=True, timeout=60).stdout
    import numpy as np
    return voice_whisper.transcribe(np.frombuffer(raw, dtype=np.float32)) if raw else ""


def pick(stretches_: list[dict], n: int = 1, check=heard, tries: int = 6) -> list[dict]:
    """The clearest few: whole sentences of 2.5 s or more, the most words first, from different scenes, whose sound
    Whisper can read again (check)."""
    good = [s for s in stretches_ if s["end"] - s["start"] >= MIN_CLIP and len(s["text"]) >= 8
            and not any(p in s["text"] for p in sp.PHANTOMS)]
    # a stretch that fits in one clip first (its words are all in the sound), then the most words
    good.sort(key=lambda s: (s["end"] - s["start"] > MAX_CLIP, -min(len(s["text"]), 60)))
    chosen = []
    for s in good:
        if tries <= 0 or len(chosen) == n:
            break
        if all(abs(s["at"] - c["at"]) >= APART for c in chosen):
            tries -= 1
            if not check or check(s):
                chosen.append(s)
    return chosen


def _font(size: int):
    from PIL import ImageFont
    for pattern in ("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", "/System/Library/Fonts/*角ゴシック W6.ttc",
                    "/System/Library/Fonts/*角ゴシック W3.ttc", "C:/Windows/Fonts/meiryob.ttc", "C:/Windows/Fonts/meiryo.ttc"):
        for path in glob.glob(pattern):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def card(path: Path, title: str, when: str, text: str) -> None:
    """A 960x540 still: the voice's label large, the time, and what they said (wrapped)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (960, 540), (24, 26, 31))
    d = ImageDraw.Draw(img)
    d.text((60, 56), title, font=_font(64), fill=(255, 255, 255))
    d.text((60, 150), when, font=_font(34), fill=(160, 168, 180))
    body, line, lines = _font(38), "", []
    for ch in "「" + text[:90] + "」":
        if d.textlength(line + ch, font=body) > 840:
            lines.append(line)
            line = ""
        line += ch
    lines.append(line)
    for i, l in enumerate(lines[:5]):
        d.text((60, 250 + i * 54), l, font=body, fill=(235, 238, 242))
    img.save(path)


def make_clip(day: str, voice: str, s: dict, label: str, index: int = 1) -> Path:
    """One MP4 for one stretch: the card for the picture, the recording's sound (evened out) for the audio."""
    folder = CLIPS_ROOT / day
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"voice{voice}_{index}.mp4"
    start = max(0.0, s["start"] - 0.2)
    length = min(s["end"] - s["start"], MAX_CLIP) + 0.4
    hh, mm = int(s["at"] // 3600), int(s["at"] % 3600 // 60)
    with tempfile.TemporaryDirectory() as tmp:
        still = Path(tmp) / "card.png"
        said = s["text"]
        if s["end"] - s["start"] > MAX_CLIP:   # only the first seconds are heard: about as many of the words
            said = said[:max(8, int(len(said) * MAX_CLIP / (s["end"] - s["start"])))] + "…"
        card(still, label if label.startswith("話者") else f"{label}（話者{voice}）",
             f"{int(day[5:7])}/{int(day[8:10])} {hh}:{mm:02d}", said)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "2", "-i", str(still),
                        "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", s["audio"],
                        "-af", "loudnorm=I=-16:TP=-1.5", "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "96k", "-t", f"{length:.2f}", "-movflags", "+faststart", str(out)],
                       check=True, timeout=120)
    return out


def listing(day: str, limit: int = 5, clips: int = 1, min_seconds: float = 20.0) -> list[dict]:
    """unnamed() with, for each voice, its lines and clips: what the chat shows for 「名前の無い人を出して」."""
    out = []
    for v in unnamed(day, min_seconds)[:limit]:
        chosen = pick(stretches(day, v["voice"]), clips)
        v["lines"] = [{"at": f"{int(s['at'] // 3600)}:{int(s['at'] % 3600 // 60):02d}", "text": s["text"]} for s in chosen]
        v["clips"] = [str(make_clip(day, v["voice"], s, v["label"], i + 1)) for i, s in enumerate(chosen)]
        out.append(v)
    return out
