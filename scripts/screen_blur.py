"""Screen-recording privacy blur: hide specific on-screen text (credentials, account info,
specific input fields) that may move/scroll across frames. The robust approach for screen UIs
(no trackable 'object' like a face) is OCR-per-(sampled)-frame: re-locate the target text every
sample so the blur FOLLOWS scrolling / navigation instead of a static box that leaks.

"What to blur" (per the chosen scope = user-specified + patterns):
  - --targets  comma-separated substrings to hide (case-insensitive), e.g. an account name
  - --patterns built-in classes: email, digits (long digit runs), key (API-key-like)
  - --regex    a custom regex

Pipeline: sample frames at --fps, OCR each, collect boxes whose text matches -> a time-series of
boxes (padded). Then render every output frame, blurring the boxes of the nearest sample. Audio
is preserved by muxing the original track back with ffmpeg.

Usage:
  python scripts/screen_blur.py <in.mp4> <out.mp4> --targets "LINE,301" --fps 4 --pad 0.3
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
DIGITS_RE = re.compile(r"\d[\d\s-]{5,}\d")          # 7+ digits (cards/accounts/phones)
KEY_RE = re.compile(r"\b[A-Za-z0-9_\-]{16,}\b")     # long token = API-key-like


def _matches(text: str, targets: list[str], patterns: set[str], regex: re.Pattern | None) -> bool:
    low = text.lower().strip()
    if not low:
        return False
    if any(t and t.lower() in low for t in targets):
        return True
    if regex and regex.search(text):
        return True
    if "email" in patterns and EMAIL_RE.search(text):
        return True
    if "digits" in patterns and DIGITS_RE.search(text):
        return True
    if "key" in patterns and KEY_RE.search(text):
        return True
    return False


def _box_xywh(poly, w: int, h: int, pad: float) -> tuple[int, int, int, int]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    px = (x1 - x0) * pad
    py = (y1 - y0) * pad
    x0 = max(0, int(x0 - px)); y0 = max(0, int(y0 - py))
    x1 = min(w, int(x1 + px)); y1 = min(h, int(y1 + py))
    return x0, y0, max(1, x1 - x0), max(1, y1 - y0)


def _blur_region(frame, x, y, w, h, style: str):
    roi = frame[y:y + h, x:x + w]
    if roi.size == 0:
        return
    if style == "mosaic":
        small = cv2.resize(roi, (max(2, w // 12), max(2, h // 12)), interpolation=cv2.INTER_NEAREST)
        frame[y:y + h, x:x + w] = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    else:  # gaussian (default) — a soft, content-obscuring blur. Downscale-then-blur fully hides
        # text/faces while staying smooth (a giant kernel alone is slow and can look boxy).
        small = cv2.resize(roi, (max(2, w // 8), max(2, h // 8)), interpolation=cv2.INTER_AREA)
        up = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
        k = min(75, max(7, (min(w, h) // 4) | 1))
        frame[y:y + h, x:x + w] = cv2.GaussianBlur(up, (k, k), 0)


def detect(src: str, targets, patterns, regex, fps: float, pad: float, start: float, end: float):
    """Return {sample_index: [(x,y,w,h), ...]} keyed by sampled-frame time bucket, plus meta."""
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    cap = cv2.VideoCapture(src)
    vfps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    interval = 1.0 / max(0.5, fps)
    boxes_by_t: dict[float, list] = {}
    next_s = start if start > 0 else 0.0
    while True:
        # real frame timestamp (robust to variable frame rate, unlike index/fps)
        t = (cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
        ok, frame = cap.read()
        if not ok:
            break
        if end > 0 and t > end:
            break
        if t + 1e-6 >= next_s and (start <= 0 or t >= start):
            res, _ = ocr(frame)
            hits = []
            for poly, text, _score in (res or []):
                if _matches(text, targets, patterns, regex):
                    hits.append(_box_xywh(poly, w, h, pad))
            boxes_by_t[round(t, 3)] = hits
            next_s = t + interval
    cap.release()
    return boxes_by_t, vfps, w, h, total


def track(src: str, box01: tuple[float, float, float, float], start: float, end: float, fps: float):
    """Follow a user-drawn region across [start,end] with lightweight template matching (base
    OpenCV, no extra deps). box01 = (x,y,w,h) normalized at `start`. Returns boxes_by_t {t:[(x,y,w,h)px]}
    that render() can consume directly. Drift is expected on hard motion — the editor lets the
    human fix keyframes; this is the auto first pass."""
    cap = cv2.VideoCapture(src)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    vfps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    bx = int(box01[0] * W); by = int(box01[1] * H)
    bw = max(8, int(box01[2] * W)); bh = max(8, int(box01[3] * H))
    interval = 1.0 / max(0.5, fps)
    boxes_by_t: dict[float, list] = {}
    template = None
    last = (bx, by, bw, bh)
    next_s = start
    while True:
        t = (cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
        ok, frame = cap.read()
        if not ok:
            break
        if end > 0 and t > end:
            break
        if t + 1e-6 < (start if start > 0 else 0.0) or t + 1e-6 < next_s:
            continue
        x, y, w, h = last
        if template is None:
            template = frame[max(0, y):y + h, max(0, x):x + w].copy()
            boxes_by_t[round(t, 3)] = [(x, y, w, h)]
            next_s = t + interval
            continue
        # search a window around the last position (±h, ±w) for the template
        pad_x, pad_y = w, h
        sx0 = max(0, x - pad_x); sy0 = max(0, y - pad_y)
        sx1 = min(W, x + w + pad_x); sy1 = min(H, y + h + pad_y)
        roi = frame[sy0:sy1, sx0:sx1]
        if roi.shape[0] >= h and roi.shape[1] >= w and template.shape[0] == h and template.shape[1] == w:
            res = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
            _minv, maxv, _minl, maxl = cv2.minMaxLoc(res)
            nx, ny = sx0 + maxl[0], sy0 + maxl[1]
            if maxv > 0.4:  # confident enough -> move; else keep last (occlusion)
                last = (nx, ny, w, h)
                # slowly adapt the template to appearance changes
                template = cv2.addWeighted(template, 0.8,
                                           frame[ny:ny + h, nx:nx + w], 0.2, 0) if frame[ny:ny + h, nx:nx + w].shape == template.shape else template
        boxes_by_t[round(t, 3)] = [last]
        next_s = t + interval
    cap.release()
    return boxes_by_t, vfps


def render(src: str, out: str, boxes_by_t: dict, vfps: float, style: str, ff: str):
    sample_ts = sorted(boxes_by_t.keys())
    cap = cv2.VideoCapture(src)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    tmp = str(Path(out).with_suffix(".noaudio.mp4"))
    vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), vfps, (w, h))
    tol = 0.4  # only blur frames within this many seconds of a sample (avoid smearing far frames)
    while True:
        t = (cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
        ok, frame = cap.read()
        if not ok:
            break
        if sample_ts:
            nearest = min(sample_ts, key=lambda s: abs(s - t))
            if abs(nearest - t) <= tol:
                for (x, y, bw, bh) in boxes_by_t.get(nearest, []):
                    _blur_region(frame, x, y, bw, bh, style)
        vw.write(frame)
    cap.release(); vw.release()
    # mux original audio back
    subprocess.run([ff, "-y", "-i", tmp, "-i", src, "-map", "0:v", "-map", "1:a?",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-shortest", out],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    Path(tmp).unlink(missing_ok=True)


def render_tracks(src: str, out: str, tracks: list[dict], vfps: float, ff: str):
    """Apply MULTIPLE independent blur tracks in one pass. Each track = {boxes_by_t, style}; per
    frame, each track contributes its nearest box (within tol). Used for manual tracked blur."""
    prepared = [(sorted(t["boxes_by_t"].keys()), t["boxes_by_t"], t.get("style", "gaussian")) for t in tracks]
    cap = cv2.VideoCapture(src)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    tmp = str(Path(out).with_suffix(".noaudio.mp4"))
    vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), vfps, (w, h))
    tol = 0.4
    while True:
        t = (cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
        ok, frame = cap.read()
        if not ok:
            break
        for sample_ts, boxes_by_t, style in prepared:
            if not sample_ts:
                continue
            nearest = min(sample_ts, key=lambda s: abs(s - t))
            if abs(nearest - t) <= tol:
                for (x, y, bw, bh) in boxes_by_t.get(nearest, []):
                    _blur_region(frame, x, y, bw, bh, style)
        vw.write(frame)
    cap.release(); vw.release()
    subprocess.run([ff, "-y", "-i", tmp, "-i", src, "-map", "0:v", "-map", "1:a?",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-shortest", out],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    Path(tmp).unlink(missing_ok=True)


def probe(src: str, targets, patterns, regex, n_frames: int = 24):
    """Sample n_frames EVENLY across the whole clip (seek, not sequential) and report which texts
    WOULD be blurred plus a sample of all on-screen text — so the editor can show the user what
    will be hidden before exporting. Bounded time = responsive 'confirm' button."""
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    cap = cv2.VideoCapture(src)
    vfps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    dur = (total / vfps) if (total and vfps) else 0.0
    matched: dict[str, int] = {}
    seen: dict[str, int] = {}
    frames = 0
    n = max(1, n_frames)
    for i in range(n):
        t = (dur * (i + 0.5) / n) if dur > 0 else 0.0
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok:
            continue
        res, _ = ocr(frame)
        frames += 1
        for _poly, text, _score in (res or []):
            tx = (text or "").strip()
            if not tx:
                continue
            seen[tx] = seen.get(tx, 0) + 1
            if _matches(tx, targets, patterns, regex):
                matched[tx] = matched.get(tx, 0) + 1
        if dur <= 0:
            break
    cap.release()
    return {
        "frames": frames,
        "matched": sorted(matched.keys(), key=lambda k: -matched[k]),
        "sample_texts": sorted(seen.keys(), key=lambda k: -seen[k])[:60],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out", nargs="?", default="")
    ap.add_argument("--targets", default="")
    ap.add_argument("--patterns", default="")  # email,digits,key
    ap.add_argument("--regex", default="")
    ap.add_argument("--fps", type=float, default=4.0)
    ap.add_argument("--pad", type=float, default=0.3)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=0.0)
    ap.add_argument("--style", default="gaussian")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--dump", default="")  # optional: write boxes json
    ap.add_argument("--probe", action="store_true")  # detect-only: print matched texts as JSON
    ap.add_argument("--probe-frames", type=int, default=24)
    ap.add_argument("--track-spec", default="")  # json: manual tracked blur(s)
    a = ap.parse_args()
    targets = [t.strip() for t in a.targets.split(",") if t.strip()]
    patterns = {p.strip() for p in a.patterns.split(",") if p.strip()}
    regex = re.compile(a.regex) if a.regex else None
    if a.track_spec:
        # Manual tracked blur: each spec track = a user-drawn box (normalized) + time range; follow
        # it on this (final) video and gaussian-blur the moving region.
        spec = json.loads(Path(a.track_spec).read_text(encoding="utf-8"))
        fps = float(spec.get("fps") or 8)
        tracks = []
        vfps = 30.0
        for tr in spec.get("tracks") or []:
            box01 = (float(tr["x"]), float(tr["y"]), float(tr["w"]), float(tr["h"]))
            boxes_by_t, vfps = track(a.src, box01, float(tr.get("start") or 0), float(tr.get("end") or 0), fps)
            tracks.append({"boxes_by_t": boxes_by_t, "style": str(tr.get("style") or "gaussian")})
        if tracks:
            render_tracks(a.src, a.out, tracks, vfps, a.ffmpeg)
        print("tracked-rendered:", a.out)
        return 0
    if a.probe:
        # ensure_ascii so Japanese text can't crash print() on a cp932 (Windows) stdout; the
        # caller json.loads() decodes the \uXXXX escapes back to proper characters.
        print(json.dumps(probe(a.src, targets, patterns, regex, a.probe_frames), ensure_ascii=True))
        return 0
    boxes_by_t, vfps, w, h, total = detect(a.src, targets, patterns, regex, a.fps, a.pad, a.start, a.end)
    nhits = sum(len(v) for v in boxes_by_t.values())
    print(f"sampled {len(boxes_by_t)} frames, {nhits} blur boxes total")
    if a.dump:
        Path(a.dump).write_text(json.dumps({str(k): v for k, v in boxes_by_t.items()}), encoding="utf-8")
    render(a.src, a.out, boxes_by_t, vfps, a.style, a.ffmpeg)
    print("rendered:", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
