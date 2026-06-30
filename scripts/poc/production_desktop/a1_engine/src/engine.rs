//! A1 in-process media engine.
//!
//! Builds a GES timeline from the timeline JSON (3 layers: video / overlay-PiP / audio,
//! mirroring `poc1.build_timeline`) and drives an in-process `ges::Pipeline`. Exposes the
//! engine API the MVP needs: `load / seek / play / pause / apply_edit / get_state`.
//!
//! Headless for A1 (fpsdisplaysink → fakesink, like poc1/poc3); the on-screen surface is
//! A2's job. Clip identity comes from the JSON `id` so edits can target a specific clip.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Instant;

use gstreamer as gst;
use gstreamer_editing_services as ges;
use gst::glib;
use gst::prelude::*;
use ges::prelude::*;

use crate::timeline_model::{self, Clip as ClipModel, Position};

const NS: f64 = 1_000_000_000.0;

fn ct_from_secs(s: f64) -> gst::ClockTime {
    let ns = if s <= 0.0 { 0 } else { (s * NS).round() as u64 };
    gst::ClockTime::from_nseconds(ns)
}

fn secs_of(ct: gst::ClockTime) -> f64 {
    ct.nseconds() as f64 / NS
}

/// Per-clip state cached between rebuilds so we can diff (touch only what changed) instead of
/// dropping + re-adding all ~250 clips every edit (which made each edit re-preroll the whole
/// timeline synchronously and freeze the UI). `pos` is the PiP rect for overlay clips.
#[derive(Clone)]
struct ClipMeta {
    lane: String,
    ts: f64,
    ss: f64,
    dur: f64,
    pos: Option<Position>,
}

fn pos_eq(a: &Option<Position>, b: &Option<Position>) -> bool {
    match (a, b) {
        (None, None) => true,
        (Some(x), Some(y)) => {
            (x.x - y.x).abs() < 1e-4
                && (x.y - y.y).abs() < 1e-4
                && (x.width - y.width).abs() < 1e-4
                && (x.height - y.height).abs() < 1e-4
        }
        _ => false,
    }
}

/// Apply a PiP rect (normalized 0..1) to an overlay clip's gescompositor pad properties.
fn set_pip(clip: &ges::Clip, pos: &Position, w: i32, h: i32) {
    let _ = clip.set_child_property("posx", &glib::Value::from((pos.x * w as f64) as i32));
    let _ = clip.set_child_property("posy", &glib::Value::from((pos.y * h as f64) as i32));
    let _ = clip.set_child_property("width", &glib::Value::from((pos.width * w as f64) as i32));
    let _ = clip.set_child_property("height", &glib::Value::from((pos.height * h as f64) as i32));
}

/// One edit operation against the live timeline. Clip targets are JSON `id`s.
#[derive(Debug, Clone)]
pub enum EditOp {
    Trim { clip_id: String, new_duration_s: f64 },
    Move { clip_id: String, new_start_s: f64 },
    Split { clip_id: String, at_s: f64 },
    Delete { clip_id: String },
    PipMove { clip_id: String, posx: i32, posy: i32 },
}

/// Result of `wait_async_done`.
#[derive(Debug, PartialEq, Eq)]
pub enum AsyncStatus {
    Ok,
    Error(String),
    Timeout,
}

#[derive(Debug)]
pub struct LoadReport {
    pub build_s: f64,
    pub preroll_s: f64,
    pub preroll_ok: bool,
    pub video_clips: usize,
    pub overlay_clips: usize,
    pub audio_clips: usize,
    pub skipped: usize,
    pub assets: usize,
    pub timeline_duration_s: f64,
}

#[derive(Debug)]
pub struct SeekResult {
    pub ok: bool,
    pub ms: f64,
}

#[derive(Debug)]
pub struct EditResult {
    pub ok: bool,
    /// Time to mutate + `commit_sync` (engine-side, no preview seek).
    pub commit_ms: f64,
    /// Timeline position a caller should seek to in order to observe the edit.
    pub verify_pos_s: f64,
    /// For Split: the JSON id assigned to the newly created tail clip.
    pub new_clip_id: Option<String>,
    pub note: Option<String>,
}

