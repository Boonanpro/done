"""Generate the "pop-out" overlay layer for one wipe/overlay clip: the matted person breaking
ABOVE the wipe box, composited over a rounded card with rim/drop/contact shadows.

v4 (2026-07): output is a SINGLE .pv.mp4 with TWO H.264 video tracks —
  track v:0 = color (yuv420p, straight-alpha colors, transparent area = black)
  track v:1 = alpha (matte in luma, yuv420p)
Both tracks are HW-decodable (d3d11) so the native GES engine composites this like a normal
clip (the old ProRes 4444 .mov was 200+ Mbps CPU-decode-only and made the whole timeline
heavy). The browser .webm and the export both derive from this same file (alphamerge).

Compositing runs on torch (CUDA when available) — the old per-frame numpy full-canvas pipeline
was the bake-time bottleneck, not the RVM matting itself. The visual math is a 1:1 port.

Geometry (all in OUTPUT pixels):
  box = (px, py, ow, oh)  -> the wipe rectangle in the composition (the "card").
  The person is scaled LARGER than the box so the box top cuts across chest/forehead
  (by intensity) and the head/shoulders extend above py over whatever is behind.

The bake canvas AUTO-EXTENDS beyond the WxH frame with margins so a card that sits
partly off-screen (or its head/shadow) is fully rendered, not cut at the frame edge —
the editor compensates the clip's display position by the margins (see --meta-file,
which records them normalized to the base frame). The alpha track is FULL-RANGE:
limited-range (16..235) can never express "fully transparent"/"fully opaque" and showed
up as a faint dark frame + a see-through person.

Used by app/api/production_asset_routes.py for clips with effects [{type:'popout'}].
Standalone test:
  python scripts/popout_overlay.py IN.mp4 --out ov.pv.mp4 --W 720 --H 1280 \
      --box 120,900,480,190 --start 130 --duration 12 --intensity mid --progress-file p.json
"""
import argparse, json, math, os, shutil, subprocess, tempfile, time
import numpy as np
import cv2
import torch

def _ffmpeg():
    c = os.path.expanduser("~/ffmpeg/bin/ffmpeg.exe")
    if os.path.exists(c): return c
    return shutil.which("ffmpeg") or __import__("imageio_ffmpeg").get_ffmpeg_exe()
FFMPEG = _ffmpeg()

# how much of the person's height sits BELOW the box top (= inside the card). smaller =>
# more of the body pops above the box. tuned to match popout_render presets.
INTENSITY_BELOW = {"subtle": 0.78, "mid": 0.62, "dramatic": 0.46}

