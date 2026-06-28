#!/usr/bin/env python3
"""
PoC-1: Convert the production timeline (contents.json) into a GES project (.xges)
that ges-launch-1.0 can load and play. This is the "vehicle" to validate the
GStreamer Editing Services engine premise on Windows:
  multi-clip + multi-layer + HW decode -> instant scrub / stable playback / no OOM.

GES time units are nanoseconds (GstClockTime). Layers:
  layer 0: main fullscreen video clips (track-types=4, video only)
  layer 1: PiP overlay video clips    (track-types=4, video only, optional transform)
  layer 2: dialogue audio clips        (track-types=2, audio only)

Usage:
  python gen_xges.py <contents.json> <asset_dir> <out.xges> [--max N] [--no-pip] [--no-audio] [--transform]
"""
import json, os, sys, html, argparse

NS = 1_000_000_000  # seconds -> nanoseconds

def sec_to_ns(s):
    return int(round(float(s) * NS))

def uri_for(asset_dir, asset_id):
    p = os.path.abspath(os.path.join(asset_dir, f"{asset_id}_proxy.mp4"))
    p = p.replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    return "file://" + p

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("contents")
    ap.add_argument("asset_dir")
    ap.add_argument("out")
    ap.add_argument("--max", type=int, default=0, help="cap clips per track (0=all)")
    ap.add_argument("--no-pip", action="store_true")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--transform", action="store_true", help="apply PiP posx/posy/width/height")
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args()

    data = json.load(open(args.contents, encoding="utf-8"))
    content = data[0]
    seq = content["timeline"]["sequence"]
    tracks = seq["tracks"]

    by_kind = {}
    for t in tracks:
        by_kind.setdefault(t.get("type"), []).extend(t.get("clips") or [])

    video_clips = by_kind.get("video", [])
    overlay_clips = [] if args.no_pip else by_kind.get("overlay", [])
    audio_clips = [] if args.no_audio else by_kind.get("audio", [])

    if args.max:
        video_clips = video_clips[:args.max]
        overlay_clips = overlay_clips[:args.max]
        audio_clips = audio_clips[:args.max]

    # collect assets actually referenced
    used = []
    for grp in (video_clips, overlay_clips, audio_clips):
        for c in grp:
            aid = c.get("asset_id")
            if aid and aid not in used:
                used.append(aid)

    out = []
    out.append("<ges version='0.7'>")
    out.append("  <project properties='properties;' metadatas='metadatas;'>")
    out.append("    <ressources>")
    for aid in used:
        uri = uri_for(args.asset_dir, aid)
        out.append(
            f"      <asset id='{html.escape(uri)}' extractable-type-name='GESUriClip' "
            f"properties='properties, supported-formats=(int)6, duration=(guint64)18446744073709551615;' "
            f"metadatas='metadatas;' />"
        )
    out.append("    </ressources>")

    caps_v = f"video/x-raw(ANY)"
    caps_a = f"audio/x-raw(ANY)"
    restrict_v = f"video/x-raw, width=(int){args.width}, height=(int){args.height}, framerate=(fraction){args.fps}/1"
    out.append("    <timeline properties='properties, auto-transition=(boolean)false;' metadatas='metadatas;'>")
    out.append(f"      <track caps='{caps_v}' track-type='4' track-id='0' "
               f"properties='properties, restriction-caps=(string)\"{restrict_v}\", mixing=(boolean)true;' "
               f"metadatas='metadatas;' />")
    out.append(f"      <track caps='{caps_a}' track-type='2' track-id='1' "
               f"properties='properties, mixing=(boolean)true;' metadatas='metadatas;' />")

    clip_id = 0
    def emit_layer(priority, clips, track_types, transform=False):
        nonlocal clip_id
        out.append(f"      <layer priority='{priority}' properties='properties, auto-transition=(boolean)false;' metadatas='metadatas;'>")
        for c in clips:
            aid = c.get("asset_id")
            if not aid:
                continue
            uri = uri_for(args.asset_dir, aid)
            start = sec_to_ns(c["timeline_start"])
            dur = sec_to_ns(c["timeline_end"] - c["timeline_start"])
            inp = sec_to_ns(c.get("source_start", 0))
            if dur <= 0:
                continue
            children = ""
            if transform and c.get("position"):
                pos = c["position"]
                px = int(round(pos.get("x", 0) * args.width))
                py = int(round(pos.get("y", 0) * args.height))
                pw = int(round(pos.get("width", 1) * args.width))
                ph = int(round(pos.get("height", 1) * args.height))
                children = (f"children-properties='properties, GESVideoSource::posx=(int){px}, "
                            f"GESVideoSource::posy=(int){py}, GESVideoSource::width=(int){pw}, "
                            f"GESVideoSource::height=(int){ph};' ")
            out.append(
                f"        <clip id='{clip_id}' asset-id='{html.escape(uri)}' type-name='GESUriClip' "
                f"layer-priority='{priority}' track-types='{track_types}' start='{start}' "
                f"duration='{dur}' inpoint='{inp}' rate='0' {children}"
                f"properties='properties, name=(string)clip{clip_id};' metadatas='metadatas;' />"
            )
            clip_id += 1
        out.append("      </layer>")

    emit_layer(0, video_clips, 4, transform=False)
    if overlay_clips:
        emit_layer(1, overlay_clips, 4, transform=args.transform)
    if audio_clips:
        emit_layer(2, audio_clips, 2, transform=False)

    out.append("    </timeline>")
    out.append("  </project>")
    out.append("</ges>")

    open(args.out, "w", encoding="utf-8").write("\n".join(out))
    print(f"wrote {args.out}: {clip_id} clips, {len(used)} assets, "
          f"video={len(video_clips)} overlay={len(overlay_clips)} audio={len(audio_clips)}")

if __name__ == "__main__":
    main()
