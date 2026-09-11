"""Full-text captions aligned to the spoken audio of a timeline.

Input: the exact script per time range ({t0, t1, text}) — the text the viewer must
read, not what Whisper heard. Whisper only supplies WORD TIMES for the timeline's
speech audio; the script is aligned to those words character by character
(difflib), chunked at 、。 into ≤24-char captions, and placed with two rules that
came out of the kittoku video (2026-09-04):
  * monotonic search — a repeated phrase ("こんなところ") must not snap back to its
    first occurrence;
  * never delay — when a caption would overlap the previous one, the PREVIOUS is cut
    short. Captions that appear late read as "wrong"; captions that vanish a
    little early do not.
Whisper runs in a subprocess (scripts/dan_audio_check.py) — never import
faster-whisper/numpy in the MCP process (DLL init hang, 2026-07-16).
"""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from app.services import timeline_commands as tc

ROOT = Path(__file__).resolve().parents[2]
_NORM_RE = re.compile(r"[\s、。,.!?！？「」・…]")
MAX_CHARS = 24


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _norm(t: str) -> str:
    return _NORM_RE.sub("", t)


def _ffmpeg() -> str:
    for c in (os.environ.get("DAN_FFMPEG"), r"C:\Users\Owner\ffmpeg\bin\ffmpeg.exe", r"C:\ffmpeg\bin\ffmpeg.exe"):
        if c and Path(c).exists():
            return c
    import shutil

    return shutil.which("ffmpeg") or "ffmpeg"


def speech_clips(sequence: dict[str, Any]) -> list[dict[str, Any]]:
    """Audio-lane clips that carry speech (everything except music/sfx roles)."""
    out: list[dict[str, Any]] = []
    for track in sequence.get("tracks") or []:
        if str(track.get("type") or "") != "audio":
            continue
        for c in track.get("clips") or []:
            if not isinstance(c, dict) or not c.get("asset_id"):
                continue
            if str(c.get("role") or "").lower() in {"music", "bgm", "sfx"}:
                continue
            if _f(c.get("volume"), 1.0) <= 0.0:
                continue
            out.append(c)
    return sorted(out, key=lambda c: _f(c.get("timeline_start")))


def render_speech_wav(sequence: dict[str, Any], assets: dict[str, dict[str, Any]], work_dir: Path,
                      t0: float | None = None, t1: float | None = None) -> Path | None:
    """Mix the speech clips into ONE mono 16k wav on the timeline clock (adelay+amix),
    so Whisper's timestamps are timeline seconds directly. Speed is honored."""
    clips = speech_clips(sequence)
    if t0 is not None or t1 is not None:
        lo, hi = (t0 if t0 is not None else -1e9), (t1 if t1 is not None else 1e9)
        clips = [c for c in clips if _f(c.get("timeline_end")) > lo and _f(c.get("timeline_start")) < hi]
    if not clips:
        return None
    work_dir.mkdir(parents=True, exist_ok=True)
    inputs: list[str] = []
    filters: list[str] = []
    n = 0
    end = 0.0
    for c in clips:
        a = assets.get(str(c.get("asset_id"))) or {}
        src = a.get("local_path") or a.get("proxy_path") or ""
        if not src or not Path(src).exists():
            continue
        ts, te = _f(c.get("timeline_start")), _f(c.get("timeline_end"))
        ss = _f(c.get("source_start"))
        spd = _f(c.get("speed"), 1.0) or 1.0
        dur = max(0.05, te - ts)
        inputs += ["-ss", f"{ss:.3f}", "-t", f"{dur * spd:.3f}", "-i", src]
        chain = f"[{n}:a]aresample=16000,aformat=channel_layouts=mono"
        if abs(spd - 1.0) > 1e-3:
            chain += f",atempo={min(2.0, max(0.5, spd)):.4f}"
        chain += f",adelay={int(ts * 1000)}|{int(ts * 1000)},volume={max(0.05, _f(c.get('volume'), 1.0)):.3f}[a{n}]"
        filters.append(chain)
        end = max(end, te)
        n += 1
    if n == 0:
        return None
    mix = "".join(f"[a{i}]" for i in range(n)) + f"amix=inputs={n}:normalize=0:dropout_transition=0[out]"
    out = work_dir / f"speech_{uuid.uuid4().hex[:8]}.wav"
    cmd = [_ffmpeg(), "-nostdin", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filters + [mix]),
           "-map", "[out]", "-t", f"{end + 0.5:.3f}", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=600,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"speech mix failed: {(r.stderr or '')[-400:]}")
    return out


