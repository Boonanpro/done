#!/usr/bin/env python3
"""
PoC-2 video producer. Plays the real GES timeline via d3d11videosink, letting the sink
create its OWN window (class GSTD3D11) -- that path renders video reliably (set_window_handle
into a foreign window renders black). The Rust shell finds that window by class, strips its
border, and keeps it positioned over the WebView2 preview region. Loops forever.
"""
import os, sys
import gi
gi.require_version('Gst', '1.0')
gi.require_version('GES', '1.0')
from gi.repository import Gst, GES, GLib
import poc1


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("contents")
    ap.add_argument("asset_dir")
    ap.add_argument("--mute", action="store_true")
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args()
    args.max = 0; args.no_pip = False; args.no_audio = False; args.transform = True

    Gst.init(None); GES.init()

    if os.environ.get("POC2_TESTSRC"):
        # Debug: bright SMPTE bars into d3d11videosink's own window (unambiguous overlay check).
        p = Gst.parse_launch("videotestsrc pattern=smpte ! videoconvert ! d3d11videosink")
        p.set_state(Gst.State.PLAYING)
        sys.stderr.write("[player] PLAYING (TESTSRC bars, own window).\n"); sys.stderr.flush()
        GLib.MainLoop().run()
        return

    by_kind, seq_dur = poc1.load_clips(args.contents)
    timeline, counts, n_assets = poc1.build_timeline(by_kind, args.asset_dir, args)
    sys.stderr.write(f"[player] timeline built: {counts}, assets={n_assets}, dur={seq_dur:.1f}s\n"); sys.stderr.flush()

    pipe = GES.Pipeline(); pipe.set_timeline(timeline)
    vsink = Gst.ElementFactory.make("d3d11videosink", "vsink")
    vsink.set_property("force-aspect-ratio", True)
    pipe.set_property("video-sink", vsink)
    if args.mute:
        pipe.set_property("audio-sink", Gst.ElementFactory.make("fakesink"))
    else:
        pipe.set_property("audio-sink", Gst.ElementFactory.make("autoaudiosink") or Gst.ElementFactory.make("fakesink"))
    pipe.set_mode(GES.PipelineFlags.FULL_PREVIEW)

    loop = GLib.MainLoop()
    bus = pipe.get_bus(); bus.add_signal_watch()
    def on_msg(_b, m):
        if m.type == Gst.MessageType.EOS:
            pipe.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, 0)
        elif m.type == Gst.MessageType.ERROR:
            e, d = m.parse_error(); sys.stderr.write(f"[player] ERROR {e}: {d}\n"); sys.stderr.flush()
        return True
    bus.connect("message", on_msg)

    pipe.set_state(Gst.State.PLAYING)
    sys.stderr.write("[player] PLAYING (looping, own GSTD3D11 window).\n"); sys.stderr.flush()
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        pipe.set_state(Gst.State.NULL)


if __name__ == "__main__":
    main()