/// Snapshot of engine state (serializable shape lives in main's report).
#[derive(Debug)]
pub struct EngineState {
    pub position_s: f64,
    pub duration_s: f64,
    pub playing: bool,
    pub state: String,
    pub video_clips: usize,
    pub overlay_clips: usize,
    pub audio_clips: usize,
}

pub struct Engine {
    timeline: ges::Timeline,
    pipeline: ges::Pipeline,
    bus: gst::Bus,
    layer_video: ges::Layer,
    layer_overlay: ges::Layer,
    layer_audio: ges::Layer,
    layer_caption: ges::Layer,
    fps_elem: gst::Element,
    // GPU DirectWrite text overlay in front of the on-screen sink; its `text` is updated live as
    // the playhead crosses caption segments (one element — no per-clip GES cost). None = headless.
    caption_overlay: Option<gst::Element>,
    // PTS of the LAST frame actually presented at the video sink (ns; u64::MAX = none yet). This
    // is the true displayed-frame position — it stalls when the picture stalls and never spikes
    // at clip boundaries the way query_position does. The playhead follows this.
    displayed_pos_ns: Arc<AtomicU64>,
    clips: HashMap<String, ges::Clip>,
    clip_meta: HashMap<String, ClipMeta>,
    asset_cache: HashMap<String, ges::UriClipAsset>,
    width: i32,
    height: i32,
    fps: i32,
    asset_dir: PathBuf,
    split_seq: u32,
}

impl Engine {
    /// One-time process init (safe to call repeatedly).
    pub fn init() -> anyhow::Result<()> {
        gst::init()?;
        ges::init()?;
        Ok(())
    }

    /// Create an engine with the output frame format (headless fpsdisplaysink). Call `load`.
    pub fn new(width: i32, height: i32, fps: i32) -> anyhow::Result<Self> {
        Self::new_with_video_sink(width, height, fps, None)
    }

    /// Like `new`, but lets the caller supply the GES pipeline's video-sink (e.g. a
    /// `d3d12swapchainsink` for on-screen DComp compositing). When `None`, a headless
    /// fpsdisplaysink→fakesink is used. With a custom sink the fps counters are unavailable.
    /// Audio is silent (use `new_full` to supply an audio sink).
    pub fn new_with_video_sink(
        width: i32,
        height: i32,
        fps: i32,
        video_sink: Option<gst::Element>,
    ) -> anyhow::Result<Self> {
        Self::new_full(width, height, fps, video_sink, None)
    }

