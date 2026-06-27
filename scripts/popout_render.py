"""Pop-out (frame-break) renderer — turn a talking-head clip into a short where the
subject's head/shoulders break out over the top edge of a rounded card.

Mode ① of the "両パターン" effort (see memory project_popout_video_styling): real
footage, local-only, NO API credits. Human matting via Robust Video Matting (RVM,
torch+CUDA). The person cutout is ALWAYS composited on top, clipped to (inside card
OR above the card's top edge), so the card border/seam never crosses the body.

Usage:
  python scripts/popout_render.py IN.mp4 --out OUT.mp4 \
      [--start 138 --duration 6] [--intensity dramatic|mid|subtle] \
      [--card-top Y] [--no-shadow] [--bg none|BG_IMAGE.png] [--aspect 9:16] [--fps 30]

Notes:
- Output is 1080x1920 (9:16) by default. Source is scaled+cropped to fill.
- --bg none  => generated dark gradient studio (default). --bg IMAGE => use that image
  (e.g. a Higgsfield-generated environment) inside the card + blurred outside.
- Requires: torch (cuda recommended), opencv-python, numpy, ffmpeg.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

import cv2
import numpy as np
import torch


# ---- ffmpeg resolution (mirror studio_render_service: ~/ffmpeg/bin, else imageio) ----
def _resolve_ffmpeg() -> str:
    cand = os.path.expanduser("~/ffmpeg/bin/ffmpeg.exe")
    if os.path.exists(cand):
        return cand
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise RuntimeError("ffmpeg not found (~/ffmpeg/bin, PATH, or imageio_ffmpeg)")


FFMPEG = _resolve_ffmpeg()

# intensity presets: card geometry for a 1080x1920 canvas. y0 = card top edge;
# lower y0 (larger value) => more of the body pops out over the top.
PRESETS = {
    "subtle":   dict(x0=110, y0=560, x1=970, y1=1480, r=64),
    "mid":      dict(x0=130, y0=740, x1=950, y1=1520, r=62),
    "dramatic": dict(x0=150, y0=900, x1=930, y1=1560, r=60),
}


def rounded_mask(w, h, rect):
    m = np.zeros((h, w), np.uint8)
    x0, y0, x1, y1, r = rect["x0"], rect["y0"], rect["x1"], rect["y1"], rect["r"]
    cv2.rectangle(m, (x0 + r, y0), (x1 - r, y1), 255, -1)
    cv2.rectangle(m, (x0, y0 + r), (x1, y1 - r), 255, -1)
    for cx, cy in [(x0 + r, y0 + r), (x1 - r, y0 + r), (x0 + r, y1 - r), (x1 - r, y1 - r)]:
        cv2.circle(m, (cx, cy), r, 255, -1)
    return m


def make_background(w, h):
    """Dark charcoal gradient + soft violet spotlight — clean premium default."""
    top = np.array([28, 26, 32], np.float32)
    bot = np.array([12, 12, 16], np.float32)
    ramp = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    bg = np.repeat(top * (1 - ramp) + bot * ramp, w, axis=1)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xx - w * 0.5) / (w * 0.7)) ** 2 + ((yy - h * 0.46) / (h * 0.5)) ** 2)
    glow = np.clip(1 - d, 0, 1) ** 2
    bg += glow[..., None] * np.array([90, 70, 140], np.float32) * 0.35
    return np.clip(bg, 0, 255).astype(np.uint8)


def aspect_dims(aspect):
    w, h = (int(x) for x in aspect.split(":"))
    # canvas height fixed at 1920 for vertical; general: long side 1920
    if h >= w:
        H = 1920
        W = int(round(H * w / h / 2) * 2)
    else:
        W = 1920
        H = int(round(W * h / w / 2) * 2)
    return W, H


def extract_segment(src, start, duration, W, H, fps, workdir):
    """Scale+crop the source to fill WxH, set fps; also pull the audio."""
    seg = os.path.join(workdir, "seg.mp4")
    wav = os.path.join(workdir, "seg.wav")
    ss = ["-ss", str(start)] if start is not None else []
    t = ["-t", str(duration)] if duration is not None else []
    vf = f"scale=-2:{H}:force_original_aspect_ratio=increase,crop={W}:{H},scale={W}:{H}"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", *ss, "-i", src, *t,
                    "-vf", vf, "-r", str(fps), "-an", "-c:v", "libx264", "-crf", "16",
                    "-pix_fmt", "yuv420p", seg, "-y"], check=True)
    has_audio = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", *ss, "-i", src, *t,
         "-vn", "-ac", "2", "-ar", "48000", wav, "-y"]).returncode == 0
    return seg, (wav if has_audio and os.path.exists(wav) else None)


def render(seg, out_silent, card, W, H, contact_shadow, bg_image):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = torch.hub.load("PeterL1n/RobustVideoMatting", "mobilenetv3", trust_repo=True)
    model = model.eval().to(device)
    if device == "cuda":
        model = model.half()

    cardmask = rounded_mask(W, H, card)
    cm = (cardmask.astype(np.float32) / 255)[..., None]

    if bg_image:
        ext = cv2.resize(cv2.imread(bg_image), (W, H)).astype(np.float32)
        studio = ext.copy()
        outer = cv2.GaussianBlur(ext, (0, 0), 18) * 0.6
        border_color = np.array([200, 150, 210], np.float32)
    else:
        outer = make_background(W, H).astype(np.float32)
        studio = None  # windowed layer shows the source video itself
        border_color = np.array([200, 195, 210], np.float32)
        # card drop shadow onto the gradient background (depth)
        drop = cv2.GaussianBlur(cardmask.astype(np.float32) / 255, (0, 0), 34)
        drop = np.roll(np.roll(drop, 22, axis=0), 10, axis=1)
        drop = np.clip(drop - cardmask.astype(np.float32) / 255, 0, 1)
        outer = outer * (1 - drop[..., None] * 0.6)

    edge = cv2.dilate(cardmask, np.ones((3, 3), np.uint8)) - cv2.erode(cardmask, np.ones((3, 3), np.uint8))
    edge_f = cv2.GaussianBlur(edge.astype(np.float32) / 255, (0, 0), 1.2)[..., None]

    # allow mask = where the person cutout may show: inside card OR above the top edge
    y0 = card["y0"]
    allow = cardmask.astype(np.float32) / 255.0
    allow[:y0, :] = 1.0
    allow = cv2.GaussianBlur(allow, (0, 0), 1.5)

    cap = cv2.VideoCapture(seg)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    vw = cv2.VideoWriter(out_silent, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    rec = [None] * 4
    n = 0
    with torch.no_grad():
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            src = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            t = torch.from_numpy(src).permute(2, 0, 1).unsqueeze(0).to(device)
            if device == "cuda":
                t = t.half()
            _, pha, *rec = model(t, *rec, downsample_ratio=0.25)
            alpha = np.clip(pha[0, 0].float().cpu().numpy(), 0, 1)
            vid = frame.astype(np.float32)

            inside = vid if studio is None else (studio * (1 - alpha[..., None]) + relight_passthrough(vid, alpha) * alpha[..., None])
            comp = outer * (1 - cm) + inside * cm

            pop = (alpha * allow)[..., None]
            keep = 1 - pop
            be = edge_f * keep * 0.6
            comp = comp * (1 - be) + border_color * be

            if contact_shadow:
                sh = cv2.GaussianBlur((alpha * allow), (0, 0), 16)
                sh = np.roll(sh, 24, axis=0) * cm[..., 0] * keep[..., 0] * 0.5
                comp = comp * (1 - sh[..., None])

            person = vid if studio is None else relight_passthrough(vid, alpha)
            comp = comp * (1 - pop) + person * pop
            vw.write(np.clip(comp, 0, 255).astype(np.uint8))
            n += 1
    vw.release()
    cap.release()
    return n


def relight_passthrough(vid, alpha):
    """Placeholder relight hook (identity). When a --bg environment is supplied this is
    where a neon/cinematic rim-light grade can be applied to match the scene. Kept as
    identity by default so real footage stays untouched."""
    return vid


def mux(out_silent, wav, out_final):
    if wav:
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error",
                        "-i", out_silent, "-i", wav, "-c:v", "libx264", "-crf", "18",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                        "-shortest", out_final, "-y"], check=True)
    else:
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error",
                        "-i", out_silent, "-c:v", "libx264", "-crf", "18",
                        "-pix_fmt", "yuv420p", out_final, "-y"], check=True)


def main():
    ap = argparse.ArgumentParser(description="Pop-out (frame-break) renderer")
    ap.add_argument("input")
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", type=float, default=None)
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--intensity", choices=list(PRESETS), default="dramatic")
    ap.add_argument("--card-top", type=int, default=None, help="override card top edge y0")
    ap.add_argument("--no-shadow", action="store_true")
    ap.add_argument("--bg", default="none", help="'none' or path to a background image")
    ap.add_argument("--aspect", default="9:16")
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args()

    W, H = aspect_dims(args.aspect)
    card = dict(PRESETS[args.intensity])
    if args.card_top is not None:
        card["y0"] = args.card_top
    bg_image = None if args.bg in ("none", "", None) else args.bg

    workdir = tempfile.mkdtemp(prefix="popout_")
    try:
        seg, wav = extract_segment(args.input, args.start, args.duration, W, H, args.fps, workdir)
        out_silent = os.path.join(workdir, "silent.mp4")
        n = render(seg, out_silent, card, W, H, not args.no_shadow, bg_image)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        mux(out_silent, wav, args.out)
        print(f"OK wrote {args.out} ({n} frames, {W}x{H}, intensity={args.intensity}, "
              f"shadow={not args.no_shadow}, bg={'gradient' if not bg_image else bg_image})")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
