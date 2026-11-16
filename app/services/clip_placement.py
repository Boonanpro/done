"""One set of numbers for where a picture sits: サイズ・左右・上下 (+ crop, + keyframes).

2026-11-16 本人「ダンがやろうと僕がやろうと編集したことはちゃんと数値にも反映されないと不自然」。
Before this, a picture's size/place was written three ways (a `position` box bigger than the
screen, `transform.scale`, per-frame `transform_keys` boxes) and the editor's size field read
only one of them. Now every video/image clip on a picture lane is stored in ONE form:

  fit        cover | contain   what 100% means: the source covering / fitting the canvas
  transform  {scale, x, y}     size (1 = 100%) and offset of the picture's centre from the
                               canvas centre (fractions of the canvas width / height)
  crop       {left,top,right,bottom}  mask: fractions of the PICTURE trimmed away
  shape      circle | rounded  cut inscribed in the visible (cropped) picture
  motion_keys [{t, scale, x, y, ease}]  keyframes (clip-relative seconds). When present they
                               drive scale/x/y; `ease` shapes the move from that key to the next.

No `position`, no media `transform_keys`. Anything still written the old way (an old tab, a
tool, Dan placing by box) is converted on write by `normalize_sequence`, with the exact same
look. The renderers (editor preview, ffmpeg export) draw this form through `render_fields`,
which turns it back into the one box form both of them already draw identically.
"""
from __future__ import annotations

import math
from typing import Any

EASES = ("linear", "ease_out", "ease_in", "ease_in_out", "hold")
_LEGACY_EASE = {"cubic_out": "ease_out", "cubic_in_out": "ease_in_out", "cubic_in": "ease_in"}
TOL = 0.0015          # canvas fraction (~1.6 px at 1080): "the same look"


def ease(name: str | None, f: float) -> float:
    f = 0.0 if f < 0 else 1.0 if f > 1 else f
    n = _LEGACY_EASE.get(str(name or ""), str(name or "linear"))
    if n == "ease_out":
        return 1 - (1 - f) ** 3
    if n == "ease_in":
        return f ** 3
    if n == "ease_in_out":
        return 4 * f ** 3 if f < 0.5 else 1 - (-2 * f + 2) ** 3 / 2
    if n == "hold":
        return 0.0 if f < 1 else 1.0
    return f


def canvas_px(fmt: str | None) -> tuple[float, float]:
    """Output canvas size used for the maths (only the ratio matters)."""
    try:
        a, b = (float(v) for v in str(fmt or "9:16").split(":"))  # the renderers' default
        r = a / b if a > 0 and b > 0 else 16 / 9
    except (TypeError, ValueError):
        r = 16 / 9
    return (1920.0, 1920.0 / r) if r >= 1 else (1920.0 * r, 1920.0)


def _num(v: Any, d: float) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else d
    except (TypeError, ValueError):
        return d


def base_size(sw: float, sh: float, W: float, H: float, fit: str | None) -> tuple[float, float]:
    """The picture's size at 100% (px)."""
    k = min(W / sw, H / sh) if fit == "contain" else max(W / sw, H / sh)
    return sw * k, sh * k


def get_transform(clip: dict[str, Any]) -> tuple[float, float, float]:
    tf = clip.get("transform") if isinstance(clip.get("transform"), dict) else {}
    s = _num(tf.get("scale"), 1.0)
    return (s if s > 0 else 1.0), _num(tf.get("x"), 0.0), _num(tf.get("y"), 0.0)


def clean_keys(raw: Any) -> list[dict[str, Any]]:
    out = []
    for k in raw if isinstance(raw, list) else []:
        if not isinstance(k, dict):
            continue
        # t may be < 0: a key before the clip's head (after its head was trimmed) still shapes the move
        t, s = _num(k.get("t"), float("nan")), _num(k.get("scale"), 0)
        if not math.isfinite(t) or s <= 0:
            continue
        e = _LEGACY_EASE.get(str(k.get("ease") or ""), str(k.get("ease") or "linear"))
        out.append({"t": round(t, 4), "scale": round(s, 5), "x": round(_num(k.get("x"), 0), 5),
                    "y": round(_num(k.get("y"), 0), 5), "ease": e if e in EASES else "linear"})
    out.sort(key=lambda k: k["t"])
    dedup: list[dict[str, Any]] = []
    for k in out:
        if dedup and abs(dedup[-1]["t"] - k["t"]) < 1e-4:
            dedup[-1] = k
        else:
            dedup.append(k)
    return dedup


