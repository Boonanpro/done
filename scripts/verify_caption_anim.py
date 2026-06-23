"""M2 animation: render a POP-animated caption (sequence) and a KARAOKE caption (per-word
highlight) through the real renderer; extract frames at different times to confirm motion."""
import sys, json, uuid, subprocess, tempfile
from pathlib import Path
ROOT = Path(r"D:/done"); sys.path.insert(0, str(ROOT))
import app.api.production_asset_routes as P

ROOM="bd05fcc0-c143-4d1c-828e-7624e087b6c1"; MAIN="e22695c0-0b77-4413-a2e8-f585739243bc"
pop = {"font":"dela-gothic","color":"#ffe000","outlineColor":"#000000","outlineWidth":1.3,"animation":"pop"}
kara = {"font":"mplus-rounded","color":"#ffffff","outlineColor":"#1b1b1b","outlineWidth":1.4,
        "animation":"karaoke","highlightColor":"#ff3b6b","highlightScale":1.18}
words = [{"text":"今日","start":4.2,"end":4.7},{"text":"は","start":4.7,"end":4.9},
         {"text":"晴れ","start":4.9,"end":5.5},{"text":"です","start":5.5,"end":6.0}]
seq={"format":"9:16","duration":7.0,"tracks":[
 {"id":"tv","type":"video","clips":[{"id":"V1","asset_id":MAIN,"track":"video","layer":0,"timeline_start":0,"timeline_end":7,"source_start":0,"source_end":7,"composition":"fullscreen","role":"main"}]},
 {"id":"tc","type":"caption","clips":[
   {"id":"CAP1","track":"caption","layer":0,"timeline_start":0.4,"timeline_end":3.6,"text":"ポップイン","style":pop},
   {"id":"CAP2","track":"caption","layer":0,"timeline_start":4.0,"timeline_end":6.2,"text":"今日は晴れです","style":kara,"words":words}]}]}
job_id=uuid.uuid4().hex; job_dir=Path(tempfile.mkdtemp(prefix="anim_"))
res=P._render_sequence_job(ROOM, job_id, "x"*32, {"timeline":{"sequence":seq}}, job_dir)
print("render:", {k:res.get(k) for k in ("render_size","rendered_clip_count")} if res else None)
mp4=job_dir/f"{job_id}_sequence.mp4"
# sequence dirs
for d in sorted(job_dir.glob("caption_*_seq")):
    print("seq:", d.name, len(list(d.glob('*.png'))), "frames")
shots=[("pop_early",0.46),("pop_full",1.5),("kara_w1",4.4),("kara_w3",5.1)]
for name,t in shots:
    out=Path(f"D:/done/uploads/_anim_{name}.png")
    subprocess.run([P._ffmpeg(),"-y","-ss",str(t),"-i",str(mp4),"-frames:v","1",str(out)],
                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
    print("frame:",name,"->",out.name, out.stat().st_size,"b")
# also tile into one image for quick view
tile=Path("D:/done/uploads/_anim_tile.png")
ins=[]
for name,_ in shots: ins+=["-i",f"D:/done/uploads/_anim_{name}.png"]
subprocess.run([P._ffmpeg(),"-y",*ins,"-filter_complex","hstack=inputs=4",str(tile)],
               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
print("tile:",tile)