    /// Full constructor: supply both the video-sink and the audio-sink. `None` audio = a silent
    /// `fakesink` (headless); pass e.g. `autoaudiosink` to actually play the timeline's audio.
    pub fn new_full(
        width: i32,
        height: i32,
        fps: i32,
        video_sink: Option<gst::Element>,
        audio_sink: Option<gst::Element>,
    ) -> anyhow::Result<Self> {
        let timeline = ges::Timeline::new_audio_video();
        // GES layer priority 0 composites ON TOP. The PiP overlay must sit IN FRONT of the
        // fullscreen video, so the overlay layer is created FIRST (priority 0) and the fullscreen
        // video SECOND (priority 1, behind). (Previously video was on top and hid the PiP.)
        let layer_overlay = timeline.append_layer(); // 0: PiP overlay video (front)
        let layer_video = timeline.append_layer(); // 1: fullscreen video (behind)
        let layer_audio = timeline.append_layer(); // 2: dialogue audio
        let layer_caption = timeline.append_layer(); // 3: (unused — captions are web overlays)

        let pipeline = ges::Pipeline::new();
        pipeline.set_timeline(&timeline)?;

        // Video sink: caller-supplied, else headless fpsdisplaysink (rendered/dropped counters).
        let mut caption_overlay: Option<gst::Element> = None;
        let displayed_pos_ns = Arc::new(AtomicU64::new(u64::MAX));
        let (vsink_elem, fps_elem) = match video_sink {
            Some(sink) => {
                // Wrap the on-screen sink with a GPU DirectWrite text overlay: captions composite
                // INTO the video frame (dwritetextoverlay takes video/x-raw(ANY) → stays on GPU
                // memory, no CPU roundtrip). One element, `text` updated live — this avoids the
                // GES TextOverlayClip cost (~286ms/clip) that froze the UI. Defaults already place
                // text bottom-centre, white, black outline.
                let cap = gst::ElementFactory::make("dwritetextoverlay")
                    .name("caption")
                    .build()
                    .map_err(|e| anyhow::anyhow!("make dwritetextoverlay: {e}"))?;
                cap.set_property("font-family", "Meiryo");
                cap.set_property_from_str("font-weight", "bold");
                cap.set_property_from_str("font-size", "56");
                cap.set_property("foreground-color", 0xFFFF_FFFFu32);
                cap.set_property("outline-color", 0xFF00_0000u32);
                cap.set_property("text", "");
                // dwritetextoverlay attaches the caption as GstVideoOverlayComposition metadata (the
                // d3d12swapchainsink advertises overlay support but never renders it). d3d12upload
                // forces D3D12 memory (the decoders are d3d11, so the stream may arrive as d3d11/
                // system), then d3d12overlaycompositor RENDERS the overlay metadata onto the D3D12
                // frame on the GPU before the swapchain sink. (Self-verified on screen.)
                let ul = gst::ElementFactory::make("d3d12upload").build()?;
                let ovc = gst::ElementFactory::make("d3d12overlaycompositor").build()?;
                let q = gst::ElementFactory::make("queue").build()?;
                let bin = gst::Bin::with_name("capbin");
                bin.add_many([&cap, &ul, &ovc, &q, &sink])?;
                gst::Element::link_many([&cap, &ul, &ovc, &q, &sink])?;
                let target = cap
                    .static_pad("sink")
                    .ok_or_else(|| anyhow::anyhow!("dwritetextoverlay sink pad missing"))?;
                let ghost = gst::GhostPad::with_target(&target)?;
                bin.add_pad(&ghost)?;
                caption_overlay = Some(cap);
                // PAD PROBE on the real sink: record the PTS of every frame that actually reaches
                // the screen. This is the displayed-frame position — it freezes when the picture
                // freezes and never spikes at clip boundaries like query_position. The playhead
                // follows this (via get_state), so the bar and the picture stay locked together.
                if let Some(spad) = sink.static_pad("sink") {
                    let dp = displayed_pos_ns.clone();
                    spad.add_probe(gst::PadProbeType::BUFFER, move |_pad, info| {
                        if let Some(gst::PadProbeData::Buffer(buf)) = &info.data {
                            if let Some(pts) = buf.pts() {
                                dp.store(pts.nseconds(), Ordering::Relaxed);
                            }
                        }
                        gst::PadProbeReturn::Ok
                    });
                }
                (bin.upcast::<gst::Element>(), sink)
            }
            None => {
                let bin = gst::parse::bin_from_description(
                    "fpsdisplaysink name=fps text-overlay=false sync=true video-sink=\"fakesink sync=true\"",
                    true,
                )?;
                let fps = bin
                    .by_name("fps")
                    .ok_or_else(|| anyhow::anyhow!("fpsdisplaysink 'fps' not found"))?;
                (bin.upcast::<gst::Element>(), fps)
            }
        };
        pipeline.set_property("video-sink", &vsink_elem);

        let asink = match audio_sink {
            Some(a) => a,
            None => {
                let a = gst::ElementFactory::make("fakesink").build()?;
                a.set_property("sync", true);
                a
            }
        };
        pipeline.set_property("audio-sink", &asink);

        pipeline.set_mode(ges::PipelineFlags::FULL_PREVIEW)?;

        let bus = pipeline.bus().ok_or_else(|| anyhow::anyhow!("no bus"))?;

        Ok(Self {
            timeline,
            pipeline,
            bus,
            layer_video,
            layer_overlay,
            layer_audio,
            layer_caption,
            fps_elem,
            caption_overlay,
            displayed_pos_ns,
            clips: HashMap::new(),
            clip_meta: HashMap::new(),
            asset_cache: HashMap::new(),
            width,
            height,
            fps,
            asset_dir: PathBuf::new(),
            split_seq: 0,
        })
    }

    fn uri_for(&self, asset_id: &str) -> String {
        let p = self
            .asset_dir
            .join(format!("{asset_id}_proxy.mp4"));
        let mut s = p
            .canonicalize()
            .unwrap_or(p)
            .to_string_lossy()
            .replace('\\', "/");
        // strip the \\?\ UNC prefix canonicalize adds on Windows
        if let Some(rest) = s.strip_prefix("//?/") {
            s = rest.to_string();
        }
        if !s.starts_with('/') {
            s = format!("/{s}");
        }
        format!("file://{s}")
    }

