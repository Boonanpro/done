"""Dan's "ears": precise speech analysis for video editing.

Transcribes a video/audio clip with word-level timestamps (Whisper large-v3 on
GPU) and reports:
  - segments / words with frame-accurate timestamps (for exact cut points)
  - dead_air: silence gaps between speech longer than a threshold (to trim)
  - restatements: adjacent near-duplicate phrases (the redundant "言い直し" take)

Dan uses this two ways:
  1) Planning: run on a source clip to find exact cut boundaries, dead air, and
     which take is the keeper.
  2) Self-verify: run on the FINAL render to catch leftover dead air or
     duplicate phrases, then re-cut and re-render until clean.

Standalone (no app imports) so it runs from any cwd.

Usage:
  python dan_audio_check.py <media> [--model large-v3] [--silence-gap 0.7]
                            [--max-seconds 0] [--words] [--json-only]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from difflib import SequenceMatcher
from pathlib import Path


def _ffmpeg() -> str:
    for cand in ("ffmpeg", "ffmpeg.exe"):
        found = shutil.which(cand)
        if found:
            return found
    fallback = r"C:/Users/Owner/ffmpeg/bin/ffmpeg.exe"
    if Path(fallback).exists():
        return fallback
    raise RuntimeError("ffmpeg not found on PATH or at the known fallback location")


def _ffprobe() -> str:
    p = Path(_ffmpeg())
    cand = p.with_name(p.name.replace("ffmpeg", "ffprobe"))
    if cand.exists():
        return str(cand)
    return shutil.which("ffprobe") or shutil.which("ffprobe.exe") or str(cand)


def _ffprobe_duration(path: str) -> float:
    exe = _ffprobe()
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=30, check=False,
        )
        return float((out.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def _extract_audio(media: str, max_seconds: float) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    cmd = [_ffmpeg(), "-y"]
    if max_seconds and max_seconds > 0:
        cmd += ["-t", f"{max_seconds:.3f}"]
    cmd += ["-i", media, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", tmp.name]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return tmp.name


def _norm(text: str) -> str:
    return re.sub(r"[\s?？!！。、,.…ー〜~・「」『』（）()]+", "", text or "")


def _transcribe(audio_path: str, model_name: str) -> list[dict]:
    import whisper  # type: ignore
    try:
        import torch  # type: ignore
        use_fp16 = bool(torch.cuda.is_available())
    except Exception:
        use_fp16 = False

    ffmpeg_dir = str(Path(_ffmpeg()).parent)
    os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    model = whisper.load_model(model_name)
    result = model.transcribe(
        audio_path, language="ja", fp16=use_fp16, verbose=False, word_timestamps=True,
    )
    segments: list[dict] = []
    for seg in result.get("segments") or []:
        text = str(seg.get("text") or "").strip()
        if not text or len(_norm(text)) < 1:
            continue
        words = [
            {"word": str(w.get("word") or "").strip(),
             "start": round(float(w.get("start") or 0), 3),
             "end": round(float(w.get("end") or 0), 3)}
            for w in (seg.get("words") or [])
            if str(w.get("word") or "").strip()
        ]
        segments.append({
            "start": round(float(seg.get("start") or 0), 3),
            "end": round(float(seg.get("end") or 0), 3),
            "text": text,
            "words": words,
        })
    return segments


def _find_dead_air(segments: list[dict], duration: float, gap: float) -> list[dict]:
    spans: list[dict] = []
    if segments:
        lead = segments[0]["start"]
        if lead >= gap:
            spans.append({"start": 0.0, "end": round(segments[0]["start"], 3), "dur": round(lead, 3), "where": "leading"})
        for a, b in zip(segments, segments[1:]):
            g = b["start"] - a["end"]
            if g >= gap:
                spans.append({"start": round(a["end"], 3), "end": round(b["start"], 3), "dur": round(g, 3), "where": "between"})
        if duration > 0:
            trail = duration - segments[-1]["end"]
            if trail >= gap:
                spans.append({"start": round(segments[-1]["end"], 3), "end": round(duration, 3), "dur": round(trail, 3), "where": "trailing"})
    return spans


def _find_restatements(segments: list[dict], ratio_threshold: float = 0.62) -> list[dict]:
    hits: list[dict] = []
    for i in range(len(segments)):
        a = segments[i]
        na = _norm(a["text"])
        if len(na) < 4:
            continue
        # compare against the next up-to-2 segments (a restart often follows immediately)
        for j in range(i + 1, min(i + 3, len(segments))):
            b = segments[j]
            nb = _norm(b["text"])
            if len(nb) < 4:
                continue
            ratio = SequenceMatcher(None, na, nb).ratio()
            contained = na in nb or nb in na
            if ratio >= ratio_threshold or contained:
                hits.append({
                    "first": {"start": a["start"], "end": a["end"], "text": a["text"]},
                    "second": {"start": b["start"], "end": b["end"], "text": b["text"]},
                    "ratio": round(ratio, 2),
                    "hint": "first is likely the discarded take; keep the later one",
                })
                break
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("media")
    ap.add_argument("--model", default=os.environ.get("DAN_WHISPER_MODEL", "large-v3"))
    ap.add_argument("--silence-gap", type=float, default=0.7)
    ap.add_argument("--max-seconds", type=float, default=0.0)
    ap.add_argument("--words", action="store_true", help="include word list in JSON")
    ap.add_argument("--json-only", action="store_true", help="suppress human summary")
    args = ap.parse_args()

    media = str(Path(args.media).resolve())
    if not Path(media).exists():
        print(f"ERROR: media not found: {media}", file=sys.stderr)
        return 2

    duration = _ffprobe_duration(media)
    audio = None
    try:
        audio = _extract_audio(media, args.max_seconds)
        segments = _transcribe(audio, args.model)
    except Exception as exc:
        print(f"ERROR: transcription failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if audio and os.path.exists(audio):
            try:
                os.unlink(audio)
            except Exception:
                pass

    dead_air = _find_dead_air(segments, duration, args.silence_gap)
    restatements = _find_restatements(segments)

    out = {
        "media": media,
        "duration": round(duration, 3),
        "model": args.model,
        "silence_gap_threshold": args.silence_gap,
        "segments": [
            {k: v for k, v in s.items() if args.words or k != "words"}
            for s in segments
        ],
        "dead_air": dead_air,
        "restatements": restatements,
        "clean": (not dead_air and not restatements),
    }
    json_path = Path(media).with_name(Path(media).stem + "_audiocheck.json")
    json_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.json_only:
        print(f"# audio check: {Path(media).name}  ({duration:.1f}s, model={args.model})")
        print(f"json: {json_path}")
        print(f"\n## transcript ({len(segments)} segments)")
        for s in segments:
            print(f"  [{s['start']:.2f}-{s['end']:.2f}] {s['text']}")
        print(f"\n## dead_air (gaps >= {args.silence_gap}s): {len(dead_air)}")
        for d in dead_air:
            print(f"  {d['where']}: {d['start']:.2f}-{d['end']:.2f}  ({d['dur']:.2f}s)")
        print(f"\n## restatements (likely 言い直し): {len(restatements)}")
        for r in restatements:
            print(f"  drop [{r['first']['start']:.2f}-{r['first']['end']:.2f}] \"{r['first']['text']}\"")
            print(f"  keep [{r['second']['start']:.2f}-{r['second']['end']:.2f}] \"{r['second']['text']}\"")
        print(f"\nclean: {out['clean']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
