"""Move every work's picture clips to the one form (サイズ・左右・上下・キーフレーム) and swap
full-screen PNGs with transparent margins for their trimmed picture (2026-11-16).

  python scripts/migrate_clip_placement.py            # report only
  python scripts/migrate_clip_placement.py --apply    # write (backups next to each file)

Each room's contents.json / assets.json is copied to *.bak-clip-placement first. The look does
not change: conversions that can't keep it exactly are left in the old form (the renderers still
draw it). A trimmed picture is a NEW asset (the full PNG stays), so an editor tab still holding
the old timeline keeps drawing correctly with the old asset.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import clip_placement as cp  # noqa: E402


def _png_bbox(path: Path):
    from PIL import Image
    try:
        with Image.open(path) as im:
            if "A" not in im.getbands():
                return None
            W0, H0 = im.size
            bbox = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    except Exception:  # noqa: BLE001
        return None
    if not bbox:
        return None
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    if w * h > 0.6 * W0 * H0:  # only a picture sitting in a much larger transparent canvas
        return None
    return (W0, H0), [x0, y0, w, h]


def migrate_room(room: Path, apply: bool, uploads_root: Path) -> dict:
    stats = {"converted": 0, "kept": 0, "trimmed_assets": 0, "retargeted": 0}
    cpath, apath = room / "contents.json", room / "assets.json"
    if not cpath.exists():
        return stats
    contents = json.loads(cpath.read_text(encoding="utf-8"))
    assets_list = json.loads(apath.read_text(encoding="utf-8")) if apath.exists() else []
    assets = {str(a.get("id")): a for a in assets_list if isinstance(a, dict)}
    changed = False
    new_assets: dict[str, dict] = {}
    for c in contents:
        tl = c.get("timeline") if isinstance(c.get("timeline"), dict) else None
        seq = tl.get("sequence") if tl else None
        if not isinstance(seq, dict):
            continue
        fmt = seq.get("format") or tl.get("format") or c.get("format")
        st = cp.normalize_sequence(seq, assets, fmt)
        stats["converted"] += st["converted"]
        stats["kept"] += st["kept"]
        touched = st["converted"] > 0
        W, H = cp.canvas_px(fmt or seq.get("format"))
        for tr in seq.get("tracks") or []:
            for clip in tr.get("clips") or []:
                a = assets.get(str(clip.get("asset_id") or ""))
                if not (isinstance(clip, dict) and cp.is_canonical(clip) and cp.is_placed_media(clip, tr.get("type"), a)):
                    continue
                if str(a.get("kind")) != "image" or (a.get("metadata") or {}).get("placed_on"):
                    continue
                aid = str(a["id"])
                if aid not in new_assets:
                    src = Path(str(a.get("local_path") or ""))
                    if not src.is_absolute():
                        src = uploads_root / src
                    found = _png_bbox(src) if src.suffix.lower() == ".png" and src.is_file() else None
                    if not found:
                        new_assets[aid] = {}
                        continue
                    (W0, H0), box = found
                    nid = uuid.uuid4().hex[:12]
                    dest = room / f"{src.stem}_trim_{nid}.png"
                    if apply:
                        from PIL import Image
                        with Image.open(src) as im:
                            im.crop((box[0], box[1], box[0] + box[2], box[1] + box[3])).save(dest, format="PNG")
                    now = datetime.now(timezone.utc).isoformat()
                    row = {**a, "id": nid, "local_path": str(dest), "original_uri": str(dest),
                           "proxy_path": None, "proxy_url": None, "view_path": None, "view_url": None,
                           "thumbnail_path": None, "thumbnail_url": None,
                           "filename": f"{a.get('filename') or src.name}（絵だけ）",
                           "metadata": {**(a.get("metadata") or {}), "width": box[2], "height": box[3],
                                        "placed_on": {"canvas": [W0, H0], "box": box}, "trimmed_from": aid},
                           "created_at": now, "updated_at": now}
                    new_assets[aid] = row
                    stats["trimmed_assets"] += 1
                row = new_assets[aid]
                if not row:
                    continue
                dims = cp.asset_dims(a)
                po = row["metadata"]["placed_on"]
                cp.retarget_to_trimmed(clip, dims, po["box"], W, H)
                clip["asset_id"] = row["id"]
                stats["retargeted"] += 1
                touched = True
        if touched:
            c["updated_at"] = datetime.now(timezone.utc).isoformat()
            changed = True
    if apply and changed:
        stamp = "bak-clip-placement"
        shutil.copy2(cpath, cpath.with_name(f"contents.json.{stamp}"))
        if apath.exists():
            shutil.copy2(apath, apath.with_name(f"assets.json.{stamp}"))
        add = [r for r in new_assets.values() if r]
        if add:
            apath.write_text(json.dumps(assets_list + add, ensure_ascii=False), encoding="utf-8")
        tmp = cpath.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(contents, ensure_ascii=False), encoding="utf-8")
        tmp.replace(cpath)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--root", default=str(ROOT / "uploads" / "production-assets"))
    ap.add_argument("--room", default="", help="only rooms whose id starts with this")
    args = ap.parse_args()
    root = Path(args.root)
    total: dict[str, int] = {}
    for room in sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith(args.room)):
        from app.services.timeline_draft import ContentsLock  # noqa: F401 - same lock as the app
        st = migrate_room(room, args.apply, root.parent.parent)
        if any(st.values()):
            print(room.name, st)
        for k, v in st.items():
            total[k] = total.get(k, 0) + v
    print("total", total, "(applied)" if args.apply else "(report only)")


if __name__ == "__main__":
    main()