    fn get_asset(&mut self, asset_id: &str) -> Result<ges::UriClipAsset, glib::Error> {
        let uri = self.uri_for(asset_id);
        if let Some(a) = self.asset_cache.get(&uri) {
            return Ok(a.clone());
        }
        let a = ges::UriClipAsset::request_sync(&uri)?;
        self.asset_cache.insert(uri, a.clone());
        Ok(a)
    }

    /// Build the timeline from `contents.json` and preroll to PAUSED (load = build + preroll).
    pub fn load(&mut self, contents_path: &str, asset_dir: &str) -> anyhow::Result<LoadReport> {
        self.asset_dir = PathBuf::from(asset_dir);
        let seq = timeline_model::parse_contents(contents_path)?;

        let mut video_clips = 0usize;
        let mut overlay_clips = 0usize;
        let mut audio_clips = 0usize;
        let mut skipped = 0usize;

        let t0 = Instant::now();

        // group clips by track kind
        let mut by_kind: HashMap<String, Vec<ClipModel>> = HashMap::new();
        for tr in seq.tracks {
            by_kind.entry(tr.kind.clone()).or_default().extend(tr.clips);
        }

        // video -> layer 0, no transform
        if let Some(clips) = by_kind.remove("video") {
            for c in clips {
                match self.add_clip(c, Layer::Video, false) {
                    Ok(true) => video_clips += 1,
                    _ => skipped += 1,
                }
            }
        }
        // overlay -> layer 1, PiP transform
        if let Some(clips) = by_kind.remove("overlay") {
            for c in clips {
                match self.add_clip(c, Layer::Overlay, true) {
                    Ok(true) => overlay_clips += 1,
                    _ => skipped += 1,
                }
            }
        }
        // audio -> layer 2
        if let Some(clips) = by_kind.remove("audio") {
            for c in clips {
                match self.add_clip(c, Layer::Audio, false) {
                    Ok(true) => audio_clips += 1,
                    _ => skipped += 1,
                }
            }
        }

        // restriction caps: force output frame size + fps on the video tracks
        let caps = gst::Caps::builder("video/x-raw")
            .field("width", self.width)
            .field("height", self.height)
            .field("framerate", gst::Fraction::new(self.fps, 1))
            .build();
        for tr in self.timeline.tracks() {
            if tr.track_type() == ges::TrackType::VIDEO {
                tr.set_restriction_caps(&caps);
            }
        }

        self.timeline.commit_sync();
        let build_s = t0.elapsed().as_secs_f64();

        // preroll to PAUSED
        let t1 = Instant::now();
        self.pipeline
            .set_state(gst::State::Paused)
            .map_err(|e| anyhow::anyhow!("set PAUSED: {e:?}"))?;
        let st = self.wait_async_done(40_000);
        let preroll_s = t1.elapsed().as_secs_f64();
        let preroll_ok = st == AsyncStatus::Ok;

        Ok(LoadReport {
            build_s,
            preroll_s,
            preroll_ok,
            video_clips,
            overlay_clips,
            audio_clips,
            skipped,
            assets: self.asset_cache.len(),
            timeline_duration_s: secs_of(self.timeline.duration()),
        })
    }