def rounded_alpha(w, h, r):
    m = np.zeros((h, w), np.uint8)
    r = max(0, min(r, min(w, h) // 2))
    cv2.rectangle(m, (r, 0), (w - r, h), 255, -1)
    cv2.rectangle(m, (0, r), (w, h - r), 255, -1)
    for cx, cy in [(r, r), (w - r, r), (r, h - r), (w - r, h - r)]:
        cv2.circle(m, (cx, cy), r, 255, -1)
    return m

def gauss_blur(t: torch.Tensor, sigma: float) -> torch.Tensor:
    """Separable gaussian blur of a (H,W) tensor on its own device (matches cv2.GaussianBlur
    with ksize=0, i.e. kernel radius derived from sigma)."""
    # cv2 auto ksize for ksize=0: round(sigma*3)*2+1 (8-bit uses *3; float images use *4 —
    # our old pipeline blurred float32 arrays, so use *4 to keep the template look identical)
    radius = max(1, int(round(sigma * 4)))
    x = torch.arange(-radius, radius + 1, dtype=t.dtype, device=t.device)
    k = torch.exp(-(x ** 2) / (2 * sigma * sigma))
    k = (k / k.sum()).view(1, 1, -1)
    v = t.view(1, 1, *t.shape)
    v = torch.nn.functional.conv2d(v, k.view(1, 1, 1, -1), padding=(0, radius))
    v = torch.nn.functional.conv2d(v, k.view(1, 1, -1, 1), padding=(radius, 0))
    return v.view(*t.shape)

def write_progress(path, done, total, error=None):
    if not path: return
    try:
        payload = {"done": int(done), "total": int(total),
                   "pct": (100 if total <= 0 else min(100, round(done * 100 / total))),
                   "ts": time.time()}
        if error: payload["error"] = str(error)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, path)
    except OSError:
        pass

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input"); ap.add_argument("--out", required=True)
    ap.add_argument("--W", type=int, required=True); ap.add_argument("--H", type=int, required=True)
    ap.add_argument("--box", required=True, help="px,py,ow,oh in output pixels")
    ap.add_argument("--start", type=float, default=None); ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--intensity", default="mid"); ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--no-shadow", action="store_true"); ap.add_argument("--radius", type=int, default=None)
    ap.add_argument("--progress-file", default=None)
    ap.add_argument("--meta-file", default=None, help="write bake metadata (canvas margins) here")
    ap.add_argument("--matte-out", default=None,
                    help="also write a matte-only mp4 (v0=person alpha, v1=contact-shadow base) "
                         "for the native live compositor (color comes from the ORIGINAL at runtime)")
    a = ap.parse_args()
    px, py, ow, oh = (int(v) for v in a.box.split(","))
    W, H = a.W, a.H
    radius = a.radius if a.radius is not None else max(8, int(min(ow, oh) * 0.08))
    below = INTENSITY_BELOW.get(a.intensity, 0.62)

    work = tempfile.mkdtemp(prefix="povl_")
    proc = None
    try:
        # 1. extract source segment scaled so the PERSON is larger than the box: source height
        #    maps to oh/below (so only `below` fraction of person is inside the card).
        person_h = int(round(oh / below)); person_h -= person_h % 2  # even (yuv420p)
        # ACCURATE seek: coarse input-seek 2s early (fast), exact output-side trim after.
        # A single input-seek lands on the source frame grid, which baked a constant
        # lipsync offset (tens of ms) into every overlay.
        pre = max(0.0, (a.start or 0.0) - 2.0)
        ss = ["-ss", f"{pre:.6f}"] if a.start is not None else []
        fine = ["-ss", f"{(a.start or 0.0) - pre:.6f}"] if a.start is not None else []
        t = ["-t", str(a.duration)] if a.duration is not None else []
        seg = os.path.join(work, "seg.mp4")
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", *ss, "-i", a.input, *fine, *t,
                        "-vf", f"scale=-2:{person_h}", "-r", str(a.fps), "-an",
                        "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", seg, "-y"], check=True)

        dev = "cuda" if torch.cuda.is_available() else "cpu"
        model = torch.hub.load("PeterL1n/RobustVideoMatting", "mobilenetv3", trust_repo=True).eval().to(dev)
        if dev == "cuda": model = model.half()

        cap = cv2.VideoCapture(seg)
        sw = int(cap.get(3)); sh = int(cap.get(4)); fps = cap.get(5) or a.fps
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total <= 0 and a.duration: total = int(a.duration * a.fps)
        write_progress(a.progress_file, 0, total)
        # horizontal placement: center the scaled source on the box center
        src_x = px + ow // 2 - sw // 2          # left of source in canvas coords
        # vertical: bottom of person ~ box bottom; box top (py) sits at `below` up from bottom
        src_y = (py + oh) - person_h            # top of source in canvas coords

        # --- auto-extend the canvas so nothing is cut at the frame edge: a card placed partly
        # off-screen, the popped head near the top, and the drop shadow all get real pixels in
        # the margins. The editor shifts the clip's display position by these margins so the
        # default look is IDENTICAL; scaling the clip down then reveals the preserved content
        # instead of a hard cut. Margins are 0 for a fully on-screen card (canvas unchanged).
        SHADOW_PAD = 120  # drop shadow reach below/right of the card (sigma 26 blur + 16 roll)
        SIDE_PAD = 32     # rim + shadow bleed sideways
        even = lambda v: int(math.ceil(max(0.0, v) / 2.0) * 2)
        BW, BH = W, H
        L = even(-min(px - SIDE_PAD, src_x))
        T = even(-min(py - 8, src_y))
        R = even(max(px + ow + SIDE_PAD, src_x + sw) - BW)
        B = even(py + oh + SHADOW_PAD - BH)
        W, H = BW + L + R, BH + T + B
        px += L; py += T; src_x += L; src_y += T
        card = rounded_alpha(ow, oh, radius)     # card mask (box-local)

        # source → canvas paste window, clipped to the canvas (static — offsets never change)
        dx0, dy0 = max(0, src_x), max(0, src_y)
        dx1, dy1 = min(W, src_x + sw), min(H, src_y + sh)
        sx0, sy0 = dx0 - src_x, dy0 - src_y
        sx1, sy1 = dx1 - src_x, dy1 - src_y
        pastable = dx1 > dx0 and dy1 > dy0

        # --- static polish masks (card geometry only; don't change per frame) ---
        f32 = torch.float32
        cardmask_full = np.zeros((H, W), np.float32)
        cy0, cx0 = max(0, py), max(0, px)
        cy1, cx1 = min(H, py + oh), min(W, px + ow)
        if cy1 > cy0 and cx1 > cx0:
            cardmask_full[cy0:cy1, cx0:cx1] = (card.astype(np.float32) / 255)[cy0 - py:cy1 - py, cx0 - px:cx1 - px]
        ca = torch.from_numpy(cardmask_full).to(dev, f32)
        # person shows inside the card OR above the box top (feathered)
        allow = ca.clone(); allow[:max(0, py), :] = 1.0
        allow = gauss_blur(allow, 1.5)
        # thin light rim on the card edge (like popout_render.py)
        _k = np.ones((3, 3), np.uint8); _cmu = (cardmask_full * 255).astype(np.uint8)
        border_np = (cv2.dilate(_cmu, _k) - cv2.erode(_cmu, _k)).astype(np.float32) / 255
        border_f = gauss_blur(torch.from_numpy(border_np).to(dev, f32), 1.2)
        border_col = torch.tensor([200.0, 195.0, 210.0], device=dev).view(3, 1, 1)  # BGR, soft light
        # card drop shadow: soft dark halo OUTSIDE the card so it looks like it floats
        drop = gauss_blur(ca, 26)
        drop = torch.roll(torch.roll(drop, 16, dims=0), 6, dims=1)
        drop = torch.clamp(drop - ca, 0, 1)
        base_a = drop * 0.45   # composite step 1: card drop shadow

        # 2-track H.264 writer: one rawvideo BGRA pipe in, color+alpha tracks out. Fixed GOP /
        # no scene-cut so both tracks share keyframe positions (clean seeks in qtdemux).
        # The ALPHA track must be FULL RANGE (in_range/out_range=full + color_range pc): the
        # default limited range clamps to 16..235, i.e. "transparent" leaks 6% black (faint dark
        # frame) and "opaque" is 92% (person see-through). Verified 0..255 via signalstats.
        # short GOP (8 frames = 0.27s): the native engine re-enters this file on every clip
        # boundary / edit commit and must decode from the previous keyframe — 30-frame GOPs made
        # that up to ~250ms per activation (audio ran ahead while the video spun up)
        enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
               "-g", "8", "-x264-params", "scenecut=0"]
        proc = subprocess.Popen(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra",
             "-s", f"{W}x{H}", "-r", str(int(fps)), "-i", "-",
             "-filter_complex",
             "[0:v]split=2[c][a];[c]format=yuv420p[cv];"
             "[a]alphaextract,scale=in_range=full:out_range=full,format=yuv420p,setparams=range=pc[av]",
             "-map", "[cv]", "-map", "[av]", *enc, "-color_range:v:1", "pc",
             "-movflags", "+faststart", a.out, "-y"], stdin=subprocess.PIPE)
        mproc = None
        if a.matte_out:
            mproc = subprocess.Popen(
                [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "gray",
                 "-s", f"{W}x{H*2}", "-r", str(int(fps)), "-i", "-",
                 "-filter_complex",
                 f"[0:v]split=2[t0][t1];[t0]crop={W}:{H}:0:0,format=yuv420p,setparams=range=pc[m0];"
                 f"[t1]crop={W}:{H}:0:{H},format=yuv420p,setparams=range=pc[m1]",
                 "-map", "[m0]", "-map", "[m1]", "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "18", "-g", "8", "-x264-params", "scenecut=0",
                 "-color_range", "pc", "-movflags", "+faststart",
                 a.matte_out, "-y"], stdin=subprocess.PIPE)
        rec = [None] * 4; n = 0
        eps = 1e-6
        with torch.no_grad():
            while True:
                ok, frame = cap.read()
                if not ok: break
                bgr_np = frame  # HxWx3 uint8 BGR
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
                tt = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).to(dev)
                if dev == "cuda": tt = tt.half()
                _, pha, *rec = model(tt, *rec, downsample_ratio=0.25)
                alpha_small = pha[0, 0].to(f32)  # sh×sw on dev

                bgr = torch.from_numpy(bgr_np).to(dev).permute(2, 0, 1).to(f32)  # 3×sh×sw, 0..255
                # paste the source frame + its matte into full-canvas layers (static window)
                card_rgb = torch.zeros((3, H, W), dtype=f32, device=dev)
                person_a = torch.zeros((H, W), dtype=f32, device=dev)
                if pastable:
                    card_rgb[:, dy0:dy1, dx0:dx1] = bgr[:, sy0:sy1, sx0:sx1]
                    person_a[dy0:dy1, dx0:dx1] = alpha_small[sy0:sy1, sx0:sx1]
                person_a = person_a * allow
                person_rgb = card_rgb  # same paste; masks differ

                # 1. card drop shadow (soft dark) around the card = floating look
                out_a = base_a.clone()
                # 2. card content over the shadow (straight-alpha "over")
                na = ca + out_a * (1 - ca)
                out_rgb = (card_rgb * ca) / torch.clamp(na, min=eps)  # shadow rgb is 0
                out_a = na
                # 3. thin light rim on the card edge (never over the person)
                be = border_f * (1 - person_a) * 0.6
                out_rgb = out_rgb * (1 - be) + border_col * be
                out_a = torch.clamp(out_a + be, 0, 1)
                # 4. contact shadow cast by the popped head onto the card
                if not a.no_shadow:
                    sh_m = torch.roll(gauss_blur(person_a, 16), 22, dims=0)
                    sh_m = sh_m * ca * (1 - person_a) * 0.5
                    out_rgb = out_rgb * (1 - sh_m)
                # 5. person on top
                new_a = out_a + person_a * (1 - out_a)
                out_rgb = (out_rgb * out_a * (1 - person_a) + person_rgb * person_a) / torch.clamp(new_a, min=eps)
                out_a = new_a

                bgra = torch.cat([torch.clamp(out_rgb, 0, 255), (out_a * 255).unsqueeze(0)], dim=0)
                frame_out = bgra.permute(1, 2, 0).to(torch.uint8).cpu().numpy()
                proc.stdin.write(np.ascontiguousarray(frame_out).tobytes())
                if mproc is not None:
                    sh_base = torch.roll(gauss_blur(person_a, 16), 22, dims=0)
                    stacked = torch.cat([person_a, sh_base], dim=0)
                    mframe = (torch.clamp(stacked, 0, 1) * 255).to(torch.uint8).cpu().numpy()
                    mproc.stdin.write(np.ascontiguousarray(mframe).tobytes())
                n += 1
                if n % 10 == 0: write_progress(a.progress_file, n, total)
        proc.stdin.close(); rc = proc.wait(); cap.release()
        if mproc is not None:
            mproc.stdin.close()
            if mproc.wait() != 0:
                raise RuntimeError("matte encoder failed")
        if rc != 0:
            raise RuntimeError(f"ffmpeg encoder exited {rc}")
        if a.meta_file:
            meta = {"margins": {"l": L / BW, "t": T / BH, "r": R / BW, "b": B / BH},
                    "base": [BW, BH], "canvas": [W, H], "fps": int(fps),
                    "src_x": src_x, "src_y": src_y, "sw": sw, "sh": sh,
                    "box": [px, py, ow, oh], "radius": radius, "v": 7}
            tmp = a.meta_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(meta, f)
            os.replace(tmp, a.meta_file)
        write_progress(a.progress_file, max(n, total), max(n, total))
        print(f"OK wrote {a.out} ({n} frames, {W}x{H} canvas (base {BW}x{BH} +{L},{T},{R},{B}), box={a.box}, intensity={a.intensity}, dev={dev})")
    except Exception as exc:
        write_progress(a.progress_file, 0, 1, error=exc)
        raise
    finally:
        if proc is not None and proc.poll() is None:
            try: proc.stdin.close()
            except OSError: pass
            proc.kill()
        shutil.rmtree(work, ignore_errors=True)

if __name__ == "__main__":
    main()
