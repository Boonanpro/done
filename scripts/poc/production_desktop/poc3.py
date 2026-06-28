#!/usr/bin/env python3
"""
PoC-3: editing immediacy on the GES engine.
Reuses poc1's timeline build (260 clips). Performs representative NLE edits on the
LIVE timeline (trim / move / split / delete / PiP-reposition), commits, and measures
"edit -> updated preview frame at the playhead" latency = commit_sync + flushing
re-seek to the edited region. Also runs a live edit during PLAYING.

Bar (§5 PoC-3): cut/trim/move reflected with NO wait.
"""
import os, sys, time, json, math, random
import gi
gi.require_version('Gst', '1.0')
gi.require_version('GES', '1.0')
from gi.repository import Gst, GES, GLib
import poc1
NS = poc1.NS
ns = poc1.ns


def stats(xs):
    xs = sorted(xs)
    if not xs:
        return None
    def pct(p):
        k = min(len(xs) - 1, int(math.ceil(p / 100.0 * len(xs))) - 1)
        return round(xs[k], 1)
    return {"n": len(xs), "ms_min": round(xs[0], 1), "ms_median": pct(50),
            "ms_p90": pct(90), "ms_p95": pct(95), "ms_max": round(xs[-1], 1),
            "ms_mean": round(sum(xs) / len(xs), 1)}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("contents")
    ap.add_argument("asset_dir")
    ap.add_argument("--edits", type=int, default=80)
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args()
    args.max = 0; args.no_pip = False; args.no_audio = False; args.transform = True

    Gst.init(None); GES.init()
    random.seed(7)
    mem = poc1.MemSampler(); mem.start()

    rep = {"edits_requested": args.edits}
    by_kind, seq_dur = poc1.load_clips(args.contents)
    timeline, counts, n_assets = poc1.build_timeline(by_kind, args.asset_dir, args)
    rep["counts"] = counts; rep["assets"] = n_assets

    pipe = GES.Pipeline(); pipe.set_timeline(timeline)
    vsink, fps_elem = poc1.make_video_sink("fake")
    pipe.set_property("video-sink", vsink)
    asink = Gst.ElementFactory.make("fakesink"); asink.set_property("sync", True)
    pipe.set_property("audio-sink", asink)
    pipe.set_mode(GES.PipelineFlags.FULL_PREVIEW)
    bus = pipe.get_bus()

    t0 = time.time()
    pipe.set_state(Gst.State.PAUSED)
    st, info = poc1.wait_async_done(bus, 40)
    rep["preroll_s"] = round(time.time() - t0, 3)
    if st != "ok":
        rep["preroll_status"] = st; rep["info"] = info
        print(json.dumps(rep, ensure_ascii=False, indent=2)); return

    layers = timeline.get_layers()
    video_layer = layers[0]
    overlay_layer = layers[1] if len(layers) > 1 else layers[0]

    commit_ms = []
    reflect = {"trim": [], "move": [], "split": [], "delete": [], "pip_move": []}
    errors = 0

    def seek_and_wait(pos_ns):
        t = time.time()
        pipe.seek_simple(Gst.Format.TIME,
                         Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE, pos_ns)
        s, _ = poc1.wait_async_done(bus, 20)
        return (time.time() - t) * 1000.0, s

    ops = ["trim", "move", "split", "delete", "pip_move"]
    for i in range(args.edits):
        op = ops[i % len(ops)]
        clips = video_layer.get_clips()
        oclips = overlay_layer.get_clips()
        if not clips:
            break
        try:
            if op == "pip_move" and oclips:
                c = random.choice(oclips)
                t_edit = time.time()
                c.set_child_property("posx", random.randint(0, args.width - 200))
                c.set_child_property("posy", random.randint(0, args.height - 300))
                ok = timeline.commit_sync()
                commit_ms.append((time.time() - t_edit) * 1000.0)
                dt, s = seek_and_wait(c.get_start() + ns(0.2))
                (reflect[op].append(dt) if s == "ok" else errors.__add__(0))
                if s != "ok": errors += 1
            elif op == "trim":
                c = random.choice(clips)
                d = c.get_duration()
                newd = max(ns(0.4), int(d * random.uniform(0.4, 0.9)))
                t_edit = time.time()
                c.set_duration(newd)
                timeline.commit_sync()
                commit_ms.append((time.time() - t_edit) * 1000.0)
                dt, s = seek_and_wait(c.get_start() + newd - ns(0.05))
                if s == "ok": reflect[op].append(dt)
                else: errors += 1
            elif op == "move":
                c = random.choice(clips)
                shift = ns(random.uniform(-1.5, 1.5))
                newstart = max(0, c.get_start() + shift)
                t_edit = time.time()
                c.set_start(newstart)
                timeline.commit_sync()
                commit_ms.append((time.time() - t_edit) * 1000.0)
                dt, s = seek_and_wait(newstart + ns(0.2))
                if s == "ok": reflect[op].append(dt)
                else: errors += 1
            elif op == "split":
                c = random.choice(clips)
                start = c.get_start(); dur = c.get_duration()
                if dur < ns(0.6):
                    continue
                pos = start + dur // 2
                t_edit = time.time()
                newc = c.split(pos)
                timeline.commit_sync()
                commit_ms.append((time.time() - t_edit) * 1000.0)
                dt, s = seek_and_wait(pos + ns(0.05))
                if s == "ok": reflect[op].append(dt)
                else: errors += 1
            elif op == "delete":
                c = random.choice(clips)
                start = c.get_start()
                t_edit = time.time()
                video_layer.remove_clip(c)
                timeline.commit_sync()
                commit_ms.append((time.time() - t_edit) * 1000.0)
                dt, s = seek_and_wait(start + ns(0.05))
                if s == "ok": reflect[op].append(dt)
                else: errors += 1
        except Exception as e:
            errors += 1
            rep.setdefault("exc", str(e))

    rep["commit_ms"] = stats(commit_ms)
    rep["reflect_ms_by_op"] = {k: stats(v) for k, v in reflect.items() if v}
    all_reflect = [x for v in reflect.values() for x in v]
    rep["reflect_ms_all"] = stats(all_reflect)
    rep["errors"] = errors

    # ---- live edit during PLAYING: move PiP every 250ms, check no stall/drop ----
    pipe.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, 0)
    poc1.wait_async_done(bus, 20)
    r0 = fps_elem.get_property("frames-rendered")
    d0 = fps_elem.get_property("frames-dropped")
    pipe.set_state(Gst.State.PLAYING)
    t0 = time.time(); live_edits = 0; live_err = None
    while time.time() - t0 < 10.0:
        oclips = overlay_layer.get_clips()
        if oclips:
            c = random.choice(oclips)
            try:
                c.set_child_property("posx", random.randint(0, args.width - 200))
                timeline.commit()  # async commit during playback
                live_edits += 1
            except Exception as e:
                live_err = str(e)
        msg = bus.timed_pop_filtered(250 * Gst.MSECOND, Gst.MessageType.ERROR)
        if msg and msg.type == Gst.MessageType.ERROR:
            e, dbg = msg.parse_error(); live_err = f"{e}: {dbg}"; break
    wall = time.time() - t0
    r1 = fps_elem.get_property("frames-rendered")
    d1 = fps_elem.get_property("frames-dropped")
    rep["live_edit_during_play"] = {
        "wall_s": round(wall, 2), "edits_applied": live_edits,
        "frames_rendered": r1 - r0, "frames_dropped": (d1 - d0),
        "avg_fps": round((r1 - r0) / wall, 1) if wall > 0 else None,
        "error": live_err,
    }

    pipe.set_state(Gst.State.NULL); time.sleep(0.2); mem.stop_flag = True
    rep["mem"] = {"peak_rss_mb": round(mem.peak_rss / 1024 / 1024, 1)}
    print(json.dumps(rep, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
