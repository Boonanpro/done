"""Bake a tracked BLUR MASK video for one clip window using SAM 3.1 (multiplex tracker).

The AI counterpart of popout_overlay.py: given a source video + time range + a target
(text concept OR a user-drawn box), this produces
  <out>.mp4      grayscale mask video (yuv420p, FULL-range luma: 255=blur here, 0=keep),
                 CFR, aligned to the extracted window; consumed by the native engine
                 (mask x blur shader) and by the ffmpeg export chain (maskedmerge).
  <out>.meta.json  {src, start, duration, fps, w, h, prompt, objects, per-frame boxes}

Prompts (one of):
  --prompt "license plate"          text concept -> ALL instances (SAM 3 PCS)
  --box x,y,w,h                     normalized box at --anchor (single object; SAM 2-style)
Refinement / selection:
  --keep-ids 1,3                    keep only these instance ids (from a previous --probe)
  --point x,y,+  --point x,y,-      positive/negative clicks at --anchor (with --box or --keep-ids single object)
  --probe                           run detection on the anchor frame only, dump
                                    <out>.probe.json + <out>.probe.jpg (numbered overlay), no propagation

QA:
  --overlay-dir DIR                 dump colored mask overlays every --overlay-every frames

Runs in the dedicated SAM env (Python 3.13):
  D:/done/venv_sam3/Scripts/python.exe scripts/blur_mask_bake.py IN.mp4 --out m.mp4 \
      --prompt "person" --start 130 --duration 12 --progress-file p.json

Checkpoint: D:/done/models/sam3/sam3.1_multiplex.pt (SAM License; mirror of facebook/sam3.1).
Used by app/api/production_asset_routes.py for effect clips [{type:'blur', track:'sam3'}].
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CKPT = REPO_ROOT / "models" / "sam3" / "sam3.1_multiplex.pt"
TRACKER_CKPT = REPO_ROOT / "models" / "sam3" / "sam3.pt"  # non-multiplex; single-object fast path


def _ffmpeg() -> str:
    c = os.path.expanduser("~/ffmpeg/bin/ffmpeg.exe")
    if os.path.exists(c):
        return c
    return shutil.which("ffmpeg") or "ffmpeg"


def _progress(path: str | None, stage: str, p: float):
    if not path:
        return
    try:
        Path(path).write_text(json.dumps({"stage": stage, "progress": round(p, 4)}), encoding="utf-8")
    except OSError:
        pass


def extract_window(src: str, start: float, duration: float, fps: float, long_side: int, tmpd: Path) -> Path:
    """Cut [start, start+duration] to a CFR H.264 segment (normalizes VFR screen recordings,
    bounds decode cost; SAM's internal inference size is 1008 so long_side=1080 loses nothing)."""
    seg = tmpd / "window.mp4"
    # compute explicit even output dims in python — ffmpeg if()-expression scaling
    # produced odd widths on some proxies (libx264 "could not open encoder")
    import cv2
    cap = cv2.VideoCapture(src)
    iw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
    ih = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
    cap.release()
    scale = min(1.0, long_side / max(iw, ih))  # never upscale
    ow = max(2, int(round(iw * scale / 2)) * 2)
    oh = max(2, int(round(ih * scale / 2)) * 2)
    vf = f"scale={ow}:{oh},fps={fps}"
    cmd = [_ffmpeg(), "-y", "-ss", f"{max(0.0, start):.3f}"]
    if duration > 0:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-i", src, "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "18", "-pix_fmt", "yuv420p", str(seg)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not seg.exists():
        raise RuntimeError(f"ffmpeg window extract failed: {r.stderr[-800:]}")
    return seg


def load_predictor(ckpt: str, grounding_batch: int = 4):
    from sam3.model_builder import build_sam3_multiplex_video_predictor
    # use_fa3=False: flash-attn-3 is not installable on Windows; the SDPA path is used instead.
    pred = build_sam3_multiplex_video_predictor(checkpoint_path=ckpt, use_fa3=False)
    # The default 16-frame batched detector pass spikes VRAM far past 8GB consumer cards;
    # Windows' sysmem fallback then turns each spike into a multi-minute stall. Smaller
    # batches trade a little throughput for staying inside VRAM (identical outputs).
    m = getattr(pred, "model", None)
    if m is not None and hasattr(m, "batched_grounding_batch_size"):
        m.batched_grounding_batch_size = max(1, int(grounding_batch))
    return pred


def load_tracker_only(ckpt: str):
    """SAM 2-style tracker WITHOUT the per-frame concept detector. For --box/--point
    single-object jobs this is an order of magnitude faster than the multiplex
    (PCS) pipeline, which re-runs exemplar detection through the whole window.
    Needs the non-multiplex sam3.pt (the 3.1 multiplex ckpt has a different neck)."""
    from sam3.model_builder import build_sam3_video_model
    model = build_sam3_video_model(checkpoint_path=ckpt, load_from_HF=False, device="cuda")
    predictor = model.tracker
    predictor.backbone = model.detector.backbone
    return predictor


def run_tracker_only(a, seg, W, H, n_frames, anchor_idx):
    """Yield (frame_idx, union_mask_bool, boxes) via the SAM2-task API."""
    import torch
    predictor = load_tracker_only(str(TRACKER_CKPT))
    # mp4 loading in this path needs decord (no Windows wheels) -> feed a JPEG folder,
    # which the SAM2-style loader handles natively
    frames_dir = Path(seg).parent / "frames"
    frames_dir.mkdir(exist_ok=True)
    r = subprocess.run([_ffmpeg(), "-y", "-i", str(seg), "-q:v", "2", "-start_number", "0",
                        str(frames_dir / "%05d.jpg")], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"frame extract failed: {r.stderr[-400:]}")
    state = predictor.init_state(video_path=str(frames_dir), offload_video_to_cpu=True)
    kw = dict(inference_state=state, frame_idx=anchor_idx, obj_id=1, clear_old_points=True)
    if a.box:
        x, y, w, h = [float(v) for v in a.box.split(",")]
        kw["box"] = torch.tensor([x, y, x + w, y + h], dtype=torch.float32)  # xywh -> xyxy
    pts, labs = [], []
    for p in a.point:
        px, py, sign = p.split(",")
        pts.append([float(px), float(py)])
        labs.append(1 if sign.strip() == "+" else 0)
    if pts:
        kw["points"] = torch.tensor(pts, dtype=torch.float32)
        kw["labels"] = torch.tensor(labs, dtype=torch.int32)
    _, obj_ids, _, video_res_masks = predictor.add_new_points_or_box(**kw)
    yield anchor_idx, (video_res_masks[0] > 0.0).squeeze().cpu().numpy(), {}
    for direction in (False, True):  # forward then reverse from the anchor
        if direction and anchor_idx == 0:
            continue
        for fi, obj_ids, _low, vmasks, _scores in predictor.propagate_in_video(
            state, start_frame_idx=anchor_idx, max_frame_num_to_track=n_frames,
            reverse=direction, propagate_preflight=(not direction),
        ):
            m = (vmasks[0] > 0.0).squeeze().cpu().numpy()
            ys, xs = np.nonzero(m)
            boxes = {}
            if len(xs):
                boxes[1] = [round(xs.min() / m.shape[1], 4), round(ys.min() / m.shape[0], 4),
                            round((xs.max() - xs.min()) / m.shape[1], 4),
                            round((ys.max() - ys.min()) / m.shape[0], 4)]
            yield fi, (m if m.any() else None), boxes


def _mask_union(out: dict, keep: set[int] | None) -> tuple[np.ndarray | None, dict]:
    """Union the selected objects' binary masks; also return per-object normalized boxes."""
    obj_ids = out["out_obj_ids"].tolist() if hasattr(out["out_obj_ids"], "tolist") else list(out["out_obj_ids"])
    masks = out["out_binary_masks"]
    union = None
    boxes = {}
    for i, oid in enumerate(obj_ids):
        if keep is not None and oid not in keep:
            continue
        m = np.asarray(masks[i])
        if m.ndim == 3:
            m = m.squeeze(0)
        if not m.any():
            continue
        union = m if union is None else (union | m)
        ys, xs = np.nonzero(m)
        h, w = m.shape
        boxes[int(oid)] = [round(xs.min() / w, 4), round(ys.min() / h, 4),
                           round((xs.max() - xs.min()) / w, 4), round((ys.max() - ys.min()) / h, 4)]
    return union, boxes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", required=True, help="output mask mp4 path")
    ap.add_argument("--prompt", default="", help="text concept (English noun phrase)")
    ap.add_argument("--box", default="", help="x,y,w,h normalized (single-object visual prompt)")
    ap.add_argument("--point", action="append", default=[], help="x,y,+|- normalized click (repeatable)")
    ap.add_argument("--keep-ids", default="", help="comma-separated instance ids to keep")
    ap.add_argument("--anchor", type=float, default=0.0, help="prompt frame time, seconds WITHIN the window")
    ap.add_argument("--start", type=float, default=0.0, help="source start seconds")
    ap.add_argument("--duration", type=float, default=0.0, help="window seconds (0 = to end)")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--long-side", type=int, default=1080)
    ap.add_argument("--ckpt", default=str(DEFAULT_CKPT))
    ap.add_argument("--grounding-batch", type=int, default=4,
                    help="detector frames per batched pass (16 = paper default; small = fits 8GB VRAM)")
    ap.add_argument("--prob-thresh", type=float, default=0.0,
                    help="detection score threshold; 0 = AUTO (try 0.5/0.35/0.2 on the anchor "
                         "frame and keep the highest that detects — attribute phrases like "
                         "'person wearing a white shirt' score far below plain nouns)")
    ap.add_argument("--probe", action="store_true", help="detect on anchor frame only; no propagation")
    ap.add_argument("--overlay-dir", default="")
    ap.add_argument("--overlay-every", type=int, default=15)
    ap.add_argument("--dilate", type=int, default=0, help="grow mask by N px (edge-leak guard)")
    ap.add_argument("--feather", type=int, default=0, help="gaussian soften mask edge by N px")
    ap.add_argument("--progress-file", default="")
    a = ap.parse_args()

    import cv2  # after argparse so --help stays fast

    t0 = time.time()
    _progress(a.progress_file, "extract", 0.0)
    tmpd = Path(tempfile.mkdtemp(prefix="blurmask_"))
    try:
        seg = extract_window(a.src, a.start, a.duration, a.fps, a.long_side, tmpd)
        cap = cv2.VideoCapture(str(seg))
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        cap.release()

        anchor_idx = min(max(0, int(round(a.anchor * a.fps))), max(0, n_frames - 1))
        if not a.prompt and not a.box and not a.point:
            print("ERROR: need --prompt or --box or --point", file=sys.stderr)
            return 2
        # single-object visual prompt (box/clicks, no concept text) -> fast tracker-only
        # engine; the multiplex/PCS engine re-runs exemplar detection per frame (~7x slower)
        single = bool(a.box or a.point) and not a.prompt and not a.probe

        _progress(a.progress_file, "load_model", 0.05)
        t_model = time.time()
        union0 = None
        boxes0: dict = {}
        used_prompt, used_thresh = a.prompt, 0.5
        keep = {int(v) for v in a.keep_ids.split(",") if v.strip()} if a.keep_ids else None
        if not single:
            predictor = load_predictor(a.ckpt, a.grounding_batch)
            t_model = time.time()
            # offload video frames to CPU RAM: on 8GB consumer GPUs the full-frame tensor
            # cache otherwise fills VRAM and the sysmem fallback makes inference 10-50x slower
            resp = predictor.handle_request(request=dict(
                type="start_session", resource_path=str(seg),
                offload_video_to_cpu=True, offload_state_to_cpu=True,
            ))
            session_id = resp["session_id"]

            req = dict(type="add_prompt", session_id=session_id, frame_index=anchor_idx)
            if a.prompt:
                req["text"] = a.prompt
            if a.box:
                import torch
                x, y, w, h = [float(v) for v in a.box.split(",")]
                req["bounding_boxes"] = torch.tensor([[x, y, w, h]], dtype=torch.float32)
                req["bounding_box_labels"] = torch.tensor([1], dtype=torch.int32)
            if a.point:
                import torch
                pts, labs = [], []
                for p in a.point:
                    px, py, sign = p.split(",")
                    pts.append([float(px), float(py)])
                    labs.append(1 if sign.strip() == "+" else 0)
                req["points"] = torch.tensor(pts, dtype=torch.float32)
                req["point_labels"] = torch.tensor(labs, dtype=torch.int32)

            _progress(a.progress_file, "detect", 0.08)
            # Two rescue axes when the anchor frame detects nothing (both MEASURED):
            # 1. phrase form — "person wearing a white shirt" detects ZERO at any
            #    threshold while "person in white shirt" detects fine; mechanically
            #    rewrite 'wearing (a/an)' -> 'in' and drop leading articles.
            # 2. score — attribute phrases can score below the 0.5 default; step the
            #    threshold down and keep the HIGHEST one that detects (selectivity).
            def _variants(p: str) -> list[str]:
                seen, out = set(), []
                for v in (
                    p,
                    re.sub(r"\bwearing an?\b", "in", p),
                    re.sub(r"\bwearing\b", "in", p),
                    re.sub(r"\b(a|an|the)\b\s*", "", re.sub(r"\bwearing an?\b", "in", p)).strip(),
                ):
                    v = re.sub(r"\s+", " ", v).strip()
                    if v and v not in seen:
                        seen.add(v)
                        out.append(v)
                return out
            thresholds = [a.prob_thresh] if a.prob_thresh > 0 else ([0.5] if not a.prompt else [0.5, 0.35, 0.2])
            out0 = None
            used_thresh, used_prompt = thresholds[0], a.prompt
            tries = [(ph, th) for ph in (_variants(a.prompt) if a.prompt else [None]) for th in thresholds]
            for i, (ph, th) in enumerate(tries):
                if ph is not None:
                    req["text"] = ph
                req["output_prob_thresh"] = th
                resp = predictor.handle_request(request=req)
                out0 = resp["outputs"]
                used_thresh, used_prompt = th, (ph or a.prompt)
                u, _b = _mask_union(out0, keep)
                if u is not None:
                    break
                if i != len(tries) - 1:
                    predictor.handle_request(request=dict(type="reset_session", session_id=session_id))
                    print(f"no detection (prompt={ph!r} thresh={th}); retrying", flush=True)
            predictor.default_output_prob_thresh = used_thresh  # propagation uses the same bar
            if used_prompt != a.prompt:
                print(f"prompt rescued: {a.prompt!r} -> {used_prompt!r}", flush=True)
            union0, boxes0 = _mask_union(out0, keep)

        out_path = Path(a.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if a.probe:
            # numbered overlay for instance picking (by the user or by a VLM)
            cap = cv2.VideoCapture(str(seg))
            cap.set(cv2.CAP_PROP_POS_FRAMES, anchor_idx)
            ok, frame = cap.read()
            cap.release()
            probe = {"objects": boxes0, "frame_index": anchor_idx, "prompt": a.prompt}
            if ok and frame is not None:
                obj_ids = out0["out_obj_ids"].tolist()
                masks = out0["out_binary_masks"]
                # saturated fixed palette + strong blend: pastel-at-45% was invisible on bright areas
                palette = [(0, 0, 220), (0, 200, 0), (220, 0, 0), (0, 180, 220), (220, 0, 220), (0, 220, 220)]
                for i, oid in enumerate(obj_ids):
                    m = np.asarray(masks[i]).squeeze().astype(bool)
                    if not m.any():
                        continue
                    color = palette[i % len(palette)]
                    frame[m] = (0.45 * frame[m] + 0.55 * np.array(color)).astype(np.uint8)
                    ys, xs = np.nonzero(m)
                    cv2.putText(frame, str(int(oid)), (int(xs.mean()), int(ys.mean())),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
                cv2.imwrite(str(out_path.with_suffix(".probe.jpg")), frame)
            out_path.with_suffix(".probe.json").write_text(json.dumps(probe, indent=1), encoding="utf-8")
            print("probe:", json.dumps(probe))
            return 0

        # ---- propagate through the window and encode the mask video ----
        _progress(a.progress_file, "track", 0.1)
        # stderr must go to a FILE: with stderr=PIPE unread, ffmpeg blocks once the 64KB
        # pipe buffer fills and the stdin.write loop deadlocks (observed: stall at 187KB)
        ff_log = open(tmpd / "ffmpeg_mask.log", "wb")
        ff = subprocess.Popen(
            [_ffmpeg(), "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}",
             "-r", f"{a.fps}", "-i", "-",
             # short GOP (like the proxies): the editor random-seeks this file per frame;
             # the x264 default 250-frame GOP made mid-window seeks walk seconds of frames
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-g", "15",
             "-pix_fmt", "yuv420p", "-color_range", "pc", str(out_path)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=ff_log,
        )
        frames_meta = {}
        written = {}
        kernel = None
        if a.dilate > 0:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (a.dilate * 2 + 1, a.dilate * 2 + 1))

        def _bake_frame(fi, union, boxes):
            g = np.zeros((H, W), np.uint8) if union is None else (union.astype(np.uint8) * 255)
            if g.shape != (H, W):
                g = cv2.resize(g, (W, H), interpolation=cv2.INTER_NEAREST)
            if kernel is not None and union is not None:
                g = cv2.dilate(g, kernel)
            if a.feather > 0 and union is not None:
                k = a.feather * 2 + 1
                g = cv2.GaussianBlur(g, (k, k), 0)
            written[fi] = g
            frames_meta[fi] = boxes

        if single:
            for fi, union, boxes in run_tracker_only(a, seg, W, H, n_frames, anchor_idx):
                _bake_frame(fi, union, boxes)
                if n_frames:
                    _progress(a.progress_file, "track", 0.1 + 0.85 * (len(written) / n_frames))
        else:
            # the anchor frame's masks come from the add_prompt response — propagation
            # does not re-emit them (a zero-mask frame 0 was the observed symptom)
            _bake_frame(anchor_idx, union0, boxes0)
            for r in predictor.handle_stream_request(
                request=dict(type="propagate_in_video", session_id=session_id)
            ):
                fi = r["frame_index"]
                union, boxes = _mask_union(r["outputs"], keep)
                _bake_frame(fi, union, boxes)
                if n_frames:
                    _progress(a.progress_file, "track", 0.1 + 0.85 * (len(written) / n_frames))
        # frames may arrive out of order (propagation runs both directions from the anchor)
        for fi in range(n_frames):
            g = written.get(fi)
            if g is None:
                g = np.zeros((H, W), np.uint8)
            ff.stdin.write(g.tobytes())
        ff.stdin.close()
        rc = ff.wait()
        ff_log.close()
        if rc != 0:
            tail = (tmpd / "ffmpeg_mask.log").read_bytes()[-800:].decode(errors="replace")
            raise RuntimeError(f"mask encode failed: {tail}")

        if a.overlay_dir:
            od = Path(a.overlay_dir)
            od.mkdir(parents=True, exist_ok=True)
            cap = cv2.VideoCapture(str(seg))
            fi = 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if fi % a.overlay_every == 0 and fi in written:
                    m = written[fi] > 127
                    frame[m] = (0.5 * frame[m] + np.array([0, 0, 128])).astype(np.uint8)
                    cv2.imwrite(str(od / f"ov_{fi:05d}.jpg"), frame)
                fi += 1
            cap.release()

        all_ids = sorted({oid for b in frames_meta.values() for oid in b})
        meta = {
            "src": str(a.src), "start": a.start, "duration": a.duration, "fps": a.fps,
            "w": W, "h": H, "n_frames": n_frames, "prompt": a.prompt, "box": a.box,
            "prompt_used": used_prompt, "thresh_used": used_thresh,
            "keep_ids": sorted(keep) if keep else None, "object_ids": all_ids,
            "boxes_by_frame": frames_meta,
            "timing": {"total_s": round(time.time() - t0, 1),
                       "model_load_s": round(t_model - t0, 1),
                       "track_s": round(time.time() - t_model, 1)},
        }
        Path(str(out_path) + ".meta.json").write_text(json.dumps(meta), encoding="utf-8")
        _progress(a.progress_file, "done", 1.0)
        print(f"baked: {out_path} objects={all_ids} frames={n_frames} "
              f"({meta['timing']['track_s']}s track / {meta['timing']['total_s']}s total)")
        return 0
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