def motion_at(clip: dict[str, Any], rel: float) -> tuple[float, float, float]:
    """scale, x, y at clip-relative time `rel` (keys win over the static transform)."""
    keys = clean_keys(clip.get("motion_keys"))
    if not keys:
        return get_transform(clip)
    if rel <= keys[0]["t"]:
        k = keys[0]
        return k["scale"], k["x"], k["y"]
    for a, b in zip(keys, keys[1:]):
        if rel < b["t"]:
            e = ease(a.get("ease"), (rel - a["t"]) / max(1e-9, b["t"] - a["t"]))
            return tuple(a[n] + (b[n] - a[n]) * e for n in ("scale", "x", "y"))  # type: ignore[return-value]
    k = keys[-1]
    return k["scale"], k["x"], k["y"]


def picture_rect(clip: dict[str, Any], rel: float, sw: float, sh: float, W: float, H: float) -> tuple[float, float, float, float]:
    """Where the whole (uncropped) picture is drawn, px: x, y, w, h."""
    s, x, y = motion_at(clip, rel)
    bw, bh = base_size(sw, sh, W, H, clip.get("fit"))
    pw, ph = bw * s, bh * s
    return W / 2 + x * W - pw / 2, H / 2 + y * H - ph / 2, pw, ph


def _crop(clip: dict[str, Any]) -> tuple[float, float, float, float]:
    c = clip.get("crop") if isinstance(clip.get("crop"), dict) else {}
    return tuple(max(0.0, min(0.95, _num(c.get(k), 0.0))) for k in ("left", "top", "right", "bottom"))  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# which clips this applies to


def is_placed_media(clip: dict[str, Any], track_type: str | None, asset: dict[str, Any] | None) -> bool:
    """A video / image clip drawn by the compositor (not audio, caption text, a scene or a pop-out)."""
    if track_type == "audio" or not clip.get("asset_id") or not isinstance(asset, dict):
        return False
    if clip.get("scene") or str(clip.get("type") or "") == "scene":
        return False
    if any(isinstance(e, dict) and e.get("type") == "popout" for e in (clip.get("effects") or [])):
        return False
    kind = str(asset.get("kind") or "")
    return kind in ("video", "image") or clip.get("kind") == "image"


def asset_dims(asset: dict[str, Any] | None) -> tuple[float, float] | None:
    md = (asset or {}).get("metadata") if isinstance((asset or {}).get("metadata"), dict) else {}
    sw, sh = _num(md.get("width"), 0), _num(md.get("height"), 0)
    if sw <= 0 or sh <= 0:
        sw, sh = _num((asset or {}).get("width"), 0), _num((asset or {}).get("height"), 0)
    return (sw, sh) if sw > 0 and sh > 0 else None


def is_canonical(clip: dict[str, Any]) -> bool:
    return not isinstance(clip.get("position"), dict) and not clip.get("transform_keys")


# ---------------------------------------------------------------------------
# old forms → the one form


def _legacy_picture(box, s_l, tx, ty, fit, sw, sh, W, H):
    bx, by, bw, bh = box
    if fit == "contain":
        k = min(bw * W / sw, bh * H / sh)
    else:
        k = max(bw * W / sw, bh * H / sh)
    pw, ph = sw * k * s_l, sh * k * s_l
    return bx * W + (bw * W - pw) / 2 + tx * W, by * H + (bh * H - ph) / 2 + ty * H, pw, ph


def _visible(P, crop, box_px, canvas=None):
    px, py, pw, ph = P
    cl, ct, cr, cb = crop
    x0, y0, x1, y1 = px + pw * cl, py + ph * ct, px + pw * (1 - cr), py + ph * (1 - cb)
    if box_px is not None:
        # only the box edges that lie inside the canvas cut anything (the canvas cuts the rest)
        bx, by, bw, bh, cw, ch = (*box_px, *(canvas or (math.inf, math.inf)))
        if bx > 0.5:
            x0 = max(x0, bx)
        if by > 0.5:
            y0 = max(y0, by)
        if bx + bw < cw - 0.5:
            x1 = min(x1, bx + bw)
        if by + bh < ch - 0.5:
            y1 = min(y1, by + bh)
    return x0, y0, x1, y1


