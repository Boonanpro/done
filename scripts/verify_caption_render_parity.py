"""M1 parity: render a real MP4 with a DESIGNED caption (Dela Gothic, yellow, outline, shadow)
through the deterministic renderer, extract a frame, and confirm the caption is burned in via
the /caption-frame HTML route (NOT libass). Visual frame saved for inspection."""
import sys, json, uuid, subprocess, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.api import production_asset_routes as P

ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
MAIN = "e22695c0-0b77-4413-a2e8-f585739243bc"

design = {"font": "dela-gothic", "color": "#ffe000", "outlineColor": "#000000",
          "outlineWidth": 1.3, "shadow": {"blur": 18, "dy": 8, "color": "rgba(0,0,0,0.6)"}}
seq = {"format": "9:16", "duration": 4.0, "tracks": [
    {"id": "tv", "type": "video", "clips": [{"id": "V1", "asset_id": MAIN, "track": "video", "layer": 0,
        "timeline_start": 0, "timeline_end": 4, "source_start": 0, "source_end": 4, "composition": "fullscreen", "role": "main"}]},
    {"id": "tc", "type": "caption", "clips": [{"id": "CAP1", "track": "caption", "layer": 0,
        "timeline_start": 0.4, "timeline_end": 3.6, "text": "渾身のテロップ", "style": design}]}]}

# throwaway content so _attach_output_asset has a target
content = P._update_content  # noqa
import requests
from app.services.auth_service import create_token_pair
tp = create_token_pair(user_id="2582a188-ff24-4a4f-b989-6063034d90b2", email="0aw325171@gmail.com")
H = {"Authorization": f"Bearer {tp.access_token}", "Content-Type": "application/json"}
C = {"done_access_token": tp.access_token}
APIB = "http://127.0.0.1:8000/api/v1/production-assets"
ct = requests.post(f"{APIB}/contents", headers=H, cookies=C, timeout=30, data=json.dumps(
    {"room_id": ROOM, "title": "PARITY", "format": "9:16", "asset_ids": [MAIN],
     "timeline": {"format": "9:16", "source_asset_ids": [MAIN], "annotations": []}})).json()
cid = ct["id"]
out_asset_id = None
try:
    job_id = uuid.uuid4().hex
    job_dir = Path(tempfile.mkdtemp(prefix="parity_"))
    res = P._render_sequence_job(ROOM, job_id, cid, {"timeline": {"sequence": seq}}, job_dir)
    print("render result:", {k: res.get(k) for k in ("render_size", "rendered_clip_count")} if res else None)
    out_asset_id = (res or {}).get("output_asset_id")
    mp4 = job_dir / f"{job_id}_sequence.mp4"
    print("mp4 exists:", mp4.exists(), "spec exists:", (job_dir / "captions_spec.json").exists(),
          "png exists:", (job_dir / "caption_000.png").exists())
    frame = Path("D:/done/uploads/_parity_frame.png")
    subprocess.run([P._ffmpeg(), "-y", "-ss", "2.0", "-i", str(mp4), "-frames:v", "1", str(frame)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    print("frame saved:", frame, "size", frame.stat().st_size)
finally:
    # cleanup throwaway content + generated asset
    cpath = P._room_dir(ROOM) / "contents.json"
    data = [c for c in json.loads(cpath.read_text(encoding="utf-8")) if c["id"] != cid]
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if out_asset_id:
        assets = [a for a in P._read_assets(ROOM) if a.get("id") != out_asset_id]
        P._write_assets(ROOM, assets)
    print("[cleanup] done")
