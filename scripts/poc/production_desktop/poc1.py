#!/usr/bin/env python3
"""
PoC-1: GES native-engine premise check on Windows.
Builds the REAL production timeline (contents.json: 98 video + 35 PiP overlay +
127 audio clips over 6 H.264 proxies) as a GES timeline, then measures:
  1. load   = build + realize + preroll (to PAUSED) time
  2. scrub  = latency of flushing/accurate seeks to random timeline positions
  3. play   = realtime playback stability (frames rendered vs dropped via fpsdisplaysink)
  4. memory = peak process RSS + peak GPU VRAM (nvidia-smi) throughout

Run with Python 3.9 + the GStreamer-bundled gi. Env is set by run_poc1.sh.
"""
import os, sys, time, json, math, random, argparse, threading, subprocess

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GES', '1.0')
from gi.repository import Gst, GES, GLib

NS = 1_000_000_000

def ns(s):  # seconds -> ns
    return int(round(float(s) * NS))

def uri_for(asset_dir, asset_id):
    p = os.path.abspath(os.path.join(asset_dir, f"{asset_id}_proxy.mp4")).replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    return "file://" + p


# ---------- GPU / CPU memory sampler ----------
class MemSampler(threading.Thread):
    def __init__(self, interval=0.05):
        super().__init__(daemon=True)
        self.interval = interval
        self.stop_flag = False
        self.peak_rss = 0
        self.peak_vram = 0
        self._proc = None
        try:
            import psutil
            self._proc = psutil.Process()
        except Exception:
            pass

    def _vram_used(self):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5).stdout.strip().splitlines()
            return int(out[0])  # MiB, total GPU (proxy for our usage delta)
        except Exception:
            return 0

    def run(self):
        while not self.stop_flag:
            if self._proc:
                try:
                    self.peak_rss = max(self.peak_rss, self._proc.memory_info().rss)
                except Exception:
                    pass
            self.peak_vram = max(self.peak_vram, self._vram_used())
            time.sleep(self.interval)


def load_clips(contents_path):
    data = json.load(open(contents_path, encoding="utf-8"))
    seq = data[0]["timeline"]["sequence"]
    by_kind = {}
    for t in seq["tracks"]:
        by_kind.setdefault(t.get("type"), []).extend(t.get("clips") or [])
    return by_kind, float(seq.get("duration", 0))


def build_timeline(by_kind, asset_dir, args):
    timeline = GES.Timeline.new_audio_video()
    layer_v = timeline.append_layer()   # 0: main fullscreen video
    layer_o = timeline.append_layer()   # 1: PiP overlay video
    layer_a = timeline.append_layer()   # 2: dialogue audio

    asset_cache = {}
    def get_asset(uri):
        a = asset_cache.get(uri)
        if a is None:
            a = GES.UriClipAsset.request_sync(uri)
            asset_cache[uri] = a
        return a

    counts = {"video": 0, "overlay": 0, "audio": 0, "skipped": 0}

    def add(group, layer, tracktype, transform=False):
        clips = by_kind.get(group, [])
        if args.max:
            clips = clips[:args.max]
        for c in clips:
            aid = c.get("asset_id")
            if not aid:
                continue
            dur = ns(c["timeline_end"] - c["timeline_start"])
            if dur <= 0:
                counts["skipped"] += 1
                continue
            start = ns(c["timeline_start"])
            inp = ns(c.get("source_start", 0))
            try:
                a = get_asset(uri_for(asset_dir, aid))
                clip = layer.add_asset(a, start, inp, dur, tracktype)
            except GLib.Error as e:
                counts["skipped"] += 1
                continue
            if transform and c.get("position"):
                pos = c["position"]
                try:
                    clip.set_child_property("posx", int(pos.get("x", 0) * args.width))
                    clip.set_child_property("posy", int(pos.get("y", 0) * args.height))
                    clip.set_child_property("width", int(pos.get("width", 1) * args.width))
                    clip.set_child_property("height", int(pos.get("height", 1) * args.height))
                except Exception:
                    pass
            counts[group] += 1

    add("video", layer_v, GES.TrackType.VIDEO, transform=False)
    if not args.no_pip:
        add("overlay", layer_o, GES.TrackType.VIDEO, transform=args.transform)
    if not args.no_audio:
        add("audio", layer_a, GES.TrackType.AUDIO, transform=False)

    # output frame size / fps
    caps = Gst.Caps.from_string(
        f"video/x-raw,width={args.width},height={args.height},framerate={args.fps}/1")
    for tr in timeline.get_tracks():
        if tr.get_property("track-type") == GES.TrackType.VIDEO:
            tr.set_restriction_caps(caps)

    timeline.commit_sync()
    return timeline, counts, len(asset_cache)


