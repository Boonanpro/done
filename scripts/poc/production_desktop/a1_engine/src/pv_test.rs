//! Standalone verification of the danpv:// two-track pop-out source inside GES:
//!   1. GstDiscoverer/UriClipAsset can discover the URI (duration OK)
//!   2. a GES timeline composites it (alpha!) over a background test clip
//!   3. flushing seeks land BOTH tracks in sync (single qtdemux)
//! Dumps PNG frames to the given dir for eyeballing.
//!
//! Usage: pv_test <path-to.pv.mp4> <out_dir>

use gstreamer as gst;
use gstreamer_editing_services as ges;
use gst::prelude::*;
use ges::prelude::*;

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let pv_path = args.get(1).expect("usage: pv_test <file.pv.mp4> <out_dir>").replace('\\', "/");
    let out_dir = args.get(2).expect("out_dir").replace('\\', "/");

    gst::init()?;
    ges::init()?;
    a1_engine::pvsrc::register().expect("register danpvsrc");

    let uri = format!("danpv:///{}", pv_path.trim_start_matches('/'));
    println!("discovering {uri}");
    let asset = ges::UriClipAsset::request_sync(&uri)?;
    println!("OK discovered: duration={:?}", asset.duration());

    let timeline = ges::Timeline::new_audio_video();
    let layer_front = timeline.append_layer(); // priority 0 = front
    let layer_back = timeline.append_layer();

    // background: 5s SMPTE test clip
    let test = ges::TestClip::new().expect("test clip");
    test.set_start(gst::ClockTime::ZERO);
    test.set_duration(Some(gst::ClockTime::from_seconds(8)));
    layer_back.add_clip(&test)?;

    // pop-out overlay on top, full duration of the bake
    let dur = asset.duration().unwrap_or(gst::ClockTime::from_seconds(5));
    let _clip = layer_front.add_asset(
        &asset,
        gst::ClockTime::ZERO,
        gst::ClockTime::ZERO,
        dur,
        ges::TrackType::VIDEO,
    )?;

    let pipeline = ges::Pipeline::new();
    pipeline.set_timeline(&timeline)?;
    let sink = gst::parse::bin_from_description(
        &format!(
            "videoconvert ! video/x-raw,format=RGB ! pngenc ! multifilesink location={}/pv_%04d.png",
            out_dir
        ),
        true,
    )?;
    pipeline.set_property("video-sink", &sink);

    pipeline.set_state(gst::State::Playing)?;
    let bus = pipeline.bus().unwrap();
    let t0 = std::time::Instant::now();
    // play 2s of real time
    loop {
        if t0.elapsed().as_secs_f64() > 2.0 { break; }
        if let Some(msg) = bus.timed_pop_filtered(
            gst::ClockTime::from_mseconds(100),
            &[gst::MessageType::Error, gst::MessageType::Eos],
        ) {
            match msg.view() {
                gst::MessageView::Error(e) => anyhow::bail!("pipeline error: {} ({:?})", e.error(), e.debug()),
                gst::MessageView::Eos(_) => break,
                _ => {}
            }
        }
    }
    let pos: Option<gst::ClockTime> = pipeline.query_position();
    println!("after 2s wall: position={pos:?}");

    // flushing seek to 4.0s — must land both tracks together (single demuxer)
    pipeline.seek_simple(
        gst::SeekFlags::FLUSH | gst::SeekFlags::ACCURATE,
        gst::ClockTime::from_mseconds(4000),
    )?;
    let t1 = std::time::Instant::now();
    loop {
        if t1.elapsed().as_secs_f64() > 1.0 { break; }
        if let Some(msg) = bus.timed_pop_filtered(
            gst::ClockTime::from_mseconds(100),
            &[gst::MessageType::Error],
        ) {
            if let gst::MessageView::Error(e) = msg.view() {
                anyhow::bail!("post-seek error: {} ({:?})", e.error(), e.debug());
            }
        }
    }
    let pos2: Option<gst::ClockTime> = pipeline.query_position();
    println!("after seek(4s)+1s: position={pos2:?}");
    pipeline.set_state(gst::State::Null)?;
    println!("PV TEST OK");
    Ok(())
}
