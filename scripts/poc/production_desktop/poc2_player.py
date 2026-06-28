#!/usr/bin/env python3
"""
PoC-2 video producer: builds the real GES timeline and plays it on-screen via
d3d11videosink, looping. If --hwnd is given, renders INTO that window (GstVideoOverlay)
so a Tauri/wry shell can overlay native video onto a WebView2 preview region.
If --hwnd 0, the sink creates its own top-level window (standalone demo).

Run with Python 3.9 + bundled gi (env set by run_poc2_player.sh).
"""
import os, sys, argparse
import gi
gi.require_version('Gst', '1.0')
gi.require_version('GES', '1.0')
gi.require_version('GstVideo', '1.0')
from gi.repository import Gst, GES, GstVideo, GLib
import poc1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("contents")
    ap.add_argument("asset_dir")
    ap.add_argument("--hwnd", type=int, default=0, help="target window handle (0 = own window)")
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args()
    args.max = 0; args.no_pip = False; args.no_audio = False; args.transform = True

    Gst.init(None); GES.init()

    by_kind, seq_dur = poc1.load_clips(args.contents)
    timeline, counts, n_assets = poc1.build_timeline(by_kind, args.asset_dir, args)
    sys.stderr.write(f"[player] timeline built: {counts}, assets={n_assets}, dur={seq_dur:.1f}s\n")
    sys.stderr.flush()

    pipe = GES.Pipeline(); pipe.set_timeline(timeline)
    vsink = Gst.ElementFactory.make("d3d11videosink", "vsink")
    vsink.set_property("force-aspect-ratio", True)
    pipe.set_property("video-sink", vsink)
    asink = Gst.ElementFactory.make("autoaudiosink")
    pipe.set_property("audio-sink", asink or Gst.ElementFactory.make("fakesink"))
    pipe.set_mode(GES.PipelineFlags.FULL_PREVIEW)

    target_hwnd = args.hwnd

    bus = pipe.get_bus()
    bus.enable_sync_message_emission()

    def on_sync(_bus, message):
        s = message.get_structure()
        if s and GstVideo.is_video_overlay_prepare_window_handle_message(message):
            if target_hwnd:
                sys.stderr.write(f"[player] binding video to hwnd {target_hwnd}\n"); sys.stderr.flush()
                overlay = message.src
                overlay.set_window_handle(target_hwnd)
                try:
                    overlay.set_render_rectangle(0, 0, -1, -1)  # fill the host window
                except Exception:
                    pass
    bus.connect("sync-message::element", on_sync)

    loop = GLib.MainLoop()

    def on_msg(_bus, message):
        t = message.type
        if t == Gst.MessageType.EOS:
            pipe.seek_simple(Gst.Format.TIME,
                             Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, 0)  # loop
        elif t == Gst.MessageType.ERROR:
            err, dbg = message.parse_error()
            sys.stderr.write(f"[player] ERROR {err}: {dbg}\n"); sys.stderr.flush()
            loop.quit()
        return True
    bus.add_signal_watch()
    bus.connect("message", on_msg)

    pipe.set_state(Gst.State.PLAYING)
    sys.stderr.write("[player] PLAYING (looping). Ctrl-C / close window to stop.\n"); sys.stderr.flush()
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        pipe.set_state(Gst.State.NULL)


if __name__ == "__main__":
    main()
