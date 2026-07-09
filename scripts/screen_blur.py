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
    # Clamp to the frame so a box running past the edge doesn't desync roi vs the resized blur
    # (shape-broadcast error). All downscale/upscale below uses the CLAMPED w/h.
    fh, fw = frame.shape[:2]
    x = max(0, min(int(x), fw - 1)); y = max(0, min(int(y), fh - 1))
    w = max(1, min(int(w), fw - x)); h = max(1, min(int(h), fh - y))
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


# (the old template-matching box tracker lived here; object tracking is SAM 3 now —
#  scripts/blur_mask_bake.py — and no server path called --track-spec/--track-probe anymore)


def _rect_overlap(a, b) -> float:
    """Intersection area of two (x,y,w,h) rects in pixels."""
    ax0, ay0, ax1, ay1 = a[0], a[1], a[0] + a[2], a[1] + a[3]
    bx0, by0, bx1, by1 = b[0], b[1], b[0] + b[2], b[1] + b[3]
    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    return ix * iy


def ocr_track(src: str, box01, anchor: float, scan_start: float, scan_end: float, fps: float,
              out_w: int = 0, out_h: int = 0, clip_rect=(0.0, 0.0, 1.0, 1.0), t_offset: float = 0.0,
              ff: str = "ffmpeg"):
    """Follow a TEXT region the user drew, ACROSS the composition. The box is in OUTPUT-normalized
    coords (what the user sees); `anchor`/`scan_*` are SOURCE-video times (the active clip's). The
    cover-fit mapping (clip_rect = the clip's output rect; out_w/h = output size) converts
    output<->source coords so we OCR the right region of the right asset even when it's cropped to
    a different aspect. Returns boxes in OUTPUT-normalized coords keyed by TIMELINE time (src+offset).
    Frames are extracted with FFMPEG (accurate seek): OpenCV's POS_MSEC/POS_FRAMES seeking is
    unreliable on the variable-frame-rate proxies typical of screen recordings (landed at the wrong
    timestamp and silently returned no frames)."""
    from rapidocr_onnxruntime import RapidOCR
    import shutil
    import tempfile
    ocr = RapidOCR()
    tmpd = Path(tempfile.mkdtemp(prefix="ocrtrack_"))
    try:
        # anchor frame (accurate input-seek)
        anchor_jpg = tmpd / "anchor.jpg"
        subprocess.run([ff, "-y", "-ss", f"{max(0.0, anchor):.3f}", "-i", src, "-frames:v", "1", "-q:v", "2", str(anchor_jpg)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        aframe = cv2.imread(str(anchor_jpg)) if anchor_jpg.exists() else None
        if aframe is None:
            return {"found": False, "text": "", "boxes": {}, "t_start": None, "t_end": None, "w": 0, "h": 0, "sample_texts": []}
        H, W = aframe.shape[:2]
        # cover-fit between the source (W,H) and the clip's output rect within the output frame.
        if out_w > 0 and out_h > 0:
            rx, ry, rw, rh = clip_rect[0] * out_w, clip_rect[1] * out_h, clip_rect[2] * out_w, clip_rect[3] * out_h
            cover = max(rw / W, rh / H) or 1.0
            off_x = rx + (rw - W * cover) / 2.0
            off_y = ry + (rh - H * cover) / 2.0

            def out_to_src(ox_n, oy_n):
                return ((ox_n * out_w - off_x) / cover, (oy_n * out_h - off_y) / cover)

            def src_to_out(sx, sy):
                return ((sx * cover + off_x) / out_w, (sy * cover + off_y) / out_h)
        else:
            def out_to_src(ox_n, oy_n):
                return (ox_n * W, oy_n * H)

            def src_to_out(sx, sy):
                return (sx / W, sy / H)

        sx0, sy0 = out_to_src(box01[0], box01[1])
        sx1, sy1 = out_to_src(box01[0] + box01[2], box01[1] + box01[3])
        bx, by = min(sx0, sx1), min(sy0, sy1)
        bw, bh = max(8.0, abs(sx1 - sx0)), max(8.0, abs(sy1 - sy0))
        drawn = (bx, by, bw, bh)
        sample_texts: list[str] = []
        # 1) target text = OCR token most overlapping the drawn box at the anchor frame
        res, _ = ocr(aframe)
        target = ""
        best_ov = 0.0
        for poly, text, _score in (res or []):
            sample_texts.append(str(text).strip())
            ov = _rect_overlap(drawn, _box_xywh(poly, W, H, 0.0))
            if ov > best_ov:
                best_ov, target = ov, str(text).strip()
        # Fallback: nearest token within ~1.5x the box size (a hand-drawn box can miss a tight token).
        if not target and res:
            bcx, bcy = bx + bw / 2, by + bh / 2
            reach = 1.5 * max(bw, bh)
            best_d = reach * reach
            for poly, text, _score in res:
                x0, y0, w0, h0 = _box_xywh(poly, W, H, 0.0)
                d = (x0 + w0 / 2 - bcx) ** 2 + (y0 + h0 / 2 - bcy) ** 2
                if d < best_d:
                    best_d, target = d, str(text).strip()
        if not target:
            return {"found": False, "text": "", "boxes": {}, "t_start": None, "t_end": None,
                    "w": W, "h": H, "sample_texts": sample_texts[:40]}
        tgt = target.lower()
        # 2) extract the scan window at `fps` (constant-rate, accurate) and OCR each frame in order.
        dur = max(0.1, scan_end - scan_start) if scan_end > 0 else 0.0
        ff_args = [ff, "-y", "-ss", f"{max(0.0, scan_start):.3f}", "-i", src]
        if dur > 0:
            ff_args += ["-t", f"{dur:.3f}"]
        ff_args += ["-vf", f"fps={fps}", "-q:v", "2", str(tmpd / "s_%05d.jpg")]
        subprocess.run(ff_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        files = sorted(tmpd.glob("s_*.jpg"))
        boxes: dict[str, list] = {}
        last_c = (bx + bw / 2, by + bh / 2)
        # Search only a GENEROUS region around the last position (text moves little between samples).
        # OCR-ing a small crop instead of the whole frame is ~10x faster — the full-frame scan timed
        # out (300s) on long clips. Margin = the box plus ~1.5x slack so slow drift stays in view.
        mx = max(bw * 1.5, 90.0)
        my = max(bh * 1.5, 70.0)
        for i, fpath in enumerate(files):
            frame = cv2.imread(str(fpath))
            if frame is None:
                continue
            t = scan_start + i / fps  # source time of this sample
            cx0 = int(max(0, last_c[0] - mx)); cy0 = int(max(0, last_c[1] - my))
            cx1 = int(min(W, last_c[0] + mx)); cy1 = int(min(H, last_c[1] + my))
            crop = frame[cy0:cy1, cx0:cx1]
            if crop.size == 0:
                continue
            res, _ = ocr(crop)
            cands = []
            for poly, text, _score in (res or []):
                tl = str(text).lower().strip()
                if not tl:
                    continue
                if tgt in tl or tl in tgt:  # exact / substring either direction
                    x0, y0, w0, h0 = _box_xywh(poly, crop.shape[1], crop.shape[0], 0.0)
                    cands.append((cx0 + x0 + w0 / 2, cy0 + y0 + h0 / 2))  # crop -> full-frame coords
            if cands:
                cx, cy = min(cands, key=lambda c: (c[0] - last_c[0]) ** 2 + (c[1] - last_c[1]) ** 2)
                last_c = (cx, cy)
                sx, sy = cx - bw / 2, cy - bh / 2
                ox0, oy0 = src_to_out(sx, sy)
                ox1, oy1 = src_to_out(sx + bw, sy + bh)
                ox, oy = min(ox0, ox1), min(oy0, oy1)
                ow, oh = abs(ox1 - ox0), abs(oy1 - oy0)
                tl_t = t + t_offset  # source time -> timeline time
                boxes[f"{tl_t:.3f}"] = [round(max(0.0, ox), 5), round(max(0.0, oy), 5), round(ow, 5), round(oh, 5)]
        ts = sorted(float(k) for k in boxes)
        return {"found": len(boxes) > 0, "text": target, "boxes": boxes,
                "t_start": ts[0] if ts else None, "t_end": ts[-1] if ts else None,
                "w": W, "h": H, "sample_texts": sample_texts[:40]}
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


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
    ap.add_argument("--ocr-track", action="store_true")  # follow the TEXT in a box (OCR); print path + time range
    ap.add_argument("--render-spec", default="")  # json {tracks:[{boxes:{t:[x,y,w,h] norm}, style}]} -> bake blur
    ap.add_argument("--box", default="")  # x,y,w,h normalized (for --track-probe / --ocr-track)
    ap.add_argument("--anchor", type=float, default=0.0)  # SOURCE time (s) for the anchor frame (--ocr-track)
    ap.add_argument("--out-w", type=int, default=0)       # output frame size (composition mapping)
    ap.add_argument("--out-h", type=int, default=0)
    ap.add_argument("--clip-rect", default="0,0,1,1")     # the clip's output rect (normalized): rx,ry,rw,rh
    ap.add_argument("--t-offset", type=float, default=0.0)  # timeline_start - source_start (src time -> timeline time)
    a = ap.parse_args()
    targets = [t.strip() for t in a.targets.split(",") if t.strip()]
    patterns = {p.strip() for p in a.patterns.split(",") if p.strip()}
    regex = re.compile(a.regex) if a.regex else None
    if a.render_spec:
        # Bake blur along PRE-COMPUTED normalized paths (from OCR tracking) — no re-tracking. The
        # nearest-sample gating in render_tracks (±0.4s) naturally limits blur to the tracked range.
        spec = json.loads(Path(a.render_spec).read_text(encoding="utf-8"))
        cap = cv2.VideoCapture(a.src)
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1
        vfps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        cap.release()
        tracks = []
        for tr in spec.get("tracks") or []:
            bb = {}
            for t, box in (tr.get("boxes") or {}).items():
                if not box or len(box) < 4:
                    continue
                bb[round(float(t), 3)] = [(int(box[0] * W), int(box[1] * H), max(2, int(box[2] * W)), max(2, int(box[3] * H)))]
            if bb:
                tracks.append({"boxes_by_t": bb, "style": str(tr.get("style") or "gaussian")})
        if tracks:
            render_tracks(a.src, a.out, tracks, vfps, a.ffmpeg)
        print("render-spec-done:", a.out)
        return 0
    if a.ocr_track:
        bx = [float(v) for v in a.box.split(",") if v.strip() != ""]
        if len(bx) < 4:
            print(json.dumps({"found": False, "boxes": {}, "error": "bad box"}))
            return 0
        cr = [float(v) for v in a.clip_rect.split(",")] if a.clip_rect else [0, 0, 1, 1]
        if len(cr) < 4:
            cr = [0, 0, 1, 1]
        out = ocr_track(a.src, (bx[0], bx[1], bx[2], bx[3]), a.anchor, a.start, a.end,
                        a.fps if a.fps > 0 else 4.0, out_w=a.out_w, out_h=a.out_h,
                        clip_rect=(cr[0], cr[1], cr[2], cr[3]), t_offset=a.t_offset, ff=a.ffmpeg)
        print(json.dumps(out, ensure_ascii=True))
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