def transcribe_words(wav: Path, model: str | None = None, initial_prompt: str | None = None) -> list[tuple[float, float, str]]:
    """Word timings via cloud API/cache; an explicit local model remains opt-in."""
    if model in (None, 'whisper-1'):
        return transcribe_cloud_words(wav, initial_prompt)
    script = ROOT / "scripts" / "dan_audio_check.py"
    model = model or os.environ.get("DAN_CAPTION_WHISPER_MODEL") or os.environ.get("DAN_WHISPER_MODEL") or "small"
    env = dict(os.environ)
    if initial_prompt:
        env["DAN_WHISPER_INITIAL_PROMPT"] = initial_prompt
    r = subprocess.run([sys.executable, str(script), str(wav), "--words", "--json-only", "--model", model],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL,
                       timeout=1800, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out_json = wav.with_name(wav.stem + "_audiocheck.json")
    if not out_json.exists():
        raise RuntimeError(f"whisper failed rc={r.returncode}: {(r.stderr or '')[-400:]}")
    data = json.loads(out_json.read_text(encoding="utf-8"))
    words: list[tuple[float, float, str]] = []
    for seg in data.get("segments") or []:
        for w in seg.get("words") or []:
            text = str(w.get("word") or w.get("text") or "")
            if text.strip():
                words.append((_f(w.get("start")), max(_f(w.get("end")), _f(w.get("start")) + 0.05), text))
    return words


def transcribe_cloud_words(wav: Path, prompt: str | None = None):
    """Word timings without loading a GPU model; bounded uploads and durable cache."""
    import hashlib, io, wave
    from openai import OpenAI
    from app.config import settings
    digest = hashlib.sha256(wav.read_bytes() + (prompt or '').encode()).hexdigest()
    cache = wav.parent / (digest + '.whisper-1.words.json')
    if cache.exists():
        return [tuple(w) for w in json.loads(cache.read_text(encoding='utf-8'))]
    words = []
    with OpenAI(api_key=settings.OPENAI_API_KEY, timeout=120, max_retries=1) as client, wave.open(str(wav), 'rb') as src:
        rate = src.getframerate()
        offset = 0.0
        while True:
            frames = src.readframes(rate * 300)
            if not frames: break
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as dst:
                dst.setparams(src.getparams()); dst.writeframes(frames)
            result = client.audio.transcriptions.create(model='whisper-1',
                file=('speech.wav', buf.getvalue(), 'audio/wav'), language='ja',
                response_format='verbose_json', timestamp_granularities=['word'],
                **({'prompt': prompt} if prompt else {}))
            words.extend((offset + w.start, offset + w.end, w.word) for w in (result.words or []))
            offset += len(frames) / (rate * src.getnchannels() * src.getsampwidth())
    tmp = cache.with_suffix('.tmp'); tmp.write_text(json.dumps(words, ensure_ascii=False), encoding='utf-8'); tmp.replace(cache)
    return words


def chunk_text(text: str, maxlen: int = MAX_CHARS) -> list[str]:
    parts = [p for p in re.split(r"(?<=[。、])", text) if p.strip()]
    out: list[str] = []
    cur = ""
    for p in parts:
        if cur and len(cur) + len(p) > maxlen:
            out.append(cur)
            cur = p
        else:
            cur += p
    if cur:
        out.append(cur)
    return [c.strip("、。 ") for c in out if c.strip("、。 ")]


def align_segments(words: list[tuple[float, float, str]], segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """segments: [{t0, t1, text}] (timeline seconds, exact script). Returns caption
    specs [{start, end, text}] on the timeline clock."""
    subs: list[dict[str, Any]] = []
    for seg in segments:
        a, b, text = _f(seg.get("t0")), _f(seg.get("t1")), str(seg.get("text") or "").strip()
        if not text or b <= a:
            continue
        ws = [w for w in words if a - 0.15 <= w[0] < b - 0.1]
        if not ws:
            # no speech detected: spread the chunks evenly so the text still shows
            cs = chunk_text(text)
            total = sum(len(c) for c in cs) or 1
            cur = a
            for c in cs:
                d = (b - a) * len(c) / total
                subs.append({"start": round(cur, 2), "end": round(cur + d - 0.03, 2), "text": c})
                cur += d
            continue
        spoken = ""
        times: list[tuple[float, float]] = []
        for st, en, wd in ws:
            wn = _norm(wd)
            for j, ch in enumerate(wn):
                spoken += ch
                times.append((st + (en - st) * j / max(1, len(wn)), en))
        refn = _norm(text)
        sm = difflib.SequenceMatcher(None, refn, spoken, autojunk=False)
        ref2time: dict[int, tuple[float, float]] = {}
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    ref2time[i1 + k] = times[j1 + k]
        pos = 0
        prev_end = ws[0][0]
        spos = 0
        first_in_seg = len(subs)
        for c in chunk_text(text):
            cn = _norm(c)
            n = len(cn)
            j = -1
            for key in (cn[:4], cn[:3], cn[1:5], cn[2:6], cn[1:4]):
                if len(key) >= 3:
                    j = spoken.find(key, spos)
                if j >= 0:
                    break
            if j >= 0:
                st = times[j][0]
                jend = min(len(times) - 1, j + n - 1)
                en = times[jend][1]
                spos = j + max(1, n - 3)
            else:
                idx = [i for i in range(pos, pos + n) if i in ref2time]
                if idx:
                    st, en = ref2time[idx[0]][0], ref2time[idx[-1]][1]
                else:
                    st, en = prev_end, prev_end + 0.4 * n / 8
            pos += n
            st = max(st, ws[0][0])
            en = max(en, st + 0.6)
            if len(subs) > first_in_seg and st < subs[-1]["end"]:
                subs[-1]["end"] = round(max(subs[-1]["start"] + 0.3, st - 0.03), 2)
            subs.append({"start": round(st, 2), "end": round(min(en + 0.15, b - 0.05), 2), "text": c})
            prev_end = en
    for i in range(1, len(subs)):
        if subs[i]["start"] < subs[i - 1]["end"]:
            subs[i - 1]["end"] = round(subs[i]["start"] - 0.03, 2)
    return [s for s in subs if s["end"] - s["start"] >= 0.2]


DEFAULT_STYLE = {"font": "noto-sans", "fontSize": 0.85, "color": "#ffffff", "outlineColor": "#00205b",
                 "outlineWidth": 2, "textAlign": "center", "maxWidth": 0.86, "y": 0.06}


def auto_captions(sequence: dict[str, Any], assets: dict[str, dict[str, Any]], work_dir: Path,
                  segments: list[dict[str, Any]], style: dict[str, Any] | None = None,
                  replace: bool = True, whisper_model: str | None = None) -> dict[str, Any]:
    """Align `segments` to the timeline's speech and write caption clips into `sequence`.
    replace=True removes existing captions inside the covered ranges first."""
    if not segments:
        return {"ok": False, "error": "segments required: [{t0,t1,text}]"}
    lo = min(_f(s.get("t0")) for s in segments)
    hi = max(_f(s.get("t1")) for s in segments)
    wav = render_speech_wav(sequence, assets, work_dir, lo - 1.0, hi + 1.0)
    words = transcribe_words(wav, model=whisper_model) if wav else []
    specs = align_segments(words, segments)
    if replace:
        for track in sequence.get("tracks") or []:
            if str(track.get("type") or "") != "caption":
                continue
            keep = []
            for c in track.get("clips") or []:
                cs, ce = _f(c.get("timeline_start")), _f(c.get("timeline_end"))
                covered = any(_f(s.get("t0")) - 0.2 <= cs and ce <= _f(s.get("t1")) + 0.2 for s in segments)
                if not covered:
                    keep.append(c)
            track["clips"] = keep
    st = dict(DEFAULT_STYLE)
    if isinstance(style, dict):
        st.update(style)
    ids = []
    for sp in specs:
        r = tc.add_caption(sequence, text=sp["text"], timeline_start=sp["start"], timeline_end=sp["end"], style=st)
        if r.get("ok"):
            ids.append(r["clip_id"])
    return {"ok": True, "captions": len(ids), "clip_ids": ids, "words": len(words), "style": st,
            "specs": specs}