def _canon_from_rects(P, V, sw, sh, W, H, fit):
    px, py, pw, ph = P
    bw, _ = base_size(sw, sh, W, H, fit)
    s = pw / bw
    x = (px + pw / 2) / W - 0.5
    y = (py + ph / 2) / H - 0.5
    x0, y0, x1, y1 = V
    crop = ((x0 - px) / pw, (y0 - py) / ph, (px + pw - x1) / pw, (py + ph - y1) / ph)
    return s, x, y, tuple(max(0.0, c) for c in crop)


def _box(pos: Any) -> tuple[float, float, float, float]:
    p = pos if isinstance(pos, dict) else {}
    return _num(p.get("x"), 0.0), _num(p.get("y"), 0.0), _num(p.get("width"), 1.0), _num(p.get("height"), 1.0)


def _legacy_keys(clip):
    out = []
    for k in clip.get("transform_keys") or []:
        if not isinstance(k, dict):
            continue
        t = _num(k.get("t"), -1)
        w, h = _num(k.get("w"), 1.0), _num(k.get("h"), 1.0)
        if t < 0 or w <= 0 or h <= 0:
            continue
        out.append((t, _num(k.get("x"), 0.0), _num(k.get("y"), 0.0), w, h))
    out.sort()
    return out


def _ease_np(name, f):
    import numpy as np
    f = np.clip(f, 0.0, 1.0)
    if name == "ease_out":
        return 1 - (1 - f) ** 3
    if name == "ease_in":
        return f ** 3
    if name == "ease_in_out":
        return np.where(f < 0.5, 4 * f ** 3, 1 - (-2 * f + 2) ** 3 / 2)
    return f


def _fit_sparse(samples: list[tuple[float, float, float, float]]) -> list[dict[str, Any]]:
    """Dense (t, size, x, y) samples → the fewest keys with eases that redraw them within TOL.
    From each key, the farthest later sample that one ease reaches through every sample in between
    becomes the next key (a part of an eased move is not itself eased, so every end is tried)."""
    import numpy as np
    if len(samples) <= 2:
        return [{"t": t, "scale": s, "x": x, "y": y, "ease": "linear"} for t, s, x, y in samples]
    a_ = np.asarray(samples, dtype=float)
    T, V = a_[:, 0], a_[:, 1:]
    gaps = np.diff(T)
    n = len(samples)
    keys, i = [], 0
    while i < n - 1:
        best_j, best_e = i + 1, "linear"
        for j in range(min(n - 1, i + 900), i + 1, -1):
            span = T[j] - T[i]
            if span <= 0:
                continue
            # a curve may only stand for samples taken every frame; between sparse keys the old
            # form moved in straight lines, so only "linear" redraws it
            dense = bool(np.all(gaps[i:j] <= 0.051))
            f = (T[i + 1:j] - T[i]) / span
            found = None
            for e in (("linear", "ease_out", "ease_in_out", "ease_in") if dense else ("linear",)):
                pred = V[i] + (V[j] - V[i]) * _ease_np(e, f)[:, None]
                if np.all(np.abs(pred - V[i + 1:j]) <= TOL):
                    found = e
                    break
            if found:
                best_j, best_e = j, found
                break
        t, s, x, y = samples[i]
        keys.append({"t": t, "scale": s, "x": x, "y": y, "ease": best_e})
        i = best_j
    t, s, x, y = samples[-1]
    keys.append({"t": t, "scale": s, "x": x, "y": y, "ease": "linear"})
    return keys