    fn add_clip(&mut self, c: ClipModel, layer: Layer, transform: bool) -> anyhow::Result<bool> {
        let asset_id = match &c.asset_id {
            Some(a) if !a.is_empty() => a.clone(),
            _ => return Ok(false),
        };
        let dur = c.duration_s();
        if dur <= 0.0 {
            return Ok(false);
        }
        let asset = match self.get_asset(&asset_id) {
            Ok(a) => a,
            Err(_) => return Ok(false),
        };
        let (gl, ttype) = match layer {
            Layer::Video => (&self.layer_video, ges::TrackType::VIDEO),
            Layer::Overlay => (&self.layer_overlay, ges::TrackType::VIDEO),
            Layer::Audio => (&self.layer_audio, ges::TrackType::AUDIO),
        };
        let clip = match gl.add_asset(
            &asset,
            ct_from_secs(c.timeline_start),
            ct_from_secs(c.source_start),
            ct_from_secs(dur),
            ttype,
        ) {
            Ok(clip) => clip,
            Err(_) => return Ok(false),
        };

        if transform {
            if let Some(pos) = c.position {
                let _ = clip.set_child_property(
                    "posx",
                    &glib::Value::from((pos.x * self.width as f64) as i32),
                );
                let _ = clip.set_child_property(
                    "posy",
                    &glib::Value::from((pos.y * self.height as f64) as i32),
                );
                let _ = clip.set_child_property(
                    "width",
                    &glib::Value::from((pos.width * self.width as f64) as i32),
                );
                let _ = clip.set_child_property(
                    "height",
                    &glib::Value::from((pos.height * self.height as f64) as i32),
                );
            }
        }

        if !c.id.is_empty() {
            // cache state so the diff rebuild can detect changes (seeds it at load() too)
            let lane = match layer {
                Layer::Video => "video",
                Layer::Overlay => "overlay",
                Layer::Audio => "audio",
            }
            .to_string();
            self.clip_meta.insert(
                c.id.clone(),
                ClipMeta { lane, ts: c.timeline_start, ss: c.source_start, dur, pos: c.position },
            );
            self.clips.insert(c.id, clip);
        }
        Ok(true)
    }

    /// Replace the whole timeline with `clips` (each tagged with a lane: "video"/"overlay"/
    /// "audio"). Removes every existing clip and rebuilds — the robust way to mirror an external
    /// editor's edits (move/trim/split/delete/link/ripple) in one shot. Returns clips added.
    pub fn rebuild(&mut self, clips: Vec<(String, ClipModel)>) -> anyhow::Result<usize> {
        use std::collections::HashSet;
        // DIFF rebuild: touch only what actually changed instead of dropping + re-adding all ~250
        // clips every edit. Dropping everything made each edit re-build + re-preroll the whole
        // timeline synchronously on the UI thread → occasional "not responding". Now a single
        // clip move only updates that one clip, so commit cost scales with the EDIT, not the
        // timeline. (Captions are NOT GES clips — drawn as an HTML overlay in the webview.)
        let mut incoming_ids: HashSet<String> = HashSet::new();
        let mut wanted: Vec<(String, ClipModel)> = Vec::new();
        for (lane, c) in clips {
            if lane == "caption" {
                continue;
            }
            if c.asset_id.as_deref().map(str::is_empty).unwrap_or(true) || c.duration_s() <= 0.0 {
                continue;
            }
            incoming_ids.insert(c.id.clone());
            wanted.push((lane, c));
        }

        let mut dirty = false;

        // 1) remove clips that no longer exist
        let gone: Vec<String> = self
            .clips
            .keys()
            .filter(|id| !incoming_ids.contains(*id))
            .cloned()
            .collect();
        for id in gone {
            if let Some(clip) = self.clips.remove(&id) {
                let _ = self.layer_video.remove_clip(&clip);
                let _ = self.layer_overlay.remove_clip(&clip);
                let _ = self.layer_audio.remove_clip(&clip);
                self.clip_meta.remove(&id);
                dirty = true;
            }
        }

        // 2) add new clips, update changed ones, leave unchanged ones untouched
        for (lane, c) in wanted {
            let (layer, transform) = match lane.as_str() {
                "overlay" => (Layer::Overlay, true),
                "audio" => (Layer::Audio, false),
                _ => (Layer::Video, false),
            };
            let dur = c.duration_s();
            match (self.clips.get(&c.id).cloned(), self.clip_meta.get(&c.id).cloned()) {
                (Some(clip), Some(m)) if m.lane == lane => {
                    // same clip, same lane → update timing / PiP only if it actually moved
                    if (m.ts - c.timeline_start).abs() > 1e-4
                        || (m.ss - c.source_start).abs() > 1e-4
                        || (m.dur - dur).abs() > 1e-4
                    {
                        clip.set_start(ct_from_secs(c.timeline_start));
                        let _ = clip.set_inpoint(ct_from_secs(c.source_start));
                        let _ = clip.set_duration(ct_from_secs(dur));
                        dirty = true;
                    }
                    if transform && !pos_eq(&m.pos, &c.position) {
                        if let Some(pos) = &c.position {
                            set_pip(&clip, pos, self.width, self.height);
                        }
                        dirty = true;
                    }
                    self.clip_meta.insert(
                        c.id.clone(),
                        ClipMeta { lane, ts: c.timeline_start, ss: c.source_start, dur, pos: c.position },
                    );
                }
                _ => {
                    // new clip, or its lane changed → drop the old (if any) and add fresh
                    if let Some(old) = self.clips.remove(&c.id) {
                        let _ = self.layer_video.remove_clip(&old);
                        let _ = self.layer_overlay.remove_clip(&old);
                        let _ = self.layer_audio.remove_clip(&old);
                    }
                    let (id, ts, ss, pos) =
                        (c.id.clone(), c.timeline_start, c.source_start, c.position);
                    if self.add_clip(c, layer, transform).unwrap_or(false) {
                        self.clip_meta.insert(id, ClipMeta { lane, ts, ss, dur, pos });
                        dirty = true;
                    }
                }
            }
        }

        // commit_sync only when something changed: serializes reconfiguration (no native overlap
        // crash) but, because the diff makes the change set tiny, the re-preroll is now sub-frame
        // for a typical edit rather than re-prerolling all ~250 clips.
        if dirty {
            let t = Instant::now();
            self.timeline.commit_sync();
            eprintln!(
                "[rebuild] commit_sync {:.0}ms ({} clips total)",
                t.elapsed().as_secs_f64() * 1000.0,
                self.clips.len()
            );
        }
        Ok(self.clips.len())
    }