def make_video_sink(kind):
    if kind == "d3d11":
        desc = "fpsdisplaysink name=fps text-overlay=false sync=true video-sink=d3d11videosink"
    else:  # fake
        desc = "fpsdisplaysink name=fps text-overlay=false sync=true video-sink=\"fakesink sync=true\""
    bin_ = Gst.parse_bin_from_description(desc, True)
    return bin_, bin_.get_by_name("fps")


def wait_async_done(bus, timeout_s=20):
    end = time.time() + timeout_s
    while time.time() < end:
        msg = bus.timed_pop_filtered(
            100 * Gst.MSECOND,
            Gst.MessageType.ASYNC_DONE | Gst.MessageType.ERROR | Gst.MessageType.STATE_CHANGED)
        if not msg:
            continue
        if msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            return ("error", f"{err}: {dbg}")
        if msg.type == Gst.MessageType.ASYNC_DONE:
            return ("ok", None)
    return ("timeout", None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("contents")
    ap.add_argument("asset_dir")
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--no-pip", action="store_true")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--transform", action="store_true")
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--sink", choices=["fake", "d3d11"], default="fake")
    ap.add_argument("--seeks", type=int, default=40)
    ap.add_argument("--seek-flags", choices=["accurate", "keyunit"], default="accurate")
    ap.add_argument("--play-secs", type=float, default=20.0)
    ap.add_argument("--scrub-window", type=float, default=0.0,
                    help="seconds; >0 = cluster seeks within a local window (warm-decoder scrub)")
    args = ap.parse_args()

    Gst.init(None)
    GES.init()
    random.seed(1234)

    mem = MemSampler()
    vram_baseline = mem._vram_used()
    mem.start()

    rep = {"args": vars(args)}

    by_kind, seq_dur = load_clips(args.contents)
    rep["timeline_duration_s"] = round(seq_dur, 3)

    t0 = time.time()
    timeline, counts, n_assets = build_timeline(by_kind, args.asset_dir, args)
    t_build = time.time() - t0
    dur_ns = timeline.get_duration()
    rep["counts"] = counts
    rep["assets"] = n_assets
    rep["timeline_built_duration_s"] = round(dur_ns / NS, 3)
    rep["build_s"] = round(t_build, 3)

    pipe = GES.Pipeline()
    pipe.set_timeline(timeline)
    vsink, fps_elem = make_video_sink(args.sink)
    try:
        pipe.set_property("video-sink", vsink)
    except Exception as e:
        rep["video_sink_warn"] = str(e)
    asink = Gst.ElementFactory.make("fakesink")
    asink.set_property("sync", True)
    try:
        pipe.set_property("audio-sink", asink)
    except Exception:
        pass
    pipe.set_mode(GES.PipelineFlags.FULL_PREVIEW)

    bus = pipe.get_bus()

    # ---- LOAD: go to PAUSED (preroll) ----
    t0 = time.time()
    pipe.set_state(Gst.State.PAUSED)
    st, info = wait_async_done(bus, timeout_s=40)
    t_preroll = time.time() - t0
    rep["preroll_s"] = round(t_preroll, 3)
    rep["preroll_status"] = st
    if st != "ok":
        rep["preroll_info"] = info
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        mem.stop_flag = True
        pipe.set_state(Gst.State.NULL)
        return

    # ---- probe which decoder elements actually instantiated (HW vs SW) ----
    decs = {}
    try:
        it = pipe.iterate_recurse()
        while True:
            ok, el = it.next()
            if ok == Gst.IteratorResult.DONE:
                break
            if ok != Gst.IteratorResult.OK:
                continue
            f = el.get_factory()
            fn = f.get_name() if f else ""
            if fn and ("dec" in fn) and ("decodebin" not in fn) and ("audio" not in fn):
                decs[fn] = decs.get(fn, 0) + 1
    except Exception as e:
        decs["_err"] = str(e)
    rep["video_decoders"] = decs

    # ---- SCRUB: random flushing seeks in PAUSED ----
    flags = Gst.SeekFlags.FLUSH | (
        Gst.SeekFlags.ACCURATE if args.seek_flags == "accurate" else Gst.SeekFlags.KEY_UNIT)
    lat = []
    fails = 0
    dur_s = dur_ns / NS
    win = args.scrub_window
    center = random.uniform(0, max(0.1, dur_s - 0.2)) if win > 0 else 0
    for i in range(args.seeks):
        if win > 0:
            lo = max(0, center - win / 2)
            hi = min(dur_s - 0.2, center + win / 2)
            pos = random.uniform(lo, hi)
        else:
            pos = random.uniform(0, max(0.1, dur_s - 0.2))
        t0 = time.time()
        pipe.seek_simple(Gst.Format.TIME, flags, ns(pos))
        st, info = wait_async_done(bus, timeout_s=20)
        dt = (time.time() - t0) * 1000.0
        if st == "ok":
            lat.append(dt)
        else:
            fails += 1
    lat.sort()
    def pct(p):
        if not lat: return None
        k = min(len(lat) - 1, int(math.ceil(p / 100.0 * len(lat))) - 1)
        return round(lat[k], 1)
    rep["scrub"] = {
        "seeks": args.seeks, "ok": len(lat), "failed": fails, "flags": args.seek_flags,
        "ms_min": round(lat[0], 1) if lat else None,
        "ms_median": pct(50), "ms_p90": pct(90), "ms_p95": pct(95),
        "ms_max": round(lat[-1], 1) if lat else None,
        "ms_mean": round(sum(lat) / len(lat), 1) if lat else None,
    }

    # ---- PLAY: realtime stability ----
    pipe.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, 0)
    wait_async_done(bus, 20)
    r0 = fps_elem.get_property("frames-rendered")
    d0 = fps_elem.get_property("frames-dropped")
    t0 = time.time()
    pipe.set_state(Gst.State.PLAYING)
    # let it run play-secs of wallclock, watching for errors
    end = t0 + args.play_secs
    err = None
    while time.time() < end:
        msg = bus.timed_pop_filtered(200 * Gst.MSECOND,
                                     Gst.MessageType.ERROR | Gst.MessageType.EOS)
        if msg and msg.type == Gst.MessageType.ERROR:
            e, dbg = msg.parse_error(); err = f"{e}: {dbg}"; break
        if msg and msg.type == Gst.MessageType.EOS:
            break
    wall = time.time() - t0
    r1 = fps_elem.get_property("frames-rendered")
    d1 = fps_elem.get_property("frames-dropped")
    rendered = r1 - r0
    dropped = (d1 - d0) if d1 >= 0 and d0 >= 0 else d1
    rep["play"] = {
        "wall_s": round(wall, 2),
        "frames_rendered": rendered,
        "frames_dropped": dropped if dropped is not None else "n/a",
        "avg_fps": round(rendered / wall, 1) if wall > 0 else None,
        "target_fps": args.fps,
        "error": err,
    }

    pipe.set_state(Gst.State.NULL)
    time.sleep(0.2)
    mem.stop_flag = True
    rep["mem"] = {
        "peak_rss_mb": round(mem.peak_rss / 1024 / 1024, 1),
        "gpu_vram_baseline_mb": vram_baseline,
        "gpu_vram_peak_mb": mem.peak_vram,
        "gpu_vram_delta_mb": mem.peak_vram - vram_baseline,
    }
    print(json.dumps(rep, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