def to_canonical(clip: dict[str, Any], sw: float, sh: float, W: float, H: float) -> dict[str, Any] | None:
    """The one-form fields that draw exactly what the old fields drew, or None when they can't
    (a stretched picture whose box has another shape, a crop that changes while moving…)."""
    fit = clip.get("fit") or "cover"
    has_box = isinstance(clip.get("position"), dict)
    box = _box(clip.get("position"))
    if fit == "stretch":
        if has_box and abs((box[2] * W / (box[3] * H)) / (sw / sh) - 1) > 0.02:
            return None
        if not has_box and abs((W / H) / (sw / sh) - 1) > 0.02:
            return None
        fit = "cover"
    s_l, tx, ty = get_transform(clip)
    crop = _crop(clip)
    shaped = clip.get("shape") in ("circle", "rounded")
    lkeys = _legacy_keys(clip)
    if not lkeys:
        lkeys = [(0.0, 0.0, 0.0, 1.0, 1.0)]
    results = []
    for t, kx, ky, kw, kh in lkeys:
        b = (box[0] + kx * box[2], box[1] + ky * box[3], box[2] * kw, box[3] * kh)
        P = _legacy_picture(b, s_l, tx, ty, fit, sw, sh, W, H)
        box_px = (b[0] * W, b[1] * H, b[2] * W, b[3] * H)
        V = _visible(P, crop, box_px, (W, H))
        if V[2] - V[0] < 1 or V[3] - V[1] < 1:
            return None
        if shaped:
            # the cut sat on the box: only the same when the box is what shows
            Vb = _visible(P, crop, box_px)
            if any(abs(u - v) > TOL * max(W, H) for u, v in zip(Vb, (box_px[0], box_px[1], box_px[0] + box_px[2], box_px[1] + box_px[3]))):
                return None
        results.append((t,) + _canon_from_rects(P, V, sw, sh, W, H, fit))
    crop0 = results[0][4]
    if any(abs(a - b) > 0.002 for r in results for a, b in zip(r[4], crop0)):
        return None
    out: dict[str, Any] = {"fit": fit}
    if any(c > 1e-4 for c in crop0):
        out["crop"] = {k: round(v, 4) for k, v in zip(("left", "top", "right", "bottom"), crop0)}
    else:
        out["crop"] = None
    if len(results) == 1 or not clip.get("transform_keys"):
        _, s, x, y, _ = results[0]
        out["transform"] = None if (abs(s - 1) < 1e-4 and abs(x) < 1e-5 and abs(y) < 1e-5) else \
            {"scale": round(s, 4), "x": round(x, 4), "y": round(y, 4)}
        out["motion_keys"] = None
    else:
        # fit on the picture's width (canvas fractions), so the tolerance is the same in pixels
        bw = base_size(sw, sh, W, H, fit)[0] / W
        keys = _fit_sparse([(round(t, 4), s * bw, x, y) for t, s, x, y, _ in results])
        for k in keys:
            k["scale"] = k["scale"] / bw
        out["motion_keys"] = clean_keys(keys)
        out["transform"] = None
    return out


def apply_canonical(clip: dict[str, Any], fields: dict[str, Any]) -> None:
    for k, v in fields.items():
        if v is None:
            clip.pop(k, None)
        else:
            clip[k] = v
    clip.pop("position", None)
    clip.pop("transform_keys", None)
    if clip.get("fit") == "cover":
        clip.pop("fit", None)


def normalize_sequence(seq: dict[str, Any] | None, assets: dict[str, dict[str, Any]], fmt: str | None = None) -> dict[str, int]:
    """Convert every picture clip still in an old form to the one form, in place. Clips that
    can't be converted exactly are left as they are (the renderers still draw the old form)."""
    stats = {"converted": 0, "kept": 0}
    if not isinstance(seq, dict):
        return stats
    W, H = canvas_px(fmt or seq.get("format"))
    for tr in seq.get("tracks") or []:
        for clip in tr.get("clips") or []:
            if not isinstance(clip, dict) or is_canonical(clip):
                continue
            asset = assets.get(str(clip.get("asset_id") or ""))
            if not is_placed_media(clip, tr.get("type"), asset):
                continue
            dims = asset_dims(asset)
            fields = to_canonical(clip, dims[0], dims[1], W, H) if dims else None
            if fields is None:
                stats["kept"] += 1
                continue
            apply_canonical(clip, fields)
            stats["converted"] += 1
    return stats


# ---------------------------------------------------------------------------
# the one form → the box form the renderers draw