    /// Flushing, frame-accurate seek; returns latency (commit→ASYNC_DONE) in ms.
    pub fn seek(&self, pos_s: f64) -> SeekResult {
        let flags = gst::SeekFlags::FLUSH | gst::SeekFlags::ACCURATE;
        let t0 = Instant::now();
        // pin the displayed position to the seek target so the playhead holds there during the
        // re-preroll (the probe still holds the OLD frame's PTS until the new frame presents).
        self.displayed_pos_ns.store(ct_from_secs(pos_s).nseconds(), Ordering::Relaxed);
        if self
            .pipeline
            .seek_simple(flags, ct_from_secs(pos_s))
            .is_err()
        {
            return SeekResult { ok: false, ms: 0.0 };
        }
        let st = self.wait_async_done(20_000);
        SeekResult {
            ok: st == AsyncStatus::Ok,
            ms: t0.elapsed().as_secs_f64() * 1000.0,
        }
    }

    /// Set the live caption text drawn by the GPU overlay (empty = none). Cheap — just a property
    /// set, safe to call often (e.g. when the playhead crosses caption boundaries).
    pub fn set_caption_text(&self, text: &str) {
        if let Some(cap) = &self.caption_overlay {
            cap.set_property("text", text);
        }
    }

    /// Non-blocking seek: issue the flushing seek and return immediately, WITHOUT waiting for
    /// ASYNC_DONE. Used right after rebuild() — waiting there would re-block the UI thread on the
    /// (possibly heavy) re-preroll. The sink presents the new frame when GStreamer is ready.
    pub fn seek_nowait(&self, pos_s: f64) {
        let flags = gst::SeekFlags::FLUSH | gst::SeekFlags::ACCURATE;
        self.displayed_pos_ns.store(ct_from_secs(pos_s).nseconds(), Ordering::Relaxed);
        let _ = self.pipeline.seek_simple(flags, ct_from_secs(pos_s));
    }

    pub fn play(&self) -> anyhow::Result<()> {
        self.pipeline
            .set_state(gst::State::Playing)
            .map_err(|e| anyhow::anyhow!("play: {e:?}"))?;
        Ok(())
    }

    pub fn pause(&self) -> anyhow::Result<()> {
        self.pipeline
            .set_state(gst::State::Paused)
            .map_err(|e| anyhow::anyhow!("pause: {e:?}"))?;
        Ok(())
    }

