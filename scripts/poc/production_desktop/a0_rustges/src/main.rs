// A0: de-risk gstreamer-rs/ges on Windows. Build a GES timeline from a real proxy and play it
// in-process (headless fakesink) to prove linking + GES works in Rust.
use gstreamer as gst;
use gstreamer_editing_services as ges;
use gst::prelude::*;
use ges::prelude::*;

fn main() {
    gst::init().expect("gst init");
    ges::init().expect("ges init");
    println!("gstreamer {} / GES initialized in Rust", gst::version_string());

    let timeline = ges::Timeline::new_audio_video();
    let layer = timeline.append_layer();

    let uri = "file:///D:/done/uploads/production-assets/bd05fcc0-c143-4d1c-828e-7624e087b6c1/c2221f83-2ca2-4f9a-b51e-4a6af3a049b8_proxy.mp4";
    let asset = ges::UriClipAsset::request_sync(uri).expect("request asset");
    println!("asset loaded: {}", uri);

    let three = gst::ClockTime::from_seconds(3);
    let _clip = layer
        .add_asset(&asset, Some(gst::ClockTime::ZERO), Some(gst::ClockTime::ZERO),
                   Some(three), ges::TrackType::VIDEO | ges::TrackType::AUDIO)
        .expect("add_asset");

    let pipeline = ges::Pipeline::new();
    pipeline.set_timeline(&timeline).expect("set timeline");
    let vsink = gst::ElementFactory::make("fakesink").build().expect("fakesink");
    pipeline.set_property("video-sink", &vsink);
    let asink = gst::ElementFactory::make("fakesink").build().expect("fakesink");
    pipeline.set_property("audio-sink", &asink);

    pipeline.set_state(gst::State::Playing).expect("play");

    let bus = pipeline.bus().unwrap();
    let start = std::time::Instant::now();
    let mut last = String::new();
    while start.elapsed().as_secs() < 5 {
        if let Some(msg) = bus.timed_pop(gst::ClockTime::from_mseconds(200)) {
            use gst::MessageView;
            match msg.view() {
                MessageView::Error(e) => { eprintln!("ERROR: {}", e.error()); break; }
                MessageView::Eos(_) => { println!("EOS"); break; }
                _ => {}
            }
        }
        if let Some(pos) = pipeline.query_position::<gst::ClockTime>() {
            last = format!("pos = {:.2}s", pos.seconds() as f64 + (pos.nseconds() % 1_000_000_000) as f64 / 1e9);
            print!("\r{}   ", last);
        }
    }
    pipeline.set_state(gst::State::Null).unwrap();
    println!("\n[A0 OK] gstreamer-rs + GES linked, timeline built and played in-process. ({})", last);
}