def render_fields(clip: dict[str, Any], sw: float, sh: float, W: float, H: float, fps: float = 30.0) -> dict[str, Any]:
    """Box-form fields (position = the whole picture, crop on it, transform_keys for moves)
    that the exporter draws exactly like the editor preview draws the one form."""
    dur = max(0.0, _num(clip.get("timeline_end"), 0) - _num(clip.get("timeline_start"), 0))
    P0 = picture_rect(clip, 0.0, sw, sh, W, H)
    out: dict[str, Any] = {
        "position": {"x": P0[0] / W, "y": P0[1] / H, "width": P0[2] / W, "height": P0[3] / H},
        "transform": None, "fit": "cover", "transform_keys": None,
    }
    keys = clean_keys(clip.get("motion_keys"))
    if len(keys) > 1:
        last = min(dur, keys[-1]["t"])
        n = max(1, int(math.ceil(last * fps)))
        ts = sorted({round(i / fps, 5) for i in range(n + 1)} | {k["t"] for k in keys if 0 <= k["t"] <= dur})
        tk = []
        for t in ts:
            P = picture_rect(clip, t, sw, sh, W, H)
            tk.append({"t": round(t, 5), "x": (P[0] - P0[0]) / P0[2], "y": (P[1] - P0[1]) / P0[3],
                       "w": P[2] / P0[2], "h": P[3] / P0[3]})
        out["transform_keys"] = tk
    return out


def render_sequence(seq: dict[str, Any], assets: dict[str, dict[str, Any]], fmt: str | None = None) -> dict[str, Any]:
    """A copy of the sequence with every one-form picture clip in box form (for the exporter)."""
    import copy
    seq = copy.deepcopy(seq)
    W, H = canvas_px(fmt or seq.get("format"))
    fps = _num(seq.get("frame_rate") or seq.get("fps"), 30.0) or 30.0
    for tr in seq.get("tracks") or []:
        for clip in tr.get("clips") or []:
            if not isinstance(clip, dict) or not is_canonical(clip):
                continue
            asset = assets.get(str(clip.get("asset_id") or ""))
            if not is_placed_media(clip, tr.get("type"), asset):
                continue
            dims = asset_dims(asset)
            if not dims:
                continue
            for k, v in render_fields(clip, dims[0], dims[1], W, H, fps).items():
                if v is None:
                    clip.pop(k, None)
                else:
                    clip[k] = v
            clip.pop("motion_keys", None)
    return seq


def describe(clip: dict[str, Any]) -> str:
    """Short text for Dan's view of the timeline."""
    keys = clean_keys(clip.get("motion_keys"))
    parts = []
    if keys:
        parts.append("motion=" + " → ".join(f"{k['t']:.2f}s {k['scale']*100:.0f}% ({k['x']:+.2f},{k['y']:+.2f}){'' if k['ease']=='linear' else ' '+k['ease']}" for k in keys[:6])
                     + (" …" if len(keys) > 6 else ""))
    else:
        s, x, y = get_transform(clip)
        if abs(s - 1) > 1e-4 or abs(x) > 1e-4 or abs(y) > 1e-4:
            parts.append(f"size={s*100:.0f}% pos=({x:+.3f},{y:+.3f})")
    return " ".join(parts)


def _needs_normalize(contents: list[dict[str, Any]]) -> bool:
    for c in contents:
        seq = ((c.get("timeline") or {}) if isinstance(c.get("timeline"), dict) else {}).get("sequence")
        for tr in (seq or {}).get("tracks") or [] if isinstance(seq, dict) else []:
            if tr.get("type") == "audio":
                continue
            for clip in tr.get("clips") or []:
                if isinstance(clip, dict) and clip.get("asset_id") and not is_canonical(clip):
                    return True
    return False


def normalize_contents(contents: list[dict[str, Any]], read_assets) -> int:
    """Every work's timeline in the one form (called on each write of contents.json).
    `read_assets` is only called when some clip still needs converting."""
    if not isinstance(contents, list) or not _needs_normalize(contents):
        return 0
    try:
        assets = {str(a.get("id")): a for a in (read_assets() or []) if isinstance(a, dict)}
    except Exception:  # noqa: BLE001 - never block a save over this
        return 0
    n = 0
    for c in contents:
        tl = c.get("timeline") if isinstance(c.get("timeline"), dict) else None
        seq = tl.get("sequence") if tl else None
        if isinstance(seq, dict):
            n += normalize_sequence(seq, assets, seq.get("format") or tl.get("format") or c.get("format"))["converted"]
    return n


# ---------------------------------------------------------------------------
# pictures with transparent margins (a 1920×1080 PNG with the art in one corner)