    /// Apply one edit to the live timeline and `commit_sync`. The edit lands in GES; the
    /// caller seeks `verify_pos_s` to render the updated preview frame (parity with poc3,
    /// which separates commit time from reflect-seek time).
    pub fn apply_edit(&mut self, op: EditOp) -> EditResult {
        match op {
            EditOp::Trim { clip_id, new_duration_s } => {
                let Some(clip) = self.clips.get(&clip_id).cloned() else {
                    return EditResult::miss(&clip_id);
                };
                let t = Instant::now();
                let _ = clip.set_duration(ct_from_secs(new_duration_s));
                self.timeline.commit_sync();
                let verify = secs_of(clip.start() + clip.duration()) - 0.05;
                EditResult::ok(t, verify)
            }
            EditOp::Move { clip_id, new_start_s } => {
                let Some(clip) = self.clips.get(&clip_id).cloned() else {
                    return EditResult::miss(&clip_id);
                };
                let t = Instant::now();
                let _ = clip.set_start(ct_from_secs(new_start_s.max(0.0)));
                self.timeline.commit_sync();
                EditResult::ok(t, new_start_s.max(0.0) + 0.2)
            }
            EditOp::Split { clip_id, at_s } => {
                let Some(clip) = self.clips.get(&clip_id).cloned() else {
                    return EditResult::miss(&clip_id);
                };
                let t = Instant::now();
                let new_clip = match clip.split(ct_from_secs(at_s).nseconds()) {
                    Ok(c) => c,
                    Err(e) => {
                        return EditResult {
                            ok: false,
                            commit_ms: t.elapsed().as_secs_f64() * 1000.0,
                            verify_pos_s: at_s,
                            new_clip_id: None,
                            note: Some(format!("split failed: {e}")),
                        }
                    }
                };
                self.timeline.commit_sync();
                self.split_seq += 1;
                let new_id = format!("{clip_id}__split{}", self.split_seq);
                self.clips.insert(new_id.clone(), new_clip);
                let mut r = EditResult::ok(t, at_s + 0.05);
                r.new_clip_id = Some(new_id);
                r
            }
            EditOp::Delete { clip_id } => {
                let Some(clip) = self.clips.remove(&clip_id) else {
                    return EditResult::miss(&clip_id);
                };
                let start = secs_of(clip.start());
                let t = Instant::now();
                if let Some(layer) = clip.layer() {
                    let _ = layer.remove_clip(&clip);
                }
                self.timeline.commit_sync();
                EditResult::ok(t, start + 0.05)
            }
            EditOp::PipMove { clip_id, posx, posy } => {
                let Some(clip) = self.clips.get(&clip_id).cloned() else {
                    return EditResult::miss(&clip_id);
                };
                let t = Instant::now();
                let _ = clip.set_child_property("posx", &glib::Value::from(posx));
                let _ = clip.set_child_property("posy", &glib::Value::from(posy));
                self.timeline.commit_sync();
                EditResult::ok(t, secs_of(clip.start()) + 0.2)
            }
        }
    }

    /// Reposition a PiP overlay with an **async** commit (non-blocking) — the correct path
    /// for edits applied *during playback*, where a synchronous commit would stall the
    /// streaming threads. Mirrors poc3's live-edit loop (`commit()` while PLAYING).
    pub fn pip_move_async(&self, clip_id: &str, posx: i32, posy: i32) -> bool {
        if let Some(c) = self.clips.get(clip_id) {
            let _ = c.set_child_property("posx", &glib::Value::from(posx));
            let _ = c.set_child_property("posy", &glib::Value::from(posy));
            let _ = self.timeline.commit();
            true
        } else {
            false
        }
    }

    pub fn get_state(&self) -> EngineState {
        // Prefer the DISPLAYED-frame position (pad probe) — it tracks what's actually on screen and
        // doesn't spike at clip boundaries. Fall back to query_position before the first frame.
        let position_s = match self.displayed_pos_ns.load(Ordering::Relaxed) {
            u64::MAX => self
                .pipeline
                .query_position::<gst::ClockTime>()
                .map(secs_of)
                .unwrap_or(0.0),
            ns => ns as f64 / NS,
        };
        let state = self.pipeline.current_state();
        EngineState {
            position_s,
            duration_s: secs_of(self.timeline.duration()),
            playing: state == gst::State::Playing,
            state: format!("{state:?}"),
            video_clips: self.layer_video.clips().len(),
            overlay_clips: self.layer_overlay.clips().len(),
            audio_clips: self.layer_audio.clips().len(),
        }
    }

    /// All known clip ids (JSON order not preserved — HashMap).
    pub fn clip_ids(&self) -> Vec<String> {
        self.clips.keys().cloned().collect()
    }

    /// Ids of clips currently on the video layer (for edit targeting parity with poc3).
    pub fn video_clip_ids(&self) -> Vec<String> {
        let live: std::collections::HashSet<*mut ()> = self
            .layer_video
            .clips()
            .iter()
            .map(|c| c.as_ptr() as *mut ())
            .collect();
        self.clips
            .iter()
            .filter(|(_, c)| live.contains(&(c.as_ptr() as *mut ())))
            .map(|(k, _)| k.clone())
            .collect()
    }

    pub fn overlay_clip_ids(&self) -> Vec<String> {
        let live: std::collections::HashSet<*mut ()> = self
            .layer_overlay
            .clips()
            .iter()
            .map(|c| c.as_ptr() as *mut ())
            .collect();
        self.clips
            .iter()
            .filter(|(_, c)| live.contains(&(c.as_ptr() as *mut ())))
            .map(|(k, _)| k.clone())
            .collect()
    }

    /// Lookup helpers used by the harness.
    pub fn clip_start_s(&self, id: &str) -> Option<f64> {
        self.clips.get(id).map(|c| secs_of(c.start()))
    }
    pub fn clip_duration_s(&self, id: &str) -> Option<f64> {
        self.clips.get(id).map(|c| secs_of(c.duration()))
    }

    pub fn fps_counters(&self) -> (u64, i64) {
        // fpsdisplaysink exposes these as guint in this build.
        let rendered = self.fps_elem.property::<u32>("frames-rendered") as u64;
        let dropped = self.fps_elem.property::<u32>("frames-dropped") as i64;
        (rendered, dropped)
    }

    pub fn bus(&self) -> &gst::Bus {
        &self.bus
    }

    /// Names of decoder elements actually instantiated (HW vs SW), like poc1's probe.
    pub fn decoder_factories(&self) -> HashMap<String, usize> {
        let mut out: HashMap<String, usize> = HashMap::new();
        let mut it = self.pipeline.iterate_recurse();
        loop {
            match it.next() {
                Ok(Some(el)) => {
                    if let Some(f) = el.factory() {
                        let n = f.name().to_string();
                        if n.contains("dec") && !n.contains("decodebin") && !n.contains("audio") {
                            *out.entry(n).or_insert(0) += 1;
                        }
                    }
                }
                Ok(None) => break,
                Err(_) => break,
            }
        }
        out
    }

    /// Wait for ASYNC_DONE / ERROR on the bus (drains STATE_CHANGED).
    pub fn wait_async_done(&self, timeout_ms: u64) -> AsyncStatus {
        let deadline = Instant::now() + std::time::Duration::from_millis(timeout_ms);
        loop {
            if Instant::now() >= deadline {
                return AsyncStatus::Timeout;
            }
            let msg = self.bus.timed_pop_filtered(
                gst::ClockTime::from_mseconds(100),
                &[
                    gst::MessageType::AsyncDone,
                    gst::MessageType::Error,
                    gst::MessageType::StateChanged,
                ],
            );
            let Some(msg) = msg else { continue };
            use gst::MessageView;
            match msg.view() {
                MessageView::Error(e) => {
                    return AsyncStatus::Error(format!("{}: {:?}", e.error(), e.debug()))
                }
                MessageView::AsyncDone(_) => return AsyncStatus::Ok,
                _ => {}
            }
        }
    }

    pub fn set_null(&self) {
        let _ = self.pipeline.set_state(gst::State::Null);
    }
}

#[derive(Clone, Copy)]
enum Layer {
    Video,
    Overlay,
    Audio,
}

impl EditResult {
    fn ok(t: Instant, verify_pos_s: f64) -> Self {
        EditResult {
            ok: true,
            commit_ms: t.elapsed().as_secs_f64() * 1000.0,
            verify_pos_s: verify_pos_s.max(0.0),
            new_clip_id: None,
            note: None,
        }
    }
    fn miss(id: &str) -> Self {
        EditResult {
            ok: false,
            commit_ms: 0.0,
            verify_pos_s: 0.0,
            new_clip_id: None,
            note: Some(format!("unknown clip id: {id}")),
        }
    }
}