def trim_transparent(path: Any) -> dict[str, Any] | None:
    """Cut the transparent margins off a PNG in place, so the clip IS the picture and its place
    is the clip's numbers (押して選べる・欄で直せる). Returns the metadata to keep —
    {"width","height","placed_on": {"canvas": [W,H], "box": [x,y,w,h]}} — or None when the
    picture has no margins worth cutting."""
    from pathlib import Path
    from PIL import Image
    p = Path(str(path))
    if p.suffix.lower() != ".png" or not p.is_file():
        return None
    with Image.open(p) as im:
        im.load()
        if "A" not in im.getbands():
            return None
        W0, H0 = im.size
        bbox = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
        if not bbox:
            return None
        x0, y0, x1, y1 = bbox
        w, h = x1 - x0, y1 - y0
        if w * h > 0.6 * W0 * H0:  # only a picture sitting in a much larger transparent canvas
            return None
        out = im.crop(bbox)
        out.save(p, format="PNG")
    return {"width": w, "height": h, "placed_on": {"canvas": [W0, H0], "box": [x0, y0, w, h]}}


def placed_box(asset: dict[str, Any] | None) -> dict[str, float] | None:
    """Where a trimmed picture sat on its original canvas, as a box of the canvas (fractions)."""
    md = (asset or {}).get("metadata") if isinstance((asset or {}).get("metadata"), dict) else {}
    po = md.get("placed_on") if isinstance(md.get("placed_on"), dict) else None
    try:
        (cw, ch), (x, y, w, h) = po["canvas"], po["box"]
        return {"x": x / cw, "y": y / ch, "width": w / cw, "height": h / ch}
    except (TypeError, KeyError, ValueError, ZeroDivisionError):
        return None


def retarget_to_trimmed(clip: dict[str, Any], old_dims: tuple[float, float], box: list[float],
                        W: float, H: float) -> None:
    """A one-form clip switched from a full PNG to its trimmed picture (box = x,y,w,h of the
    picture in the full PNG, px): the same pixels stay in the same place. Exact for keyframes
    too (the new numbers are an affine function of the old ones)."""
    ow, oh = old_dims
    bx, by, bw, bh = box
    fit = clip.get("fit")

    def conv(s: float, x: float, y: float) -> tuple[float, float, float]:
        P = picture_rect({"fit": fit, "transform": {"scale": s, "x": x, "y": y}}, 0, ow, oh, W, H)
        nx, ny, nw = P[0] + P[2] * bx / ow, P[1] + P[3] * by / oh, P[2] * bw / ow
        nh = P[3] * bh / oh
        s2 = nw / base_size(bw, bh, W, H, fit)[0]
        return s2, (nx + nw / 2) / W - 0.5, (ny + nh / 2) / H - 0.5

    P0 = picture_rect(clip, 0, ow, oh, W, H)
    c = _crop(clip)
    if any(v > 1e-4 for v in c):
        # the crop mask was a fraction of the full PNG: the same cut edges, now of the picture
        vx0, vy0 = P0[0] + P0[2] * c[0], P0[1] + P0[3] * c[1]
        vx1, vy1 = P0[0] + P0[2] * (1 - c[2]), P0[1] + P0[3] * (1 - c[3])
        nx0, ny0 = P0[0] + P0[2] * bx / ow, P0[1] + P0[3] * by / oh
        nw, nh = P0[2] * bw / ow, P0[3] * bh / oh
        nc = (max(0.0, (vx0 - nx0) / nw), max(0.0, (vy0 - ny0) / nh),
              max(0.0, (nx0 + nw - vx1) / nw), max(0.0, (ny0 + nh - vy1) / nh))
        clip["crop"] = {k: round(min(0.95, v), 4) for k, v in zip(("left", "top", "right", "bottom"), nc)}
        if not any(v > 1e-4 for v in nc):
            clip.pop("crop", None)
    keys = clean_keys(clip.get("motion_keys"))
    if keys:
        for k in keys:
            k["scale"], k["x"], k["y"] = (round(v, 5) for v in conv(k["scale"], k["x"], k["y"]))
        clip["motion_keys"] = keys
    else:
        s, x, y = conv(*get_transform(clip))
        clip["transform"] = {"scale": round(s, 5), "x": round(x, 5), "y": round(y, 5)}
