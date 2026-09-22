//! done native editor — one process, two threads, zero seams.
//!
//! MEDIA thread (owns D3D11 + decoders + compositor + WASAPI): pulls frames, composites
//! on the GPU, publishes finished RGBA + the audio-master clock. Decodes the ORIGINAL
//! source for quality (proxy only while scrubbing — original long-GOP seeks are slow);
//! primes upcoming clips so boundaries stay free.
//! UI thread (egui): draws the timeline, uploads the latest published frame, sends
//! {t, playing, scrubbing} down. Neither thread ever waits on the other.
//!
//! Usage: native_ui [contents.json] [asset_dir]
//! Keys: Space=play/pause, drag timeline=scrub, wheel=pan, Ctrl+wheel=zoom.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod compositor;
mod caption_live;
mod edits;
mod frame_ring;
mod gpu_present;
mod media;
mod model;

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::sync::OnceLock;
use std::time::Instant;

use eframe::egui;

fn timeline_body_height(ui: &egui::Ui) -> f32 {
    // horizontal() reserves at least interact_size.y, even for a 12px scrollbar.
    // Forgetting the inter-widget gap feeds overflow back into the resizable panel.
    let footer = ui.spacing().interact_size.y.max(12.0);
    (ui.available_height() - footer - ui.spacing().item_spacing.y).max(0.0)
}

#[cfg(test)]
mod timeline_layout_tests {
    use super::*;

    #[test]
    fn timeline_height_stays_at_the_users_size() {
        for height in [160.0, 260.0, 420.0] {
            let ctx = egui::Context::default();
            let mut first = 0.0;
            for frame in 0..240 {
                let input = egui::RawInput {
                    screen_rect: Some(egui::Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(1200.0, 900.0))),
                    ..Default::default()
                };
                let _ = ctx.run(input, |ctx| {
                    ctx.style_mut(|s| s.spacing.item_spacing = egui::vec2(8.0, 8.0));
                    let panel = egui::TopBottomPanel::bottom("timeline")
                        .resizable(true).default_height(height).height_range(140.0..=700.0)
                        .show(ctx, |ui| {
                            ui.horizontal(|ui| { ui.button("Timeline").on_hover_text("toolbar"); });
                            ui.add_space(2.0);
                            let h = timeline_body_height(ui);
                            ui.allocate_exact_size(egui::vec2(ui.available_width(), h), egui::Sense::hover());
                            ui.horizontal(|ui| { ui.allocate_exact_size(egui::vec2(200.0, 12.0), egui::Sense::hover()); });
                        });
                    if frame == 0 { first = panel.response.rect.height(); }
                    assert!((panel.response.rect.height() - first).abs() < 0.1,
                        "panel drift at frame {frame}: {} -> {}", first, panel.response.rect.height());
                });
            }
        }
    }
}

const ROOM: &str = "D:/done/uploads/production-assets/bd05fcc0-c143-4d1c-828e-7624e087b6c1";
// design tokens (Filmora-reference dark theme: near-black stage, teal accent, pink playhead)
const UI_ACCENT: egui::Color32 = egui::Color32::from_rgb(184, 206, 255);
const UI_PLAYHEAD: egui::Color32 = egui::Color32::from_rgb(255, 74, 85);
const UI_PANEL: egui::Color32 = egui::Color32::from_rgb(24, 24, 27);
const UI_STAGE: egui::Color32 = egui::Color32::from_rgb(12, 12, 14);

/// キャンバス寸法はコンテンツの「形式」に追従する（旧: 1080x1920 固定で
/// 16:9 を選んでも縦型に描画されていた）。sequence の width/height が
/// あればそれを優先し、無ければ timeline.format から引く。
static CANVAS_DIMS: std::sync::atomic::AtomicU64 =
    std::sync::atomic::AtomicU64::new((1080u64 << 32) | 1920u64);

fn canvas_w() -> u32 {
    (CANVAS_DIMS.load(std::sync::atomic::Ordering::Relaxed) >> 32) as u32
}

fn canvas_h() -> u32 {
    (CANVAS_DIMS.load(std::sync::atomic::Ordering::Relaxed) & 0xffff_ffff) as u32
}

fn canvas_for_format(fmt: &str) -> (u32, u32) {
    match fmt {
        "16:9" => (1920, 1080),
        "1:1" => (1080, 1080),
        "4:5" => (1080, 1350),
        _ => (1080, 1920), // 9:16 と未知はこれまで通り縦型
    }
}

/// contents.json（配列・先頭がアクティブ）からキャンバス寸法を決めて反映する。
/// ドキュメントの読み込み/切替のたびに呼ぶこと（media スレッドが寸法変化を
/// 検知してコンポジタを作り直す）。
fn set_canvas_from_content(raw: &serde_json::Value) {
    let c = raw.get(0).unwrap_or(raw);
    let tl = c.get("timeline");
    let seq = tl.and_then(|t| t.get("sequence"));
    let mut w = seq.and_then(|s| s.get("width")).and_then(|v| v.as_u64()).unwrap_or(0) as u32;
    let mut h = seq.and_then(|s| s.get("height")).and_then(|v| v.as_u64()).unwrap_or(0) as u32;
    if w == 0 || h == 0 {
        let fmt = tl.and_then(|t| t.get("format")).or_else(|| seq.and_then(|s| s.get("format"))).or_else(|| c.get("format")).and_then(|v| v.as_str()).unwrap_or("9:16");
        let d = canvas_for_format(fmt);
        w = d.0;
        h = d.1;
    }
    CANVAS_DIMS.store(((w as u64) << 32) | h as u64, std::sync::atomic::Ordering::Relaxed);
}

#[derive(Clone)]
struct Req {
    t: f64,
    playing: bool,
    scrubbing: bool,
    speed: f64,
    gen: u64,
}

/// What compose does with the finished canvas.
/// `None` is the GPU-direct playback mode: the canvas is handed to the preview as
/// a texture and NEVER mapped — a dense CTA can no longer stall the media thread
/// on a readback. `Sync` stays for interactive one-shots (exact pixels now, and
/// they also feed the CPU-side debug/screenshot buffer). `Async` only serves the
/// CPU fallback when WGL interop is unavailable.
#[derive(Clone, Copy, PartialEq)]
enum Rb {
    None,
    Async,
    Sync,
}

/// A finished preview frame in flight between producer and presentation.
/// Gpu is the normal case (Arc'd pooled texture, clone = pointer copy);
/// Cpu remains for the interop-unavailable fallback and cached pixels.
#[derive(Clone)]
enum Frame {
    Gpu(Arc<gpu_present::GpuTex>),
    Cpu(Vec<u8>),
}

/// BLUR jump diagnostics: while true, compose logs the base layer's landed source frame
/// and the producer logs cache/live serve decisions (armed around ◱ interactions).
static BLUR_DBG: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

/// EXPORT mode: draw EVERY designed caption in the GPU compositor, including the ones
/// the interactive editor leaves to the WebView overlay (captions above the topmost
/// video/effect). Headless export has no WebView — without this, those captions would
/// silently vanish from the file, which was the exact user-reported bug.
static EXPORT_ALL_CAPTIONS: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

#[link(name = "user32")]
extern "system" {
    fn GetWindowLongPtrW(hwnd: isize, index: i32) -> isize;
    fn SetWindowLongPtrW(hwnd: isize, index: i32, value: isize) -> isize;
    fn GetParent(hwnd: isize) -> isize;
    fn EnumChildWindows(
        hwnd: isize,
        callback: Option<unsafe extern "system" fn(isize, isize) -> i32>,
        param: isize,
    ) -> i32;
    fn EnableWindow(hwnd: isize, enable: i32) -> i32;
}

#[cfg(target_os = "windows")]
unsafe extern "system" fn make_caption_hwnd_visual_only(hwnd: isize, _param: isize) -> i32 {
    const GWL_STYLE: i32 = -16;
    const GWL_EXSTYLE: i32 = -20;
    const WS_TABSTOP: isize = 0x0001_0000;
    const WS_EX_NOACTIVATE: isize = 0x0800_0000;
    let old = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
    SetWindowLongPtrW(hwnd, GWL_EXSTYLE, old | WS_EX_NOACTIVATE);
    // WS_EX_NOACTIVATE only covers mouse activation. WebView2 can still join the
    // keyboard tab chain while its controller is starting, starving egui of every
    // shortcut until focus returns. The caption surface has no interactive controls.
    let style = GetWindowLongPtrW(hwnd, GWL_STYLE);
    SetWindowLongPtrW(hwnd, GWL_STYLE, style & !WS_TABSTOP);
    // The caption renderer has no controls. Disabling its HWND makes Win32 skip it
    // during mouse/keyboard targeting while leaving WebView2 painting and script
    // execution intact. The egui window below is therefore the sole input owner.
    EnableWindow(hwnd, 0);
    1
}

#[cfg(target_os = "windows")]
unsafe fn make_caption_window_tree_visual_only(hwnd: isize) {
    // Eframe/winit normally clips painting beneath child HWNDs. A transparent WebView2
    // needs the parent to keep painting the video behind it (wry's wgpu example uses
    // WindowAttributesExtWindows::with_clip_children(false) for the same reason).
    const GWL_STYLE: i32 = -16;
    const WS_CLIPCHILDREN: isize = 0x0200_0000;
    let parent = GetParent(hwnd);
    if parent != 0 {
        let style = GetWindowLongPtrW(parent, GWL_STYLE);
        SetWindowLongPtrW(parent, GWL_STYLE, style & !WS_CLIPCHILDREN);
    }
    make_caption_hwnd_visual_only(hwnd, 0);
    EnumChildWindows(hwnd, Some(make_caption_hwnd_visual_only), 0);
}

struct FrameOut {
    /// GPU-direct path: the composed frame as a pooled D3D11 texture. The UI
    /// draws THIS (via WGL interop) when present; `rgba` is then only the debug/
    /// screenshot buffer of the last synchronous compose.
    tex: Option<Arc<gpu_present::GpuTex>>,
    rgba: Vec<u8>,
    seq: u64,
    t: f64,
    /// the EFFECTIVE timeline instant of the pixels (base layer's landed frame time):
    /// what the eye actually sees. Overlays that must stick to the picture (region
    /// outline, keyframe state) evaluate at THIS time, never at the request time —
    /// on VFR sources the two always differ by up to half a frame, which on fast
    /// keyed motion reads as "the frame is offset from the blur".
    eff_t: f64,
    comp_ms: f32,
    comp_max: f32,  // worst compose over the last second
    gap_max: f32,   // worst wall-clock gap between published frames (what the eye sees)
    quality: &'static str,
    /// Caption-owner generation used to compose these pixels. WebView may reveal a
    /// live caption only after this matches the current generation, preventing its
    /// new text from being drawn over an older GPU-caption frame.
    caption_epoch: u64,
}

const THUMB_BUCKET_S: f64 = 5.0; // filmstrip granularity: one real frame per 5s of source

#[derive(Clone, PartialEq)]
enum AuxJob {
    Thumb { asset_id: String, path: String, bucket: i64 },
    Peaks { asset_id: String, path: String },
}

#[derive(Default)]
struct AuxOut {
    thumbs: std::collections::HashMap<(String, i64), (usize, usize, Vec<u8>)>,
    peaks: std::collections::HashMap<String, (f64, Vec<f32>)>, // (sec/bucket, peaks)
    ver: u64,
}

struct Shared {
    // min timeline time affected by pending edits (f64 bits; INFINITY = untouched).
    // The producer consumes it to invalidate only the dirty suffix of the frame cache.
    dirty_from_bits: AtomicU64,
    caption_epoch: AtomicU64,
    req: Mutex<Req>,
    frame: Mutex<FrameOut>,
    clock_bits: AtomicU64,
    underruns: AtomicU64,
    audio_unavailable: AtomicBool,
    ring_level: std::sync::atomic::AtomicUsize,
    /// (timeline_t, effective_t of the pixels, frame)
    ring: Mutex<std::collections::VecDeque<(f64, f64, Frame)>>,
    ring_gen: AtomicU64,
    // timeline position the ring is being built FOR (f64 bits). On a mid-play seek this
    // moves to the new playhead BEFORE the clock does — audio waits on it (JUMPGATE) and
    // the presenter goes hands-off so it can't eat the rebuilt ring as "stale".
    ring_target_bits: AtomicU64,
    doc: Mutex<Arc<model::Doc>>,
    aux_req: Mutex<Vec<AuxJob>>,
    aux: Mutex<AuxOut>,
    /// Presentation texture pool, created by the media thread (it owns the D3D
    /// device). None until the engine is up.
    gpu_pool: Mutex<Option<Arc<gpu_present::TexPool>>>,
    /// Set once (by either side) when WGL interop is unusable; every producer
    /// then reverts to the CPU readback path.
    gpu_disabled: std::sync::atomic::AtomicBool,
}

/// Audio on its own thread: the WASAPI buffer is refilled no matter what the video side is
/// doing, so an expensive video seek can never make sound stutter again. Also owns the
/// master clock and restarts the stream when the playhead jumps (scrub while playing).
fn audio_thread(shared: Arc<Shared>) {
    let mut audio = audio_transport::Transport::<media::AudioOut>::new();
    let min_ready = |speed: f64| -> usize {
        if speed >= 3.0 {
            20
        } else if speed >= 1.5 {
            12
        } else {
            8
        }
    };
    let mut was_playing = false;
    let mut last_gen = u64::MAX;
    let mut last_tick = Instant::now();
    let mut last_speed = 1.0f64;
    let mut audio_error_at: Option<Instant> = None;
    loop {
        let (playing, t_req, speed, gen) = {
            let r = shared.req.lock().unwrap();
            (r.playing, r.t, r.speed, r.gen)
        };
        let doc: Arc<model::Doc> = shared.doc.lock().unwrap().clone();
        if playing != was_playing {
            if playing {
                // hold the clock until the video ring is REBUILT AT THE PLAY POSITION —
                // level alone was satisfied by leftover frames, and the 400ms cap gave up
                // exactly when a post-edit cold start needed longer (audio ran, video froze)
                let t0 = std::time::Instant::now();
                loop {
                    let rt = f64::from_bits(shared.ring_target_bits.load(Ordering::Relaxed));
                    let lvl = shared.ring_level.load(Ordering::Relaxed);
                    if ((rt - t_req).abs() < 0.5 && lvl >= min_ready(speed)) || t0.elapsed().as_millis() > 1200 {
                        break;
                    }
                    let r2 = shared.req.lock().unwrap().clone();
                    if !r2.playing {
                        break;
                    }
                    std::thread::sleep(std::time::Duration::from_millis(5));
                }
                let _ = audio.start_at(t_req, speed);
                shared.clock_bits.store(t_req.to_bits(), Ordering::Relaxed);
            } else {
                audio.stop();
            }
            was_playing = playing;
            last_gen = gen;
            last_speed = speed;
        } else if playing && gen != last_gen {
            last_gen = gen;
            let cur = f64::from_bits(shared.clock_bits.load(Ordering::Relaxed));
            if (speed - last_speed).abs() > 0.01 || (t_req - cur).abs() > 0.3 {
                // playhead jumped mid-play: WAIT for the video ring to rebuild at the new
                // position before restarting the clock (same gate as play start). Restarting
                // instantly made production chase a running clock — audio played while the
                // video froze for seconds catching up.
                let t0 = std::time::Instant::now();
                let mut aborted = false;
                loop {
                    let rt = f64::from_bits(shared.ring_target_bits.load(Ordering::Relaxed));
                    let lvl = shared.ring_level.load(Ordering::Relaxed);
                    if ((rt - t_req).abs() < 0.5 && lvl >= min_ready(speed)) || t0.elapsed().as_millis() > 900 {
                        break;
                    }
                    let r2 = shared.req.lock().unwrap().clone();
                    if r2.gen != gen || !r2.playing {
                        aborted = true; // newer seek / paused — that event drives the clock
                        break;
                    }
                    std::thread::sleep(std::time::Duration::from_millis(5));
                }
                if !aborted {
                    let _ = audio.start_at(t_req, speed);
                    shared.clock_bits.store(t_req.to_bits(), Ordering::Relaxed);
                    eprintln!(
                        "JUMPGATE {:.0}ms ring={} speed={speed:.1}x",
                        t0.elapsed().as_secs_f32() * 1000.0,
                        shared.ring_level.load(Ordering::Relaxed)
                    );
                }
            }
            last_speed = speed;
        } else if playing && (speed - last_speed).abs() > 0.01 {
            let cur = f64::from_bits(shared.clock_bits.load(Ordering::Relaxed));
            let _ = audio.start_at(cur, speed);
            last_speed = speed;
        }
        if playing {
            if let Err(err) = audio.fill(&doc, speed) {
                if audio_error_at.map(|t| t.elapsed().as_secs() >= 2).unwrap_or(true) {
                    eprintln!("AUDIO_FILL_ERROR {err:#}");
                    audio_error_at = Some(Instant::now());
                }
            } else { audio_error_at = None; }
            shared.audio_unavailable.store(audio.unavailable(), Ordering::Relaxed);
            let c = audio.clock().min(doc.duration());
            let prev = f64::from_bits(shared.clock_bits.load(Ordering::Relaxed));
            if (c - prev).abs() > 0.3 {
                eprintln!("CLOCK-JUMP {prev:.2} -> {c:.2}");
            }
            shared.clock_bits.store(c.to_bits(), Ordering::Relaxed);
            shared.underruns.store(audio.underruns, Ordering::Relaxed);
            if last_tick.elapsed().as_secs_f32() >= 5.0 {
                last_tick = Instant::now();
                let ring = shared.ring_level.load(Ordering::Relaxed);
                eprintln!("TICK t={c:.2} ring={ring} drops={}", audio.underruns);
            }
        }
        std::thread::sleep(std::time::Duration::from_millis(8));
    }
}

/// Core of the key-work clock (see App::keyed_grid_t): prefer the DISPLAYED
/// frame's slot, but when the transport playhead (`req`) sits on an existing key
/// and the displayed slot drifted off it, use the playhead's slot.
fn snap_key_slot(disp: f64, req: f64, clip_start: f64, key_times_rel: &[f64]) -> f64 {
    if (disp - req).abs() > 1e-9 {
        let on = |t: f64| {
            key_times_rel
                .iter()
                .any(|kt| (clip_start + kt - t).abs() <= edits::KEY_REPLACE_EPS)
        };
        if on(req) && !on(disp) {
            return req;
        }
    }
    disp
}

#[cfg(test)]
mod key_slot_tests {
    use super::snap_key_slot;
    const F: f64 = 1.0 / 30.0; // one 30fps frame

    #[test]
    fn playhead_on_key_wins_over_drifted_display_slot() {
        // The bug: head ON key K, but the displayed slot rounded one frame早く →
        // the write minted a new key at K-1F. It must edit K instead.
        let k = 10.0 + 15.0 * F; // key at clip-relative 15 frames (clip starts at 10s)
        assert_eq!(snap_key_slot(k - F, k, 10.0, &[15.0 * F]), k);
    }

    #[test]
    fn off_key_keeps_the_picture_glued_display_slot() {
        let t = 10.0 + 15.0 * F;
        assert_eq!(snap_key_slot(t - F, t, 10.0, &[]), t - F);
        // and when the DISPLAYED slot itself is on a key, it already replaces it
        assert_eq!(snap_key_slot(t - F, t, 10.0, &[14.0 * F]), t - F);
    }

    #[test]
    fn deliberate_neighbour_frame_key_still_possible() {
        // head one frame BEFORE key K (both slots agree) → new key at K-1F is intended
        let k = 10.0 + 15.0 * F;
        assert_eq!(snap_key_slot(k - F, k - F, 10.0, &[15.0 * F]), k - F);
    }
}

#[derive(Clone, PartialEq)]
enum Drag {
    None,
    Scrub,
    Move { ids: Vec<String>, anchor_id: String, grab: f64, orig: f64, applied: f64 },
    Trim { ids: Vec<String>, left: bool, last_t: f64 },
    // anchor_t is a TIMELINE time (not a screen x): edge auto-scroll moves the view
    // under a held marquee, so a screen-space anchor would slide along the timeline.
    Marquee { anchor_t: f64, anchor_y: f32 },
    Volume { ids: Vec<String>, start_y: f32, start_vol: f64 },
}

/// Olive-style composed-frame cache: finished timeline frames on the selected sequence
/// grid, LZ4-compressed in RAM. Scrub/jump/playback over cached spans just decompress
/// (~3-6ms) instead of composing (30-100ms+). Conservative correctness: ANY document edit
/// clears the whole cache — a stale frame is structurally impossible. Filled during
/// paused idle (playhead outward) and opportunistically from playback production.
struct FrameCache {
    // key: sequence-frame bucket; value: (EXACT compose time, lz4 pixels). The exact time is the
    // honesty check: a bucket can span more than one source frame — and
    // serving "whatever the bucket holds" showed the NEIGHBOUR frame when a paused
    // inspection landed 12ms away from the cached compose (the freeze-boundary bug the
    // dump-frame verification missed because it bypasses this cache).
    frames: std::collections::HashMap<i64, (f64, f64, Vec<u8>)>, // (exact_t, eff_t, lz4)
    bytes: usize,
    budget: usize,
    max_frames: usize,
    hits: u64,
    misses: u64,
}

impl FrameCache {
    fn new() -> Self {
        Self {
            frames: Default::default(),
            bytes: 0,
            // Keep the preview working set bounded. The old 2.5GB cache was the main
            // reason a normal editing session became progressively heavier.
            budget: 384 * 1024 * 1024,
            max_frames: 180,
            hits: 0,
            misses: 0,
        }
    }
    fn idx(t: f64, fps: f64) -> i64 {
        (t * fps).round() as i64
    }
    fn clear(&mut self) {
        self.frames.clear();
        self.bytes = 0;
    }
    /// Drop only frames at/after `t` — an edit at 60s must not throw away the first
    /// minute of finished frames (the whole-cache clear was the post-edit heaviness).
    fn invalidate_from(&mut self, t: f64, fps: f64) {
        let cut = Self::idx(t, fps) - 1;
        let dead: Vec<i64> = self.frames.keys().copied().filter(|k| *k >= cut).collect();
        for k in dead {
            if let Some((_, _, z)) = self.frames.remove(&k) {
                self.bytes -= z.len();
            }
        }
    }
    /// Serve only when the cached pixels were composed within `tol` seconds of `t`.
    /// Playback reuse passes a whole tick (~17ms); paused/scrub inspection passes 5ms
    /// so a neighbouring source frame can never impersonate the requested one.
    /// On hit returns the pixels' EFFECTIVE time (see FrameOut::eff_t).
    fn get(&mut self, t: f64, fps: f64, tol: f64, out: &mut Vec<u8>) -> Option<f64> {
        if let Some((ct, eff, z)) = self.frames.get(&Self::idx(t, fps)) {
            if (ct - t).abs() <= tol {
                if let Ok(raw) = lz4_flex::decompress_size_prepended(z) {
                    out.clear();
                    out.extend_from_slice(&raw);
                    self.hits += 1;
                    return Some(*eff);
                }
            }
        }
        self.misses += 1;
        None
    }
    fn contains(&self, t: f64, fps: f64) -> bool {
        self.frames.contains_key(&Self::idx(t, fps))
    }
    fn insert(&mut self, t: f64, fps: f64, eff: f64, rgba: &[u8], playhead: f64) {
        let key = Self::idx(t, fps);
        if self.frames.contains_key(&key) {
            return;
        }
        let z = lz4_flex::compress_prepend_size(rgba);
        self.bytes += z.len();
        self.frames.insert(key, (t, eff, z));
        // over budget: evict farthest-from-playhead first
        while self.bytes > self.budget || self.frames.len() > self.max_frames {
            let ph = Self::idx(playhead, fps);
            let Some((&far, _)) = self.frames.iter().max_by_key(|(k, _)| (**k - ph).abs()) else {
                break;
            };
            if let Some((_, _, z)) = self.frames.remove(&far) {
                self.bytes -= z.len();
            }
        }
    }
}

#[cfg(test)]
mod frame_cache_stability_tests {
    use super::FrameCache;

    #[test]
    fn cache_never_exceeds_frame_or_byte_limits() {
        let mut cache = FrameCache::new();
        cache.max_frames = 8;
        cache.budget = 512;
        for i in 0..100 {
            let pixels: Vec<u8> = (0..1024).map(|n| (n as u8).wrapping_add(i as u8)).collect();
            cache.insert(i as f64 / 30.0, 30.0, i as f64 / 30.0, &pixels, 0.0);
            assert!(cache.frames.len() <= cache.max_frames);
            assert!(cache.bytes <= cache.budget);
        }
    }
}

/// asset_id -> source-frame pts table ({asset}_proxy.pts.json, written at proxy encode).
/// The settle/produce path snaps source times to the NEAREST real frame start so a scrub
/// on the CFR proxy and its settle on the (possibly VFR) original show the same picture.
type PtsMap = std::collections::HashMap<String, Option<std::sync::Arc<Vec<f64>>>>;

/// Load ONE missing pts table per idle slice (a 43k-frame table parses in ~50ms).
fn pts_load_pass(doc: &model::Doc, maps: &mut PtsMap) -> bool {
    for tr in &doc.seq.tracks {
        if tr.kind == "audio" {
            continue;
        }
        for c in &tr.clips {
            let Some(aid) = c.asset_id.as_deref() else { continue };
            if maps.contains_key(aid) {
                continue;
            }
            let p = format!("{}/{}_proxy.pts.json", doc.asset_dir, aid);
            let loaded = std::fs::read_to_string(&p)
                .ok()
                .and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok())
                .and_then(|v| {
                    let pts: Vec<f64> = v
                        .get("pts")?
                        .as_array()?
                        .iter()
                        .filter_map(|x| x.as_f64())
                        .collect();
                    (pts.len() > 1).then(|| std::sync::Arc::new(pts))
                });
            let had = loaded.is_some();
            maps.insert(aid.to_string(), loaded);
            if had {
                return true; // one parse per slice
            }
        }
    }
    false
}

/// Snap a source time to the nearest real frame start (+tiny epsilon so the decoder's
/// "newest frame <= t" lands exactly on it).
fn snap_src_t(maps: &PtsMap, asset_id: &str, src_t: f64) -> f64 {
    let Some(Some(pts)) = maps.get(asset_id) else { return src_t };
    let i = pts.partition_point(|p| *p <= src_t);
    let lo = if i > 0 { pts[i - 1] } else { pts[0] };
    let hi = *pts.get(i).unwrap_or(&lo);
    let chosen = if (src_t - lo).abs() <= (hi - src_t).abs() { lo } else { hi };
    chosen + 0.0002
}

/// key -> Some((bake meta, static card-mask texture)) when the LIVE matte path is usable,
/// None when this key has no matte twin (v6 bake) and stays on the pv fallback.
type MaskMap = std::collections::HashMap<
    String,
    Option<(model::PopMeta, windows::Win32::Graphics::Direct3D11::ID3D11Texture2D)>,
>;

// mt.mp4 mux order is [person α, shadow base] but MF enumerates the two video tracks in
// REVERSE mux order (same quirk as the pv twin) — verified visually.
const MT_PERSON: u32 = 1;
const MT_SHADOW: u32 = 0;

/// Build ONE missing pop-out mask texture per call (the σ26 blur costs ~0.3s — idle only).
/// v6 keys (no matte twin on disk) are memoized as None and stay on the pv fallback for
/// this session; the effect-clip migration re-keys everything anyway.
fn mask_build_pass(
    doc: &model::Doc,
    d3d: &media::D3d,
    masks: &mut MaskMap,
    center: Option<f64>,
) -> bool {
    // Matte textures are several MB each. Keep only the playhead working set in the
    // interactive editor; command-line verification can pass None to scan everything.
    if let Some(t) = center {
        let wanted: std::collections::HashSet<String> = doc
            .seq
            .tracks
            .iter()
            .flat_map(|tr| tr.clips.iter())
            .filter(|c| c.timeline_end >= t - 3.0 && c.timeline_start <= t + 12.0)
            .filter_map(|c| c.popout_key().map(|(key, _)| key))
            .collect();
        masks.retain(|key, _| wanted.contains(key));
    }
    for tr in &doc.seq.tracks {
        if tr.kind == "audio" {
            continue;
        }
        for c in &tr.clips {
            if center
                .map(|t| c.timeline_end < t - 3.0 || c.timeline_start > t + 12.0)
                .unwrap_or(false)
            {
                continue;
            }
            let Some((key, _)) = c.popout_key() else { continue };
            let mt = doc.rel_path(&format!("popout-cache/{key}.mt.mp4"));
            if let Some(entry) = masks.get(&key) {
                // None = matte twin wasn't on disk earlier; a bake may have finished
                // since — pick it up in-session (no restart needed)
                if entry.is_some() || !std::path::Path::new(&mt).exists() {
                    continue;
                }
            }
            let meta = if std::path::Path::new(&mt).exists() {
                model::PopMeta::load(&doc.rel_path(&format!("popout-cache/{key}.json")))
            } else {
                None
            };
            let Some(meta) = meta else {
                masks.insert(key, None);
                continue;
            };
            match compositor::Compositor::build_popout_mask(d3d, &meta) {
                Ok(tex) => {
                    eprintln!("mask built {key} {}x{}", meta.canvas[0], meta.canvas[1]);
                    masks.insert(key, Some((meta, tex)));
                }
                Err(e) => {
                    eprintln!("mask build {key}: {e:#}");
                    masks.insert(key, None);
                }
            }
            return true; // one per idle slice
        }
    }
    false
}

/// Draw a person clip as a PLAIN PiP at the card box — the stand-in whenever the baked
/// pop-out isn't usable (still baking, or the cache file is broken).
#[allow(clippy::too_many_arguments)]
fn draw_plain_pip(
    doc: &model::Doc,
    d3d: &media::D3d,
    pool: &mut media::VideoPool,
    comp: &mut compositor::Compositor,
    c: &model::Clip,
    b: model::Pos,
    t: f64,
    original: bool,
    fast: bool,
) -> anyhow::Result<Option<String>> {
    let Some(aid) = c.asset_id.as_deref() else { return Ok(None) };
    let bb = c.popout_card_box().unwrap_or(b);
    let p2 = doc.asset_path_q(aid, original);
    let src_t = c.src_at(t);
    if c.is_freeze() {
        // freeze PiP: asset-keyed still, baked only from an exact ORIGINAL decode
        let key = (format!("fz:{aid}"), (src_t * 1000.0).round() as i64);
        let _ = load_freeze_png(doc, d3d, comp, c, &key);
        let got = comp.still_get(&key);
        let (tex, wh) = if let Some(x) = got {
            x
        } else {
            fz_log(&format!("FZ_FALLBACK pip id={} t={t:.2} fast={fast}", c.id));
            let vs = pool.get(d3d, &p2, 0, false, src_t)?;
            let is_exact = if fast {
                vs.ensure_frame_scrub(d3d, src_t, 12.0)?;
                false
            } else {
                vs.ensure_frame(d3d, src_t)?;
                true
            };
            let tw = (vs.bgra.clone(), (vs.width, vs.height));
            if is_exact {
                comp.still_put(d3d, key, &tw.0, tw.1)?;
            }
            tw
        };
        comp.set_grade(grade_params(c));
        comp.draw_cropped_opacity(d3d, &tex, wh, (bb.x, bb.y, bb.width, bb.height), !c.stretches_to_box(), None, c.crop_ltrb_at(t), c.visual_opacity())?;
        return Ok(None);
    }
    let vs = pool.get(d3d, &p2, 0, false, src_t)?;
    if fast {
        let _ = vs.ensure_frame_scrub(d3d, src_t, 12.0)?;
    } else {
        vs.ensure_frame(d3d, src_t)
            .map_err(|e| e.context(format!("plain-pip {} src_t={src_t:.2}", vs.name)))?;
    }
    let (tex, wh) = (vs.bgra.clone(), (vs.width, vs.height));
    comp.set_grade(grade_params(c));
    comp.draw_cropped_opacity(d3d, &tex, wh, (bb.x, bb.y, bb.width, bb.height), !c.stretches_to_box(), None, c.crop_ltrb_at(t), c.visual_opacity())?;
    Ok(Some(p2))
}

/// Fit the complete source into a timeline box without cropping or distortion.
/// Coordinates are normalized to the fixed preview canvas, whose pixels are not
/// square in normalized space for portrait projects.
fn contain_box(
    dst: (f64, f64, f64, f64),
    src_wh: (u32, u32),
) -> (f64, f64, f64, f64) {
    if src_wh.0 == 0 || src_wh.1 == 0 || dst.2 <= 0.0 || dst.3 <= 0.0 {
        return dst;
    }
    let (bw, bh) = (dst.2 * canvas_w() as f64, dst.3 * canvas_h() as f64);
    let scale = (bw / src_wh.0 as f64).min(bh / src_wh.1 as f64);
    let (dw, dh) = (
        (src_wh.0 as f64 * scale) / canvas_w() as f64,
        (src_wh.1 as f64 * scale) / canvas_h() as f64,
    );
    (dst.0 + (dst.2 - dw) / 2.0, dst.1 + (dst.3 - dh) / 2.0, dw, dh)
}

/// クリップの実効表示箱。contain クリップは素材実寸のアスペクトそのままの箱になる。
/// 選択枠・ドラッグ・ジオメトリ写像・描画のすべてがこの箱を使うことで、キャンバスが
/// どの形でも素材の形が保たれる（余白はクリップの一部ではない）。箱アスペクト==素材
/// アスペクトになるため、下流の cover/contain 計算は恒等になり既存の写像は壊れない。
fn effective_box(doc: &model::Doc, c: &model::Clip, t: f64) -> model::Pos {
    let b = c.display_box_at(t);
    if !c.contains_in_box() {
        return b;
    }
    let Some(aid) = c.asset_id.as_deref() else { return b };
    let dims = doc.asset_dims.get(aid).copied().unwrap_or((0, 0));
    let (x, y, w, h) = contain_box((b.x, b.y, b.width, b.height), dims);
    model::Pos { x, y, width: w, height: h }
}

/// Throttled diagnostics for the freeze paths (at most one line per 500ms) — cheap
/// enough to stay on permanently; %TEMP%/native_ui.log captures real user sessions.
/// Within ±1.2s of any freeze clip (diagnostic scope guard).
fn near_freeze(doc: &model::Doc, t: f64) -> bool {
    doc.seq
        .tracks
        .iter()
        .flat_map(|tr| tr.clips.iter())
        .filter(|c| c.is_freeze())
        .any(|c| t > c.timeline_start - 1.2 && t < c.timeline_end + 1.2)
}

// ---------------- frame-accurate stepping ----------------
// Arrow keys move by SOURCE frames of the clip under the playhead, landing on frame
// MIDPOINTS. The old global 1/30 grid skipped/repeated frames whenever a clip start
// drifted off-grid (every ripple edit does that), and could never land on a frame that
// occupies less than one grid cell — e.g. the freeze contract's "right clip starts on
// the displayed frame" window (measured: the first grid point after a freeze jumped
// straight to the SECOND frame of the continuation).

type PtsCache = std::collections::HashMap<String, Option<std::sync::Arc<Vec<f64>>>>;

fn cached_pts(doc: &model::Doc, cache: &mut PtsCache, aid: &str) -> Option<std::sync::Arc<Vec<f64>>> {
    if let Some(hit) = cache.get(aid) {
        return hit.clone();
    }
    let load = || -> Option<Vec<f64>> {
        let p = format!("{}/{aid}_proxy.pts.json", doc.asset_dir);
        let txt = std::fs::read_to_string(p).ok()?;
        let v: serde_json::Value = serde_json::from_str(&txt).ok()?;
        let pts: Vec<f64> = v.get("pts")?.as_array()?.iter().filter_map(|x| x.as_f64()).collect();
        (!pts.is_empty()).then_some(pts)
    };
    let arc = load().map(std::sync::Arc::new);
    cache.insert(aid.to_string(), arc.clone());
    arc
}

/// The frame index the engine DISPLAYS for `src` (nearest pts — measured semantics).
fn nearest_idx(pts: &[f64], src: f64) -> usize {
    let i = pts.partition_point(|p| *p <= src);
    if i == 0 {
        return 0;
    }
    if i >= pts.len() {
        return pts.len() - 1;
    }
    if (src - pts[i - 1]).abs() <= (pts[i] - src).abs() { i - 1 } else { i }
}

fn local_fd(pts: &[f64], k: usize) -> f64 {
    pts.get(k + 1)
        .map(|n| n - pts[k])
        .filter(|d| *d > 1e-4 && *d < 1.0)
        .or_else(|| (k > 0).then(|| pts[k] - pts[k - 1]).filter(|d| *d > 1e-4 && *d < 1.0))
        .unwrap_or(1.0 / 30.0)
}

/// Landing point inside frame `k`: 30% past its pts. NOT the midpoint — the midpoint
/// is EQUIDISTANT between neighbouring pts, so nearest-frame display becomes a float
/// coin-flip (measured: landing dead-center showed the NEXT frame). 30% is decisively
/// inside for both nearest and floor semantics.
fn frame_mid(pts: &[f64], k: usize) -> Option<f64> {
    let p = *pts.get(k)?;
    Some(p + 0.3 * local_fd(pts, k))
}

/// First (dir>0) or last (dir<0) frame whose MIDPOINT falls inside the clip starting/
/// ending at source time `src_edge` — i.e. frames actually shown for at least half
/// their duration. Robust against 3dp-rounded source fields sitting a hair off a pts.
fn edge_frame(pts: &[f64], src_edge: f64, dir: f64) -> usize {
    let mut k = nearest_idx(pts, src_edge);
    if dir > 0.0 {
        while k + 1 < pts.len() && frame_mid(pts, k).unwrap_or(f64::MAX) < src_edge {
            k += 1;
        }
    } else {
        while k > 0 && frame_mid(pts, k).unwrap_or(f64::MIN) > src_edge {
            k -= 1;
        }
    }
    k
}

/// The clip whose frames stepping follows: first non-audio lane, asset-bearing.
fn step_clip_under(doc: &model::Doc, t: f64) -> Option<model::Clip> {
    doc.seq
        .tracks
        .iter()
        .filter(|tr| tr.kind != "audio")
        .flat_map(|tr| tr.clips.iter())
        .find(|c| c.asset_id.is_some() && t >= c.timeline_start - 1e-9 && t < c.timeline_end - 1e-9)
        .cloned()
}

/// Land just inside `edge` (in step direction `dir`) on a WHOLE frame midpoint.
fn step_enter(doc: &model::Doc, cache: &mut PtsCache, edge: f64, dir: f64) -> Option<f64> {
    let c = step_clip_under(doc, edge + dir * 1e-4)?;
    if c.is_freeze() {
        // a still: any point shows the same picture — sit just inside the boundary
        return Some(if dir > 0.0 {
            (edge + 0.01).min(c.timeline_end - 1e-3)
        } else {
            (edge - 0.01).max(c.timeline_start)
        });
    }
    let aid = c.asset_id.clone()?;
    let pts = cached_pts(doc, cache, &aid)?;
    let src_edge = c.src_at(edge.clamp(c.timeline_start, c.timeline_end));
    let k = edge_frame(&pts, src_edge, dir);
    let nt = c.t_at_src(frame_mid(&pts, k)?);
    Some(nt.clamp(c.timeline_start, (c.timeline_end - 1e-3).max(c.timeline_start)))
}

/// Where one frame-step from `t` lands. None = no clip/sidecar (caller grid-steps).
fn step_target(doc: &model::Doc, cache: &mut PtsCache, t: f64, dir: f64) -> Option<f64> {
    const G: f64 = 1.0 / 30.0;
    let c = step_clip_under(doc, t)?;
    if c.is_freeze() {
        // inside the still the picture never changes: step the timeline grid, and hop
        // onto the neighbour clip's first/last whole frame when crossing out
        let grid = (t / G).round() * G + dir * G;
        if dir > 0.0 && grid >= c.timeline_end - 1e-9 {
            return step_enter(doc, cache, c.timeline_end, 1.0);
        }
        if dir < 0.0 && grid < c.timeline_start {
            return step_enter(doc, cache, c.timeline_start, -1.0);
        }
        return Some(grid);
    }
    let aid = c.asset_id.clone()?;
    let pts = cached_pts(doc, cache, &aid)?;
    let src = c.src_at(t);
    let k2 = nearest_idx(&pts, src) as i64 + dir as i64;
    if k2 < 0 {
        return step_enter(doc, cache, c.timeline_start, -1.0);
    }
    let nt = c.t_at_src(frame_mid(&pts, k2 as usize)?);
    if nt >= c.timeline_end - 1e-6 {
        return step_enter(doc, cache, c.timeline_end, 1.0);
    }
    if nt < c.timeline_start {
        return step_enter(doc, cache, c.timeline_start, -1.0);
    }
    Some(nt)
}

fn fz_log(msg: &str) {
    thread_local! {
        static LAST: std::cell::Cell<Option<std::time::Instant>> = const { std::cell::Cell::new(None) };
    }
    LAST.with(|l| {
        let now = std::time::Instant::now();
        if l.get().map(|p| now.duration_since(p).as_millis() > 500).unwrap_or(true) {
            l.set(Some(now));
            eprintln!("{msg}");
        }
    });
}

/// Load a freeze clip's materialized PNG into the still cache (once). Returns whether
/// the still is now available under `key`.
fn load_freeze_png(
    doc: &model::Doc,
    d3d: &media::D3d,
    comp: &compositor::Compositor,
    c: &model::Clip,
    key: &(String, i64),
) -> bool {
    if comp.still_get(key).is_some() {
        return true;
    }
    let Some(rel) = c.freeze_still.as_deref() else { return false };
    let p = doc.rel_path(rel);
    let Ok(bytes) = std::fs::read(&p) else {
        fz_log(&format!("FZ_WAIT png-not-ready {rel}"));
        return false;
    };
    let t0 = std::time::Instant::now();
    let Ok(img) = image::load_from_memory(&bytes) else {
        fz_log(&format!("FZ_ERR png-decode-failed {rel}"));
        return false;
    };
    // Normalize to the PROXY resolution (long side 1920): playback neighbours are proxy
    // frames, so a 4K still made the seam jump in sharpness (measured: proxy-dec
    // 1080x1920 -> png 2160x3840, identical boxes). Same size = seam is invisible.
    // Bonus: 33MB -> 8MB VRAM per still.
    let (ow, oh) = (img.width(), img.height());
    let long = ow.max(oh);
    let img = if long > 1920 {
        let sc = 1920.0 / long as f32;
        img.resize(
            ((ow as f32 * sc).round() as u32).max(2),
            ((oh as f32 * sc).round() as u32).max(2),
            image::imageops::FilterType::CatmullRom,
        )
    } else {
        img
    };
    let rgba = img.to_rgba8();
    let (w, h) = (rgba.width(), rgba.height());
    let ok = comp.still_put_rgba(d3d, key.clone(), w, h, rgba.as_raw()).is_ok();
    eprintln!(
        "STILL_LOAD {}ms {rel} {ow}x{oh}->{w}x{h} ok={ok}",
        t0.elapsed().as_millis()
    );
    ok
}

fn compose(
    doc: &model::Doc,
    d3d: &media::D3d,
    pool: &mut media::VideoPool,
    comp: &mut compositor::Compositor,
    masks: &MaskMap,
    pts_maps: &PtsMap,
    t: f64,
    original: bool,
    fast: bool, // scrub: budgeted seek — newest reachable frame now, exact frame on settle
    rb: Rb,     // what to do with the finished canvas (GPU handoff / async / sync readback)
) -> anyhow::Result<(Vec<String>, bool, f64)> { // (used files, exact?, EFFECTIVE time of the pixels)
    pool.frame_no += 1;
    let mut used = Vec::new();
    let mut exact = true; // false while any budgeted scrub seek stopped short of t
    // ONE z-ordered draw list: lane array order = stacking (0 = backmost), within a lane
    // the clip order. Videos, region effects AND designed captions all live in it — the
    // lane rule "上にあるものが前面" holds across kinds, not just among videos. A region
    // effect processes exactly the composite BELOW its lane; captions above the topmost
    // video/effect stay in the WebView overlay (live animation), the rest draw here.
    const Z_VIDEO: u8 = 0;
    const Z_FX: u8 = 1;
    const Z_CAP: u8 = 2;
    let layers: Vec<(u8, model::Clip)> = {
        let mut out = Vec::new();
        for tr in doc.seq.tracks.iter().filter(|tr| tr.kind != "audio" && !tr.hidden) {
            for c in &tr.clips {
                if !doc.clip_active_at(c, t) {
                    continue;
                }
                if c.asset_id.is_some() {
                    if c.is_video_enabled() {
                        out.push((Z_VIDEO, c.clone()));
                    }
                } else if c.region.is_some() {
                    if c.style.as_ref().and_then(|v| v.as_str()) != Some("note") {
                        out.push((Z_FX, c.clone()));
                    }
                } else if c.text.as_deref().map(|s| !s.trim().is_empty()).unwrap_or(false) {
                    out.push((Z_CAP, c.clone()));
                }
            }
        }
        out
    };
    let native_caps = native_caption_ids(doc, t);
    // The timeline moment the BASE video layer actually landed on (budgeted scrub
    // seeks may stop a frame short of t). Region effects evaluate their keyframes at
    // THIS time so the blur stays glued to the picture that is really on screen —
    // "video one frame behind, blur at the new spot" was the momentary uncover.
    let base_id = doc.active_video(t).0.map(|b| b.id.clone());
    let mut base_eff_t: Option<f64> = None;
    let _t_begin = Instant::now();
    comp.begin(d3d);
    let _ms_base = 0f64;
    let mut _ms_ov = 0f64;
    // scrub deadline: the FULLSCREEN base updates every tick (that's what the eye tracks
    // while whipping); decorations (pop-out person / mattes) update only while the tick
    // budget lasts and land exactly at rest via the refine loop — original pixels always,
    // never a proxy
    let f_deadline = Instant::now() + std::time::Duration::from_millis(30);
    // Geometry clock for transform keyframes (display box / crop): the request time
    // QUANTIZED to the sequence grid — the same slot value keyframe WRITES use, so a
    // key's frame shows exactly the key's value (region_keys use the same rule below).
    let gfps = doc.seq.frame_rate.filter(|f| f.is_finite() && *f > 1.0).unwrap_or(30.0);
    let t_geo = (t * gfps).round() / gfps;
    // Interactive seeks request an exact synchronous readback. Playback deliberately
    // does not: forcing a GPU readback for every video/text/image edge stalls the media
    // thread, and a dense CTA can otherwise stop transport altogether.
    // seam diagnostics: within ±0.6s of a freeze boundary, log exactly what every layer
    // draws (texture size / quality / box) — the ground truth for the "width grows" report
    let near_fz = doc
        .seq
        .tracks
        .iter()
        .flat_map(|tr| tr.clips.iter())
        .filter(|c| c.is_freeze())
        .any(|c| (t - c.timeline_start).abs() < 0.6 || (t - c.timeline_end).abs() < 0.6);
    let _t = Instant::now();
    for (zk, c) in &layers {
        if *zk == Z_FX {
            // region effect (blur/mosaic): processes the composite BELOW this lane.
            // Keyframed rects follow the DISPLAYED base frame's time (base_eff_t), not
            // the request time — glued to the picture during budgeted scrubs — and are
            // QUANTIZED to the sequence grid (same slot value keyframe WRITES use).
            let t_fx = (base_eff_t.unwrap_or(t) * gfps).round() / gfps;
            if let Some(rg) = c.region_at(t_fx) {
                let style = c.style.as_ref().and_then(|v| v.as_str()).unwrap_or("");
                let is_mosaic = style.contains("mosaic");
                let is_solid = style == "solid";
                let strength = c.effect_strength.unwrap_or(if is_mosaic { 14.0 } else { 16.0 }).clamp(2.0, 64.0);
                let opacity = c.effect_opacity.unwrap_or(1.0).clamp(0.0, 1.0);
                let solid = effect_rgb(c.effect_color.as_deref().unwrap_or("#000000"));
                // SAM tracked blur: the baked mask video follows the object; until the
                // bake lands (or outside its window) the static stand-in below applies.
                let mut applied = false;
                if let Some(bt) = c.blur_track.as_ref() {
                    let key = bt.get("key").and_then(|v| v.as_str()).unwrap_or("");
                    let bs = bt.get("bake_start").and_then(|v| v.as_f64()).unwrap_or(0.0);
                    let be = bt.get("bake_end").and_then(|v| v.as_f64()).unwrap_or(f64::MAX);
                    let baid = bt.get("asset_id").and_then(|v| v.as_str()).unwrap_or("");
                    let mpath = doc.rel_path(&format!("blur-cache/{key}.mask.mp4"));
                    let base_info = doc
                        .active_video(t)
                        .0
                        .filter(|b| b.asset_id.as_deref() == Some(baid))
                        .map(|b| (b.src_at(t), effective_box(doc, b, t_fx), b.crop_ltrb_at(t_fx)));
                    let mask_ok = !key.is_empty()
                        && std::fs::metadata(&mpath).map(|m| m.len() > 0).unwrap_or(false);
                    if let (Some((src_t, bb, bcrop)), true) = (base_info, mask_ok) {
                        let in_window = src_t >= bs - 0.05 && src_t <= be + 0.05;
                        let mt = (src_t - bs).max(0.0);
                        if !in_window {
                            // fall through to the static stand-in below
                        } else if let Ok(vs) = pool.get(d3d, &mpath, 0, false, mt) {
                            let ok = if fast {
                                if Instant::now() < f_deadline {
                                    vs.ensure_frame_scrub(d3d, mt, 8.0).unwrap_or(false)
                                } else {
                                    false
                                }
                            } else {
                                vs.ensure_frame(d3d, mt).is_ok()
                            };
                            if !ok {
                                exact = false; // settle pass will land the exact mask frame
                            }
                            if BLUR_DBG.load(Ordering::Relaxed) {
                                eprintln!(
                                    "BLURMASK t={t:.3} clip={} req_mt={mt:.3} landed={:.3} ok={ok} fast={fast} (mask_frame≈{})",
                                    c.id,
                                    vs.shown_pts(),
                                    (vs.shown_pts() * 30.0).round() as i64
                                );
                            }
                            // draw with the decoder's LAST frame even when the budgeted
                            // seek missed: a frame-stale tracked mask beats flashing to
                            // the static stand-in
                            let tex = vs.bgra.clone();
                            let wh = (vs.width, vs.height);
                            let rendered = if is_solid {
                                comp.apply_solid_masked(d3d, &tex, wh, (bb.x, bb.y, bb.width, bb.height), bcrop, solid, opacity)
                            } else {
                                comp.apply_blur_masked(d3d, &tex, wh, (bb.x, bb.y, bb.width, bb.height), bcrop, strength)
                            };
                            if rendered.is_ok() {
                                applied = true;
                                used.push(mpath);
                            }
                        }
                    }
                }
                if !applied {
                    // a clip WITH a tracked bake never shows the blocky grid: style only
                    // picks the look for pure static region clips
                    if style == "spotlight" {
                        // 注目演出: 範囲以外を沈める。不透明度スライダーが沈み量
                        let _ = comp.apply_spotlight(d3d, rg, 1.0 - 0.55 * opacity);
                    } else if style == "marker" {
                        let _ = comp.apply_marker(d3d, rg, opacity);
                    } else if style == "frame" {
                        // 矩形枠: 囲むだけで周囲を暗くしない。マーカー/スポットの
                        // 重ね掛けで注目以外がどんどん沈む問題への答え（同一シーンで
                        // 複数箇所を目立たせる用途）。solid の帯4本＝新シェーダ不要
                        let (x, y, w, h) = rg;
                        let t = c.effect_strength.unwrap_or(4.0).clamp(1.0, 24.0) / canvas_h() as f64;
                        let tx = t * canvas_h() as f64 / canvas_w() as f64;
                        let fcol = effect_rgb(c.effect_color.as_deref().unwrap_or("#ffe14d"));
                        // 回転は枠全体の中心を共通pivotに（帯4本がバラけないように）
                        let rot = c.effect_rot.unwrap_or(0.0);
                        let pivot = (x + w * 0.5, y + h * 0.5);
                        for s in [
                            (x - tx, y - t, w + 2.0 * tx, t),
                            (x - tx, y + h, w + 2.0 * tx, t),
                            (x - tx, y, tx, h),
                            (x + w, y, tx, h),
                        ] {
                            let _ = comp.apply_solid_rect_rot(d3d, s, fcol, opacity, rot, pivot);
                        }
                    } else if style == "zoom" {
                        let z = c.effect_strength.unwrap_or(1.6).clamp(1.1, 3.0);
                        let _ = comp.apply_zoom(d3d, rg, z);
                    } else if is_mosaic && c.blur_track.is_none() {
                        let _ = comp.apply_mosaic(d3d, rg, strength);
                    } else if is_solid {
                        let rot = c.effect_rot.unwrap_or(0.0);
                        let pivot = (rg.0 + rg.2 * 0.5, rg.1 + rg.3 * 0.5);
                        let _ = comp.apply_solid_rect_rot(d3d, rg, solid, opacity, rot, pivot);
                    } else {
                        let _ = comp.apply_blur_rect(d3d, rg, strength, c.effect_rot.unwrap_or(0.0));
                    }
                }
            }
            continue;
        }
        if *zk == Z_CAP {
            // designed caption at its LANE position. Texture = the same /caption-frame
            // PNG the export burns (caption-cache, rendered at the DEFAULT anchor with
            // x/y stripped): shift the full-canvas quad by the live style offsets — the
            // canvas edge crops exactly like the renderer's overflow:hidden. Captions
            // ABOVE every video/effect are not in native_caps: the WebView draws them
            // live (animation intact) on its always-on-top plane.
            if !native_caps.contains(&c.id) {
                continue;
            }
            let text = c.text.clone().unwrap_or_default();
            let style_owned = c.style.clone().unwrap_or_else(|| serde_json::json!({}));
            let key = caption_cache_key(c, &text, &style_owned);
            // Caption PNGs are scene resources, not transient stills. Keeping them in
            // the generic 24-entry still cache made a dense timeline evict/reload the
            // CTA caption on every pass (disk decode + CPU BGRA swizzle + GPU upload).
            // Their dedicated cache is keyed by caption content/style and survives
            // unrelated freeze/image work.
            if comp.caption_get(&key).is_none() {
                let png = std::path::Path::new(&doc.asset_dir)
                    .join("caption-cache")
                    .join(format!("{key}.png"));
                match std::fs::read(&png).ok().and_then(|b| image::load_from_memory(&b).ok()) {
                    Some(img) => {
                        let rgba = img.to_rgba8();
                        let (w, h) = (rgba.width(), rgba.height());
                        let _ = comp.caption_put_rgba(
                            d3d, key.clone(), &c.id, w, h, rgba.as_raw(),
                            (0.0, 0.0, 1.0, 1.0), caption_style_num(&style_owned, "fontSize", 1.0),
                        );
                    }
                    None => {
                        // PNG not rendered yet (caption_cache_pass fills it in the
                        // background) — native_caption_ids keeps such captions in the
                        // WebView, so this is just belt-and-braces
                        exact = false;
                    }
                }
            }
            if let Some((tex, wh, _, _)) = comp.caption_get(&key) {
                let xf = caption_style_num(&style_owned, "x", 0.0);
                let yf = caption_style_num(&style_owned, "y", 0.08).clamp(0.0, 0.92);
                let dst = c.caption_box_at(t_geo, (xf, 0.08 - yf, 1.0, 1.0));
                let _ = comp.draw_alpha_opacity(d3d, &tex, wh, dst, c.visual_opacity());
            }
            continue;
        }
        let b = effective_box(doc, c, t_geo);
        if let Some((key, off)) = c.popout_key() {
            // LIVE matte path: color sampled from the ORIGINAL frame — the same file and
            // the same src_t the AUDIO plays, so lips can't drift. The baked pv (30fps
            // re-encode, ~17ms staler) remains the fallback while no matte twin exists.
            let live = masks.get(&key).and_then(|o| o.clone());
            if let (Some((meta, mask)), Some(aid)) = (live, c.asset_id.as_deref()) {
                let opath = doc.asset_path_q(aid, original);
                let src_t = c.src_at(t);
                let mt_path = doc.rel_path(&format!("popout-cache/{key}.mt.mp4"));
                let mt_t = if c.is_freeze() { off } else { off + (c.src_at(t) - c.source_start) };
                // ONE pool.get per stream: a second get in the same compose sees the
                // instance as busy-this-frame and OPENS A SPARE (~50ms + an empty texture)
                // — that was 110ms/frame of the pop-out scrub cost
                // FREEZE: bake original+mattes ONCE (exact), then serve the stills forever.
                // Re-decoding per scrub tick made the cutout visibly change inside a frozen
                // clip (budgeted approximations differ per position) and fought the pool.
                let fz_keys = if c.is_freeze() {
                    Some((
                        (format!("fz:{aid}"), (src_t * 1000.0).round() as i64),
                        (format!("fz:{key}#mt0"), (mt_t * 1000.0).round() as i64),
                        (format!("fz:{key}#mt1"), (mt_t * 1000.0).round() as i64),
                    ))
                } else {
                    None
                };
                if let Some((ko, _, _)) = fz_keys.as_ref() {
                    let _ = load_freeze_png(doc, d3d, comp, c, ko);
                }
                let cached = fz_keys.as_ref().and_then(|(ko, kp, ks)| {
                    Some((comp.still_get(ko)?, comp.still_get(kp)?, comp.still_get(ks)?))
                });
                let (otex, ptex, stex);
                if let Some(((o, _), (pp, _), (ss, _))) = cached {
                    otex = o;
                    ptex = pp;
                    stex = ss;
                } else {
                    if fz_keys.is_some() {
                        // freeze still not baked yet: whatever we show now is provisional —
                        // force a settle pass so the ORIGINAL-quality bake happens at rest
                        exact = false;
                        fz_log(&format!("FZ_FALLBACK popout id={} t={t:.2} fast={fast}", c.id));
                    }
                    let o = {
                        let sdec = pool.get(d3d, &opath, 0, false, src_t)?;
                        if fast {
                            if Instant::now() < f_deadline {
                                exact &= sdec.ensure_frame_scrub(d3d, src_t, 12.0)?;
                            } else {
                                exact = false; // out of budget — stale person, refined at rest
                            }
                        } else {
                            sdec.ensure_frame(d3d, src_t)
                                .map_err(|e| e.context(format!("live-orig {} src_t={src_t:.2}", sdec.name)))?;
                        }
                        (sdec.bgra.clone(), (sdec.width, sdec.height))
                    };
                    let mut mt_tex = Vec::with_capacity(2);
                    for stream in [MT_PERSON, MT_SHADOW] {
                        let sdec = pool.get(d3d, &mt_path, stream, true, mt_t)?;
                        if fast {
                            if Instant::now() < f_deadline {
                                exact &= sdec.ensure_frame_scrub(d3d, mt_t, 8.0)?;
                            } else {
                                exact = false;
                            }
                        } else {
                            sdec.ensure_frame(d3d, mt_t)
                                .map_err(|e| e.context(format!("live-mt {} src_t={mt_t:.2}", sdec.name)))?;
                        }
                        mt_tex.push((sdec.bgra.clone(), (sdec.width, sdec.height)));
                    }
                    let ss = mt_tex.pop().unwrap();
                    let pp = mt_tex.pop().unwrap();
                    if let (Some((ko, kp, ks)), true) = (fz_keys, !fast) {
                        let _ = comp.still_put(d3d, ko, &o.0, o.1);
                        let _ = comp.still_put(d3d, kp, &pp.0, pp.1);
                        let _ = comp.still_put(d3d, ks, &ss.0, ss.1);
                    }
                    otex = o.0;
                    ptex = pp.0;
                    stex = ss.0;
                }
                let (cw, ch) = (meta.canvas[0] as f32, meta.canvas[1] as f32);
                let aff = [
                    meta.src_x as f32 / cw,
                    meta.src_y as f32 / ch,
                    meta.sw as f32 / cw,
                    meta.sh as f32 / ch,
                ];
                comp.draw_popout_live(d3d, &otex, &ptex, &stex, &mask, (b.x, b.y, b.width, b.height), aff, c.visual_opacity())?;
                used.push(opath);
                used.push(mt_path);
                continue;
            }
            let rel = format!("popout-cache/{key}.pv.mp4");
            let path = doc.rel_path(&rel);
            let pv_usable = std::fs::metadata(&path).map(|m| m.len() > 0).unwrap_or(false);
            if !pv_usable {
                // bake not finished (or a broken 0-byte cache): show the person as a
                // PLAIN PiP at the card box — the clip must never vanish, and one bad
                // cache file must never take the whole preview down
                if let Some(p2) = draw_plain_pip(doc, d3d, pool, comp, c, b, t, original, fast)? {
                    used.push(p2);
                }
                continue;
            }
            let pv_draw = (|pool: &mut media::VideoPool, comp: &mut compositor::Compositor, used: &mut Vec<String>| -> anyhow::Result<()> {
                let src_t = if c.is_freeze() { off } else { off + (c.src_at(t) - c.source_start) };
                const COLOR: u32 = 1; // MF enumerates this pv's 2 video tracks in reverse mux order
                const MATTE: u32 = 0;
                let (ctex, cwh) = {
                    let s = pool.get(d3d, &path, COLOR, false, src_t)?;
                    if fast {
                        if Instant::now() < f_deadline {
                            exact &= s.ensure_frame_scrub(d3d, src_t, 12.0)?;
                        } else {
                            exact = false;
                        }
                    } else {
                        s.ensure_frame(d3d, src_t)
                            .map_err(|e| e.context(format!("pv-color {} src_t={src_t:.2}", s.name)))?;
                    }
                    (s.bgra.clone(), (s.width, s.height))
                };
                let mtex = {
                    let s = pool.get(d3d, &path, MATTE, true, src_t)?;
                    if fast {
                        if Instant::now() < f_deadline {
                            exact &= s.ensure_frame_scrub(d3d, src_t, 12.0)?;
                        } else {
                            exact = false;
                        }
                    } else {
                        s.ensure_frame(d3d, src_t)
                            .map_err(|e| e.context(format!("pv-matte {} src_t={src_t:.2}", s.name)))?;
                    }
                    s.bgra.clone()
                };
                comp.draw_opacity(d3d, &ctex, cwh, (b.x, b.y, b.width, b.height), false, Some(&mtex), c.visual_opacity())?;
                used.push(path.clone());
                Ok(())
            })(pool, comp, &mut used);
            if let Err(e) = pv_draw {
                eprintln!("pv fallback {key}: {e:#}");
                if let Some(p2) = draw_plain_pip(doc, d3d, pool, comp, c, b, t, original, fast)? {
                    used.push(p2);
                }
            }
        } else if let Some(aid) = c.asset_id.as_deref().filter(|a| doc.asset_images.contains(*a)) {
            // STILL IMAGE clip (logo / generated CTA art): decode once into the still
            // cache, draw CONTAIN-fitted (aspect preserved inside the box) with alpha —
            // no decoder, no audio, identical semantics to the exporter's image branch.
            let Some(path) = doc.originals.get(aid).cloned() else { continue };
            let key = (format!("img:{aid}"), 0i64);
            if comp.still_get(&key).is_none() {
                if let Ok(bytes) = std::fs::read(&path) {
                    if let Ok(img) = image::load_from_memory(&bytes) {
                        let (ow, oh) = (img.width(), img.height());
                        let long = ow.max(oh);
                        let img = if long > 1920 {
                            let sc = 1920.0 / long as f32;
                            img.resize(
                                ((ow as f32 * sc).round() as u32).max(2),
                                ((oh as f32 * sc).round() as u32).max(2),
                                image::imageops::FilterType::CatmullRom,
                            )
                        } else {
                            img
                        };
                        let rgba = img.to_rgba8();
                        let (w, h) = (rgba.width(), rgba.height());
                        let _ = comp.still_put_rgba(d3d, key.clone(), w, h, rgba.as_raw());
                    }
                }
            }
            if let Some((tex, (iw, ih))) = comp.still_get(&key) {
                // Explicit cover must fill the box just as it does for video.
                // Legacy/default images remain contain-fitted; an explicit X/Y resize
                // switches to stretch and the source fills the edited box itself.
                let (bx, by, bw, bh) = (b.x, b.y, b.width, b.height);
                if c.fit.as_deref() == Some("cover") {
                    comp.set_grade(grade_params(c));
                    comp.draw_alpha_cover_opacity(d3d, &tex, (iw, ih),
                        (bx, by, bw, bh), c.crop_ltrb_at(t_geo), c.visual_opacity())?;
                    used.push(path);
                    continue;
                }
                if c.stretches_to_box() {
                    comp.set_grade(grade_params(c));
                    let _ = comp.draw_alpha_opacity(
                        d3d,
                        &tex,
                        (iw, ih),
                        (bx, by, bw, bh),
                        c.visual_opacity(),
                    );
                    used.push(path);
                    continue;
                }
                let box_px_w = bw * canvas_w() as f64;
                let box_px_h = bh * canvas_h() as f64;
                let (mut dw, mut dh) = (bw, bh);
                if iw > 0 && ih > 0 && box_px_w > 1.0 && box_px_h > 1.0 {
                    let ia = iw as f64 / ih as f64;
                    let ba = box_px_w / box_px_h;
                    if ia > ba {
                        dh = bh * (ba / ia);
                    } else {
                        dw = bw * (ia / ba);
                    }
                }
                let dst = (bx + (bw - dw) / 2.0, by + (bh - dh) / 2.0, dw, dh);
                comp.set_grade(grade_params(c));
                let _ = comp.draw_alpha_opacity(d3d, &tex, (iw, ih), dst, c.visual_opacity());
            }
            used.push(path);
        } else if let Some(aid) = c.asset_id.as_deref() {
            let path = doc.asset_path_q(aid, original);
            let mut src_t = c.src_at(t);
            if !fast && original {
                src_t = snap_src_t(pts_maps, aid, src_t);
            }
            let blur_dbg = BLUR_DBG.load(Ordering::Relaxed);
            if c.is_freeze() {
                // Freeze still: keyed by ASSET (a path key forked into separate proxy- and
                // original-quality stills that visibly swapped), baked ONLY from an exact
                // ORIGINAL decode. Until it exists, live frames show WITHOUT being cached.
                let key = (format!("fz:{aid}"), (src_t * 1000.0).round() as i64);
                let _ = load_freeze_png(doc, d3d, comp, c, &key);
                let got = comp.still_get(&key);
                let got_was_still = got.is_some();
                let (tex, wh) = if let Some(x) = got {
                    x
                } else {
                    fz_log(&format!(
                        "FZ_FALLBACK base id={} t={t:.2} fast={fast} original={original}",
                        c.id
                    ));
                    let vs = pool.get(d3d, &path, 0, false, src_t)?;
                    let is_exact = if fast {
                        exact = false; // still not baked yet — settle must come back
                        vs.ensure_frame_scrub(d3d, src_t, 12.0)?;
                        false
                    } else {
                        vs.ensure_frame(d3d, src_t)?;
                        true
                    };
                    let tw = (vs.bgra.clone(), (vs.width, vs.height));
                    if is_exact {
                        comp.still_put(d3d, key, &tw.0, tw.1)?;
                    }
                    tw
                };
                let b = effective_box(doc, c, t_geo);
                if near_fz {
                    eprintln!(
                        "FZ_SEAM t={t:.3} clip={} q={} tex={}x{} box={:.4},{:.4},{:.4},{:.4}",
                        c.id,
                        if got_was_still { "png" } else if original { "orig-dec" } else { "proxy-dec" },
                        wh.0, wh.1, b.x, b.y, b.width, b.height
                    );
                }
                let dst = (b.x, b.y, b.width, b.height);
                let dst = if c.contains_in_box() { contain_box(dst, wh) } else { dst };
                comp.set_grade(grade_params(c));
                comp.draw_cropped_opacity(d3d, &tex, wh, dst, !c.stretches_to_box() && !c.contains_in_box(), None, c.crop_ltrb_at(t_geo), c.visual_opacity())?;
                used.push(path);
                continue;
            }
            let vs = pool.get(d3d, &path, 0, false, src_t)?;
            if fast {
                if Instant::now() < f_deadline {
                    exact &= vs.ensure_frame_scrub(d3d, src_t, 12.0)?;
                } else {
                    exact = false;
                }
            } else {
                vs.ensure_frame(d3d, src_t)
                    .map_err(|e| e.context(format!("overlay {} src_t={src_t:.2}", vs.name)))?;
            }
            if blur_dbg {
                eprintln!(
                    "BLURBASE t={t:.3} clip={} req_src={src_t:.3} landed={:.3} fast={fast}",
                    c.id,
                    vs.shown_pts()
                );
            }
            if base_id.as_deref() == Some(c.id.as_str()) && vs.shown_pts() >= 0.0 {
                let landed = vs.shown_pts();
                // Label the pixels with the REQUEST time when the landed frame is the
                // one COVERING t (pts <= src_t < pts + frame). Re-mapping the landed pts
                // and re-rounding relabelled the same picture one grid slot EARLY
                // whenever the clip's source offset sits more than half a frame off the
                // sequence grid — every keyframe write/read/highlight then ran one frame
                // left of the playhead (user-visible off-by-one). The window is ~2.5
                // sequence frames so 24fps sources on a 30fps grid still count as
                // covering; a budgeted scrub that stopped genuinely short keeps the real
                // landed time (the blur stays glued to the stale picture, as designed).
                let covering = landed <= src_t + 0.0005 && src_t - landed < 2.5 / gfps.max(1.0);
                let eff = if covering { t } else { c.timeline_start + (landed - c.source_start) };
                // sanity: decoder slop is bounded (±0.6s windows); reject wild values
                if (eff - t).abs() < 0.75 {
                    base_eff_t = Some(eff);
                }
            }
            let (tex, wh) = (vs.bgra.clone(), (vs.width, vs.height));
            if near_fz {
                eprintln!(
                    "FZ_SEAM t={t:.3} clip={} q={} tex={}x{} box={:.4},{:.4},{:.4},{:.4}",
                    c.id,
                    if original { "orig-dec" } else { "proxy-dec" },
                    wh.0, wh.1, b.x, b.y, b.width, b.height
                );
            }
            let dst = (b.x, b.y, b.width, b.height);
            let dst = if c.contains_in_box() { contain_box(dst, wh) } else { dst };
            comp.set_grade(grade_params(c));
            comp.draw_cropped_opacity(d3d, &tex, wh, dst, !c.stretches_to_box() && !c.contains_in_box(), None, c.crop_ltrb_at(t_geo), c.visual_opacity())?;
            used.push(path);
        }
    }
    // (region effects and captions are drawn IN the z loop above — lane order is the
    // one and only stacking rule. Captions above the topmost video/effect layer are
    // not here: the transparent WebView2 overlay renders those live.)
    _ms_ov = _t.elapsed().as_secs_f64() * 1000.0;
    let _t = Instant::now();
    match rb {
        // GPU-direct: the caller snapshots the canvas into a pooled texture; no map
        Rb::None => {}
        Rb::Async => comp.readback(d3d)?,
        Rb::Sync => comp.readback_sync(d3d)?,
    }
    let _ms_rb = _t.elapsed().as_secs_f64() * 1000.0;
    let total = _t_begin.elapsed().as_secs_f64() * 1000.0;
    if total > 40.0 {
        eprintln!("slow compose t={t:.2}: base={_ms_base:.0} ov={_ms_ov:.0} rb={_ms_rb:.0} total={total:.0}");
    }
    Ok((used, exact, base_eff_t.unwrap_or(t)))
}

fn py_json(v: &serde_json::Value) -> String {
    match v {
        serde_json::Value::Null => "null".into(),
        serde_json::Value::Bool(b) => {
            if *b { "true".into() } else { "false".into() }
        }
        serde_json::Value::Number(n) => n.to_string(),
        serde_json::Value::String(s) => serde_json::to_string(s).unwrap_or_else(|_| "\"\"".into()),
        serde_json::Value::Array(a) => {
            let parts: Vec<String> = a.iter().map(py_json).collect();
            format!("[{}]", parts.join(", "))
        }
        serde_json::Value::Object(m) => {
            let mut keys: Vec<&String> = m.keys().collect();
            keys.sort();
            let parts: Vec<String> = keys
                .into_iter()
                .map(|k| format!("{}: {}", serde_json::to_string(k).unwrap(), py_json(&m[k])))
                .collect();
            format!("{{{}}}", parts.join(", "))
        }
    }
}

fn caption_style_num(style: &serde_json::Value, key: &str, default: f64) -> f64 {
    style.get(key).and_then(|v| v.as_f64()).unwrap_or(default)
}

/// UI-thread frame cost meter → UISTAT line every 5s in %TEMP%/native_ui.log.
/// 「タイムラインが重くなる」報告の一次証拠: frame avg/max (UI paint cost), undo
/// bytes, cache entry counts, process working set. Reading the log after a real
/// session tells WHICH resource grew instead of guessing.
struct UiFrameStat {
    frames: u32,
    total_ms: f32,
    max_ms: f32,
    last_log: Instant,
}
thread_local! {
    static UI_FRAME_STAT: std::cell::RefCell<UiFrameStat> = std::cell::RefCell::new(UiFrameStat {
        frames: 0,
        total_ms: 0.0,
        max_ms: 0.0,
        last_log: Instant::now(),
    });
}

struct UiStatGuard {
    start: Instant,
    // Some(app snapshot) when this frame should emit the 5s line
    info: Option<String>,
}

impl UiStatGuard {
    fn begin(app: &App) -> Self {
        let due = UI_FRAME_STAT.with(|s| s.borrow().last_log.elapsed().as_secs_f32() >= 5.0);
        let info = due.then(|| {
            let undo_bytes: usize = app.undo.iter().map(|s| s.len()).sum::<usize>()
                + app.redo.iter().map(|s| s.len()).sum::<usize>();
            let ws_mb = process_working_set_mb();
            format!(
                "undo={}x/{:.1}MB thumbs={} peaks={} capfree={} ws={}MB",
                app.undo.len() + app.redo.len(),
                undo_bytes as f32 / 1.048e6,
                app.thumbs.len(),
                app.peaks.len(),
                app.cap_tex.len(),
                ws_mb,
            )
        });
        UiStatGuard { start: Instant::now(), info }
    }
}

impl Drop for UiStatGuard {
    fn drop(&mut self) {
        let ms = self.start.elapsed().as_secs_f32() * 1000.0;
        UI_FRAME_STAT.with(|s| {
            let mut s = s.borrow_mut();
            s.frames += 1;
            s.total_ms += ms;
            s.max_ms = s.max_ms.max(ms);
            if let Some(info) = self.info.take() {
                eprintln!(
                    "UISTAT frame avg={:.1}ms max={:.1}ms n={} {}",
                    if s.frames > 0 { s.total_ms / s.frames as f32 } else { 0.0 },
                    s.max_ms,
                    s.frames,
                    info,
                );
                s.frames = 0;
                s.total_ms = 0.0;
                s.max_ms = 0.0;
                s.last_log = Instant::now();
            }
        });
    }
}

/// Process working set in MB (0 when the query fails) — the restart-fixes-it class of
/// slowdown is almost always visible here first.
fn process_working_set_mb() -> u64 {
    #[cfg(target_os = "windows")]
    unsafe {
        use windows::Win32::System::ProcessStatus::{GetProcessMemoryInfo, PROCESS_MEMORY_COUNTERS};
        use windows::Win32::System::Threading::GetCurrentProcess;
        let mut pmc = PROCESS_MEMORY_COUNTERS {
            cb: std::mem::size_of::<PROCESS_MEMORY_COUNTERS>() as u32,
            ..Default::default()
        };
        if GetProcessMemoryInfo(GetCurrentProcess(), &mut pmc, pmc.cb).is_ok() {
            return (pmc.WorkingSetSize / (1024 * 1024)) as u64;
        }
    }
    0
}

/// "#rrggbb" (or "#rgb") → Color32; anything unparsable falls back to `default`.
fn hex_color32(s: &str, default: egui::Color32) -> egui::Color32 {
    let h = s.trim().trim_start_matches('#');
    let full = match h.len() {
        3 => h.chars().flat_map(|c| [c, c]).collect::<String>(),
        6 => h.to_string(),
        _ => return default,
    };
    match u32::from_str_radix(&full, 16) {
        Ok(v) => egui::Color32::from_rgb((v >> 16) as u8, (v >> 8) as u8, v as u8),
        Err(_) => default,
    }
}

/// Hex colour for GPU effect shaders, with black as the safe redaction fallback.
fn effect_rgb(s: &str) -> [f32; 3] {
    let c = hex_color32(s, egui::Color32::BLACK);
    [c.r() as f32 / 255.0, c.g() as f32 / 255.0, c.b() as f32 / 255.0]
}

fn color32_hex(c: egui::Color32) -> String {
    format!("#{:02x}{:02x}{:02x}", c.r(), c.g(), c.b())
}

/// スポイト: the color of the physical screen pixel under the mouse cursor. Samples
/// the COMPOSITED desktop, so whatever the eye sees is what is picked — the video
/// frame, a pop-out, or the caption WebView overlay alike.
fn screen_pixel_under_cursor() -> Option<egui::Color32> {
    #[cfg(target_os = "windows")]
    unsafe {
        use windows::Win32::Foundation::POINT;
        use windows::Win32::Graphics::Gdi::{GetDC, GetPixel, ReleaseDC, CLR_INVALID};
        use windows::Win32::UI::WindowsAndMessaging::GetCursorPos;
        let mut pt = POINT::default();
        if GetCursorPos(&mut pt).is_err() {
            return None;
        }
        let dc = GetDC(None);
        if dc.is_invalid() {
            return None;
        }
        let c = GetPixel(dc, pt.x, pt.y);
        ReleaseDC(None, dc);
        if c == windows::Win32::Foundation::COLORREF(CLR_INVALID) {
            return None;
        }
        // COLORREF is 0x00BBGGRR
        let v = c.0;
        return Some(egui::Color32::from_rgb(
            (v & 0xff) as u8,
            ((v >> 8) & 0xff) as u8,
            ((v >> 16) & 0xff) as u8,
        ));
    }
    #[allow(unreachable_code)]
    None
}

/// The same curated designs as the Web's CAPTION_PRESETS (caption-design.ts) — one
/// click sets the whole look; fontSize / x / y are the user's and are NOT touched.
/// Keys not in a preset are explicitly nulled so leftovers from the previous look
/// (bg / gradient / shadow / karaoke highlight) never bleed through.
fn caption_presets() -> Vec<(&'static str, serde_json::Value)> {
    use serde_json::json;
    let base = |d: serde_json::Value| {
        let mut full = json!({
            "bg": null, "gradient": null, "shadow": null,
            "highlightColor": null, "highlightScale": null, "animation": "none"
        });
        edits_merge_for_preset(&mut full, &d);
        full
    };
    vec![
        ("標準", base(json!({"font":"noto-sans","color":"#ffffff","outlineColor":"#000000","outlineWidth":1}))),
        ("バラエティ黄", base(json!({"font":"dela-gothic","color":"#ffe000","outlineColor":"#000000","outlineWidth":1.4,"animation":"pop"}))),
        ("赤ポップ", base(json!({"font":"dela-gothic","color":"#ff3b30","outlineColor":"#ffffff","outlineWidth":1.4,"animation":"pop"}))),
        ("字幕バー", base(json!({"font":"noto-sans","color":"#ffffff","outlineColor":"#000000","outlineWidth":0.5,
            "bg":{"color":"#000000","opacity":0.62,"radius":0.2,"padX":0.5,"padY":0.18},"animation":"fade"}))),
        ("シンプル黒箱", base(json!({"font":"noto-sans","color":"#ffffff","outlineColor":"#000000","outlineWidth":0,
            "bg":{"color":"#000000","opacity":1.0,"radius":0.05,"padX":0.5,"padY":0.22}}))),
        ("シンプル白箱", base(json!({"font":"noto-sans","color":"#111111","outlineColor":"#000000","outlineWidth":0,
            "bg":{"color":"#ffffff","opacity":1.0,"radius":0.05,"padX":0.5,"padY":0.22}}))),
        ("カラオケ実況", base(json!({"font":"mplus-rounded","color":"#ffffff","outlineColor":"#1b1b1b","outlineWidth":1.3,
            "animation":"karaoke","highlightColor":"#ff3b6b","highlightScale":1.16}))),
        ("タイプ", base(json!({"font":"noto-sans","color":"#ffffff","outlineColor":"#000000","outlineWidth":1,"animation":"typewriter"}))),
        ("ネオン", base(json!({"font":"dela-gothic","color":"#19e6ff","outlineColor":"#003b46","outlineWidth":1.2,
            "shadow":{"color":"#19e6ff","blur":24,"dy":0},"animation":"fade"}))),
        ("明朝・上品", base(json!({"font":"mincho","color":"#ffffff","outlineColor":"#000000","outlineWidth":0.6,
            "bg":{"color":"#16213e","opacity":0.52,"radius":0.1,"padX":0.5,"padY":0.2},"animation":"slide"}))),
        ("丸かわいい", base(json!({"font":"zen-maru","color":"#ff7aa8","outlineColor":"#ffffff","outlineWidth":1.6,"animation":"pop"}))),
    ]
}

/// Overlay preset fields onto the null-scaffold (plain shallow merge, preset side wins).
fn edits_merge_for_preset(dst: &mut serde_json::Value, src: &serde_json::Value) {
    if let (Some(d), Some(s)) = (dst.as_object_mut(), src.as_object()) {
        for (k, v) in s {
            d.insert(k.clone(), v.clone());
        }
    }
}

fn caption_fallbacks() -> &'static Mutex<std::collections::HashMap<String, (String, f64)>> {
    static FALLBACKS: OnceLock<Mutex<std::collections::HashMap<String, (String, f64)>>> = OnceLock::new();
    FALLBACKS.get_or_init(|| Mutex::new(Default::default()))
}

fn caption_render_style(style: &serde_json::Value) -> serde_json::Value {
    let mut design = if style.is_object() { style.clone() } else { serde_json::json!({}) };
    if let Some(o) = design.as_object_mut() {
        o.remove("x");
        o.remove("y");
    }
    design
}

fn caption_cache_key(c: &model::Clip, text: &str, style: &serde_json::Value) -> String {
    use sha1::{Digest, Sha1};
    let design = caption_render_style(style);
    let words = if c.words.is_array() { c.words.clone() } else { serde_json::json!([]) };
    let spec = serde_json::json!({
        "w": canvas_w(),
        "h": canvas_h(),
        "t": text,
        "d": design,
        "words": words,
    });
    let mut hasher = Sha1::new();
    hasher.update(py_json(&spec).as_bytes());
    format!("{:x}", hasher.finalize())[..16].to_string()
}

fn caption_legacy_cache_key(c: &model::Clip, text: &str, style: &serde_json::Value) -> String {
    use sha1::{Digest, Sha1};
    let design = if style.is_object() { style.clone() } else { serde_json::json!({}) };
    let words = if c.words.is_array() { c.words.clone() } else { serde_json::json!([]) };
    let spec = serde_json::json!({
        "w": canvas_w(),
        "h": canvas_h(),
        "t": text,
        "d": design,
        "words": words,
    });
    let mut hasher = Sha1::new();
    hasher.update(py_json(&spec).as_bytes());
    format!("{:x}", hasher.finalize())[..16].to_string()
}

/// ACTIVE designed captions at time t that the GPU compositor draws at their LANE
/// position: every caption with at least one video/effect layer ABOVE it (lane array
/// order = z). Captions above the topmost video/effect stay on the WebView overlay
/// (live animation). A caption whose cache PNG hasn't landed yet, or whose text is
/// being live-edited, stays in the WebView too — visible with a briefly-wrong z beats
/// invisible, and the set converges as soon as caption_cache_pass delivers the PNG.
fn native_caption_ids(doc: &model::Doc, t: f64) -> std::collections::HashSet<String> {
    let mut below: Vec<&model::Clip> = Vec::new();
    let mut out = std::collections::HashSet::new();
    let mut promote = |caps: &mut Vec<&model::Clip>, out: &mut std::collections::HashSet<String>| {
        for c in caps.drain(..) {
            if caption_live::is_active(&c.id) {
                continue;
            }
            let text = c.text.clone().unwrap_or_default();
            let style = c.style.clone().unwrap_or_else(|| serde_json::json!({}));
            let key = caption_cache_key(c, &text, &style);
            let png = std::path::Path::new(&doc.asset_dir)
                .join("caption-cache")
                .join(format!("{key}.png"));
            if std::fs::metadata(&png).map(|m| m.len() > 0).unwrap_or(false) {
                out.insert(c.id.clone());
            }
        }
    };
    for tr in doc.seq.tracks.iter().filter(|tr| tr.kind != "audio" && !tr.hidden) {
        for c in &tr.clips {
            if !doc.clip_active_at(c, t) {
                continue;
            }
            if c.asset_id.is_some() {
                if c.is_video_enabled() {
                    promote(&mut below, &mut out);
                }
            } else if c.region.is_some() {
                if c.style.as_ref().and_then(|v| v.as_str()) != Some("note") {
                    promote(&mut below, &mut out);
                }
            } else if c.text.as_deref().map(|s| !s.trim().is_empty()).unwrap_or(false) {
                below.push(c);
            }
        }
    }
    if EXPORT_ALL_CAPTIONS.load(Ordering::Relaxed) {
        // headless export: the WebView overlay does not exist — captions above the
        // topmost video draw natively too (in the same lane z-order)
        promote(&mut below, &mut out);
    }
    out
}

fn caption_runtime_dst(c: &model::Clip, cached_dst: (f64, f64, f64, f64), cached_font_size: f64) -> (f64, f64, f64, f64) {
    let style = c.style.as_ref().unwrap_or(&serde_json::Value::Null);
    let y_frac = caption_style_num(style, "y", 0.08).clamp(0.0, 0.92);
    let x_frac = caption_style_num(style, "x", 0.0);
    let cur_font = caption_style_num(style, "fontSize", 1.0).max(0.05);
    let scale = (cur_font / cached_font_size.max(0.05)).clamp(0.25, 4.0);
    let default_y = 0.08;
    let (x, y, w, h) = cached_dst;
    let nw = w * scale;
    let nh = h * scale;
    let cx = x + w * 0.5 + x_frac;
    let bottom = y + h - (y_frac - default_y);
    // No snap-back clamping: a caption may sit partly off-screen (the renderer just
    // crops at the frame edge), so the box must follow it out rather than stick inside.
    (cx - nw * 0.5, bottom - nh, nw, nh)
}

fn crop_alpha_rgba(rgba: &image::RgbaImage) -> Option<(Vec<u8>, u32, u32, (u32, u32, u32, u32))> {
    let (w, h) = rgba.dimensions();
    let (mut min_x, mut min_y) = (w, h);
    let (mut max_x, mut max_y) = (0u32, 0u32);
    for y in 0..h {
        for x in 0..w {
            if rgba.get_pixel(x, y).0[3] != 0 {
                min_x = min_x.min(x);
                min_y = min_y.min(y);
                max_x = max_x.max(x);
                max_y = max_y.max(y);
            }
        }
    }
    if min_x > max_x || min_y > max_y {
        return None;
    }
    let cw = max_x - min_x + 1;
    let ch = max_y - min_y + 1;
    let mut out = vec![0u8; (cw * ch * 4) as usize];
    for yy in 0..ch {
        let src = (((min_y + yy) * w + min_x) * 4) as usize;
        let dst = (yy * cw * 4) as usize;
        out[dst..dst + (cw * 4) as usize].copy_from_slice(&rgba.as_raw()[src..src + (cw * 4) as usize]);
    }
    Some((out, cw, ch, (min_x, min_y, cw, ch)))
}

/// Pre-seek decoders for clips starting soon so entering them costs nothing.
fn prime_upcoming(
    doc: &model::Doc,
    d3d: &media::D3d,
    pool: &mut media::VideoPool,
    masks: &MaskMap,
    t: f64,
    original: bool,
    used: &[String],
) {
    let _ = used;
    // BUDGETED: nearest upcoming boundary first, and at most ONE slice of decode work per
    // call — un-budgeted priming ate 100-180ms per loop and starved both the ring and the
    // boundary it was supposed to protect.
    let mut ups: Vec<&model::Clip> = Vec::new();
    for tr in &doc.seq.tracks {
        if tr.kind == "audio" {
            continue;
        }
        for c in &tr.clips {
            if c.timeline_start > t && c.timeline_start <= t + 3.0 {
                ups.push(c);
            }
        }
    }
    ups.sort_by(|a, b| a.timeline_start.partial_cmp(&b.timeline_start).unwrap());
    for c in ups {
        let mut step = |pool: &mut media::VideoPool| -> bool {
            if let Some((key, off)) = c.popout_key() {
                let live = masks.get(&key).map_or(false, |o| o.is_some());
                if live {
                    let mt = doc.rel_path(&format!("popout-cache/{key}.mt.mp4"));
                    let orig = c
                        .asset_id
                        .as_deref()
                        .map(|aid| doc.asset_path_q(aid, original));
                    orig.map(|p| pool.prime_spare(d3d, &p, 0, false, c.source_start).unwrap_or(false))
                        .unwrap_or(false)
                        || pool.prime_spare(d3d, &mt, MT_PERSON, true, off).unwrap_or(false)
                        || pool.prime_spare(d3d, &mt, MT_SHADOW, true, off).unwrap_or(false)
                } else {
                    let path = doc.rel_path(&format!("popout-cache/{key}.pv.mp4"));
                    pool.prime_spare(d3d, &path, 0, true, off).unwrap_or(false)
                        || pool.prime_spare(d3d, &path, 1, false, off).unwrap_or(false)
                }
            } else if let Some(aid) = c.asset_id.as_deref() {
                let path = doc.asset_path_q(aid, original);
                pool.prime_spare(d3d, &path, 0, false, c.source_start).unwrap_or(false)
            } else {
                false
            }
        };
        if step(pool) {
            // strictly ONE decode-read per producer slice: a faster budgeted walk was
            // tried and it GAP-stormed — aggressive priming keeps re-seating the spare
            // the next compose is about to claim, so every join walked cold
            return;
        }
    }
}

/// Ring is FULL (~400ms of slack) — the ONLY moment mid-play that can afford a decoder
/// OPEN (100-300ms). Warm instances for clips starting in the next few seconds, nearest
/// first, one open per call. Without this, a session that goes straight from launch to
/// play has no spares, boundary priming no-ops, and every big source jump walks cold.
fn warm_upcoming(
    doc: &model::Doc,
    d3d: &media::D3d,
    pool: &mut media::VideoPool,
    masks: &MaskMap,
    t: f64,
) -> bool {
    let is_live = |c: &model::Clip| {
        c.popout_key()
            .map_or(false, |(k, _)| masks.get(&k).map_or(false, |o| o.is_some()))
    };
    let mut uses: std::collections::HashMap<String, usize> = Default::default();
    for tr in &doc.seq.tracks {
        if tr.kind == "audio" {
            continue;
        }
        for c in &tr.clips {
            // live pop-outs decode the original too — count them as concurrent users
            if c.popout().is_none() || is_live(c) {
                if let Some(aid) = c.asset_id.as_deref() {
                    *uses.entry(doc.asset_path_q(aid, true)).or_default() += 1;
                }
            }
        }
    }
    let mut ups: Vec<&model::Clip> = Vec::new();
    for tr in &doc.seq.tracks {
        if tr.kind == "audio" {
            continue;
        }
        for c in &tr.clips {
            let active = c.timeline_start <= t && t < c.timeline_end;
            if active || (c.timeline_start > t && c.timeline_start <= t + 8.0) {
                ups.push(c);
            }
        }
    }
    ups.sort_by(|a, b| a.timeline_start.partial_cmp(&b.timeline_start).unwrap());
    for c in ups {
        if let Some((key, _)) = c.popout_key() {
            if is_live(c) {
                let mt = doc.rel_path(&format!("popout-cache/{key}.mt.mp4"));
                for s in [MT_PERSON, MT_SHADOW] {
                    if !pool.has_instances(&mt, s, 1) {
                        let _ = pool.warm_open(d3d, &mt, s, true, 1);
                        return true;
                    }
                }
                if let Some(aid) = c.asset_id.as_deref() {
                    let p = doc.asset_path_q(aid, true);
                    let want = if uses.get(&p).copied().unwrap_or(0) >= 2 { 2 } else { 1 };
                    for n in 1..=want {
                        if !pool.has_instances(&p, 0, n) {
                            let _ = pool.warm_open(d3d, &p, 0, false, n);
                            return true;
                        }
                    }
                }
                continue;
            }
            let p = doc.rel_path(&format!("popout-cache/{key}.pv.mp4"));
            if !std::path::Path::new(&p).exists() {
                continue;
            }
            for (s, fr) in [(0u32, true), (1u32, false)] {
                if !pool.has_instances(&p, s, 1) {
                    let _ = pool.warm_open(d3d, &p, s, fr, 1);
                    return true;
                }
            }
        } else if let Some(aid) = c.asset_id.as_deref() {
            let p = doc.asset_path_q(aid, true);
            // files cut into multiple clips need a 2nd instance (boundary ping-pong)
            let want = if uses.get(&p).copied().unwrap_or(0) >= 2 { 2 } else { 1 };
            for n in 1..=want {
                if !pool.has_instances(&p, 0, n) {
                    let _ = pool.warm_open(d3d, &p, 0, false, n);
                    return true;
                }
            }
        }
    }
    false
}

/// Tiny localhost-only HTTP client (the sandbox popout endpoints are auth-free local
/// APIs) — a dependency-free TcpStream request beats pulling a whole HTTP stack.
// RwLock（OnceLockでない）: トークンは24時間で失効する。制作ボタンから
// 起動するたび native_token.txt が新しくなるので、401 を受けたらファイルを
// 読み直して自己復帰する（開きっぱなしのエディタが翌日サイレントに
// 使えなくなる問題の根治）。
mod assistant_panel;
mod audio_transport;
static API_TOKEN: std::sync::RwLock<Option<String>> = std::sync::RwLock::new(None);
static TOKEN_REFRESH_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

fn token_file_path() -> String {
    if let Ok(directory) = std::env::var("DONE_NATIVE_AUTH_DIR") {
        return std::path::Path::new(&directory).join("native_token.txt").to_string_lossy().to_string();
    }
    format!(
        "{}/.done/native_token.txt",
        std::env::var("USERPROFILE").unwrap_or_default().replace(char::from(92), "/")
    )
}

/// 401 を受けたとき: 保存ファイルのトークンが今より新しければ差し替えて true
fn refresh_api_token_from_file() -> bool {
    let _refresh_guard = TOKEN_REFRESH_LOCK.lock().unwrap();
    let Some(fresh) = std::fs::read_to_string(token_file_path())
        .ok()
        .map(|t| t.trim().to_string())
        .filter(|t| !t.is_empty())
    else {
        return false;
    };
    if API_TOKEN.read().unwrap().as_deref() != Some(fresh.as_str()) {
        *API_TOKEN.write().unwrap() = Some(fresh);
        return true;
    }
    // Rereading an expired access token cannot renew a login. Use the separately
    // stored refresh credential through the normal authenticated refresh API.
    let refresh_path = token_file_path().replace("native_token.txt", "native_refresh_token.txt");
    let Ok(refresh) = std::fs::read_to_string(&refresh_path) else { return false; };
    let body = serde_json::json!({"refresh_token": refresh.trim()}).to_string();
    let Ok(raw) = http_local_once("POST", "/api/v1/editor-assistant/refresh", Some(&body)) else { return false; };
    let Ok(pair) = serde_json::from_str::<serde_json::Value>(&raw) else { return false; };
    let (Some(access), Some(next_refresh)) = (pair["access_token"].as_str(), pair["refresh_token"].as_str()) else { return false; };
    if access.is_empty() || next_refresh.is_empty() { return false; }
    if std::fs::write(&refresh_path, next_refresh).is_err() { return false; }
    if std::fs::write(token_file_path(), access).is_err() { return false; }
    *API_TOKEN.write().unwrap() = Some(access.to_string());
    true
}

/// Auth token for the local server: --token arg > DONE_TOKEN env > ~/.done/native_token.txt
/// (long-lived token minted server-side; done:// launches will inject their own).
fn load_api_token(args: &[String]) {
    // a done:// deep link carries the freshest token — it wins over --token/env/file
    let deep_tok = args
        .iter()
        .find(|a| a.starts_with("done://"))
        .and_then(|url| url.split('?').nth(1))
        .and_then(|q| q.split('&').find_map(|kv| kv.strip_prefix("token=").map(|v| v.to_string())))
        .filter(|v| !v.is_empty());
    let tok = deep_tok
        .or_else(|| {
            args.iter()
                .position(|a| a == "--token")
                .and_then(|i| args.get(i + 1).cloned())
        })
        .or_else(|| std::env::var("DONE_TOKEN").ok())
        .or_else(|| {
            let p = format!(
                "{}/.done/native_token.txt",
                std::env::var("USERPROFILE").unwrap_or_default().replace(char::from(92), "/")
            );
            std::fs::read_to_string(p).ok().map(|t| t.trim().to_string())
        })
        .filter(|t| !t.is_empty());
    *API_TOKEN.write().unwrap() = tok;
}

fn http_local(method: &str, path: &str, json_body: Option<&str>) -> anyhow::Result<String> {
    let used = API_TOKEN.read().unwrap().clone();
    match http_local_once(method, path, json_body) {
        Err(e) if format!("{e:#}").contains(" 401 ") => {
            // トークン失効 → ファイルの新トークンで一度だけリトライ。
            // 並行リクエストが同時に401になった場合、ファイル読み直しに
            // 「勝つ」のは1本だけなので、他スレッドが更新済みで現在の
            // トークンが自分の使った物と違う場合もリトライ対象にする。
            let refreshed = refresh_api_token_from_file();
            let now = API_TOKEN.read().unwrap().clone();
            if refreshed || now != used {
                http_local_once(method, path, json_body)
            } else {
                Err(e)
            }
        }
        other => other,
    }
}

fn http_local_once(method: &str, path: &str, json_body: Option<&str>) -> anyhow::Result<String> {
    use std::io::{Read, Write};
    let mut st = std::net::TcpStream::connect(("127.0.0.1", 8000))?;
    st.set_read_timeout(Some(std::time::Duration::from_secs(20)))?;
    let body = json_body.unwrap_or("");
    let auth = API_TOKEN
        .read()
        .unwrap()
        .as_ref()
        .map(|t| format!("Authorization: Bearer {t}\r\n"))
        .unwrap_or_default();
    let req = format!(
        "{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:8000\r\nConnection: close\r\n{auth}Content-Type: application/json\r\nContent-Length: {}\r\n\r\n{}",
        body.len(),
        body
    );
    st.write_all(req.as_bytes())?;
    let mut buf = Vec::new();
    st.read_to_end(&mut buf)?;
    let text = String::from_utf8_lossy(&buf).to_string();
    let Some(split) = text.find("\r\n\r\n") else {
        anyhow::bail!("bad http response ({} bytes)", buf.len());
    };
    let (head, mut rest) = (text[..split].to_string(), text[split + 4..].to_string());
    if head.to_ascii_lowercase().contains("transfer-encoding: chunked") {
        let mut out = String::new();
        let mut s2 = rest.as_str();
        while let Some(nl) = s2.find("\r\n") {
            let n = usize::from_str_radix(s2[..nl].trim(), 16).unwrap_or(0);
            if n == 0 {
                break;
            }
            out.push_str(&s2[nl + 2..nl + 2 + n]);
            s2 = &s2[nl + 2 + n + 2..];
        }
        rest = out;
    }
    if !head.starts_with("HTTP/1.1 2") && !head.starts_with("HTTP/1.0 2") {
        anyhow::bail!("http {}: {}", head.lines().next().unwrap_or(""), &rest[..rest.len().min(200)]);
    }
    Ok(rest)
}

/// Popout bake state shown ON the clip itself (the user's request: the clip's look
/// changes, not a sidebar spinner).
#[derive(Clone, Copy, PartialEq)]
enum PopState {
    Baking(u8),
    Failed,
    Ready,
}

fn chr_nl() -> &'static str {
    "\n"
}

fn probe_duration(path: &str) -> Option<f64> {
    use windows::core::PCWSTR;
    use windows::Win32::Media::MediaFoundation::*;
    unsafe {
        let _ = windows::Win32::System::Com::CoInitializeEx(
            None,
            windows::Win32::System::Com::COINIT_MULTITHREADED,
        );
        let _ = MFStartup(MF_VERSION, MFSTARTUP_FULL);
        let w: Vec<u16> = path.encode_utf16().chain(std::iter::once(0)).collect();
        let reader = MFCreateSourceReaderFromURL(PCWSTR(w.as_ptr()), None).ok()?;
        let pv = reader
            .GetPresentationAttribute(MF_SOURCE_READER_MEDIASOURCE.0 as u32, &MF_PD_DURATION)
            .ok()?;
        let hns = pv.as_raw().Anonymous.Anonymous.Anonymous.hVal;
        Some(hns as f64 / 10_000_000.0)
    }
}

/// Declared source frame rate for first-import project setup. VFR files still report a
/// nominal rate here; their proxy is normalized to the chosen timeline rate later.
fn probe_frame_rate(path: &str) -> Option<f64> {
    use windows::core::PCWSTR;
    use windows::Win32::Media::MediaFoundation::*;
    unsafe {
        let _ = windows::Win32::System::Com::CoInitializeEx(
            None,
            windows::Win32::System::Com::COINIT_MULTITHREADED,
        );
        let _ = MFStartup(MF_VERSION, MFSTARTUP_FULL);
        let w: Vec<u16> = path.encode_utf16().chain(std::iter::once(0)).collect();
        let reader = MFCreateSourceReaderFromURL(PCWSTR(w.as_ptr()), None).ok()?;
        let mt = reader.GetCurrentMediaType(MF_SOURCE_READER_FIRST_VIDEO_STREAM.0 as u32).ok()?;
        let packed = mt.GetUINT64(&MF_MT_FRAME_RATE).ok()?;
        let numerator = (packed >> 32) as u32;
        let denominator = packed as u32;
        (numerator > 0 && denominator > 0).then_some(numerator as f64 / denominator as f64)
    }
}

fn probe_has_audio(path: &str) -> bool {
    use windows::core::PCWSTR;
    use windows::Win32::Media::MediaFoundation::*;
    unsafe {
        let _ = windows::Win32::System::Com::CoInitializeEx(
            None,
            windows::Win32::System::Com::COINIT_MULTITHREADED,
        );
        let _ = MFStartup(MF_VERSION, MFSTARTUP_FULL);
        let w: Vec<u16> = path.encode_utf16().chain(std::iter::once(0)).collect();
        MFCreateSourceReaderFromURL(PCWSTR(w.as_ptr()), None)
            .ok()
            .and_then(|reader| reader.GetCurrentMediaType(MF_SOURCE_READER_FIRST_AUDIO_STREAM.0 as u32).ok())
            .is_some()
    }
}

fn is_image_path(path: &std::path::Path) -> bool {
    matches!(
        path.extension().and_then(|e| e.to_str()).unwrap_or("").to_ascii_lowercase().as_str(),
        "png" | "jpg" | "jpeg" | "webp" | "bmp" | "gif"
    )
}

/// Materialise a timeline-preview proxy for a locally dropped video.  Direct timeline
/// drops used to claim `proxy_ready` without producing a file, forcing playback to use
/// the often variable-frame-rate, long-GOP original forever.  The output is CFR with a
/// one-second GOP and is renamed only after ffmpeg exits successfully, so readers never
/// see a partial MP4.
fn spawn_local_proxy(asset_dir: String, asset_id: String, source: String) {
    if !std::path::Path::new(&source).is_file() {
        return;
    }
    let output = format!("{asset_dir}/{asset_id}_proxy.mp4");
    if std::fs::metadata(&output).map(|m| m.len() > 0).unwrap_or(false) {
        return;
    }
    std::thread::spawn(move || {
        use std::os::windows::process::CommandExt;
        let ff = ["C:/Users/Owner/ffmpeg/bin/ffmpeg.exe", "C:/ffmpeg/bin/ffmpeg.exe"]
            .into_iter()
            .find(|p| std::path::Path::new(p).is_file())
            .unwrap_or("ffmpeg");
        let partial = format!("{output}.part.mp4");
        let _ = std::fs::remove_file(&partial);
        let status = std::process::Command::new(ff)
            .args([
                "-hide_banner", "-loglevel", "error", "-y", "-i", &source,
                "-map", "0:v:0", "-map", "0:a?",
                "-vf", "scale=-2:720:flags=lanczos,fps=30",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                // 0.2s GOP: a backward frame-step decodes ≤5 frames instead of ≤29 —
                // the difference between "waiting" and "instant" when inspecting
                // frame-by-frame in reverse. Modest size cost on a preview-only file.
                "-g", "6", "-keyint_min", "6", "-sc_threshold", "0",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                "-movflags", "+faststart", &partial,
            ])
            .creation_flags(0x0800_0000) // CREATE_NO_WINDOW
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status();
        let ready = status.map(|s| s.success()).unwrap_or(false)
            && std::fs::metadata(&partial).map(|m| m.len() > 0).unwrap_or(false);
        if ready && std::fs::rename(&partial, &output).is_ok() {
            eprintln!("PROXY_READY asset={asset_id}");
        } else {
            let _ = std::fs::remove_file(&partial);
            eprintln!("PROXY_FAILED asset={asset_id}");
        }
    });
}

/// Start proxies for every local video already used by the open sequence. This repairs
/// older direct drops made before native import actually produced proxy media.
fn spawn_missing_timeline_proxies(doc: &model::Doc) {
    let mut ids = std::collections::HashSet::new();
    for track in &doc.seq.tracks {
        if track.kind != "audio" {
            for clip in &track.clips {
                if let Some(id) = clip.asset_id.as_deref() {
                    ids.insert(id.to_string());
                }
            }
        }
    }
    for id in ids {
        if !doc.asset_images.contains(&id) {
            if let Some(source) = doc.originals.get(&id) {
                spawn_local_proxy(doc.asset_dir.clone(), id, source.clone());
            }
        }
    }
}

/// Local (JST, UTC+9 fixed) compact timestamp for default export filenames.
/// Same civil-from-days math as iso8601_utc_now — no chrono dependency.
fn jst_timestamp_compact() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
        + 9 * 3600;
    let days = secs.div_euclid(86400);
    let sod = secs.rem_euclid(86400);
    let (h, mi) = (sod / 3600, (sod % 3600) / 60);
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    format!("{y:04}{m:02}{d:02}_{h:02}{mi:02}")
}

/// ISO8601 UTC now without a chrono dependency (Howard Hinnant civil-from-days).
/// assets.json records must carry created_at/updated_at to satisfy the API schema.
fn iso8601_utc_now() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    let days = secs.div_euclid(86400);
    let sod = secs.rem_euclid(86400);
    let (h, mi, s) = (sod / 3600, (sod % 3600) / 60, sod % 60);
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    format!("{y:04}-{m:02}-{d:02}T{h:02}:{mi:02}:{s:02}+00:00")
}

/// OS cursor position in egui points for this window, straight from Win32.
/// winit's Windows file-drop handler discards the OLE drag coordinates
/// (DragEnter/DragOver/Drop all ignore their POINTL argument) and the OLE mouse
/// capture means no WM_MOUSEMOVE reaches the window either, so for the whole
/// OS drag gesture — including the drop frame — egui's interact_pos/hover_pos
/// are None. GetCursorPos is the only live position source during that window.
/// レーンid採番用のソルト。プロセス内カウンタだとセッションを跨いで衝突するので
/// エポックms（1回のドラッグ/ドロップ/ロード毎に1つ）を使う。
fn lane_salt() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

/// 時間区間の開始順ソート＋重なり・隣接マージ。
fn merge_time_ranges(mut v: Vec<(f64, f64)>) -> Vec<(f64, f64)> {
    v.sort_by(|x, y| x.0.total_cmp(&y.0));
    let mut m: Vec<(f64, f64)> = Vec::new();
    for r in v {
        if let Some(last) = m.last_mut() {
            if r.0 <= last.1 + 1e-6 {
                last.1 = last.1.max(r.1);
                continue;
            }
        }
        m.push(r);
    }
    m
}

/// クリップのカラーグレード係数（コンポジタの set_grade へ渡す形）。
/// 全て既定値なら None（グレード無効＝コストゼロ）。
fn grade_params(c: &model::Clip) -> Option<[f32; 6]> {
    let g = c.grade.as_ref()?;
    let f = |k: &str, d: f64| g.get(k).and_then(|v| v.as_f64()).unwrap_or(d);
    let mode = match g.get("log").and_then(|v| v.as_str()).unwrap_or("") {
        "slog3" => 2.0f32,
        "vlog" => 3.0,
        "clog3" => 4.0,
        _ => 1.0,
    };
    let (ev, ct, sat, temp, tint) =
        (f("ev", 0.0), f("contrast", 1.0), f("sat", 1.0), f("temp", 0.0), f("tint", 0.0));
    if mode == 1.0 && ev == 0.0 && ct == 1.0 && sat == 1.0 && temp == 0.0 && tint == 0.0 {
        return None;
    }
    Some([mode, ev as f32, ct as f32, sat as f32, temp as f32, tint as f32])
}

/// Timeline thumbnail for IMAGE assets. The normal thumbnailer decodes via Media
/// Foundation, which has no still-image path — every image clip therefore fell
/// back to the flat grey placeholder. Decode with the image crate instead.
fn image_thumb(path: &str, max_w: usize) -> Option<(usize, usize, Vec<u8>)> {
    let img = image::open(path).ok()?;
    let w = img.width().max(1);
    let scale = (max_w as f32 / w as f32).min(1.0);
    let tw = ((w as f32 * scale) as u32).max(1);
    let th = ((img.height().max(1) as f32 * scale) as u32).max(1);
    let small = img.thumbnail(tw, th).to_rgba8();
    Some((small.width() as usize, small.height() as usize, small.into_raw()))
}

fn os_cursor_in_ui(ctx: &egui::Context) -> Option<egui::Pos2> {
    let (inner, ppp) = ctx.input(|i| (i.viewport().inner_rect, i.pixels_per_point()));
    let inner = inner?;
    let mut p = windows::Win32::Foundation::POINT::default();
    unsafe { windows::Win32::UI::WindowsAndMessaging::GetCursorPos(&mut p).ok()? };
    Some(egui::pos2(p.x as f32 / ppp - inner.min.x, p.y as f32 / ppp - inner.min.y))
}

fn is_timeline_media_path(path: &std::path::Path) -> bool {
    is_image_path(path)
        || matches!(
            path.extension().and_then(|e| e.to_str()).unwrap_or("").to_ascii_lowercase().as_str(),
            "mp4" | "mov" | "mkv" | "webm" | "m4v"
        )
}

/// Pure audio files (BGM / SE / narration): dropped onto the timeline they land on the
/// AUDIO lane, not a visual lane. Media Foundation decodes all of these directly.
fn is_audio_path(path: &std::path::Path) -> bool {
    matches!(
        path.extension().and_then(|e| e.to_str()).unwrap_or("").to_ascii_lowercase().as_str(),
        "mp3" | "wav" | "m4a" | "aac" | "flac" | "ogg" | "opus" | "wma"
    )
}

const TIMELINE_FPS_CHOICES: [f64; 8] = [23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0];

fn canonical_timeline_fps(fps: f64) -> f64 {
    TIMELINE_FPS_CHOICES
        .iter()
        .copied()
        .min_by(|a, b| (fps - *a).abs().total_cmp(&(fps - *b).abs()))
        .filter(|candidate| (fps - *candidate).abs() <= 1.0)
        .unwrap_or(30.0)
}

fn fps_label(fps: f64) -> &'static str {
    if (fps - 23.976).abs() < 0.01 { "23.976 fps" }
    else if (fps - 24.0).abs() < 0.01 { "24 fps" }
    else if (fps - 25.0).abs() < 0.01 { "25 fps" }
    else if (fps - 29.97).abs() < 0.01 { "29.97 fps" }
    else if (fps - 50.0).abs() < 0.01 { "50 fps" }
    else if (fps - 59.94).abs() < 0.01 { "59.94 fps" }
    else if (fps - 60.0).abs() < 0.01 { "60 fps" }
    else { "30 fps" }
}

/// Open ONE not-yet-open decoder instance per call (idle time only). Returns true when
/// every stream the timeline can hit is pre-opened, so playback never pays an open.
/// CAPPED: decoders are GPU memory — warming a whole long timeline exhausted VRAM
/// (0x8007000E on the next mid-play open). Past the cap, the near-playhead warmer
/// (warm_upcoming) and the LRU eviction cover playback.
fn warm_open_pass(
    doc: &model::Doc,
    d3d: &media::D3d,
    pool: &mut media::VideoPool,
    masks: &MaskMap,
    center: f64,
) -> bool {
    const INSTANCE_CAP: usize = 12;
    if pool.stats().1 >= INSTANCE_CAP {
        return true; // budget spent — treat as warm
    }
    use std::collections::HashMap;
    let mut count: HashMap<String, usize> = HashMap::new();
    let mut spans: HashMap<String, Vec<(f64, f64)>> = HashMap::new();
    let mut pops: Vec<(String, bool)> = Vec::new(); // (path, is_matte_twin)
    for tr in &doc.seq.tracks {
        if tr.kind == "audio" {
            continue;
        }
        for c in &tr.clips {
            if c.timeline_end < center - 3.0 || c.timeline_start > center + 10.0 {
                continue;
            }
            if let Some((key, _)) = c.popout_key() {
                let live = masks.get(&key).map_or(false, |o| o.is_some());
                if live {
                    // live path decodes the matte twin + the ORIGINAL (counted below)
                    let p = doc.rel_path(&format!("popout-cache/{key}.mt.mp4"));
                    if !pops.iter().any(|(q, _)| *q == p) {
                        pops.push((p, true));
                    }
                    if let Some(aid) = c.asset_id.as_deref() {
                        let p = doc.asset_path_q(aid, true);
                        *count.entry(p.clone()).or_default() += 1;
                        spans.entry(p).or_default().push((c.timeline_start, c.timeline_end));
                    }
                } else {
                    let p = doc.rel_path(&format!("popout-cache/{key}.pv.mp4"));
                    if std::path::Path::new(&p).exists() && !pops.iter().any(|(q, _)| *q == p) {
                        pops.push((p, false));
                    }
                }
            } else if let Some(aid) = c.asset_id.as_deref() {
                let p = doc.asset_path_q(aid, true);
                *count.entry(p.clone()).or_default() += 1;
                spans.entry(p).or_default().push((c.timeline_start, c.timeline_end));
            }
        }
    }
    for (path, n) in count {
        // instances = max simultaneous on-screen uses of this file (fullscreen + wipe of
        // the same source overlap!) + 1 spare for boundary ping-pong
        let ss = spans.get(&path).cloned().unwrap_or_default();
        let mut concurrent = 1usize;
        for (i, a) in ss.iter().enumerate() {
            let mut o = 1;
            for (j, b) in ss.iter().enumerate() {
                if i != j && a.0 < b.1 && b.0 < a.1 {
                    o += 1;
                }
            }
            concurrent = concurrent.max(o.min(2));
        }
        let want = if n >= 2 { concurrent + 1 } else { 1 };
        if !pool.has_instances(&path, 0, want) {
            let _ = pool.warm_open(d3d, &path, 0, false, want);
            return false; // one open per idle slice
        }
    }
    for (p, is_mt) in pops {
        // matte twin: both tracks full range; pv: ordinal 0 = matte (full), 1 = color
        let ranges: [(u32, bool); 2] = if is_mt { [(0, true), (1, true)] } else { [(0, true), (1, false)] };
        for (s, fr) in ranges {
            if !pool.has_instances(&p, s, 1) {
                let _ = pool.warm_open(d3d, &p, s, fr, 1);
                return false;
            }
        }
    }
    // scrub proxies: the drag path decodes these — a cold open on the first drag is a
    // visible hitch
    let mut proxies: Vec<String> = Vec::new();
    for tr in &doc.seq.tracks {
        if tr.kind == "audio" {
            continue;
        }
        for c in &tr.clips {
            if c.timeline_end < center - 3.0 || c.timeline_start > center + 10.0 {
                continue;
            }
            if let Some(aid) = c.asset_id.as_deref() {
                let p = doc.asset_path(aid);
                if std::path::Path::new(&p).exists() && !proxies.contains(&p) {
                    proxies.push(p);
                }
            }
        }
    }
    for p in proxies {
        if !pool.has_instances(&p, 0, 1) {
            let _ = pool.warm_open(d3d, &p, 0, false, 1);
            return false;
        }
    }
    true
}

/// Presenter: its ONLY job is moving the right ring frame to the screen every few ms.
/// It never decodes, never composes, never waits on production — so a slow production
/// step can only ever drain the ring, never delay presentation itself.
fn presenter_thread(shared: Arc<Shared>) {
    let mut published_t = -1.0f64;
    let mut last_pub: Option<Instant> = None;
    let mut session_gap_max = 0.0f32;
    let mut seen_gen = u64::MAX;
    let mut seq_hi = 1_000_000u64;
    loop {
        let playing = shared.req.lock().unwrap().playing;
        if !playing {
            published_t = -1.0;
            last_pub = None;
            session_gap_max = 0.0;
            std::thread::sleep(std::time::Duration::from_millis(6));
            continue;
        }
        let g = shared.ring_gen.load(Ordering::Relaxed);
        if g != seen_gen {
            seen_gen = g;
            published_t = -1.0;
            last_pub = None;
            session_gap_max = 0.0;
        }
        let t = f64::from_bits(shared.clock_bits.load(Ordering::Relaxed));
        let target = f64::from_bits(shared.ring_target_bits.load(Ordering::Relaxed));
        if (target - t).abs() > 0.5 {
            // mid-play seek in flight: the ring belongs to the NEW position, the clock is
            // still at the old one — popping "stale" frames here would eat the rebuild
            last_pub = None;
            std::thread::sleep(std::time::Duration::from_millis(4));
            continue;
        }
        let mut grabbed: Option<(f64, f64, Frame)> = None;
        {
            let timeline_fps = shared.doc.lock().unwrap().seq.frame_rate
                .filter(|fps| fps.is_finite() && *fps > 1.0)
                .unwrap_or(30.0);
            let frame_step = 1.0 / timeline_fps;
            let mut ring = shared.ring.lock().unwrap();
            while ring.front().map(|(ft, ..)| *ft < t - frame_step).unwrap_or(false) {
                ring.pop_front();
            }
            if let Some((ft, ..)) = ring.iter().rev().find(|(ft, ..)| *ft <= t) {
                let ft = *ft;
                if ft > published_t {
                    if let Some((_, eff, frame)) = ring.iter().find(|(x, ..)| *x == ft) {
                        // Gpu frames clone as an Arc pointer — presentation no
                        // longer moves pixels at all.
                        grabbed = Some((ft, *eff, frame.clone()));
                    }
                }
            }
            shared.ring_level.store(ring.len(), Ordering::Relaxed);
        }
        if grabbed.is_none() {
            if let Some(lp) = last_pub {
                let idle = lp.elapsed().as_secs_f32() * 1000.0;
                if idle > 500.0 && idle % 500.0 < 8.0 {
                    let (fr, ba, ln) = {
                        let rg = shared.ring.lock().unwrap();
                        (rg.front().map(|(f2, ..)| *f2), rg.back().map(|(b2, ..)| *b2), rg.len())
                    };
                    eprintln!("PRES-IDLE {idle:.0}ms t={t:.2} pub={published_t:.2} ring={ln} front={fr:?} back={ba:?}");
                }
            }
        }
        if let Some((ft, eff, frame)) = grabbed {
            let now = Instant::now();
            seq_hi += 1;
            let mut f = shared.frame.lock().unwrap();
            match frame {
                Frame::Gpu(tex) => f.tex = Some(tex),
                Frame::Cpu(rgba) => {
                    f.rgba = rgba;
                    f.tex = None;
                }
            }
            f.seq = seq_hi;
            f.t = ft;
            f.eff_t = eff;
            f.quality = "proxy";
            if let Some(lp) = last_pub {
                let gms = now.duration_since(lp).as_secs_f32() * 1000.0;
                if gms > session_gap_max {
                    session_gap_max = gms;
                }
                if gms > 120.0 {
                    eprintln!("GAP {gms:.0}ms at timeline t={ft:.2} (clock {t:.2})");
                }
            }
            f.gap_max = session_gap_max;
            last_pub = Some(now);
            published_t = ft;
        }
        std::thread::sleep(std::time::Duration::from_millis(4));
    }
}

#[cfg(target_os = "windows")]
fn process_handle_count() -> u32 {
    use windows::Win32::System::Threading::{GetCurrentProcess, GetProcessHandleCount};
    let mut n = 0u32;
    unsafe {
        let _ = GetProcessHandleCount(GetCurrentProcess(), &mut n);
    }
    n
}

/// Snapshot the composed canvas into a pooled GPU texture for presentation —
/// the GPU-direct replacement for readback. On failure the GPU path is disabled
/// for the session and callers fall back to CPU pixels.
fn snapshot_canvas(
    shared: &Shared,
    d3d: &media::D3d,
    comp: &compositor::Compositor,
    gpu_pool: &Arc<gpu_present::TexPool>,
) -> Option<Arc<gpu_present::GpuTex>> {
    match gpu_pool.acquire() {
        Ok(tex) => {
            comp.copy_canvas_to(d3d, &tex.tex);
            // Submit now so the UI-side interop lock observes the finished copy.
            unsafe { d3d.ctx.Flush() };
            Some(tex)
        }
        Err(e) => {
            eprintln!("GPU_PRESENT pool acquire failed — CPU fallback: {e:#}");
            shared.gpu_disabled.store(true, Ordering::Relaxed);
            None
        }
    }
}

fn media_thread(shared: Arc<Shared>) {
    let run = || -> anyhow::Result<()> {
        let d3d = media::D3d::new()?;
        let mut pool = media::VideoPool::new();
        let mut comp = compositor::Compositor::new(&d3d, canvas_w(), canvas_h())?;
        // Presentation pool on the SAME device as the compositor: publishing a
        // frame is one GPU-side CopyResource, never a Map.
        let mut gpu_pool = Arc::new(gpu_present::TexPool::new(d3d.device.clone(), canvas_w(), canvas_h()));
        *shared.gpu_pool.lock().unwrap() = Some(gpu_pool.clone());
        let mut was_playing;
        let mut last_gen = u64::MAX;
        let mut jump_to: Option<f64> = None; // mid-play seek target until the clock follows
        let mut last_t = -1.0f64;
        let mut seq = 0u64;
        let mut peak_scan: Option<(String, media::PeakScan)> = None;
        let mut comp_hist: Vec<(Instant, f32)> = Vec::new();
        let mut gap_hist: Vec<(Instant, f32)> = Vec::new();
        let mut last_pub: Option<Instant> = None;
        let mut warm_done = false;
        let mut last_doc_ptr: usize = 0;
        let mut last_caption_epoch = u64::MAX;
        let mut settle = Instant::now(); // last user interaction (scrub/edit/seek)
        let mut edit_cooldown_until = Instant::now();
        let mut scrub_win: Vec<f32> = Vec::new();
        let mut scrub_t0 = Instant::now();
        let mut scrub_exact = true; // last scrub compose reached the exact frame
        // A PAUSED frame that composed INEXACT (tracked-blur mask / caption texture /
        // decoder momentarily unavailable) must never sit on screen as the final
        // picture — that was the "same frame sometimes shows the blur, sometimes not"
        // instability: nothing re-marked the request dirty, so the provisional pixels
        // stayed until the next user action. Retry until exact (bounded).
        let mut rest_retry: u32 = 0;
        let mut masks: MaskMap = Default::default();
        let mut pts_maps: PtsMap = Default::default();
        let mut fcache = FrameCache::new();
        // idle-fill slots that composed INEXACT (mask/caption not ready): retry later
        // instead of hammering the same frame every idle slice
        let mut fill_defer: std::collections::HashMap<i64, Instant> = Default::default();
        let mut prev_was_compose = false;
        let mut prev_compose_t = f64::NAN;
        let mut prev_compose_eff = f64::NAN;
        let mut resource_check = Instant::now();
        let mut last_resource_recovery = Instant::now() - std::time::Duration::from_secs(60);
        let mut prev_playing = false;
        let mut play_started: Option<Instant> = None;
        // Look-ahead ring: timeline frames composed AHEAD of the playhead on the chosen
        // sequence grid. Presentation picks from the ring and NEVER waits for a decode — GOP walks
        // and source switches are paid in the ring's future (the Filmora mechanism).
        const RING_DEPTH: usize = 12; // ~400ms of slack
        // Speculative paused-idle cache fill is too expensive for structural edits:
        // it composes arbitrary surrounding frames even when the user only needs the
        // current preview and a short play-ahead ring. Keep the cache as an
        // opportunistic playback/scrub accelerator, but do not let it compete with
        // interactive work in the background.
        const IDLE_FRAME_CACHE_FILL: bool = false;
        // Async triple-buffer readback has delayed provenance. It is safe for sequential
        // presentation, but not as a random-access cache entry after a cut/decoder switch.
        const PLAYBACK_FRAME_CACHE_FILL: bool = false;
        // Thumbnail/waveform work has a dedicated worker and must not compete with the
        // preview decoder on this latency-sensitive thread.
        const MEDIA_THREAD_AUX: bool = false;
        loop {
            let hb0 = Instant::now();
            if resource_check.elapsed() >= std::time::Duration::from_secs(2) {
                resource_check = Instant::now();
                d3d.drain_debug("tick");
                let handles = process_handle_count();
                if handles > 6_000
                    && last_resource_recovery.elapsed() >= std::time::Duration::from_secs(15)
                {
                    // Driver/MF resources must never grow until the whole app needs a
                    // restart. Release optional state in-process and cold-open on demand.
                    eprintln!(
                        "RESOURCE_RECOVERY handles={handles} cache={}MB pool={:?}",
                        fcache.bytes / 1024 / 1024,
                        pool.stats()
                    );
                    fcache.clear();
                    pool.clear();
                    masks.clear();
                    comp.clear_transient_caches();
                    gpu_pool.trim(0);
                    unsafe { d3d.ctx.Flush() };
                    warm_done = false;
                    last_resource_recovery = Instant::now();
                }
            }
            let doc: Arc<model::Doc> = shared.doc.lock().unwrap().clone();
            let caption_epoch = shared.caption_epoch.load(Ordering::Relaxed);
            if caption_epoch != last_caption_epoch {
                // A live/pending caption switched owner. Cached/ring pixels may contain
                // its previous GPU render, so neither may be presented again.
                fcache.clear();
                shared.ring.lock().unwrap().clear();
                shared.ring_gen.fetch_add(1, Ordering::Relaxed);
                shared.ring_level.store(0, Ordering::Relaxed);
                last_caption_epoch = caption_epoch;
            }
            let ptr = Arc::as_ptr(&doc) as usize;
            let timeline_fps = doc.seq.frame_rate.filter(|fps| fps.is_finite() && *fps > 1.0).unwrap_or(30.0);
            let frame_step = 1.0 / timeline_fps;
            if ptr != last_doc_ptr {
                last_doc_ptr = ptr;
                warm_done = false;
                // 形式の違うコンテンツへ切替: キャンバス寸法が変わったら
                // コンポジタと提示プールを作り直す（旧寸法のテクスチャは全て無効）
                if comp.width != canvas_w() || comp.height != canvas_h() {
                    eprintln!(
                        "CANVAS_RESIZE {}x{} -> {}x{}",
                        comp.width, comp.height, canvas_w(), canvas_h()
                    );
                    comp = compositor::Compositor::new(&d3d, canvas_w(), canvas_h())?;
                    gpu_pool = Arc::new(gpu_present::TexPool::new(
                        d3d.device.clone(), canvas_w(), canvas_h(),
                    ));
                    *shared.gpu_pool.lock().unwrap() = Some(gpu_pool.clone());
                    fcache.clear();
                    shared.ring.lock().unwrap().clear();
                    shared.ring_gen.fetch_add(1, Ordering::Relaxed);
                    shared.ring_level.store(0, Ordering::Relaxed);
                }
                edit_cooldown_until = Instant::now() + std::time::Duration::from_millis(1500);
                // edited: never show a stale composed frame — but only the frames at/after
                // the earliest change are stale; everything before survives (Filmora keeps
                // its render cache across local edits, the full clear was our post-edit lag)
                let df = f64::from_bits(
                    shared.dirty_from_bits.swap(f64::INFINITY.to_bits(), Ordering::Relaxed),
                );
                let cut = if df.is_finite() { (df - 0.2).max(0.0) } else { 0.0 };
                if df.is_finite() {
                    eprintln!("CACHE_INVAL from={df:.2}");
                    fcache.invalidate_from(cut, timeline_fps);
                } else {
                    eprintln!("CACHE_CLEAR full");
                    fcache.clear(); // unknown provenance (open/undo/redo): full reset
                }
                // the RING holds composed frames too: time-aligned entries survived the
                // doc swap and briefly played PRE-EDIT content after every edit
                {
                    let mut rg = shared.ring.lock().unwrap();
                    let before = rg.len();
                    rg.retain(|(ft, ..)| *ft < cut);
                    if rg.len() != before {
                        shared.ring_gen.fetch_add(1, Ordering::Relaxed);
                    }
                    shared.ring_level.store(rg.len(), Ordering::Relaxed);
                }
            }
            let dur = doc.duration();
            let gpu_on = !shared.gpu_disabled.load(Ordering::Relaxed);
            let r = shared.req.lock().unwrap().clone();
            was_playing = r.playing;
            let _ = was_playing;
            let ms_pre = hb0.elapsed().as_secs_f32() * 1000.0; // doc clone + req lock
            let t = if r.playing {
                f64::from_bits(shared.clock_bits.load(Ordering::Relaxed)).min(dur)
            } else {
                r.t
            };
            // play-start latency: time from the play request to a healthy ring — the
            // measured "video freezes right after an edit while audio runs"
            if r.playing && !prev_playing {
                play_started = Some(Instant::now());
                eprintln!("PLAY_START t={t:.2}");
            }
            prev_playing = r.playing;
            if let Some(ps) = play_started {
                if shared.ring_level.load(Ordering::Relaxed) >= 4 {
                    eprintln!("PLAY_READY {}ms", ps.elapsed().as_millis());
                    play_started = None;
                } else if ps.elapsed().as_secs() > 8 {
                    eprintln!("PLAY_STARVED >8000ms ring={}", shared.ring_level.load(Ordering::Relaxed));
                    play_started = None;
                }
            }
            if r.playing {
                if r.gen != last_gen {
                    last_gen = r.gen;
                    let jump = (r.t - t).abs() > 0.3;
                    let target = if jump { r.t } else { t };
                    {
                        let mut rg = shared.ring.lock().unwrap();
                        let aligned = rg
                            .front()
                            .map(|(ft, ..)| (*ft - target).abs() < 2.0 / 30.0 || (*ft < target && rg.back().map(|(bt, ..)| *bt >= target).unwrap_or(false)))
                            .unwrap_or(false);
                        if !aligned {
                            rg.clear();
                            shared.ring_level.store(0, Ordering::Relaxed);
                            shared.ring_gen.fetch_add(1, Ordering::Relaxed);
                        }
                    }
                    if jump {
                        // seek during playback: SNAP the preview to the new position NOW
                        // (budgeted seek, <~60ms) while the audio gate holds the clock and
                        // the ring rebuilds — no more seconds of frozen video chasing a
                        // running clock
                        jump_to = Some(r.t);
                        if let Ok((_, _, eff)) = compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, r.t, false, true, Rb::Sync) {
                            let tex = if gpu_on { snapshot_canvas(&shared, &d3d, &comp, &gpu_pool) } else { None };
                            seq += 1;
                            let mut f = shared.frame.lock().unwrap();
                            f.tex = tex;
                            f.rgba.clear();
                            f.rgba.extend_from_slice(&comp.rgba);
                            f.seq = seq;
                            f.t = r.t;
                            f.eff_t = eff;
                            f.quality = "proxy";
                            f.caption_epoch = caption_epoch;
                        }
                    }
                }
                if let Some(j) = jump_to {
                    if (t - j).abs() < 0.3 {
                        jump_to = None; // audio restarted at the new position — normal ops
                    }
                }
                let t_build = jump_to.unwrap_or(t);
                shared.ring_target_bits.store(t_build.to_bits(), Ordering::Relaxed);
                let (next_t, len) = {
                    let rg = shared.ring.lock().unwrap();
                    (
                        rg.back().map(|(ft, ..)| ft + frame_step).unwrap_or_else(|| (t_build / frame_step).floor() * frame_step),
                        rg.len(),
                    )
                };
                let (mut ms_comp, mut ms_push, mut ms_prime) = (0f32, 0f32, 0f32);
                let mut slept = false;
                let target_depth = if r.speed >= 3.0 {
                    RING_DEPTH * 4
                } else if r.speed >= 1.5 {
                    RING_DEPTH * 2
                } else {
                    RING_DEPTH
                };
                if len < target_depth && next_t <= dur {
                    let t0 = Instant::now();
                    // cache hit = decompress instead of compose (jump refills become ~instant)
                    let mut cached_buf: Vec<u8> = Vec::new();
                    let cache_eff = fcache.get(next_t, timeline_fps, frame_step * 0.51, &mut cached_buf);
                    let from_cache = cache_eff.is_some();
                    let res = if let Some(eff) = cache_eff {
                        Ok((Vec::new(), true, eff))
                    } else {
                        // GPU-direct playback: NO readback at all — a video/text/image
                        // dense span can no longer stall the producer on a GPU map.
                        // A ring entry is presented later as the frame for `next_t`.
                        // Unlike interactive scrubbing it may not contain a provisional
                        // decoder surface: that turns a freeze->video seam into a whole
                        // run of the freeze's last frame. The ring has decode-ahead slack,
                        // so wait for the exact source frame here.
                        compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, next_t, false, false, if gpu_on { Rb::None } else { Rb::Async })
                    };
                    ms_comp = t0.elapsed().as_secs_f32() * 1000.0;
                    match res {
                        Ok((used, exact, eff)) => {
                            // Keep the ring's time/pixel contract even if a future render
                            // path accidentally becomes budgeted again. Presenting an
                            // inexact canvas is worse than leaving this slot unfilled:
                            // audio can continue while a stale picture masquerades as video.
                            if !exact {
                                eprintln!("RING_REJECT provisional frame at t={next_t:.3}");
                                std::thread::sleep(std::time::Duration::from_millis(1));
                                continue;
                            }
                            if ms_comp > 60.0 {
                                eprintln!("SLOWPROD t={next_t:.2}: {ms_comp:.0}ms");
                            }
                            let p0 = Instant::now();
                            let payload = if from_cache {
                                Frame::Cpu(cached_buf.clone())
                            } else if gpu_on {
                                match snapshot_canvas(&shared, &d3d, &comp, &gpu_pool) {
                                    Some(t) => Frame::Gpu(t),
                                    None => Frame::Cpu(comp.rgba.clone()),
                                }
                            } else {
                                Frame::Cpu(comp.rgba.clone())
                            };
                            {
                                let mut rg = shared.ring.lock().unwrap();
                                rg.push_back((next_t, eff, payload));
                                // never trim against the OLD clock while a jump is pending —
                                // a backward seek's fresh frames all look "stale" to it
                                if jump_to.is_none() {
                                    while rg.front().map(|(ft, ..)| *ft < t - 2.0 * frame_step).unwrap_or(false) {
                                        rg.pop_front();
                                    }
                                }
                                shared.ring_level.store(rg.len(), Ordering::Relaxed);
                            }
                            if PLAYBACK_FRAME_CACHE_FILL
                                && !from_cache
                                && prev_was_compose
                                && len >= 6
                                && ms_comp < 25.0
                            {
                                // cheap frames get cached opportunistically (lz4 ~5ms).
                                // ASYNC readback returns the PREVIOUS compose's pixels, so
                                // the content belongs to the previous sequence frame — keying it at
                                // next_t poisoned the cache with shifted frames (the
                                // "ちらちら" flicker on jumps into cached spans)
                                // PROVENANCE CHECK: the compensation assumes the previous
                                // compose was exactly one sequence frame earlier — log when it wasn't
                                // (jump seams would cache WRONG-time pixels)
                                if (prev_compose_t - (next_t - frame_step)).abs() > 1e-4 {
                                    eprintln!(
                                        "CACHE_PUT_WRONG key={:.3} pixels_from={prev_compose_t:.3}",
                                        next_t - frame_step
                                    );
                                } else if near_freeze(&doc, next_t) {
                                    eprintln!("CACHE_PUT key={:.3} ok", next_t - frame_step);
                                }
                                // pixels are the PREVIOUS compose's (async readback) — so
                                // is their effective time
                                fcache.insert(next_t - frame_step, timeline_fps, prev_compose_eff, &comp.rgba, t);
                            }
                            prev_was_compose = !from_cache;
                            prev_compose_t = next_t;
                            if !from_cache {
                                prev_compose_eff = eff;
                            }
                            ms_push = p0.elapsed().as_secs_f32() * 1000.0;
                            // prime whenever we can afford it: a shallow ring is USUALLY
                            // the rapid-boundary case (0.2-2s clips) that needs priming the
                            // most — the old len>=8 gate starved exactly those boundaries
                            // (measured as 200-500ms GAPs at clip joins)
                            if len >= 4 || ms_comp < 15.0 {
                                let p1 = Instant::now();
                                prime_upcoming(&doc, &d3d, &mut pool, &masks, next_t, true, &used);
                                ms_prime = p1.elapsed().as_secs_f32() * 1000.0;
                                if ms_prime > 60.0 {
                                    eprintln!("SLOWPRIME t={next_t:.2}: {ms_prime:.0}ms");
                                }
                            }
                        }
                        // errors were invisible to SLOWPROD — a failing compose that takes
                        // 100ms+ per attempt looks like "producer stopped for no reason"
                        Err(e) => {
                            let msg = format!("{e:#}");
                            eprintln!("compose ERR t={next_t:.2} after {ms_comp:.0}ms: {msg}");
                            {
                                let r = unsafe { d3d.device.GetDeviceRemovedReason() };
                                eprintln!("DEVICE_STATE {r:?}");
                                d3d.drain_debug("err");
                            }
                            if msg.contains("0x8007000E") {
                                // out of (GPU) memory: dump idle decoder instances NOW
                                pool.evict_stale(120);
                            }
                            std::thread::sleep(std::time::Duration::from_millis(30));
                        }
                    }
                    if pool.frame_no % 120 == 0 {
                        pool.evict_stale(900); // ~30s of composes — passed pop-outs get freed
                        // Olive uses 5s normal / 1s during playback; our opens are ~100x
                        // costlier, so 12s and playback-only
                        pool.evict_idle(std::time::Duration::from_secs(12));
                        // presentation textures beyond the ring's working set go back
                        // to the driver (a 3x-speed burst must not park VRAM forever)
                        gpu_pool.trim(RING_DEPTH + 4);
                        // Submit queued GPU work so completed decoder views are released
                        // during long playback instead of accumulating until restart.
                        unsafe { d3d.ctx.Flush() };
                    }
                    if pool.frame_no % 300 == 0 {
                        let (nf, ni) = pool.stats();
                        eprintln!("POOL files={nf} instances={ni}");
                    }
                } else {
                    slept = true;
                    if !warm_upcoming(&doc, &d3d, &mut pool, &masks, t) {
                        std::thread::sleep(std::time::Duration::from_millis(2));
                    }
                }
                // heartbeat: name ANY producer iteration that starved the ring, with the
                // stage that ate the time (the t≈54 stall showed no SLOWPROD — the block
                // is outside the old timed regions)
                let tot = hb0.elapsed().as_secs_f32() * 1000.0;
                if tot > 100.0 && !(slept && tot < 110.0) {
                    eprintln!(
                        "HEART {tot:.0}ms t={t:.2} next={next_t:.2} ring={len} pre={ms_pre:.0} comp={ms_comp:.0} push={ms_push:.0} prime={ms_prime:.0} slept={slept}"
                    );
                }
                last_t = t;
                continue;
            }
            // PAUSED: keep the ring pre-built ahead of the playhead so pressing play is
            // instant (the ~1s start hole was the ring warming up from empty)
            if r.gen != last_gen || r.scrubbing {
                // ANY interaction pushes background work out of the way — pre-build, warm
                // opens and thumbnails restart only after ~200ms of stillness. Sharing this
                // thread with 200ms background composes is what broke scrub tracking.
                settle = Instant::now();
            }
            if r.gen != last_gen {
                warm_done = false;
                if last_t >= 0.0 && (t - last_t).abs() > 3.0 {
                    // A far scrub/jump changes the decoder working set. Do not retain the
                    // old location's sessions and then open another complete set.
                    pool.clear();
                }
                shared.ring.lock().unwrap().clear();
                shared.ring_gen.fetch_add(1, Ordering::Relaxed);
            }
            let settled = !r.scrubbing && settle.elapsed().as_secs_f32() > 0.2;
            let dirty = r.gen != last_gen || (t - last_t).abs() > 1e-6;
            if dirty && {
                // composed-frame cache first: scrub/settle over a cached span shows the
                // ORIGINAL-quality frame in ~5ms without touching a decoder
                let mut buf = Vec::new();
                if let Some(eff) = fcache.get(t, timeline_fps, 0.005, &mut buf) {
                    if near_freeze(&doc, t) {
                        eprintln!("SERVE t={t:.3} src=cache");
                    }
                    if BLUR_DBG.load(Ordering::Relaxed) {
                        eprintln!("BLURSERVE t={t:.3} src=cache");
                    }
                    seq += 1;
                    let mut f = shared.frame.lock().unwrap();
                    f.tex = None; // cached CPU pixels — display via the CPU path
                    f.rgba = buf;
                    f.seq = seq;
                    f.t = t;
                    f.eff_t = eff;
                    f.comp_ms = 0.0;
                    f.quality = "proxy";
                    f.caption_epoch = caption_epoch;
                    scrub_exact = true;
                    last_gen = r.gen;
                    last_t = t;
                    false // handled — skip the compose branch
                } else {
                    true
                }
            } {
                // ONE pipeline, ONE quality: everything (play, scrub, pause, cache,
                // stills) renders from the HIGH-QUALITY proxy. The old settle-to-original
                // pass made every source switch a visible seam (quality/geometry deltas);
                // Filmora's preview is uniformly proxy too — that IS its stability.
                let original = false;
                let t0 = Instant::now();
                let mut landed_exact = false;
                match compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, t, original, r.scrubbing, Rb::Sync) {
                    Ok((used, exact, eff)) => {
                        landed_exact = exact;
                        scrub_exact = !r.scrubbing || exact;
                        let tex = if gpu_on { snapshot_canvas(&shared, &d3d, &comp, &gpu_pool) } else { None };
                        seq += 1;
                        {
                            let mut f = shared.frame.lock().unwrap();
                            f.tex = tex;
                            f.rgba.clear();
                            f.rgba.extend_from_slice(&comp.rgba);
                            f.seq = seq;
                            f.t = t;
                            f.eff_t = eff;
                            f.comp_ms = t0.elapsed().as_secs_f32() * 1000.0;
                            let now = Instant::now();
                            comp_hist.push((now, f.comp_ms));
                            comp_hist.retain(|(t2, _)| now.duration_since(*t2).as_secs_f32() < 1.0);
                            f.comp_max = comp_hist.iter().map(|(_, v)| *v).fold(0.0, f32::max);
                            last_pub = Some(now);
                            f.quality = "proxy";
                            f.caption_epoch = caption_epoch;
                        }
                        let _ = used;
                    }
                    Err(e) => {
                        let msg = format!("{e:#}");
                        eprintln!("compose: {msg}");
                        if msg.contains("0x887A0005") {
                            let r = unsafe { d3d.device.GetDeviceRemovedReason() };
                            eprintln!("DEVICE_REMOVED reason={r:?}");
                        }
                    }
                }
                if r.scrubbing {
                    // scrub responsiveness meter: frames delivered per second while dragging
                    scrub_win.push(t0.elapsed().as_secs_f32() * 1000.0);
                    if scrub_t0.elapsed().as_secs_f32() >= 1.0 {
                        let n = scrub_win.len();
                        let avg = scrub_win.iter().sum::<f32>() / n as f32;
                        let worst = scrub_win.iter().copied().fold(0.0, f32::max);
                        eprintln!("SCRUB {n}fps avg={avg:.0}ms worst={worst:.0}ms");
                        scrub_win.clear();
                        scrub_t0 = Instant::now();
                    }
                } else {
                    scrub_win.clear();
                    scrub_t0 = Instant::now();
                }
                // PAUSED + provisional result (or compose error): leave the request
                // dirty and recompose until the exact frame lands. Without this, a
                // one-shot mask/caption/decoder hiccup left wrong pixels on screen as
                // the FINAL state — the intermittent "blur missing on this frame" bug.
                // Bounded (~3s) so a permanently missing resource cannot spin forever;
                // any later edit/seek resets the budget.
                if !r.playing && !r.scrubbing && !landed_exact && rest_retry < 120 {
                    rest_retry += 1;
                    if rest_retry == 1 || rest_retry % 40 == 0 {
                        eprintln!("REST_RETRY t={t:.3} attempt={rest_retry}");
                    }
                    std::thread::sleep(std::time::Duration::from_millis(25));
                    continue;
                }
                rest_retry = 0;
                last_gen = r.gen;
                last_t = t;
            } else if !settled {
                // refine only once the pointer actually RESTS — refining between drag
                // ticks kept compose+readback running back-to-back, saturating the GPU
                // queue and stalling every decoder ReadSample behind it (~50ms/sample)
                let resting = settle.elapsed().as_secs_f32() > 0.12;
                if r.scrubbing && !scrub_exact && resting {
                    let mut buf = Vec::new();
                    if let Some(eff) = fcache.get(t, timeline_fps, 0.005, &mut buf) {
                        if near_freeze(&doc, t) {
                            eprintln!("SERVE t={t:.3} src=cache-rest");
                        }
                        seq += 1;
                        let mut f = shared.frame.lock().unwrap();
                        f.tex = None; // cached CPU pixels — display via the CPU path
                        f.rgba = buf;
                        f.seq = seq;
                        f.t = t;
                        f.eff_t = eff;
                        f.quality = "proxy";
                        f.caption_epoch = caption_epoch;
                        scrub_exact = true;
                        std::thread::sleep(std::time::Duration::from_millis(2));
                        continue;
                    }
                    // finger resting mid-drag on a long-GOP spot: keep refining toward the
                    // exact frame, one budget slice per pass (converges like Filmora's
                    // "stop and the picture sharpens to the real frame")
                    if let Ok((_, ex, eff)) = compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, t, false, true, Rb::Sync) {
                        scrub_exact = ex;
                        let tex = if gpu_on { snapshot_canvas(&shared, &d3d, &comp, &gpu_pool) } else { None };
                        seq += 1;
                        let mut f = shared.frame.lock().unwrap();
                        f.tex = tex;
                        f.rgba.clear();
                        f.rgba.extend_from_slice(&comp.rgba);
                        f.seq = seq;
                        f.t = t;
                        f.eff_t = eff;
                        f.quality = "proxy";
                        f.caption_epoch = caption_epoch;
                    } else {
                        scrub_exact = true; // failed — stop hammering
                    }
                } else {
                    // interaction in flight: keep this thread FREE so the next scrub frame
                    // starts the instant it arrives
                    std::thread::sleep(std::time::Duration::from_millis(2));
                }
            } else if Instant::now() < edit_cooldown_until {
                // Right after a structural edit (freeze/ripple/split), the user needs the
                // current frame back more than speculative ring/cache/mask warming. Let the
                // required settle compose above run, then give the UI/decoder queues a short
                // quiet window before background work resumes.
                std::thread::sleep(std::time::Duration::from_millis(8));
            } else if shared.ring.lock().unwrap().len() < RING_DEPTH {
                // FIRST: pre-build the ring ahead of the frozen playhead so pressing play
                // is instant — compose opens the decoders it needs on demand, so this must
                // not wait behind the full warm pass (59 files ≈ tens of seconds)
                let next_t = {
                    let rg = shared.ring.lock().unwrap();
                    rg.back().map(|(ft, ..)| ft + frame_step).unwrap_or_else(|| (t / frame_step).floor() * frame_step)
                };
                if next_t <= dur {
                    if let Ok((_, _, eff)) = compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, next_t, false, false, if gpu_on { Rb::None } else { Rb::Async }) {
                        let payload = if gpu_on {
                            match snapshot_canvas(&shared, &d3d, &comp, &gpu_pool) {
                                Some(t) => Frame::Gpu(t),
                                None => Frame::Cpu(comp.rgba.clone()),
                            }
                        } else {
                            Frame::Cpu(comp.rgba.clone())
                        };
                        let mut rg = shared.ring.lock().unwrap();
                        rg.push_back((next_t, eff, payload));
                        shared.ring_level.store(rg.len(), Ordering::Relaxed);
                    }
                } else {
                    std::thread::sleep(std::time::Duration::from_millis(2));
                }
            } else if {
                let p0 = Instant::now();
                let r2 = mask_build_pass(&doc, &d3d, &mut masks, Some(t));
                if p0.elapsed().as_millis() > 80 {
                    eprintln!("PASS mask {}ms", p0.elapsed().as_millis());
                }
                r2
            } {
                // pop-out card masks for the live matte path — one σ26 blur per slice.
                // BEFORE the warm pass: few and quick, and without them pop-outs render
                // from the stale pv twin
            } else if pts_load_pass(&doc, &mut pts_maps) {
                // frame-pts tables for exact proxy<->original settling
            } else if !warm_done {
                // THEN: open every decoder the rest of the timeline needs (a cold open
                // mid-play is a 100-200ms media-thread stall = visible gap)
                let p0 = Instant::now();
                warm_done = warm_open_pass(&doc, &d3d, &mut pool, &masks, t);
                if p0.elapsed().as_millis() > 80 {
                    eprintln!("PASS warm {}ms", p0.elapsed().as_millis());
                }
            } else if IDLE_FRAME_CACHE_FILL && shared.aux_req.lock().unwrap().is_empty() && {
                // Olive-style background fill: compose ORIGINAL-quality frames outward
                // from the playhead into the frame cache (one per idle slice). AFTER
                // thumbnails/waveforms (visible UI beats invisible cache warmth).
                let mut target = None;
                'fill: for step in 0..(45.0 * timeline_fps) as i64 {
                    for dir in [1i64, -1i64] {
                        let idx = FrameCache::idx(t, timeline_fps) + dir * step;
                        if idx < 0 {
                            continue;
                        }
                        let ft = idx as f64 / timeline_fps;
                        if ft > dur {
                            continue;
                        }
                        if !fcache.contains(ft, timeline_fps)
                            && fill_defer
                                .get(&idx)
                                .map(|at| at.elapsed().as_secs_f32() > 5.0)
                                .unwrap_or(true)
                        {
                            target = Some(ft);
                            break 'fill;
                        }
                    }
                }
                if let Some(ft) = target {
                    if let Ok((_, ex, eff)) = compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, ft, false, false, Rb::Sync) {
                        // EXACT frames only. A compose whose tracked-blur mask (or caption
                        // PNG) wasn't ready returns Ok(exact=false) with the effect stale or
                        // missing — caching that poisoned the slot FOREVER (insert never
                        // overwrites), and frame-stepping then showed "blur off" on a frame
                        // that recomposes correctly: the user-reported direction/history
                        // dependent preview. Inexact slots stay empty and refill next idle.
                        if ex {
                            fcache.insert(ft, timeline_fps, eff, &comp.rgba, t);
                            fill_defer.remove(&FrameCache::idx(ft, timeline_fps));
                        } else {
                            fill_defer.insert(FrameCache::idx(ft, timeline_fps), Instant::now());
                        }
                    }
                    if fcache.frames.len() % 300 == 0 {
                        eprintln!(
                            "FCACHE frames={} mb={} hit={} miss={}",
                            fcache.frames.len(),
                            fcache.bytes / 1_048_576,
                            fcache.hits,
                            fcache.misses
                        );
                    }
                    true
                } else {
                    false
                }
            } {
                // filled one cache frame this slice
            } else if !MEDIA_THREAD_AUX {
                std::thread::sleep(std::time::Duration::from_millis(3));
            } else {
                // Legacy fallback: the dedicated aux thread normally owns these jobs.
                let job = { shared.aux_req.lock().unwrap().first().cloned() };
                match job {
                    Some(AuxJob::Thumb { asset_id, path, bucket }) => {
                        let tt = bucket as f64 * THUMB_BUCKET_S + THUMB_BUCKET_S * 0.5;
                        let got = if is_image_path(std::path::Path::new(&path)) {
                            image_thumb(&path, 96)
                        } else {
                            media::thumbnail(&d3d, &path, tt, 96).ok()
                        };
                        {
                            let mut a = shared.aux.lock().unwrap();
                            if let Some(t) = got {
                                a.thumbs.insert((asset_id.clone(), bucket), t);
                            } else {
                                a.thumbs.insert((asset_id.clone(), bucket), (1, 1, vec![40, 40, 40, 255]));
                            }
                            a.ver += 1;
                        }
                        shared.aux_req.lock().unwrap().retain(
                            |j| !matches!(j, AuxJob::Thumb { asset_id: a2, bucket: b2, .. } if *a2 == asset_id && *b2 == bucket),
                        );
                    }
                    Some(AuxJob::Peaks { asset_id, path }) => {
                        if peak_scan.as_ref().map(|(id, _)| id != &asset_id).unwrap_or(true) {
                            peak_scan = media::PeakScan::new(&path).ok().map(|p| (asset_id.clone(), p));
                        }
                        let mut finished = false;
                        if let Some((_, sc)) = peak_scan.as_mut() {
                            let _ = sc.step();
                            if sc.done {
                                let mut a = shared.aux.lock().unwrap();
                                a.peaks.insert(asset_id.clone(), (sc.spb(), std::mem::take(&mut sc.peaks)));
                                a.ver += 1;
                                finished = true;
                            }
                        } else {
                            finished = true; // open failed — drop the job
                        }
                        if finished {
                            peak_scan = None;
                            shared.aux_req.lock().unwrap().retain(|j| !matches!(j, AuxJob::Peaks { asset_id: a2, .. } if *a2 == asset_id));
                        }
                    }
                    None => std::thread::sleep(std::time::Duration::from_millis(3)),
                }
            }
        }
    };
    if let Err(e) = run() {
        eprintln!("media thread died: {e:#}");
    }
}

fn aux_thread(shared: Arc<Shared>) {
    let run = || -> anyhow::Result<()> {
        if std::env::var_os("NATIVE_DISABLE_AUX").is_some() {
            loop {
                std::thread::sleep(std::time::Duration::from_secs(1));
            }
        }
        let d3d = media::D3d::new()?;
        let mut thumbnailer = media::Thumbnailer::new();
        let mut peak_scan: Option<(String, media::PeakScan)> = None;
        loop {
            let job = { shared.aux_req.lock().unwrap().first().cloned() };
            match job {
                Some(AuxJob::Thumb { asset_id, path, bucket }) => {
                    let tt = bucket as f64 * THUMB_BUCKET_S + THUMB_BUCKET_S * 0.5;
                    let got = if is_image_path(std::path::Path::new(&path)) {
                        image_thumb(&path, 96)
                    } else {
                        thumbnailer.thumbnail(&d3d, &path, tt, 96).ok()
                    };
                    {
                        let mut a = shared.aux.lock().unwrap();
                        if let Some(t) = got {
                            a.thumbs.insert((asset_id.clone(), bucket), t);
                        } else {
                            a.thumbs.insert((asset_id.clone(), bucket), (1, 1, vec![40, 40, 40, 255]));
                        }
                        a.ver += 1;
                    }
                    shared.aux_req.lock().unwrap().retain(
                        |j| !matches!(j, AuxJob::Thumb { asset_id: a2, bucket: b2, .. } if *a2 == asset_id && *b2 == bucket),
                    );
                }
                Some(AuxJob::Peaks { asset_id, path }) => {
                    if peak_scan.as_ref().map(|(id, _)| id != &asset_id).unwrap_or(true) {
                        peak_scan = media::PeakScan::new(&path).ok().map(|p| (asset_id.clone(), p));
                    }
                    let mut finished = false;
                    if let Some((_, sc)) = peak_scan.as_mut() {
                        let _ = sc.step();
                        if sc.done {
                            let mut a = shared.aux.lock().unwrap();
                            a.peaks.insert(asset_id.clone(), (sc.spb(), std::mem::take(&mut sc.peaks)));
                            a.ver += 1;
                            finished = true;
                        }
                    } else {
                        finished = true;
                    }
                    if finished {
                        peak_scan = None;
                        shared.aux_req.lock().unwrap().retain(|j| !matches!(j, AuxJob::Peaks { asset_id: a2, .. } if *a2 == asset_id));
                    }
                }
                None => std::thread::sleep(std::time::Duration::from_millis(3)),
            }
        }
    };
    if let Err(e) = run() {
        eprintln!("aux thread died: {e:#}");
    }
}

#[derive(PartialEq, Clone, Copy)]
enum Screen {
    Library,
    Editor,
}

#[derive(Default)]
struct Library {
    /// first assets fetch finished — gates the empty-room guide so it never
    /// flashes while the initial list is still loading
    loaded: bool,
    assets: Vec<serde_json::Value>,
    contents: Vec<serde_json::Value>,
    selected_assets: Vec<String>,
    thumbs: std::collections::HashMap<String, egui::TextureHandle>,
    brief: String,
    title: String,
    format: String,
    /// Library-first text-to-video. Unlike `start_generation`, this needs no source asset.
    ai_model: String,
    ai_duration: i32,
    thumb_tried: std::collections::HashSet<String>,
    gen_content: Option<String>,
    gen_job: Option<String>,
    events: Vec<String>,
    error: Option<String>,
    started: bool,
    /// 削除確認中の素材 (asset_id, filename, 使用中につきforce提案)
    confirm_delete: Option<(String, String, bool)>,
    /// コンテンツ削除の確認中 (content_id, title)
    confirm_delete_content: Option<(String, String)>,
}

/// Short-lived IME/editing state. It is intentionally separate from the document: a
/// Japanese conversion may change several times before the user has committed text.
/// `clip.text` remains the only persisted caption value.
struct CaptionDraft {
    text: String,
    commit_at: Instant,
}

struct App {
    screen: Screen,
    lib: Library,
    lib_poll: Instant,
    lib_sink: std::sync::Arc<Mutex<Vec<(String, Result<serde_json::Value, String>)>>>,
    /// files chosen in the native file picker (background thread) awaiting register
    picked_files: std::sync::Arc<Mutex<Vec<std::path::PathBuf>>>,
    /// a picker dialog is currently open (prevents double dialogs)
    picker_open: std::sync::Arc<std::sync::atomic::AtomicBool>,
    /// このエディタが紐づくチャットルーム名（タイトルバー表示用）
    room_label: Option<String>,
    title_set: bool,
    /// 生成中コンテンツid（ライブ組み上がり表示＋編集ロックの対象）
    generating_content: Option<String>,
    /// 生成中の contents.json 変更検知（中間保存＝カット済みタイムラインの反映）
    gen_contents_mtime: Option<std::time::SystemTime>,
    /// 外部書き込み検知（ダンのコミット等）: 最後にこの画面が読んだ/書いた contents.json の mtime
    disk_mtime: Option<std::time::SystemTime>,
    /// エディタ状態（開いているコンテンツ・再生位置・選択）の外部公開: 前回書いた内容と時刻
    state_pub_last: String,
    state_pub_at: Instant,
    state_pub_written: Instant,
    /// 新規クリップの出現アニメ: クリップid → 表示開始時刻（時差でポポポッと出す）
    clip_spawn: std::collections::HashMap<String, Instant>,
    lib_gen_stash: Option<serde_json::Value>,
    marquee: Option<egui::Rect>,
    insp_text: String,
    caption_drafts: std::collections::HashMap<String, CaptionDraft>,
    /// Text editors rendered on the previous frame. Numeric drags and sliders may keep
    /// egui focus, but only these IDs are allowed to suppress timeline shortcuts.
    text_focus_ids: Vec<egui::Id>,
    blur_mode: bool,
    blur_drag: Option<egui::Pos2>,
    insp_for: String,
    cap_keys: std::collections::HashMap<String, String>, // caption clip id -> render key
    cap_tex: std::collections::HashMap<String, egui::TextureHandle>, // key -> texture
    cap_probe: std::collections::HashMap<String, Instant>, // key -> last disk check
    cap_sig: u64,
    cap_req_ids: Vec<String>,
    caption_web: Option<wry::WebView>,
    caption_web_ready: Arc<std::sync::atomic::AtomicBool>,
    caption_web_sig: u64,
    caption_web_t: f64,
    caption_web_hidden_sig: u64,
    /// Doc the caption payload was last built from (Arc identity). Rebuilding and
    /// hashing the full caption JSON every FRAME burned constant UI-thread time on
    /// caption-heavy docs; the doc pointer only changes on real edits.
    caption_doc_ptr: usize,
    recut_open: bool,
    recut_thresh: f32,
    recut_lead: f32,
    recut_tail: f32,
    recut_busy: bool,
    revise_open: bool,
    assistant: assistant_panel::AssistantPanel,
    revise_text: String,
    /// ダンに指示の場所指定: プレビューを囲むモード / 囲んだ正規化矩形 / その時刻
    revise_pick: bool,
    revise_region: Option<(f64, f64, f64, f64)>,
    revise_region_t: f64,
    doc: Arc<model::Doc>,
    shared: Arc<Shared>,
    selected: Vec<String>,
    /// Asset currently being dragged from the editor's media menu toward the timeline.
    asset_drag: Option<serde_json::Value>,
    /// Probed duration per OS-dragged file path, so the timeline ghost shows the real
    /// clip length while hovering (probe once per path, not per frame).
    os_drag_durations: std::collections::HashMap<String, f64>,
    /// Moveドラッグ開始時に確定した付着クリップ（親=メインレーンの移動対象に頭が
    /// 載っている前面レーンのクリップ+リンク音声）。水平移動のdtだけ一緒に動く。
    move_attached: Vec<String>,
    /// 複数選択中のクリップを押した時の「離したら単独選択に絞る」予約。
    /// 実移動(drag_engaged)が始まったら破棄＝グループ移動は従来どおり。
    click_collapse: Option<String>,
    drag: Drag,
    /// Moveドラッグ中に凍結したレーンレイアウト。ドラッグ開始で空レーンが
    /// 出現してレイアウトがズレ、ポインタ→レーン対応が壊れてクリップが
    /// 初手で別レーンへテレポートする回帰（#591）の根治。
    drag_lane_tops: Option<Vec<(usize, f32, f32)>>,
    /// Move ドラッグの押下位置。実移動（8px超 or レーン帯離脱）までは
    /// ドロップレーンを展開しない＝長押しだけで画面が動かない（ユーザー報告対応）
    drag_press: Option<egui::Pos2>,
    /// 実移動が始まったか。false の間クリップは選択状態のまま何も動かさない
    drag_engaged: bool,
    /// 直前の非ドラッグ時レイアウト（凍結時のアンカー整列に使う）
    last_lane_tops: Vec<(usize, f32, f32)>,
    // undo/redo hold SERIALIZED documents, not Value trees: a 60-deep history of
    // Value clones held hundreds of MB of long-lived small allocations (a real NLE
    // keeps compact undo storage); a compact String is ~8x smaller and parses back
    // in ~10ms on the rare Ctrl+Z.
    undo: Vec<String>,
    // armed at gesture start (press/drag), committed to `undo` by the FIRST real edit.
    // Pushing at press time polluted the stack with no-op snapshots (a plain click piled
    // identical states, so Ctrl+Z seemed to only ever go one step back).
    pending_undo: Option<serde_json::Value>,
    redo: Vec<String>,
    clip_clipboard: Option<serde_json::Value>,
    save_at: Option<Instant>,
    /// Canonical JSON snapshot last read from / written to disk.  A server-side agent
    /// may update the same timeline while this window is open; never let a stale editor
    /// instance overwrite that newer document on debounce or close.
    disk_fingerprint: String,
    salt: u64,
    // Files dropped into an empty project wait here until its timeline frame rate is chosen.
    pending_initial_imports: Vec<std::path::PathBuf>,
    pending_initial_fps: Vec<f64>,
    thumbs: std::collections::HashMap<(String, i64), egui::TextureHandle>,
    peaks: std::collections::HashMap<String, (f64, Vec<f32>)>,
    aux_ver: u64,
    /// CPU-fallback preview texture (only fed when the GPU-direct path is off)
    tex: Option<egui::TextureHandle>,
    /// GPU-direct preview: the published D3D11 frame currently on screen. Holding
    /// the Arc keeps the pool from recycling it while it is displayed.
    display_tex: Option<Arc<gpu_present::GpuTex>>,
    /// WGL interop renderer state (lives inside the egui paint callback)
    gl_video: Arc<gpu_present::GlVideo>,
    last_seq: u64,
    playing: bool,
    transport_button: Option<egui::Rect>,
    playback_speed: f64,
    preview_fullscreen: bool,
    /// 全画面プレビュー(P)の小型トランスポート: 最後にマウスが動いた時刻。
    /// 再生中に触らなければ自動で消える（DaVinci流）。
    fs_bar_last_move: Option<Instant>,
    /// シークバーのドラッグ開始時に再生中だったら、離した時に再生を再開する
    fs_resume_play: bool,
    show_help: bool,
    step_settle_at: Option<Instant>,
    // NATIVE_STEP_PROBE state machine: (phase, phase entry time)
    step_probe: Option<(u8, Instant)>,
    toast: Option<(String, Instant)>,
    playhead_snap: bool,
    snap_line: Option<f64>,
    hover_lane: Option<usize>,
    /// preview inspector: (clip ids with start boxes, drag kind, pointer at start, primary box)
    inspect_drag: Option<(Vec<(String, model::Pos)>, u8, egui::Pos2, model::Pos)>,
    // clip id, live edit buffer, pre-edit document (restored on Cancel)
    caption_edit: Option<(String, String, serde_json::Value)>,
    // dragging a caption on the preview: (clip id, grab pos, style x at grab, style y at grab)
    caption_drag: Option<(String, egui::Pos2, f64, f64)>,
    // clip id -> on-screen box (canvas fractions), measured in the caption WebView's real
    // DOM (__reportCapBoxes) after every payload/time change. Written by the ipc handler.
    caption_live_boxes: Arc<Mutex<std::collections::HashMap<String, [f64; 4]>>>,
    // render key -> alpha bbox of the cache PNG (canvas fractions, default anchor).
    // The drag hit-box fallback for captions the GPU compositor owns (lane z): those
    // are excluded from the WebView payload, so no DOM box ever arrives for them.
    caption_png_boxes: std::collections::HashMap<String, (f64, f64, f64, f64)>,
    lane_reorder: Option<usize>,
    export_result: std::sync::Arc<Mutex<Option<Result<serde_json::Value, String>>>>,
    export_job: Option<String>,
    export_status: Option<String>,
    export_poll: Instant,
    /// DaVinci-style render range (in/out, timeline seconds). None = whole content.
    /// Session-local: I/O keys set the edges at the playhead; ruler band edges drag.
    export_range: Option<(f64, f64)>,
    /// 書き出しダイアログ「サブタイムラインの区間だけ繋げて書き出す」チェック状態
    export_use_sub: bool,
    /// サブタイムラインの I キーで置いた「イン点待ち」（O で区間として確定）
    sub_in: Option<f64>,
    /// 区間ジャンプ直後の音声クロック再アンカー待ち（この間は再ジャンプしない）
    sub_jump_until: Option<Instant>,
    /// この再生セッションが「区間だけ飛び飛び」かどうか。再生開始位置で決まる:
    /// 緑区間の中から開始=飛び飛び／区間の外から開始=普通の全体再生（素材の下見）
    sub_skip_active: bool,
    /// 緑帯の端ドラッグ中: (掴んだ時点の区間リスト, 区間index, イン点か)
    sub_edge_drag: Option<(Vec<(f64, f64)>, usize, bool)>,
    /// サブタブ削除の二段確認（右クリック2回）: (サブid, 1回目の時刻)
    sub_del_arm: Option<(String, Instant)>,
    /// render progress 0..1 while the server reports frame=N/M; None = no bar
    /// (queued / finishing phase / idle)
    export_progress: Option<f32>,
    /// last finished export's output file — shown with a "フォルダを開く" button
    export_done_path: Option<String>,
    /// export settings dialog (button press 1 = confirm destination/range, press 2 = go)
    export_dialog_open: bool,
    /// destination FILE path shown in the dialog; sent as output_copy_path
    export_dest: String,
    /// ruler range-handle drag in progress: Some(true)=in edge, Some(false)=out edge
    range_drag: Option<bool>,
    /// clip_id -> popout bake display state (polled from the cache dir, not the server)
    pop_states: std::collections::HashMap<String, PopState>,
    bake_results: std::sync::Arc<Mutex<Vec<(String, Result<serde_json::Value, String>)>>>,
    last_pop_poll: Instant,
    /// clip_id -> SAM tracked-blur bake state (same cache-dir polling pattern as popout)
    blur_states: std::collections::HashMap<String, PopState>,
    blur_bake_results: std::sync::Arc<Mutex<Vec<(String, Result<serde_json::Value, String>)>>>,
    last_blur_poll: Instant,
    /// bake key -> (parsed boxes_by_frame from the mask meta, last load attempt).
    /// A miss is RETRIED after 1s — permanently caching "not there yet" during a bake
    /// froze the outline on its pre-bake state forever.
    blur_meta_cache: std::collections::HashMap<String, (Option<serde_json::Value>, Instant)>,
    /// dragging a region-effect rectangle on the preview: (clip id, mode 0=move/1..4=NW,NE,SW,SE corner, grab pos, orig region)
    region_drag: Option<(String, u8, egui::Pos2, (f64, f64, f64, f64))>,
    /// キー打ちモード: このクリップIDに対してON。ON中のドラッグだけが表示フレームの
    /// スロットにキーを打つ。クリップ紐付きなので選択が変われば自動的に無効＝
    /// 「別クリップを触ったら誤ってキー化」が構造的に起きない
    kf_mode: Option<String>,
    /// KFドラッグ中に固定するキー時刻（クリップ相対）。ドラッグ開始時に一度だけ
    /// 決めて指を離すまで変えない＝再生ヘッドが動いてもキーが散らばらない
    kf_drag_rel: Option<f64>,
    /// キー打ちモードOFFでキー有りクリップをドラッグ中: ドラッグ開始時のキー配列の
    /// スナップショット。毎フレーム「スナップショット＋累積オフセット」で書き直す
    /// （軌跡ごと平行移動・キーは増えも減りもしない）
    kf_drag_orig_keys: Option<serde_json::Value>,
    /// 映像クリップの位置/サイズドラッグ用キー状態（kf_drag_* のtransform版）:
    /// (kf_modeクリップのキー時刻 clip相対, OFF時のキー有りクリップの元キー配列)
    tkf_drag_rel: Option<f64>,
    tkf_drag_orig: Vec<(String, serde_json::Value)>,
    /// スポイト: (適用先 0=文字色 1=フチ色 2=枠色, 対象テロップid)。armed中は
    /// プレビュークリック=画面ピクセル色を拾って適用（右クリック/Escで中止）
    eyedrop: Option<(u8, Vec<String>)>,
    /// 追従修正モード: clip id being corrected; clicks on the preview collect +/- points
    corr_mode: Option<String>,
    /// correction points in SOURCE coords (x, y, positive) — all on corr_anchor_src's frame
    corr_points: Vec<(f64, f64, bool)>,
    corr_anchor_src: Option<f64>,
    /// BLURSHIFT diagnostics: watch the presented-frame time for 2s after a ◱ drop
    blur_debug_until: Option<Instant>,
    blur_debug_last_t: f64,
    blur_out_log_at: Instant,
    last_push: Instant,
    // Filmora semantics (observed in its logs: Pause -> seek -> auto Play): any timeline
    // interaction while playing pauses first; playback auto-resumes once the video ring
    // is ready at the new position.
    resume_pending: Option<Instant>,
    resume_on_release: bool,
    t: f64,
    dur: f64,
    pps: f32,
    scroll_x: f32,
    ui_fps: f32,
    last_frames: Vec<Instant>,
    comp_ms: f32,
    comp_max: f32,
    gap_max: f32,
    underruns: u64,
    quality: &'static str,
    gen: u64,
}

impl App {
    fn new(contents: &str, dir: &str) -> anyhow::Result<Self> {
        let mut raw: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(contents)?)?;
        let disk_fingerprint = serde_json::to_string(&raw).unwrap_or_default();
        // 前回開いていたタブ（サブ）をメモリ上の sequence スロットへスワップイン
        edits::seq_swap_in(&mut raw);
        let before_norm = serde_json::to_string(&raw).unwrap_or_default();
        edits::normalize_linked_audio(&mut raw);
        edits::remove_orphan_linked_audio(&mut raw);
        edits::quantize_timeline_frames(&mut raw);
        // 無名レーンは「ジェスチャ中の仮レーン」だけという不変条件をロード時に確立。
        // 過去に作られたクリップ載りの無名レーンへ id を付与しておかないと、
        // 最初のドラッグで仮レーン扱い(already_provisionalガード/prune)に巻き込まれる。
        edits::promote_unnamed_occupied_tracks(&mut raw, lane_salt());
        let normalized_on_load = serde_json::to_string(&raw).unwrap_or_default() != before_norm;
        set_canvas_from_content(&raw);
        let doc = Arc::new(model::Doc::from_raw(raw, contents, dir)?);
        // Do this before playback threads start. Existing direct drops are upgraded in
        // the background; until their atomic proxy appears, the original remains usable.
        spawn_missing_timeline_proxies(&doc);
        let dur = doc.duration();
        let shared = Arc::new(Shared {
            req: Mutex::new(Req { t: 0.0, playing: false, scrubbing: false, speed: 1.0, gen: 0 }),
            frame: Mutex::new(FrameOut {
                tex: None,
                rgba: vec![0; (canvas_w() * canvas_h() * 4) as usize],
                seq: 0,
                t: 0.0,
                eff_t: 0.0,
                comp_ms: 0.0,
                comp_max: 0.0,
                gap_max: 0.0,
                quality: "proxy",
                caption_epoch: 0,
            }),
            clock_bits: AtomicU64::new(0f64.to_bits()),
            underruns: AtomicU64::new(0),
            audio_unavailable: AtomicBool::new(false),
            dirty_from_bits: AtomicU64::new(f64::INFINITY.to_bits()),
            caption_epoch: AtomicU64::new(0),
            ring_level: std::sync::atomic::AtomicUsize::new(0),
            ring: Mutex::new(Default::default()),
            ring_gen: AtomicU64::new(0),
            ring_target_bits: AtomicU64::new(0f64.to_bits()),
            doc: Mutex::new(doc.clone()),
            aux_req: Mutex::new(Vec::new()),
            aux: Mutex::new(AuxOut::default()),
            gpu_pool: Mutex::new(None),
            gpu_disabled: std::sync::atomic::AtomicBool::new(
                std::env::var("NATIVE_NO_GPU_PRESENT").map(|v| !v.is_empty()).unwrap_or(false),
            ),
        });
        {
            let shared = shared.clone();
            std::thread::Builder::new()
                .name("media".into())
                .spawn(move || media_thread(shared))?;
        }
        {
            let shared = shared.clone();
            std::thread::Builder::new()
                .name("audio".into())
                .spawn(move || audio_thread(shared))?;
        }
        {
            let shared = shared.clone();
            std::thread::Builder::new()
                .name("aux".into())
                .spawn(move || aux_thread(shared))?;
        }
        {
            let shared = shared.clone();
            std::thread::Builder::new()
                .name("presenter".into())
                .spawn(move || presenter_thread(shared))?;
        }
        Ok(Self {
            screen: Screen::Editor,
            lib: Library { format: "9:16".into(), ai_model: "seedance_2_5".into(), ai_duration: 30, ..Default::default() },
            lib_poll: Instant::now(),
            lib_sink: Default::default(),
            picked_files: Default::default(),
            picker_open: Default::default(),
            room_label: None,
            title_set: false,
            generating_content: None,
            gen_contents_mtime: None,
            disk_mtime: None,
            state_pub_last: String::new(),
            state_pub_at: Instant::now(),
            state_pub_written: Instant::now() - std::time::Duration::from_secs(60),
            clip_spawn: Default::default(),
            lib_gen_stash: None,
            marquee: None,
            insp_text: String::new(),
            caption_drafts: Default::default(),
            text_focus_ids: Vec::new(),
            blur_mode: false,
            blur_drag: None,
            insp_for: String::new(),
            cap_keys: Default::default(),
            cap_tex: Default::default(),
            cap_probe: Default::default(),
            cap_sig: 0,
            cap_req_ids: Vec::new(),
            caption_web: None,
            caption_web_ready: Arc::new(std::sync::atomic::AtomicBool::new(false)),
            caption_web_sig: 0,
            caption_web_t: f64::NAN,
            caption_web_hidden_sig: 0,
            caption_doc_ptr: 0,
            recut_open: false,
            recut_thresh: 0.45,
            recut_lead: 0.06,
            recut_tail: 0.10,
            recut_busy: false,
            revise_open: false,
            assistant: assistant_panel::AssistantPanel::new(),
            revise_text: String::new(),
            revise_pick: false,
            revise_region: None,
            revise_region_t: 0.0,
            doc,
            shared,
            selected: Vec::new(),
            asset_drag: None,
            os_drag_durations: std::collections::HashMap::new(),
            move_attached: Vec::new(),
            click_collapse: None,
            drag: Drag::None,
            drag_lane_tops: None,
            drag_press: None,
            drag_engaged: false,
            last_lane_tops: Vec::new(),
            undo: Vec::new(),
            pending_undo: None,
            redo: Vec::new(),
            clip_clipboard: None,
            save_at: normalized_on_load.then(|| Instant::now() + std::time::Duration::from_millis(1200)),
            disk_fingerprint,
            thumbs: Default::default(),
            peaks: Default::default(),
            aux_ver: 0,
            salt: std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0),
            pending_initial_imports: Vec::new(),
            pending_initial_fps: Vec::new(),
            tex: None,
            display_tex: None,
            gl_video: Arc::new(gpu_present::GlVideo::new()),
            last_seq: 0,
            playing: false,
            transport_button: None,
            playback_speed: 1.0,
            preview_fullscreen: false,
            fs_bar_last_move: None,
            fs_resume_play: false,
            show_help: false,
            step_settle_at: None,
            step_probe: None,
            toast: None,
            playhead_snap: false,
            snap_line: None,
            hover_lane: None,
            inspect_drag: None,
            caption_edit: None,
            caption_drag: None,
            caption_live_boxes: Arc::new(Mutex::new(Default::default())),
            caption_png_boxes: Default::default(),
            lane_reorder: None,
            export_result: Default::default(),
            export_job: None,
            export_status: None,
            export_poll: Instant::now(),
            export_range: None,
            export_use_sub: false,
            sub_in: None,
            sub_jump_until: None,
            sub_skip_active: false,
            sub_edge_drag: None,
            sub_del_arm: None,
            range_drag: None,
            export_progress: None,
            export_done_path: None,
            export_dialog_open: false,
            export_dest: String::new(),
            pop_states: Default::default(),
            bake_results: Default::default(),
            last_pop_poll: Instant::now(),
            blur_states: Default::default(),
            blur_bake_results: Default::default(),
            last_blur_poll: Instant::now(),
            blur_meta_cache: Default::default(),
            region_drag: None,
            kf_mode: None,
            kf_drag_rel: None,
            kf_drag_orig_keys: None,
            tkf_drag_rel: None,
            tkf_drag_orig: Vec::new(),
            eyedrop: None,
            corr_mode: None,
            corr_points: Vec::new(),
            corr_anchor_src: None,
            blur_debug_until: None,
            blur_debug_last_t: 0.0,
            blur_out_log_at: Instant::now(),
            last_push: Instant::now(),
            resume_pending: None,
            resume_on_release: false,
            t: 0.0,
            dur,
            pps: 8.0,
            scroll_x: 0.0,
            ui_fps: 0.0,
            last_frames: Vec::new(),
            comp_ms: 0.0,
            comp_max: 0.0,
            gap_max: 0.0,
            underruns: 0,
            quality: "proxy",
            gen: 0,
        })
    }

    /// Apply an edit to the RAW document, re-derive the typed view, hand it to the media
    /// thread, and schedule a debounced save. Undo = raw snapshots.
    /// Earliest timeline time whose composed frames may differ between two docs: any
    /// added / removed / retimed / retracked / restyled clip contributes min(old_ts, new_ts).
    fn dirty_from(old_doc: &model::Doc, new_doc: &model::Doc) -> f64 {
        use std::collections::HashMap;
        let snap = |d: &model::Doc| -> HashMap<String, String> {
            let mut m = HashMap::new();
            for (ti, tr) in d.seq.tracks.iter().enumerate() {
                for c in &tr.clips {
                    // any field that changes the rendered output participates
                    // (region_keys was missing here — key edits left STALE cached frames
                    // that served the old blur position for a beat before the fresh
                    // compose replaced them: the "blur lags the frame" report)
                    let sig = format!(
                        "{ti}|{:.3}|{:.3}|{:.3}|{:?}|{:?}|{:?}|{:?}|{:?}|{:?}|{:?}|{:?}|{:.3}|{:.3}|{}|{}|{}|{}",
                        c.timeline_start,
                        c.timeline_end,
                        c.source_start,
                        c.source_end,
                        c.position,
                        c.crop,
                        c.region,
                        c.region_keys,
                        c.blur_track,
                        c.text,
                        c.fit,
                        c.volume,
                        c.opacity,
                        c.effects.len(),
                        tr.hidden,
                        tr.muted,
                        tr.solo
                    );
                    m.insert(c.id.clone(), sig);
                }
            }
            m
        };
        let (a, b) = (snap(old_doc), snap(new_doc));
        let mut min_t = f64::INFINITY;
        let start_of = |d: &model::Doc, id: &str| -> Option<f64> {
            d.seq
                .tracks
                .iter()
                .flat_map(|tr| tr.clips.iter())
                .find(|c| c.id == id)
                .map(|c| c.timeline_start)
        };
        for (id, sig) in &a {
            if b.get(id) != Some(sig) {
                if let Some(t) = start_of(old_doc, id) {
                    min_t = min_t.min(t);
                }
                if let Some(t) = start_of(new_doc, id) {
                    min_t = min_t.min(t);
                }
            }
        }
        for id in b.keys() {
            if !a.contains_key(id) {
                if let Some(t) = start_of(new_doc, id) {
                    min_t = min_t.min(t);
                }
            }
        }
        min_t
    }

    fn apply_edit(&mut self, snapshot: bool, f: impl FnOnce(&mut serde_json::Value)) {
        // Human edits remain available while Dan works. save_document merges
        // disjoint changes and refuses a conflicting overwrite.
        if snapshot {
            self.pending_undo = None;
            self.undo.push(self.doc.raw.to_string());
            if self.undo.len() > 60 {
                self.undo.remove(0);
            }
            self.redo.clear();
        } else if let Some(prev) = self.pending_undo.take() {
            // first real edit of the armed gesture — commit the pre-gesture state
            self.undo.push(prev.to_string());
            if self.undo.len() > 60 {
                self.undo.remove(0);
            }
            self.redo.clear();
        }
        let mut raw = self.doc.raw.clone();
        f(&mut raw);
        edits::normalize_linked_audio(&mut raw);
        edits::remove_orphan_linked_audio(&mut raw);
        edits::quantize_timeline_frames(&mut raw);
        // キャンバス寸法はドキュメント公開の「前」に確定させる。メディアスレッドは
        // doc差し替えの瞬間に寸法変化を見てコンポジタを作り直すため、後から寸法だけ
        // 変えると再構築されず、古い形の合成絵が新しい枠へ引き伸ばされる（形式切替の潰れ）。
        set_canvas_from_content(&raw);
        match model::Doc::from_raw(raw, &self.doc.contents_path, &self.doc.asset_dir) {
            Ok(nd) => {
                let df = Self::dirty_from(&self.doc, &nd);
                if df.is_finite() {
                    // accumulate the MIN across rapid edits until the producer consumes it
                    let cur = f64::from_bits(self.shared.dirty_from_bits.load(Ordering::Relaxed));
                    self.shared
                        .dirty_from_bits
                        .store(df.min(cur).to_bits(), Ordering::Relaxed);
                }
                let nd = Arc::new(nd);
                self.doc = nd.clone();
                *self.shared.doc.lock().unwrap() = nd;
                self.dur = self.doc.duration();
                self.cap_keys.clear();
                self.cap_sig = 0;
                self.save_at = Some(Instant::now() + std::time::Duration::from_millis(1200));
                // mid-drag edits (move/trim) count as scrubbing: the media thread must stay
                // free for the next tick, and the preview uses the budgeted scrub seek
                let scrubbing = !matches!(self.drag, Drag::None);
                self.push_req(scrubbing);
            }
            Err(e) => eprintln!("apply_edit: doc rebuild FAILED (edit dropped): {e:#}"),
        }
    }

    fn restore(&mut self, raw: serde_json::Value) {
        let mut raw = raw;
        edits::quantize_timeline_frames(&mut raw);
        set_canvas_from_content(&raw);
        if let Ok(nd) = model::Doc::from_raw(raw, &self.doc.contents_path, &self.doc.asset_dir) {
            let nd = Arc::new(nd);
            self.doc = nd.clone();
            *self.shared.doc.lock().unwrap() = nd;
            self.dur = self.doc.duration();
            self.save_at = Some(Instant::now() + std::time::Duration::from_millis(1200));
            self.push_req(false);
        }
    }

    /// Persist only if this instance is still editing the version it loaded.  Agent
    /// edits are written by another process, so an unconditional save-on-exit would
    /// otherwise erase them with this window's stale in-memory document.
    fn save_document(&mut self) -> anyhow::Result<bool> {
        let _contents_guard = match edits::lock_contents(&self.doc.contents_path) {
            Ok(guard) => guard,
            Err(_) => {
                self.save_at = Some(Instant::now() + std::time::Duration::from_millis(200));
                return Ok(false);
            }
        };
        let on_disk: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&self.doc.contents_path)?)?;
        let fingerprint = serde_json::to_string(&on_disk)?;
        let disk_form = edits::seq_swap_out(&self.doc.raw);
        let disk_form = if fingerprint != self.disk_fingerprint {
            let baseline:serde_json::Value=serde_json::from_str(&self.disk_fingerprint)?;
            match edits::merge_save(&baseline,&on_disk,&disk_form) {
                Ok(merged)=>merged,
                Err(_)=>{
                    self.save_at=None;
                    self.toast("同じ場面が外部で変更されています。保存は保留しました。手編集はこの画面に残っています。");
                    return Ok(false);
                }
            }
        } else {disk_form};
        // メモリはアクティブタブが sequence に入っているので、ディスク形
        // （sequence=メイン・サブは subseqs）へ変換して書く
        edits::save(&disk_form, &self.doc.contents_path)?;
        self.disk_fingerprint = disk_form.to_string();
        let mut live_form=disk_form;
        edits::seq_swap_in(&mut live_form);
        if live_form!=self.doc.raw {
            let doc=Arc::new(model::Doc::from_raw(live_form,&self.doc.contents_path,&self.doc.asset_dir)?);
            self.doc=doc.clone();*self.shared.doc.lock().unwrap()=doc;
        }
        self.remember_disk_mtime();
        Ok(true)
    }

    /// Snap t to nearby clip edges / the playhead (8px feel like Filmora's magnet).
    fn snap(&self, t: f64, ignore: &[String]) -> f64 {
        let t = self.grid_quantize(t);
        let tol = (8.0 / self.pps) as f64;
        let mut best = t;
        let mut bd = tol;
        for tr in &self.doc.seq.tracks {
            for c in &tr.clips {
                if ignore.contains(&c.id) {
                    continue;
                }
                for e in [c.timeline_start, c.timeline_end] {
                    let d = (e - t).abs();
                    if d < bd {
                        bd = d;
                        best = e;
                    }
                }
            }
        }
        self.grid_quantize(best)
    }

    fn snap_playhead(&self, t: f64) -> f64 {
        let t = self.grid_quantize(t.clamp(0.0, self.dur));
        if !self.playhead_snap {
            return t;
        }
        let tol = (8.0 / self.pps) as f64;
        let mut best = t.clamp(0.0, self.dur);
        let mut bd = tol;
        for tr in &self.doc.seq.tracks {
            if tr.hidden {
                continue;
            }
            for c in &tr.clips {
                for e in [c.timeline_start, c.timeline_end] {
                    let e = e.clamp(0.0, self.dur);
                    let d = (e - t).abs();
                    if d < bd {
                        bd = d;
                        best = e;
                    }
                }
            }
        }
        if self.playhead_snap {
            let d = (self.t - t).abs();
            if d < bd {
                best = self.t;
            }
        }
        best
    }

    /// Register a dropped file as an asset and insert it at the playhead on the first
    /// visual lane. Exact timeline drops use `import_file_at` below.
    /// 素材ドロップ/カードドロップの「最上段より上」ゾーン: 新規最前面ビジュアル
    /// レーンを挿入して、その index を返す（レーンは上へ何本でも増やせる）。
    fn insert_new_top_lane(&mut self) -> usize {
        let target = (0..self.doc.seq.tracks.len())
            .filter(|&i| self.doc.seq.tracks[i].kind != "audio")
            .max()
            .map(|f| f + 1)
            .unwrap_or(0);
        let salt = lane_salt();
        self.apply_edit(false, move |raw| edits::insert_top_visual_track(raw, salt));
        target
    }

    fn import_file(&mut self, p: &std::path::Path) -> anyhow::Result<()> {
        let target = self
            .doc
            .seq
            .tracks
            .iter()
            .position(|tr| tr.kind != "audio")
            .unwrap_or(0);
        self.import_file_at(p, self.t, target)
    }

    fn import_file_at(&mut self, p: &std::path::Path, t: f64, target: usize) -> anyhow::Result<()> {
        let path = p.to_string_lossy().replace(char::from(92), "/");
        self.salt += 1;
        let id = format!("nat{}_{}", self.salt, std::process::id());
        let salt = self.salt;
        let image = is_image_path(p);
        // asset duration via a throwaway probe on the media thread would be cleaner; a direct
        // MF probe from this thread works because MF objects are free-threaded (COM init is
        // best-effort here).
        let dur = if image { 5.0 } else { probe_duration(&path).unwrap_or(5.0) };
        let has_audio = !image && probe_has_audio(&path);
        // assets.json append
        let aj = format!("{}/assets.json", self.doc.asset_dir);
        let mut arr: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(&aj).unwrap_or_else(|_| "[]".into()))
                .unwrap_or_else(|_| serde_json::Value::Array(vec![]));
        let mut metadata = serde_json::json!({ "duration": dur });
        if let Some(fps) = (!image).then(|| probe_frame_rate(&path)).flatten() {
            metadata["fps"] = serde_json::json!(fps);
        }
        if has_audio {
            metadata["audio_codec"] = serde_json::json!("source");
        }
        if let Some(a) = arr.as_array_mut() {
            // ProductionAsset APIスキーマ完全準拠で書く。最小レコード（status=ready・
            // room_id等欠落）は一覧APIのレスポンス検証を500にし、部屋の素材が
            // 丸ごと読めなくなった（MCP側でも同種事故の前科があり全フィールド明示が規律）
            let fname = p.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
            let room_id = std::path::Path::new(&self.doc.asset_dir)
                .file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_default();
            let now = iso8601_utc_now();
            a.push(serde_json::json!({
                "id": id,
                "room_id": room_id,
                "kind": if image { "image" } else { "video" },
                "source_type": "local_path",
                "original_uri": path,
                "local_path": path,
                "proxy_path": null,
                "proxy_url": null,
                "thumbnail_path": null,
                "thumbnail_url": null,
                "name": fname,
                "filename": fname,
                "status": if image { "ready" } else { "proxy_pending" },
                "metadata": metadata,
                "created_at": now,
                "updated_at": now,
                "imported_by": "native"
            }));
        }
        std::fs::write(&aj, serde_json::to_string(&arr)?)?;
        if !image {
            spawn_local_proxy(self.doc.asset_dir.clone(), id.clone(), path.clone());
        }
        let aid = id.clone();
        self.apply_edit(true, move |raw| {
            edits::place_asset(raw, target, t, dur, &aid, has_audio, image, salt);
        });
        self.selected.clear();
        self.selected.push(format!("drop_v_{salt}"));
        self.t = t;
        self.push_req(false);
        Ok(())
    }

    /// Import a PURE AUDIO file (BGM etc.) at time `t` on the audio lane. Same
    /// assets.json contract as import_file_at, but kind="audio", no proxy and no
    /// visual clip — Media Foundation decodes the source (mp3/wav/…) directly.
    fn import_audio_at(&mut self, p: &std::path::Path, t: f64) -> anyhow::Result<()> {
        let path = p.to_string_lossy().replace(char::from(92), "/");
        self.salt += 1;
        let id = format!("nat{}_{}", self.salt, std::process::id());
        let salt = self.salt;
        let dur = probe_duration(&path).unwrap_or(0.0);
        anyhow::ensure!(dur > 0.05, "音声の長さを取得できません: {path}");
        let aj = format!("{}/assets.json", self.doc.asset_dir);
        let mut arr: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(&aj).unwrap_or_else(|_| "[]".into()))
                .unwrap_or_else(|_| serde_json::Value::Array(vec![]));
        if let Some(a) = arr.as_array_mut() {
            let fname = p.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
            let room_id = std::path::Path::new(&self.doc.asset_dir)
                .file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_default();
            let now = iso8601_utc_now();
            a.push(serde_json::json!({
                "id": id,
                "room_id": room_id,
                "kind": "audio",
                "source_type": "local_path",
                "original_uri": path,
                "local_path": path,
                "proxy_path": null,
                "proxy_url": null,
                "thumbnail_path": null,
                "thumbnail_url": null,
                "name": fname,
                "filename": fname,
                "status": "ready",
                "metadata": { "duration": dur, "audio_codec": "source" },
                "created_at": now,
                "updated_at": now,
                "imported_by": "native"
            }));
        }
        std::fs::write(&aj, serde_json::to_string(&arr)?)?;
        let aid = id.clone();
        self.apply_edit(true, move |raw| {
            edits::place_audio_asset(raw, t, dur, &aid, salt);
        });
        self.selected.clear();
        self.selected.push(format!("drop_a_{salt}"));
        self.t = t;
        self.push_req(false);
        Ok(())
    }

    fn timeline_fps(&self) -> f64 {
        self.doc.seq.frame_rate.filter(|fps| fps.is_finite() && *fps > 1.0).unwrap_or(30.0)
    }

    /// Snap a timeline instant onto the sequence frame grid. THE clock rule: keyframe
    /// WRITES and keyframe EVALUATION both go through this on the displayed frame's
    /// effective time, so "the key's frame shows the key's value, the next frame is
    /// still" holds exactly (the old mid-vs-start half-frame gap leaked motion onto
    /// keyless frames).
    fn grid_quantize(&self, t: f64) -> f64 {
        let f = self.timeline_fps();
        (t * f).round() / f
    }

    /// The grid slot of the frame that is REALLY on screen — the single clock every
    /// keyframe read AND write uses (outline, on-key paint, drag keying, ◆＋, ◆削除).
    fn displayed_grid_t(&self) -> f64 {
        self.grid_quantize({
            let f = self.shared.frame.lock().unwrap();
            let eff = if f.eff_t > 0.0 { f.eff_t } else { f.t };
            if f.rgba.is_empty() || (eff - self.t).abs() > 0.75 {
                self.t
            } else {
                eff
            }
        })
    }

    /// Key-work clock for ONE clip (region AND transform keys): the displayed
    /// frame's grid slot — EXCEPT when the transport playhead itself sits on one
    /// of the clip's existing keys while the displayed slot drifted off it.
    /// The displayed slot follows the base video's LANDED frame (eff_t), which on
    /// VFR/proxy sources can round to the PREVIOUS grid slot; adjusting a key you
    /// navigated to must edit THAT key, never mint a neighbour one frame away.
    /// `key_times_rel` are the clip's key instants, clip-relative.
    fn keyed_grid_t(&self, clip_start: f64, key_times_rel: &[f64]) -> f64 {
        snap_key_slot(self.displayed_grid_t(), self.grid_quantize(self.t), clip_start, key_times_rel)
    }

    fn has_timeline_media(&self) -> bool {
        self.doc.seq.tracks.iter().flat_map(|track| track.clips.iter()).any(|clip| clip.asset_id.is_some())
    }

    fn set_timeline_fps(&mut self, fps: f64) {
        let fps = canonical_timeline_fps(fps);
        self.apply_edit(false, move |raw| {
            if let Some(seq) = raw.get_mut(0)
                .and_then(|root| root.get_mut("timeline"))
                .and_then(|timeline| timeline.get_mut("sequence"))
                .and_then(|seq| seq.as_object_mut())
            {
                seq.insert("frame_rate".into(), serde_json::json!(fps));
            }
        });
    }

    fn import_initial_files(&mut self, fps: f64) {
        let files = std::mem::take(&mut self.pending_initial_imports);
        self.pending_initial_fps.clear();
        self.set_timeline_fps(fps);
        for path in files {
            if let Err(e) = self.import_file(&path) {
                eprintln!("import: {e:#}");
            }
        }
    }

    fn toast(&mut self, msg: &str) {
        self.toast = Some((msg.to_string(), Instant::now()));
    }

    fn room_id(&self) -> String {
        self.doc
            .asset_dir
            .rsplit('/')
            .next()
            .unwrap_or_default()
            .to_string()
    }

    fn timeline_format(&self) -> String {
        self.doc
            .raw
            .get(0)
            .and_then(|r| {
                r.get("timeline")
                    .and_then(|t| t.get("format"))
                    .or_else(|| r.get("format"))
            })
            .and_then(|v| v.as_str())
            .unwrap_or("9:16")
            .to_string()
    }

    /// E key: toggle the pop-out effect on the selected person clips. Applying kicks the
    /// server bake (auth-free local API) on a background thread; the clip itself turns
    /// into a "生成中 n%" progress strip until the bake lands.
    fn toggle_popout(&mut self) {
        // ANY video clip can pop out — where it sits on the timeline is the user's
        // business. The card box: a PiP-ish display position is reused as the card;
        // a (near-)fullscreen clip gets the standard card preset.
        let sel: Vec<(String, model::Clip)> = self
            .doc
            .seq
            .tracks
            .iter()
            .filter(|tr| tr.kind != "audio")
            .flat_map(|tr| tr.clips.iter())
            .filter(|c| self.selected.contains(&c.id) && c.asset_id.is_some())
            .map(|c| (c.id.clone(), c.clone()))
            .collect();
        if sel.is_empty() {
            return;
        }
        let remove = sel.iter().all(|(id, c)| {
            c.popout_params().is_some() && !matches!(self.pop_states.get(id), Some(PopState::Failed))
        });
        if remove {
            let ids: Vec<String> = sel.iter().map(|(id, _)| id.clone()).collect();
            self.apply_edit(true, |raw| edits::set_popout(raw, &ids, None));
            for id in ids {
                self.pop_states.remove(&id);
            }
            return;
        }
        let room = self.room_id();
        let fmt = self.timeline_format();
        for (id, c) in sel {
            if c.popout_params().is_some() && !matches!(self.pop_states.get(&id), Some(PopState::Failed)) {
                continue; // already applied and healthy
            }
            let box_ = match c.position {
                Some(p) if p.width < 0.9 && p.height < 0.9 => p,
                _ => model::Pos { x: 0.27, y: 0.655, width: 0.46, height: 0.30 },
            };
            // effect goes on the clip IMMEDIATELY (state shows 0%); the key arrives async
            let orig_pos = c
                .position
                .map(|p| serde_json::json!({"x": p.x, "y": p.y, "width": p.width, "height": p.height}))
                .unwrap_or(serde_json::Value::Null);
            let params = serde_json::json!({
                "intensity": "mid", "shadow": true,
                "box": {"x": box_.x, "y": box_.y, "width": box_.width, "height": box_.height},
                "orig_position": orig_pos,
                "baked_format": fmt,
            });
            let ids = vec![id.clone()];
            self.apply_edit(true, move |raw| edits::set_popout(raw, &ids, Some(params)));
            self.pop_states.insert(id.clone(), PopState::Baking(0));
            let payload = serde_json::json!({
                "room_id": room, "asset_id": c.asset_id,
                "format": fmt,
                "position": {"x": box_.x, "y": box_.y, "width": box_.width, "height": box_.height},
                "source_start": c.source_start,
                "source_end": c.source_end.unwrap_or(c.source_start + (c.timeline_end - c.timeline_start)),
                "intensity": "mid", "shadow": true,
            })
            .to_string();
            let sink = self.bake_results.clone();
            let cid = id.clone();
            std::thread::spawn(move || {
                let res = http_local("POST", "/api/v1/production-assets/popout-overlay", Some(&payload))
                    .and_then(|txt| Ok(serde_json::from_str::<serde_json::Value>(&txt)?))
                    .map_err(|e| format!("{e:#}"));
                sink.lock().unwrap().push((cid, res));
            });
        }
    }

    /// Bake bookkeeping: absorb async POST results into effect params, poll progress
    /// files, finalize margins/position when a bake lands. Called from update() and the
    /// headless self-test.
    fn poll_popout_bakes(&mut self) {
        // async bake-POST results: write the returned key/bake window into the effect
        {
            let results: Vec<(String, Result<serde_json::Value, String>)> =
                std::mem::take(&mut *self.bake_results.lock().unwrap());
            for (cid, res) in results {
                match res {
                    Ok(v) => {
                        let (key, bs, be) = (
                            v.get("key").and_then(|x| x.as_str()).unwrap_or("").to_string(),
                            v.get("bake_start").and_then(|x| x.as_f64()).unwrap_or(0.0),
                            v.get("bake_end").and_then(|x| x.as_f64()).unwrap_or(0.0),
                        );
                        if key.is_empty() {
                            self.pop_states.insert(cid, PopState::Failed);
                            continue;
                        }
                        let clip = self
                            .doc
                            .seq
                            .tracks
                            .iter()
                            .flat_map(|tr| tr.clips.iter())
                            .find(|c| c.id == cid)
                            .cloned();
                        if let Some(c) = clip {
                            if let Some(p) = c.popout_params() {
                                let mut p2 = p.clone();
                                if let Some(o) = p2.as_object_mut() {
                                    o.insert("overlay_key".into(), serde_json::json!(key));
                                    o.insert("bake_start".into(), serde_json::json!(bs));
                                    o.insert("bake_end".into(), serde_json::json!(be));
                                    o.insert("bake_v".into(), serde_json::json!(7));
                                }
                                let ids = vec![cid.clone()];
                                self.apply_edit(false, move |raw| edits::set_popout(raw, &ids, Some(p2)));
                            }
                        }
                    }
                    Err(e) => {
                        eprintln!("popout bake request failed: {e}");
                        self.pop_states.insert(cid, PopState::Failed);
                    }
                }
            }
        }
        // poll bake progress straight off the cache dir (same machine — no server round
        // trip) and finalize margins/position the moment a bake lands
        if self.last_pop_poll.elapsed().as_millis() > 700 {
            self.last_pop_poll = Instant::now();
            let cache = format!("{}/popout-cache", self.doc.asset_dir);
            let mut finalize: Vec<(String, serde_json::Value)> = Vec::new();
            for tr in &self.doc.seq.tracks {
                for c in &tr.clips {
                    let Some(p) = c.popout_params() else { continue };
                    let Some(key) = p.get("overlay_key").and_then(|k| k.as_str()) else {
                        continue; // POST still in flight
                    };
                    let pv_ok = std::fs::metadata(format!("{cache}/{key}.pv.mp4"))
                        .map(|m| m.len() > 0)
                        .unwrap_or(false);
                    if pv_ok {
                        if p.get("margins").is_none() {
                            if let Some(m) = std::fs::read_to_string(format!("{cache}/{key}.json"))
                                .ok()
                                .and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok())
                                .and_then(|j| j.get("margins").cloned())
                            {
                                finalize.push((c.id.clone(), m));
                            }
                        }
                        self.pop_states.insert(c.id.clone(), PopState::Ready);
                        continue;
                    }
                    let prog = std::fs::read_to_string(format!("{cache}/{key}.progress.json"))
                        .ok()
                        .and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok());
                    let state = match prog {
                        Some(j) if j.get("error").is_some() => PopState::Failed,
                        Some(j) => PopState::Baking(
                            j.get("pct").and_then(|v| v.as_i64()).unwrap_or(0).clamp(0, 99) as u8,
                        ),
                        None => PopState::Baking(0),
                    };
                    self.pop_states.insert(c.id.clone(), state);
                }
            }
            for (cid, m) in finalize {
                self.apply_edit(false, move |raw| edits::finalize_popout(raw, &cid, &m));
            }
        }
    }

    /// Bake a SAM tracked-blur for one region-effect clip: resolve the base video clip
    /// under the effect window, POST /blur-mask (box = the drawn rectangle) and bind the
    /// pending bake to the clip — the mask then FOLLOWS the object inside the rectangle.
    fn apply_blur_bake(&mut self, id: &str) {
        self.apply_blur_bake_ex(id, None, None)
    }

    /// 追従修正: re-bake THIS clip's window anchored by the collected +/- clicks. The
    /// splice contract comes from clip bounds — neighbours (split-off spans) keep their
    /// own mask keys untouched, so everything outside this clip stays bit-identical.
    fn apply_blur_correction(&mut self, id: &str) {
        if self.corr_points.is_empty() {
            self.toast("先にプレビューで対象をクリックしてください（左=＋ / 右=−）");
            return;
        }
        let pts = self.corr_points.clone();
        let anchor = self.corr_anchor_src;
        eprintln!("CORRBAKE clip={id} anchor={anchor:?} points={pts:?}");
        self.apply_blur_bake_ex(id, Some(pts), anchor);
        self.corr_mode = None;
        self.corr_points.clear();
        self.corr_anchor_src = None;
    }

    fn apply_blur_bake_ex(&mut self, id: &str, points: Option<Vec<(f64, f64, bool)>>, anchor_override: Option<f64>) {
        let Some(c) = self
            .doc
            .seq
            .tracks
            .iter()
            .flat_map(|tr| tr.clips.iter())
            .find(|c| c.id == id)
            .cloned()
        else {
            return;
        };
        let Some(rg) = c.region_xywh() else { return };
        let mid = (c.timeline_start + c.timeline_end) * 0.5;
        let (cx, cy) = (rg.0 + rg.2 * 0.5, rg.1 + rg.3 * 0.5);
        let active = self.doc.active_media(mid);
        let base = active
            .iter()
            .rev()
            .copied()
            .find(|b| {
                let p = effective_box(&self.doc, b, mid);
                cx >= p.x && cx <= p.x + p.width && cy >= p.y && cy <= p.y + p.height
            })
            .or_else(|| active.last().copied())
            .cloned();
        let Some(b) = base.filter(|b| b.asset_id.is_some() && !b.is_freeze()) else {
            self.toast = Some(("追従ベイクには下に通常の映像クリップが必要です".into(), Instant::now()));
            return;
        };
        let aid = b.asset_id.clone().unwrap();
        // mask window = the union of the source ranges of ALL base cuts of this asset
        // under the effect clip. Dan timelines are strings of short cuts — covering only
        // the middle cut left the other cuts mask-less (the "tracks only sometimes" bug).
        // Tracking runs CONTINUOUSLY through unseen gaps, so cut-crossing identity holds.
        let (mut ss, mut se) = (f64::MAX, f64::MIN);
        // lanes have no roles: the base cuts of this asset may sit on ANY visual lane
        // (the asset_id match below is the real filter)
        for tr in self.doc.seq.tracks.iter().filter(|tr| tr.kind != "audio" && !tr.hidden) {
            for bc in &tr.clips {
                if bc.asset_id.as_deref() != Some(aid.as_str()) || bc.is_freeze() {
                    continue;
                }
                if bc.timeline_end <= c.timeline_start || bc.timeline_start >= c.timeline_end {
                    continue;
                }
                ss = ss.min(bc.src_at(c.timeline_start.max(bc.timeline_start)));
                se = se.max(bc.src_at(c.timeline_end.min(bc.timeline_end)));
            }
        }
        if !ss.is_finite() || se <= ss {
            ss = b.src_at(c.timeline_start.max(b.timeline_start));
            se = b.src_at(c.timeline_end.min(b.timeline_end)).max(ss + 0.1);
        }
        let se = se.max(ss + 0.1);
        // the object to track = whatever the rectangle covers on the frame the user is
        // LOOKING AT: playhead if it sits inside the effect window (over this asset),
        // else the effect start. Anchoring at the padded window start silently picked
        // whatever happened to be in the box 1.5s earlier.
        let anchor_src = if self.t >= c.timeline_start && self.t < c.timeline_end {
            self.doc
                .active_media(self.t)
                .into_iter()
                .find(|bc| bc.id == b.id)
                .map(|bc| bc.src_at(self.t))
        } else {
            None
        }
        .unwrap_or_else(|| b.src_at(c.timeline_start.max(b.timeline_start)));
        // the rectangle was drawn in CANVAS space; SAM works on SOURCE pixels — map it
        // through the inverse of the base clip's cover-crop (aspect mismatch shifted the
        // box onto the wrong object before this). Keyframed bases evaluate at the SAME
        // moment the anchor frame comes from.
        let t_anchor = if self.t >= c.timeline_start && self.t < c.timeline_end {
            self.t
        } else {
            c.timeline_start.max(b.timeline_start)
        };
        let dims = self.doc.asset_dims.get(&aid).copied().unwrap_or((0, 0));
        let bb = effective_box(&self.doc, &b, t_anchor);
        let sbox = compositor::canvas_box_to_source(
            (canvas_w(), canvas_h()),
            dims,
            (bb.x, bb.y, bb.width, bb.height),
            !b.stretches_to_box(),
            b.crop_ltrb_at(t_anchor),
            rg,
        );
        let room = self.room_id();
        // bind immediately (shows 0%); the cache key arrives async from the POST
        let pending = serde_json::json!({ "asset_id": aid, "target_clip_id": b.id });
        let cid = id.to_string();
        self.apply_edit(true, move |raw| edits::set_blur_track(raw, &cid, Some(pending)));
        self.blur_states.insert(id.to_string(), PopState::Baking(0));
        let mut pj = serde_json::json!({
            "room_id": room, "asset_id": aid,
            "source_start": ss, "source_end": se,
            "anchor": anchor_override.unwrap_or(anchor_src),
        });
        if let Some(pts) = points.as_ref().filter(|p| !p.is_empty()) {
            // correction clicks: SAM point prompts (fast tracker engine)
            pj["points"] = serde_json::json!(pts
                .iter()
                .map(|(x, y, pos)| serde_json::json!([x, y, if *pos { 1 } else { 0 }]))
                .collect::<Vec<_>>());
        } else {
            pj["box"] = serde_json::json!([sbox.0, sbox.1, sbox.2, sbox.3]);
        }
        let payload = pj.to_string();
        let sink = self.blur_bake_results.clone();
        let cid = id.to_string();
        std::thread::spawn(move || {
            let res = http_local("POST", "/api/v1/production-assets/blur-mask", Some(&payload))
                .and_then(|txt| Ok(serde_json::from_str::<serde_json::Value>(&txt)?))
                .map_err(|e| format!("{e:#}"));
            sink.lock().unwrap().push((cid, res));
        });
    }

    /// Absorb async blur-bake POST results into the clip binding and poll mask progress
    /// straight off the cache dir (same machine — no server round trip).
    fn poll_blur_bakes(&mut self) {
        {
            let results: Vec<(String, Result<serde_json::Value, String>)> =
                std::mem::take(&mut *self.blur_bake_results.lock().unwrap());
            for (cid, res) in results {
                match res {
                    Ok(v) => {
                        let key = v.get("key").and_then(|x| x.as_str()).unwrap_or("").to_string();
                        let bs = v.get("bake_start").and_then(|x| x.as_f64()).unwrap_or(0.0);
                        if key.is_empty() {
                            self.blur_states.insert(cid, PopState::Failed);
                            continue;
                        }
                        let cur = self
                            .doc
                            .seq
                            .tracks
                            .iter()
                            .flat_map(|tr| tr.clips.iter())
                            .find(|c| c.id == cid)
                            .and_then(|c| c.blur_track.clone());
                        if let Some(mut bt) = cur {
                            if let Some(o) = bt.as_object_mut() {
                                o.insert("key".into(), serde_json::json!(key));
                                o.insert("bake_start".into(), serde_json::json!(bs));
                            }
                            let cid2 = cid.clone();
                            self.apply_edit(false, move |raw| edits::set_blur_track(raw, &cid2, Some(bt)));
                        }
                    }
                    Err(e) => {
                        eprintln!("blur bake request failed: {e}");
                        self.blur_states.insert(cid, PopState::Failed);
                    }
                }
            }
        }
        if self.last_blur_poll.elapsed().as_millis() > 700 {
            self.last_blur_poll = Instant::now();
            let cache = format!("{}/blur-cache", self.doc.asset_dir);
            for tr in &self.doc.seq.tracks {
                for c in &tr.clips {
                    let Some(bt) = c.blur_track.as_ref() else { continue };
                    let Some(key) = bt.get("key").and_then(|k| k.as_str()) else { continue };
                    if std::fs::metadata(format!("{cache}/{key}.mask.mp4"))
                        .map(|m| m.len() > 0)
                        .unwrap_or(false)
                    {
                        self.blur_states.insert(c.id.clone(), PopState::Ready);
                        continue;
                    }
                    let prog = std::fs::read_to_string(format!("{cache}/{key}.progress.json"))
                        .ok()
                        .and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok());
                    let state = match prog {
                        Some(j) if j.get("error").is_some() => PopState::Failed,
                        // blur_mask_bake.py writes {"stage", "progress": 0..1}
                        Some(j) => PopState::Baking(
                            ((j.get("progress").and_then(|v| v.as_f64()).unwrap_or(0.0)) * 100.0)
                                .clamp(0.0, 99.0) as u8,
                        ),
                        None => PopState::Baking(0),
                    };
                    self.blur_states.insert(c.id.clone(), state);
                }
            }
        }
    }

    /// Drop a dragged clip onto another lane: move its visual clip(s) to that track.
    /// Any non-audio lane is a valid target — lanes are just layers.
    fn drop_move_to_lane(&mut self, ids: &[String], target: usize) {
        let tk = self.doc.seq.tracks.get(target).map(|t| t.kind.clone()).unwrap_or_default();
        let src_track = self
            .doc
            .seq
            .tracks
            .iter()
            .position(|tr| tr.kind != "audio" && tr.clips.iter().any(|c| ids.contains(&c.id)));
        let vids: Vec<String> = self
            .doc
            .seq
            .tracks
            .iter()
            .filter(|tr| tr.kind != "audio")
            .flat_map(|tr| tr.clips.iter())
            .filter(|c| ids.contains(&c.id))
            .map(|c| c.id.clone())
            .collect();
        eprintln!(
            "DROPLANE target={target}({tk}) src={src_track:?} clips={}",
            vids.len()
        );
        if tk != "audio" && src_track != Some(target) && !vids.is_empty() {
            self.apply_edit(true, move |raw| edits::move_to_track(raw, &vids, target));
        }
    }

    fn remember_caption_fallbacks(&self, ids: &[String]) {
        let Ok(mut map) = caption_fallbacks().lock() else {
            return;
        };
        for tr in &self.doc.seq.tracks {
            for c in &tr.clips {
                if !ids.iter().any(|id| id == &c.id) {
                    continue;
                }
                let Some(text) = c.text.as_deref().map(str::trim).filter(|s| !s.is_empty()) else {
                    continue;
                };
                let style = c.style.as_ref().unwrap_or(&serde_json::Value::Null);
                let key = caption_cache_key(c, text, style);
                let png = std::path::Path::new(&self.doc.asset_dir).join("caption-cache").join(format!("{key}.png"));
                if !png.exists() || std::fs::metadata(&png).map(|m| m.len() == 0).unwrap_or(true) {
                    continue;
                }
                let font_size = caption_style_num(style, "fontSize", 1.0).max(0.05);
                map.insert(c.id.clone(), (key, font_size));
            }
        }
    }

    fn ensure_caption_web(&mut self, frame: &eframe::Frame) {
        if self.caption_web.is_some() {
            return;
        }
        use wry::WebViewBuilderExtWindows as _;
        let bounds = wry::Rect {
            position: wry::dpi::LogicalPosition::new(0.0, 0.0).into(),
            size: wry::dpi::LogicalSize::new(1.0, 1.0).into(),
        };
        self.caption_web_ready.store(false, Ordering::Relaxed);
        let ready = self.caption_web_ready.clone();
        let live_boxes = self.caption_live_boxes.clone();
        // __reportCapBoxes(t): measure every ACTIVE caption's box in the real DOM (the
        // same filter/order CaptionLayer uses) as canvas fractions, and post them back.
        // This is the caption drag hit-test's source of truth — font metrics, wrapping
        // and the bg bar all come from the renderer itself, never re-estimated.
        let report_js = "window.__reportCapBoxes=function(t){try{\
var p=window.__nativeCaptionPayload;if(!p||!window.ipc)return;\
var fps=(Number.isFinite(p.fps)&&p.fps>1)?p.fps:30;\
var fr=Math.round(t*fps),hidden=new Set(p.hiddenCaptionIds||[]);\
var acts=p.captions.filter(function(c){return c.text&&c.text.trim()&&!hidden.has(c.id)&&fr>=Math.round(c.start*fps)&&fr<Math.round(c.end*fps)});\
var root=document.querySelector('div[data-ready]');if(!root)return;\
var cont=root.firstElementChild;if(!cont)return;\
var layer=cont.firstElementChild;if(!layer)return;\
var cr=layer.getBoundingClientRect();if(!(cr.width>1))return;\
var kids=[].filter.call(layer.children,function(el){return el.tagName!=='STYLE'});\
if(kids.length!==acts.length)return;\
var out={};\
for(var i=0;i<acts.length;i++){var para=kids[i].querySelector('p');var b=(para?para.parentElement:(kids[i].firstElementChild||kids[i])).getBoundingClientRect();\
out[acts[i].id||String(i)]=[(b.left-cr.left)/cr.width,(b.top-cr.top)/cr.height,b.width/cr.width,b.height/cr.height];}\
window.ipc.postMessage('capboxes:'+JSON.stringify(out));\
}catch(e){}};";
        let built = wry::WebViewBuilder::new()
            .with_url("http://127.0.0.1:3000/caption-frame")
            .with_transparent(true)
            .with_focused(false)
            .with_bounds(bounds)
            .with_initialization_script(
                &format!("{report_js}setInterval(()=>{{if(!window.__captionReadySent&&window.__setCaptionPayload&&window.ipc){{window.__captionReadySent=1;window.ipc.postMessage('caption-ready')}}}},100);"),
            )
            .with_ipc_handler(move |req| {
                if req.body() == "caption-ready" {
                    ready.store(true, Ordering::Relaxed);
                } else if let Some(json) = req.body().strip_prefix("capboxes:") {
                    if let Ok(map) = serde_json::from_str::<std::collections::HashMap<String, [f64; 4]>>(json) {
                        if let Ok(mut lb) = live_boxes.lock() {
                            *lb = map;
                        }
                    }
                }
            })
            .with_browser_accelerator_keys(false)
            .with_default_context_menus(false)
            .build_as_child(frame);
        match built {
            Ok(web) => {
                // Keep the exact browser renderer used by preview/export, but make its
                // entire native window tree visual-only. egui remains the one and only
                // keyboard/mouse input path.
                #[cfg(target_os = "windows")]
                {
                    use wry::WebViewExtWindows as _;
                    let mut hwnd = Default::default();
                    if unsafe { web.controller().ParentWindow(&mut hwnd) }.is_ok() {
                        unsafe {
                            make_caption_window_tree_visual_only(hwnd.0 as isize);
                        }
                    }
                }
                self.caption_web = Some(web);
                self.caption_web_sig = 0;
                self.caption_web_t = f64::NAN;
            }
            Err(e) => eprintln!("caption WebView2 init failed: {e}"),
        }
    }

    fn caption_web_captions(&self) -> serde_json::Value {
        let mut out = Vec::new();
        for tr in &self.doc.seq.tracks {
            if tr.hidden {
                continue;
            }
            for c in &tr.clips {
                if c.text.is_none() || c.asset_id.is_some() || c.region.is_some() {
                    continue;
                }
                let text = self.caption_display_text(c);
                if text.trim().is_empty() {
                    continue;
                }
                out.push(serde_json::json!({
                    "id": c.id,
                    "text": text,
                    "start": c.timeline_start,
                    "end": c.timeline_end,
                    "design": c.style.clone().unwrap_or_else(|| serde_json::json!({})),
                    "words": c.words.clone(),
                    "transform_keys": c.transform_keys.clone(),
                    "opacity": c.visual_opacity(),
                }));
            }
        }
        serde_json::Value::Array(out)
    }

    /// The value every UI surface should show while a caption is being edited. The
    /// draft is an IME transaction only; once it settles it is written to `clip.text`.
    fn caption_display_text(&self, clip: &model::Clip) -> String {
        self.caption_drafts
            .get(&clip.id)
            .map(|draft| draft.text.clone())
            .or_else(|| clip.text.clone())
            .unwrap_or_default()
    }

    fn sync_caption_web(&mut self, frame: &eframe::Frame, rect: egui::Rect, visible: bool) {
        self.ensure_caption_web(frame);
        // Captions follow the timeline frame actually published to the preview, not the
        // continuously-running audio clock. Video and text therefore share one boundary.
        let t = if self.playing {
            let shown = self.shared.frame.lock().unwrap().t;
            if shown.is_finite() && (shown - self.displayed_t()).abs() < 0.75 {
                shown
            } else {
                self.grid_quantize(self.displayed_t())
            }
        } else {
            self.grid_quantize(self.t)
        };
        // GPU and WebView must agree on ownership for this exact displayed frame. The
        // document payload stays cached, while this small ID set is refreshed at cuts
        // and when a caption cache PNG becomes available.
        let mut hidden_caption_ids: Vec<String> = native_caption_ids(&self.doc, t).into_iter().collect();
        hidden_caption_ids.sort();
        use std::hash::{Hash, Hasher};
        let mut hidden_hasher = std::collections::hash_map::DefaultHasher::new();
        hidden_caption_ids.hash(&mut hidden_hasher);
        let hidden_sig = hidden_hasher.finish();
        if std::env::var("NATIVE_ZCAP_DEBUG").is_ok() {
            static LAST: OnceLock<Mutex<String>> = OnceLock::new();
            let msg = format!("ZCAP t={t:.2} native={hidden_caption_ids:?}");
            let last = LAST.get_or_init(|| Mutex::new(String::new()));
            if let Ok(mut l) = last.lock() {
                if *l != msg {
                    eprintln!("{msg}");
                    *l = msg;
                }
            }
        }
        // Rebuild + hash the caption payload only when the DOCUMENT changed (Arc
        // identity; live typing resets caption_web_sig) — not every frame.
        let doc_ptr = Arc::as_ptr(&self.doc) as usize;
        let dirty = doc_ptr != self.caption_doc_ptr
            || self.caption_web_sig == 0
            || !self.caption_web_ready.load(Ordering::Relaxed);
        let (captions, sig) = if dirty {
            let captions = self.caption_web_captions();
            let mut hasher = std::collections::hash_map::DefaultHasher::new();
            captions.to_string().hash(&mut hasher);
            let sig = hasher.finish();
            self.caption_doc_ptr = doc_ptr;
            (Some(captions), sig)
        } else {
            (None, self.caption_web_sig)
        };
        let Some(web) = self.caption_web.as_ref() else { return };
        #[cfg(target_os = "windows")]
        {
            use wry::WebViewExtWindows as _;
            let mut hwnd = Default::default();
            if unsafe { web.controller().ParentWindow(&mut hwnd) }.is_ok() {
                // WebView2 creates its render child asynchronously. Re-applying this is
                // intentional and idempotent: late-created Chromium HWNDs cannot become
                // a second input owner during startup.
                unsafe { make_caption_window_tree_visual_only(hwnd.0 as isize) };
            }
        }
        let _ = web.set_visible(visible && !(self.assistant.open && self.assistant.immersive));
        if !visible {
            return;
        }
        let bounds = wry::Rect {
            position: wry::dpi::LogicalPosition::new(rect.left() as f64, rect.top() as f64).into(),
            size: wry::dpi::LogicalSize::new(rect.width() as f64, rect.height() as f64).into(),
        };
        let _ = web.set_bounds(bounds);
        // Do not let a new WebView caption appear over pixels composed under the
        // previous owner. The media thread publishes this generation only after it has
        // rebuilt the current frame with the matching GPU/WebView ownership plan.
        let wanted_epoch = self.shared.caption_epoch.load(Ordering::Relaxed);
        let presented_epoch = self.shared.frame.lock().unwrap().caption_epoch;
        if presented_epoch != wanted_epoch {
            return;
        }
        let web_ready = self.caption_web_ready.load(Ordering::Relaxed);
        if (sig != self.caption_web_sig || !web_ready) && captions.is_some() {
            let payload = serde_json::json!({
                "outW": canvas_w(),
                "outH": canvas_h(),
                "fps": self.doc.seq.frame_rate.unwrap_or(30.0),
                "time": t,
                "hiddenCaptionIds": hidden_caption_ids,
                "captions": captions.unwrap(),
            });
            let js = format!(
                "window.__nativeCaptionPayload={0};window.__setCaptionPayload&&window.__setCaptionPayload(window.__nativeCaptionPayload).then(function(){{window.__reportCapBoxes&&window.__reportCapBoxes({t:.6})}});",
                payload
            );
            let _ = web.evaluate_script(&js);
            if web_ready {
                self.caption_web_sig = sig;
            }
            self.caption_web_t = t;
            self.caption_web_hidden_sig = hidden_sig;
        } else if !self.caption_web_t.is_finite()
            || (t - self.caption_web_t).abs() > 0.001
            || hidden_sig != self.caption_web_hidden_sig
        {
            let hidden_json = serde_json::to_string(&hidden_caption_ids).unwrap_or_else(|_| "[]".to_string());
            let _ = web.evaluate_script(&format!(
                "window.__renderCaptionAt&&window.__renderCaptionAt({t:.6},{hidden_json}).then(function(){{window.__reportCapBoxes&&window.__reportCapBoxes({t:.6})}});"
            ));
            self.caption_web_t = t;
            self.caption_web_hidden_sig = hidden_sig;
        }
    }

    /// Advance caption ownership. The producer drops every cached/ring frame from the
    /// prior generation before it publishes this one, so GPU and WebView never paint the
    /// same caption at once.
    fn bump_caption_epoch(&mut self) {
        self.shared.caption_epoch.fetch_add(1, Ordering::Relaxed);
        self.caption_web_sig = 0;
        self.push_req(false);
    }

    /// Stage an IME edit without rebuilding the whole timeline on each composition
    /// change. The WebView is the temporary visual owner; `clip.text` is committed
    /// after the user pauses, changes focus, or explicitly saves the dialog.
    fn stage_caption_text(&mut self, clip_id: &str, text: String) {
        let first_change = !self.caption_drafts.contains_key(clip_id);
        self.caption_drafts.insert(
            clip_id.to_string(),
            CaptionDraft {
                text,
                commit_at: Instant::now() + std::time::Duration::from_millis(350),
            },
        );
        caption_live::activate(clip_id);
        // The document did not change, so invalidate only the small overlay payload.
        self.caption_web_sig = 0;
        if first_change {
            self.bump_caption_epoch();
        }
    }

    fn commit_caption_drafts(&mut self, only: Option<&str>) {
        let now = Instant::now();
        let due: Vec<(String, String)> = self
            .caption_drafts
            .iter()
            .filter(|(id, draft)| only == Some(id.as_str()) || only.is_none() && draft.commit_at <= now)
            .map(|(id, draft)| (id.clone(), draft.text.clone()))
            .collect();
        for (id, text) in due {
            self.caption_drafts.remove(&id);
            self.apply_edit(false, move |raw| edits::set_text(raw, &id, &text));
            // Keep WebView ownership until caption_cache_pass sees a PNG for this
            // committed document value, then it performs the atomic GPU handoff.
        }
    }

    fn flush_caption_drafts(&mut self) {
        let ids: Vec<String> = self.caption_drafts.keys().cloned().collect();
        for id in ids {
            self.commit_caption_drafts(Some(&id));
        }
    }

    /// Designed captions: when the caption set changes, ask the server for the SAME
    /// /caption-frame PNGs the export burns in (cached server-side); the preview then
    /// shows the real design instead of plain text.
    fn caption_cache_pass(&mut self) {
        use std::hash::{Hash, Hasher};
        let mut specs: Vec<(String, serde_json::Value)> = Vec::new();
        let mut missing_cache = false;
        let mut completed_live = Vec::new();
        let tracks = self.doc.raw.get(0).and_then(|c| c.get("timeline")).and_then(|t| t.get("sequence")).and_then(|sq| sq.get("tracks")).and_then(|t| t.as_array());
        if let Some(tracks) = tracks {
            for tr in tracks {
                for cl in tr.get("clips").and_then(|c| c.as_array()).map(|a| a.as_slice()).unwrap_or(&[]) {
                    let text = cl.get("text").and_then(|t| t.as_str()).unwrap_or("");
                    if text.trim().is_empty() {
                        continue;
                    }
                    let id = cl.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                    let design = caption_render_style(cl.get("style").unwrap_or(&serde_json::Value::Null));
                    let spec = serde_json::json!({
                        "text": text,
                        "design": design,
                        "words": cl.get("words").cloned().unwrap_or(serde_json::json!([])),
                    });
                    let key_src = serde_json::json!({
                        "w": canvas_w(),
                        "h": canvas_h(),
                        "t": text,
                        "d": spec.get("design").cloned().unwrap_or_else(|| serde_json::json!({})),
                        "words": spec.get("words").cloned().unwrap_or_else(|| serde_json::json!([])),
                    });
                    let key = {
                        use sha1::{Digest, Sha1};
                        let mut hasher = Sha1::new();
                        hasher.update(py_json(&key_src).as_bytes());
                        format!("{:x}", hasher.finalize())[..16].to_string()
                    };
                    let png = std::path::Path::new(&self.doc.asset_dir).join("caption-cache").join(format!("{key}.png"));
                    if !png.exists() || std::fs::metadata(&png).map(|m| m.len() == 0).unwrap_or(true) {
                        missing_cache = true;
                    } else if caption_live::is_active(&id) && !self.caption_drafts.contains_key(&id) {
                        completed_live.push(id.clone());
                    }
                    specs.push((id, spec));
                }
            }
        }
        let mut h = std::collections::hash_map::DefaultHasher::new();
        for (id, sp) in &specs {
            id.hash(&mut h);
            sp.to_string().hash(&mut h);
        }
        let sig = h.finish();
        if specs.is_empty() {
            return;
        }
        // Commit handoff only after the PNG for the committed live text exists. The
        // epoch gate in sync_caption_web keeps WebView visible until the GPU frame for
        // this new owner has actually been published.
        if !completed_live.is_empty() {
            for id in completed_live {
                caption_live::clear(&id);
            }
            self.bump_caption_epoch();
        }
        if sig == self.cap_sig {
            if !missing_cache {
                return;
            }
            let retry_key = "__caption_cache_retry__".to_string();
            if self
                .cap_probe
                .get(&retry_key)
                .map(|t| t.elapsed().as_secs_f32() < 2.5)
                .unwrap_or(false)
            {
                return;
            }
            self.cap_probe.insert(retry_key, Instant::now());
        }
        self.cap_sig = sig;
        self.cap_req_ids = specs.iter().map(|(id, _)| id.clone()).collect();
        let items: Vec<serde_json::Value> = specs.into_iter().map(|(_, sp)| sp).collect();
        let body = serde_json::json!({
            "room_id": self.room_id(),
            "outW": canvas_w(),
            "outH": canvas_h(),
            "items": items,
        });
        self.lib_post("capcache", "/api/v1/production-assets/caption-cache".into(), body);
    }

    /// The playhead time the user is LOOKING AT. While playing, self.t is stale (it only
    /// syncs on pause) — playhead-anchored edits (F/S/mosaic/insert) that used self.t
    /// landed up to ±0.3s away from the displayed frame, with a SIGN that depended on
    /// history: the measured "freeze captures a different scene, inconsistently".
    fn displayed_t(&self) -> f64 {
        if self.playing {
            f64::from_bits(self.shared.clock_bits.load(Ordering::Relaxed))
        } else {
            self.t
        }
    }

    /// One arrow-key sequence-frame step (exactly what the key handler runs).
    fn step_once(&mut self, dir: f64) {
        let fstep = 1.0 / self.timeline_fps();
        // The editor timeline and output are CFR at the chosen sequence rate. Do not derive arrow movement from
        // source PTS: mixed 30/60fps (or VFR) assets then make the same key move a different
        // distance depending on the clip under the playhead. Snap the current position to the
        // sequence grid first, then advance exactly one output frame.
        self.t = (((self.t / fstep).round() + dir) * fstep).clamp(0.0, self.dur);
        // EXACT from the first paint. The old scrub-then-settle sequence flashed a
        // budget-limited provisional frame (stale tracked-blur mask etc.) for ~100ms on
        // every arrow step — frame-by-frame blur inspection then read those flashes as
        // "the blur is off on this frame". A single frame step is cheap to compose
        // exactly; backward steps pay one seek (~100-300ms) for a picture that is
        // always the truth.
        self.step_settle_at = None;
        self.push_req(false);
    }

    /// NATIVE_STEP_PROBE: drive the REAL user path end-to-end — play across a freeze
    /// (fills the frame cache exactly like a session does), pause, frame-step across
    /// both freeze boundaries, and save what the ENGINE SERVED (shared.frame — the very
    /// pixels the pane paints) at each landing. This is the verification the compose-
    /// only --dump-frame could not give: it includes the cache serve path.
    fn step_probe_drive(&mut self) {
        let Some((phase, since)) = self.step_probe else { return };
        let out_dir = std::env::var("NATIVE_PROBE_OUT")
            .unwrap_or_else(|_| format!("{}/stills", self.doc.asset_dir));
        let ms = since.elapsed().as_millis();
        let fz = self
            .doc
            .seq
            .tracks
            .iter()
            .flat_map(|tr| tr.clips.iter())
            .filter(|c| c.is_freeze() && c.freeze_still.is_some())
            .max_by(|a, b| a.timeline_start.total_cmp(&b.timeline_start))
            .cloned();
        let Some(fz) = fz else {
            eprintln!("STEPPROBE no freeze — abort");
            std::process::exit(2);
        };
        let snap = |app: &App, name: &str| {
            let f = app.shared.frame.lock().unwrap();
            if f.rgba.len() == (canvas_w() * canvas_h() * 4) as usize {
                let p = format!("{out_dir}/{name}.png");
                let _ = std::fs::create_dir_all(&out_dir);
                let _ = image::save_buffer(&p, &f.rgba, canvas_w(), canvas_h(), image::ColorType::Rgba8);
                eprintln!("STEPPROBE snap {name} t={:.4} seq={}", app.t, f.seq);
            } else {
                eprintln!("STEPPROBE snap {name} EMPTY");
            }
        };
        let mut goto = |app: &mut App, p: u8| {
            app.step_probe = Some((p, Instant::now()));
        };
        match phase {
            // warm up, then play from 2s before the freeze (fills the cache/ring the
            // way a real session does)
            0 if ms > 2500 => {
                self.t = (fz.timeline_start - 2.0).max(0.0);
                self.playing = true;
                self.push_req(false);
                eprintln!("STEPPROBE play from {:.3}", self.t);
                goto(self, 1);
            }
            // once the clock is inside the freeze, pause exactly like the user does
            1 => {
                let c = f64::from_bits(self.shared.clock_bits.load(Ordering::Relaxed));
                if c > fz.timeline_start + 0.4 {
                    self.pause_at_displayed();
                    goto(self, 2);
                } else if ms > 15000 {
                    eprintln!("STEPPROBE play never reached freeze — abort");
                    std::process::exit(2);
                }
            }
            // settle, snap the still as served
            2 if ms > 900 => {
                snap(self, "probe_still");
                // scrub near the freeze tail (a user positioning before stepping out)
                self.t = fz.timeline_end - 0.02;
                self.push_req(false);
                goto(self, 3);
            }
            3 if ms > 900 => {
                snap(self, "probe_still_tail");
                self.step_once(1.0); // step OUT across the right boundary
                goto(self, 4);
            }
            4 if ms > 900 => {
                snap(self, "probe_right_first");
                self.step_once(1.0);
                goto(self, 5);
            }
            5 if ms > 900 => {
                snap(self, "probe_right_second");
                // over to the left boundary
                self.t = fz.timeline_start + 0.02;
                self.push_req(false);
                goto(self, 6);
            }
            6 if ms > 900 => {
                snap(self, "probe_still_head");
                self.step_once(-1.0); // step OUT across the left boundary
                goto(self, 7);
            }
            7 if ms > 900 => {
                snap(self, "probe_left_last");
                eprintln!("STEPPROBE done fz={} span=[{:.4},{:.4}]", fz.id, fz.timeline_start, fz.timeline_end);
                std::process::exit(0);
            }
            _ => {}
        }
    }

    /// Sync + pause at the displayed frame (for edits that imply inspecting a frame).
    fn pause_at_displayed(&mut self) {
        if self.playing {
            self.t = self.displayed_t();
            self.playing = false;
            self.resume_pending = None;
            self.push_req(false);
        }
    }

    fn toggle_play(&mut self) {
        if self.playing {
            // freeze the playhead where the audible clock actually was
            self.t = f64::from_bits(self.shared.clock_bits.load(Ordering::Relaxed));
        }
        self.playing = !self.playing;
        if self.playing {
            // 末尾で止まった状態のSpace/▶: 再生範囲の先頭から再生し直す
            // （in/out指定があればその頭、サブタブは最初の緑区間の頭、通常は0）。
            // 自然停止はコーデック都合で末尾の1〜2フレーム手前に着地する（実測: 10.100s の
            // 動画で 10.067s 停止）ため、余裕は2.5フレーム取る
            let end_eps = 2.5 / self.timeline_fps().max(1.0);
            let restart_to: Option<f64> = if !self.on_sub_tab() {
                if let Some((ra, rb)) = self.export_range {
                    (self.t >= rb - end_eps || self.t >= self.dur - end_eps).then_some(ra)
                } else {
                    (self.t >= self.dur - end_eps).then_some(0.0)
                }
            } else {
                let first = self.sub_ranges().first().map(|&(a, _)| a).unwrap_or(0.0);
                let last_end = self.sub_ranges().last().map(|&(_, b)| b).unwrap_or(self.dur);
                (self.t >= last_end - end_eps || self.t >= self.dur - end_eps).then_some(first)
            };
            if let Some(a) = restart_to {
                self.t = a;
            }
            // サブタイムライン: 再生開始位置で意図を汲む — 緑区間の中から始めたら
            // 「区間だけ飛び飛び」、外（暗転部分）から始めたら普通の全体再生。
            // 判定は再生セッション開始時に一度だけ。
            self.sub_skip_active = self.on_sub_tab()
                && self
                    .sub_ranges()
                    .iter()
                    .any(|&(a, b)| self.t >= a - 0.001 && self.t < b);
        }
        self.resume_pending = None;
        self.push_req(false);
    }

    fn cycle_playback_speed(&mut self) {
        if self.playing {
            self.t = self.displayed_t().clamp(0.0, self.dur);
        }
        self.playback_speed = if self.playback_speed < 1.5 {
            2.0
        } else if self.playback_speed < 3.0 {
            4.0
        } else {
            1.0
        };
        self.push_req(false);
    }

    fn split_at_playhead(&mut self) {
        let t = self.displayed_t();
        let base: Vec<String> = if self.selected.is_empty() {
            self.doc
                .seq
                .tracks
                .iter()
                .flat_map(|tr| tr.clips.iter())
                .filter(|c| t > c.timeline_start + 0.05 && t < c.timeline_end - 0.05)
                .map(|c| c.id.clone())
                .collect()
        } else {
            self.selected.clone()
        };
        if !base.is_empty() {
            let ids = edits::expand_links(&self.doc.raw, &base);
            let salt = self.salt;
            self.salt += 1;
            let before: std::collections::HashSet<String> = self
                .doc
                .seq
                .tracks
                .iter()
                .flat_map(|tr| tr.clips.iter())
                .map(|c| c.id.clone())
                .collect();
            self.apply_edit(true, |raw| edits::split_clips(raw, &ids, t, salt));
            // 分割で生まれた右半分も選択に加える: カット点の瞬間は右クリップの領域
            // なので、右が未選択だと枠がその場で消えて見えた
            let new_ids: Vec<String> = self
                .doc
                .seq
                .tracks
                .iter()
                .flat_map(|tr| tr.clips.iter())
                .map(|c| c.id.clone())
                .filter(|i| !before.contains(i))
                .collect();
            for i in new_ids {
                if !self.selected.contains(&i) {
                    self.selected.push(i);
                }
            }
        }
    }

    fn delete_selected(&mut self, force_ripple: bool) {
        if self.selected.is_empty() {
            return;
        }
        let ids = edits::expand_links(&self.doc.raw, &self.selected);
        self.selected.clear();
        if force_ripple {
            self.apply_edit(true, |raw| edits::ripple_delete(raw, &ids));
            return;
        }
        let mut mag: Vec<String> = Vec::new();
        let mut plain: Vec<String> = Vec::new();
        for (ti, tr) in self.doc.seq.tracks.iter().enumerate() {
            let magnetic = self.doc.is_magnet(ti);
            for c in &tr.clips {
                if ids.contains(&c.id) {
                    if magnetic {
                        mag.push(c.id.clone());
                    } else {
                        plain.push(c.id.clone());
                    }
                }
            }
        }
        let mag = if mag.is_empty() { mag } else { edits::expand_links(&self.doc.raw, &mag) };
        let plain: Vec<String> = plain.into_iter().filter(|i| !mag.contains(i)).collect();
        self.apply_edit(true, move |raw| {
            // attached clips (head-under rule, any lane in front) go with EVERY deletion
            let mut all: Vec<String> = mag.iter().chain(plain.iter()).cloned().collect();
            let attached = edits::attached_to(raw, &all);
            if !attached.is_empty() {
                let att = edits::expand_links(raw, &attached);
                edits::delete_clips(raw, &att);
                all.retain(|i| !att.contains(i));
            }
            let plain: Vec<String> = all.iter().filter(|i| plain.contains(i)).cloned().collect();
            let mag: Vec<String> = all.iter().filter(|i| mag.contains(i)).cloned().collect();
            if !plain.is_empty() {
                edits::delete_clips(raw, &plain);
            }
            if !mag.is_empty() {
                edits::magnet_delete(raw, &mag);
            }
        });
    }

    fn do_undo(&mut self) {
        if let Some(prev) = self.undo.pop() {
            match serde_json::from_str(&prev) {
                Ok(v) => {
                    self.redo.push(self.doc.raw.to_string());
                    self.restore(v);
                }
                Err(e) => eprintln!("UNDO parse failed: {e}"),
            }
        }
    }

    fn do_redo(&mut self) {
        if let Some(next) = self.redo.pop() {
            match serde_json::from_str(&next) {
                Ok(v) => {
                    self.undo.push(self.doc.raw.to_string());
                    self.restore(v);
                }
                Err(e) => eprintln!("REDO parse failed: {e}"),
            }
        }
    }

    fn zoom_fit(&mut self, width: f32) {
        self.pps = ((width - 112.0 - 40.0) / (self.dur.max(1.0) as f32)).clamp(1.0, 400.0);
        self.scroll_x = 0.0;
    }

    /// transport bar under the preview: jump/step/play buttons + seek bar + timecode
    fn transport_ui(&mut self, ui: &mut egui::Ui) {
        let timeline_fps = self.timeline_fps();
        let fmt_tc = |t: f64| {
            let fr = ((t * timeline_fps).round() as i64).max(0);
            let fps_i = timeline_fps.round() as i64;
            format!("{:02}:{:02}:{:02}", fr / (fps_i * 60), (fr / fps_i) % 60, fr % fps_i)
        };
        ui.horizontal_centered(|ui| {
            ui.add_space(10.0);
            let mut tbtn = |ui: &mut egui::Ui, glyph: &str, tip: &str| -> bool {
                ui.add(
                    egui::Button::new(egui::RichText::new(glyph).size(17.0))
                        .min_size(egui::vec2(34.0, 30.0))
                        .frame(false),
                )
                .on_hover_text(tip)
                .clicked()
            };
            if tbtn(ui, "⏮", "先頭へ (Home)") {
                self.playing = false;
                self.t = 0.0;
                self.push_req(false);
            }
            if tbtn(ui, "⏪", "1フレーム戻る (←)") {
                self.playing = false;
                self.step_once(-1.0);
            }
            // The transport owns its geometry; fallback-font glyph metrics must
            // never shift the adjacent step buttons or the seek bar.
            let (play_rect, play_button) = ui.allocate_exact_size(
                egui::vec2(44.0, 36.0), egui::Sense::click());
            let play_button = play_button.on_hover_text("再生 / 一時停止 (Space)");
            let fill = if self.playing { egui::Color32::from_rgb(60,60,66) } else { UI_ACCENT };
            ui.painter().rect_filled(play_rect,16.0,fill);
            if play_button.hovered() || play_button.has_focus() {
                ui.painter().rect_stroke(play_rect.shrink(1.0),16.0,
                    egui::Stroke::new(1.0,egui::Color32::from_white_alpha(100)));
            }
            let center=play_rect.center();
            if self.playing {
                for dx in [-4.5,4.5] {
                    ui.painter().rect_filled(egui::Rect::from_center_size(
                        center+egui::vec2(dx,0.0),egui::vec2(4.0,16.0)),0.5,egui::Color32::WHITE);
                }
            } else {
                ui.painter().add(egui::Shape::convex_polygon(vec![
                    center+egui::vec2(-5.0,-8.0), center+egui::vec2(8.0,0.0),
                    center+egui::vec2(-5.0,8.0)],egui::Color32::WHITE,egui::Stroke::NONE));
            }
            play_button.widget_info(|| egui::WidgetInfo::labeled(
                egui::WidgetType::Button, true, if self.playing { "一時停止" } else { "再生" }));
            self.transport_button=Some(play_button.rect);
            if play_button.clicked() {
                play_button.surrender_focus();
                self.toggle_play();
            }
            if tbtn(ui, "⏩", "1フレーム進む (→)") {
                self.playing = false;
                self.step_once(1.0);
            }
            if tbtn(ui, "⏭", "末尾へ (End)") {
                self.playing = false;
                self.t = self.dur;
                self.push_req(false);
            }
            if self.shared.audio_unavailable.load(Ordering::Relaxed) {
                ui.label(egui::RichText::new("音声出力を再接続中").size(11.0).color(egui::Color32::from_rgb(230,190,110)));
            }
            ui.add_space(8.0);
            // timecode (current / total)
            let tc_now = if self.playing {
                f64::from_bits(self.shared.clock_bits.load(Ordering::Relaxed))
            } else {
                self.t
            };
            // seek bar fills the middle
            let tc_w = 150.0;
            let bar_w = (ui.available_width() - tc_w - 16.0).max(60.0);
            let (bar, bresp) = ui.allocate_exact_size(egui::vec2(bar_w, 26.0), egui::Sense::click_and_drag());
            let pb = ui.painter_at(bar);
            let line_y = bar.center().y;
            pb.line_segment(
                [egui::pos2(bar.left(), line_y), egui::pos2(bar.right(), line_y)],
                egui::Stroke::new(4.0, egui::Color32::from_rgb(52, 52, 58)),
            );
            let frac = (tc_now / self.dur.max(0.001)).clamp(0.0, 1.0) as f32;
            let px = bar.left() + frac * bar.width();
            pb.line_segment(
                [egui::pos2(bar.left(), line_y), egui::pos2(px, line_y)],
                egui::Stroke::new(4.0, UI_ACCENT),
            );
            pb.circle_filled(egui::pos2(px, line_y), if bresp.hovered() || bresp.dragged() { 8.0 } else { 6.0 }, egui::Color32::WHITE);
            if bresp.drag_started() && self.playing {
                self.t = f64::from_bits(self.shared.clock_bits.load(Ordering::Relaxed));
                self.playing = false;
                self.resume_on_release = true;
                self.push_req(false);
            }
            if bresp.dragged() || bresp.clicked() {
                if let Some(pos) = bresp.interact_pointer_pos() {
                    let f = ((pos.x - bar.left()) / bar.width()).clamp(0.0, 1.0);
                    self.playing = false;
                    self.t = (f as f64) * self.dur;
                    self.push_req(bresp.dragged());
                }
            }
            if bresp.drag_stopped() {
                self.push_req(false);
                if self.resume_on_release {
                    self.resume_on_release = false;
                    self.resume_pending = Some(Instant::now());
                }
            }
            ui.add(
                egui::Label::new(
                    egui::RichText::new(format!("{} / {}", fmt_tc(tc_now), fmt_tc(self.dur)))
                        .monospace()
                        .size(13.0)
                        .color(egui::Color32::from_gray(200)),
                )
                .selectable(false),
            );
        });
    }

    fn copy_selected(&mut self) {
        if self.selected.is_empty() { return; }
        self.clip_clipboard=Some(edits::copy_clips(&self.doc.raw,&self.selected));
        self.toast("選択部分をコピーしました");
    }

    fn paste_at_playhead(&mut self) {
        if let Some(bundle)=self.clip_clipboard.clone() {
            let at=self.t;
            let salt=std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_nanos() as u64;
            self.apply_edit(true,move |raw| { edits::paste_clips(raw,&bundle,at,salt); });
            self.toast("再生位置に貼り付けました");
        }
    }

    /// icon strip above the ruler: undo/redo, split, delete, zoom (Filmora layout)
    fn timeline_toolbar(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            ui.add_space(6.0);
            ui.menu_button("編集", |ui| {
                if ui.add_enabled(!self.selected.is_empty(),egui::Button::new("コピー　Ctrl+C")).clicked() {
                    self.copy_selected();ui.close_menu();
                }
                if ui.add_enabled(self.clip_clipboard.is_some(),egui::Button::new("再生位置に貼り付け　Ctrl+V")).clicked() {
                    self.paste_at_playhead();ui.close_menu();
                }
                ui.separator();
                if ui.button("保存　Ctrl+S").clicked() {
                    match self.save_document() {
                        Ok(true)=>{self.save_at=None;self.toast("保存しました");},
                        Ok(false)=>{},
                        Err(e)=>self.toast(&format!("保存できませんでした: {e}")),
                    }
                    ui.close_menu();
                }
                if ui.button("操作一覧　F1").clicked() {
                    self.show_help=true;ui.close_menu();
                }
            });
            let mut ibtn = |ui: &mut egui::Ui, glyph: &str, tip: &str, enabled: bool| -> bool {
                ui.add_enabled(
                    enabled,
                    egui::Button::new(egui::RichText::new(glyph).size(15.0))
                        .min_size(egui::vec2(30.0, 26.0))
                        .frame(false),
                )
                .on_hover_text(tip)
                .clicked()
            };
            let can_undo = !self.undo.is_empty();
            let can_redo = !self.redo.is_empty();
            if ibtn(ui, "↶", "元に戻す (Ctrl+Z)", can_undo) {
                self.do_undo();
            }
            if ibtn(ui, "↷", "やり直し (Ctrl+Y)", can_redo) {
                self.do_redo();
            }
            ui.separator();
            if ibtn(ui, "✂", "再生ヘッドで分割 (S)", true) {
                self.split_at_playhead();
            }
            if ibtn(ui, "🗑", "削除 (Del)", !self.selected.is_empty()) {
                self.delete_selected(false);
            }
            ui.separator();
            let (mr, mresp) = ui.allocate_exact_size(egui::vec2(32.0, 26.0), egui::Sense::click());
            let bg = if self.playhead_snap {
                UI_ACCENT
            } else if mresp.hovered() {
                egui::Color32::from_rgb(46, 46, 52)
            } else {
                egui::Color32::from_rgb(34, 34, 39)
            };
            ui.painter().rect_filled(mr, 4.0, bg);
            let col = if self.playhead_snap { egui::Color32::WHITE } else { egui::Color32::from_gray(190) };
            let cx = mr.center().x;
            let top = mr.top() + 7.0;
            let bot = mr.bottom() - 6.0;
            let left = cx - 7.0;
            let right = cx + 7.0;
            let stroke = egui::Stroke::new(2.0, col);
            ui.painter().line_segment([egui::pos2(left, top), egui::pos2(left, bot)], stroke);
            ui.painter().line_segment([egui::pos2(right, top), egui::pos2(right, bot)], stroke);
            ui.painter().line_segment([egui::pos2(left, bot), egui::pos2(cx - 3.0, bot + 3.0)], stroke);
            ui.painter().line_segment([egui::pos2(right, bot), egui::pos2(cx + 3.0, bot + 3.0)], stroke);
            ui.painter().line_segment([egui::pos2(cx - 3.0, bot + 3.0), egui::pos2(cx + 3.0, bot + 3.0)], stroke);
            ui.painter().rect_filled(
                egui::Rect::from_min_max(egui::pos2(left - 2.0, top - 2.0), egui::pos2(left + 3.0, top + 2.0)),
                1.0,
                egui::Color32::from_rgb(245, 80, 80),
            );
            ui.painter().rect_filled(
                egui::Rect::from_min_max(egui::pos2(right - 3.0, top - 2.0), egui::pos2(right + 2.0, top + 2.0)),
                1.0,
                egui::Color32::from_rgb(80, 150, 255),
            );
            if mresp.on_hover_text("Snap playhead and clips to edges").clicked() {
                self.playhead_snap = !self.playhead_snap;
                self.snap_line = None;
            }
            ui.separator();
            // ---- シーケンスタブ: メイン | サブ… | ＋ ----
            // サブ=独立した複製（素材はID共有＝軽い）。編集してもメインは不変。
            {
                let active = self.active_seq_id();
                let tabs = self.seq_tabs();
                if ui.selectable_label(active == "main", "メイン").clicked() && active != "main" {
                    self.switch_seq("main");
                }
                let mut want_switch: Option<String> = None;
                let mut want_delete: Option<String> = None;
                let mut arm: Option<(String, String)> = None;
                for (id, name) in &tabs {
                    let sel = *id == active;
                    let armed = matches!(&self.sub_del_arm, Some((aid, at)) if aid == id && at.elapsed().as_secs() < 2);
                    let label = if armed { format!("🗑 {name}?") } else { name.clone() };
                    let resp = ui
                        .selectable_label(sel, label)
                        .on_hover_text("クリック=切替 / 右クリック2回=削除。サブは独立した複製で、編集してもメインは変わりません");
                    if resp.clicked() && !sel {
                        want_switch = Some(id.clone());
                    }
                    if resp.secondary_clicked() {
                        if armed {
                            want_delete = Some(id.clone());
                        } else {
                            arm = Some((id.clone(), name.clone()));
                        }
                    }
                }
                if let Some((id, name)) = arm {
                    self.sub_del_arm = Some((id, Instant::now()));
                    self.toast(&format!("「{name}」を削除するにはもう一度右クリック"));
                }
                if want_delete.is_some() {
                    self.sub_del_arm = None;
                }
                if ui
                    .small_button("＋")
                    .on_hover_text("今開いているタイムラインを複製してサブを作る（元は変更されない・素材は共有）")
                    .clicked()
                {
                    self.create_sub();
                }
                if let Some(id) = want_switch {
                    self.switch_seq(&id);
                }
                if let Some(id) = want_delete {
                    self.delete_sub(&id);
                }
            }
            ui.separator();
            ui.label(
                egui::RichText::new(if self.selected.is_empty() {
                    String::new()
                } else {
                    format!("{}個選択中", self.selected.len())
                })
                .small()
                .weak(),
            );
            // zoom cluster on the right (fixed-height child: a bare with_layout would
            // claim the panel's full remaining height and balloon the panel)
            let w = ui.available_width();
            ui.allocate_ui_with_layout(
                egui::vec2(w, 26.0),
                egui::Layout::right_to_left(egui::Align::Center),
                |ui| {
                    ui.add_space(8.0);
                    if ui.small_button("全体").on_hover_text("全体をフィット").clicked() {
                        let w = ui.ctx().screen_rect().width();
                        self.zoom_fit(w);
                    }
                    let mut z = self.pps.ln();
                    let resp = ui.add(
                        egui::Slider::new(&mut z, 1.0f32.ln()..=400.0f32.ln()).show_value(false),
                    );
                    if resp.changed() {
                        let anchor = (self.t as f32) * self.pps - self.scroll_x;
                        self.pps = z.exp().clamp(1.0, 400.0);
                        self.scroll_x = ((self.t as f32) * self.pps - anchor).max(0.0);
                    }
                    ui.label(egui::RichText::new("🔍").size(13.0));
                },
            );
        });
    }

    /// One asset card in the library grid: thumbnail, name, status chip, selection state.
    fn asset_card(&mut self, ui: &mut egui::Ui, a: &serde_json::Value) {
        let id = a.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let name = a
            .get("filename")
            .or_else(|| a.get("name"))
            .and_then(|v| v.as_str())
            .unwrap_or("(無名)")
            .to_string();
        let status = a.get("status").and_then(|v| v.as_str()).unwrap_or("");
        let selected = self.lib.selected_assets.iter().any(|s| *s == id);
        let (rect, resp) = ui.allocate_exact_size(egui::vec2(150.0, 116.0), egui::Sense::click());
        let hov = resp.hovered();
        let p = ui.painter_at(rect);
        p.rect_filled(rect, 8.0, if hov { egui::Color32::from_rgb(36, 36, 41) } else { egui::Color32::from_rgb(28, 28, 32) });
        let img_r = egui::Rect::from_min_max(
            rect.min + egui::vec2(4.0, 4.0),
            egui::pos2(rect.right() - 4.0, rect.bottom() - 24.0),
        );
        if let Some(t) = self.lib.thumbs.get(&id) {
            p.image(
                t.id(),
                img_r,
                egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0)),
                egui::Color32::WHITE,
            );
        } else {
            p.rect_filled(img_r, 6.0, egui::Color32::from_rgb(18, 18, 21));
            p.text(img_r.center(), egui::Align2::CENTER_CENTER, "🎞", egui::FontId::proportional(22.0), egui::Color32::from_gray(70));
        }
        // status chip (only when NOT ready — ready needs no noise)
        let chip = match status {
            "processing" | "registered" => Some(("処理中…", egui::Color32::from_rgb(200, 150, 40))),
            "failed" => Some(("失敗", egui::Color32::from_rgb(200, 70, 70))),
            _ => None,
        };
        if let Some((label, col)) = chip {
            let cr = egui::Rect::from_min_size(img_r.min + egui::vec2(5.0, 5.0), egui::vec2(52.0, 17.0));
            p.rect_filled(cr, 8.0, col.gamma_multiply(0.9));
            p.text(cr.center(), egui::Align2::CENTER_CENTER, label, egui::FontId::proportional(10.0), egui::Color32::WHITE);
        }
        let short: String = name.chars().take(16).collect();
        p.text(
            egui::pos2(rect.left() + 7.0, rect.bottom() - 12.0),
            egui::Align2::LEFT_CENTER,
            short,
            egui::FontId::proportional(10.0),
            egui::Color32::from_gray(200),
        );
        if selected {
            p.rect_stroke(rect, 8.0, egui::Stroke::new(2.5, UI_ACCENT));
            let cc = egui::pos2(rect.right() - 13.0, rect.top() + 13.0);
            p.circle_filled(cc, 9.0, UI_ACCENT);
            p.text(cc, egui::Align2::CENTER_CENTER, "✔", egui::FontId::proportional(11.0), egui::Color32::WHITE);
        } else {
            p.rect_stroke(rect, 8.0, egui::Stroke::new(1.0, if hov { egui::Color32::from_gray(120) } else { egui::Color32::from_gray(48) }));
        }
        // hover 時のみ左上に削除 ✕（右上は選択✔が使うので左上）
        let del_r = egui::Rect::from_center_size(
            egui::pos2(rect.left() + 13.0, rect.top() + 13.0),
            egui::vec2(18.0, 18.0),
        );
        let on_del = hov
            && resp
                .hover_pos()
                .map_or(false, |p| del_r.contains(p));
        if hov {
            p.circle_filled(del_r.center(), 9.0, if on_del {
                egui::Color32::from_rgb(190, 60, 60)
            } else {
                egui::Color32::from_black_alpha(170)
            });
            p.text(del_r.center(), egui::Align2::CENTER_CENTER, "✕", egui::FontId::proportional(11.0), egui::Color32::from_gray(230));
            ui.ctx().set_cursor_icon(egui::CursorIcon::PointingHand);
        }
        if resp.clicked() && !id.is_empty() {
            let del_clicked = resp
                .interact_pointer_pos()
                .map_or(false, |p| del_r.contains(p));
            if del_clicked {
                self.lib.confirm_delete = Some((id.clone(), name.clone(), false));
            } else if selected {
                self.lib.selected_assets.retain(|s| *s != id);
            } else {
                self.lib.selected_assets.push(id.clone());
            }
        }
    }

    /// Inspector: properties panel. Multiple selected media clips can be edited together.
    fn inspector_ui(&mut self, ctx: &egui::Context) {
        let selected: Vec<(model::Clip, String)> = self
            .doc
            .seq
            .tracks
            .iter()
            .flat_map(|tr| tr.clips.iter().map(move |c| (c, tr.kind.clone())))
            .filter(|(c, _)| self.selected.contains(&c.id))
            .map(|(c, k)| (c.clone(), k))
            .collect();
        // the panel is ALWAYS rendered at its fixed width — appearing/disappearing with
        // the selection resized the central area and made the preview jump every time a
        // clip was selected or created ("パネルが出るたびプレビューの位置が変わる")
        // 幅は開閉どちらの状態でも完全固定。選択のたびに中央のプレビュー位置が
        // 微妙に動く（ガクつく）のを防ぐ — パネルは常に同じ幅で存在し続ける。
        const INSPECTOR_W: f32 = 320.0;
        let placeholder = |ctx: &egui::Context| {
            egui::SidePanel::right("inspector")
                .resizable(false)
                .exact_width(INSPECTOR_W)
                .show(ctx, |ui| {
                    ui.add_space(12.0);
                    ui.label(
                        egui::RichText::new("クリップを選択すると\nここに編集パネルが出ます")
                            .small()
                            .weak(),
                    );
                });
        };
        if selected.is_empty() {
            placeholder(ctx);
            return;
        }
        let multi = selected.len() > 1;
        let same_media = selected
            .iter()
            .all(|(c, k)| k != "audio" && c.asset_id.is_some() && c.text.is_none() && c.region.is_none());
        let same_caption = selected
            .iter()
            .all(|(c, k)| k == "caption" || (c.text.is_some() && c.asset_id.is_none() && c.region.is_none()));
        let same_region_effect = selected.iter().all(|(c, _)| {
            c.region.is_some()
                && c.asset_id.is_none()
                && c.style.as_ref().and_then(|v| v.as_str()) != Some("note")
        });
        if multi && !same_media && !same_caption && !same_region_effect {
            placeholder(ctx);
            return;
        }
        let (clip, kind) = selected[0].clone();
        let id = clip.id.clone();
        let edit_ids: Vec<String> = selected.iter().map(|(c, _)| c.id.clone()).collect();
        egui::SidePanel::right("inspector").resizable(false).exact_width(INSPECTOR_W).show(ctx, |ui| {
            egui::ScrollArea::vertical().show(ui, |ui| {
                ui.add_space(8.0);
                let title = if multi {
                    format!("{} clips", selected.len())
                } else if clip.text.is_some() && clip.asset_id.is_none() {
                    "テロップ".to_string()
                } else {
                    clip.asset_id
                        .as_ref()
                        .and_then(|a| self.doc.asset_names.get(a))
                        .cloned()
                        .unwrap_or_else(|| "クリップ".into())
                };
                ui.heading(egui::RichText::new(title).size(15.0));
                ui.label(
                    egui::RichText::new(format!(
                        "{}  {:02}:{:02} - {:02}:{:02}（{:.1}秒）",
                        kind,
                        clip.timeline_start as i64 / 60,
                        clip.timeline_start as i64 % 60,
                        clip.timeline_end as i64 / 60,
                        clip.timeline_end as i64 % 60,
                        clip.dur()
                    ))
                    .weak()
                    .small(),
                );
                ui.separator();
                // ---- standalone audio clip (BGM / SE): volume ----
                if !multi && kind == "audio" && clip.asset_id.is_some() {
                    ui.label(egui::RichText::new("音量").strong());
                    let mut vol = (clip.volume * 100.0) as f32;
                    let r = ui.add(egui::Slider::new(&mut vol, 0.0..=200.0).suffix("%").fixed_decimals(0));
                    if r.drag_started() {
                        self.pending_undo = Some(self.doc.raw.clone());
                    }
                    if r.changed() {
                        let ids = edits::expand_links(&self.doc.raw, &edit_ids);
                        let v = (vol / 100.0) as f64;
                        self.apply_edit(false, move |raw| edits::set_volume(raw, &ids, v));
                    }
                    if r.drag_stopped() {
                        ui.memory_mut(|mem| mem.surrender_focus(r.id));
                    }
                    ui.add_space(6.0);
                }
                // ---- region effect (blur/mosaic) ----
                if !multi && clip.region.is_some() && clip.asset_id.is_none()
                    && clip.style.as_ref().and_then(|v| v.as_str()) == Some("note")
                {
                    // 指示クリップ: クリップの頭〜尻がAI作業の時間範囲、矩形が場所
                    ui.label(egui::RichText::new("📝 指示クリップ").strong());
                    ui.label(
                        egui::RichText::new(
                            "「ダンに指示」送信時にこの範囲（時間=クリップの長さ・場所=矩形）が指示に添付され、クリップは消費されます。長さ・位置は普通のクリップとして調整できます",
                        )
                        .small()
                        .weak(),
                    );
                    ui.add_space(6.0);
                    if ui.button("🗑 この指示クリップを削除").clicked() {
                        let cid = vec![id.clone()];
                        self.apply_edit(true, move |raw| edits::delete_clips(raw, &cid));
                        self.selected.clear();
                        self.push_req(false);
                    }
                    return;
                }
                // ---- multi-select region effects: apply one set of controls to all ----
                if multi && same_region_effect {
                    ui.label(egui::RichText::new("範囲エフェクトを一括編集").strong());
                    ui.label(egui::RichText::new("変更は選択中の全クリップに適用されます。").small().weak());
                    let cur = clip.style.as_ref().and_then(|v| v.as_str()).unwrap_or("mosaic").to_string();
                    ui.horizontal(|ui| {
                        for (label, val) in [("モザイク", "mosaic"), ("ぼかし", "gaussian"), ("単色", "solid"), ("マーカー", "marker"), ("スポットライト", "spotlight"), ("枠", "frame"), ("ズーム", "zoom")] {
                            let all_same = selected.iter().all(|(c, _)| c.style.as_ref().and_then(|v| v.as_str()) == Some(val));
                            if ui.selectable_label(all_same, label).clicked() {
                                let ids = edit_ids.clone();
                                self.apply_edit(true, move |raw| {
                                    for cid in &ids { edits::set_style(raw, cid, val); }
                                });
                                self.push_req(false);
                            }
                        }
                    });
                    let is_solid = cur == "solid";
                    if !is_solid {
                        let mut strength = clip.effect_strength.unwrap_or(if cur.contains("mosaic") { 14.0 } else { 16.0 }) as f32;
                        ui.horizontal(|ui| {
                            ui.label(if cur.contains("mosaic") { "粗さ" } else { "ぼかし強度" });
                            let resp = ui.add(egui::Slider::new(&mut strength, 2.0..=64.0).suffix(" px"));
                            if resp.drag_started() { self.pending_undo = Some(self.doc.raw.clone()); }
                            if resp.changed() {
                                let ids = edit_ids.clone(); let value = strength as f64;
                                self.apply_edit(false, move |raw| {
                                    for cid in &ids { edits::set_effect_options(raw, cid, Some(value), None, None); }
                                });
                            }
                        });
                    } else {
                        let mut colour = hex_color32(clip.effect_color.as_deref().unwrap_or("#000000"), egui::Color32::BLACK);
                        let mut opacity = clip.effect_opacity.unwrap_or(1.0) as f32;
                        ui.horizontal(|ui| {
                            ui.label("色");
                            if ui.color_edit_button_srgba(&mut colour).changed() {
                                let ids = edit_ids.clone(); let hex = color32_hex(colour);
                                self.apply_edit(true, move |raw| {
                                    for cid in &ids { edits::set_effect_options(raw, cid, None, Some(hex.clone()), None); }
                                });
                            }
                            ui.label(egui::RichText::new(color32_hex(colour)).weak());
                        });
                        ui.horizontal(|ui| {
                            ui.label("不透明度");
                            let resp = ui.add(egui::Slider::new(&mut opacity, 0.0..=1.0).show_value(false));
                            ui.label(format!("{:0}%", opacity * 100.0));
                            if resp.drag_started() { self.pending_undo = Some(self.doc.raw.clone()); }
                            if resp.changed() {
                                let ids = edit_ids.clone(); let value = opacity as f64;
                                self.apply_edit(false, move |raw| {
                                    for cid in &ids { edits::set_effect_options(raw, cid, None, None, Some(value)); }
                                });
                            }
                        });
                    }
                    return;
                }
                if !multi && clip.region.is_some() && clip.asset_id.is_none() {
                    ui.label(egui::RichText::new("種類").strong());
                    let cur = clip.style.as_ref().and_then(|v| v.as_str()).unwrap_or("mosaic").to_string();
                    ui.horizontal(|ui| {
                        for (label, val) in [
                            ("モザイク", "mosaic"),
                            ("ぼかし", "gaussian"),
                            ("単色", "solid"),
                        ] {
                            if ui.selectable_label(cur.contains(val), label).clicked() {
                                let cid = id.clone();
                                self.apply_edit(true, move |raw| edits::set_style(raw, &cid, val));
                                self.push_req(false);
                            }
                        }
                    });
                    // 注目演出（隠すのではなく見せるための範囲エフェクト）
                    ui.horizontal(|ui| {
                        for (label, val) in [
                            ("マーカー", "marker"),
                            ("スポットライト", "spotlight"),
                            ("枠", "frame"),
                            ("ズーム", "zoom"),
                        ] {
                            if ui.selectable_label(cur == val, label).clicked() {
                                let cid = id.clone();
                                self.apply_edit(true, move |raw| edits::set_style(raw, &cid, val));
                                self.push_req(false);
                            }
                        }
                    });
                    let is_solid = cur == "solid";
                    let is_focus = cur == "marker" || cur == "spotlight";
                    let is_zoom = cur == "zoom";
                    let is_frame = cur == "frame";
                    let mut strength = clip.effect_strength.unwrap_or(if cur.contains("mosaic") { 14.0 } else { 16.0 }) as f32;
                    if is_zoom {
                        let mut z = clip.effect_strength.unwrap_or(1.6) as f32;
                        ui.horizontal(|ui| {
                            ui.label("倍率");
                            let resp = ui.add(egui::Slider::new(&mut z, 1.1..=3.0).suffix("x").fixed_decimals(2));
                            if resp.drag_started() { self.pending_undo = Some(self.doc.raw.clone()); }
                            if resp.changed() {
                                let cid = id.clone();
                                self.apply_edit(false, move |raw| edits::set_effect_options(raw, &cid, Some(z as f64), None, None));
                            }
                        });
                    } else if is_focus {
                        let mut opacity = clip.effect_opacity.unwrap_or(1.0) as f32;
                        ui.horizontal(|ui| {
                            ui.label("強さ");
                            let resp = ui.add(egui::Slider::new(&mut opacity, 0.0..=1.0).show_value(false));
                            ui.label(format!("{:0}%", opacity * 100.0));
                            if resp.drag_started() { self.pending_undo = Some(self.doc.raw.clone()); }
                            if resp.changed() {
                                let cid = id.clone();
                                self.apply_edit(false, move |raw| edits::set_effect_options(raw, &cid, None, None, Some(opacity as f64)));
                            }
                        });
                    } else if is_frame {
                        let mut colour = hex_color32(
                            clip.effect_color.as_deref().unwrap_or("#ffe14d"),
                            egui::Color32::from_rgb(255, 225, 77),
                        );
                        let mut opacity = clip.effect_opacity.unwrap_or(1.0) as f32;
                        let mut th = clip.effect_strength.unwrap_or(4.0) as f32;
                        ui.horizontal(|ui| {
                            ui.label("色");
                            if ui.color_edit_button_srgba(&mut colour).changed() {
                                let cid = id.clone();
                                let hex = color32_hex(colour);
                                self.apply_edit(true, move |raw| {
                                    edits::set_effect_options(raw, &cid, None, Some(hex), None)
                                });
                            }
                            ui.label("太さ");
                            let r = ui.add(egui::Slider::new(&mut th, 1.0..=24.0).suffix(" px"));
                            if r.drag_started() {
                                self.pending_undo = Some(self.doc.raw.clone());
                            }
                            if r.changed() {
                                let cid = id.clone();
                                self.apply_edit(false, move |raw| {
                                    edits::set_effect_options(raw, &cid, Some(th as f64), None, None)
                                });
                            }
                        });
                        ui.horizontal(|ui| {
                            ui.label("不透明度");
                            let resp = ui.add(egui::Slider::new(&mut opacity, 0.0..=1.0).show_value(false));
                            ui.label(format!("{:0}%", opacity * 100.0));
                            if resp.drag_started() {
                                self.pending_undo = Some(self.doc.raw.clone());
                            }
                            if resp.changed() {
                                let cid = id.clone();
                                self.apply_edit(false, move |raw| {
                                    edits::set_effect_options(raw, &cid, None, None, Some(opacity as f64))
                                });
                            }
                        });
                    } else if !is_solid {
                        let label = if cur.contains("mosaic") { "粗さ" } else { "ぼかし強度" };
                        ui.horizontal(|ui| {
                            ui.label(label);
                            let resp = ui.add(egui::Slider::new(&mut strength, 2.0..=64.0).suffix(" px"));
                            if resp.drag_started() { self.pending_undo = Some(self.doc.raw.clone()); }
                            if resp.changed() {
                                let cid = id.clone();
                                self.apply_edit(false, move |raw| edits::set_effect_options(raw, &cid, Some(strength as f64), None, None));
                            }
                        });
                    } else {
                        let mut colour = hex_color32(clip.effect_color.as_deref().unwrap_or("#000000"), egui::Color32::BLACK);
                        let mut opacity = clip.effect_opacity.unwrap_or(1.0) as f32;
                        ui.horizontal(|ui| {
                            ui.label("色");
                            if ui.color_edit_button_srgba(&mut colour).changed() {
                                let cid = id.clone();
                                let hex = color32_hex(colour);
                                self.apply_edit(true, move |raw| edits::set_effect_options(raw, &cid, None, Some(hex), None));
                            }
                            ui.label(egui::RichText::new(color32_hex(colour)).weak());
                        });
                        ui.horizontal(|ui| {
                            ui.label("不透明度");
                            let resp = ui.add(egui::Slider::new(&mut opacity, 0.0..=1.0).show_value(false));
                            ui.label(format!("{:0}%", opacity * 100.0));
                            if resp.drag_started() { self.pending_undo = Some(self.doc.raw.clone()); }
                            if resp.changed() {
                                let cid = id.clone();
                                self.apply_edit(false, move |raw| edits::set_effect_options(raw, &cid, None, None, Some(opacity as f64)));
                            }
                        });
                    }
                    // 角度: 単色/枠/ぼかしの矩形を回す（細い単色＋角度＝斜めの疑似ライン）
                    if is_solid || is_frame || cur == "gaussian" {
                        let mut rot = clip.effect_rot.unwrap_or(0.0) as f32;
                        ui.horizontal(|ui| {
                            ui.label("角度");
                            let r = ui.add(egui::Slider::new(&mut rot, -90.0..=90.0).suffix("°").fixed_decimals(1));
                            if r.drag_started() { self.pending_undo = Some(self.doc.raw.clone()); }
                            if r.changed() {
                                let cid = id.clone();
                                self.apply_edit(false, move |raw| edits::set_effect_rot(raw, &cid, Some(rot as f64)));
                            }
                            if ui.small_button("0°").clicked() {
                                let cid = id.clone();
                                self.apply_edit(true, move |raw| edits::set_effect_rot(raw, &cid, None));
                            }
                        });
                    }
                    ui.label(egui::RichText::new(if is_frame {
                        "枠=範囲を四角い線で囲むだけ（周囲は暗くしない）。同一シーンで複数箇所を目立たせても画面が沈みません。"
                    } else if is_focus || is_zoom {
                        "マーカー/スポットライト=範囲を目立たせる、ズーム=範囲へパンチイン。移動する対象は下の手動追従（キーフレーム）で追えます。"
                    } else {
                        "単色は静的範囲にもAI追従にも使えます。細くして角度をつければ斜めの線・帯としても使えます。ぼかし・モザイクは強度を調整できます。"
                    }).small().weak());
                    ui.add_space(6.0);
                    // ---- SAM tracked blur: the rectangle picks the OBJECT; the baked
                    // mask then follows it (pixel silhouette), replacing the static rect
                    // (隠す系スタイル専用 — 注目演出はマスク追従の対象外)
                    let has_track = clip.blur_track.is_some();
                    if !(is_focus || is_zoom || is_frame) {
                    ui.label(egui::RichText::new("AI追従（SAM）").strong());
                    ui.horizontal(|ui| {
                        let blabel = if has_track { "再ベイク" } else { "囲んだ物体を追従ぼかし" };
                        if ui.button(blabel).clicked() {
                            let cid = id.clone();
                            self.apply_blur_bake(&cid);
                        }
                        if has_track && ui.button("追従解除").clicked() {
                            let cid = id.clone();
                            self.apply_edit(true, move |raw| edits::set_blur_track(raw, &cid, None));
                            self.blur_states.remove(&id);
                            self.push_req(false);
                        }
                    });
                    }
                    if has_track {
                        let in_corr = self.corr_mode.as_deref() == Some(id.as_str());
                        ui.horizontal(|ui| {
                            if ui
                                .selectable_label(in_corr, "追従修正")
                                .on_hover_text(
                                    "外れているフレームで対象を左クリック（＋=これを追え）/\n右クリック（−=これは違う）→ 修正ベイク。\n直したい区間はSで分割して切り出してから",
                                )
                                .clicked()
                            {
                                if in_corr {
                                    self.corr_mode = None;
                                    self.corr_points.clear();
                                    self.corr_anchor_src = None;
                                } else {
                                    self.corr_mode = Some(id.clone());
                                    self.corr_points.clear();
                                    self.corr_anchor_src = None;
                                    self.pause_at_displayed();
                                }
                            }
                            if in_corr {
                                if ui
                                    .add_enabled(!self.corr_points.is_empty(), egui::Button::new("修正ベイク"))
                                    .clicked()
                                {
                                    let cid = id.clone();
                                    self.apply_blur_correction(&cid);
                                }
                                if ui.button("点クリア").clicked() {
                                    self.corr_points.clear();
                                    self.corr_anchor_src = None;
                                }
                            }
                        });
                        if in_corr {
                            ui.label(
                                egui::RichText::new(format!(
                                    "点 {}個（左=＋含める / 右=−除外。別フレームでクリックすると打ち直し）",
                                    self.corr_points.len()
                                ))
                                .small()
                                .weak(),
                            );
                        }
                    }
                    if !has_track {
                        // ---- 手動: 位置キーフレーム（AI追従なしの矩形をダビンチ流に手で追わせる）----
                        ui.add_space(6.0);
                        ui.label(egui::RichText::new("手動追従（キーフレーム）").strong());
                        let kts = clip.region_key_times();
                        let nkeys = kts.len();
                        // ONE clock: the displayed frame's grid slot, snapped to the
                        // playhead's slot when it sits on an existing key (keyed_grid_t)
                        let t_now = self.keyed_grid_t(clip.timeline_start, &kts);
                        let rel = t_now - clip.timeline_start;
                        let on_key = kts.iter().any(|kt| (kt - rel).abs() <= edits::KEY_REPLACE_EPS);
                        let kf_on = self.kf_mode.as_deref() == Some(id.as_str());
                        ui.horizontal(|ui| {
                            // キーを作れるのはこのトグルON中のドラッグだけ。OFFのドラッグは
                            // キー有りクリップなら「軌跡ごと平行移動/一括リサイズ」（キーは
                            // 増えない）。トグルはクリップ紐付き＝選択が変われば自動OFF
                            if ui
                                .selectable_label(kf_on, "◆キー打ちモード")
                                .on_hover_text(
                                    "ON: ドラッグ/リサイズが表示中フレームにキーを打つ（打った瞬間に通知）。\nOFF: キー有りクリップのドラッグは動き全体をそのまま平行移動（キーは増えない）。\n枠が赤=キー上（ドラッグで打ち直し）、オレンジ=補間中（ON中のドラッグで新規キー）",
                                )
                                .clicked()
                            {
                                self.kf_mode = if kf_on { None } else { Some(id.clone()) };
                                if self.kf_mode.is_some() {
                                    self.pause_at_displayed();
                                }
                            }
                            if nkeys > 0 && !kf_on {
                                ui.label(
                                    egui::RichText::new("OFF: ドラッグ=全体移動")
                                        .small()
                                        .weak(),
                                );
                            }
                            if nkeys > 0 && ui.button("キー全消し").clicked() {
                                let cid = id.clone();
                                self.apply_edit(true, move |raw| edits::clear_region_keys(raw, &cid));
                                self.push_req(false);
                            }
                        });
                        if kf_on || nkeys > 0 {
                            ui.horizontal(|ui| {
                                // ← 前のキーへ / このフレームにキー / このキーを削除 / 次のキーへ →
                                let prev = kts.iter().rev().find(|kt| **kt < rel - 1e-3).copied();
                                let next = kts.iter().find(|kt| **kt > rel + 1e-3).copied();
                                if ui
                                    .add_enabled(prev.is_some(), egui::Button::new("◀"))
                                    .on_hover_text("前のキーへ")
                                    .clicked()
                                {
                                    self.playing = false;
                                    self.t = clip.timeline_start + prev.unwrap();
                                    self.push_req(false);
                                }
                                if on_key {
                                    if ui
                                        .button("◆削除")
                                        .on_hover_text("再生ヘッド位置のキーだけ削除")
                                        .clicked()
                                    {
                                        let cid = id.clone();
                                        self.apply_edit(true, move |raw| {
                                            edits::remove_region_key(raw, &cid, rel)
                                        });
                                        self.push_req(false);
                                    }
                                } else if ui
                                    .add_enabled(
                                        rel >= 0.0 && rel <= clip.dur(),
                                        egui::Button::new("◆＋"),
                                    )
                                    .on_hover_text("このフレームの今の位置にキーを打つ（動かさず固定したい時に）")
                                    .on_disabled_hover_text("再生ヘッドをこのぼかしクリップの範囲内に置いてください")
                                    .clicked()
                                {
                                    if let Some((kx, ky, kw, kh)) = clip.region_at(t_now) {
                                        let cid = id.clone();
                                        self.apply_edit(true, move |raw| {
                                            edits::set_region_key(raw, &cid, rel, kx, ky, kw, kh)
                                        });
                                        self.toast(&format!("◆ キーを打ちました（{}個）", nkeys + 1));
                                        self.push_req(false);
                                    }
                                }
                                if ui
                                    .add_enabled(next.is_some(), egui::Button::new("▶"))
                                    .on_hover_text("次のキーへ")
                                    .clicked()
                                {
                                    self.playing = false;
                                    self.t = clip.timeline_start + next.unwrap();
                                    self.push_req(false);
                                }
                                let status = if on_key {
                                    format!("キー{nkeys}個・キー上")
                                } else {
                                    format!("キー{nkeys}個")
                                };
                                ui.label(
                                    egui::RichText::new(status)
                                        .small()
                                        .color(if on_key {
                                            egui::Color32::from_rgb(240, 100, 100)
                                        } else {
                                            egui::Color32::GRAY
                                        }),
                                );
                            });
                        }
                    }
                    match self.blur_states.get(&id).copied() {
                        Some(PopState::Baking(pct)) => {
                            ui.label(egui::RichText::new(format!("追従ベイク中 {pct}%")).small());
                        }
                        Some(PopState::Failed) => {
                            ui.label(egui::RichText::new("ベイク失敗 — もう一度お試しください").small().color(egui::Color32::from_rgb(230, 90, 90)));
                        }
                        Some(PopState::Ready) => {
                            ui.label(egui::RichText::new("追従中（マスク適用済み）").small().color(egui::Color32::from_rgb(90, 200, 140)));
                        }
                        None => {}
                    }
                    ui.add_space(6.0);
                    ui.label(egui::RichText::new("時間（秒）").strong());
                    let mut span = [clip.timeline_start, clip.timeline_end];
                    let mut sp_changed = false;
                    ui.horizontal(|ui| {
                        for i in 0..2 {
                            let r = ui.add(egui::DragValue::new(&mut span[i]).speed(0.05).range(0.0..=self.dur));
                            if r.drag_started() || r.gained_focus() {
                                self.pending_undo = Some(self.doc.raw.clone());
                            }
                            sp_changed |= r.changed();
                        }
                    });
                    if sp_changed {
                        let cid = id.clone();
                        let (a, b2) = (span[0], span[1]);
                        self.apply_edit(false, move |raw| edits::set_span(raw, &cid, a, b2));
                        self.push_req(false);
                    }
                    ui.add_space(6.0);
                    if ui.button("🗑 このぼかしを削除").clicked() {
                        let cid = vec![id.clone()];
                        self.apply_edit(true, move |raw| edits::delete_clips(raw, &cid));
                        self.selected.clear();
                        self.push_req(false);
                    }
                    return;
                }
                // ---- caption: edit the text right here ----
                if clip.text.is_some() && clip.asset_id.is_none() {
                    if !multi {
                    if self.insp_for != id {
                        self.insp_for = id.clone();
                        self.insp_text = self.caption_display_text(&clip);
                    }
                    ui.label(egui::RichText::new("本文").strong());
                    let r = ui.add(
                        egui::TextEdit::multiline(&mut self.insp_text)
                            .id(egui::Id::new("cap_text_edit"))
                            .desired_rows(4)
                            .desired_width(f32::INFINITY),
                    );
                    self.text_focus_ids.push(r.id);
                    if r.gained_focus() {
                        self.pending_undo = Some(self.doc.raw.clone());
                    }
                    if r.changed() {
                        let txt = self.insp_text.clone();
                        self.stage_caption_text(&id, txt);
                        // Keep IME composition local. The document/cache work starts
                        // only after a short idle period or a focus transition.
                        ui.ctx().request_repaint_after(std::time::Duration::from_millis(16));
                    }
                    if r.lost_focus() {
                        self.commit_caption_drafts(Some(&id));
                    }
                    } else {
                        ui.label(egui::RichText::new(format!("{} captions", selected.len())).weak().small());
                    }
                    ui.add_space(8.0);
                    ui.label(egui::RichText::new("デザイン").strong());
                    let style = clip.style.clone().unwrap_or_else(|| serde_json::json!({}));
                    let font_size = style.get("fontSize").and_then(|v| v.as_f64()).unwrap_or(1.04);
                    let max_width = style.get("maxWidth").and_then(|v| v.as_f64()).unwrap_or(0.88);
                    let y_pos = style.get("y").and_then(|v| v.as_f64()).unwrap_or(0.14);
                    let outline = style.get("outlineWidth").and_then(|v| v.as_f64()).unwrap_or(1.25);
                    if ui.button("白文字・黒フチ・ゴシック").clicked() {
                        let ids = edit_ids.clone();
                        self.remember_caption_fallbacks(&ids);
                        let patch = serde_json::json!({
                            "font": "noto-sans", "color": "#ffffff", "outlineColor": "#000000",
                            "outlineWidth": 1.65, "fontSize": font_size, "y": y_pos,
                            "bg": null, "gradient": null, "highlightColor": null, "highlightScale": null,
                            "shadow": {"color":"rgba(0,0,0,0.85)","blur":10,"dy":3},
                            "animation": "none"
                        });
                        self.apply_edit(true, move |raw| edits::patch_caption_style(raw, &ids, patch));
                        self.push_req(false);
                    }
                    let mut fs = font_size;
                    if ui.add(egui::Slider::new(&mut fs, 0.0..=2.2).text("大きさ")).changed() {
                        let ids = edit_ids.clone();
                        self.remember_caption_fallbacks(&ids);
                        let patch = serde_json::json!({"fontSize": (fs * 100.0).round() / 100.0});
                        self.apply_edit(false, move |raw| edits::patch_caption_style(raw, &ids, patch));
                        self.push_req(false);
                    }
                    let mut mw = max_width;
                    if ui
                        .add(egui::Slider::new(&mut mw, 0.05..=1.5).text("横幅"))
                        .on_hover_text("画面幅に対するテロップ枠の最大幅。100%を超える指定も可能です")
                        .changed()
                    {
                        let ids = edit_ids.clone();
                        self.remember_caption_fallbacks(&ids);
                        let patch = serde_json::json!({"maxWidth": (mw * 100.0).round() / 100.0});
                        self.apply_edit(false, move |raw| edits::patch_caption_style(raw, &ids, patch));
                        self.push_req(false);
                    }
                    let current_align = style.get("textAlign").and_then(|v| v.as_str()).unwrap_or("center");
                    let mut text_align = current_align.to_string();
                    ui.horizontal(|ui| {
                        ui.label("文字揃え");
                        ui.selectable_value(&mut text_align, "left".to_string(), "左");
                        ui.selectable_value(&mut text_align, "center".to_string(), "中央");
                        ui.selectable_value(&mut text_align, "right".to_string(), "右");
                    });
                    if text_align != current_align {
                        let ids = edit_ids.clone();
                        self.remember_caption_fallbacks(&ids);
                        let patch = serde_json::json!({"textAlign": text_align});
                        self.apply_edit(false, move |raw| edits::patch_caption_style(raw, &ids, patch));
                        self.push_req(false);
                    }
                    let mut yv = y_pos;
                    if ui.add(egui::Slider::new(&mut yv, 0.0..=0.92).text("上下")).changed() {
                        let ids = edit_ids.clone();
                        self.remember_caption_fallbacks(&ids);
                        let patch = serde_json::json!({"y": (yv * 100.0).round() / 100.0});
                        self.apply_edit(false, move |raw| edits::patch_caption_style(raw, &ids, patch));
                        self.push_req(false);
                    }
                    let x_pos = style.get("x").and_then(|v| v.as_f64()).unwrap_or(0.0);
                    let mut xv = x_pos;
                    // Fraction of frame width; ±0.5 puts the caption's center on a frame
                    // edge, so partial off-screen placement is reachable (edges crop, like
                    // the export's overflow:hidden — nothing snaps back inside).
                    if ui.add(egui::Slider::new(&mut xv, -0.5..=0.5).text("左右")).changed() {
                        let ids = edit_ids.clone();
                        self.remember_caption_fallbacks(&ids);
                        let patch = serde_json::json!({"x": (xv * 100.0).round() / 100.0});
                        self.apply_edit(false, move |raw| edits::patch_caption_style(raw, &ids, patch));
                        self.push_req(false);
                    }
                    let mut ow = outline;
                    if ui.add(egui::Slider::new(&mut ow, 0.0..=3.0).text("フチ")).changed() {
                        let ids = edit_ids.clone();
                        self.remember_caption_fallbacks(&ids);
                        let patch = serde_json::json!({"outlineWidth": (ow * 100.0).round() / 100.0});
                        self.apply_edit(false, move |raw| edits::patch_caption_style(raw, &ids, patch));
                        self.push_req(false);
                    }
                    // ---- 色（文字 / フチ）----
                    ui.horizontal(|ui| {
                        ui.label(egui::RichText::new("文字色").weak().small());
                        let mut tc = hex_color32(
                            style.get("color").and_then(|v| v.as_str()).unwrap_or("#ffffff"),
                            egui::Color32::WHITE,
                        );
                        if ui.color_edit_button_srgba(&mut tc).changed() {
                            // 本文欄で文字を選択していればその範囲だけ、無ければ全体。
                            // （egui の TextEditState はフォーカスが外れても選択範囲を
                            // 保持するので、ピッカー操作後でも範囲が取れる）
                            let sel = if multi {
                                None
                            } else {
                                egui::TextEdit::load_state(ui.ctx(), egui::Id::new("cap_text_edit"))
                                    .and_then(|st| st.cursor.char_range())
                                    .map(|cr| {
                                        (
                                            cr.primary.index.min(cr.secondary.index),
                                            cr.primary.index.max(cr.secondary.index),
                                        )
                                    })
                                    .filter(|(a, b)| b > a)
                            };
                            let ids = edit_ids.clone();
                            self.remember_caption_fallbacks(&ids);
                            if let (Some((a, b)), Some(cid)) = (sel, edit_ids.first().cloned()) {
                                let col = color32_hex(tc);
                                self.apply_edit(false, move |raw| {
                                    edits::set_caption_color_span(raw, &cid, a, b, Some(&col))
                                });
                                // ピッカー操作でフォーカスが移っても選択が見えたままに
                                ui.ctx().memory_mut(|m| {
                                    m.request_focus(egui::Id::new("cap_text_edit"))
                                });
                            } else {
                                // a plain color pick must WIN: a leftover gradient overrides
                                // `color` in the renderer, so it is cleared explicitly.
                                // 選択なしの全体変更は範囲色(colorSpans)もリセット＝見たまま
                                let patch = serde_json::json!({
                                    "color": color32_hex(tc),
                                    "gradient": null,
                                    "colorSpans": null,
                                });
                                self.apply_edit(false, move |raw| {
                                    edits::patch_caption_style(raw, &ids, patch)
                                });
                            }
                            self.push_req(false);
                        }
                        if ui
                            .small_button("スポイト")
                            .on_hover_text("プレビューでクリックした場所の色を文字色にする")
                            .clicked()
                        {
                            self.eyedrop = Some((0, edit_ids.clone()));
                        }
                        ui.add_space(8.0);
                        ui.label(egui::RichText::new("フチ色").weak().small());
                        let mut oc = hex_color32(
                            style.get("outlineColor").and_then(|v| v.as_str()).unwrap_or("#000000"),
                            egui::Color32::BLACK,
                        );
                        if ui.color_edit_button_srgba(&mut oc).changed() {
                            let ids = edit_ids.clone();
                            self.remember_caption_fallbacks(&ids);
                            let patch = serde_json::json!({"outlineColor": color32_hex(oc)});
                            self.apply_edit(false, move |raw| edits::patch_caption_style(raw, &ids, patch));
                            self.push_req(false);
                        }
                        if ui
                            .small_button("スポイト")
                            .on_hover_text("プレビューでクリックした場所の色をフチ色にする")
                            .clicked()
                        {
                            self.eyedrop = Some((1, edit_ids.clone()));
                        }
                    });
                    // ---- 四角枠（テロップの背景ボックス）----
                    let bg = style.get("bg").filter(|v| v.is_object()).cloned();
                    let mut boxed = bg.is_some();
                    if ui.checkbox(&mut boxed, "四角枠（背景ボックス）").changed() {
                        let ids = edit_ids.clone();
                        self.remember_caption_fallbacks(&ids);
                        let patch = if boxed {
                            serde_json::json!({"bg": {"color": "#000000", "opacity": 0.62,
                                                       "radius": 0.2, "padX": 0.5, "padY": 0.18}})
                        } else {
                            serde_json::json!({"bg": null})
                        };
                        self.apply_edit(true, move |raw| edits::patch_caption_style(raw, &ids, patch));
                        self.push_req(false);
                    }
                    if let Some(bg) = bg {
                        // merge_object is shallow: every tweak re-sends the FULL bg object
                        let g = |k: &str, d: f64| bg.get(k).and_then(|v| v.as_f64()).unwrap_or(d);
                        let bg_col = bg.get("color").and_then(|v| v.as_str()).unwrap_or("#000000").to_string();
                        let (mut op, mut rad) = (g("opacity", 0.62), g("radius", 0.2));
                        let (pad_x, pad_y) = (g("padX", 0.5), g("padY", 0.18));
                        let mut bc = hex_color32(&bg_col, egui::Color32::BLACK);
                        let mut send: Option<serde_json::Value> = None;
                        ui.horizontal(|ui| {
                            ui.label(egui::RichText::new("枠色").weak().small());
                            if ui.color_edit_button_srgba(&mut bc).changed() {
                                send = Some(serde_json::json!({"color": color32_hex(bc)}));
                            }
                            if ui
                                .small_button("スポイト")
                                .on_hover_text("プレビューでクリックした場所の色を枠色にする")
                                .clicked()
                            {
                                self.eyedrop = Some((2, edit_ids.clone()));
                            }
                        });
                        if ui.add(egui::Slider::new(&mut op, 0.05..=1.0).text("枠の濃さ")).changed() {
                            send = Some(serde_json::json!({"opacity": (op * 100.0).round() / 100.0}));
                        }
                        if ui.add(egui::Slider::new(&mut rad, 0.0..=0.6).text("角丸")).changed() {
                            send = Some(serde_json::json!({"radius": (rad * 100.0).round() / 100.0}));
                        }
                        if let Some(delta) = send {
                            let mut full = serde_json::json!({
                                "color": bg_col, "opacity": op, "radius": rad,
                                "padX": pad_x, "padY": pad_y,
                            });
                            edits_merge_for_preset(&mut full, &delta);
                            let ids = edit_ids.clone();
                            self.remember_caption_fallbacks(&ids);
                            let patch = serde_json::json!({"bg": full});
                            self.apply_edit(false, move |raw| edits::patch_caption_style(raw, &ids, patch));
                            self.push_req(false);
                        }
                    }
                    // ---- デザインプリセット（Web版と同じ9種）----
                    ui.add_space(4.0);
                    ui.menu_button("デザインプリセット ▾", |ui| {
                        for (label, design) in caption_presets() {
                            if ui.button(label).clicked() {
                                let ids = edit_ids.clone();
                                self.remember_caption_fallbacks(&ids);
                                let patch = design.clone();
                                self.apply_edit(true, move |raw| edits::patch_caption_style(raw, &ids, patch));
                                self.push_req(false);
                                ui.close_menu();
                            }
                        }
                    });
                    if ui.button("この見た目を全テロップに適用").clicked() {
                        let ids: Vec<String> = self
                            .doc
                            .seq
                            .tracks
                            .iter()
                            .flat_map(|tr| tr.clips.iter())
                            .filter(|c| c.text.is_some() && c.asset_id.is_none())
                            .map(|c| c.id.clone())
                            .collect();
                        self.remember_caption_fallbacks(&ids);
                        let patch = clip.style.clone().unwrap_or_else(|| serde_json::json!({}));
                        self.apply_edit(true, move |raw| edits::patch_all_caption_style(raw, patch));
                        self.push_req(false);
                    }
                    return;
                }
                if clip.asset_id.is_none() {
                    return;
                }
                if kind != "audio" {
                    ui.label(egui::RichText::new("映像").strong());
                    // Multi-select applies a single explicit state to every selected video;
                    // linked audio is deliberately excluded and continues to play.
                    let mut video_enabled = selected.iter().all(|(c, k)| k != "audio" && c.is_video_enabled());
                    if ui.checkbox(&mut video_enabled, "映像を表示").changed() {
                        let ids = edit_ids.clone();
                        self.apply_edit(true, move |raw| edits::set_video_enabled(raw, &ids, video_enabled));
                        self.push_req(false);
                    }
                    ui.add_space(6.0);
                }
                // ---- position & size (canvas %) ----
                ui.label(egui::RichText::new("位置とサイズ（%）").strong());
                // keyed clips: the fields show (and edit around) the DISPLAYED pose
                let tkf_t_now = self.keyed_grid_t(clip.timeline_start, &clip.transform_key_times());
                let has_tkeys = !clip.transform_key_times().is_empty();
                let b = effective_box(&self.doc, &clip, tkf_t_now);

                let mut xy = [b.x * 100.0, b.y * 100.0];
                let mut xy_changed = false;
                ui.horizontal(|ui| {
                    ui.label(egui::RichText::new("位置 X / Y").weak().small());
                    for v in &mut xy {
                        let r = ui.add(egui::DragValue::new(v).speed(0.5).range(-100.0..=100.0).suffix("%"));
                        if r.drag_started() || r.gained_focus() {
                            self.pending_undo = Some(self.doc.raw.clone());
                        }
                        xy_changed |= r.changed();
                        if r.drag_stopped() {
                            ui.memory_mut(|mem| mem.surrender_focus(r.id));
                        }
                    }
                });
                if xy_changed {
                    let (x, y) = (xy[0] / 100.0, xy[1] / 100.0);
                    self.apply_box_edit(edit_ids.clone(), b, x, y, b.width, b.height);
                    self.push_req(false);
                }

                // A single size value scales both axes by the same factor. The geometric
                // mean stays stable even when the current box was previously stretched.
                let old_size = (b.width * b.height).sqrt().max(0.01) * 100.0;
                let mut size = old_size;
                let size_resp = ui.horizontal(|ui| {
                    ui.label(egui::RichText::new("比率維持").weak().small());
                    ui.add(egui::DragValue::new(&mut size).speed(0.5).range(1.0..=400.0).suffix("%"))
                }).inner;
                if size_resp.drag_started() || size_resp.gained_focus() {
                    self.pending_undo = Some(self.doc.raw.clone());
                }
                if size_resp.changed() {
                    let factor = size / old_size;
                    let (nw, nh) = (b.width * factor, b.height * factor);
                    let (cx, cy) = (b.x + b.width / 2.0, b.y + b.height / 2.0);
                    self.apply_box_edit(edit_ids.clone(), b, cx - nw / 2.0, cy - nh / 2.0, nw, nh);
                    self.push_req(false);
                }
                if size_resp.drag_stopped() {
                    ui.memory_mut(|mem| mem.surrender_focus(size_resp.id));
                }

                let mut wh = [b.width * 100.0, b.height * 100.0];
                let mut wh_changed = false;
                ui.horizontal(|ui| {
                    ui.label(egui::RichText::new("個別 X / Y").weak().small());
                    for v in &mut wh {
                        let r = ui.add(egui::DragValue::new(v).speed(0.5).range(1.0..=400.0).suffix("%"));
                        if r.drag_started() || r.gained_focus() {
                            self.pending_undo = Some(self.doc.raw.clone());
                        }
                        wh_changed |= r.changed();
                        if r.drag_stopped() {
                            ui.memory_mut(|mem| mem.surrender_focus(r.id));
                        }
                    }
                });
                if wh_changed {
                    let (nw, nh) = (wh[0] / 100.0, wh[1] / 100.0);
                    let (cx, cy) = (b.x + b.width / 2.0, b.y + b.height / 2.0);
                    self.apply_box_edit(edit_ids.clone(), b, cx - nw / 2.0, cy - nh / 2.0, nw, nh);
                    let ids = edit_ids.clone();
                    self.apply_edit(false, move |raw| edits::set_fit_many(raw, &ids, true));
                    self.push_req(false);
                }
                if ui.small_button("全画面に戻す").clicked() {
                    let ids = edit_ids.clone();
                    self.apply_edit(true, move |raw| {
                        edits::set_position_many(raw, &ids, 0.0, 0.0, 1.0, 1.0);
                        edits::set_fit_many(raw, &ids, false);
                    });
                    self.push_req(false);
                }
                // ---- 位置/サイズ/クロップのキーフレーム（ぼかしの手動追従と同じ操作系）----
                if !multi && kind != "audio" {
                    ui.add_space(6.0);
                    ui.label(egui::RichText::new("キーフレーム（位置・サイズ・クロップ）").strong());
                    let id = clip.id.clone();
                    let kts = clip.transform_key_times();
                    let nkeys = kts.len();
                    let rel = tkf_t_now - clip.timeline_start;
                    let on_key = kts.iter().any(|kt| (kt - rel).abs() <= edits::KEY_REPLACE_EPS);
                    let kf_on = self.kf_mode.as_deref() == Some(id.as_str());
                    ui.horizontal(|ui| {
                        if ui
                            .selectable_label(kf_on, "◆キー打ちモード")
                            .on_hover_text(
                                "ON: プレビューのドラッグ/リサイズ、数値変更、クロップ変更が表示中フレームにキーを打つ。\nOFF: キー有りクリップのドラッグは動き全体をそのまま平行移動（キーは増えない）。\n枠が赤=キー上（ドラッグで打ち直し）、オレンジ=補間中（ON中のドラッグで新規キー）",
                            )
                            .clicked()
                        {
                            self.kf_mode = if kf_on { None } else { Some(id.clone()) };
                            if self.kf_mode.is_some() {
                                self.pause_at_displayed();
                            }
                        }
                        if nkeys > 0 && !kf_on {
                            ui.label(egui::RichText::new("OFF: ドラッグ=全体移動").small().weak());
                        }
                        if nkeys > 0 && ui.button("キー全消し").clicked() {
                            let cid = id.clone();
                            self.apply_edit(true, move |raw| edits::clear_transform_keys(raw, &cid));
                            self.push_req(false);
                        }
                    });
                    if kf_on || nkeys > 0 {
                        ui.horizontal(|ui| {
                            let prev = kts.iter().rev().find(|kt| **kt < rel - 1e-3).copied();
                            let next = kts.iter().find(|kt| **kt > rel + 1e-3).copied();
                            if ui
                                .add_enabled(prev.is_some(), egui::Button::new("◀"))
                                .on_hover_text("前のキーへ")
                                .clicked()
                            {
                                self.playing = false;
                                self.t = clip.timeline_start + prev.unwrap();
                                self.push_req(false);
                            }
                            if on_key {
                                if ui
                                    .button("◆削除")
                                    .on_hover_text("再生ヘッド位置のキーだけ削除")
                                    .clicked()
                                {
                                    let cid = id.clone();
                                    self.apply_edit(true, move |raw| {
                                        edits::remove_transform_key(raw, &cid, rel)
                                    });
                                    self.push_req(false);
                                }
                            } else if ui
                                .add_enabled(rel >= 0.0 && rel <= clip.dur(), egui::Button::new("◆＋"))
                                .on_hover_text("このフレームの今の位置/サイズ/クロップにキーを打つ（動かさず固定したい時に）")
                                .on_disabled_hover_text("再生ヘッドをこのクリップの範囲内に置いてください")
                                .clicked()
                            {
                                let kb = effective_box(&self.doc, &clip, tkf_t_now);
                                let kc = clip.crop_ltrb_at(tkf_t_now);
                                let cid = id.clone();
                                self.apply_edit(true, move |raw| {
                                    edits::set_transform_key(
                                        raw, &cid, rel, kb.x, kb.y, kb.width, kb.height, kc,
                                    )
                                });
                                self.toast(&format!("◆ キーを打ちました（{}個）", nkeys + 1));
                                self.push_req(false);
                            }
                            if ui
                                .add_enabled(next.is_some(), egui::Button::new("▶"))
                                .on_hover_text("次のキーへ")
                                .clicked()
                            {
                                self.playing = false;
                                self.t = clip.timeline_start + next.unwrap();
                                self.push_req(false);
                            }
                            let status = if on_key {
                                egui::RichText::new("キー上").color(egui::Color32::from_rgb(240, 80, 80))
                            } else if nkeys > 0 {
                                egui::RichText::new(format!("補間中（{nkeys}個）"))
                                    .color(egui::Color32::from_rgb(255, 170, 60))
                            } else {
                                egui::RichText::new("キー無し").weak()
                            };
                            ui.label(status.small());
                        });
                    }
                }
                ui.add_space(6.0);
                ui.label(egui::RichText::new("不透明度").strong());
                let mut opacity = clip.opacity * 100.0;
                let opacity_resp = ui.add(
                    egui::Slider::new(&mut opacity, 0.0..=100.0)
                        .suffix("%")
                        .fixed_decimals(0),
                );
                if opacity_resp.drag_started() {
                    self.pending_undo = Some(self.doc.raw.clone());
                }
                if opacity_resp.changed() {
                    let ids = edit_ids.clone();
                    self.apply_edit(false, move |raw| edits::set_opacity_many(raw, &ids, opacity / 100.0));
                    self.push_req(false);
                }
                if opacity_resp.drag_stopped() {
                    ui.memory_mut(|mem| mem.surrender_focus(opacity_resp.id));
                }
                ui.add_space(6.0);
                // ---- volume ----
                if selected.iter().any(|(c, _)| c.link_id.is_some()) {
                    ui.label(egui::RichText::new("音量").strong());
                    let mut vol = (clip.volume * 100.0) as f32;
                    let r = ui.add(egui::Slider::new(&mut vol, 0.0..=200.0).suffix("%"));
                    if r.drag_started() {
                        self.pending_undo = Some(self.doc.raw.clone());
                    }
                    if r.changed() {
                        let ids = edits::expand_links(&self.doc.raw, &edit_ids);
                        let v = (vol / 100.0) as f64;
                        self.apply_edit(false, move |raw| edits::set_volume(raw, &ids, v));
                    }
                    ui.add_space(6.0);
                }
                // ---- 再生速度 ----
                if !clip.is_freeze() && clip.asset_id.is_some() && clip.source_end.is_some() {
                    ui.label(egui::RichText::new("再生速度").strong());
                    let has_ramp = !clip.speed_keys.is_empty();
                    let mut spd = clip.speed * 100.0;
                    ui.horizontal(|ui| {
                        let r = ui.add(
                            egui::DragValue::new(&mut spd)
                                .speed(1.0)
                                .range(5.0..=1600.0)
                                .suffix("%"),
                        );
                        if r.gained_focus() || r.drag_started() {
                            self.pending_undo = Some(self.doc.raw.clone());
                        }
                        let mut set_to: Option<f64> = None;
                        if r.changed() {
                            set_to = Some(spd / 100.0);
                        }
                        for (lbl, v) in [("0.5x", 0.5), ("1x", 1.0), ("1.5x", 1.5), ("2x", 2.0)] {
                            if ui.small_button(lbl).clicked() {
                                self.pending_undo = None;
                                set_to = Some(v);
                            }
                        }
                        if let Some(v) = set_to {
                            let ids = edits::expand_links(&self.doc.raw, &edit_ids);
                            self.apply_edit(true, move |raw| edits::set_clip_speed(raw, &ids, v));
                            self.push_req(false);
                        }
                    });
                    if has_ramp {
                        ui.label(
                            egui::RichText::new("※ランプ設定中（等速の変更でランプは解除）")
                                .weak()
                                .small(),
                        );
                    }
                    // ---- スピードランプ ----
                    if !multi {
                        ui.add_space(4.0);
                        ui.horizontal(|ui| {
                            ui.label(egui::RichText::new("スピードランプ").strong());
                            if ui.small_button("＋ 再生ヘッドにキー").clicked() {
                                let mut keys = clip.speed_keys.clone();
                                let u = if self.t > clip.timeline_start + 0.05
                                    && self.t < clip.timeline_end - 0.05
                                {
                                    clip.src_at(self.t)
                                } else {
                                    clip.source_start
                                };
                                let v = if keys.is_empty() {
                                    clip.speed.max(0.05)
                                } else {
                                    clip.rate_at(self.t)
                                };
                                keys.push(model::SpeedKey { u, v, ease: 0.5 });
                                keys.sort_by(|a, b| a.u.total_cmp(&b.u));
                                let ids = edits::expand_links(&self.doc.raw, &edit_ids);
                                self.apply_edit(true, move |raw| edits::set_speed_keys(raw, &ids, &keys));
                                self.push_req(false);
                            }
                        });
                        if !clip.speed_keys.is_empty() {
                            let mut keys = clip.speed_keys.clone();
                            let mut kchanged = false;
                            let mut remove: Option<usize> = None;
                            let css = clip.source_start;
                            for (i, k) in keys.iter_mut().enumerate() {
                                ui.horizontal(|ui| {
                                    ui.label(egui::RichText::new(format!("{}", i + 1)).weak().small());
                                    ui.label(egui::RichText::new("位置").weak().small());
                                    let mut pos = k.u - css;
                                    let r1 = ui.add(
                                        egui::DragValue::new(&mut pos).speed(0.05).suffix("s"),
                                    );
                                    if r1.changed() {
                                        k.u = css + pos.max(0.0);
                                        kchanged = true;
                                    }
                                    ui.label(egui::RichText::new("速度").weak().small());
                                    let mut v = k.v;
                                    let r2 = ui.add(
                                        egui::DragValue::new(&mut v)
                                            .speed(0.02)
                                            .range(0.1..=8.0)
                                            .suffix("x"),
                                    );
                                    if r2.changed() {
                                        k.v = v;
                                        kchanged = true;
                                    }
                                    ui.label(egui::RichText::new("カーブ").weak().small());
                                    let mut e = k.ease;
                                    let r3 = ui.add(
                                        egui::DragValue::new(&mut e).speed(0.02).range(0.0..=1.0),
                                    );
                                    if r3.changed() {
                                        k.ease = e;
                                        kchanged = true;
                                    }
                                    if r1.drag_started() || r2.drag_started() || r3.drag_started() {
                                        self.pending_undo = Some(self.doc.raw.clone());
                                    }
                                    if ui.small_button("✖").clicked() {
                                        remove = Some(i);
                                    }
                                });
                            }
                            if let Some(i) = remove {
                                keys.remove(i);
                                kchanged = true;
                            }
                            if kchanged {
                                keys.sort_by(|a, b| a.u.total_cmp(&b.u));
                                let ids = edits::expand_links(&self.doc.raw, &edit_ids);
                                self.apply_edit(false, move |raw| edits::set_speed_keys(raw, &ids, &keys));
                                self.push_req(false);
                            }
                            ui.label(
                                egui::RichText::new("位置=クリップ内ソース秒 / カーブ=つなぎ目の滑らかさ(0=急,1=なだらか)")
                                    .weak()
                                    .small(),
                            );
                        }
                    }
                    ui.add_space(6.0);
                }
                // ---- カラー（グレード）----
                if clip.asset_id.is_some() {
                    ui.label(egui::RichText::new("カラー").strong());
                    let g = clip.grade.clone().unwrap_or_else(|| serde_json::json!({}));
                    let gf = |k: &str, d: f64| g.get(k).and_then(|v| v.as_f64()).unwrap_or(d);
                    let cur_log = g.get("log").and_then(|v| v.as_str()).unwrap_or("").to_string();
                    ui.horizontal_wrapped(|ui| {
                        ui.label(egui::RichText::new("Log変換").weak().small());
                        for (label, val) in
                            [("なし", ""), ("S-Log3", "slog3"), ("V-Log", "vlog"), ("C-Log3", "clog3")]
                        {
                            if ui.selectable_label(cur_log == val, label).clicked() {
                                let ids = edit_ids.clone();
                                let patch = if val.is_empty() {
                                    serde_json::json!({"log": null})
                                } else {
                                    serde_json::json!({"log": val})
                                };
                                self.apply_edit(true, move |raw| edits::set_grade(raw, &ids, &patch));
                                self.push_req(false);
                            }
                        }
                    });
                    // プリセット=スライダー5本の値の束。トグル式: もう一度押すと
                    // オフ＝調整値を全部外してスライダーが初期位置に戻る（Logは維持）。
                    // 束は5キー全指定（マージ残りで前のプリセットの色が混ざらないように）。
                    let cur5 = [gf("ev", 0.0), gf("contrast", 1.0), gf("sat", 1.0), gf("temp", 0.0), gf("tint", 0.0)];
                    ui.horizontal_wrapped(|ui| {
                        ui.label(egui::RichText::new("プリセット").weak().small());
                        for (label, p) in [
                            ("シネマ", [0.0, 1.15, 0.95, 0.15, 0.0]),
                            ("ティール&オレンジ", [0.0, 1.12, 1.1, 0.35, -0.08]),
                            ("ビビッド", [0.0, 1.1, 1.35, 0.0, 0.0]),
                            ("フィルム", [0.0, 0.92, 0.85, 0.08, 0.05]),
                            ("モノクロ", [0.0, 1.05, 0.0, 0.0, 0.0]),
                        ] {
                            let active = cur5.iter().zip(p).all(|(a, b)| (a - b).abs() < 1e-4);
                            if ui.selectable_label(active, label).clicked() {
                                let ids = edit_ids.clone();
                                let patch = if active {
                                    serde_json::json!({"ev": null, "contrast": null, "sat": null, "temp": null, "tint": null})
                                } else {
                                    serde_json::json!({"ev": p[0], "contrast": p[1], "sat": p[2], "temp": p[3], "tint": p[4]})
                                };
                                self.apply_edit(true, move |raw| edits::set_grade(raw, &ids, &patch));
                                self.push_req(false);
                            }
                        }
                    });
                    let mut ev = gf("ev", 0.0) as f32;
                    let r = ui.add(egui::Slider::new(&mut ev, -2.0..=2.0).text("露出").fixed_decimals(2));
                    if r.drag_started() {
                        self.pending_undo = Some(self.doc.raw.clone());
                    }
                    if r.changed() {
                        let ids = edit_ids.clone();
                        let patch = serde_json::json!({"ev": ev as f64});
                        self.apply_edit(false, move |raw| edits::set_grade(raw, &ids, &patch));
                        self.push_req(false);
                    }
                    let mut ct = gf("contrast", 1.0) as f32;
                    let r = ui.add(egui::Slider::new(&mut ct, 0.5..=1.8).text("コントラスト").fixed_decimals(2));
                    if r.drag_started() {
                        self.pending_undo = Some(self.doc.raw.clone());
                    }
                    if r.changed() {
                        let ids = edit_ids.clone();
                        let patch = serde_json::json!({"contrast": ct as f64});
                        self.apply_edit(false, move |raw| edits::set_grade(raw, &ids, &patch));
                        self.push_req(false);
                    }
                    let mut sat = gf("sat", 1.0) as f32;
                    let r = ui.add(egui::Slider::new(&mut sat, 0.0..=2.0).text("彩度").fixed_decimals(2));
                    if r.drag_started() {
                        self.pending_undo = Some(self.doc.raw.clone());
                    }
                    if r.changed() {
                        let ids = edit_ids.clone();
                        let patch = serde_json::json!({"sat": sat as f64});
                        self.apply_edit(false, move |raw| edits::set_grade(raw, &ids, &patch));
                        self.push_req(false);
                    }
                    let mut temp = gf("temp", 0.0) as f32;
                    let r = ui.add(egui::Slider::new(&mut temp, -1.0..=1.0).text("色温度").fixed_decimals(2));
                    if r.drag_started() {
                        self.pending_undo = Some(self.doc.raw.clone());
                    }
                    if r.changed() {
                        let ids = edit_ids.clone();
                        let patch = serde_json::json!({"temp": temp as f64});
                        self.apply_edit(false, move |raw| edits::set_grade(raw, &ids, &patch));
                        self.push_req(false);
                    }
                    let mut tint = gf("tint", 0.0) as f32;
                    let r = ui.add(egui::Slider::new(&mut tint, -1.0..=1.0).text("ティント").fixed_decimals(2));
                    if r.drag_started() {
                        self.pending_undo = Some(self.doc.raw.clone());
                    }
                    if r.changed() {
                        let ids = edit_ids.clone();
                        let patch = serde_json::json!({"tint": tint as f64});
                        self.apply_edit(false, move |raw| edits::set_grade(raw, &ids, &patch));
                        self.push_req(false);
                    }
                    ui.horizontal(|ui| {
                        if ui.small_button("調整をリセット").clicked() {
                            let ids = edit_ids.clone();
                            let patch = serde_json::json!({"ev": null, "contrast": null, "sat": null, "temp": null, "tint": null});
                            self.apply_edit(true, move |raw| edits::set_grade(raw, &ids, &patch));
                            self.push_req(false);
                        }
                        if ui.small_button("すべてリセット").clicked() {
                            let ids = edit_ids.clone();
                            self.apply_edit(true, move |raw| {
                                edits::set_grade(raw, &ids, &serde_json::Value::Null)
                            });
                            self.push_req(false);
                        }
                    });
                    ui.label(
                        egui::RichText::new("複数選択中は選択した全クリップに適用されます")
                            .weak()
                            .small(),
                    );
                    ui.add_space(6.0);
                }
                // ---- crop ----
                ui.label(egui::RichText::new("クロップ（端を切る %）").strong());
                let (l, t, r_, bm) = if has_tkeys {
                    clip.crop_ltrb_at(tkf_t_now).unwrap_or((0.0, 0.0, 0.0, 0.0))
                } else {
                    clip.crop_ltrb().unwrap_or((0.0, 0.0, 0.0, 0.0))
                };
                let mut cr = [l * 100.0, t * 100.0, r_ * 100.0, bm * 100.0];
                let mut cchanged = false;
                for (row, pair, names) in [
                    ("左 / 右", [0usize, 2], true),
                    ("上 / 下", [1, 3], true),
                ] {
                    let _ = names;
                    ui.horizontal(|ui| {
                        ui.label(egui::RichText::new(row).weak().small());
                        for &i in &pair {
                            let r = ui.add(
                                egui::DragValue::new(&mut cr[i]).speed(0.5).range(0.0..=90.0).suffix("%"),
                            );
                            if r.drag_started() || r.gained_focus() {
                                self.pending_undo = Some(self.doc.raw.clone());
                            }
                            cchanged |= r.changed();
                        }
                    });
                }
                if cchanged {
                    let (cl, ct, crr, cb) =
                        (cr[0] / 100.0, cr[1] / 100.0, cr[2] / 100.0, cr[3] / 100.0);
                    let tkf_rel = tkf_t_now - clip.timeline_start;
                    if !multi
                        && self.kf_mode.as_deref() == Some(clip.id.as_str())
                        && tkf_rel >= 0.0
                        && tkf_rel <= clip.dur()
                    {
                        // キー打ちモードON: 表示フレームに「今の枠＋新しいクロップ」のキー
                        let cid = clip.id.clone();
                        self.apply_edit(false, move |raw| {
                            edits::set_transform_key(
                                raw, &cid, tkf_rel, b.x, b.y, b.width, b.height,
                                Some((cl, ct, crr, cb)),
                            )
                        });
                    } else {
                        let ids = edit_ids.clone();
                        self.apply_edit(false, move |raw| edits::set_crop_many(raw, &ids, cl, ct, crr, cb));
                    }
                    self.push_req(false);
                }
                if clip.crop_ltrb().is_some() && ui.small_button("クロップ解除").clicked() {
                    let ids = edit_ids.clone();
                    self.apply_edit(true, move |raw| edits::set_crop_many(raw, &ids, 0.0, 0.0, 0.0, 0.0));
                    self.push_req(false);
                }
                ui.add_space(6.0);
                // ---- popout ----
                if !multi && kind != "audio" {
                    ui.label(egui::RichText::new("飛び出し").strong());
                    let has = clip.effects.iter().any(|e| e.kind == "popout");
                    if ui
                        .button(if has { "解除する" } else { "適用する (E)" })
                        .clicked()
                    {
                        self.toggle_popout();
                    }
                }
                ui.add_space(10.0);
                ui.label(
                    egui::RichText::new("ヒント: プレビュー上でも直接ドラッグ移動・四隅でリサイズできます")
                        .small()
                        .weak(),
                );
            });
        });
    }

    /// F: freeze-frame — hold the frame under the playhead for 2s inside the selected
    /// (or hit) clip; everything after shifts right (ripple insert).
    fn freeze_at_playhead(&mut self) {
        self.pause_at_displayed();
        let t = self.t;
        let target = self
            .doc
            .seq
            .tracks
            .iter()
            .filter(|tr| tr.kind != "audio")
            .flat_map(|tr| tr.clips.iter())
            .find(|c| {
                c.asset_id.is_some()
                    && t > c.timeline_start + 0.05
                    && t < c.timeline_end - 0.05
                    && (self.selected.is_empty() || self.selected.contains(&c.id))
            })
            .map(|c| c.id.clone());
        let Some(id) = target else {
            self.toast("フリーズ: 再生ヘッドを映像クリップの上に置いてください");
            return;
        };
        // Snap the split to the END of the displayed frame (pts sidecar), and remember
        // the frame's duration. User contract (2026-07-06): left clip's LAST frame, the
        // still, and the right clip's FIRST frame are all the SAME frame — the one on
        // screen when F was pressed. Splitting at the frame's end keeps that frame inside
        // the left piece; `frame_back` rewinds the still + right pieces onto it.
        let (snap_delta, frame_back) = self
            .doc
            .seq
            .tracks
            .iter()
            .flat_map(|tr| tr.clips.iter())
            .find(|c| c.id == id)
            .and_then(|c| {
                let aid = c.asset_id.as_deref()?;
                // 速度対応: ヘッド下のソース時刻・フレーム端→タイムラインの換算は
                // クリップの写像/局所レート経由（1:1だと速度クリップでズレる）
                let src = c.src_at(t);
                let p = format!("{}/{aid}_proxy.pts.json", self.doc.asset_dir);
                let txt = std::fs::read_to_string(p).ok()?;
                let v: serde_json::Value = serde_json::from_str(&txt).ok()?;
                let pts: Vec<f64> = v
                    .get("pts")?
                    .as_array()?
                    .iter()
                    .filter_map(|x| x.as_f64())
                    .collect();
                if pts.is_empty() {
                    return None;
                }
                let i = pts.partition_point(|p| *p <= src);
                let lo = if i > 0 { pts[i - 1] } else { pts[0] };
                let hi = *pts.get(i).unwrap_or(&lo);
                // the frame the paused preview is showing (verified by press-frame diff)
                let (chosen, j) = if (src - lo).abs() <= (hi - src).abs() {
                    (lo, i.saturating_sub(1))
                } else {
                    (hi, i)
                };
                // its end = the next frame's pts; fall back to the local gap / 30fps
                let fd = pts
                    .get(j + 1)
                    .map(|n| n - chosen)
                    .filter(|d| *d > 1e-4 && *d < 1.0)
                    .or_else(|| (j > 0).then(|| chosen - pts[j - 1]).filter(|d| *d > 1e-4))
                    .unwrap_or(1.0 / 30.0);
                // split at the frame's end — but never past the clip's own tail (a VFR
                // hole near the end could otherwise push the split outside the clip and
                // leave a gap). When clamped, `back` shrinks so the rewind still lands
                // exactly on the displayed frame's pts.
                let rate = c.rate_at(t).max(0.01);
                let tn = (t + (chosen + fd + 0.0002 - src) / rate).min(c.timeline_end - 0.05);
                let new_src = c.src_at(tn);
                Some((tn - t, (new_src - chosen).max(0.0)))
            })
            .unwrap_or((0.0, 0.0));
        let t = t + snap_delta; // split lands at the displayed frame's END
        let salt = self.salt;
        self.salt += 1;
        // Filmora-style materialized still — but NEVER on the UI thread (the sync call
        // froze the app for seconds and flashed a console window: confirmed bug). The clip
        // records the PNG path up front; the engine picks the file up the moment the
        // background ffmpeg finishes.
        let bake = self
            .doc
            .seq
            .tracks
            .iter()
            .flat_map(|tr| tr.clips.iter())
            .find(|c| c.id == id)
            .and_then(|c| {
                let aid = c.asset_id.as_deref()?;
                let src = (c.src_at(t) - frame_back).max(0.0);
                let srcp = self.doc.asset_path_q(aid, false);
                Some((src, srcp))
            });
        let still_rel = bake.as_ref().map(|_| format!("stills/fz_{salt}.png"));
        // capture what the user was LOOKING AT when F was pressed (symptom-B ground truth):
        // the presented frame buffer, saved next to the still for later pixel comparison
        {
            let shown = {
                let f = self.shared.frame.lock().unwrap();
                (!f.rgba.is_empty()).then(|| f.rgba.clone())
            };
            if let Some(rgba) = shown {
                let out = format!("{}/stills/debug_press_{salt}.png", self.doc.asset_dir);
                let dir = format!("{}/stills", self.doc.asset_dir);
                std::thread::spawn(move || {
                    let _ = std::fs::create_dir_all(&dir);
                    let (w, h) = (canvas_w(), canvas_h());
                    if rgba.len() == (w * h * 4) as usize {
                        let _ = image::save_buffer(&out, &rgba, w, h, image::ColorType::Rgba8);
                        eprintln!("PRESS_FRAME saved {out}");
                    }
                });
            }
        }
        if let (Some((src, srcp)), Some(rel)) = (bake, still_rel.clone()) {
            let dir = format!("{}/stills", self.doc.asset_dir);
            let out = format!("{}/{rel}", self.doc.asset_dir);
            eprintln!("FREEZE_PRESS t={t:.3} src={src:.3} out={rel}");
            std::thread::spawn(move || {
                use std::os::windows::process::CommandExt;
                let _ = std::fs::create_dir_all(&dir);
                let ff = ["C:/Users/Owner/ffmpeg/bin/ffmpeg.exe", "C:/ffmpeg/bin/ffmpeg.exe"]
                    .into_iter()
                    .find(|f| std::path::Path::new(f).exists())
                    .unwrap_or("ffmpeg");
                let t0 = std::time::Instant::now();
                let tmp = format!("{out}.part.png");
                let ok = std::process::Command::new(ff)
                    .args([
                        "-y",
                        "-ss",
                        &format!("{:.4}", (src - 0.0002).max(0.0)),
                        "-i",
                        &srcp,
                        "-frames:v",
                        "1",
                        &tmp,
                    ])
                    .creation_flags(0x0800_0000) // CREATE_NO_WINDOW
                    .stdout(std::process::Stdio::null())
                    .stderr(std::process::Stdio::null())
                    .status()
                    .map(|st| st.success())
                    .unwrap_or(false);
                let good = ok && std::fs::metadata(&tmp).map(|m| m.len() > 0).unwrap_or(false);
                if good {
                    let _ = std::fs::rename(&tmp, &out);
                    eprintln!("FZ_BAKE_DONE {}ms {rel}", t0.elapsed().as_millis());
                } else {
                    let _ = std::fs::remove_file(&tmp);
                    eprintln!("FZ_BAKE_FAIL {}ms {rel} src={srcp}", t0.elapsed().as_millis());
                }
            });
        }
        self.apply_edit(true, move |raw| {
            edits::freeze_frame_with_still(raw, &id, t, 2.0, salt, still_rel, frame_back)
        });
        self.push_req(false);
        self.toast("フリーズフレームを挿入しました（2秒・静止画は数秒で確定します）");
    }

    /// Insert a library asset at the playhead on the main video lane (ripple insert).
    fn insert_asset_at_playhead(&mut self, asset: &serde_json::Value) {
        let aid = asset.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
        if aid.is_empty() {
            return;
        }
        let meta = asset.get("metadata").and_then(|m| m.as_object());
        let dur = meta
            .and_then(|m| m.get("duration"))
            .and_then(|d| d.as_f64())
            .unwrap_or(5.0)
            .max(0.5);
        let has_audio = meta
            .and_then(|m| m.get("audio_codec"))
            .and_then(|a| a.as_str())
            .map(|a| !a.is_empty())
            .unwrap_or(false);
        self.pause_at_displayed();
        let t = self.t;
        let salt = self.salt;
        self.salt += 1;
        self.apply_edit(true, move |raw| {
            edits::insert_asset(raw, t, dur, &aid, has_audio, salt)
        });
        self.push_req(false);
        self.toast("素材を挿入しました（後ろは右にシフト）");
    }

    /// Load (and lazily generate) library thumbnails — used by the library grid AND the
    /// editor's ＋素材 menu.
    /// Place a media-library asset at the lane/time chosen by a direct drag.
    /// This is non-ripple so dropping media never shifts an existing edit.
    fn place_library_asset_at(&mut self, asset: &serde_json::Value, t: f64, target: usize) {
        let aid = asset.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
        if aid.is_empty() {
            return;
        }
        let is_image = asset.get("kind").and_then(|v| v.as_str()) == Some("image")
            || asset
                .get("local_path")
                .and_then(|v| v.as_str())
                .map(|p| is_image_path(std::path::Path::new(p)))
                .unwrap_or(false);
        let meta = asset.get("metadata").and_then(|m| m.as_object());
        let dur = if is_image {
            5.0
        } else {
            meta.and_then(|m| m.get("duration"))
                .and_then(|d| d.as_f64())
                .unwrap_or(5.0)
                .max(0.5)
        };
        let has_audio = !is_image
            && meta.and_then(|m| m.get("audio_codec"))
                .and_then(|a| a.as_str())
                .map(|a| !a.is_empty())
                .unwrap_or(false);
        self.pause_at_displayed();
        let salt = self.salt;
        self.salt += 1;
        self.apply_edit(true, move |raw| {
            edits::place_asset(raw, target, t, dur, &aid, has_audio, is_image, salt);
        });
        self.selected.clear();
        self.selected.push(format!("drop_v_{salt}"));
        self.t = t;
        self.push_req(false);
        self.toast(if is_image {
            "画像をタイムラインに追加しました（長さは5秒です）"
        } else {
            "映像をタイムラインに追加しました"
        });
    }

    fn ensure_lib_thumbs(&mut self, ctx: &egui::Context) {
        let room_dir = self.doc.asset_dir.clone();
        let ids: Vec<String> = self
            .lib
            .assets
            .iter()
            .filter_map(|a| a.get("id").and_then(|v| v.as_str()).map(|s| s.to_string()))
            .collect();
        for id in ids {
            if self.lib.thumbs.contains_key(&id) {
                continue;
            }
            let p = format!("{room_dir}/{id}_thumb.jpg");
            if !std::path::Path::new(&p).exists() && !self.lib.thumb_tried.contains(&id) {
                // missing thumb: spawn ffmpeg once against the proxy (or original)
                self.lib.thumb_tried.insert(id.clone());
                let src = [format!("{room_dir}/{id}_proxy.mp4"), format!("{room_dir}/{id}.mp4")]
                    .into_iter()
                    .find(|f| std::fs::metadata(f).map(|m| m.len() > 0).unwrap_or(false));
                if let Some(src) = src {
                    let ff = ["C:/Users/Owner/ffmpeg/bin/ffmpeg.exe", "C:/ffmpeg/bin/ffmpeg.exe"]
                        .into_iter()
                        .find(|f| std::path::Path::new(f).exists())
                        .unwrap_or("ffmpeg");
                    let _ = std::process::Command::new(ff)
                        .args(["-y", "-ss", "0.5", "-i", &src, "-frames:v", "1", "-vf", "scale=320:-2", &p])
                        .stdout(std::process::Stdio::null())
                        .stderr(std::process::Stdio::null())
                        .spawn();
                }
                continue;
            }
            if let Ok(bytes) = std::fs::read(&p) {
                if let Ok(img) = image::load_from_memory(&bytes) {
                    let rgba = img.to_rgba8();
                    let (w, h) = (rgba.width() as usize, rgba.height() as usize);
                    let tex = ctx.load_texture(
                        format!("lib_{id}"),
                        egui::ColorImage::from_rgba_unmultiplied([w, h], &rgba),
                        egui::TextureOptions::LINEAR,
                    );
                    self.lib.thumbs.insert(id, tex);
                }
            }
        }
    }

    fn lib_get(&self, tag: &str, path: String) {
        let sink = self.lib_sink.clone();
        let tag = tag.to_string();
        std::thread::spawn(move || {
            let res = http_local("GET", &path, None)
                .and_then(|t| Ok(serde_json::from_str::<serde_json::Value>(&t)?))
                .map_err(|e| format!("{e:#}"));
            sink.lock().unwrap().push((tag, res));
        });
    }

    fn lib_post(&self, tag: &str, path: String, body: serde_json::Value) {
        let sink = self.lib_sink.clone();
        let tag = tag.to_string();
        std::thread::spawn(move || {
            let res = http_local("POST", &path, Some(&body.to_string()))
                .and_then(|t| Ok(serde_json::from_str::<serde_json::Value>(&t)?))
                .map_err(|e| format!("{e:#}"));
            sink.lock().unwrap().push((tag, res));
        });
    }

    fn lib_del(&self, tag: &str, path: String) {
        let sink = self.lib_sink.clone();
        let tag = tag.to_string();
        std::thread::spawn(move || {
            let res = http_local("DELETE", &path, None)
                .and_then(|t| Ok(serde_json::from_str::<serde_json::Value>(&t)?))
                .map_err(|e| format!("{e:#}"));
            sink.lock().unwrap().push((tag, res));
        });
    }

    fn lib_refresh(&mut self) {
        let room = self.room_id();
        self.lib_get("assets", format!("/api/v1/production-assets?room_id={room}"));
        self.lib_get("contents", format!("/api/v1/production-assets/contents?room_id={room}"));
        if self.room_label.is_none() {
            // どのチャットルームのエディタかをタイトルバーに出すための部屋名解決
            self.lib_get("projects", "/api/v1/projects".into());
        }
    }

    /// Open a content in the editor. The editor machinery assumes index 0, so the picked
    /// content is moved to the array head (order is cosmetic; saving writes the whole
    /// array back, nothing is lost).
    /// Legacy freeze clips (created before the materialized-PNG era, or while the
    /// silent ffmpeg bug ate the bake) have no freeze_still and fall back to per-frame
    /// decoding forever — the measured source of "the still moves". Bake their PNGs.
    fn migrate_legacy_freezes(&mut self) {
        let jobs: Vec<(String, String, f64)> = self
            .doc
            .seq
            .tracks
            .iter()
            .flat_map(|tr| tr.clips.iter())
            .filter(|c| c.is_freeze() && c.freeze_still.is_none() && c.asset_id.is_some())
            .map(|c| {
                (
                    c.id.clone(),
                    self.doc.asset_path_q(c.asset_id.as_deref().unwrap(), false),
                    c.source_start,
                )
            })
            .collect();
        if jobs.is_empty() {
            return;
        }
        eprintln!("FZ_MIGRATE {} legacy freeze clips", jobs.len());
        for (cid, srcp, src) in jobs {
            let rel = format!("stills/fzmig_{}.png", cid.replace(['/', '\\'], "_"));
            let out = format!("{}/{rel}", self.doc.asset_dir);
            let dir = format!("{}/stills", self.doc.asset_dir);
            let rel2 = rel.clone();
            let cid2 = cid.clone();
            self.apply_edit(false, move |raw| {
                edits::set_freeze_still(raw, &cid2, &rel2);
            });
            if std::fs::metadata(&out).map(|m| m.len() > 0).unwrap_or(false) {
                continue; // already baked in an earlier session
            }
            std::thread::spawn(move || {
                use std::os::windows::process::CommandExt;
                let _ = std::fs::create_dir_all(&dir);
                let ff = ["C:/Users/Owner/ffmpeg/bin/ffmpeg.exe", "C:/ffmpeg/bin/ffmpeg.exe"]
                    .into_iter()
                    .find(|f| std::path::Path::new(f).exists())
                    .unwrap_or("ffmpeg");
                let tmp = format!("{out}.part.png");
                let ok = std::process::Command::new(ff)
                    .args([
                        "-y",
                        "-ss",
                        &format!("{:.4}", (src - 0.0002).max(0.0)),
                        "-i",
                        &srcp,
                        "-frames:v",
                        "1",
                        &tmp,
                    ])
                    .creation_flags(0x0800_0000)
                    .stdout(std::process::Stdio::null())
                    .stderr(std::process::Stdio::null())
                    .status()
                    .map(|st| st.success())
                    .unwrap_or(false);
                if ok && std::fs::metadata(&tmp).map(|m| m.len() > 0).unwrap_or(false) {
                    let _ = std::fs::rename(&tmp, &out);
                    eprintln!("FZ_MIGRATE_DONE {rel}");
                } else {
                    let _ = std::fs::remove_file(&tmp);
                    eprintln!("FZ_MIGRATE_FAIL {rel}");
                }
            });
        }
    }

    /// 現在の doc の全クリップid（ライブ再読込時の「新規クリップ」検出用）
    fn clip_id_set(&self) -> std::collections::HashSet<String> {
        self.doc
            .seq
            .tracks
            .iter()
            .flat_map(|t| t.clips.iter().map(|c| c.id.clone()))
            .collect()
    }

    /// 再読込で増えたクリップに時差の出現時刻を割り当てる（60ms間隔のフェードイン）
    fn stagger_new_clips(&mut self, before: &std::collections::HashSet<String>) {
        let mut delay = 0u64;
        let ids: Vec<String> = self
            .doc
            .seq
            .tracks
            .iter()
            .flat_map(|t| t.clips.iter().map(|c| c.id.clone()))
            .collect();
        for id in ids {
            if !before.contains(&id) {
                self.clip_spawn
                    .insert(id, Instant::now() + std::time::Duration::from_millis(delay));
                delay = (delay + 40).min(160);
            }
        }
    }

    /// 出現アニメ中クリップのベール透明度（None=アニメ完了/対象外）。
    /// フェード0.4秒。開始時刻が未来（時差待ち）の間は完全に隠す。
    fn spawn_veil(&self, id: &str) -> Option<u8> {
        let t0 = self.clip_spawn.get(id)?;
        let el = t0.elapsed().as_secs_f32(); // 未来のInstantは0に飽和
        let a = (el / 0.4).clamp(0.0, 1.0);
        if a >= 1.0 { None } else { Some(((1.0 - a) * 235.0) as u8) }
    }

    /// 開いているコンテンツが生成中（＝ライブ表示・編集ロック対象）か
    fn refresh_job_state(&mut self) {
        let path=format!("{}/jobs.json", self.doc.asset_dir);
        let Ok(text)=std::fs::read_to_string(path) else { return };
        let Ok(rows)=serde_json::from_str::<Vec<serde_json::Value>>(&text) else { return };
        let cid=self.content_id();
        let active=rows.iter().any(|j| j["content_id"].as_str()==Some(cid.as_str())
            && matches!(j["status"].as_str(), Some("running" | "queued")));
        self.generating_content=if active { Some(cid) } else { None };
        if !active { self.assistant.production.clear(); self.assistant.production_label=None; }
    }

    fn is_generating_open(&self) -> bool {
        self.generating_content.is_some()
            && self.generating_content.as_deref() == Some(self.content_id().as_str())
    }

    /// contents.json の mtime を今の値で記憶する（open / save の直後に呼ぶ）
    fn remember_disk_mtime(&mut self) {
        let path = format!("{}/contents.json", self.doc.asset_dir);
        self.disk_mtime = std::fs::metadata(&path).and_then(|m| m.modified()).ok();
    }

    /// 外部更新の取り込み（2秒ポーリングから）。再生位置・選択・再生状態は保ったまま開き直す。
    fn poll_external_update(&mut self, viewport_width: f32) {
        let path = format!("{}/contents.json", self.doc.asset_dir);
        let Ok(mt) = std::fs::metadata(&path).and_then(|m| m.modified()) else { return };
        if self.disk_mtime.map_or(false, |prev| mt <= prev) {
            return;
        }
        let Ok(txt) = std::fs::read_to_string(&path) else { return };
        let Ok(on_disk) = serde_json::from_str::<serde_json::Value>(&txt) else { return };
        let fp = serde_json::to_string(&on_disk).unwrap_or_default();
        if fp == self.disk_fingerprint {
            return; // 自分の保存
        }
        let cid = self.content_id();
        if cid.is_empty() {
            return;
        }
        if self.save_at.is_some() {
            return;
        }
        self.disk_mtime = Some(mt);
        let keep_t = self.displayed_t();
        let keep_sel = self.selected.clone();
        let keep_playing = self.playing;
        let keep_pps = self.pps;
        let keep_scroll_x = self.scroll_x;
        let before = self.clip_id_set();
        let old_clips: std::collections::HashMap<String, String> = self.doc.seq.tracks.iter()
            .flat_map(|t| t.clips.iter()).map(|c| (c.id.clone(), format!("{c:?}"))).collect();
        let previous_raw = self.doc.raw.to_string();
        let previous_undo = self.undo.clone();
        self.open_content_impl(&cid, false);
        self.undo = previous_undo;
        self.undo.push(previous_raw);
        self.redo.clear();
        self.t = keep_t.min(self.dur.max(0.0));
        let ids = self.clip_id_set();
        self.selected = keep_sel.into_iter().filter(|s| ids.contains(s)).collect();
        self.playing = keep_playing;
        self.pps = keep_pps;
        self.scroll_x = keep_scroll_x;
        if before.is_empty() && !ids.is_empty() && self.dur > 0.0 {
            self.zoom_fit(viewport_width);
        }
        self.stagger_new_clips(&before);
        for clip in self.doc.seq.tracks.iter().flat_map(|t| t.clips.iter()) {
            if old_clips.get(&clip.id).map_or(false, |old| old != &format!("{clip:?}")) {
                self.clip_spawn.insert(clip.id.clone(), Instant::now());
            }
        }
        self.push_req(false);
        // The changed clips themselves provide feedback; avoid a toast per edit.
    }

    /// エディタ状態を部屋フォルダへ公開（editor_state.json）。チャット/音声のダンが
    /// 「いまどのコンテンツの何秒を見て、何を選んでいるか」を読むための一方向チャネル。
    fn assistant_ui(&mut self, ctx: &egui::Context, frame: &eframe::Frame) {
        let assistant_context = serde_json::json!({
            "room_id": self.room_id(), "content_id": if self.screen == Screen::Editor { self.content_id() } else { String::new() },
            "playhead": (self.displayed_t() * 1000.0).round() / 1000.0,
            "unsaved": self.save_at.is_some(),
            "pointer": self.assistant.pointer,
            "visible_targets": self.assistant.targets,
            "region_selection": self.assistant.selection,
            "preview_viewport": self.assistant.viewport,
            "selected": self.doc.seq.tracks.iter().flat_map(|tr| tr.clips.iter())
                .filter(|c| self.selected.contains(&c.id))
                .map(|c| serde_json::json!({"id": c.id, "text": c.text,
                    "approved": self.doc.raw.as_array().and_then(|a| a.first())
                        .and_then(|c0| c0.pointer("/timeline/sequence/tracks")).and_then(|t| t.as_array())
                        .map(|tracks| tracks.iter().filter_map(|t| t["clips"].as_array())
                            .flatten().any(|raw| raw["id"].as_str() == Some(c.id.as_str()) && raw["approved"] == true))
                        .unwrap_or(false),
                    "timeline_start": c.timeline_start, "timeline_end": c.timeline_end}))
                .collect::<Vec<_>>()
        });
        let assistant_token = API_TOKEN.read().unwrap().clone().unwrap_or_default();
        for command in self.assistant.show(ctx, frame, assistant_context, &assistant_token) {
            match command.as_str() {
                "auth" => {}, // assistant.show already renewed and published it
                "return_keyboard" => {
                    if let Some(id) = ctx.memory(|m| m.focused()) {
                        ctx.memory_mut(|m| m.surrender_focus(id));
                    }
                },
                "toggle_play" if self.screen == Screen::Editor => self.toggle_play(),
                "close" => self.assistant.open = false,
                "stage_full" => { self.assistant.immersive = true; self.pause_at_displayed(); },
                "stage_compact" => self.assistant.immersive = false,
                _ if command.starts_with("external:https://") => { let _ = std::process::Command::new("rundll32").args(["url.dll,FileProtocolHandler", &command[9..]]).spawn(); },
                "undo" => { self.poll_external_update(ctx.screen_rect().width()); self.do_undo(); },
                "refresh" => self.poll_external_update(ctx.screen_rect().width()),
                "pick" => { self.assistant.pick = true; self.assistant.open = true; self.assistant.immersive = false; },
                "clear_focus" => { self.assistant.focus = None; self.assistant.selection = None; },
                _ if command.starts_with('{') => {
                    if let Ok(v) = serde_json::from_str::<serde_json::Value>(&command) {
                        let id = v["request_id"].as_str().unwrap_or("");
                        let action = &v["action"];
                        if action["content_id"].as_str() == Some(self.content_id().as_str()) && self.screen == Screen::Editor {
                            match action["kind"].as_str().unwrap_or("") {
                                "production_activity" => {
                                    self.assistant.production=action["operations"].as_array().cloned().unwrap_or_default();
                                    self.assistant.production_at=Some(Instant::now());
                                    self.assistant.production_label=action["label"].as_str().map(str::to_owned);
                                    if action["active_count"].as_u64()==Some(0) { self.generating_content=None; }
                                    ctx.request_repaint();
                                },
                                "work_finished" => {
                                    self.refresh_job_state();
                                    let text=match (action["status"].as_str(),action["committed"].as_bool()) {
                                        (Some("done"),Some(true)) => "ダンの編集が完了しました",
                                        (Some("done"),_) => "ダンの作業が終了しました",
                                        (Some("canceled"),_) => "作業を停止しました",
                                        _ => "作業が止まりました。会話欄で結果を確認できます",
                                    };
                                    self.toast(text);ctx.request_repaint();
                                },
                                "seek" | "focus" => {
                                    self.pause_at_displayed();
                                    self.t = action["t"].as_f64().unwrap_or(self.t).clamp(0.0, self.dur);
                                    if action["kind"] == "focus" { self.assistant.focus = Some(action.clone()); }
                                    self.push_req(false);
                                    ctx.request_repaint();
                                    self.assistant.reply(id, serde_json::json!({"ok": true}));
                                },
                                _ => self.assistant.reply(id, serde_json::json!({"ok": false, "error": "未対応の画面操作です"})),
                            }
                        } else { self.assistant.reply(id, serde_json::json!({"ok": false, "error": "開いている動画が変わりました"})); }
                    }
                },
                _ if command.starts_with("open:") && self.save_at.is_none() => self.open_content(&command[5..]),
                _ => {},
            }
        }
    }

    fn publish_editor_state(&mut self) {
        if self.state_pub_at.elapsed().as_millis() < 500 {
            return;
        }
        self.state_pub_at = Instant::now();
        let cid = self.content_id();
        let sel: Vec<serde_json::Value> = self
            .selected
            .iter()
            .filter_map(|id| {
                self.doc.seq.tracks.iter().enumerate().find_map(|(ti, tr)| {
                    tr.clips.iter().find(|c| &c.id == id).map(|c| {
                        serde_json::json!({
                            "id": c.id, "lane": ti, "timeline_start": c.timeline_start,
                            "timeline_end": c.timeline_end,
                            "text": c.text, "asset_id": c.asset_id,
                            "region": c.region.is_some(),
                        })
                    })
                })
            })
            .collect();
        let in_editor = self.screen == Screen::Editor;
        let state = serde_json::json!({
            "room_id": self.room_id(),
            // ライブラリ画面では何も開いていない（raw[0] の id は意味を持たない）
            "content_id": if in_editor { cid.clone() } else { String::new() },
            "playhead": (self.displayed_t() * 1000.0).round() / 1000.0,
            "playing": self.playing,
            "duration": self.dur,
            "transport_button": self.transport_button.map(|r| serde_json::json!({"x":r.center().x,"y":r.center().y})),
            "audio_unavailable": self.shared.audio_unavailable.load(Ordering::Relaxed),
            "production_label": self.assistant.production_label,
            "pixels_per_second": self.pps,
            "scroll_x": self.scroll_x,
            "selected": sel,
            "editor": if self.screen == Screen::Editor { "editor" } else { "library" },
            "build": env!("NATIVE_BUILD_TAG"),
        });
        let body = state.to_string();
        // 再生中は playhead が毎回変わるので、書くのは秒精度で丸めた指紋が変わった時だけ
        let fp = format!("{cid}|{:.1}|{}|{}", self.displayed_t(), self.playing, sel.len());
        // 変化が無くても 20 秒ごとに書く（ハートビート）: 読む側は mtime で
        // 「エディタが生きているか」を判定するため
        let heartbeat = self.state_pub_written.elapsed().as_secs() >= 20;
        if !heartbeat {
            if fp == self.state_pub_last && self.playing {
                return;
            }
            if body == self.state_pub_last {
                return;
            }
        }
        self.state_pub_written = Instant::now();
        self.state_pub_last = if self.playing { fp } else { body.clone() };
        let path = format!("{}/editor_state.json", self.doc.asset_dir);
        let tmp = format!("{path}.tmp");
        if std::fs::write(&tmp, body).is_ok() {
            let _ = std::fs::rename(&tmp, &path);
        }
    }

    fn open_content(&mut self, content_id: &str) {
        self.open_content_impl(content_id, true);
    }

    fn open_content_impl(&mut self, content_id: &str, publish: bool) {
        self.assistant.pointer = serde_json::Value::Null;
        self.assistant.focus = None;
        self.assistant.selection = None;
        self.assistant.targets.clear();
        let path = format!("{}/contents.json", self.doc.asset_dir);
        let Ok(txt) = std::fs::read_to_string(&path) else { return };
        let Ok(mut raw) = serde_json::from_str::<serde_json::Value>(&txt) else { return };
        // いまディスクから読んだ内容が新しい基準：外部更新検出の指紋も更新する
        // （生成のライブ反映で再オープンした後、保存が永久にブロックされないように）
        let disk_fp = serde_json::to_string(&raw).unwrap_or_default();
        // 生成中(status=running)のコンテンツを開いたら、経路を問わずライブ表示
        // ＋編集ロックに入る（ライブラリから手動で開いた場合も同じ体験にする）
        let open_status = raw
            .as_array()
            .and_then(|arr| arr.iter().find(|c| c.get("id").and_then(|v| v.as_str()) == Some(content_id)))
            .and_then(|c| c.get("status"))
            .and_then(|s| s.as_str())
            .map(|s| s.to_string());
        if let Some(arr) = raw.as_array_mut() {
            if let Some(idx) = arr.iter().position(|c| c.get("id").and_then(|v| v.as_str()) == Some(content_id)) {
                let c = arr.remove(idx);
                arr.insert(0, c);
            }
        }
        edits::seq_swap_in(&mut raw);
        if let Ok(nd) = model::Doc::from_raw(raw, &self.doc.contents_path, &self.doc.asset_dir) {
            let nd = Arc::new(nd);
            self.disk_fingerprint = disk_fp;
            self.generating_content = match open_status.as_deref() {
                Some("running") => Some(content_id.to_string()),
                // 開始直後はジョブがまだ status を running に切り替えていない
                // （既定 draft）。自動遷移で既に生成中と分かっている場合は維持する
                Some("draft") if self.generating_content.as_deref() == Some(content_id) => {
                    Some(content_id.to_string())
                }
                _ => None,
            };
            self.doc = nd.clone();
            *self.shared.doc.lock().unwrap() = nd;
            self.dur = self.doc.duration();
            self.t = 0.0;
            self.playing = false;
            self.selected.clear();
            self.undo.clear();
            self.redo.clear();
            self.pop_states.clear();
            self.screen = Screen::Editor;
            if publish { self.push_req(false); }
            self.migrate_legacy_freezes();
            self.remember_disk_mtime();
        }
    }

    /// "ダンに指示": non-destructive dan_revise on the open content. Reuses the library
    /// generation machinery (gen_content + gen_job + job_poll) — on done the content
    /// auto-reloads in the editor.
    fn start_revision(&mut self) {
        let note = self.revise_text.trim().to_string();
        if note.is_empty() || self.lib.started {
            return;
        }
        let cid = self.content_id();
        let room = self.room_id();
        let path = format!("{}/contents.json", self.doc.asset_dir);
        let Ok(txt) = std::fs::read_to_string(&path) else {
            self.toast("contents.json が読めません");
            return;
        };
        let Ok(raw) = serde_json::from_str::<serde_json::Value>(&txt) else { return };
        let empty: Vec<serde_json::Value> = Vec::new();
        let arr = raw.as_array().unwrap_or(&empty);
        let Some(content) = arr
            .iter()
            .find(|c| c.get("id").and_then(|v| v.as_str()) == Some(cid.as_str()))
        else {
            self.toast("コンテンツが見つかりません");
            return;
        };
        let timeline = content.get("timeline").cloned().unwrap_or(serde_json::json!({}));
        let asset_ids = content.get("asset_ids").cloned().unwrap_or(serde_json::json!([]));
        let id_list: Vec<String> = asset_ids
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();
        let source_assets: Vec<serde_json::Value> = self
            .lib
            .assets
            .iter()
            .filter(|a| {
                a.get("id")
                    .and_then(|v| v.as_str())
                    .map(|id| id_list.iter().any(|x| x == id))
                    .unwrap_or(false)
            })
            .cloned()
            .collect();
        let mut tl = timeline.clone();
        if let Some(o) = tl.as_object_mut() {
            o.insert("format".into(), content.get("format").cloned().unwrap_or(serde_json::json!("9:16")));
            o.insert("source_asset_ids".into(), asset_ids.clone());
        }
        let body = serde_json::json!({
            "room_id": room,
            "content_id": cid,
            "instruction": {
                "mode": "dan_revise",
                "content_id": cid,
                "content_title": content.get("title").cloned().unwrap_or_default(),
                "asset_ids": asset_ids,
                "source_assets": source_assets,
                "brief": timeline.get("brief").cloned().unwrap_or(serde_json::json!("")),
                "revision_text": note,
                // 対象の明示: 選択中クリップ（この指示の主語）
                "selected_clips": serde_json::Value::Array(
                    self.doc
                        .seq
                        .tracks
                        .iter()
                        .flat_map(|tr| tr.clips.iter().map(move |c| (tr.kind.clone(), c)))
                        .filter(|(_, c)| self.selected.contains(&c.id))
                        .map(|(lane, c)| {
                            serde_json::json!({
                                "id": c.id,
                                "lane": lane,
                                "timeline_start": c.timeline_start,
                                "timeline_end": c.timeline_end,
                                "text": c.text,
                                "asset": c.asset_id.as_ref().and_then(|a| self.doc.asset_names.get(a)),
                            })
                        })
                        .collect(),
                ),
                // 指示クリップ(style=note): クリップの頭〜尻=時間範囲・矩形=場所
                "revision_regions": serde_json::Value::Array(
                    self.doc
                        .seq
                        .tracks
                        .iter()
                        .flat_map(|tr| tr.clips.iter())
                        .filter(|c| c.style.as_ref().and_then(|v| v.as_str()) == Some("note"))
                        .filter_map(|c| {
                            let (rx, ry, rw, rh) = c.region_xywh()?;
                            Some(serde_json::json!({
                                "start": c.timeline_start,
                                "end": c.timeline_end,
                                "data": {"x": rx, "y": ry, "width": rw, "height": rh},
                                "note": "ユーザーがタイムラインに置いた指示クリップの範囲",
                            }))
                        })
                        .collect(),
                ),
                "workflow_preset": timeline.get("workflow_preset").cloned().unwrap_or(serde_json::json!("video_ugc")),
                "timeline": tl,
            },
        });
        self.lib.gen_content = Some(cid);
        self.lib.gen_job = None;
        self.lib.error = None;
        self.lib.started = true;
        self.lib.events = vec!["ダンに指示を送っています…".into()];
        self.lib_post("gen_job", "/api/v1/production-assets/jobs".into(), body);
        // 指示クリップは送信で消費される（範囲はジョブに引き渡し済み）
        let note_ids: Vec<String> = self
            .doc
            .seq
            .tracks
            .iter()
            .flat_map(|tr| tr.clips.iter())
            .filter(|c| c.style.as_ref().and_then(|v| v.as_str()) == Some("note"))
            .map(|c| c.id.clone())
            .collect();
        if !note_ids.is_empty() {
            self.apply_edit(true, move |raw| edits::delete_clips(raw, &note_ids));
            self.push_req(false);
        }
    }

    fn start_generation(&mut self) {
        let room = self.room_id();
        // 旧「作りたいもの」プリセットは実体が「アスペクト比＋定型ブリーフ文」
        // だけだった（workflow_preset はバックエンドで未参照）ので廃止。
        // ブリーフ空のときだけ無難な既定指示を入れる。
        let brief = if self.lib.brief.trim().is_empty() {
            "テンポ良く無音や間をカットして、テロップを付けた動画にしてください。".to_string()
        } else {
            self.lib.brief.clone()
        };
        let pname = "video";
        let title = if self.lib.title.trim().is_empty() {
            format!("動画 {}", self.lib.contents.len() + 1)
        } else {
            self.lib.title.clone()
        };
        let assets: Vec<serde_json::Value> = self
            .lib
            .assets
            .iter()
            .filter(|a| {
                a.get("id")
                    .and_then(|v| v.as_str())
                    .map(|id| self.lib.selected_assets.iter().any(|s| s == id))
                    .unwrap_or(false)
            })
            .cloned()
            .collect();
        let asset_ids: Vec<String> = assets
            .iter()
            .filter_map(|a| a.get("id").and_then(|v| v.as_str()).map(|s| s.to_string()))
            .collect();
        let fmt = self.lib.format.clone();
        let timeline = serde_json::json!({
            "brief": brief, "workflow_preset": pname, "format": fmt,
            "source_asset_ids": asset_ids, "annotations": [],
        });
        self.lib.started = true;
        self.lib.error = None;
        self.lib.events.clear();
        let body = serde_json::json!({
            "room_id": room, "title": title, "format": fmt,
            "asset_ids": asset_ids, "timeline": timeline,
        });
        // content is created first; the dan_plan job is kicked when its id comes back
        self.lib_post("gen_content", "/api/v1/production-assets/contents".into(), body);
        // stash what the job needs
        self.lib.gen_content = None;
        self.lib.gen_job = None;
        let stash = serde_json::json!({
            "brief": brief, "workflow_preset": pname, "format": fmt,
            "asset_ids": asset_ids, "source_assets": assets, "timeline": timeline, "title": title,
        });
        self.lib.events.push("コンテンツを作成しています…".into());
        self.lib_gen_stash = Some(stash);
    }

    /// Create an editable, source-less content and let the backend Higgsfield job fill
    /// it with the first generated asset/clip. This is the native app's real entry point
    /// for "AIで新しい動画を作る".
    fn start_ai_video(&mut self) {
        if self.lib.started || self.lib.brief.trim().is_empty() {
            return;
        }
        let room = self.room_id();
        let title = if self.lib.title.trim().is_empty() {
            format!("AI動画 {}", self.lib.contents.len() + 1)
        } else { self.lib.title.clone() };
        let format = if self.lib.format == "4:5" { "9:16".to_string() } else { self.lib.format.clone() };
        let prompt = self.lib.brief.clone();
        // Selection is reference material for the AI (logo/photo/video), not a mode switch.
        let reference_asset_ids: Vec<String> = self.lib.selected_assets.clone();
        let timeline = serde_json::json!({
            "brief": prompt, "format": format, "source_asset_ids": reference_asset_ids, "annotations": [],
            "sequence": { "format": format, "duration": 0, "tracks": [] },
        });
        self.lib.started = true;
        self.lib.error = None;
        self.lib.events = vec!["AI動画の編集プロジェクトを作成しています…".into()];
        self.lib.gen_content = None;
        self.lib.gen_job = None;
        self.lib_post("gen_content", "/api/v1/production-assets/contents".into(), serde_json::json!({
            "room_id": room, "title": title, "format": format, "asset_ids": reference_asset_ids, "timeline": timeline,
        }));
        self.lib_gen_stash = Some(serde_json::json!({
            "mode": "higgsfield_generate", "prompt": prompt, "model": self.lib.ai_model,
            "duration": self.lib.ai_duration, "aspect_ratio": format, "timeline": timeline, "title": title,
            "reference_asset_ids": reference_asset_ids,
        }));
    }

    fn content_id(&self) -> String {
        self.doc
            .raw
            .get(0)
            .and_then(|r| r.get("id"))
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .to_string()
    }

    /// Press 1 of the export flow: open the settings dialog with a remembered
    /// destination folder and a title+timestamp default filename.
    fn open_export_dialog(&mut self) {
        let memo = format!("{}/.export_dir.txt", self.doc.asset_dir);
        let dir = std::fs::read_to_string(&memo)
            .ok()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty() && std::path::Path::new(s).is_dir())
            .unwrap_or_else(|| {
                std::env::var("USERPROFILE")
                    .map(|u| format!("{u}\\Videos"))
                    .unwrap_or_else(|_| "C:\\".into())
            });
        let title: String = self
            .doc
            .raw
            .get(0)
            .and_then(|c| c.get("title"))
            .and_then(|t| t.as_str())
            .unwrap_or("動画")
            .chars()
            .filter(|c| !"\\/:*?\"<>|".contains(*c))
            .take(40)
            .collect();
        let title = if title.trim().is_empty() { "動画".to_string() } else { title };
        self.export_dest = format!("{dir}\\{title}_{}.mp4", jst_timestamp_compact());
        // サブタイムライン編集中に書き出しを開いたら、既定でその区間だけを書き出す
        self.export_use_sub = self.on_sub_tab() && !self.sub_ranges().is_empty();
        self.export_dialog_open = true;
    }

    /// サブタブを開いているか。タブが役割を決める: メイン=I/Oで青い単一書き出し
    /// 範囲、サブ=I/Oで緑の飛び飛び区間＋区間だけ再生（モードボタンは廃止）。
    fn on_sub_tab(&self) -> bool {
        self.active_seq_id() != "main"
    }

    /// 今開いているシーケンスタブのid（"main" またはサブid）。
    fn active_seq_id(&self) -> String {
        self.doc
            .raw
            .get(0)
            .and_then(|c| c.pointer("/timeline/active_seq"))
            .and_then(|v| v.as_str())
            .unwrap_or("main")
            .to_string()
    }

    /// サブタブの一覧 (id, 表示名)。順序は timeline.seq_order。
    fn seq_tabs(&self) -> Vec<(String, String)> {
        let tl = self.doc.raw.get(0).and_then(|c| c.get("timeline"));
        let order: Vec<String> = tl
            .and_then(|t| t.get("seq_order"))
            .and_then(|v| v.as_array())
            .map(|a| a.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect())
            .unwrap_or_default();
        let names = tl.and_then(|t| t.get("seq_names"));
        order
            .into_iter()
            .map(|id| {
                let name = names
                    .and_then(|n| n.get(&id))
                    .and_then(|v| v.as_str())
                    .unwrap_or("サブ")
                    .to_string();
                (id, name)
            })
            .collect()
    }

    /// シーケンスタブ切替。sequence スロットの中身を入れ替えるだけなので、
    /// 既存の編集・描画・保存コードは何も知らなくてよい。undo履歴はタブ間で
    /// 混ぜない（切替時にクリア）。
    fn switch_seq(&mut self, target: &str) {
        if self.is_generating_open() {
            self.toast("🎬 ダンが制作中です。完成後に切り替えられます");
            return;
        }
        let mut raw = self.doc.raw.clone();
        {
            let Some(tl) = raw
                .get_mut(0)
                .and_then(|c| c.get_mut("timeline"))
                .and_then(|t| t.as_object_mut())
            else {
                return;
            };
            let active = tl.get("active_seq").and_then(|v| v.as_str()).unwrap_or("main").to_string();
            if active == target {
                return;
            }
            // 対象を先に取り出す（無ければ何もしない）
            let next = if target == "main" {
                tl.remove("main_seq")
            } else {
                tl.get_mut("subseqs").and_then(|s| s.as_object_mut()).and_then(|s| s.remove(target))
            };
            let Some(next) = next else {
                return;
            };
            // 今の sequence を退避してから入れ替え
            if let Some(cur) = tl.insert("sequence".into(), next) {
                if active == "main" {
                    tl.insert("main_seq".into(), cur);
                } else if let Some(s) = tl
                    .entry("subseqs")
                    .or_insert_with(|| serde_json::json!({}))
                    .as_object_mut()
                {
                    s.insert(active, cur);
                }
            }
            tl.insert("active_seq".into(), serde_json::Value::from(target));
        }
        self.undo.clear();
        self.redo.clear();
        self.pending_undo = None;
        self.selected.clear();
        self.sub_in = None;
        self.sub_edge_drag = None;
        self.playing = false;
        self.resume_pending = None;
        self.restore(raw);
        self.t = self.t.min(self.dur);
        self.push_req(false);
    }

    /// 今開いているタイムラインを複製してサブタブを作り、そこへ切り替える。
    /// 素材はID参照の共有なので複製されるのはJSONのクリップ並びだけ＝軽い。
    fn create_sub(&mut self) {
        if self.is_generating_open() {
            self.toast("🎬 ダンが制作中です。完成後に作成できます");
            return;
        }
        let mut raw = self.doc.raw.clone();
        let new_id = format!("sub{}", lane_salt());
        {
            let Some(tl) = raw
                .get_mut(0)
                .and_then(|c| c.get_mut("timeline"))
                .and_then(|t| t.as_object_mut())
            else {
                return;
            };
            let seq = tl.get("sequence").cloned().unwrap_or_else(|| serde_json::json!({}));
            let n = tl.get("seq_order").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0) + 1;
            if let Some(s) = tl
                .entry("subseqs")
                .or_insert_with(|| serde_json::json!({}))
                .as_object_mut()
            {
                s.insert(new_id.clone(), seq);
            }
            if let Some(a) = tl
                .entry("seq_order")
                .or_insert_with(|| serde_json::json!([]))
                .as_array_mut()
            {
                a.push(serde_json::Value::from(new_id.clone()));
            }
            if let Some(s) = tl
                .entry("seq_names")
                .or_insert_with(|| serde_json::json!({}))
                .as_object_mut()
            {
                s.insert(new_id.clone(), serde_json::Value::from(format!("サブ{n}")));
            }
        }
        self.restore(raw);
        self.switch_seq(&new_id);
        self.toast("サブを作成: 自由に編集できます（メインは変わりません）。I→Oで緑の区間を組めば区間だけ再生・書き出し");
    }

    /// サブタブ削除（右クリック2回で確定済み）。アクティブならメインへ戻ってから。
    fn delete_sub(&mut self, id: &str) {
        if self.active_seq_id() == id {
            self.switch_seq("main");
        }
        let mut raw = self.doc.raw.clone();
        {
            let Some(tl) = raw
                .get_mut(0)
                .and_then(|c| c.get_mut("timeline"))
                .and_then(|t| t.as_object_mut())
            else {
                return;
            };
            if let Some(s) = tl.get_mut("subseqs").and_then(|s| s.as_object_mut()) {
                s.remove(id);
            }
            if let Some(s) = tl.get_mut("seq_names").and_then(|s| s.as_object_mut()) {
                s.remove(id);
            }
            if let Some(a) = tl.get_mut("seq_order").and_then(|v| v.as_array_mut()) {
                a.retain(|v| v.as_str() != Some(id));
            }
        }
        self.restore(raw);
        self.toast("サブを削除しました");
    }

    /// サブタイムラインの再生区間（開始順ソート・マージ済み）。
    /// contents.json の sequence.subtimeline.ranges に永続化されている。
    fn sub_ranges(&self) -> Vec<(f64, f64)> {
        let v: Vec<(f64, f64)> = self
            .doc
            .raw
            .get(0)
            .and_then(|c| c.pointer("/timeline/sequence/subtimeline/ranges"))
            .and_then(|r| r.as_array())
            .map(|a| {
                a.iter()
                    .filter_map(|r| {
                        let x = r.as_array()?;
                        let (a, b) = (x.first()?.as_f64()?, x.get(1)?.as_f64()?);
                        (b > a && a >= 0.0).then_some((a, b))
                    })
                    .collect()
            })
            .unwrap_or_default();
        merge_time_ranges(v)
    }

    /// サブタイムラインへ区間を追加して保存（undo対象）。
    fn sub_add_range(&mut self, a: f64, b: f64) {
        let mut rs = self.sub_ranges();
        rs.push((a.min(b), a.max(b)));
        let rs = merge_time_ranges(rs);
        self.apply_edit(true, move |raw| edits::set_subtimeline_ranges(raw, &rs));
    }

    fn start_export(&mut self) {
        // mode "export" renders the CURRENT timeline server-side (the sequence rides in
        // the instruction — what you see is exactly what gets rendered).
        // sequence スロットには「開いているタブ」が入っている＝タブごとの書き出しが
        // 自動で成立。退避中の main_seq/subseqs は送らない（payload節約）
        let tl = self.doc.raw.get(0).and_then(|r| r.get("timeline"));
        let mut timeline = serde_json::json!({
            "sequence": tl.and_then(|t| t.get("sequence")).cloned().unwrap_or_else(|| serde_json::json!({})),
        });
        if let Some(fmt) = tl.and_then(|t| t.get("format")).cloned() {
            timeline["format"] = fmt;
        }
        let mut instruction = serde_json::json!({"mode": "export", "timeline": timeline});
        let sel_ranges = if self.export_use_sub { self.sub_ranges() } else { Vec::new() };
        if !sel_ranges.is_empty() {
            // サブタイムラインの区間だけを（飛び飛びでも）繋げて1本に書き出す
            instruction["export_ranges"] =
                serde_json::json!(sel_ranges.iter().map(|(a, b)| vec![*a, *b]).collect::<Vec<_>>());
        } else if let Some((ra, rb)) = (!self.on_sub_tab()).then_some(self.export_range).flatten() {
            // in/out render range (DaVinci-style, メインタブ専用): backend forwards it
            // to the native exporter as start/end; unset = whole content
            instruction["export_range"] = serde_json::json!([ra, rb]);
        }
        if self.export_dest.trim().to_ascii_lowercase().ends_with(".mp4") {
            // user-confirmed destination from the export dialog: backend copies the
            // finished file here (asset registration still happens as before)
            instruction["output_copy_path"] = serde_json::json!(self.export_dest.trim());
        }
        let payload = serde_json::json!({
            "room_id": self.room_id(),
            "content_id": self.content_id(),
            "instruction": instruction,
        })
        .to_string();
        self.export_status = Some("書き出しを開始しています…".into());
        self.export_progress = None;
        self.export_done_path = None;
        let sink = self.export_result.clone();
        std::thread::spawn(move || {
            let res = http_local("POST", "/api/v1/production-assets/jobs", Some(&payload))
                .and_then(|t| Ok(serde_json::from_str::<serde_json::Value>(&t)?))
                .map_err(|e| format!("{e:#}"));
            *sink.lock().unwrap() = Some(res);
        });
    }

    fn poll_export(&mut self) {
        let taken = self.export_result.lock().unwrap().take();
        if let Some(res) = taken {
            match res {
                Ok(v) => {
                    if !self.absorb_export_poll(&v) {
                        // not a poll payload -> job-creation response
                        self.export_job = v.get("id").and_then(|x| x.as_str()).map(|s| s.to_string());
                        self.export_status = Some("書き出し中…".into());
                    }
                }
                Err(e) => {
                    if self.export_job.is_some() {
                        // ONE poll round-trip failed — the render on the server is
                        // unaffected. Keep the job and keep polling; showing this as
                        // "書き出しエラー" (and abandoning the poll) misread a busy
                        // moment as a failed export for the user.
                        self.export_status = Some("サーバー応答待ち…（書き出しは継続中・自動で再確認します）".into());
                        eprintln!("export poll transport error (retrying): {e}");
                    } else {
                        self.export_status = Some(format!("書き出しエラー: {e}"));
                        eprintln!("export failed: {e}");
                    }
                }
            }
        }
        let Some(job_id) = self.export_job.clone() else { return };
        if self.export_poll.elapsed().as_millis() < 2000 {
            return;
        }
        self.export_poll = Instant::now();
        let path = format!(
            "/api/v1/production-assets/jobs?room_id={}&content_id={}",
            self.room_id(),
            self.content_id()
        );
        let ev_path = format!(
            "/api/v1/production-assets/jobs/{}/events?room_id={}",
            job_id,
            self.room_id()
        );
        let sink = self.export_result.clone();
        std::thread::spawn(move || {
            let events = http_local("GET", &ev_path, None)
                .ok()
                .and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok())
                .unwrap_or(serde_json::json!([]));
            let res = http_local("GET", &path, None)
                .and_then(|t| Ok(serde_json::from_str::<serde_json::Value>(&t)?))
                .map(|list| serde_json::json!({"poll": list, "job": job_id, "events": events}))
                .map_err(|e| format!("{e:#}"));
            *sink.lock().unwrap() = Some(res);
        });
    }

    fn absorb_export_poll(&mut self, v: &serde_json::Value) -> bool {
        let (Some(list), Some(job_id)) = (v.get("poll"), v.get("job").and_then(|x| x.as_str())) else {
            return false;
        };
        let Some(job) = list.as_array().and_then(|a| a.iter().find(|j| j.get("id").and_then(|x| x.as_str()) == Some(job_id))) else {
            return true;
        };
        match job.get("status").and_then(|s| s.as_str()).unwrap_or("") {
            "done" => {
                // prefer the user's chosen destination (dialog) over the internal job path
                let res = job.get("result");
                let out = res
                    .and_then(|r| r.get("user_output_path").or_else(|| r.get("output_path")))
                    .and_then(|p| p.as_str())
                    .unwrap_or("")
                    .to_string();
                self.export_job = None;
                self.export_progress = None;
                self.export_status = Some("書き出し完了".into());
                self.export_done_path = Some(out.clone());
                self.toast(&format!("書き出し完了 → {out}"));
            }
            "failed" => {
                let err = job.get("error").and_then(|e| e.as_str()).unwrap_or("不明なエラー");
                self.export_job = None;
                self.export_progress = None;
                self.export_status = Some(format!("書き出し失敗: {err}"));
            }
            st => {
                // live phase text = the newest non-error server event; frame=N/M in it
                // drives the progress bar (None during the finishing/OCR phase)
                let ev_text = v
                    .get("events")
                    .and_then(|e| e.as_array())
                    .and_then(|a| {
                        a.iter().rev().find_map(|ev| {
                            let txt = ev.get("text")?.as_str()?;
                            (ev.get("type").and_then(|x| x.as_str()) != Some("error"))
                                .then(|| txt.to_string())
                        })
                    });
                if let Some(txt) = &ev_text {
                    if let Some(frac) = txt.split("frame=").nth(1).and_then(|s| {
                        let (n, m) = s.split_whitespace().next()?.split_once('/')?;
                        let (a, b) = (n.parse::<f64>().ok()?, m.parse::<f64>().ok()?);
                        (b > 0.0).then(|| (a / b) as f32)
                    }) {
                        self.export_progress = Some(frac);
                    } else if txt.contains("ぼかし確認中") {
                        self.export_progress = None; // indeterminate finishing pass
                    }
                }
                self.export_status = Some(ev_text.unwrap_or_else(|| {
                    format!("書き出し{}…", if st == "queued" { "待機中" } else { "中" })
                }));
            }
        }
        true
    }

    /// Preview inspector: the selected clip's display box is drawn over the preview and
    /// can be MOVED (drag inside) or RESIZED (corner handles, aspect kept) directly.
    /// Current region rectangle of a clip (canvas fractions).
    fn region_of(&self, id: &str) -> (f64, f64, f64, f64) {
        self.doc
            .seq
            .tracks
            .iter()
            .flat_map(|tr| tr.clips.iter())
            .find(|c| c.id == id)
            .and_then(|c| c.region_at(self.t))
            .unwrap_or((0.25, 0.25, 0.5, 0.5))
    }

    /// On-screen box (canvas fractions) of a caption from its cache PNG: alpha bbox of
    /// the default-anchor render mapped through the live style x/y/fontSize — exactly
    /// how the compositor places the same PNG, so the box matches the pixels. None
    /// until the PNG lands (caption_cache_pass renders it in the background).
    fn caption_png_box(&mut self, c: &model::Clip) -> Option<(f64, f64, f64, f64)> {
        let text = c.text.clone().unwrap_or_default();
        if text.trim().is_empty() {
            return None;
        }
        let style = c.style.clone().unwrap_or_else(|| serde_json::json!({}));
        let key = caption_cache_key(c, &text, &style);
        let font = caption_style_num(&style, "fontSize", 1.0).max(0.05);
        if let Some(bbox) = self.caption_png_boxes.get(&key) {
            return Some(c.caption_box_at(self.displayed_t(), caption_runtime_dst(c, *bbox, font)));
        }
        let png = std::path::Path::new(&self.doc.asset_dir)
            .join("caption-cache")
            .join(format!("{key}.png"));
        let img = image::open(&png).ok()?.to_rgba8();
        let (w, h) = img.dimensions();
        let (_, _, _, (bx, by, bw, bh)) = crop_alpha_rgba(&img)?;
        let bbox = (
            bx as f64 / w as f64,
            by as f64 / h as f64,
            bw as f64 / w as f64,
            bh as f64 / h as f64,
        );
        if self.caption_png_boxes.len() > 256 {
            self.caption_png_boxes.clear();
        }
        self.caption_png_boxes.insert(key, bbox);
        Some(c.caption_box_at(self.displayed_t(), caption_runtime_dst(c, bbox, font)))
    }

    fn assistant_preview(&mut self, ui: &mut egui::Ui, resp: &egui::Response, vid: egui::Rect) -> bool {
        self.assistant.viewport = serde_json::json!({"x":vid.left(),"y":vid.top(),"w":vid.width(),"h":vid.height(),"scale":ui.ctx().pixels_per_point()});
        let t = self.displayed_grid_t();
        let clips: Vec<_> = self.doc.seq.tracks.iter().filter(|tr| tr.kind != "audio").flat_map(|tr| tr.clips.iter())
            .filter(|c| t >= c.timeline_start && t < c.timeline_end).cloned().collect();
        let mut targets = Vec::new();
        for c in &clips {
            let rect = if let Some(r) = c.region_at(t) { Some(r) }
                else if c.text.is_some() && c.asset_id.is_none() {
                    let live = self.caption_live_boxes.lock().ok().and_then(|m| m.get(&c.id).copied());
                    live.map(|[x,y,w,h]| (x,y,w,h)).or_else(|| self.caption_png_box(c))
                } else if c.asset_id.is_some() { Some((0.0,0.0,1.0,1.0)) } else { None };
            if let Some((x,y,w,h)) = rect {
                targets.push(serde_json::json!({"id":c.id,"text":c.text,"asset_id":c.asset_id,
                    "rect":[x,y,w,h],"start":c.timeline_start,"end":c.timeline_end}));
            }
        }
        self.assistant.targets = targets;
        let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_millis() as u64;
        let pointer = resp.interact_pointer_pos().or_else(|| resp.hover_pos()).filter(|p| vid.contains(*p));
        if let Some(pt) = pointer {
            if now.saturating_sub(self.assistant.pointer["at_ms"].as_u64().unwrap_or(0)) >= 80 {
                let x = ((pt.x-vid.left())/vid.width()) as f64;
                let y = ((pt.y-vid.top())/vid.height()) as f64;
                let mut trail = self.assistant.pointer["trail"].as_array().cloned().unwrap_or_default();
                trail.retain(|v| now.saturating_sub(v["at_ms"].as_u64().unwrap_or(0)) < 5000);
                trail.push(serde_json::json!({"x":x,"y":y,"t":t,"at_ms":now}));
                self.assistant.pointer = serde_json::json!({"x":x,"y":y,"t":t,"at_ms":now,"trail":trail});
            }
        }
        let p = ui.painter_at(vid);
        if let Some(f) = &self.assistant.focus {
            if let Some(r) = f["rect"].as_array().filter(|r| r.len()==4) {
                let x=r[0].as_f64().unwrap_or(0.0) as f32; let y=r[1].as_f64().unwrap_or(0.0) as f32;
                let w=r[2].as_f64().unwrap_or(0.0) as f32; let h=r[3].as_f64().unwrap_or(0.0) as f32;
                let rr=egui::Rect::from_min_size(vid.min+egui::vec2(x*vid.width(),y*vid.height()),egui::vec2(w*vid.width(),h*vid.height()));
                let col=egui::Color32::from_rgb(100,210,255);
                p.rect_filled(rr,3.0,col.gamma_multiply(0.12)); p.rect_stroke(rr,3.0,egui::Stroke::new(2.0,col));
                p.text(rr.left_top()+egui::vec2(4.0,4.0),egui::Align2::LEFT_TOP,f["label"].as_str().unwrap_or("この辺り？"),egui::FontId::proportional(14.0),col);
            }
        }
        if !self.assistant.pick { return false; }
        ui.ctx().set_cursor_icon(egui::CursorIcon::Crosshair);
        p.text(vid.center_top()+egui::vec2(0.0,12.0),egui::Align2::CENTER_TOP,"指示する場所を囲んでください（Escで終了）",egui::FontId::proportional(14.0),UI_ACCENT);
        if ui.input(|i| i.key_pressed(egui::Key::Escape)) { self.assistant.pick=false; self.assistant.drag=None; return true; }
        if resp.drag_started() { self.assistant.drag=pointer; }
        if let (Some(a),Some(b))=(self.assistant.drag,pointer) {
            let r=egui::Rect::from_two_pos(a,b).intersect(vid);
            p.rect_stroke(r,0.0,egui::Stroke::new(2.0,UI_ACCENT));
            if resp.drag_stopped() {
                self.assistant.drag=None; self.assistant.pick=false;
                if r.width()>3.0 && r.height()>3.0 {
                    let x=((r.left()-vid.left())/vid.width()) as f64; let y=((r.top()-vid.top())/vid.height()) as f64;
                    let w=(r.width()/vid.width()) as f64; let h=(r.height()/vid.height()) as f64;
                    let mut hits: Vec<_>=self.assistant.targets.iter().filter(|v| {
                        let b=&v["rect"]; let bx=b[0].as_f64().unwrap_or(0.0); let by=b[1].as_f64().unwrap_or(0.0);
                        bx<x+w && bx+b[2].as_f64().unwrap_or(0.0)>x && by<y+h && by+b[3].as_f64().unwrap_or(0.0)>y
                    }).cloned().collect();
                    if hits.iter().any(|v| v["text"].is_string()) { hits.retain(|v| v["text"].is_string()); }
                    self.selected=hits.iter().filter_map(|v| v["id"].as_str().map(str::to_string)).collect();
                    self.assistant.selection=Some(serde_json::json!({"rect":[x,y,w,h],"t":t,"targets":hits}));
                    self.assistant.focus=Some(serde_json::json!({"rect":[x,y,w,h],"label":"選択した範囲"}));
                    self.pause_at_displayed();
                }
            }
        }
        true
    }

    fn preview_inspector(&mut self, ui: &mut egui::Ui, resp: &egui::Response) {
        let img = resp.rect;
        // selected region-effect clip while the playhead is inside its range: a plain
        // rectangle around the blur area. Mapped to the VIDEO rect (canvas-aspect fit,
        // centered) — resp.rect is the whole justified panel and drawing into it put
        // the outline outside the picture (same letterbox trap as the caption PNGs).
        let vid = {
            let (cw, ch) = (canvas_w() as f32, canvas_h() as f32);
            let scale = (img.width() / cw).min(img.height() / ch);
            egui::Rect::from_center_size(img.center(), egui::vec2(cw * scale, ch * scale))
        };
        if self.assistant_preview(ui, resp, vid) { return; }
        // The caption WebView is visual-only, so preview gestures arrive through the
        // normal egui response just like every other editor interaction.
        let pointer_pos = resp.interact_pointer_pos().or_else(|| resp.hover_pos());
        let preview_drag_started = resp.drag_started();
        let preview_dragging = resp.dragged();
        let preview_drag_stopped = resp.drag_stopped();
        // The outline follows the frame that is REALLY on screen — its EFFECTIVE time
        // (the base layer's landed frame instant), the same time the blur inside the
        // frame was evaluated at. Request-time (self.t / f.t) differs from it by up to
        // half a frame on VFR sources, which on fast keyed motion reads as "the frame
        // is offset from the blur" (30px+ at their hand-keyed speeds).
        let t_disp = self.displayed_grid_t();
        // (id, rect, baked, blur_track, on_key, rot) — on_key = playhead sits on a position
        // keyframe of this clip (within half a frame)。rot = effect_rot（描画が回る
        // スタイルのみ。枠線/ハンドルも同角度で回して見た目を一致させる）
        let outlines: Vec<(String, (f64, f64, f64, f64), bool, Option<serde_json::Value>, bool, f64)> = self
            .doc
            .seq
            .tracks
            .iter()
            .flat_map(|tr| tr.clips.iter())
            .filter(|c| {
                self.selected.contains(&c.id)
                    && c.region.is_some()
                    && c.asset_id.is_none()
                    && t_disp >= c.timeline_start
                    && t_disp < c.timeline_end
            })
            .filter_map(|c| c.region_at(t_disp).map(|rg| {
                let kts = c.region_key_times();
                let rel = self.keyed_grid_t(c.timeline_start, &kts) - c.timeline_start;
                let on_key = kts.iter().any(|kt| (kt - rel).abs() <= edits::KEY_REPLACE_EPS);
                // 回転が描画に効くスタイル（単色/枠/ぼかし系）だけ枠線も回す
                let style = c.style.as_ref().and_then(|v| v.as_str()).unwrap_or("");
                let rot = if style.contains("mosaic")
                    || matches!(style, "marker" | "spotlight" | "zoom" | "note")
                {
                    0.0
                } else {
                    c.effect_rot.unwrap_or(0.0)
                };
                (
                    c.id.clone(),
                    rg,
                    matches!(self.blur_states.get(&c.id), Some(PopState::Ready)),
                    c.blur_track.clone(),
                    on_key,
                    rot,
                )
            }))
            .collect();
        // --- スポイト: クリックした画面ピクセルの色を拾って適用; owns the pointer ---
        if let Some((target, ids)) = self.eyedrop.clone() {
            ui.ctx().set_cursor_icon(egui::CursorIcon::Crosshair);
            let sampled = screen_pixel_under_cursor();
            let p = ui.painter_at(img);
            p.text(
                egui::pos2(vid.center().x, vid.top() + 14.0),
                egui::Align2::CENTER_CENTER,
                "スポイト: 拾いたい色をクリック（右クリック/Escで中止）",
                egui::FontId::proportional(13.0),
                egui::Color32::from_rgb(120, 220, 255),
            );
            if let (Some(c), Some(pt)) = (sampled, pointer_pos) {
                // live swatch by the cursor — offset so the swatch never covers the
                // pixel being sampled
                let r = egui::Rect::from_min_size(pt + egui::vec2(16.0, 12.0), egui::vec2(46.0, 20.0));
                p.rect_filled(r, 3.0, c);
                p.rect_stroke(r, 3.0, egui::Stroke::new(1.0, egui::Color32::WHITE));
                p.text(
                    r.right_center() + egui::vec2(6.0, 0.0),
                    egui::Align2::LEFT_CENTER,
                    color32_hex(c),
                    egui::FontId::monospace(11.0),
                    egui::Color32::WHITE,
                );
            }
            ui.ctx().request_repaint(); // the swatch follows the cursor live
            if resp.secondary_clicked() || ui.input(|i| i.key_pressed(egui::Key::Escape)) {
                self.eyedrop = None;
                return;
            }
            if resp.clicked() {
                if let Some(c) = sampled {
                    let hex = color32_hex(c);
                    self.remember_caption_fallbacks(&ids);
                    let patch = match target {
                        // a plain color pick must WIN over a leftover gradient
                        0 => serde_json::json!({"color": hex, "gradient": null}),
                        1 => serde_json::json!({"outlineColor": hex}),
                        _ => {
                            // merge_object is shallow: send the FULL bg object with the
                            // new color (current values, or the 四角枠 defaults)
                            let mut bg = self
                                .doc
                                .seq
                                .tracks
                                .iter()
                                .flat_map(|tr| tr.clips.iter())
                                .find(|c| ids.contains(&c.id))
                                .and_then(|c| c.style.as_ref())
                                .and_then(|s| s.get("bg"))
                                .filter(|v| v.is_object())
                                .cloned()
                                .unwrap_or_else(|| {
                                    serde_json::json!({"opacity": 0.62, "radius": 0.2,
                                                        "padX": 0.5, "padY": 0.18})
                                });
                            bg["color"] = serde_json::json!(hex);
                            serde_json::json!({"bg": bg})
                        }
                    };
                    let ids2 = ids.clone();
                    self.apply_edit(true, move |raw| edits::patch_caption_style(raw, &ids2, patch));
                    self.push_req(false);
                    self.toast(&format!("スポイト: {hex} を適用"));
                }
                self.eyedrop = None;
            }
            return;
        }
        // --- 追従修正モード: clicks collect +/- points; owns the pointer entirely ---
        if let Some(cid) = self.corr_mode.clone() {
            let clip = self
                .doc
                .seq
                .tracks
                .iter()
                .flat_map(|tr| tr.clips.iter())
                .find(|c| c.id == cid)
                .cloned();
            let Some(c) = clip else {
                self.corr_mode = None;
                return;
            };
            let inside_time = self.t >= c.timeline_start && self.t < c.timeline_end;
            let baid = c
                .blur_track
                .as_ref()
                .and_then(|bt| bt.get("asset_id"))
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let base = self
                .doc
                .active_video(self.t)
                .0
                .filter(|b| b.asset_id.as_deref() == Some(baid.as_str()))
                .cloned();
            if let (true, Some(b)) = (inside_time, base) {
                let dims = self.doc.asset_dims.get(&baid).copied().unwrap_or((0, 0));
                let bb = effective_box(&self.doc, &b, self.t);
                let src_now = b.src_at(self.t);
                // markers (source -> canvas)
                let p = ui.painter_at(vid);
                for (sx, sy, pos) in &self.corr_points {
                    let cb = compositor::source_box_to_canvas(
                        (canvas_w(), canvas_h()),
                        dims,
                        (bb.x, bb.y, bb.width, bb.height),
                        !b.stretches_to_box(),
                        b.crop_ltrb_at(self.t),
                        (*sx, *sy, 0.0, 0.0),
                    );
                    let cp = egui::pos2(
                        vid.left() + cb.0 as f32 * vid.width(),
                        vid.top() + cb.1 as f32 * vid.height(),
                    );
                    let col = if *pos {
                        egui::Color32::from_rgb(60, 230, 120)
                    } else {
                        egui::Color32::from_rgb(240, 70, 70)
                    };
                    p.circle_stroke(cp, 8.0, egui::Stroke::new(3.0, col));
                    p.circle_filled(cp, 2.5, col);
                }
                p.text(
                    egui::pos2(vid.center().x, vid.top() + 14.0),
                    egui::Align2::CENTER_CENTER,
                    "追従修正: 対象を左クリック＋ / 右クリック−",
                    egui::FontId::proportional(13.0),
                    egui::Color32::from_rgb(60, 230, 120),
                );
                let lclick = resp.clicked();
                let rclick = resp.secondary_clicked();
                if lclick || rclick {
                    if let Some(pt) = pointer_pos {
                        if vid.contains(pt) {
                            // clicks belong to ONE anchor frame; clicking on a different
                            // frame starts the point set over there
                            if self.corr_anchor_src.map(|a| (a - src_now).abs() > 0.05).unwrap_or(false) {
                                self.corr_points.clear();
                                self.toast("別のフレームなので点を打ち直します");
                            }
                            self.corr_anchor_src = Some(src_now);
                            let cx = ((pt.x - vid.left()) / vid.width()) as f64;
                            let cy = ((pt.y - vid.top()) / vid.height()) as f64;
                            let (sx, sy) = compositor::canvas_point_to_source(
                                (canvas_w(), canvas_h()),
                                dims,
                                (bb.x, bb.y, bb.width, bb.height),
                                !b.stretches_to_box(),
                                b.crop_ltrb_at(self.t),
                                (cx, cy),
                            );
                            self.corr_points.push((sx, sy, lclick));
                        }
                    }
                }
            } else {
                ui.painter_at(vid).text(
                    egui::pos2(vid.center().x, vid.top() + 14.0),
                    egui::Align2::CENTER_CENTER,
                    "追従修正: 再生ヘッドをこのぼかしクリップの範囲内に",
                    egui::FontId::proportional(13.0),
                    egui::Color32::from_rgb(255, 170, 60),
                );
            }
            return;
        }
        let mut editable: Vec<(String, egui::Rect, [egui::Pos2; 4], f64)> = Vec::new();
        for (_cid, rg, tracked, bt, on_key, rot) in outlines {
            // while a bake is live, the outline FOLLOWS the tracked object: the mask
            // meta records the object's box per mask frame — look up the box for the
            // frame the preview is showing and map it source -> canvas
            let mut draw_box = rg;
            let mut following = false;
            if tracked {
                if let Some(bt) = bt.as_ref() {
                    let key = bt.get("key").and_then(|v| v.as_str()).unwrap_or("").to_string();
                    let bs = bt.get("bake_start").and_then(|v| v.as_f64()).unwrap_or(0.0);
                    let baid = bt.get("asset_id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                    let meta_path = format!("{}/blur-cache/{}.mask.mp4.meta.json", self.doc.asset_dir, key);
                    let load = || {
                        std::fs::read_to_string(&meta_path)
                            .ok()
                            .and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok())
                            .and_then(|j| j.get("boxes_by_frame").cloned())
                    };
                    let meta = match self.blur_meta_cache.get_mut(&key) {
                        Some((Some(v), _)) => Some(v.clone()),
                        Some((slot @ None, at)) if at.elapsed().as_secs() >= 1 => {
                            *slot = load();
                            if slot.is_none() {
                                eprintln!("BLUROUT meta retry miss key={key}");
                            }
                            *at = Instant::now();
                            slot.clone()
                        }
                        Some((None, _)) => None,
                        None => {
                            let v = load();
                            if v.is_none() {
                                eprintln!("BLUROUT meta first miss key={key} path={meta_path}");
                            }
                            self.blur_meta_cache.insert(key.clone(), (v.clone(), Instant::now()));
                            v
                        }
                    };
                    let base = self
                        .doc
                        .active_video(t_disp)
                        .0
                        .filter(|b| b.asset_id.as_deref() == Some(baid.as_str()));
                    if meta.is_none() || base.is_none() {
                        if self.blur_out_log_at.elapsed().as_secs() >= 1 {
                            self.blur_out_log_at = Instant::now();
                            eprintln!(
                                "BLUROUT fallback: meta={} base={} key={key}",
                                meta.is_some(),
                                base.is_some()
                            );
                        }
                    }
                    if let (Some(bf), Some(b)) = (meta, base) {
                        let fi = ((b.src_at(t_disp) - bs) * 30.0).round() as i64;
                        // nearest recorded frame within ±4 (propagation can skip a few)
                        let hit = (0..=4).find_map(|d| {
                            [fi - d, fi + d].into_iter().find_map(|f| {
                                bf.get(f.to_string()).filter(|v| {
                                    v.as_object().map(|o| !o.is_empty()).unwrap_or(false)
                                })
                            })
                        });
                        if hit.is_none() && self.blur_out_log_at.elapsed().as_secs() >= 1 {
                            self.blur_out_log_at = Instant::now();
                            eprintln!("BLUROUT no box at mask frame {fi} key={key}");
                        }
                        if let Some(objs) = hit.and_then(|v| v.as_object()) {
                            let (mut x0, mut y0, mut x1, mut y1) = (1.0f64, 1.0f64, 0.0f64, 0.0f64);
                            for bx in objs.values() {
                                let g = |i: usize| bx.get(i).and_then(|v| v.as_f64()).unwrap_or(0.0);
                                x0 = x0.min(g(0));
                                y0 = y0.min(g(1));
                                x1 = x1.max(g(0) + g(2));
                                y1 = y1.max(g(1) + g(3));
                            }
                            if x1 > x0 && y1 > y0 {
                                let dims = self.doc.asset_dims.get(&baid).copied().unwrap_or((0, 0));
                                let bb = effective_box(&self.doc, &b, t_disp);
                                draw_box = compositor::source_box_to_canvas(
                                    (canvas_w(), canvas_h()),
                                    dims,
                                    (bb.x, bb.y, bb.width, bb.height),
                                    !b.stretches_to_box(),
                                    b.crop_ltrb_at(t_disp),
                                    (x0, y0, x1 - x0, y1 - y0),
                                );
                                following = true;
                            }
                        }
                    }
                }
            }
            let (x, y, w, h) = draw_box;
            let r = egui::Rect::from_min_size(
                egui::pos2(
                    vid.left() + x as f32 * vid.width(),
                    vid.top() + y as f32 * vid.height(),
                ),
                egui::vec2(w as f32 * vid.width(), h as f32 * vid.height()),
            );
            let col = if following {
                egui::Color32::from_rgb(90, 220, 150)
            } else if on_key {
                // playhead ON a position keyframe: DaVinci-red = "this drag re-writes THIS key"
                egui::Color32::from_rgb(240, 80, 80)
            } else {
                egui::Color32::from_rgb(255, 170, 60)
            };
            let p = ui.painter_at(vid);
            // 回転スタイルは枠線・ハンドルも同角度で回す（見た目の角度を確認できる
            // ように）。回転は描画と同じ「矩形中心・時計回り」。プレビュー枠 vid は
            // キャンバスと同アスペクトなのでスクリーン空間の回転角=描画の回転角。
            let rot_corner = |p0: egui::Pos2| -> egui::Pos2 {
                if rot.abs() < 1e-3 {
                    return p0;
                }
                let (sn, cs) = (rot.to_radians().sin() as f32, rot.to_radians().cos() as f32);
                let ctr = r.center();
                let d = p0 - ctr;
                egui::pos2(ctr.x + cs * d.x - sn * d.y, ctr.y + sn * d.x + cs * d.y)
            };
            // NW, NE, SW, SE（ヒット判定 mode 1..4 と同順）
            let hs4 = [
                rot_corner(r.left_top()),
                rot_corner(r.right_top()),
                rot_corner(r.left_bottom()),
                rot_corner(r.right_bottom()),
            ];
            if rot.abs() < 1e-3 {
                p.rect_stroke(r, 2.0, egui::Stroke::new(2.0, col));
            } else {
                p.add(egui::Shape::closed_line(
                    vec![hs4[0], hs4[1], hs4[3], hs4[2]],
                    egui::Stroke::new(2.0, col),
                ));
            }
            if on_key && !following {
                // small key diamond on the rect's top edge so the state reads at a glance
                let cpt = rot_corner(egui::pos2(r.center().x, r.top()));
                p.add(egui::Shape::convex_polygon(
                    vec![
                        cpt + egui::vec2(0.0, -5.0),
                        cpt + egui::vec2(5.0, 0.0),
                        cpt + egui::vec2(0.0, 5.0),
                        cpt + egui::vec2(-5.0, 0.0),
                    ],
                    col,
                    egui::Stroke::NONE,
                ));
            }
            // the ORANGE (static/anchor) rect is hand-editable: corner handles + body
            // drag. A green following box is the TRACKED object, not the region — its
            // rect is not draggable (解除 first to hand-adjust).
            if !following {
                for c4 in hs4 {
                    p.rect_filled(egui::Rect::from_center_size(c4, egui::vec2(10.0, 10.0)), 1.0, col);
                }
                editable.push((_cid.clone(), r, hs4, rot));
            }
        }
        // --- region rect editing: corners = resize, inside = move (shape preserved) ---
        if preview_drag_started && self.region_drag.is_none() {
            // ヒット判定は「押した瞬間の位置」で行う。egui の drag_started は数px
            // 動いてから発火するため、現在位置だと速いドラッグでハンドル(12pt)を
            // 外れて掴み損ねる（掴んだ後のデルタ基準も press 起点に揃える）
            let press_pt = ui.input(|i| i.pointer.press_origin()).or(pointer_pos);
            if let Some(pt) = press_pt {
                'hit: for (cid, r, hs4, ed_rot) in &editable {
                    // (timeline_start, keys snapshot) of a keyframe-able clip (no AI track)
                    let key_info = self
                        .doc
                        .seq
                        .tracks
                        .iter()
                        .flat_map(|tr| tr.clips.iter())
                        .find(|c| c.id == *cid && c.blur_track.is_none())
                        .map(|c| (c.timeline_start, c.region_keys.clone()));
                    // キーがあるクリップのドラッグは常に「この時点のキーだけ」。
                    // 軌跡ごと平行移動（スナップショット＋オフセットで全キー書き直し）は
                    // Alt+ドラッグの明示操作のみ。キー時刻=表示フレームの格子スロット
                    // (t_disp)。評価と同じ式なので「キーのフレームでキーの値ちょうど」が
                    // 厳密に成立する。
                    // corner hit zones shrink with the rect so a small rect keeps a
                    // grabbable BODY (10px corners used to swallow short rects whole)
                    // 角の当たりは12pt固定（細い矩形で判定が消えて掴めない問題の根治。
                    // 角が優先、本体は角に近くない場合のみ）。ハンドル位置=表示位置
                    // （回転時は回転後の角）なので、見えている所がそのまま掴める
                    let cr = 12.0f32;
                    // 本体判定は無回転ローカル空間で（回転した細線は軸平行バウンディング
                    // ボックスとズレるため、ポインタを逆回転してから判定する）
                    let ptl = if ed_rot.abs() > 1e-3 {
                        let (sn, cs) =
                            ((-ed_rot).to_radians().sin() as f32, (-ed_rot).to_radians().cos() as f32);
                        let ctr = r.center();
                        let d = pt - ctr;
                        egui::pos2(ctr.x + cs * d.x - sn * d.y, ctr.y + sn * d.x + cs * d.y)
                    } else {
                        pt
                    };
                    // 極細矩形（疑似ライン）でも本体を掴めるよう、当たりは最低12px幅
                    let body = r.expand2(egui::vec2(
                        (12.0 - r.width()).max(0.0) * 0.5,
                        (12.0 - r.height()).max(0.0) * 0.5,
                    ));
                    let mode = hs4
                        .iter()
                        .position(|cp| cp.distance(pt) <= cr)
                        .map(|ci| ci as u8 + 1)
                        .unwrap_or(if body.contains(ptl) { 0 } else { u8::MAX });
                    if mode == u8::MAX {
                        continue;
                    }
                    let armed = self.kf_mode.as_deref() == Some(cid.as_str());
                    self.kf_drag_rel = None;
                    self.kf_drag_orig_keys = None;
                    if let Some((ts, keys)) = key_info {
                        if self.playing {
                            self.pause_at_displayed();
                        }
                        let has_keys = keys
                            .as_ref()
                            .and_then(|k| k.as_array())
                            .map(|a| !a.is_empty())
                            .unwrap_or(false);
                        let alt = ui.input(|i| i.modifiers.alt);
                        if has_keys && alt {
                            // Alt+ドラッグ = 軌跡ごと平行移動（全キー一括・明示操作のみ）
                            self.kf_drag_orig_keys = keys;
                        } else if armed || has_keys {
                            // キーがあるクリップのドラッグは「この時点のキーだけ」を書く。
                            // 以前はモードOFF時に全キー平行移動が既定で、Bを直したら
                            // 確認済みのAまで動く事故になっていた（触っていないキーは
                            // 絶対に変えない、が編集の大原則）。
                            // 既存キー上にヘッドがあるならそのキーの時刻に書く
                            // （keyed_grid_t — 1フレーム手前に別キーが湧く事故の根治）
                            let kts_rel: Vec<f64> = keys
                                .as_ref()
                                .and_then(|k| k.as_array())
                                .map(|a| a.iter().filter_map(|k| k.get("t").and_then(|v| v.as_f64())).collect())
                                .unwrap_or_default();
                            self.kf_drag_rel = Some(self.keyed_grid_t(ts, &kts_rel) - ts);
                        }
                    }
                    self.pending_undo = Some(self.doc.raw.clone());
                    eprintln!(
                        "KFDRAG start mode={mode} rel={:?} offset_keys={} armed={armed}",
                        self.kf_drag_rel,
                        self.kf_drag_orig_keys.is_some(),
                    );
                    self.region_drag = Some((cid.clone(), mode, pt, self.region_of(cid)));
                    break 'hit;
                }
            }
        }
        if let Some((cid, mode, grab, orig)) = self.region_drag.clone() {
            if let Some(pt) = pointer_pos {
                let dx = ((pt.x - grab.x) / vid.width()) as f64;
                let dy = ((pt.y - grab.y) / vid.height()) as f64;
                let (ox, oy, ow, oh) = orig;
                let (mut x, mut y, mut w, mut h) = orig;
                if mode == 0 {
                    x += dx;
                    y += dy;
                } else {
                    // 角ドラッグ＝掴んだ角を自由に動かし、対角をアンカーに正規化。
                    // 反対側へ突き抜けたら矩形が反転して逆方向に伸びる＝細さの下限が
                    // 操作として存在しない（0通過はregion_atの「矩形なし」判定を
                    // 避けるため極小値で一瞬止まるだけ）
                    let (gx, gy, ax, ay) = match mode {
                        1 => (ox, oy, ox + ow, oy + oh),      // NW を掴む / SE 固定
                        2 => (ox + ow, oy, ox, oy + oh),      // NE を掴む / SW 固定
                        3 => (ox, oy + oh, ox + ow, oy),      // SW を掴む / NE 固定
                        _ => (ox + ow, oy + oh, ox, oy),      // SE を掴む / NW 固定
                    };
                    let (mx, my) = (gx + dx, gy + dy);
                    x = mx.min(ax);
                    y = my.min(ay);
                    w = (mx - ax).abs();
                    h = (my - ay).abs();
                }
                w = w.clamp(0.0002, 1.0);
                h = h.clamp(0.0002, 1.0);
                // 画面外へのはみ出しOK（端ギリギリを隠す用）。ただし最低5%は画面内に
                // 残す＝完全に出て掴めなくなる事故を防ぐ
                x = x.clamp(0.05 - w, 0.95);
                y = y.clamp(0.05 - h, 0.95);
                let cid2 = cid.clone();
                if let Some(rel) = self.kf_drag_rel {
                    // キー打ちモードON: 移動もリサイズも位置+サイズのキーとして書く
                    self.apply_edit(false, move |raw| edits::set_region_key(raw, &cid2, rel, x, y, w, h));
                } else if let Some(okeys) = self.kf_drag_orig_keys.clone() {
                    // OFF＋キー有り: 軌跡ごと平行移動/一括リサイズ（キーは作らない）。
                    // 基準矩形も同じ絶対値で追従（旧形式キーのサイズ参照元）
                    let (dx, dy, dw, dh) = (x - orig.0, y - orig.1, w - orig.2, h - orig.3);
                    self.apply_edit(false, move |raw| {
                        edits::set_region(raw, &cid2, x, y, w, h);
                        edits::offset_region_keys(raw, &cid2, &okeys, dx, dy, dw, dh);
                    });
                } else {
                    self.apply_edit(false, move |raw| edits::set_region(raw, &cid2, x, y, w, h));
                }
            }
            if ui.input(|i| i.pointer.any_released()) {
                // キーを書いたことを必ず見える化（暗黙のキー増加を根絶）
                if self.kf_drag_rel.is_some() {
                    let n = self
                        .doc
                        .seq
                        .tracks
                        .iter()
                        .flat_map(|tr| tr.clips.iter())
                        .find(|c| c.id == cid)
                        .map(|c| c.region_key_times().len())
                        .unwrap_or(0);
                    self.toast(&format!("◆ キーを打ちました（{n}個）"));
                }
                self.region_drag = None;
                self.kf_drag_rel = None;
                self.kf_drag_orig_keys = None;
                self.push_req(false);
            }
            return; // the gesture owns the pointer — skip the asset-clip inspector below
        }
        // --- caption drag: a selected telop can be MOVED directly on the preview.
        // Writes style.x / style.y (the same fields as the 左右/上下 sliders), so the
        // WebView overlay and the export both follow. No snap-back at the edges.
        if let Some((cid, grab, sx, sy)) = self.caption_drag.clone() {
            if let Some(pt) = pointer_pos {
                let dx = ((pt.x - grab.x) / vid.width()) as f64;
                let dy = ((pt.y - grab.y) / vid.height()) as f64;
                let q3 = |v: f64| (v * 1000.0).round() / 1000.0;
                // style.y is "fraction UP from the bottom" and the renderer clamps it
                // to 0..0.92 — mirror that here so the box never lies about the pixels.
                let patch = serde_json::json!({
                    "x": q3(sx + dx),
                    "y": q3((sy - dy).clamp(0.0, 0.92)),
                });
                let ids = vec![cid];
                self.apply_edit(false, move |raw| edits::patch_caption_style(raw, &ids, patch));
            }
            if ui.input(|i| i.pointer.any_released()) {
                self.caption_drag = None;
                self.push_req(false);
            }
            return;
        }
        let sel_caps: Vec<model::Clip> = self
            .doc
            .seq
            .tracks
            .iter()
            .flat_map(|tr| tr.clips.iter())
            .filter(|c| {
                self.selected.contains(&c.id)
                    && c.text.is_some()
                    && c.asset_id.is_none()
                    && c.region.is_none()
                    && t_disp >= c.timeline_start
                    && t_disp < c.timeline_end
            })
            .cloned()
            .collect();
        for c in &sel_caps {
            // Box source 1: the WebView's DOM measurement (captions the overlay draws).
            // Box source 2: compositor-owned captions (lane z puts video above them) are
            // NOT in the WebView payload, so measure their cache PNG instead — same
            // pixels, so the box matches what's on screen.
            let sbox = self
                .caption_live_boxes
                .lock()
                .ok()
                .and_then(|lb| lb.get(&c.id).copied())
                .map(|[x, y, w, h]| (x, y, w, h))
                .or_else(|| self.caption_png_box(c));
            if std::env::var("NATIVE_CAPBOX_DEBUG").is_ok() {
                eprintln!("CAPBOX id={} box={:?}", c.id, sbox);
            }
            let Some((dx0, dy0, dw, dh)) = sbox else { continue };
            let r = egui::Rect::from_min_size(
                egui::pos2(
                    vid.left() + dx0 as f32 * vid.width(),
                    vid.top() + dy0 as f32 * vid.height(),
                ),
                egui::vec2(dw as f32 * vid.width(), dh as f32 * vid.height()),
            );
            let p = ui.painter_at(vid);
            p.rect_stroke(r, 3.0, egui::Stroke::new(1.5, egui::Color32::from_rgb(190, 150, 60)));
            if let Some(pt) = pointer_pos {
                if r.contains(pt) {
                    ui.ctx().set_cursor_icon(egui::CursorIcon::Grab);
                    if preview_drag_started && self.caption_drag.is_none() {
                        let style = c.style.clone().unwrap_or_else(|| serde_json::json!({}));
                        let sx = caption_style_num(&style, "x", 0.0);
                        let sy = caption_style_num(&style, "y", 0.08).clamp(0.0, 0.92);
                        self.pending_undo = Some(self.doc.raw.clone());
                        self.caption_drag = Some((c.id.clone(), pt, sx, sy));
                    }
                }
            }
        }
        if self.caption_drag.is_some() {
            return;
        }
        let sel: Vec<model::Clip> = self
            .doc
            .seq
            .tracks
            .iter()
            .filter(|tr| tr.kind != "audio")
            .flat_map(|tr| tr.clips.iter())
            .filter(|c| self.selected.contains(&c.id) && c.asset_id.is_some())
            .cloned()
            .collect();
        if sel.is_empty() {
            return;
        }
        let same_kind = sel.iter().all(|c| c.text.is_none() && c.asset_id.is_some());
        if !same_kind {
            return;
        }
        let Some(c) = sel
            .iter()
            .find(|c| self.t >= c.timeline_start && self.t < c.timeline_end)
            .or_else(|| sel.first())
        else {
            return;
        };
        // only meaningful while the clip is on screen
        if self.t < c.timeline_start || self.t >= c.timeline_end {
            return;
        }
        // the frame follows the keyframed pose at the DISPLAYED frame (region 流儀)
        let b = effective_box(&self.doc, c, t_disp);
        let tkts = c.transform_key_times();
        let t_rel = t_disp - c.timeline_start;
        let on_tkey = tkts.iter().any(|kt| (kt - t_rel).abs() <= edits::KEY_REPLACE_EPS);
        let frame_col = if on_tkey {
            // playhead ON a transform keyframe: DaVinci-red = "drag re-writes THIS key"
            egui::Color32::from_rgb(240, 80, 80)
        } else if !tkts.is_empty() {
            egui::Color32::from_rgb(255, 170, 60) // interpolating between keys
        } else {
            egui::Color32::from_rgb(90, 170, 255)
        };
        let bx = egui::Rect::from_min_size(
            egui::pos2(
                vid.left() + (b.x as f32) * vid.width(),
                vid.top() + (b.y as f32) * vid.height(),
            ),
            egui::vec2((b.width as f32) * vid.width(), (b.height as f32) * vid.height()),
        );
        let p = ui.painter_at(vid);
        p.rect_stroke(bx, 2.0, egui::Stroke::new(1.5, frame_col));
        let corners = [bx.min, egui::pos2(bx.max.x, bx.min.y), egui::pos2(bx.min.x, bx.max.y), bx.max];
        for cp in corners {
            p.rect_filled(egui::Rect::from_center_size(cp, egui::vec2(9.0, 9.0)), 2.0, frame_col);
        }
        if on_tkey {
            let cpt = egui::pos2(bx.center().x, bx.top());
            p.add(egui::Shape::convex_polygon(
                vec![
                    cpt + egui::vec2(0.0, -5.0),
                    cpt + egui::vec2(5.0, 0.0),
                    cpt + egui::vec2(0.0, 5.0),
                    cpt + egui::vec2(-5.0, 0.0),
                ],
                frame_col,
                egui::Stroke::NONE,
            ));
        }
        // Corners keep the current shape. Edge handles deform one axis only.
        let edges = [
            egui::pos2(bx.left(), bx.center().y),
            egui::pos2(bx.right(), bx.center().y),
            egui::pos2(bx.center().x, bx.top()),
            egui::pos2(bx.center().x, bx.bottom()),
        ];
        for ep in edges {
            p.rect_filled(egui::Rect::from_center_size(ep, egui::vec2(8.0, 8.0)), 1.0, egui::Color32::WHITE);
        }
        let pointer = pointer_pos;
        // cursor feedback
        if let Some(pt) = pointer {
            if corners.iter().any(|cp| cp.distance(pt) < 10.0) {
                ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeNwSe);
            } else if edges[..2].iter().any(|ep| ep.distance(pt) < 10.0) {
                ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeHorizontal);
            } else if edges[2..].iter().any(|ep| ep.distance(pt) < 10.0) {
                ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeVertical);
            } else if bx.contains(pt) {
                ui.ctx().set_cursor_icon(egui::CursorIcon::Grab);
            }
        }
        if preview_drag_started {
            if let Some(pt) = pointer_pos {
                let corner = corners.iter().position(|cp| cp.distance(pt) < 10.0);
                let edge = edges.iter().position(|ep| ep.distance(pt) < 10.0);
                // drag starts from the DISPLAYED pose (keyframed clips: the evaluated box)
                let starts: Vec<(String, model::Pos)> = sel
                    .iter()
                    .map(|c| (c.id.clone(), effective_box(&self.doc, c, t_disp)))
                    .collect();
                if corner.is_some() || edge.is_some() || bx.contains(pt) {
                    // transform-key routing, armed per clip like the region editor:
                    // kf ON = this drag writes a key at the displayed frame; OFF with
                    // keys = the whole trajectory offsets rigidly (no key appears)
                    self.tkf_drag_rel = None;
                    self.tkf_drag_orig = Vec::new();
                    let armed_clip = self
                        .kf_mode
                        .as_deref()
                        .and_then(|kid| sel.iter().find(|c| c.id == kid));
                    if let Some(ac) = armed_clip {
                        // keyed_grid_t: ヘッドが既存キー上ならそのキーの時刻に書く
                        let rel = self.keyed_grid_t(ac.timeline_start, &ac.transform_key_times())
                            - ac.timeline_start;
                        if rel >= 0.0 && rel <= ac.dur() {
                            self.tkf_drag_rel = Some(rel);
                        }
                    }
                    for c in &sel {
                        if Some(c.id.as_str()) != self.kf_mode.as_deref() {
                            if let Some(k) = c.transform_keys.clone().filter(|k| {
                                k.as_array().map(|a| !a.is_empty()).unwrap_or(false)
                            }) {
                                self.tkf_drag_orig.push((c.id.clone(), k));
                            }
                        }
                    }
                    if (self.tkf_drag_rel.is_some() || !self.tkf_drag_orig.is_empty()) && self.playing {
                        self.pause_at_displayed();
                    }
                }
                if let Some(ci) = corner {
                    self.pending_undo = Some(self.doc.raw.clone());
                    self.inspect_drag = Some((starts, ci as u8 + 1, pt, b));
                } else if let Some(ei) = edge {
                    self.pending_undo = Some(self.doc.raw.clone());
                    self.inspect_drag = Some((starts, ei as u8 + 5, pt, b));
                } else if bx.contains(pt) {
                    self.pending_undo = Some(self.doc.raw.clone());
                    self.inspect_drag = Some((starts, 0, pt, b));
                }
            }
        }
        if preview_dragging {
            if let (Some((starts, mode, start, ob)), Some(pt)) = (self.inspect_drag.clone(), pointer_pos) {
                let dx = ((pt.x - start.x) / vid.width()) as f64;
                let dy = ((pt.y - start.y) / vid.height()) as f64;
                let scale = if mode == 0 || mode >= 5 {
                    1.0
                } else {
                    let (_, _, sxs, sys) = match mode {
                        1 => (ob.x + ob.width, ob.y + ob.height, -1.0, -1.0),
                        2 => (ob.x, ob.y + ob.height, 1.0, -1.0),
                        3 => (ob.x + ob.width, ob.y, -1.0, 1.0),
                        _ => (ob.x, ob.y, 1.0, 1.0),
                    };
                    let scale_w = (ob.width + dx * sxs).max(0.03) / ob.width;
                    let scale_h = (ob.height + dy * sys).max(0.03) / ob.height;
                    scale_w.max(scale_h)
                };
                let stretch_ids: Vec<String> = starts.iter().map(|(id, _)| id.clone()).collect();
                let armed = self.tkf_drag_rel.map(|rel| (self.kf_mode.clone().unwrap_or_default(), rel));
                let offset_keys = self.tkf_drag_orig.clone();
                self.apply_edit(false, move |raw| {
                    for (id, sb) in &starts {
                        let (nx, ny, nw, nh) = if mode == 0 {
                            (sb.x + dx, sb.y + dy, sb.width, sb.height)
                        } else if mode == 5 {
                            let nw = (sb.width - dx).max(0.03);
                            (sb.x + sb.width - nw, sb.y, nw, sb.height)
                        } else if mode == 6 {
                            (sb.x, sb.y, (sb.width + dx).max(0.03), sb.height)
                        } else if mode == 7 {
                            let nh = (sb.height - dy).max(0.03);
                            (sb.x, sb.y + sb.height - nh, sb.width, nh)
                        } else if mode == 8 {
                            (sb.x, sb.y, sb.width, (sb.height + dy).max(0.03))
                        } else {
                            let (ax, ay, sxs, sys) = match mode {
                                1 => (sb.x + sb.width, sb.y + sb.height, -1.0, -1.0),
                                2 => (sb.x, sb.y + sb.height, 1.0, -1.0),
                                3 => (sb.x + sb.width, sb.y, -1.0, 1.0),
                                _ => (sb.x, sb.y, 1.0, 1.0),
                            };
                            let (nw, nh) = (sb.width * scale, sb.height * scale);
                            let nx = if sxs < 0.0 { ax - nw } else { ax };
                            let ny = if sys < 0.0 { ay - nh } else { ay };
                            (nx, ny, nw, nh)
                        };
                        if let Some((aid, rel)) = armed.as_ref().filter(|(aid, _)| aid == id) {
                            // キー打ちモードON: 表示フレームのスロットに位置+サイズのキー
                            // （クロップは触らない＝置換キーの持つcropは維持される）
                            edits::set_transform_key(raw, aid, *rel, nx, ny, nw, nh, None);
                        } else if let Some((_, okeys)) = offset_keys.iter().find(|(oid, _)| oid == id) {
                            // OFF＋キー有り: 軌跡ごと平行移動/一括リサイズ（キーは増えない）
                            let (dx2, dy2, dw2, dh2) =
                                (nx - sb.x, ny - sb.y, nw - sb.width, nh - sb.height);
                            edits::set_position(raw, id, nx, ny, nw, nh);
                            edits::offset_transform_keys(raw, id, okeys, dx2, dy2, dw2, dh2);
                        } else {
                            edits::set_position(raw, id, nx, ny, nw, nh);
                        }
                    }
                    if mode >= 5 {
                        edits::set_fit_many(raw, &stretch_ids, true);
                    }
                });
            }
        }
        if preview_drag_stopped {
            // キーを書いたことを必ず見える化（暗黙のキー増加を根絶）— region 流儀
            if self.inspect_drag.is_some() && self.tkf_drag_rel.is_some() {
                if let Some(kid) = self.kf_mode.clone() {
                    let n = self
                        .doc
                        .seq
                        .tracks
                        .iter()
                        .flat_map(|tr| tr.clips.iter())
                        .find(|c| c.id == kid)
                        .map(|c| c.transform_key_times().len())
                        .unwrap_or(0);
                    self.toast(&format!("◆ キーを打ちました（{n}個）"));
                }
            }
            self.tkf_drag_rel = None;
            self.tkf_drag_orig = Vec::new();
            self.inspect_drag = None;
            self.push_req(false); // settle full quality after the adjustment
        }
    }

    /// Inspector box edits route through the transform-key rules (region 流儀):
    /// kf mode ON (single clip, playhead in span) = write a key at the displayed frame;
    /// OFF with keys = shift the whole trajectory by the delta; else = plain base write.
    /// `old_b` is the box the numeric fields were SHOWING (evaluated for keyed clips).
    fn apply_box_edit(&mut self, ids: Vec<String>, old_b: model::Pos, x: f64, y: f64, w: f64, h: f64) {
        if ids.len() == 1 {
            let id = ids[0].clone();
            let clip = self
                .doc
                .seq
                .tracks
                .iter()
                .flat_map(|tr| tr.clips.iter())
                .find(|c| c.id == id)
                .cloned();
            if let Some(c) = clip {
                let t_now = self.displayed_grid_t();
                let rel = t_now - c.timeline_start;
                if self.kf_mode.as_deref() == Some(id.as_str()) && rel >= 0.0 && rel <= c.dur() {
                    let cid = id.clone();
                    self.apply_edit(false, move |raw| {
                        edits::set_transform_key(raw, &cid, rel, x, y, w, h, None)
                    });
                    return;
                }
                if let Some(keys) = c
                    .transform_keys
                    .clone()
                    .filter(|k| k.as_array().map(|a| !a.is_empty()).unwrap_or(false))
                {
                    let (dx, dy, dw, dh) = (x - old_b.x, y - old_b.y, w - old_b.width, h - old_b.height);
                    let cid = id.clone();
                    self.apply_edit(false, move |raw| {
                        edits::set_position(raw, &cid, x, y, w, h);
                        edits::offset_transform_keys(raw, &cid, &keys, dx, dy, dw, dh);
                    });
                    return;
                }
            }
        }
        self.apply_edit(false, move |raw| edits::set_position_many(raw, &ids, x, y, w, h));
    }

    fn push_req(&mut self, scrubbing: bool) {
        let mut r = self.shared.req.lock().unwrap();
        self.gen += 1;
        self.last_push = Instant::now();
        *r = Req { t: self.t, playing: self.playing, scrubbing, speed: self.playback_speed, gen: self.gen };
    }

    fn timeline_ui(&mut self, ui: &mut egui::Ui) {
        const NEW_TOP_LANE: usize = usize::MAX;
        const NEW_BOTTOM_LANE: usize = usize::MAX - 1;
        const GUTTER: f32 = 112.0; // lane headers (lock/eye/mute/solo/magnet icons)
        let h = timeline_body_height(ui);
        let w = ui.available_width();
        let (rect, resp) = ui.allocate_exact_size(egui::vec2(w, h), egui::Sense::click_and_drag());
        let body = egui::Rect::from_min_max(egui::pos2(rect.left() + GUTTER, rect.top()), rect.max);
        // set while drawing key diamonds (clicking one jumps the playhead to the key);
        // applied at the end of the frame — the draw loop borrows self immutably
        let mut kf_click_seek: Option<f64> = None;
        let p = ui.painter_at(rect);
        p.rect_filled(rect, 0.0, egui::Color32::from_gray(18));
        p.rect_filled(
            egui::Rect::from_min_max(rect.min, egui::pos2(rect.left() + GUTTER, rect.bottom())),
            0.0,
            egui::Color32::from_gray(24),
        );

        let (scroll, zoom_mod, pointer) =
            ui.input(|i| (i.raw_scroll_delta, i.modifiers.ctrl, i.pointer.hover_pos()));
        if body.contains(pointer.unwrap_or_default()) {
            if zoom_mod && scroll.y != 0.0 {
                let px = pointer.unwrap().x - body.left();
                let t_at = (self.scroll_x + px) / self.pps;
                self.pps = (self.pps * (1.0 + scroll.y.signum() * 0.15)).clamp(1.0, 400.0);
                self.scroll_x = (t_at * self.pps - px).max(0.0);
            } else if scroll.x != 0.0 || scroll.y != 0.0 {
                self.scroll_x = (self.scroll_x - scroll.x - scroll.y).max(0.0);
            }
        }

        let ruler_h = 20.0;
        p.rect_filled(
            egui::Rect::from_min_max(body.min, egui::pos2(body.right(), body.top() + ruler_h)),
            0.0,
            egui::Color32::from_rgb(17, 17, 19),
        );
        let step_s = (60.0 / self.pps).ceil().max(1.0);
        // minor ticks: quarters of the labelled step (skip when they'd crowd)
        let minor = step_s / 4.0;
        if minor * self.pps >= 7.0 {
            let mut m = (self.scroll_x / self.pps / minor).floor() * minor;
            while m * self.pps - self.scroll_x < w {
                let x = body.left() + m * self.pps - self.scroll_x;
                if x >= body.left() {
                    p.line_segment(
                        [egui::pos2(x, body.top() + ruler_h - 5.0), egui::pos2(x, body.top() + ruler_h)],
                        egui::Stroke::new(1.0, egui::Color32::from_gray(55)),
                    );
                }
                m += minor;
            }
        }
        let mut s = (self.scroll_x / self.pps / step_s).floor() * step_s;
        while s * self.pps - self.scroll_x < w {
            let x = body.left() + s * self.pps - self.scroll_x;
            if x >= body.left() {
                p.line_segment(
                    [egui::pos2(x, body.top() + ruler_h - 9.0), egui::pos2(x, body.top() + ruler_h)],
                    egui::Stroke::new(1.0, egui::Color32::from_gray(105)),
                );
                p.text(
                    egui::pos2(x + 4.0, body.top() + 2.0),
                    egui::Align2::LEFT_TOP,
                    format!("{:02}:{:02}", (s as i64) / 60, (s as i64) % 60),
                    egui::FontId::monospace(9.5),
                    egui::Color32::from_gray(135),
                );
            }
            s += step_s;
        }

        // ---- render range band (DaVinci-style in/out) on the ruler ----
        // I/O keys set the edges at the playhead; the edge flags drag; export uses
        // only this span when set. Session-local state (not written to the timeline).
        // メインタブ専用（サブタブの I/O は緑の飛び飛び区間）
        if let Some((ra, rb)) = (!self.on_sub_tab()).then_some(self.export_range).flatten() {
            let x0 = (body.left() + ra as f32 * self.pps - self.scroll_x).max(body.left());
            let x1 = (body.left() + rb as f32 * self.pps - self.scroll_x).min(body.right());
            if x1 > body.left() && x0 < body.right() {
                p.rect_filled(
                    egui::Rect::from_min_max(
                        egui::pos2(x0, body.top() + 1.0),
                        egui::pos2(x1, body.top() + 8.0),
                    ),
                    2.0,
                    egui::Color32::from_rgba_unmultiplied(90, 170, 255, 90),
                );
            }
            for (t_edge, is_in) in [(ra, true), (rb, false)] {
                let x = body.left() + t_edge as f32 * self.pps - self.scroll_x;
                if x < body.left() - 8.0 || x > body.right() + 8.0 {
                    continue;
                }
                p.line_segment(
                    [egui::pos2(x, body.top()), egui::pos2(x, body.top() + ruler_h)],
                    egui::Stroke::new(2.0, egui::Color32::from_rgb(110, 190, 255)),
                );
                let dir = if is_in { 5.0 } else { -5.0 };
                p.add(egui::Shape::convex_polygon(
                    vec![
                        egui::pos2(x, body.top() + 1.0),
                        egui::pos2(x + dir, body.top() + 5.0),
                        egui::pos2(x, body.top() + 9.0),
                    ],
                    egui::Color32::from_rgb(110, 190, 255),
                    egui::Stroke::NONE,
                ));
            }
        }

        // ---- サブタイムライン区間帯（飛び飛び再生区間・サブタブ専用）----
        // 緑帯=再生・書き出しの対象。区間外のレーン本体は暗転して
        // 「ここは流れない」を見せる。イン点待ちは緑の縦線。
        if self.on_sub_tab() {
            let subs = self.sub_ranges();
            let x_of = |t: f64| body.left() + t as f32 * self.pps - self.scroll_x;
            for &(a, b) in &subs {
                let x0 = x_of(a).max(body.left());
                let x1 = x_of(b).min(body.right());
                if x1 <= body.left() || x0 >= body.right() {
                    continue;
                }
                p.rect_filled(
                    egui::Rect::from_min_max(
                        egui::pos2(x0, body.top() + 9.0),
                        egui::pos2(x1, body.top() + 16.0),
                    ),
                    2.0,
                    egui::Color32::from_rgba_unmultiplied(0, 210, 140, 170),
                );
                // モード中は端をドラッグハンドルとして見せる（縦線＋内向き三角）
                if self.on_sub_tab() {
                    let ec = egui::Color32::from_rgb(0, 230, 155);
                    for (t_edge, is_in) in [(a, true), (b, false)] {
                        let x = x_of(t_edge);
                        if x < body.left() - 8.0 || x > body.right() + 8.0 {
                            continue;
                        }
                        p.line_segment(
                            [egui::pos2(x, body.top() + 1.0), egui::pos2(x, body.top() + 17.0)],
                            egui::Stroke::new(2.0, ec),
                        );
                        let dir = if is_in { 5.0 } else { -5.0 };
                        p.add(egui::Shape::convex_polygon(
                            vec![
                                egui::pos2(x, body.top() + 1.0),
                                egui::pos2(x + dir, body.top() + 5.0),
                                egui::pos2(x, body.top() + 9.0),
                            ],
                            ec,
                            egui::Stroke::NONE,
                        ));
                    }
                }
            }
        }

        // Layered-track model (Filmora/Olive): the tracks array IS the stacking order,
        // index 0 = back. Display shows visual tracks top=front (reverse array order);
        // audio tracks sit below the visual stack (universal NLE convention). No
        // kind-based pinning — reorder/move clips and the render follows.
        // ロールフリー表示: レーンの太さは「役割(kind)」では決めない。太いのは
        // 映像メインレーン（配列先頭＝最背面の視覚レーン）1本だけで、それ以外は
        // 種類にかかわらず一律スリム。ビジュアルレーンは空でも常に表示する
        // （普通のNLEの持続的トラック）。ドラッグ中だけ出没する幽霊レーンも、
        // 「最上段の唯一のクリップを上へ引いても±0に見える」問題も、これで消える。
        // 同一ジェスチャ中の仮レーン(無名・空)だけは edits 側の prune が畳む。
        let moving = matches!(self.drag, Drag::Move { .. }) && self.drag_engaged;
        let visual: Vec<usize> = (0..self.doc.seq.tracks.len())
            .rev()
            .filter(|&i| self.doc.seq.tracks[i].kind != "audio")
            .collect();
        let audio: Vec<usize> = (0..self.doc.seq.tracks.len())
            .filter(|&i| self.doc.seq.tracks[i].kind == "audio")
            // 音声レーンへのドロップは許可していないので、ドラッグ中でも
            // 空の音声レーンは出さない（無意味なレイアウトのズレを減らす）
            .filter(|&i| !self.doc.seq.tracks[i].clips.is_empty())
            .collect();
        let order: Vec<usize> = visual.into_iter().chain(audio).collect();
        let main_visual: Option<usize> =
            (0..self.doc.seq.tracks.len()).find(|&i| self.doc.seq.tracks[i].kind != "audio");
        let lane_h_for = |i: usize| -> f32 { if Some(i) == main_visual { 54.0 } else { 26.0 } };
        let total_h: f32 = order.iter().map(|&i| lane_h_for(i) + 3.0).sum();
        let avail = h - ruler_h - 6.0;
        let squeeze = (avail / total_h.max(1.0)).min(1.0);
        let mut lane_tops: Vec<(usize, f32, f32)> = Vec::new(); // (track idx, y0, height)
        {
            // レーン束は余った縦空間の中央に置く。上（ルーラー直下）にギチギチ、
            // 下に広大な余白という頭でっかちを避け、パネルをどう広げても
            // シーケンスがバランスの良い中間に来る。
            let mut y = rect.top() + ruler_h + 3.0 + ((avail - total_h).max(0.0) * 0.5);
            for &i in &order {
                let lh = lane_h_for(i) * squeeze;
                lane_tops.push((i, y, lh));
                y += lh + 3.0 * squeeze;
            }
        }
        // --- Moveドラッグ中はレイアウトを凍結する -----------------------------
        // 空レーンの出現でレイアウトが毎フレーム変わると、押下時のポインタ座標が
        // 別レーンを指してしまい、ライブ追従が初手でクリップをテレポートさせる。
        // 開始時に「アンカーのレーンが押下時と同じ y に来る」よう全体をオフセット
        // した展開レイアウトを一度だけ作り、ドラッグ終了まで使い続ける。
        if moving {
            if let Some(frozen) = &self.drag_lane_tops {
                lane_tops = frozen.clone();
            } else {
                if let Drag::Move { anchor_id, .. } = &self.drag {
                    let anchor_track = self
                        .doc
                        .seq
                        .tracks
                        .iter()
                        .position(|tr| tr.clips.iter().any(|c| &c.id == anchor_id));
                    if let Some(at) = anchor_track {
                        let pre = self.last_lane_tops.iter().find(|&&(i, _, _)| i == at).map(|&(_, y, _)| y);
                        let post = lane_tops.iter().find(|&&(i, _, _)| i == at).map(|&(_, y, _)| y);
                        if let (Some(a), Some(b)) = (pre, post) {
                            let off = a - b;
                            for lt in lane_tops.iter_mut() {
                                lt.1 += off;
                            }
                        }
                    }
                }
                self.drag_lane_tops = Some(lane_tops.clone());
            }
        } else {
            self.drag_lane_tops = None;
            self.last_lane_tops = lane_tops.clone();
        }
        let mut clips_drawn = 0usize;
        let mut hits: Vec<(egui::Rect, String)> = Vec::new();
        // marquee-only hit rects: hits + clips culled from drawing (offscreen). Pointer
        // hit-tests keep using `hits` so offscreen rects never capture clicks/trims.
        let mut marquee_hits: Vec<(egui::Rect, String)> = Vec::new();
        // drop zone for "drag above the top lane -> new lane". The first lane starts a
        // mere 3px under the ruler, so clamping the zone below the ruler left a 3px
        // target nobody could hit ("レーンが増えない"). While a Move-drag is active the
        // ruler is not scrubbing, so the WHOLE band above lane 1 (ruler included) is the
        // drop zone.
        let new_top_drop = lane_tops.first().map(|&(_, y0, _)| {
            egui::Rect::from_min_max(
                egui::pos2(body.left(), (y0 - 40.0).max(body.top())),
                egui::pos2(body.right(), y0),
            )
        });
        // Filmora-style unified A/V clips: audio linked to a video/overlay clip is DRAWN
        // as part of that clip (waveform strip along its bottom) instead of duplicating a
        // clip on the audio lane. Standalone audio (BGM etc.) stays on the audio lane.
        let linked_av: std::collections::HashSet<String> = {
            let vids: std::collections::HashSet<&str> = self
                .doc
                .seq
                .tracks
                .iter()
                .filter(|tr| tr.kind != "audio")
                .flat_map(|tr| tr.clips.iter())
                .filter_map(|c| c.link_id.as_deref())
                .collect();
            self.doc
                .seq
                .tracks
                .iter()
                .filter(|tr| tr.kind == "audio")
                .flat_map(|tr| tr.clips.iter())
                .filter(|c| c.link_id.as_deref().map(|l| vids.contains(l)).unwrap_or(false))
                .map(|c| c.id.clone())
                .collect()
        };
        let mut flag_click: Option<(usize, String, bool)> = None;
        let mut lane_delete: Option<usize> = None;
        for &(ti, y0, lane_h) in &lane_tops {
            // 凍結レイアウト使用中にレーン移動でトラックが消えることがある
            // （空トラックの自動削除）。古いインデックスは1フレームだけ読み飛ばす
            let Some(tr) = self.doc.seq.tracks.get(ti) else { continue };
            // lane header itself is draggable: reorder tracks (stacking order)
            let hdr = egui::Rect::from_min_max(
                egui::pos2(rect.left(), y0),
                egui::pos2(rect.left() + GUTTER - 2.0, y0 + lane_h),
            );
            let hresp = ui.interact(hdr, egui::Id::new(("lane_hdr", ti)), egui::Sense::click_and_drag());
            if hresp.drag_started() {
                self.lane_reorder = Some(ti);
                self.pending_undo = Some(self.doc.raw.clone());
            }
            if hresp.hovered() {
                ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeVertical);
            }
            if self.lane_reorder == Some(ti) {
                p.rect_filled(hdr, 2.0, egui::Color32::from_rgba_unmultiplied(120, 170, 255, 40));
            }
            if self.hover_lane == Some(ti) && matches!(self.drag, Drag::Move { .. }) {
                p.rect_filled(
                    egui::Rect::from_min_max(egui::pos2(body.left(), y0), egui::pos2(body.right(), y0 + lane_h)),
                    0.0,
                    egui::Color32::from_rgba_unmultiplied(120, 170, 255, 22),
                );
            }
            // lane header: standard NLE toggles (lock / eye / mute / solo,
            // magnet on the main video lane). Lanes still have no fixed roles.
            {
                let is_audio = tr.kind == "audio";
                let magnet_here = !is_audio
                    && tr.kind == "video"
                    && self.doc.seq.tracks.iter().position(|t| t.kind == "video") == Some(ti);
                let base_video = magnet_here; // eye is not offered on the storyline spine
                let mut icons: Vec<(&str, &str, bool)> = vec![("locked", "🔒", tr.locked)];
                if !is_audio && !base_video {
                    icons.push(("hidden", "👁", tr.hidden));
                }
                icons.push(("muted", "🔇", tr.muted));
                icons.push(("solo", "Ｓ", tr.solo));
                if magnet_here {
                    icons.push(("magnet", "磁", self.doc.is_magnet(ti)));
                }
                let mut x = rect.left() + 4.0;
                for (key, glyph, on) in icons {
                    let r = egui::Rect::from_min_size(
                        egui::pos2(x, y0 + lane_h * 0.5 - 9.0),
                        egui::vec2(17.0, 18.0),
                    );
                    let iresp = ui.interact(r, egui::Id::new(("lane_flag", ti, key)), egui::Sense::click());
                    let col = if on {
                        match key {
                            "locked" => egui::Color32::from_rgb(240, 180, 70),
                            "hidden" | "muted" => egui::Color32::from_rgb(240, 110, 110),
                            "solo" => egui::Color32::from_rgb(120, 220, 130),
                            _ => egui::Color32::from_rgb(120, 180, 255),
                        }
                    } else if iresp.hovered() {
                        egui::Color32::from_gray(190)
                    } else {
                        egui::Color32::from_gray(80)
                    };
                    p.text(
                        r.center(),
                        egui::Align2::CENTER_CENTER,
                        glyph,
                        egui::FontId::proportional(15.0),
                        col,
                    );
                    if iresp.on_hover_text(match key {
                        "locked" => "ロック（編集不可）",
                        "hidden" => "表示/非表示",
                        "muted" => "ミュート",
                        "solo" => "ソロ（このレーンの音だけ再生）",
                        _ => "マグネット（消したら左詰め）",
                    }).clicked() {
                        let key = key.to_string();
                        let cur = match key.as_str() {
                            "locked" => tr.locked,
                            "hidden" => tr.hidden,
                            "muted" => tr.muted,
                            "solo" => tr.solo,
                            _ => self.doc.is_magnet(ti),
                        };
                        flag_click = Some((ti, key, !cur));
                    }
                    x += 18.0;
                }
                // 空レーンはヘッダ右端の小さな×で削除できる
                if tr.clips.is_empty() {
                    let r = egui::Rect::from_min_size(
                        egui::pos2(rect.left() + GUTTER - 20.0, y0 + lane_h * 0.5 - 8.0),
                        egui::vec2(16.0, 16.0),
                    );
                    let xresp =
                        ui.interact(r, egui::Id::new(("lane_del", ti)), egui::Sense::click());
                    p.text(
                        r.center(),
                        egui::Align2::CENTER_CENTER,
                        "✖",
                        egui::FontId::proportional(12.0),
                        if xresp.hovered() {
                            egui::Color32::from_rgb(240, 110, 110)
                        } else {
                            egui::Color32::from_gray(110)
                        },
                    );
                    if xresp.on_hover_text("この空レーンを削除").clicked() {
                        lane_delete = Some(ti);
                    }
                }
            }
            p.line_segment(
                [egui::pos2(rect.left(), y0 + lane_h + 1.5), egui::pos2(rect.right(), y0 + lane_h + 1.5)],
                egui::Stroke::new(1.0, egui::Color32::from_gray(28)),
            );
            // lane row background: a whisper of contrast so empty lanes read as lanes
            p.rect_filled(
                egui::Rect::from_min_max(egui::pos2(body.left(), y0), egui::pos2(body.right(), y0 + lane_h)),
                0.0,
                if tr.kind == "audio" {
                    egui::Color32::from_rgb(19, 23, 22)
                } else {
                    egui::Color32::from_rgb(21, 21, 24)
                },
            );
            for c in &tr.clips {
                if tr.kind == "audio" && linked_av.contains(&c.id) {
                    continue; // drawn as part of its video clip
                }
                // color = what the CLIP IS, never which lane it sits on (region clips
                // can live on any lane and used to change color when moved between
                // lanes). State dressing (bake veil etc.) stays separate below.
                let color = if c.style.as_ref().and_then(|v| v.as_str()) == Some("note") {
                    egui::Color32::from_rgb(150, 110, 220) // 指示クリップ
                } else if c.region.is_some() && c.asset_id.is_none() {
                    egui::Color32::from_rgb(0, 150, 160) // blur / mosaic
                } else if tr.kind == "audio" {
                    egui::Color32::from_rgb(70, 160, 90)
                } else if c.asset_id.is_some() {
                    egui::Color32::from_rgb(70, 110, 190) // video asset (base or PiP)
                } else if c.text.is_some() {
                    egui::Color32::from_rgb(190, 150, 60) // caption accent
                } else {
                    egui::Color32::from_gray(90)
                };
                let x0 = body.left() + (c.timeline_start as f32) * self.pps - self.scroll_x;
                let x1 = body.left() + (c.timeline_end as f32) * self.pps - self.scroll_x;
                if x1 < body.left() || x0 > body.right() {
                    // A marquee re-derives the selection every frame, and edge auto-scroll
                    // can carry already-boxed clips out of view — they must stay selectable,
                    // so offscreen clips still get an (unclamped) marquee rect.
                    if !tr.locked {
                        marquee_hits.push((
                            egui::Rect::from_min_max(egui::pos2(x0, y0), egui::pos2(x1, y0 + lane_h)),
                            c.id.clone(),
                        ));
                    }
                    continue;
                }
                let r = egui::Rect::from_min_max(
                    egui::pos2(x0.max(body.left()), y0),
                    egui::pos2(x1.min(body.right()), y0 + lane_h),
                );
                // ライブ組み上がり: 新規クリップは背景色ベールを上層に重ねて
                // フェードイン（時差つき）。上層レイヤなので装飾ごと隠れる。
                if let Some(v) = self.spawn_veil(&c.id) {
                    let vp = ui.ctx().layer_painter(egui::LayerId::new(
                        egui::Order::Foreground,
                        egui::Id::new("clip_spawn_veil"),
                    ));
                    vp.rect_filled(r, 4.0, egui::Color32::from_rgba_unmultiplied(160,205,255,v/8));
                    vp.rect_stroke(r.shrink(1.0),4.0,egui::Stroke::new(2.0,egui::Color32::from_rgba_unmultiplied(180,220,255,v)));
                    ui.ctx().request_repaint();
                }
                let is_pop = c.effects.iter().any(|e| e.kind == "popout");
                let is_blur_bake = c.blur_track.is_some();
                let pop_state = if is_pop {
                    self.pop_states.get(&c.id).copied()
                } else if is_blur_bake {
                    // SAM tracked-blur bakes reuse the same progress dressing
                    self.blur_states.get(&c.id).copied()
                } else {
                    None
                };
                let is_caption = c.text.is_some() && c.asset_id.is_none();
                let picture_disabled = tr.kind != "audio" && c.asset_id.is_some() && !c.is_video_enabled();
                if is_caption {
                    // caption clip: dark slate body + mustard accent edge + the TEXT itself
                    p.rect_filled(r, 4.0, egui::Color32::from_rgb(46, 42, 30));
                    p.rect_filled(
                        egui::Rect::from_min_max(r.min, egui::pos2(r.left() + 3.0, r.bottom())),
                        2.0,
                        color,
                    );
                    if r.width() > 22.0 {
                        let txt = self.caption_display_text(c).replace(chr_nl(), " ");
                        let max_chars = ((r.width() - 10.0) / 10.0) as usize;
                        let shown: String = txt.chars().take(max_chars.max(1)).collect();
                        p.text(
                            egui::pos2(r.left() + 7.0, r.center().y),
                            egui::Align2::LEFT_CENTER,
                            shown,
                            egui::FontId::proportional(10.0),
                            egui::Color32::from_gray(215),
                        );
                    }
                } else {
                    p.rect_filled(r, 4.0, color.gamma_multiply(if picture_disabled { 0.22 } else { 0.55 }));
                    if picture_disabled && r.width() > 32.0 {
                        p.text(
                            r.center(),
                            egui::Align2::CENTER_CENTER,
                            "映像OFF",
                            egui::FontId::proportional(10.0),
                            egui::Color32::from_gray(190),
                        );
                    }
                    if c.region.is_some() && r.width() > 26.0 {
                        let style = c.style.as_ref().and_then(|v| v.as_str()).unwrap_or("");
                        p.text(
                            egui::pos2(r.left() + 6.0, r.center().y),
                            egui::Align2::LEFT_CENTER,
                            match style {
                                "note" => "📝 指示",
                                "marker" => "マーカー",
                                "spotlight" => "スポット",
                                "frame" => "枠",
                                "zoom" => "ズーム",
                                s if s.contains("mosaic") => "モザイク",
                                _ => "ぼかし",
                            },
                            egui::FontId::proportional(10.0),
                            egui::Color32::from_gray(220),
                        );
                    }
                    // keyframes: diamond per key on the clip's lower half — region clips
                    // show their position keys, media clips their transform keys; the one
                    // under the playhead lights up red (DaVinci-style). CLICKING a diamond
                    // jumps the playhead onto that key (nearest key within 8px when
                    // zoomed-out diamonds overlap).
                    let kf_times = if c.region.is_some() {
                        c.region_key_times()
                    } else {
                        c.transform_key_times()
                    };
                    if !kf_times.is_empty() {
                        let rel_now = self.displayed_grid_t() - c.timeline_start;
                        let click_at = resp
                            .clicked()
                            .then(|| resp.interact_pointer_pos())
                            .flatten()
                            .filter(|pp| {
                                (pp.y - (r.bottom() - 8.0)).abs() <= 9.0
                                    && pp.x >= r.left() - 6.0
                                    && pp.x <= r.right() + 6.0
                            });
                        let dur = (c.timeline_end - c.timeline_start).max(0.0);
                        let mut best_hit: Option<(f32, f64)> = None;
                        // cluster keys that land on (nearly) the same pixel so "looks like
                        // one diamond but is actually N keys" is impossible: one diamond
                        // with a ×N badge instead. Out-of-range keys (pushed outside the
                        // clip by trims/splits) pin as ⚠-colored diamonds at the edge.
                        let mut clusters: Vec<(f32, u32, bool, bool)> = Vec::new(); // (px, count, hot, oob)
                        for kt in kf_times {
                            let oob = kt < -1e-9 || kt > dur + 1e-9;
                            let kx_raw = body.left()
                                + ((c.timeline_start + kt) as f32) * self.pps
                                - self.scroll_x;
                            // A very short clip can be narrower than the 10px diamond
                            // margin. `f32::clamp(min, max)` panics when min > max, which
                            // previously closed the app merely by drawing/clicking such a
                            // timeline. Pin its key marker to the clip centre instead.
                            let key_left = r.left() + 5.0;
                            let key_right = r.right() - 5.0;
                            let kx = if key_left <= key_right {
                                kx_raw.clamp(key_left, key_right)
                            } else {
                                r.center().x
                            };
                            if kx < body.left() - 8.0 || kx > body.right() + 8.0 {
                                continue;
                            }
                            if let Some(pp) = click_at {
                                let dx = (kx - pp.x).abs();
                                if dx <= 8.0 && best_hit.map(|(bd, _)| dx < bd).unwrap_or(true) {
                                    best_hit = Some((dx, kt));
                                }
                            }
                            let hot = (kt - rel_now).abs() <= edits::KEY_REPLACE_EPS;
                            match clusters.last_mut() {
                                Some((px, n, h, o)) if (*px - kx).abs() <= 3.0 => {
                                    *n += 1;
                                    *h |= hot;
                                    *o |= oob;
                                }
                                _ => clusters.push((kx, 1, hot, oob)),
                            }
                        }
                        for (kx, n, hot, oob) in clusters {
                            let (sz, kc) = if hot {
                                (5.0, egui::Color32::from_rgb(240, 80, 80))
                            } else if oob {
                                (4.0, egui::Color32::from_rgb(255, 190, 60)) // ⚠: 範囲外キーあり
                            } else {
                                (4.0, egui::Color32::from_gray(235))
                            };
                            let cpt = egui::pos2(kx, r.bottom() - 8.0);
                            p.add(egui::Shape::convex_polygon(
                                vec![
                                    cpt + egui::vec2(0.0, -sz),
                                    cpt + egui::vec2(sz, 0.0),
                                    cpt + egui::vec2(0.0, sz),
                                    cpt + egui::vec2(-sz, 0.0),
                                ],
                                kc,
                                egui::Stroke::new(1.0, egui::Color32::from_gray(40)),
                            ));
                            if n > 1 {
                                p.text(
                                    cpt + egui::vec2(5.0, -6.0),
                                    egui::Align2::LEFT_CENTER,
                                    format!("×{n}"),
                                    egui::FontId::proportional(9.0),
                                    kc,
                                );
                            }
                        }
                        if let Some((_, kt)) = best_hit {
                            kf_click_seek = Some(c.timeline_start + kt);
                        }
                    }
                }
                // effect state ON the clip, without killing the "what is this clip"
                // read: thin orange effect strip on top + translucent progress veil
                if is_pop {
                    let strip = egui::Rect::from_min_max(r.min, egui::pos2(r.right(), r.top() + 4.0));
                    p.rect_filled(strip, 2.0, egui::Color32::from_rgb(255, 150, 60));
                }
                match pop_state {
                    Some(PopState::Baking(pct)) => {
                        // UNMISSABLE progress, without hiding what the clip is:
                        // moderate veil + a SOLID 5px progress bar + always-on label
                        let frac = (pct as f32 / 100.0).clamp(0.02, 1.0);
                        let veil = egui::Rect::from_min_size(r.min, egui::vec2(r.width() * frac, r.height()));
                        p.rect_filled(veil, 3.0, egui::Color32::from_rgba_unmultiplied(255, 150, 60, 110));
                        let bar = egui::Rect::from_min_max(
                            egui::pos2(r.left(), r.bottom() - 5.0),
                            egui::pos2(r.left() + r.width() * frac, r.bottom()),
                        );
                        p.rect_filled(bar, 2.0, egui::Color32::from_rgb(255, 150, 60));
                        let label = if r.width() > 90.0 {
                            if is_pop {
                                format!("飛び出し生成中 {pct}%")
                            } else {
                                format!("追従ベイク中 {pct}%")
                            }
                        } else {
                            format!("{pct}%")
                        };
                        if r.width() > 24.0 {
                            let font = egui::FontId::proportional(if r.width() > 90.0 { 10.0 } else { 9.0 });
                            for (dx, dy) in [(-1.0, 0.0), (1.0, 0.0), (0.0, -1.0), (0.0, 1.0)] {
                                p.text(r.center() + egui::vec2(dx, dy), egui::Align2::CENTER_CENTER, &label, font.clone(), egui::Color32::BLACK);
                            }
                            p.text(r.center(), egui::Align2::CENTER_CENTER, &label, font, egui::Color32::WHITE);
                        }
                        let pulse = ((ui.input(|i| i.time) * 3.0).sin() * 0.5 + 0.5) as f32;
                        p.rect_stroke(
                            r,
                            3.0,
                            egui::Stroke::new(2.0, egui::Color32::from_rgba_unmultiplied(255, 190, 120, (120.0 + 130.0 * pulse) as u8)),
                        );
                    }
                    Some(PopState::Failed) => {
                        p.rect_stroke(r, 3.0, egui::Stroke::new(2.0, egui::Color32::from_rgb(230, 60, 60)));
                        if r.width() > 70.0 {
                            p.text(
                                r.center(),
                                egui::Align2::CENTER_CENTER,
                                "失敗 (Eで再試行)",
                                egui::FontId::proportional(10.0),
                                egui::Color32::from_rgb(255, 120, 120),
                            );
                        }
                    }
                    _ => {}
                }
                // Filmora-style title strip: colored bar with the clip name; filmstrip below
                let strip_h = if !is_caption && c.asset_id.is_some() && lane_h >= 40.0 { 14.0 } else { 0.0 };
                if tr.kind != "audio" {
                    if let Some(aid) = c.asset_id.as_ref() {
                        // FILMSTRIP: each tile shows the actual source frame at its position,
                        // at the SOURCE's aspect (a portrait video gets narrow tiles, not a
                        // squashed 16:9 smear)
                        let film_top = r.top() + strip_h;
                        let film_h = r.height() - strip_h;
                        let aspect = self
                            .thumbs
                            .get(&(aid.clone(), 0))
                            .map(|t| {
                                let sz = t.size();
                                (sz[0] as f32 / sz[1].max(1) as f32).clamp(0.3, 2.5)
                            })
                            .unwrap_or(16.0 / 9.0);
                        let tile_w = (film_h * aspect).max(8.0);
                        let px_per_src = self.pps.max(0.001) as f64;
                        let tile_src = tile_w as f64 / px_per_src;
                        let mut tile_i = (c.source_start / tile_src).floor() as i64;
                        let mut x = x0 + ((tile_i as f64 * tile_src - c.source_start) as f32) * self.pps;
                        while x < r.right() {
                            let tt = (tile_i as f64 * tile_src).max(0.0);
                            let b = (tt / THUMB_BUCKET_S) as i64;
                            let th = self
                                .thumbs
                                .get(&(aid.clone(), b))
                                .or_else(|| self.thumbs.get(&(aid.clone(), 0)));
                            if let Some(th) = th {
                                let left = x.max(r.left()).max(body.left());
                                let right = (x + tile_w).min(r.right());
                                if right > left {
                                    let tr2 = egui::Rect::from_min_max(
                                        egui::pos2(left, film_top),
                                        egui::pos2(right, r.bottom()),
                                    );
                                    let u0 = ((left - x) / tile_w).clamp(0.0, 1.0);
                                    let u1 = ((right - x) / tile_w).clamp(0.0, 1.0);
                                    p.image(
                                        th.id(),
                                        tr2,
                                        egui::Rect::from_min_max(egui::pos2(u0, 0.0), egui::pos2(u1, 1.0)),
                                        egui::Color32::from_white_alpha(210),
                                    );
                                }
                            }
                            x += tile_w;
                            tile_i += 1;
                        }
                    }
                }
                if strip_h > 0.0 {
                    let strip = egui::Rect::from_min_max(r.min, egui::pos2(r.right(), r.top() + strip_h));
                    p.rect_filled(
                        strip,
                        egui::Rounding { nw: 4.0, ne: 4.0, sw: 0.0, se: 0.0 },
                        if is_pop { egui::Color32::from_rgb(200, 110, 30) } else { color },
                    );
                    if strip.width() > 30.0 {
                        let name = c
                            .asset_id
                            .as_ref()
                            .and_then(|a| self.doc.asset_names.get(a))
                            .cloned()
                            .unwrap_or_default();
                        let label = if is_pop { format!("飛び出し | {name}") } else { name };
                        let max_chars = ((strip.width() - 10.0) / 7.0) as usize;
                        let shown: String = label.chars().take(max_chars.max(1)).collect();
                        p.text(
                            egui::pos2(strip.left() + 5.0, strip.center().y),
                            egui::Align2::LEFT_CENTER,
                            shown,
                            egui::FontId::proportional(9.5),
                            egui::Color32::from_white_alpha(235),
                        );
                    }
                    // 速度バッジ: 等速≠1x は「1.5x」、ランプは「⚡」
                    let spd_badge = if !c.speed_keys.is_empty() {
                        Some("⚡ランプ".to_string())
                    } else if (c.speed - 1.0).abs() > 1e-9 {
                        Some(format!("{}x", (c.speed * 100.0).round() / 100.0))
                    } else {
                        None
                    };
                    if let Some(b) = spd_badge {
                        if strip.width() > 60.0 {
                            p.text(
                                egui::pos2(strip.right() - 4.0, strip.center().y),
                                egui::Align2::RIGHT_CENTER,
                                b,
                                egui::FontId::proportional(9.0),
                                egui::Color32::from_rgb(255, 220, 120),
                            );
                        }
                    }
                }
                // スピードランプの速度カーブ帯（対数スケール 0.25x..4x を高さへ）
                if !c.speed_keys.is_empty() && tr.kind != "audio" && r.width() > 20.0 {
                    let n = ((r.width() / 3.0) as usize).max(2);
                    let mut prev: Option<egui::Pos2> = None;
                    for i in 0..=n {
                        let frac = i as f64 / n as f64;
                        let t = c.timeline_start + frac * (c.timeline_end - c.timeline_start);
                        let v = c.rate_at(t).clamp(0.25, 4.0);
                        let y01 = ((v.ln() - 0.25f64.ln()) / (4.0f64.ln() - 0.25f64.ln())) as f32;
                        let y = r.bottom() - 2.0 - y01 * (r.height() - strip_h - 4.0).max(4.0);
                        let pt = egui::pos2(r.left() + (frac as f32) * r.width(), y);
                        if let Some(pp) = prev {
                            p.line_segment(
                                [pp, pt],
                                egui::Stroke::new(
                                    1.5,
                                    egui::Color32::from_rgba_unmultiplied(255, 220, 120, 200),
                                ),
                            );
                        }
                        prev = Some(pt);
                    }
                }
                if tr.kind != "audio" && c.link_id.is_some() {
                    // unified A/V: waveform ribbon along the clip's bottom quarter
                    if let Some((spb, pk)) = c.asset_id.as_ref().and_then(|a| self.peaks.get(a)) {
                        let base_y = r.bottom() - 1.0;
                        let amp = (r.height() * 0.26).min(12.0);
                        let n = ((r.width() / 2.0) as usize).max(1);
                        for i in 0..n {
                            let x = r.left() + (i as f32) * 2.0;
                            let tt = c.src_at(
                                c.timeline_start
                                    + (i as f64 / n as f64) * (c.timeline_end - c.timeline_start),
                            );
                            let idx = (tt / spb) as usize;
                            let v = pk.get(idx).copied().unwrap_or(0.0).min(1.0);
                            p.line_segment(
                                [egui::pos2(x, base_y), egui::pos2(x, base_y - v * amp)],
                                egui::Stroke::new(1.4, egui::Color32::from_rgba_unmultiplied(55, 215, 175, 130)),
                            );
                        }
                    }
                }
                if tr.kind == "audio" {
                    if let Some((spb, pk)) = c.asset_id.as_ref().and_then(|a| self.peaks.get(a)) {
                        let mid = r.center().y;
                        let half = r.height() * 0.44;
                        let n = ((r.width() / 2.0) as usize).max(1);
                        for i in 0..n {
                            let x = r.left() + (i as f32) * 2.0;
                            let tt = c.src_at(
                                c.timeline_start
                                    + (i as f64 / n as f64) * (c.timeline_end - c.timeline_start),
                            );
                            let idx = (tt / spb) as usize;
                            let v = pk.get(idx).copied().unwrap_or(0.0).min(1.0).max(0.04);
                            p.line_segment(
                                [egui::pos2(x, mid + v * half), egui::pos2(x, mid - v * half)],
                                egui::Stroke::new(1.4, egui::Color32::from_rgb(45, 190, 155)),
                            );
                        }
                    }
                }
                if self.assistant.production_at.map(|t|t.elapsed().as_secs()<10).unwrap_or(false) {
                    let working=self.assistant.production.iter().any(|op| {
                        if !matches!(op["category"].as_str(), Some("editing" | "generation")) { return false; }
                        let ids=op["clip_ids"].as_array();
                        if ids.map(|v|!v.is_empty()).unwrap_or(false) {
                            return ids.unwrap().iter().any(|id|id.as_str()==Some(c.id.as_str()));
                        }
                        match op["tool"].as_str().unwrap_or("") {
                            "generate_speech" => tr.kind=="audio",
                            "generate_video" | "generate_image" => c.asset_id.is_some() && tr.kind!="audio",
                            _ => false,
                        }
                    });
                    if working {
                        let phase=ui.input(|i|i.time) as f32;
                        let strength=0.55+0.35*(phase*3.0).sin();
                        p.rect_stroke(r.shrink(1.0),4.0,egui::Stroke::new(2.0,egui::Color32::from_rgba_unmultiplied(150,235,201,(strength*255.0) as u8)));
                        let x=r.left()+((phase*0.35).fract())*r.width();
                        p.line_segment([egui::pos2(x,r.top()+2.0),egui::pos2(x,r.bottom()-2.0)],egui::Stroke::new(2.0,egui::Color32::from_rgba_unmultiplied(180,240,220,110)));
                        ui.ctx().request_repaint_after(std::time::Duration::from_millis(33));
                    }
                }
                let sel = self.selected.contains(&c.id);
                let hovered = pointer.map(|pt| r.contains(pt)).unwrap_or(false);
                p.rect_stroke(
                    r,
                    4.0,
                    if sel {
                        egui::Stroke::new(2.0, egui::Color32::WHITE)
                    } else if hovered && !tr.locked {
                        egui::Stroke::new(1.5, egui::Color32::from_gray(160))
                    } else {
                        egui::Stroke::new(1.0, egui::Color32::from_gray(12))
                    },
                );
                if sel {
                    // trim handles on the selected clip's edges
                    for hx in [r.left(), r.right()] {
                        p.rect_filled(
                            egui::Rect::from_center_size(egui::pos2(hx, r.center().y), egui::vec2(5.0, (lane_h * 0.55).min(22.0))),
                            2.0,
                            egui::Color32::WHITE,
                        );
                    }
                }
                if let Some(pt) = pointer {
                    // matches the selection-independent trim hit: inside zone scales with
                    // clip width, outside capture 10px
                    let inner = (r.width() * 0.33).clamp(4.0, 10.0);
                    let edge_hit = if r.contains(pt) { inner } else { 10.0 };
                    if r.expand2(egui::vec2(10.0, 0.0)).contains(pt)
                        && ((pt.x - r.left()).abs() <= edge_hit || (pt.x - r.right()).abs() <= edge_hit)
                    {
                        ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeHorizontal);
                    } else if r.contains(pt)
                        && {
                            let on_audio_lane = tr.kind == "audio";
                            let (ribbon, min_h) = if on_audio_lane { (10.0, 20.0) } else { (14.0, 40.0) };
                            pt.y > r.bottom() - ribbon
                                && r.height() >= min_h
                                && c.asset_id.is_some()
                                && (c.link_id.is_some() || on_audio_lane)
                        }
                    {
                        // waveform ribbon = volume zone
                        ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeVertical);
                    }
                }
                if !tr.locked {
                    hits.push((r, c.id.clone()));
                    marquee_hits.push((r, c.id.clone()));
                }
                clips_drawn += 1;
            }
        }

        if self.hover_lane == Some(NEW_BOTTOM_LANE) && matches!(self.drag, Drag::Move { .. }) {
            if let Some(&(_, y0, lh)) = lane_tops.last() {
                let r = egui::Rect::from_min_max(egui::pos2(body.left(), y0 + lh), egui::pos2(body.right(), (y0 + lh + 40.0).min(body.bottom())));
                p.rect_filled(r, 0.0, egui::Color32::from_rgba_unmultiplied(120, 170, 255, 34));
                p.line_segment([egui::pos2(r.left(), r.top()), egui::pos2(r.right(), r.top())], egui::Stroke::new(2.0, egui::Color32::from_rgb(120, 180, 255)));
            }
        }
        if self.hover_lane == Some(NEW_TOP_LANE) && matches!(self.drag, Drag::Move { .. }) {
            if let Some(r) = new_top_drop {
                p.rect_filled(r, 0.0, egui::Color32::from_rgba_unmultiplied(120, 170, 255, 34));
                p.line_segment(
                    [egui::pos2(r.left(), r.bottom()), egui::pos2(r.right(), r.bottom())],
                    egui::Stroke::new(2.0, egui::Color32::from_rgb(120, 180, 255)),
                );
            }
        }

        // サブタイムラインモード: 区間外のレーンを暗転（クリップより前面に塗る＝
        // 「ここは再生・書き出しに含まれない」を見せる）＋イン点待ちの緑縦線
        if self.on_sub_tab() {
            let subs = self.sub_ranges();
            let x_of = |t: f64| body.left() + t as f32 * self.pps - self.scroll_x;
            if !subs.is_empty() {
                let mut edges: Vec<(f64, f64)> = Vec::new();
                let mut prev = 0.0f64;
                for &(a, b) in &subs {
                    if a > prev {
                        edges.push((prev, a));
                    }
                    prev = prev.max(b);
                }
                edges.push((prev, f64::MAX));
                for (a, b) in edges {
                    let x0 = x_of(a).max(body.left());
                    let x1 = if b == f64::MAX { body.right() } else { x_of(b).min(body.right()) };
                    if x1 <= x0 {
                        continue;
                    }
                    p.rect_filled(
                        egui::Rect::from_min_max(
                            egui::pos2(x0, body.top() + 18.0),
                            egui::pos2(x1, rect.bottom()),
                        ),
                        0.0,
                        egui::Color32::from_rgba_unmultiplied(0, 0, 0, 110),
                    );
                }
            }
            if let Some(a) = self.sub_in {
                let x = x_of(a);
                if x >= body.left() && x <= body.right() {
                    p.line_segment(
                        [egui::pos2(x, body.top()), egui::pos2(x, rect.bottom())],
                        egui::Stroke::new(2.0, egui::Color32::from_rgb(0, 210, 140)),
                    );
                }
            }
        }
        let hx = body.left() + (self.t as f32) * self.pps - self.scroll_x;
        if hx >= body.left() && hx <= body.right() {
            p.line_segment(
                [egui::pos2(hx, body.top()), egui::pos2(hx, rect.bottom())],
                egui::Stroke::new(1.5, UI_PLAYHEAD),
            );
            // grab handle on the ruler
            p.add(egui::Shape::convex_polygon(
                vec![
                    egui::pos2(hx - 6.0, body.top()),
                    egui::pos2(hx + 6.0, body.top()),
                    egui::pos2(hx, body.top() + 11.0),
                ],
                UI_PLAYHEAD,
                egui::Stroke::NONE,
            ));
        }
        // snap guide while dragging
        if let Some(st) = self.snap_line {
            let sx = body.left() + (st as f32) * self.pps - self.scroll_x;
            if sx >= body.left() && sx <= body.right() {
                p.line_segment(
                    [egui::pos2(sx, body.top()), egui::pos2(sx, rect.bottom())],
                    egui::Stroke::new(1.0, egui::Color32::from_rgb(255, 220, 90)),
                );
            }
        }

        if let Some((ti, key, val)) = flag_click {
            self.apply_edit(true, move |raw| edits::set_track_flag(raw, ti, &key, val));
            self.push_req(false);
        }
        if let Some(ti) = lane_delete {
            self.apply_edit(true, move |raw| edits::delete_track(raw, ti));
            self.drag_lane_tops = None;
            self.push_req(false);
        }
        // ---- interactions: trim edges > move body > scrub empty space ----
        let to_t = |scroll_x: f32, pps: f32, x: f32| ((scroll_x + (x - body.left())) / pps).max(0.0) as f64;
        // サブタイムライン: ルーラーの緑帯を右クリック=その区間を削除
        if self.on_sub_tab() && resp.secondary_clicked() {
            if let Some(pos) = resp.interact_pointer_pos() {
                if pos.y <= body.top() + 18.0 {
                    let t = to_t(self.scroll_x, self.pps, pos.x);
                    let rs = self.sub_ranges();
                    if let Some(k) = rs.iter().position(|&(a, b)| t >= a && t <= b) {
                        let (a, b) = rs[k];
                        let mut rest = rs.clone();
                        rest.remove(k);
                        self.apply_edit(true, move |raw| edits::set_subtimeline_ranges(raw, &rest));
                        self.toast(&format!(
                            "区間を削除: {:02}:{:02}〜{:02}:{:02}",
                            a as i64 / 60, a as i64 % 60, b as i64 / 60, b as i64 % 60
                        ));
                        self.push_req(false);
                    }
                }
            }
        }
        // selection & drag arming happen ON PRESS (standard NLE feel) — the old
        // clicked()/drag_started() pair depended on release timing and a clean previous
        // drag state, which made selection feel unreliable
        let pressed_here = resp.hovered() && ui.input(|i| i.pointer.primary_pressed());
        if pressed_here {
            self.drag = Drag::None; // clear any stale drag state
        }
        if pressed_here || resp.drag_started() {
            // Filmora semantics: touching the timeline while playing pauses playback FIRST
            // (its own logs show Pause -> seek -> auto Play). This also kills the bug where
            // the running clock overwrote the clicked position on release, cancelling the
            // jump ("映像だけ飛んでヘッドは元の場所" / seconds of frozen video).
            let was_playing = self.playing;
            if was_playing {
                self.t = f64::from_bits(self.shared.clock_bits.load(Ordering::Relaxed));
                self.playing = false;
                if resp.drag_started() {
                    self.resume_on_release = true; // resume when the drag ends
                } else {
                    self.resume_pending = Some(Instant::now()); // plain click: resume ASAP
                }
                self.push_req(false);
            }
            if let Some(pos) = resp.interact_pointer_pos() {
                // edge grab = trim, SELECTION-INDEPENDENT (requiring pre-selection made a
                // fresh clip's edge read as Move — "広げようとすると全体が動く"). Inside
                // zone scales with clip width so narrow clips keep a grabbable body;
                // outside capture (widening) reaches 10px past the edge unless the
                // pointer is inside a NEIGHBOUR clip's body (that body wins).
                let edge_hit = hits
                    .iter()
                    .filter_map(|(r, id)| {
                        if !r.expand2(egui::vec2(10.0, 0.0)).contains(pos) {
                            return None;
                        }
                        let inside = r.contains(pos);
                        let selected = self.selected.contains(id);
                        // ポインタが別クリップの本体内なら外側キャプチャは譲る — ただし
                        // 「選択中クリップのエッジ」だけは例外。密着カットでは左端の白い
                        // ハンドル(境界中央)の左半分が前のクリップの本体に落ち、掴んだ
                        // つもりの左端が前クリップの右端トリムに化けていた（右へ=前が
                        // 重なって頭が消え短縮に見える/左へ=前が縮んで隙間、の報告バグ）
                        if !inside && !selected && hits.iter().any(|(rb, _)| rb.contains(pos)) {
                            return None; // pointer is in another clip's body
                        }
                        let edge_px = (r.width() * 0.33).clamp(4.0, 10.0);
                        let dl = (pos.x - r.left()).abs();
                        let dr = (pos.x - r.right()).abs();
                        let dist = dl.min(dr);
                        let hit_edge = if inside { dist <= edge_px } else { dist <= 10.0 };
                        hit_edge.then_some((selected, dist, *r, id.clone(), dl <= dr))
                    })
                    // 選択中クリップのエッジを最優先、その中で距離最小
                    .min_by(|a, b| {
                        (!a.0, a.1).partial_cmp(&(!b.0, b.1)).unwrap_or(std::cmp::Ordering::Equal)
                    })
                    .map(|(_, _, r, id, left)| (r, id, Some(left)));
                let body_hit = edge_hit.or_else(|| {
                    hits.iter()
                        .rev()
                        .find(|(r, _)| r.expand2(egui::vec2(4.0, 0.0)).contains(pos))
                        .map(|(r, id)| (*r, id.clone(), None))
                });
                let hit = body_hit;
                match hit {
                    Some((r, id, edge)) => {
                        if resp.double_clicked() {
                            if let Some(c) = self
                                .doc
                                .seq
                                .tracks
                                .iter()
                                .flat_map(|tr| tr.clips.iter())
                                .find(|c| c.id == *id)
                            {
                                if let Some(txt) = &c.text {
                                    let original = self.doc.raw.clone();
                                    self.pending_undo = Some(original.clone());
                                    self.caption_edit = Some((c.id.clone(), txt.clone(), original));
                                }
                            }
                        }
                        if !self.selected.contains(&id) {
                            if ui.input(|i| i.modifiers.ctrl) {
                                self.selected.push(id.clone());
                            } else {
                                self.selected = vec![id.clone()];
                            }
                            self.click_collapse = None;
                        } else if self.selected.len() > 1 && !ui.input(|i| i.modifiers.ctrl) {
                            // 複数選択中のクリップを「動かさずにクリック」したら、離した
                            // 時点でそのクリップ単独選択に絞る。押下時に絞らないのは
                            // グループごと掴んでドラッグ移動する操作を殺さないため
                            self.click_collapse = Some(id.clone());
                        } else {
                            self.click_collapse = None;
                        }
                        let ids = edits::expand_links(&self.doc.raw, &self.selected);
                        if self.drag == Drag::None {
                            self.pending_undo = Some(self.doc.raw.clone());
                            // volume ribbon: linked audio rides its visual clip's bottom
                            // strip; a STANDALONE audio clip (BGM) sits on the short 30px
                            // audio lane, so its zone is thinner and has no 40px gate.
                            let vol_meta = self
                                .doc
                                .seq
                                .tracks
                                .iter()
                                .flat_map(|tr| tr.clips.iter().map(move |c| (tr.kind.as_str(), c)))
                                .find(|(_, c)| c.id == *id)
                                .map(|(k, c)| {
                                    (k == "audio",
                                     c.asset_id.is_some() && (c.link_id.is_some() || k == "audio"),
                                     c.volume)
                                });
                            let (on_audio_lane, can_vol, v0) = vol_meta.unwrap_or((false, false, 1.0));
                            let (ribbon, min_h) = if on_audio_lane { (10.0, 20.0) } else { (14.0, 40.0) };
                            let vol_zone = pos.y > r.bottom() - ribbon
                                && r.height() >= min_h
                                && edge.is_none()
                                && (pos.x - r.left()).abs() >= 10.0
                                && (pos.x - r.right()).abs() >= 10.0
                                && can_vol;
                            if vol_zone {
                                self.drag = Drag::Volume { ids, start_y: pos.y, start_vol: v0 };
                            } else if let Some(left) = edge {
                                let edges = self
                                    .doc
                                    .seq
                                    .tracks
                                    .iter()
                                    .flat_map(|tr| tr.clips.iter())
                                    .filter(|c| ids.contains(&c.id))
                                    .map(|c| if left { c.timeline_start } else { c.timeline_end });
                                let last_t = if left { edges.fold(f64::MAX, f64::min) } else { edges.fold(f64::MIN, f64::max) };
                                let last_t = if last_t.is_finite() { last_t } else { to_t(self.scroll_x, self.pps, pos.x) };
                                eprintln!(
                                    "TRIMPRESS left={left} edge_t={last_t:.3} ids={:?}",
                                    ids.first()
                                );
                                self.drag = Drag::Trim { ids, left, last_t };
                            } else {
                                let ts = self
                                    .doc
                                    .seq
                                    .tracks
                                    .iter()
                                    .flat_map(|tr| tr.clips.iter())
                                    .find(|c| c.id == *id)
                                    .map(|c| c.timeline_start)
                                    .unwrap_or(0.0);
                                // 付着クリップ(メインレーンのクリップに頭が載っている
                                // 前面レーンのクリップ+そのリンク音声)は削除と同様、
                                // 移動でも親と一緒に時間シフトさせる（Filmoraの規則）。
                                // メンバーはドラッグ開始時に確定。
                                self.move_attached = {
                                    let a = edits::attached_to(&self.doc.raw, &ids);
                                    if a.is_empty() {
                                        a
                                    } else {
                                        edits::expand_links(&self.doc.raw, &a)
                                            .into_iter()
                                            .filter(|i| !ids.contains(i))
                                            .collect()
                                    }
                                };
                                self.drag = Drag::Move {
                                    ids,
                                    anchor_id: id.clone(),
                                    grab: to_t(self.scroll_x, self.pps, pos.x),
                                    orig: ts,
                                    applied: 0.0,
                                };
                                self.drag_press = Some(pos);
                                self.drag_engaged = false;
                                self.hover_lane = None;
                            }
                        }
                    }
                    None => {
                        // ruler strip keeps the press-scrub feel; empty LANE space arms a
                        // marquee (drag = box-select, a tiny click still seeks on release)
                        if pos.y <= body.top() + 18.0 {
                            // サブタイムラインの緑帯の端（イン点/アウト点）ドラッグが最優先。
                            // ドラッグ中は掴んだ時点の区間リスト（未マージ）を基準に編集し、
                            // 隣の区間に触れた瞬間に合体して index がズレるのを防ぐ
                            if self.on_sub_tab() {
                                let subs = self.sub_ranges();
                                let mut best: Option<(usize, bool, f32)> = None;
                                for (k, &(a, b)) in subs.iter().enumerate() {
                                    for (t_edge, is_in) in [(a, true), (b, false)] {
                                        let x = body.left() + t_edge as f32 * self.pps - self.scroll_x;
                                        let d = (pos.x - x).abs();
                                        if d <= 6.0 && best.map(|(_, _, bd)| d < bd).unwrap_or(true) {
                                            best = Some((k, is_in, d));
                                        }
                                    }
                                }
                                if let Some((k, is_in, _)) = best {
                                    self.pending_undo = Some(self.doc.raw.clone());
                                    self.sub_edge_drag = Some((subs, k, is_in));
                                }
                            }
                            // render-range edge flags win over scrub within ±6px
                            // （青帯はメインタブ専用）
                            if self.sub_edge_drag.is_none() && !self.on_sub_tab() {
                                if let Some((ra, rb)) = self.export_range {
                                    let xa = body.left() + ra as f32 * self.pps - self.scroll_x;
                                    let xb = body.left() + rb as f32 * self.pps - self.scroll_x;
                                    if (pos.x - xa).abs() <= 6.0 {
                                        self.range_drag = Some(true);
                                    } else if (pos.x - xb).abs() <= 6.0 {
                                        self.range_drag = Some(false);
                                    }
                                }
                            }
                            if self.sub_edge_drag.is_none() && self.range_drag.is_none() {
                                self.selected.clear();
                                self.drag = Drag::Scrub;
                                let raw_t = to_t(self.scroll_x, self.pps, pos.x);
                                let nt = self.snap_playhead(raw_t);
                                self.snap_line = ((nt - raw_t).abs() > 1e-9).then_some(nt);
                                self.t = nt;
                                self.push_req(false);
                            }
                        } else {
                            if !ui.input(|i| i.modifiers.ctrl) {
                                self.selected.clear();
                            }
                            self.drag = Drag::Marquee {
                                anchor_t: to_t(self.scroll_x, self.pps, pos.x),
                                anchor_y: pos.y,
                            };
                        }
                    }
                }
            }
        }
        if resp.dragged() {
            if let Some(pos) = resp.interact_pointer_pos() {
                if let Some((base, k, is_in)) = self.sub_edge_drag.clone() {
                    // 緑帯の端ドラッグ: フレーム量子化・1フレーム最小幅。掴んだ時点の
                    // リスト base を毎フレーム基準にする（保存時に読み側でマージされる）
                    let f = 1.0 / self.timeline_fps();
                    let t_new = self.grid_quantize(to_t(self.scroll_x, self.pps, pos.x).max(0.0));
                    let mut rs = base;
                    if let Some(r) = rs.get_mut(k) {
                        if is_in {
                            r.0 = t_new.min(r.1 - f).max(0.0);
                        } else {
                            r.1 = t_new.max(r.0 + f);
                        }
                        self.apply_edit(false, move |raw| edits::set_subtimeline_ranges(raw, &rs));
                    }
                }
                if let Some(is_in) = self.range_drag {
                    // drag a render-range edge: frame-quantized, kept ordered with a
                    // one-frame minimum span
                    let f = 1.0 / self.timeline_fps();
                    let t_new = self.grid_quantize(to_t(self.scroll_x, self.pps, pos.x).max(0.0) as f64);
                    if let Some((ra, rb)) = self.export_range {
                        self.export_range = Some(if is_in {
                            (t_new.min(rb - f), rb)
                        } else {
                            (ra, t_new.max(ra + f))
                        });
                    }
                }
                match self.drag.clone() {
                    Drag::Scrub => {
                        let raw_t = to_t(self.scroll_x, self.pps, pos.x);
                        let nt = self.snap_playhead(raw_t);
                        self.snap_line = ((nt - raw_t).abs() > 1e-9).then_some(nt);
                        self.t = nt;
                        self.push_req(true);
                    }
                    Drag::Move { ids, anchor_id, grab, orig, applied } => 'move_gate: {
                        // 実移動（8px超 or 押下レーンの帯から離脱）までは一切動かさない:
                        // 長押しだけでドロップレーンが展開して画面が動く現象の根治。
                        // 未発火のまま離せば従来どおり「クリック＝選択」で終わる。
                        if !self.drag_engaged {
                            let press = self.drag_press.unwrap_or(pos);
                            let band = self
                                .doc
                                .seq
                                .tracks
                                .iter()
                                .position(|tr| tr.clips.iter().any(|c| c.id == anchor_id))
                                .and_then(|at| {
                                    self.last_lane_tops.iter().find(|&&(i, _, _)| i == at).copied()
                                })
                                .map(|(_, y0, lh)| (y0, y0 + lh));
                            let dist = ((pos.x - press.x).powi(2) + (pos.y - press.y).powi(2)).sqrt();
                            let outside = band.map_or(false, |(y0, y1)| pos.y < y0 || pos.y > y1);
                            if dist > 8.0 || outside {
                                self.drag_engaged = true; // 次フレームから凍結展開レイアウトで移動処理
                            }
                            break 'move_gate;
                        }
                        // vertical: the clip FOLLOWS the pointer's lane live (not on release)
                        let prev_hover = self.hover_lane;
                        // 最上段レーンより上なら帯の外でも新規レーン扱い
                        // （上へは何本でも増やせる）
                        let above_top = body.contains(pos)
                            && lane_tops.first().map(|&(_, y0, _)| pos.y < y0).unwrap_or(false);
                        // 最下段レーンより下 = 新規音声レーン行き（音声クリップのみ）
                        let below_bottom = body.contains(pos)
                            && lane_tops.last().map(|&(_, y0, lh)| pos.y > y0 + lh).unwrap_or(false);
                        self.hover_lane = if above_top {
                            Some(NEW_TOP_LANE)
                        } else if below_bottom {
                            Some(NEW_BOTTOM_LANE)
                        } else {
                            lane_tops
                                .iter()
                                .find(|&&(_, y0, lh)| pos.y >= y0 && pos.y <= y0 + lh)
                                .map(|&(ti, _, _)| ti)
                        };
                        if let Some(target) = self.hover_lane {
                            // 音声クリップ（リンクされていない BGM/ナレーション）のレーン移動:
                            // 別の音声レーンへ、または最下段より下で新規音声レーンへ
                            let auds: Vec<String> = self
                                .doc
                                .seq
                                .tracks
                                .iter()
                                .filter(|tr| tr.kind == "audio")
                                .flat_map(|tr| tr.clips.iter())
                                .filter(|c| ids.contains(&c.id) && c.link_id.is_none())
                                .map(|c| c.id.clone())
                                .collect();
                            if !auds.is_empty() && target != NEW_TOP_LANE {
                                let is_new = target == NEW_BOTTOM_LANE;
                                let tgt_audio = !is_new && self.doc.seq.tracks.get(target).map(|t| t.kind == "audio" && !t.locked).unwrap_or(false);
                                let already = !is_new && self.doc.seq.tracks.get(target).map(|t| t.clips.iter().any(|c| auds.contains(&c.id))).unwrap_or(true);
                                if (is_new && prev_hover != Some(NEW_BOTTOM_LANE)) || (tgt_audio && !already) {
                                    let salt = lane_salt();
                                    let tgt = if is_new { None } else { Some(target) };
                                    eprintln!("AUDIOLANE move: {} clip(s) -> {:?}", auds.len(), tgt);
                                    self.apply_edit(false, move |raw| edits::move_audio_clips_to_track(raw, &auds, tgt, salt));
                                    self.drag_lane_tops = None;
                                }
                            }
                            if target == NEW_TOP_LANE {
                                let vids: Vec<String> = self
                                    .doc
                                    .seq
                                    .tracks
                                    .iter()
                                    .filter(|tr| tr.kind != "audio")
                                    .flat_map(|tr| tr.clips.iter())
                                    .filter(|c| ids.contains(&c.id))
                                    .map(|c| c.id.clone())
                                    .collect();
                                // ゾーン滞在中に毎フレーム発火させない（edits側の
                                // 二重生成ガードで無害だが、毎回のapply_editが
                                // CACHE_CLEARを起こして無駄）→ ゾーン進入時のみ
                                if !vids.is_empty() && prev_hover != Some(NEW_TOP_LANE) {
                                    eprintln!("NEWLANE drop fired for {} clip(s)", vids.len());
                                    self.apply_edit(false, move |raw| edits::move_group_to_new_top_track(raw, &vids, &anchor_id));
                                    // トラック構成が変わったので凍結レイアウトを作り直す
                                    self.drag_lane_tops = None;
                                }
                            } else {
                            let tk_ok = self
                                .doc
                                .seq
                                .tracks
                                .get(target)
                                .map(|t| t.kind != "audio")
                                .unwrap_or(false);
                            let already = self
                                .doc
                                .seq
                                .tracks
                                .get(target)
                                .map(|t| t.clips.iter().any(|c| ids.contains(&c.id)))
                                .unwrap_or(true);
                            if tk_ok && !already {
                                let vids: Vec<String> = self
                                    .doc
                                    .seq
                                    .tracks
                                    .iter()
                                    .filter(|tr| tr.kind != "audio")
                                    .flat_map(|tr| tr.clips.iter())
                                    .filter(|c| ids.contains(&c.id))
                                    .map(|c| c.id.clone())
                                    .collect();
                                if !vids.is_empty() {
                                    eprintln!("LANEMOVE fired: {} clip(s) -> track {}", vids.len(), target);
                                    self.apply_edit(false, move |raw| edits::move_group_to_track(raw, &vids, &anchor_id, target));
                                    // 移動で空トラックが消えて構成が変わりうる。
                                    // 凍結レイアウトを作り直す（NEWLANE側と同じ扱い）
                                    self.drag_lane_tops = None;
                                }
                            }
                            }
                        }
                        let raw_t = orig + (to_t(self.scroll_x, self.pps, pos.x) - grab);
                        let want = self.snap(raw_t, &ids);
                        self.snap_line = ((want - raw_t).abs() > 1e-9).then_some(want);
                        let dt = want - orig - applied;
                        // 付着クリップも同じ時間シフトに含める（レーンは変えない —
                        // レーン変更(LANEMOVE/NEWLANE)は選択本体だけに適用される）
                        let move_ids: Vec<String> = ids
                            .iter()
                            .cloned()
                            .chain(self.move_attached.iter().cloned())
                            .collect();
                        let min_start = self
                            .doc
                            .seq
                            .tracks
                            .iter()
                            .flat_map(|tr| tr.clips.iter())
                            .filter(|c| move_ids.contains(&c.id))
                            .map(|c| c.timeline_start)
                            .fold(f64::MAX, f64::min);
                        let actual_dt = if min_start.is_finite() { dt.max(-min_start) } else { dt };
                        if actual_dt.abs() > 1e-4 {
                            self.apply_edit(false, |raw| edits::move_clips(raw, &move_ids, actual_dt));
                            if let Drag::Move { applied, .. } = &mut self.drag {
                                *applied += actual_dt;
                            }
                        }
                    }
                    Drag::Trim { ids, left, last_t } => {
                        let raw_t = to_t(self.scroll_x, self.pps, pos.x);
                        let mut nt = self.snap(raw_t, &ids);
                        // スナップ許容は 8px/pps ＝ズームが荒いと1秒超になり、エッジ密集
                        // タイムラインでは nt が常にカット点へ量子化されて微調整トリムが
                        // d=0 に潰される（「左に広げられない」の一因）。トリム中は
                        // 実時間 0.25s を上限にする
                        if (nt - raw_t).abs() > 0.25 {
                            nt = self.grid_quantize(raw_t);
                        }
                        let requested = nt - last_t;
                        self.snap_line = ((nt - raw_t).abs() > 1e-9).then_some(nt);
                        // 静止画クリップにはソース時間の概念が無い＝両方向へ自由に
                        // 伸ばせる（従来は source_start=0 の制限で左拡大が常にゼロ）
                        let stills: Vec<String> = self
                            .doc
                            .seq
                            .tracks
                            .iter()
                            .flat_map(|tr| tr.clips.iter())
                            .filter(|c| {
                                ids.contains(&c.id)
                                    && c.asset_id
                                        .as_ref()
                                        .map(|a| self.doc.asset_images.contains(a))
                                        .unwrap_or(false)
                            })
                            .map(|c| c.id.clone())
                            .collect();
                        let applied = std::cell::Cell::new(0.0f64);
                        {
                            let ap = &applied;
                            self.apply_edit(false, |raw| {
                                ap.set(edits::trim_clip_live_from(raw, &ids, left, last_t, nt, &stills));
                            });
                        }
                        // 実際に消化できた分だけ追跡値を進める。限界で止まった分の
                        // マウス移動を溜めない＝「見えない幅」と反転時の空白の根治
                        if let Drag::Trim { last_t, .. } = &mut self.drag {
                            *last_t += applied.get();
                        }
                        // 常設ログ: トリムが「効かない」報告の一次証拠（%TEMP%\done_app.log）
                        if applied.get().abs() > 1e-9 || (nt - last_t).abs() > 1e-9 {
                            eprintln!(
                                "TRIM_DBG left={left} last_t={last_t:.3} nt={nt:.3} applied={:.3} ids={:?}",
                                applied.get(),
                                ids.first()
                            );
                        }
                        // 伸ばせない限界を超えた領域では、動いているかのような
                        // 黄色いスナップ線を出さない（誤解の元＝報告バグ）
                        if (applied.get() - requested).abs() > 1e-4 {
                            self.snap_line = None;
                        }
                    }
                    Drag::Volume { ids, start_y, start_vol } => {
                        let vol = (start_vol + ((start_y - pos.y) as f64) / 90.0).clamp(0.0, 2.0);
                        self.apply_edit(false, |raw| edits::set_volume(raw, &ids, vol));
                        ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeVertical);
                        p.text(
                            pos + egui::vec2(12.0, -14.0),
                            egui::Align2::LEFT_CENTER,
                            format!("音量 {:.0}%", vol * 100.0),
                            egui::FontId::proportional(11.0),
                            egui::Color32::WHITE,
                        );
                    }
                    Drag::Marquee { anchor_t, anchor_y } => {
                        let ax = body.left() + (anchor_t as f32) * self.pps - self.scroll_x;
                        let r = egui::Rect::from_two_pos(egui::pos2(ax, anchor_y), pos);
                        self.marquee = Some(r);
                        self.selected = marquee_hits
                            .iter()
                            .filter(|(cr, _)| cr.intersects(r))
                            .map(|(_, id)| id.clone())
                            .collect();
                    }
                    Drag::None => {}
                }
            }
        }
        // marquee rectangle overlay (the logical rect can extend past the viewport after
        // edge auto-scroll — only the visible part is drawn, never over the lane headers)
        if let Some(r) = self.marquee {
            let vis = r.intersect(body);
            p.rect_filled(vis, 0.0, egui::Color32::from_rgba_unmultiplied(90, 160, 255, 24));
            p.rect_stroke(vis, 0.0, egui::Stroke::new(1.0, egui::Color32::from_rgb(120, 180, 255)));
        }
        // Edge auto-scroll while holding the playhead, a clip selection, or a marquee.  A
        // clip drag uses scroll_x in its time mapping, so advancing the viewport here also
        // keeps moving the held block on the next repaint even when the pointer stays at
        // the edge; the marquee anchor is a timeline time for the same reason.
        // Merely hovering near an edge never moves the view, and a marquee only scrolls
        // once it is an actual box (a tiny press-near-the-edge must stay a click-seek).
        let marquee_scrolls = matches!(&self.drag, Drag::Marquee { .. })
            && self
                .marquee
                .map(|r| r.width().max(r.height()) > 4.0)
                .unwrap_or(false);
        if (matches!(&self.drag, Drag::Scrub | Drag::Move { .. }) || marquee_scrolls)
            && ui.input(|i| i.pointer.primary_down())
        {
            if let Some(pt) = ui.input(|i| i.pointer.interact_pos()) {
                const EDGE: f32 = 26.0;
                let speed = |d: f32| ((EDGE - d) / EDGE * 14.0).clamp(2.0, 14.0);
                if pt.x < body.left() + EDGE {
                    self.scroll_x = (self.scroll_x - speed(pt.x - body.left())).max(0.0);
                    ui.ctx().request_repaint();
                } else if pt.x > body.right() - EDGE {
                    let max_sx = ((self.dur as f32) * self.pps - body.width()).max(0.0);
                    self.scroll_x = (self.scroll_x + speed(body.right() - pt.x)).min(max_sx);
                    ui.ctx().request_repaint();
                }
            }
        }
        // lane reorder: while a header is being dragged, dropping over another lane's
        // row moves the track there (live on release)
        if let Some(from) = self.lane_reorder {
            let released = ui.input(|i| i.pointer.any_released());
            if released {
                if let Some(pt) = ui.input(|i| i.pointer.interact_pos()) {
                    if let Some(&(to, _, _)) = lane_tops.iter().find(|&&(_, y0, lh)| pt.y >= y0 && pt.y <= y0 + lh) {
                        if to != from {
                            self.apply_edit(false, move |raw| edits::reorder_tracks(raw, from, to));
                        }
                    }
                }
                self.lane_reorder = None;
            }
        }
        let released_now = ui.input(|i| i.pointer.any_released());
        if released_now {
            self.range_drag = None;
            if self.sub_edge_drag.take().is_some() {
                self.push_req(false);
            }
        }
        if resp.drag_stopped() || (released_now && self.drag != Drag::None) {
            let prev = std::mem::replace(&mut self.drag, Drag::None);
            if let Drag::Marquee { anchor_t, .. } = &prev {
                let moved = self
                    .marquee
                    .map(|r| r.width().max(r.height()) > 4.0)
                    .unwrap_or(false);
                if !moved {
                    self.t = anchor_t.min(self.dur);
                }
                self.marquee = None;
            }
            eprintln!(
                "DRAGSTOP prev={} hover={:?}",
                match &prev {
                    Drag::None => "none",
                    Drag::Scrub => "scrub",
                    Drag::Move { .. } => "move",
                    Drag::Trim { .. } => "trim",
                    Drag::Marquee { .. } => "marquee",
                    Drag::Volume { .. } => "volume",
                },
                self.hover_lane
            );
            match &prev {
                Drag::Trim { ids, .. } => {
                    self.apply_edit(false, |raw| edits::settle_overlaps(raw, ids));
                }
                // Moving must never erase either an unselected destination clip or another
                // member of a multi-selection. Overlaps remain explicit and editable; trim
                // retains its established overwrite-on-settle behaviour.
                Drag::Move { .. } => {
                    // ジェスチャ確定: クリップが載ったままの無名(仮)レーンへ id を
                    // 付与して恒久レーンに昇格させる。以後そのレーンは空になっても
                    // prune に消されず表示され続ける＝レーンは減らない。
                    let needs_promote = self
                        .doc
                        .raw
                        .get(0)
                        .and_then(|r| r.get("timeline"))
                        .and_then(|t| t.get("sequence"))
                        .and_then(|s| s.get("tracks"))
                        .and_then(|t| t.as_array())
                        .map(|ts| {
                            ts.iter().any(|tr| {
                                tr.get("id").and_then(|v| v.as_str()).is_none()
                                    && tr
                                        .get("clips")
                                        .and_then(|c| c.as_array())
                                        .map(|c| !c.is_empty())
                                        .unwrap_or(false)
                            })
                        })
                        .unwrap_or(false);
                    if needs_promote {
                        let s = lane_salt();
                        self.apply_edit(false, move |raw| {
                            edits::promote_unnamed_occupied_tracks(raw, s)
                        });
                    }
                }
                _ => {}
            }
            // 複数選択中クリップの単純クリック（実移動なし）→ 単独選択へ絞る
            if matches!(&prev, Drag::Move { .. }) && !self.drag_engaged {
                if let Some(cid) = self.click_collapse.take() {
                    self.selected = vec![cid];
                }
            }
            self.click_collapse = None;
            let _ = &prev; // lane moves happen LIVE during the drag now
            self.move_attached.clear();
            self.hover_lane = None;
            self.snap_line = None;
            if self.resume_on_release {
                self.resume_on_release = false;
                self.resume_pending = Some(Instant::now());
            }
            self.push_req(false); // settle on full quality
        }

        // Direct media placement. Both an OS file drag and a drag from the media menu
        // resolve to the lane under the pointer and the visible timeline time. Locked and
        // audio lanes are not valid visual destinations.
        // `hover_pos` is cleared by egui on the mouse-up frame for some native
        // windowing backends.  A library-card drag was consequently visible over
        // the timeline, but its release had no target and was silently discarded.
        // `interact_pos` retains the pointer position through that release frame;
        // fall back to hover for an OS file drag, which has no egui interaction.
        let raw_media_pointer = ui.input(|i| i.pointer.interact_pos().or_else(|| i.pointer.hover_pos()));
        let hovered_os_media = ui.input(|i| {
            i.raw.hovered_files.iter().any(|f| {
                f.path.as_deref().map(is_timeline_media_path).unwrap_or(false)
            })
        });
        let hovered_os_audio = ui.input(|i| {
            i.raw.hovered_files.iter().any(|f| {
                f.path.as_deref().map(is_audio_path).unwrap_or(false)
            })
        });
        let os_dropped_any = ui.input(|i| !i.raw.dropped_files.is_empty());
        // While an OS file drag is over the window (or dropping this frame) egui has
        // no pointer at all — see os_cursor_in_ui. Prefer the live Win32 cursor there;
        // internal library-card drags keep using the normal egui pointer.
        let os_cursor = if hovered_os_media || hovered_os_audio || os_dropped_any {
            // Nothing but the initial HoveredFile event arrives during an OS drag, so
            // keep frames coming ourselves or the ghost/lane highlight freezes.
            ui.ctx().request_repaint();
            os_cursor_in_ui(ui.ctx())
        } else {
            None
        };
        let media_pointer = os_cursor.or(raw_media_pointer);
        // The ghost must show the REAL clip length from the moment it appears, or the
        // user cannot judge where it will land / what it will cover. Probe each hovered
        // file once and cache by path — the drop itself re-probes authoritatively.
        let os_hover_len = if hovered_os_media {
            let first: Option<std::path::PathBuf> = ui.input(|i| {
                i.raw
                    .hovered_files
                    .iter()
                    .filter_map(|f| f.path.clone())
                    .find(|p| is_timeline_media_path(p))
            });
            first.map(|p| {
                let key = p.to_string_lossy().replace(char::from(92), "/");
                *self.os_drag_durations.entry(key.clone()).or_insert_with(|| {
                    if is_image_path(&p) { 5.0 } else { probe_duration(&key).unwrap_or(5.0) }
                })
            })
        } else {
            None
        };
        // The drag only becomes a CLIP once the pointer actually enters the timeline
        // body: outside it (preview, panels…) the gesture stays "just a file" and both
        // ghost and drop resolution are off. Inside, a release must not require the
        // exact few pixels of a lane — backends report the point just outside the row
        // (or on a clip/header) — so snap to the closest unlocked visual lane. This is
        // the target used by the live ghost and by the final drop alike.
        let drop_target = media_pointer.and_then(|pt| {
            if !body.contains(pt) {
                return None;
            }
            // 「最上段レーンより上」は常に新規レーン行き。クリップ移動と同じ規則で、
            // 素材ドロップでもレーンを上へ何本でも増やせる。
            if lane_tops.first().map(|&(_, y0, _)| pt.y < y0).unwrap_or(false) {
                return Some(NEW_TOP_LANE);
            }
            lane_tops
                .iter()
                .filter(|&&(ti, _, _)| {
                    self.doc.seq.tracks.get(ti)
                        .map(|t| t.kind != "audio" && !t.locked)
                        .unwrap_or(false)
                })
                .min_by(|&&(_, y_a, h_a), &&(_, y_b, h_b)| {
                    let d_a = (pt.y - (y_a + h_a * 0.5)).abs();
                    let d_b = (pt.y - (y_b + h_b * 0.5)).abs();
                    d_a.partial_cmp(&d_b).unwrap_or(std::cmp::Ordering::Equal)
                })
                .map(|&(ti, _, _)| ti)
        });
        let drop_time = media_pointer.filter(|pt| body.contains(*pt)).map(|pt| {
            self.snap(
                ((self.scroll_x + pt.x - body.left()) / self.pps).max(0.0) as f64,
                &[],
            )
        });
        if (self.asset_drag.is_some() || hovered_os_media)
            && drop_target.is_some()
            && drop_time.is_some()
        {
            let ti = drop_target.unwrap();
            let (y0, lh) = if ti == NEW_TOP_LANE {
                // 新規レーンの着地帯: 現在の最上段のすぐ上に仮のレーン枠を描く
                let band = 26.0 * squeeze;
                let top = lane_tops.first().map(|&(_, y, _)| y).unwrap_or(body.top() + 30.0);
                ((top - band - 3.0).max(body.top()), band)
            } else {
                let (_, y0, lh) =
                    lane_tops.iter().find(|&&(i, _, _)| i == ti).copied().unwrap();
                (y0, lh)
            };
            let lane_rect = egui::Rect::from_min_max(
                egui::pos2(body.left(), y0),
                egui::pos2(body.right(), y0 + lh),
            );
            p.rect_filled(lane_rect, 0.0, egui::Color32::from_rgba_unmultiplied(70, 135, 220, 35));
            p.rect_stroke(lane_rect, 0.0, egui::Stroke::new(1.5, UI_ACCENT));
            let x = body.left() + drop_time.unwrap() as f32 * self.pps - self.scroll_x;
            // Materialise the prospective clip before release, at its TRUE length:
            // library assets carry a duration, OS-file drags use the probed cache
            // above. 5s only remains as the image/probe-failure fallback.
            let preview_len = self.asset_drag.as_ref()
                .and_then(|a| a.get("duration").and_then(|d| d.as_f64()))
                .or(os_hover_len)
                .unwrap_or(5.0) as f32;
            let w = (preview_len * self.pps).max(2.0).min(body.right() - x);
            let clip_rect = egui::Rect::from_min_size(egui::pos2(x, y0 + 3.0), egui::vec2(w.max(0.0), (lh - 6.0).max(4.0)));
            p.rect_filled(clip_rect, 3.0, egui::Color32::from_rgba_unmultiplied(70, 135, 220, 110));
            p.rect_stroke(clip_rect, 3.0, egui::Stroke::new(1.5, UI_ACCENT));
            p.line_segment(
                [egui::pos2(x, y0), egui::pos2(x, y0 + lh)],
                egui::Stroke::new(2.0, UI_ACCENT),
            );
            ui.ctx().set_cursor_icon(egui::CursorIcon::Copy);
        }
        // OS drag of an AUDIO file: preview lands on the AUDIO lane (wherever the
        // pointer is horizontally — the vertical lane is fixed).
        if hovered_os_audio {
            if let (Some(&(_, y0, lh)), Some(t)) = (
                lane_tops.iter().find(|&&(ti, _, _)| {
                    self.doc.seq.tracks.get(ti).map(|t| t.kind == "audio").unwrap_or(false)
                }),
                drop_time,
            ) {
                let lane_rect = egui::Rect::from_min_max(
                    egui::pos2(body.left(), y0),
                    egui::pos2(body.right(), y0 + lh),
                );
                p.rect_filled(lane_rect, 0.0, egui::Color32::from_rgba_unmultiplied(70, 200, 140, 35));
                p.rect_stroke(lane_rect, 0.0, egui::Stroke::new(1.5, UI_ACCENT));
                let x = body.left() + t as f32 * self.pps - self.scroll_x;
                p.line_segment(
                    [egui::pos2(x, y0), egui::pos2(x, y0 + lh)],
                    egui::Stroke::new(2.0, UI_ACCENT),
                );
                ui.ctx().set_cursor_icon(egui::CursorIcon::Copy);
            }
        }

        // A menu drag is an application-internal gesture, so clear it on every release,
        // but only mutate the timeline when it ended over a valid visual lane.
        if released_now && self.asset_drag.is_some() {
            let dragged = self.asset_drag.take();
            if let (Some(asset), Some(ti), Some(t)) = (dragged, drop_target, drop_time) {
                let ti = if ti == NEW_TOP_LANE { self.insert_new_top_lane() } else { ti };
                self.place_library_asset_at(&asset, t, ti);
            }
        }

        let (dropped_audio, dropped_media): (Vec<std::path::PathBuf>, Vec<std::path::PathBuf>) = ui
            .input(|i| {
                i.raw
                    .dropped_files
                    .iter()
                    .filter_map(|f| f.path.clone())
                    .filter(|path| is_timeline_media_path(path) || is_audio_path(path))
                    .collect::<Vec<_>>()
            })
            .into_iter()
            .partition(|path| is_audio_path(path));
        if !dropped_audio.is_empty() || !dropped_media.is_empty() {
            // Permanent evidence line for drop failures: says WHICH condition was
            // missing (egui pointer vs Win32 cursor vs lane/time resolution).
            eprintln!(
                "OSDROP media={} audio={} raw={:?} os_cursor={:?} target={:?} time={:?} body_x={:.0}..{:.0}",
                dropped_media.len(),
                dropped_audio.len(),
                raw_media_pointer,
                os_cursor,
                drop_target,
                drop_time,
                body.left(),
                body.right()
            );
        }
        if !dropped_audio.is_empty() {
            if let Some(t) = drop_time {
                for path in dropped_audio {
                    if let Err(e) = self.import_audio_at(&path, t) {
                        eprintln!("import audio: {e:#}");
                        self.toast("音声を追加できませんでした");
                    }
                }
            } else {
                // Released outside the timeline: the file stays "just a file" —
                // register it as room material, never place a clip.
                for path in dropped_audio {
                    self.register_media_path(&path);
                }
                self.toast("タイムライン外なので素材ライブラリに追加しました");
            }
        }
        if !dropped_media.is_empty() {
            if let (Some(ti), Some(t)) = (drop_target, drop_time) {
                if !self.has_timeline_media()
                    && self.doc.seq.frame_rate.is_none()
                    && dropped_media.iter().any(|p| !is_image_path(p))
                {
                    self.pending_initial_fps = dropped_media
                        .iter()
                        .filter(|p| !is_image_path(p))
                        .filter_map(|p| probe_frame_rate(&p.to_string_lossy()))
                        .collect();
                    self.pending_initial_imports.extend(dropped_media);
                } else {
                    let ti = if ti == NEW_TOP_LANE { self.insert_new_top_lane() } else { ti };
                    for path in dropped_media {
                        if let Err(e) = self.import_file_at(&path, t, ti) {
                            eprintln!("import: {e:#}");
                            self.toast("素材を追加できませんでした");
                        }
                    }
                }
            } else {
                // Same "just a file" contract for visual media dropped outside the
                // timeline (or into a room with no visible lane yet).
                for path in dropped_media {
                    self.register_media_path(&path);
                }
                self.toast("タイムライン外なので素材ライブラリに追加しました");
            }
        }

        p.text(
            egui::pos2(rect.left() + GUTTER + 6.0, rect.bottom() - 14.0),
            egui::Align2::LEFT_TOP,
            format!(
                "{} clips | {:02}:{:02}.{:02} | {}",
                clips_drawn,
                (self.t as i64) / 60,
                (self.t as i64) % 60,
                ((self.t * 100.0) as i64) % 100,
                if self.playing { "再生中" } else { "停止" }
            ),
            egui::FontId::proportional(11.0),
            egui::Color32::from_gray(200),
        );

        // ---- bottom bar: horizontal scrollbar (zoom lives in the timeline toolbar) ----
        ui.horizontal(|ui| {
            ui.add_space(4.0);
            // scrollbar: thumb = visible window over the whole duration
            let (bar, bresp) = ui.allocate_exact_size(
                egui::vec2(ui.available_width() - 8.0, 12.0),
                egui::Sense::click_and_drag(),
            );
            let pb = ui.painter_at(bar);
            pb.rect_filled(bar, 4.0, egui::Color32::from_gray(30));
            let total_w = (self.dur as f32) * self.pps;
            let view_w = bar.width().min(total_w.max(1.0));
            let frac_w = (bar.width() / total_w.max(1.0)).min(1.0);
            let frac_x = (self.scroll_x / total_w.max(1.0)).min(1.0);
            let thumb = egui::Rect::from_min_size(
                egui::pos2(bar.left() + frac_x * bar.width(), bar.top() + 1.0),
                egui::vec2((frac_w * bar.width()).max(24.0), bar.height() - 2.0),
            );
            pb.rect_filled(thumb, 4.0, egui::Color32::from_gray(90));
            if bresp.dragged() || bresp.clicked() {
                if let Some(pos) = bresp.interact_pointer_pos() {
                    let fx = ((pos.x - bar.left()) / bar.width()).clamp(0.0, 1.0);
                    self.scroll_x = (fx * total_w - view_w * 0.5).max(0.0);
                }
            }
        });
        // NOTE: the old "claim leftover space" hack (anti shrink-drift) is gone — with the
        // toolbar row above us it flipped into a GROW loop that ballooned the panel to its
        // max height. The exact-size allocation above already reports our height honestly.
        if let Some(t2) = kf_click_seek {
            self.playing = false;
            self.t = t2.clamp(0.0, self.dur);
            self.push_req(false);
        }
    }
}

impl App {
    fn absorb_lib(&mut self, viewport_width: f32) {
        let taken: Vec<(String, Result<serde_json::Value, String>)> =
            std::mem::take(&mut *self.lib_sink.lock().unwrap());
        for (tag, res) in taken {
            match (tag.as_str(), res) {
                ("assets", Ok(v)) => {
                    self.lib.assets = v.as_array().cloned().unwrap_or_default();
                    self.lib.loaded = true;
                }
                ("contents", Ok(v)) => {
                    self.lib.contents = v.as_array().cloned().unwrap_or_default();
                }
                ("gen_content", Ok(v)) => {
                    let cid = v.get("id").and_then(|x| x.as_str()).unwrap_or("").to_string();
                    if cid.is_empty() {
                        self.lib.error = Some("コンテンツ作成に失敗".into());
                        self.lib.started = false;
                        continue;
                    }
                    self.lib.gen_content = Some(cid.clone());
                    self.lib.events.push("ダンの計画ジョブを開始しています…".into());
                    let st = self.lib_gen_stash.clone().unwrap_or(serde_json::json!({}));
                    let is_ai_video = st.get("mode").and_then(|v| v.as_str()) == Some("higgsfield_generate");
                    let body = serde_json::json!({
                        "room_id": self.room_id(),
                        "content_id": cid,
                        "instruction": {
                            "mode": if is_ai_video { "higgsfield_generate" } else { "dan_plan" },
                            "content_id": cid,
                            "content_title": st.get("title").cloned().unwrap_or_default(),
                            "asset_ids": st.get("asset_ids").cloned().unwrap_or_default(),
                            "source_assets": st.get("source_assets").cloned().unwrap_or_default(),
                            "brief": st.get("brief").cloned().unwrap_or_default(),
                            "workflow_preset": st.get("workflow_preset").cloned().unwrap_or_default(),
                            "timeline": st.get("timeline").cloned().unwrap_or_default(),
                            "prompt": st.get("prompt").cloned().unwrap_or_default(),
                            "model": st.get("model").cloned().unwrap_or_default(),
                            "duration": st.get("duration").cloned().unwrap_or_default(),
                            "aspect_ratio": st.get("aspect_ratio").cloned().unwrap_or_default(),
                            "reference_asset_ids": st.get("reference_asset_ids").cloned().unwrap_or_default(),
                        },
                    });
                    self.lib_post("gen_job", "/api/v1/production-assets/jobs".into(), body);
                    // ライブ組み上がり: 開始と同時にエディタへ遷移（最初は空の
                    // タイムライン）。中間保存が届くたびに live reload で育つ。
                    if !is_ai_video {
                        self.generating_content = Some(cid.clone());
                        self.gen_contents_mtime = None;
                        self.clip_spawn.clear();
                        self.open_content(&cid);
                    }
                }
                ("gen_job", Ok(v)) => {
                    self.lib.gen_job = v.get("id").and_then(|x| x.as_str()).map(|s| s.to_string());
                    self.lib.events.push("ダンが制作中…".into());
                }
                ("job_poll", Ok(v)) => {
                    let Some(job_id) = self.lib.gen_job.clone() else { continue };
                    let found = v.as_array().and_then(|a| {
                        a.iter()
                            .find(|j| j.get("id").and_then(|x| x.as_str()) == Some(job_id.as_str()))
                            .cloned()
                    });
                    let Some(job) = found else { continue };
                    match job.get("status").and_then(|s| s.as_str()).unwrap_or("") {
                        "done" => {
                            let cid = self.lib.gen_content.clone().unwrap_or_default();
                            self.lib.started = false;
                            self.lib.gen_job = None;
                            self.lib.events.push("完成。開いています…".into());
                            let before = self.clip_id_set();
                            self.open_content(&cid);
                            self.stagger_new_clips(&before);
                            self.generating_content = None;
                        }
                        "failed" => {
                            let msg = job.get("error").and_then(|e| e.as_str()).unwrap_or("失敗").to_string();
                            // 「何も起こらない」で終わらせない: パネルを閉じていても
                            // トーストで必ず一報を出す（詳細はパネルの赤文字に残る）
                            let short: String = msg.chars().take(90).collect();
                            self.toast(&format!("ダンの作業がエラーで止まりました: {short}"));
                            self.lib.error = Some(msg);
                            self.lib.started = false;
                            self.lib.gen_job = None;
                            // 失敗時は編集ロックを解除（途中まで出来たカット済み
                            // タイムラインがあればそのまま編集できる）
                            self.generating_content = None;
                        }
                        _ => {}
                    }
                }
                ("events_poll", Ok(v)) => {
                    if let Some(arr) = v.as_array() {
                        let msgs: Vec<String> = arr
                            .iter()
                            .rev()
                            .take(40)
                            .rev()
                            .filter_map(|e| e.get("text").and_then(|t| t.as_str()).map(|s| s.to_string()))
                            .collect();
                        if !msgs.is_empty() {
                            self.lib.events = msgs;
                        }
                    }
                }
                ("act", Ok(_)) => {
                    self.lib.error = None;
                    self.lib_refresh();
                }
                ("act", Err(e)) => {
                    // 素材登録の失敗をサイレントにしない（トークン失効が代表例）
                    self.lib.error = Some(if e.contains(" 401 ") {
                        "ログインの有効期限が切れています。チャットの「制作」ボタンから開き直すと復帰します".into()
                    } else {
                        format!("素材の登録に失敗: {e}")
                    });
                }
                ("projects", Ok(v)) => {
                    let arr = v
                        .as_array()
                        .cloned()
                        .or_else(|| v.get("projects").and_then(|p| p.as_array()).cloned())
                        .unwrap_or_default();
                    let rid = self.room_id();
                    if let Some(name) = arr
                        .iter()
                        .find(|p| p.get("room_id").and_then(|r| r.as_str()) == Some(rid.as_str()))
                        .and_then(|p| p.get("name").or_else(|| p.get("title")))
                        .and_then(|n| n.as_str())
                    {
                        self.room_label = Some(name.to_string());
                    }
                }
                ("del", Ok(_)) => {
                    self.lib.confirm_delete = None;
                    self.lib_refresh();
                }
                ("del", Err(e)) => {
                    if e.contains(" 409 ") {
                        // コンテンツ使用中 → force の二段確認に切り替える
                        if let Some(cd) = self.lib.confirm_delete.as_mut() {
                            cd.2 = true;
                        }
                    } else {
                        self.lib.error = Some(format!("素材の削除に失敗: {e}"));
                        self.lib.confirm_delete = None;
                    }
                }
                ("delc", Ok(_)) => {
                    self.lib.confirm_delete_content = None;
                    self.lib_refresh();
                }
                ("delc", Err(e)) => {
                    self.lib.error = Some(format!("コンテンツの削除に失敗: {e}"));
                    self.lib.confirm_delete_content = None;
                }
                ("capcache", Ok(v)) => {
                    if let Some(res) = v.get("results").and_then(|r| r.as_array()) {
                        for (i, r) in res.iter().enumerate() {
                            if let (Some(id), Some(key)) = (
                                self.cap_req_ids.get(i),
                                r.get("key").and_then(|k| k.as_str()),
                            ) {
                                self.cap_keys.insert(id.clone(), key.to_string());
                            }
                        }
                    }
                    // Exact server rasters have landed on disk. Replace the fast local
                    // preview now instead of waiting for the next unrelated interaction.
                    self.push_req(false);
                }
                ("capcache", Err(e)) => {
                    eprintln!("capcache error: {e}");
                }
                ("recut", Ok(v)) => {
                    self.recut_busy = false;
                    let cuts = v.get("cut_count").and_then(|x| x.as_i64()).unwrap_or(0);
                    let removed = v.get("removed_total").and_then(|x| x.as_f64()).unwrap_or(0.0);
                    let nclips = v.get("clip_count").and_then(|x| x.as_i64()).unwrap_or(0);
                    let cid = self.content_id();
                    self.open_content(&cid);
                    self.toast(&format!(
                        "再カット完了 ✓ {cuts}箇所・約{}秒短縮（クリップ{nclips}個）",
                        removed.round() as i64
                    ));
                }
                ("recut", Err(e)) => {
                    self.recut_busy = false;
                    let msg = e.chars().take(80).collect::<String>();
                    self.toast(&format!("再カット失敗: {msg}"));
                }
                (_, Err(e)) => {
                    self.lib.error = Some(e.clone());
                    self.lib.started = false;
                    eprintln!("library api error: {e}");
                }
                _ => {}
            }
        }
        if self.lib_poll.elapsed().as_millis() > 2000 {
            self.lib_poll = Instant::now();
            let room = self.room_id();
            if let (Some(_), Some(job)) = (&self.lib.gen_content, &self.lib.gen_job) {
                self.lib_get("job_poll", format!("/api/v1/production-assets/jobs?room_id={room}"));
                self.lib_get(
                    "events_poll",
                    format!("/api/v1/production-assets/jobs/{job}/events?room_id={room}"),
                );
            }
            // ライブ組み上がり: 生成中は中間保存（カット済みタイムライン等）を
            // mtime 変化で検知して開き直す。新しく現れたクリップは時差フェードイン。
            if self.screen == Screen::Editor {
                self.refresh_job_state();
                // 外部書き込み（チャット/音声からのダンのコミット、別プロセスの編集）を
                // 常時取り込む: mtime が進み、中身がこの画面の指紋と違えば開き直す。
                // 未保存の手編集がある間は上書きせずトーストで知らせる（保存時のガードと同じ規律）。
                self.poll_external_update(viewport_width);
            }
            self.clip_spawn.retain(|_, t| t.elapsed().as_secs_f32() < 3.0);
            if self.screen == Screen::Library
                && self
                    .lib
                    .assets
                    .iter()
                    .any(|a| a.get("status").and_then(|s| s.as_str()) == Some("processing"))
            {
                self.lib_refresh();
            }
        }
    }

    /// Windows 標準のファイル選択ダイアログを背景スレッドで開く（UIは固まらない）。
    /// 選択結果は picked_files 経由で library_ui が拾って register する。
    fn open_file_picker(&self) {
        use std::sync::atomic::Ordering;
        if self.picker_open.swap(true, Ordering::SeqCst) {
            return; // already open
        }
        let sink = self.picked_files.clone();
        let flag = self.picker_open.clone();
        std::thread::spawn(move || {
            let files = pick_media_files();
            if !files.is_empty() {
                sink.lock().unwrap().extend(files);
            }
            flag.store(false, Ordering::SeqCst);
        });
    }

    /// picked_files / dropped files 共通の register 送信
    fn register_media_path(&mut self, pth: &std::path::Path) {
        let body = serde_json::json!({
            "room_id": self.room_id(),
            "uri": pth.to_string_lossy().replace(char::from(92), "/"),
            "source_type": "local_path",
            "make_proxy": true,
        });
        self.lib_post("act", "/api/v1/production-assets/register".into(), body);
    }

    fn library_ui(&mut self, ctx: &egui::Context) {
        if let Ok(cid) = std::env::var("NATIVE_LIB_OPEN") {
            if !cid.is_empty() {
                std::env::set_var("NATIVE_LIB_OPEN", "");
                self.open_content(&cid);
                return;
            }
        }
        if let Ok(aid) = std::env::var("NATIVE_LIB_GEN") {
            if !aid.is_empty() && !self.lib.assets.is_empty() && !self.lib.started {
                std::env::set_var("NATIVE_LIB_GEN", "");
                self.lib.selected_assets = vec![aid];
                self.lib.title = "ネイティブ生成テスト".into();
                self.start_generation();
            }
        }
        self.ensure_lib_thumbs(ctx);
        egui::TopBottomPanel::top("library_creation").show(ctx, |ui| {
            ui.add_space(16.0);
            ui.horizontal(|ui| {
                ui.add_space(16.0);
                ui.vertical(|ui| {
                    ui.label(egui::RichText::new("思い描く動画を、ダンと。").size(24.0));
                    ui.label(egui::RichText::new("話しながら、イメージを形にしていきましょう。").weak());
                });
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    ui.add_space(16.0);
                    if ui.add(egui::Button::new(egui::RichText::new("ダンと制作").size(16.0).color(egui::Color32::from_rgb(22,27,36)))
                        .min_size(egui::vec2(160.0,48.0)).fill(UI_ACCENT)).clicked() {
                        self.assistant.immersive=true; self.assistant.open=true;
                    }
                });
            });
            ui.add_space(16.0);
        });
        let room_empty = self.lib.loaded && self.lib.assets.is_empty() && self.lib.contents.is_empty();
        let dragging_files = ctx.input(|i| !i.raw.hovered_files.is_empty());
        if room_empty {
            egui::CentralPanel::default().show(ctx, |ui| {
                let avail = ui.available_size();
                ui.vertical_centered(|ui| {
                    ui.add_space((avail.y * 0.16).clamp(24.0, 120.0));
                    ui.label(egui::RichText::new("素材を入れて動画づくりを始めましょう").size(20.0).strong());
                    ui.add_space(4.0);
                    ui.label(
                        egui::RichText::new("入れた素材から、ダンが丸ごと編集した動画を作れます")
                            .weak(),
                    );
                    ui.add_space(18.0);
                    // --- drop zone ---
                    let zone = egui::vec2(
                        (avail.x - 80.0).clamp(320.0, 720.0),
                        (avail.y * 0.42).clamp(200.0, 340.0),
                    );
                    let (rect, resp) = ui.allocate_exact_size(zone, egui::Sense::click());
                    let hov = resp.hovered() || dragging_files;
                    let p = ui.painter_at(rect);
                    p.rect_filled(
                        rect,
                        14.0,
                        if hov { egui::Color32::from_rgb(24, 40, 36) } else { egui::Color32::from_rgb(24, 24, 28) },
                    );
                    // 破線ボーダー（egui に破線rectは無いので4辺を dashed_line で描く）
                    let bcol = if hov { UI_ACCENT } else { egui::Color32::from_gray(90) };
                    let bs = egui::Stroke::new(if hov { 2.0 } else { 1.5 }, bcol);
                    let r2 = rect.shrink(6.0);
                    for (a, b) in [
                        (r2.left_top(), r2.right_top()),
                        (r2.right_top(), r2.right_bottom()),
                        (r2.right_bottom(), r2.left_bottom()),
                        (r2.left_bottom(), r2.left_top()),
                    ] {
                        p.add(egui::Shape::dashed_line(&[a, b], bs, 8.0, 6.0));
                    }
                    let cy = rect.center().y;
                    p.text(
                        egui::pos2(rect.center().x, cy - 34.0),
                        egui::Align2::CENTER_CENTER,
                        "🎞",
                        egui::FontId::proportional(42.0),
                        egui::Color32::from_gray(190),
                    );
                    p.text(
                        egui::pos2(rect.center().x, cy + 12.0),
                        egui::Align2::CENTER_CENTER,
                        if dragging_files { "ここにドロップして追加" } else { "動画・画像をここにドラッグ＆ドロップ" },
                        egui::FontId::proportional(16.0),
                        if hov { UI_ACCENT } else { egui::Color32::from_gray(220) },
                    );
                    p.text(
                        egui::pos2(rect.center().x, cy + 38.0),
                        egui::Align2::CENTER_CENTER,
                        "またはクリックしてファイルを選択",
                        egui::FontId::proportional(12.0),
                        egui::Color32::from_gray(140),
                    );
                    if resp.hovered() {
                        ui.ctx().set_cursor_icon(egui::CursorIcon::PointingHand);
                    }
                    if resp.clicked() {
                        self.open_file_picker();
                    }
                    ui.add_space(16.0);
                    ui.label(
                        egui::RichText::new("素材がなくても「ダンと制作」から始められます。")
                            .size(12.5)
                            .color(egui::Color32::from_gray(150)),
                    );
                });
            });
            // drop / picker はガイド画面でも下の共通ハンドラが処理する
            self.library_ingest(ctx);
            ctx.request_repaint_after(std::time::Duration::from_millis(300));
            return;
        }
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.add_space(6.0);
            ui.horizontal(|ui| {
                ui.heading("制作ライブラリ");
                if let Some(l) = &self.room_label {
                    let short: String = l.chars().take(24).collect();
                    ui.label(egui::RichText::new(format!("｜ {short}")).weak().size(13.0));
                }
                if ui
                    .add(egui::Button::new("🔄").frame(false))
                    .on_hover_text("一覧を更新")
                    .clicked()
                {
                    self.lib_refresh();
                }
            });
            egui::ScrollArea::vertical().show(ui, |ui| {
                // ---- contents ----
                ui.add_space(6.0);
                ui.label(egui::RichText::new("コンテンツ").strong().size(13.0));
                ui.label(egui::RichText::new("クリックで編集画面が開きます").weak().small());
                ui.add_space(2.0);
                ui.horizontal_wrapped(|ui| {
                    let contents = self.lib.contents.clone();
                    for c in &contents {
                        let title = c.get("title").and_then(|v| v.as_str()).unwrap_or("(無題)").to_string();
                        let cid = c.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                        let sq = c.get("timeline").and_then(|t| t.get("sequence"));
                        let nclips: usize = sq
                            .and_then(|sq| sq.get("tracks"))
                            .and_then(|t| t.as_array())
                            .map(|t| t.iter().map(|tr| tr.get("clips").and_then(|c| c.as_array()).map(|c| c.len()).unwrap_or(0)).sum())
                            .unwrap_or(0);
                        let dur = sq.and_then(|sq| sq.get("duration")).and_then(|d| d.as_f64()).unwrap_or(0.0);
                        let generating = c.get("status").and_then(|v| v.as_str()) == Some("running");
                        // 動画サムネ: タイムライン先頭の映像クリップの素材サムネを流用
                        let thumb = sq
                            .and_then(|sq| sq.get("tracks"))
                            .and_then(|t| t.as_array())
                            .and_then(|ts| {
                                ts.iter()
                                    .flat_map(|tr| {
                                        tr.get("clips").and_then(|c| c.as_array()).cloned().unwrap_or_default()
                                    })
                                    .find_map(|cl| {
                                        cl.get("asset_id").and_then(|a| a.as_str()).map(|s| s.to_string())
                                    })
                            })
                            .and_then(|aid| self.lib.thumbs.get(&aid).cloned());
                        let (rect, resp) = ui.allocate_exact_size(egui::vec2(200.0, 150.0), egui::Sense::click());
                        let pp = ui.painter_at(rect);
                        let hov = resp.hovered();
                        pp.rect_filled(rect, 8.0, if hov { egui::Color32::from_rgb(42, 42, 48) } else { egui::Color32::from_rgb(32, 32, 37) });
                        let img_r = egui::Rect::from_min_max(
                            rect.min + egui::vec2(4.0, 4.0),
                            egui::pos2(rect.right() - 4.0, rect.bottom() - 40.0),
                        );
                        if let Some(t) = &thumb {
                            pp.image(
                                t.id(),
                                img_r,
                                egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0)),
                                egui::Color32::WHITE,
                            );
                        } else {
                            pp.rect_filled(img_r, 6.0, egui::Color32::from_rgb(18, 18, 21));
                            pp.text(img_r.center(), egui::Align2::CENTER_CENTER, "🎬", egui::FontId::proportional(26.0), egui::Color32::from_gray(80));
                        }
                        pp.rect_stroke(rect, 8.0, egui::Stroke::new(1.0, if hov { UI_ACCENT } else { egui::Color32::from_gray(50) }));
                        let tshort: String = title.chars().take(14).collect();
                        pp.text(egui::pos2(rect.left() + 8.0, rect.bottom() - 28.0), egui::Align2::LEFT_CENTER,
                                tshort, egui::FontId::proportional(12.0), egui::Color32::from_gray(230));
                        pp.text(egui::pos2(rect.left() + 8.0, rect.bottom() - 12.0), egui::Align2::LEFT_CENTER,
                                format!("{nclips}クリップ・{:.0}:{:02}", dur as i64 / 60, dur as i64 % 60),
                                egui::FontId::proportional(10.0), egui::Color32::from_gray(140));
                        // hover時のみ左上に削除✕（生成中はジョブと衝突するため出さない）
                        let del_r = egui::Rect::from_center_size(
                            egui::pos2(rect.left() + 13.0, rect.top() + 13.0),
                            egui::vec2(18.0, 18.0),
                        );
                        let can_delete = hov && !generating && !cid.is_empty();
                        if can_delete {
                            let on_del = resp.hover_pos().map_or(false, |p| del_r.contains(p));
                            pp.circle_filled(del_r.center(), 9.0, if on_del {
                                egui::Color32::from_rgb(190, 60, 60)
                            } else {
                                egui::Color32::from_black_alpha(170)
                            });
                            pp.text(del_r.center(), egui::Align2::CENTER_CENTER, "✕", egui::FontId::proportional(11.0), egui::Color32::from_gray(230));
                        }
                        if hov {
                            pp.text(egui::pos2(rect.right() - 8.0, rect.bottom() - 12.0), egui::Align2::RIGHT_CENTER,
                                    "開く ▶", egui::FontId::proportional(11.0), UI_ACCENT);
                            ui.ctx().set_cursor_icon(egui::CursorIcon::PointingHand);
                        }
                        if resp.clicked() && !cid.is_empty() {
                            let del_clicked = can_delete
                                && resp.interact_pointer_pos().map_or(false, |p| del_r.contains(p));
                            if del_clicked {
                                self.lib.confirm_delete_content = Some((cid.clone(), title.clone()));
                            } else {
                                self.open_content(&cid);
                            }
                        }
                    }
                    if contents.is_empty() {
                        ui.label(egui::RichText::new("まだ作品がありません。「ダンと制作」から始めましょう。").weak());
                    }
                });
                // ---- user assets ----
                ui.add_space(12.0);
                let assets = self.lib.assets.clone();
                let (mine, generated): (Vec<_>, Vec<_>) = assets
                    .iter()
                    .partition(|a| a.get("source_type").and_then(|v| v.as_str()) != Some("generated"));
                ui.label(egui::RichText::new("あなたの素材").strong().size(13.0));
                ui.label(egui::RichText::new("素材をクリックして選択できます").weak().small());
                ui.add_space(2.0);
                ui.horizontal_wrapped(|ui| {
                    for a in &mine {
                        self.asset_card(ui, a);
                    }
                    if mine.is_empty() {
                        ui.label(egui::RichText::new("動画ファイルをこのウィンドウにドロップして追加").weak());
                    }
                });
                // 控えめなドロップ帯: 素材がある部屋でも常設の追加口
                ui.add_space(8.0);
                {
                    let w = ui.available_width().min(680.0);
                    let (rect, resp) = ui.allocate_exact_size(egui::vec2(w, 46.0), egui::Sense::click());
                    let hov = resp.hovered() || dragging_files;
                    let p = ui.painter_at(rect);
                    p.rect_filled(rect, 10.0, if hov { egui::Color32::from_rgb(24, 40, 36) } else { egui::Color32::from_rgb(24, 24, 28) });
                    let bcol = if hov { UI_ACCENT } else { egui::Color32::from_gray(70) };
                    let bs = egui::Stroke::new(1.2, bcol);
                    let r2 = rect.shrink(3.0);
                    for (a, b) in [
                        (r2.left_top(), r2.right_top()),
                        (r2.right_top(), r2.right_bottom()),
                        (r2.right_bottom(), r2.left_bottom()),
                        (r2.left_bottom(), r2.left_top()),
                    ] {
                        p.add(egui::Shape::dashed_line(&[a, b], bs, 7.0, 5.0));
                    }
                    p.text(
                        rect.center(),
                        egui::Align2::CENTER_CENTER,
                        "＋ 動画・画像をここにドロップ、またはクリックでファイル選択",
                        egui::FontId::proportional(12.0),
                        if hov { UI_ACCENT } else { egui::Color32::from_gray(150) },
                    );
                    if resp.hovered() {
                        ui.ctx().set_cursor_icon(egui::CursorIcon::PointingHand);
                    }
                    if resp.clicked() {
                        self.open_file_picker();
                    }
                }
                // ---- generated (collapsed) ----
                if !generated.is_empty() {
                    ui.add_space(10.0);
                    egui::CollapsingHeader::new(
                        egui::RichText::new(format!("ダンの生成物（{}件）", generated.len())).size(12.5),
                    )
                    .default_open(false)
                    .show(ui, |ui| {
                        ui.horizontal_wrapped(|ui| {
                            for a in &generated {
                                self.asset_card(ui, a);
                            }
                        });
                    });
                }
                ui.add_space(20.0);
            });
        });
        // ドラッグ中は画面全体に受け皿オーバーレイ（どこに落としても登録される）
        if dragging_files {
            let sr = ctx.screen_rect();
            let p = ctx.layer_painter(egui::LayerId::new(
                egui::Order::Foreground,
                egui::Id::new("lib_drop_overlay"),
            ));
            p.rect_filled(sr, 0.0, egui::Color32::from_black_alpha(150));
            let r2 = sr.shrink(18.0);
            let bs = egui::Stroke::new(2.0, UI_ACCENT);
            for (a, b) in [
                (r2.left_top(), r2.right_top()),
                (r2.right_top(), r2.right_bottom()),
                (r2.right_bottom(), r2.left_bottom()),
                (r2.left_bottom(), r2.left_top()),
            ] {
                p.add(egui::Shape::dashed_line(&[a, b], bs, 10.0, 8.0));
            }
            p.text(
                sr.center(),
                egui::Align2::CENTER_CENTER,
                "ここにドロップして素材を追加",
                egui::FontId::proportional(26.0),
                UI_ACCENT,
            );
        }
        self.delete_confirm_ui(ctx);
        self.library_ingest(ctx);
        ctx.request_repaint_after(std::time::Duration::from_millis(300));
    }

    /// 素材削除の確認モーダル。データ実削除（コピー/プロキシ/サムネ+登録）を
    /// 伴うので必ずワンクッション置く。コンテンツ使用中(409)は二段目の確認へ。
    fn delete_confirm_ui(&mut self, ctx: &egui::Context) {
        // コンテンツ削除の確認モーダル（素材削除とは独立の状態）
        if let Some((cid, title)) = self.lib.confirm_delete_content.clone() {
            egui::Window::new("コンテンツを削除")
                .collapsible(false)
                .resizable(false)
                .anchor(egui::Align2::CENTER_CENTER, [0.0, 0.0])
                .show(ctx, |ui| {
                    let short: String = title.chars().take(30).collect();
                    ui.label(format!("「{short}」を削除しますか？"));
                    ui.label(
                        egui::RichText::new("タイムラインのデータごと削除されます。素材ファイルは残ります。")
                            .small()
                            .weak(),
                    );
                    ui.add_space(8.0);
                    ui.horizontal(|ui| {
                        if ui
                            .add(egui::Button::new(egui::RichText::new("削除する").color(egui::Color32::WHITE))
                                .fill(egui::Color32::from_rgb(170, 50, 50)))
                            .clicked()
                        {
                            let room = self.room_id();
                            self.lib_del(
                                "delc",
                                format!("/api/v1/production-assets/contents/{cid}?room_id={room}"),
                            );
                        }
                        if ui.button("キャンセル").clicked() {
                            self.lib.confirm_delete_content = None;
                        }
                    });
                });
        }
        let Some((id, name, force_offer)) = self.lib.confirm_delete.clone() else {
            return;
        };
        egui::Window::new("素材を削除")
            .collapsible(false)
            .resizable(false)
            .anchor(egui::Align2::CENTER_CENTER, [0.0, 0.0])
            .show(ctx, |ui| {
                let short: String = name.chars().take(30).collect();
                ui.label(format!("「{short}」を削除しますか？"));
                ui.label(
                    egui::RichText::new(
                        "取り込んだコピー・プロキシ・サムネイルと登録が削除されます。\nPC内の元ファイルは消えません。",
                    )
                    .small()
                    .weak(),
                );
                if force_offer {
                    ui.add_space(4.0);
                    ui.colored_label(
                        egui::Color32::from_rgb(230, 160, 60),
                        "⚠ この素材はコンテンツで使用中です。削除するとそのクリップは再生できなくなります。",
                    );
                }
                ui.add_space(8.0);
                ui.horizontal(|ui| {
                    let label = if force_offer { "使用中でも削除する" } else { "削除する" };
                    if ui
                        .add(egui::Button::new(egui::RichText::new(label).color(egui::Color32::WHITE))
                            .fill(egui::Color32::from_rgb(170, 50, 50)))
                        .clicked()
                    {
                        let room = self.room_id();
                        self.lib_del(
                            "del",
                            format!("/api/v1/production-assets/{id}?room_id={room}&force={force_offer}"),
                        );
                    }
                    if ui.button("キャンセル").clicked() {
                        self.lib.confirm_delete = None;
                    }
                });
            });
    }

    /// ライブラリへの素材取り込み共通ハンドラ: ドラッグ&ドロップと
    /// ファイル選択ダイアログの結果を register する（通常/空部屋ガイド共通）
    fn library_ingest(&mut self, ctx: &egui::Context) {
        // drag & drop: local files register by path (no upload roundtrip needed)
        let dropped: Vec<std::path::PathBuf> =
            ctx.input(|i| i.raw.dropped_files.iter().filter_map(|f| f.path.clone()).collect());
        for pth in dropped {
            self.register_media_path(&pth);
        }
        let picked: Vec<std::path::PathBuf> = std::mem::take(&mut *self.picked_files.lock().unwrap());
        for pth in picked {
            self.register_media_path(&pth);
        }
    }
}

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, frame: &mut eframe::Frame) {
        let _uistat = UiStatGuard::begin(self);
        self.publish_editor_state();
        // 部屋名が判明したらタイトルバーへ（どの部屋のエディタか一目で分かる）
        if !self.title_set {
            if let Some(label) = self.room_label.clone() {
                let short: String = label.chars().take(28).collect();
                ctx.send_viewport_cmd(egui::ViewportCommand::Title(format!(
                    "{short} — done Studio  [{}]",
                    env!("NATIVE_BUILD_TAG")
                )));
                self.title_set = true;
            }
        }
        // IME変換の確定Enterがそのまま改行として入る（egui 0.29のIMEリーク）。
        // このフレームにIMEイベントがある間はEnter/改行テキストを握り潰す —
        // 確定済みテキストで押す普通のEnterはIMEイベントが無いので通る
        ctx.input_mut(|i| {
            let ime_active = i.events.iter().any(|e| matches!(e, egui::Event::Ime(_)));
            if ime_active {
                i.events.retain(|e| {
                    let enter_key = matches!(
                        e,
                        egui::Event::Key { key: egui::Key::Enter, pressed: true, .. }
                    );
                    let newline_text = matches!(e, egui::Event::Text(t) if t == "\n" || t == "\r" || t == "\r\n");
                    !(enter_key || newline_text)
                });
            }
        });
        self.absorb_lib(ctx.screen_rect().width());
        // Finish pending saves before either the library or editor can return.
        if let Some(at) = self.save_at {
            if Instant::now() >= at {
                self.save_at = None;
                if let Err(e) = self.save_document() { eprintln!("save: {e:#}"); }
            }
        }
        if self.screen == Screen::Library {
            if let Some(web) = self.caption_web.as_ref() {
                let _ = web.set_visible(false);
            }
            self.assistant_ui(ctx, frame);
            self.library_ui(ctx);
            return;
        }
        // Caption text edits stay in memory while typing (the WebView overlay renders
        // those live) — but the GPU compositor needs the cache PNGs to draw captions at
        // their LANE position (z-order across kinds), so keep the background render
        // warm. The pass is sig-deduped + retry-throttled internally; per-frame is fine.
        self.caption_cache_pass();
        if let Ok(v) = std::env::var("NATIVE_FREEZE_AT") {
            if let Ok(t) = v.parse::<f64>() {
                std::env::set_var("NATIVE_FREEZE_AT", "");
                self.t = t;
                self.freeze_at_playhead();
            }
        }
        if std::env::var("NATIVE_STEP_PROBE").map(|v| !v.is_empty()).unwrap_or(false) {
            if self.step_probe.is_none() {
                self.step_probe = Some((0, Instant::now()));
            }
            self.step_probe_drive();
            ctx.request_repaint_after(std::time::Duration::from_millis(80));
        }
        if let Ok(v) = std::env::var("NATIVE_SELECT") {
            if !v.is_empty() {
                std::env::set_var("NATIVE_SELECT", "");
                let want_caption = v == "caption";
                let pick = self
                    .doc
                    .seq
                    .tracks
                    .iter()
                    .filter(|t| {
                        if want_caption { t.kind == "caption" } else { t.kind == "video" }
                    })
                    .flat_map(|t| t.clips.iter())
                    .nth(2)
                    .map(|c| c.id.clone());
                if let Some(id) = pick {
                    self.selected = vec![id];
                }
            }
        }
        let now = Instant::now();
        self.last_frames.push(now);
        self.last_frames.retain(|t| now.duration_since(*t).as_secs_f32() < 1.0);
        self.ui_fps = self.last_frames.len() as f32;

        // edit keys: S=split, Del=delete, Ctrl+Z/Y=undo/redo.
        // typing = ANY text field has focus: every timeline shortcut must stand down —
        // Space toggled playback and Delete removed CLIPS while編集中のテロップに文字を
        // 打っていた（P/L しかガードされていなかった）
        // Numeric widgets become text editors when their value is clicked. While any UI
        // widget wants keyboard input, timeline commands (Delete, S/F/E/P/L, arrows,
        // Space, Ctrl+A/D/Z/Y, Home/End and zoom keys) must stand down.
        let focused = ctx.memory(|mem| mem.focused());
        let typing = ctx.wants_keyboard_input()
            || focused
            .map(|id| self.text_focus_ids.contains(&id))
            .unwrap_or(false);
        self.text_focus_ids.clear();
        let ctrl = ctx.input(|i| i.modifiers.ctrl);
        if !typing && !ctrl && ctx.input(|i| i.key_pressed(egui::Key::S)) {
            self.split_at_playhead();
        }
        if !typing && !ctrl && ctx.input(|i| i.key_pressed(egui::Key::F)) {
            self.freeze_at_playhead();
        }
        if !typing && !ctrl && ctx.input(|i| i.key_pressed(egui::Key::E)) {
            self.toggle_popout();
        }
        if !typing && !ctrl && ctx.input(|i| i.key_pressed(egui::Key::P)) {
            self.preview_fullscreen = !self.preview_fullscreen;
            ctx.send_viewport_cmd(egui::ViewportCommand::Fullscreen(self.preview_fullscreen));
            self.push_req(false);
        }
        if !typing && !ctrl && ctx.input(|i| i.key_pressed(egui::Key::L)) {
            self.cycle_playback_speed();
        }
        self.poll_popout_bakes();
        self.poll_blur_bakes();
        // BLURSHIFT: after a ◱ drop, log every presented-frame time change for 2s —
        // the ground truth for "リリースした瞬間プレビューが別の場所に変わる"
        if let Some(until) = self.blur_debug_until {
            if Instant::now() > until {
                self.blur_debug_until = None;
                BLUR_DBG.store(false, Ordering::Relaxed);
            } else {
                let (ft, fq) = {
                    let f = self.shared.frame.lock().unwrap();
                    (f.t, f.quality)
                };
                if (ft - self.blur_debug_last_t).abs() > 0.03 {
                    eprintln!(
                        "BLURSHIFT shown {:.3} -> {:.3} (self.t={:.3} q={} playing={})",
                        self.blur_debug_last_t, ft, self.t, fq, self.playing
                    );
                    self.blur_debug_last_t = ft;
                }
            }
        }
        // Delete/Backspace are DESTRUCTIVE and use a WIDER guard than the other
        // shortcuts, deliberately: `typing` (text_focus_ids) only covers registered
        // text editors, but numeric DragValues/sliders keep egui keyboard focus after
        // a mouse adjust — pressing Delete right after tweaking an inspector value
        // used to remove the CLIP (PR#522 guarded this via wants_keyboard_input; the
        // text_focus_ids narrowing lost it as a side effect). Both behaviors hold:
        // Space/S/etc. keep working right after a slider adjust (narrow guard), while
        // clip deletion additionally requires that NO widget owns the keyboard —
        // click the timeline/clip first, which is the natural delete flow anyway.
        // 経緯を消さないこと: この2段ガードは「スライダー後にショートカットが死ぬ」
        // 対策と「数値欄でのDelete誤爆」対策の両立が目的。片方に寄せると必ず
        // もう片方が壊れる（2026-07-16に実際に往復した）。
        if !typing
            && !ctx.wants_keyboard_input()
            && ctx.input(|i| i.key_pressed(egui::Key::Delete) || i.key_pressed(egui::Key::Backspace))
        {
            let force_ripple = ctx.input(|i| i.modifiers.shift);
            self.delete_selected(force_ripple);
        }
        if !typing && ctrl && ctx.input(|i| i.key_pressed(egui::Key::D)) && !self.selected.is_empty()
        {
            let ids = edits::expand_links(&self.doc.raw, &self.selected);
            let salt = std::process::id() as u64 ^ (self.t * 1000.0) as u64;
            self.apply_edit(true, move |raw| edits::duplicate_clips(raw, &ids, salt));
            self.toast("複製しました（右に空きが無い場合は別レーンの同じ時刻）");
        }
        if !typing && ctrl && ctx.input(|i| i.key_pressed(egui::Key::A)) {
            self.selected = self
                .doc
                .seq
                .tracks
                .iter()
                .filter(|tr| !tr.locked)
                .flat_map(|tr| tr.clips.iter())
                .map(|c| c.id.clone())
                .collect();
        }
        if !typing && ctrl && ctx.input(|i| i.key_pressed(egui::Key::S)) {
            match self.save_document() {
                Ok(true) => { self.save_at=None; self.toast("保存しました"); },
                Ok(false) => {},
                Err(e) => self.toast(&format!("保存できませんでした: {e}")),
            }
        }
        if !typing && ctrl && ctx.input(|i| i.key_pressed(egui::Key::C)) && !self.selected.is_empty() {
            self.copy_selected();
        }
        if !typing && ctrl && ctx.input(|i| i.key_pressed(egui::Key::V)) {
            self.paste_at_playhead();
        }
        if !typing && ctrl && ctx.input(|i| i.key_pressed(egui::Key::Z)) {
            if ctx.input(|i|i.modifiers.shift) {self.do_redo();} else {self.do_undo();}
        }
        if !typing && ctrl && ctx.input(|i| i.key_pressed(egui::Key::Y)) {
            self.do_redo();
        }
        // Plain Space belongs to transport even after clicking a text field.
        // Preserve IME conversion and Shift+Space for literal whitespace.
        let transport_space = ctx.input_mut(|i| {
            if !i.modifiers.is_none() || i.events.iter().any(|e| matches!(e, egui::Event::Ime(_))) {
                return false;
            }
            let initial = i.events.iter().any(|e| matches!(e, egui::Event::Key { key: egui::Key::Space, pressed: true, repeat: false, .. }));
            let pressed = i.consume_key(egui::Modifiers::NONE, egui::Key::Space);
            if pressed {
                i.events.retain(|e| !matches!(e, egui::Event::Text(s) if s == " "));
            }
            pressed && initial
        });
        if transport_space {
            self.toggle_play();
        }
        // auto-resume after a timeline interaction paused playback: wait until the ring
        // is rebuilt at the new position (or a short timeout), exactly like Filmora's
        // Pause -> seek -> Play cycle
        if let Some(t0) = self.resume_pending {
            if self.playing {
                self.resume_pending = None;
            } else if self.drag == Drag::None && !self.resume_on_release {
                let lvl = self.shared.ring_level.load(Ordering::Relaxed);
                let need = if self.playback_speed >= 3.0 {
                    20
                } else if self.playback_speed >= 1.5 {
                    12
                } else {
                    8
                };
                if lvl >= need || t0.elapsed().as_millis() > 900 {
                    self.resume_pending = None;
                    self.playing = true;
                    self.push_req(false);
                }
            }
        }
        // Home/End = timeline start/end, +/- = zoom around the playhead
        if !typing && ctx.input(|i| i.key_pressed(egui::Key::Home)) {
            self.t = 0.0;
            self.playing = false;
            self.resume_pending = None;
            self.push_req(false);
        }
        if !typing && ctx.input(|i| i.key_pressed(egui::Key::End)) {
            self.t = self.dur;
            self.playing = false;
            self.resume_pending = None;
            self.push_req(false);
        }
        for (key, dir) in [(egui::Key::Plus, 1.0f32), (egui::Key::Equals, 1.0), (egui::Key::Minus, -1.0)] {
            if !typing && ctx.input(|i| i.key_pressed(key)) {
                let old_pps = self.pps;
                self.pps = (self.pps * (1.0 + dir * 0.25)).clamp(1.0, 400.0);
                // keep the playhead visually anchored while zooming
                self.scroll_x = ((self.t as f32) * self.pps
                    - ((self.t as f32) * old_pps - self.scroll_x))
                    .max(0.0);
            }
        }
        if !typing && ctx.input(|i| i.key_pressed(egui::Key::F1) || i.key_pressed(egui::Key::Questionmark)) {
            self.show_help = !self.show_help;
        }
        // Frame step while paused: always one 30fps SEQUENCE/output frame. Source PTS must not
        // affect transport distance, otherwise mixed-FPS/VFR clips make arrows jump unevenly.
        if !self.playing && !typing {
            if ctx.input(|i| i.key_pressed(egui::Key::ArrowRight)) {
                self.step_once(1.0);
            }
            if ctx.input(|i| i.key_pressed(egui::Key::ArrowLeft)) {
                self.step_once(-1.0);
            }
        }
        // Render range (DaVinci-style): I = in point, O = out point at the playhead.
        // The other edge defaults to the content edge so a single keypress makes a
        // valid span; the export button then renders only this range.
        // サブタイムラインモード中は I/O が「区間の追加」になる（飛び飛び可）。
        if !typing && self.on_sub_tab() {
            let f = 1.0 / self.timeline_fps();
            let t_now = self.grid_quantize(self.t);
            if ctx.input(|i| i.key_pressed(egui::Key::I)) {
                self.sub_in = Some(t_now);
                self.toast(&format!(
                    "サブタイムライン イン点 {:02}:{:02} — Oキーで区間確定",
                    t_now as i64 / 60, t_now as i64 % 60
                ));
            }
            if ctx.input(|i| i.key_pressed(egui::Key::O)) {
                let a = self.sub_in.take().unwrap_or(0.0);
                let (a, b) = (a.min(t_now), a.max(t_now).max(a.min(t_now) + f));
                self.sub_add_range(a, b);
                let n = self.sub_ranges().len();
                self.toast(&format!(
                    "区間を追加: {:02}:{:02}〜{:02}:{:02}（計{}区間）",
                    a as i64 / 60, a as i64 % 60, b as i64 / 60, b as i64 % 60, n
                ));
                self.push_req(false);
            }
        } else if !typing {
            let f = 1.0 / self.timeline_fps();
            let t_now = self.grid_quantize(self.t);
            if ctx.input(|i| i.key_pressed(egui::Key::I)) {
                let out_e = self.export_range.map(|(_, b)| b).unwrap_or(self.dur).max(t_now + f);
                self.export_range = Some((t_now, out_e));
                self.toast(&format!("書き出し範囲イン点: {:02}:{:02}", t_now as i64 / 60, t_now as i64 % 60));
            }
            if ctx.input(|i| i.key_pressed(egui::Key::O)) {
                let in_e = self.export_range.map(|(a, _)| a).unwrap_or(0.0).min((t_now - f).max(0.0));
                self.export_range = Some((in_e, t_now.max(in_e + f)));
                self.toast(&format!("書き出し範囲アウト点: {:02}:{:02}", t_now as i64 / 60, t_now as i64 % 60));
            }
        }
        if !self.playing
            && self.step_settle_at.is_some()
            && ctx.input(|i| i.key_down(egui::Key::ArrowRight) || i.key_down(egui::Key::ArrowLeft))
        {
            self.step_settle_at = Some(Instant::now() + std::time::Duration::from_millis(90));
        }
        if let Some(at) = self.step_settle_at {
            if !self.playing && Instant::now() >= at {
                self.step_settle_at = None;
                self.push_req(false);
            }
        }
        self.underruns = self.shared.underruns.load(Ordering::Relaxed);
        if self.playing {
            let c = f64::from_bits(self.shared.clock_bits.load(Ordering::Relaxed));
            // the audio clock re-anchors a beat after a seek/play request — until it does,
            // showing it would flash the playhead bar back to the OLD position
            // （サブタイムラインの区間ジャンプ直後も同じ理屈で保持し、ホールド明けは
            // クロックを強制採用する。0.3ゲート任せだと短い区間で古い t が区間内に
            // 見え続け、区間末で止まらずタイムライン末尾まで流れてしまう）
            let mut jump_hold = false;
            if let Some(u) = self.sub_jump_until {
                if Instant::now() >= u {
                    self.sub_jump_until = None;
                    self.t = c;
                } else {
                    jump_hold = true;
                }
            }
            if !jump_hold && ((c - self.t).abs() < 0.3 || self.last_push.elapsed().as_secs_f32() > 1.2) {
                self.t = c;
            }
            // サブタイムライン: 再生ヘッドが区間の外に出たら次の区間頭へジャンプ
            // ＝飛び飛び再生。最後の区間を出たら最終区間の末尾で停止。
            // （区間の外から始めた再生セッションでは何もしない＝普通の全体再生）
            if self.on_sub_tab() && self.sub_skip_active && !jump_hold {
                let rs = self.sub_ranges();
                if !rs.is_empty() && !rs.iter().any(|&(a, b)| self.t >= a - 0.001 && self.t < b) {
                    if let Some(&(a, b)) = rs.iter().find(|&&(a, _)| a > self.t) {
                        self.t = a;
                        // ホールドは区間長より短く（短い区間でも区間末チェックが生きる）
                        let hold = ((b - a) * 800.0).clamp(150.0, 700.0) as u64;
                        self.sub_jump_until =
                            Some(Instant::now() + std::time::Duration::from_millis(hold));
                        self.push_req(false);
                    } else {
                        self.playing = false;
                        self.t = rs.last().map(|&(_, b)| b).unwrap_or(self.t).min(self.dur);
                        self.push_req(false);
                    }
                }
            }
            if self.t >= self.dur - 0.05 {
                self.playing = false;
                self.push_req(false);
            }
        }

        // adopt the newest published frame (the media thread never blocks on us).
        // GPU-direct: taking the frame is an Arc clone — zero pixels move. The CPU
        // upload below only runs as the interop-unavailable fallback.
        {
            let gpu_ok = !self.shared.gpu_disabled.load(Ordering::Relaxed);
            let f = self.shared.frame.lock().unwrap();
            let stale_paused_frame = !self.playing && (f.t - self.t).abs() > 0.002;
            if f.seq != self.last_seq && !stale_paused_frame {
                if let (true, Some(tex)) = (gpu_ok, f.tex.clone()) {
                    self.last_seq = f.seq;
                    self.comp_ms = f.comp_ms;
                    self.comp_max = f.comp_max;
                    self.gap_max = f.gap_max;
                    self.quality = f.quality;
                    self.display_tex = Some(tex);
                } else if f.rgba.len() == (canvas_w() * canvas_h() * 4) as usize {
                    self.last_seq = f.seq;
                    self.comp_ms = f.comp_ms;
                    self.comp_max = f.comp_max;
                    self.gap_max = f.gap_max;
                    self.quality = f.quality;
                    self.display_tex = None;
                    let img = egui::ColorImage::from_rgba_unmultiplied(
                        [canvas_w() as usize, canvas_h() as usize],
                        &f.rgba,
                    );
                    match &mut self.tex {
                        Some(t) => t.set(img, egui::TextureOptions::LINEAR),
                        None => {
                            self.tex =
                                Some(ctx.load_texture("preview", img, egui::TextureOptions::LINEAR))
                        }
                    }
                }
            } else if stale_paused_frame {
                ctx.request_repaint();
            }
            if !gpu_ok {
                // interop died mid-session: never draw a frozen GPU frame again
                self.display_tex = None;
            }
        }

        // aux results -> egui textures / peak store
        {
            let mut fresh: Vec<((String, i64), (usize, usize, Vec<u8>))> = Vec::new();
            {
                let a = self.shared.aux.lock().unwrap();
                if a.ver != self.aux_ver {
                    self.aux_ver = a.ver;
                    for (k, v) in &a.thumbs {
                        if !self.thumbs.contains_key(k) {
                            fresh.push((k.clone(), v.clone()));
                        }
                    }
                    for (k, v) in &a.peaks {
                        if !self.peaks.contains_key(k) {
                            self.peaks.insert(k.clone(), v.clone());
                        }
                    }
                }
            }
            for (k, (w, h, rgba)) in fresh {
                let img = egui::ColorImage::from_rgba_unmultiplied([w, h], &rgba);
                self.thumbs.insert(
                    k.clone(),
                    ctx.load_texture(format!("th_{}_{}", k.0, k.1), img, egui::TextureOptions::LINEAR),
                );
            }
        }
        // request thumbs/peaks for assets on the timeline that lack them
        {
            let mut req = self.shared.aux_req.lock().unwrap();
            if req.len() < 64 {
                let mut want: Vec<AuxJob> = Vec::new();
                for tr in &self.doc.seq.tracks {
                    for c in &tr.clips {
                        let Some(aid) = c.asset_id.clone() else { continue };
                        if tr.kind != "audio" {
                            let s0 = c.source_start;
                            // 速度対応: サムネの対象ソース範囲は source_end が正
                            let s1 = c
                                .source_end
                                .unwrap_or(c.source_start + (c.timeline_end - c.timeline_start));
                            let (b0, b1) = ((s0 / THUMB_BUCKET_S) as i64, (s1 / THUMB_BUCKET_S) as i64);
                            for b in b0..=b1 {
                                if !self.thumbs.contains_key(&(aid.clone(), b)) {
                                    want.push(AuxJob::Thumb {
                                        asset_id: aid.clone(),
                                        path: self.doc.asset_path(&aid),
                                        bucket: b,
                                    });
                                }
                            }
                        }
                        if tr.kind == "audio" && !self.peaks.contains_key(&aid) {
                            want.push(AuxJob::Peaks { asset_id: aid.clone(), path: self.doc.asset_path(&aid) });
                        }
                    }
                }
                let focus = self.displayed_t();
                want.sort_by(|a, b| {
                    let ta = match a {
                        AuxJob::Thumb { bucket, .. } => *bucket as f64 * THUMB_BUCKET_S,
                        AuxJob::Peaks { .. } => f64::INFINITY,
                    };
                    let tb = match b {
                        AuxJob::Thumb { bucket, .. } => *bucket as f64 * THUMB_BUCKET_S,
                        AuxJob::Peaks { .. } => f64::INFINITY,
                    };
                    (ta - focus).abs().total_cmp(&(tb - focus).abs())
                });
                for j in want {
                    if !req.contains(&j) && req.len() < 64 {
                        req.push(j);
                    }
                }
            }
        }
        // First import defines the sequence/output frame rate. This is deliberately shown only
        // before any media exists: changing an edited timeline's rate would retime its cuts and
        // generated assets, so that belongs in an explicit project-settings migration instead.
        if !self.pending_initial_imports.is_empty() {
            let mut counts = [0u32; TIMELINE_FPS_CHOICES.len()];
            for source_fps in &self.pending_initial_fps {
                let fps = canonical_timeline_fps(*source_fps);
                if let Some(idx) = TIMELINE_FPS_CHOICES.iter().position(|candidate| (*candidate - fps).abs() < 0.01) {
                    counts[idx] += 1;
                }
            }
            let recommended = counts.iter().enumerate()
                .max_by_key(|(_, count)| **count)
                .filter(|(_, count)| **count > 0)
                .map(|(idx, _)| TIMELINE_FPS_CHOICES[idx])
                .unwrap_or(30.0);
            let mut choice: Option<f64> = None;
            let mut cancel = false;
            egui::Window::new("プロジェクトのフレームレート")
                .collapsible(false)
                .resizable(false)
                .anchor(egui::Align2::CENTER_CENTER, egui::Vec2::ZERO)
                .show(ctx, |ui| {
                    ui.label(format!("{} 本の最初の素材を追加します。", self.pending_initial_imports.len()));
                    ui.label("タイムラインのフレームレートを選んでください。");
                    ui.add_space(8.0);
                    for (idx, fps) in TIMELINE_FPS_CHOICES.iter().enumerate() {
                        let suffix = if (*fps - recommended).abs() < 0.01 { "（推奨）" } else { "" };
                        let detected = counts[idx];
                        let detail = if detected > 0 { format!(" / 選択素材 {detected} 本") } else { String::new() };
                        if ui.button(format!("{}{}{}", fps_label(*fps), suffix, detail)).clicked() {
                            choice = Some(*fps);
                        }
                    }
                    ui.add_space(4.0);
                    if ui.button("キャンセル").clicked() { cancel = true; }
                });
            if let Some(fps) = choice {
                self.import_initial_files(fps);
            } else if cancel {
                self.pending_initial_imports.clear();
                self.pending_initial_fps.clear();
            }
        }

        self.poll_export();
        // 全画面プレビュー(P): DaVinci風の小型トランスポートバー。
        // 一時停止中は常に表示、再生中はマウスを動かした時だけ現れて自動で消える。
        if self.preview_fullscreen {
            let moved = ctx.input(|i| {
                i.pointer.delta().length() > 0.5 || i.pointer.any_down() || i.pointer.any_click()
            });
            if moved {
                self.fs_bar_last_move = Some(Instant::now());
            }
            let recent = self
                .fs_bar_last_move
                .map(|t| t.elapsed().as_secs_f32() < 2.2)
                .unwrap_or(false);
            if !self.playing || recent {
                egui::Area::new(egui::Id::new("fs_transport"))
                    .order(egui::Order::Foreground)
                    .anchor(egui::Align2::CENTER_BOTTOM, egui::vec2(0.0, -28.0))
                    .show(ctx, |ui| {
                        egui::Frame::none()
                            .fill(egui::Color32::from_black_alpha(170))
                            .rounding(10.0)
                            .inner_margin(egui::Margin::symmetric(14.0, 8.0))
                            .show(ui, |ui| {
                                ui.horizontal(|ui| {
                                    let glyph = if self.playing { "⏸" } else { "▶" };
                                    if ui
                                        .add(
                                            egui::Button::new(
                                                egui::RichText::new(glyph)
                                                    .size(20.0)
                                                    .color(egui::Color32::WHITE),
                                            )
                                            .frame(false)
                                            .min_size(egui::vec2(30.0, 26.0)),
                                        )
                                        .on_hover_text("再生/停止 (Space)")
                                        .clicked()
                                    {
                                        self.toggle_play();
                                    }
                                    let dur = self.dur.max(0.001);
                                    let mut tv = self.t;
                                    let w = (ctx.screen_rect().width() * 0.42).clamp(260.0, 760.0);
                                    ui.spacing_mut().slider_width = w;
                                    let sl = ui.add(
                                        egui::Slider::new(&mut tv, 0.0..=dur)
                                            .show_value(false)
                                            .trailing_fill(true),
                                    );
                                    if sl.drag_started() {
                                        self.fs_resume_play = self.playing;
                                        self.playing = false;
                                    }
                                    if sl.changed() {
                                        self.t = tv.clamp(0.0, dur);
                                        self.push_req(true);
                                    }
                                    if sl.drag_stopped() {
                                        if self.fs_resume_play {
                                            self.fs_resume_play = false;
                                            self.playing = true;
                                        }
                                        self.push_req(false);
                                    }
                                    let fps = self.timeline_fps();
                                    let tc = |t: f64| {
                                        let fr = ((t * fps).round() as i64).max(0);
                                        let f = fps.round() as i64;
                                        format!(
                                            "{:02}:{:02}:{:02}",
                                            fr / (f * 60),
                                            (fr / f) % 60,
                                            fr % f
                                        )
                                    };
                                    ui.label(
                                        egui::RichText::new(format!(
                                            "{} / {}",
                                            tc(self.t),
                                            tc(self.dur)
                                        ))
                                        .color(egui::Color32::from_gray(220))
                                        .monospace(),
                                    );
                                    if ui.ui_contains_pointer() {
                                        self.fs_bar_last_move = Some(Instant::now());
                                    }
                                });
                            });
                    });
            }
        }
        if !self.preview_fullscreen {
            egui::TopBottomPanel::top("toolbar").exact_height(38.0).show(ctx, |ui| {
                ui.horizontal_centered(|ui| {
                if ui.button("📚 ライブラリ").clicked() {
                    self.playing = false;
                    self.push_req(false);
                    self.lib_refresh();
                    self.screen = Screen::Library;
                }
                ui.separator();
                if ui
                    .selectable_label(self.recut_open, "✂ カット調整")
                    .on_hover_text("無音の詰め具合を変えてダンのカットを組み直す")
                    .clicked()
                {
                    self.recut_open = !self.recut_open;
                }
                if ui
                    .selectable_label(self.blur_mode, "◱ ぼかし/注目")
                    .on_hover_text("プレビュー上をドラッグして範囲を指定 → 右パネルで種類を選択（ぼかし/モザイク/単色/マーカー/スポットライト/ズーム）")
                    .clicked()
                {
                    self.blur_mode = !self.blur_mode;
                    self.blur_drag = None;
                    if self.blur_mode {
                        // drawing over a RUNNING video meant the clip landed seconds past
                        // the frame the user aimed at ("描いた瞬間に別の場所が映る") —
                        // freeze the preview on the displayed frame first, like F/S do
                        self.pause_at_displayed();
                        // arm the jump diagnostics + force one re-serve so the log shows
                        // WHERE the currently displayed frame comes from (cache or live)
                        BLUR_DBG.store(true, Ordering::Relaxed);
                        self.blur_debug_until =
                            Some(Instant::now() + std::time::Duration::from_secs(20));
                        self.push_req(false);
                    }
                }
                ui.menu_button("＋素材", |ui| {
                    ui.set_min_width(260.0);
                    ui.label(egui::RichText::new("再生ヘッドの位置に挿入（後ろは右へ）").weak().small());
                    if self.lib.assets.is_empty() {
                        self.lib_refresh();
                        ui.label("読み込み中…");
                    }
                    self.ensure_lib_thumbs(ui.ctx());
                    let assets: Vec<serde_json::Value> = self
                        .lib
                        .assets
                        .iter()
                        .filter(|a| a.get("source_type").and_then(|v| v.as_str()) != Some("generated"))
                        .cloned()
                        .collect();
                    egui::ScrollArea::vertical().max_height(420.0).show(ui, |ui| {
                        for a in &assets {
                            let id = a.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                            let name = a
                                .get("filename")
                                .or_else(|| a.get("name"))
                                .and_then(|v| v.as_str())
                                .unwrap_or("(無名)");
                            let dur = a
                                .get("metadata")
                                .and_then(|m| m.get("duration"))
                                .and_then(|d| d.as_f64())
                                .unwrap_or(0.0);
                            let (rect, resp) = ui.allocate_exact_size(
                                egui::vec2(250.0, 60.0),
                                egui::Sense::click_and_drag(),
                            );
                            let pp = ui.painter_at(rect);
                            let hov = resp.hovered();
                            pp.rect_filled(
                                rect,
                                6.0,
                                if hov { egui::Color32::from_rgb(46, 46, 52) } else { egui::Color32::from_rgb(32, 32, 37) },
                            );
                            let img_r = egui::Rect::from_min_size(rect.min + egui::vec2(4.0, 4.0), egui::vec2(92.0, 52.0));
                            if let Some(t) = self.lib.thumbs.get(&id) {
                                pp.image(
                                    t.id(),
                                    img_r,
                                    egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0)),
                                    egui::Color32::WHITE,
                                );
                            } else {
                                pp.rect_filled(img_r, 4.0, egui::Color32::from_rgb(18, 18, 21));
                                pp.text(img_r.center(), egui::Align2::CENTER_CENTER, "🎞", egui::FontId::proportional(18.0), egui::Color32::from_gray(80));
                            }
                            let short: String = name.chars().take(18).collect();
                            pp.text(
                                egui::pos2(img_r.right() + 8.0, rect.top() + 20.0),
                                egui::Align2::LEFT_CENTER,
                                short,
                                egui::FontId::proportional(11.5),
                                egui::Color32::from_gray(225),
                            );
                            if dur > 0.0 {
                                pp.text(
                                    egui::pos2(img_r.right() + 8.0, rect.bottom() - 15.0),
                                    egui::Align2::LEFT_CENTER,
                                    format!("{:.0}:{:02}", dur as i64 / 60, dur as i64 % 60),
                                    egui::FontId::proportional(10.0),
                                    egui::Color32::from_gray(140),
                                );
                            }
                            if hov {
                                pp.rect_stroke(rect, 6.0, egui::Stroke::new(1.2, UI_ACCENT));
                                ui.ctx().set_cursor_icon(egui::CursorIcon::PointingHand);
                            }
                            if resp.clicked() {
                                self.insert_asset_at_playhead(a);
                                ui.close_menu();
                            }
                            if resp.drag_started() {
                                self.asset_drag = Some(a.clone());
                                ui.ctx().set_cursor_icon(egui::CursorIcon::Grabbing);
                            }
                            ui.add_space(3.0);
                        }
                    });
                });
                // キャンバス形式（プレビュー枠=書き出しの形）。何度でも切替可。
                // クリップは素材実寸ベースの実効箱で描くため、切替で素材は歪まない。
                {
                    let cur = self
                        .doc
                        .raw
                        .get(0)
                        .and_then(|c| c.get("timeline"))
                        .and_then(|t| t.get("format"))
                        .or_else(|| self.doc.raw.get(0).and_then(|c| c.pointer("/timeline/sequence/format")))
                        .or_else(|| self.doc.raw.get(0).and_then(|c| c.get("format")))
                        .and_then(|v| v.as_str())
                        .unwrap_or("9:16")
                        .to_string();
                    let mut pick = cur.clone();
                    egui::ComboBox::from_id_source("canvas_fmt")
                        .width(70.0)
                        .selected_text(format!("🖼 {cur}"))
                        .show_ui(ui, |ui| {
                            for f in ["9:16", "16:9", "1:1", "4:5"] {
                                ui.selectable_value(&mut pick, f.to_string(), f);
                            }
                        })
                        .response
                        .on_hover_text("プレビュー枠と書き出しの形。何度でも切替でき、素材は歪みません");
                    if pick != cur {
                        let p2 = pick.clone();
                        self.apply_edit(true, move |raw| edits::set_canvas_format(raw, &p2));
                        self.push_req(false);
                    }
                }
                if ui.selectable_label(self.assistant.open, "ダンと制作").clicked() {
                    self.assistant.open = !self.assistant.open;
                    self.assistant.immersive=false;
                    self.revise_open = false;
                }
                // サブタブでは I/O=緑の飛び飛び区間（モードボタンは廃止。
                // タブが役割を決める: メイン=青い単一書き出し範囲／サブ=緑区間）
                if self.on_sub_tab() && !self.sub_ranges().is_empty() {
                    if ui
                        .small_button("▶ 区間を通しで再生")
                        .on_hover_text("最初の区間の頭から、区間だけを繋げて再生します（仕上がり確認）")
                        .clicked()
                    {
                        if let Some(&(a, _)) = self.sub_ranges().first() {
                            self.t = a;
                            self.playing = true;
                            self.sub_skip_active = true;
                            self.resume_pending = None;
                            self.push_req(false);
                        }
                    }
                }
                let exporting = self.export_job.is_some();
                if ui
                    .add_enabled(!exporting, egui::Button::new("📤 書き出し"))
                    .clicked()
                {
                    self.open_export_dialog();
                }
                if self.export_dialog_open {
                    let mut keep_open = true;
                    egui::Window::new("書き出し設定")
                        .collapsible(false)
                        .resizable(false)
                        .open(&mut keep_open)
                        .anchor(egui::Align2::CENTER_CENTER, [0.0, -60.0])
                        .show(ui.ctx(), |ui| {
                            let content_end = self
                                .doc
                                .seq
                                .tracks
                                .iter()
                                .flat_map(|t| t.clips.iter())
                                .map(|c| c.timeline_end)
                                .fold(0.0f64, f64::max);
                            // 青い単一範囲はメインタブ専用（サブタブでは無視）
                            let (r0, r1) = (!self.on_sub_tab())
                                .then_some(self.export_range)
                                .flatten()
                                .unwrap_or((0.0, content_end));
                            let sel_ranges = self.sub_ranges();
                            let sel_total: f64 = sel_ranges.iter().map(|(a, b)| b - a).sum();
                            let dur = if self.export_use_sub && !sel_ranges.is_empty() {
                                sel_total
                            } else {
                                (r1 - r0).max(0.0)
                            };
                            ui.label(format!(
                                "解像度 1080x1920 / 30fps   長さ {:02}:{:02}",
                                dur as i64 / 60, dur as i64 % 60
                            ));
                            // どのタブを書き出すか（sequenceスロット=開いているタブ）
                            let active_tab = self.active_seq_id();
                            if active_tab != "main" {
                                let tname = self
                                    .seq_tabs()
                                    .into_iter()
                                    .find(|(id, _)| *id == active_tab)
                                    .map(|(_, n)| n)
                                    .unwrap_or_else(|| "サブ".into());
                                ui.label(
                                    egui::RichText::new(format!("書き出し対象: {tname}（開いているタブ）"))
                                        .color(egui::Color32::from_rgb(0, 210, 140))
                                        .small(),
                                );
                            }
                            // サブタイムライン書き出し: 組んだ再生区間だけを繋げて1本に
                            // （緑区間はサブタブ専用）
                            if self.on_sub_tab() && !sel_ranges.is_empty() {
                                ui.checkbox(
                                    &mut self.export_use_sub,
                                    format!(
                                        "サブタイムラインの区間だけ繋げて書き出す（{}区間・計{:02}:{:02}）",
                                        sel_ranges.len(),
                                        sel_total as i64 / 60,
                                        sel_total as i64 % 60
                                    ),
                                );
                            } else if self.export_use_sub {
                                self.export_use_sub = false;
                            }
                            if self.export_use_sub && !sel_ranges.is_empty() {
                                let list = sel_ranges
                                    .iter()
                                    .take(6)
                                    .map(|(a, b)| {
                                        format!(
                                            "{:02}:{:02}-{:02}:{:02}",
                                            *a as i64 / 60, *a as i64 % 60, *b as i64 / 60, *b as i64 % 60
                                        )
                                    })
                                    .collect::<Vec<_>>()
                                    .join(", ");
                                let more = if sel_ranges.len() > 6 { " …" } else { "" };
                                ui.label(
                                    egui::RichText::new(format!("区間: {list}{more}"))
                                        .color(egui::Color32::from_rgb(110, 190, 255))
                                        .small(),
                                );
                            }
                            if !self.export_use_sub && !self.on_sub_tab() && self.export_range.is_some() {
                                ui.label(
                                    egui::RichText::new(format!(
                                        "範囲書き出し: {:02}:{:02} 〜 {:02}:{:02}（解除はダイアログを閉じて✕）",
                                        r0 as i64 / 60, r0 as i64 % 60, r1 as i64 / 60, r1 as i64 % 60
                                    ))
                                    .color(egui::Color32::from_rgb(110, 190, 255))
                                    .small(),
                                );
                            } else if self.on_sub_tab() {
                                ui.label(
                                    egui::RichText::new("範囲: 全体（Iでイン点→Oで区間追加＝緑の区間だけ書き出せます）")
                                        .weak()
                                        .small(),
                                );
                            } else {
                                ui.label(egui::RichText::new("範囲: 全体（I/Oキーで範囲指定できます）").weak().small());
                            }
                            ui.add_space(8.0);
                            ui.label(egui::RichText::new("保存先ファイル").strong());
                            ui.add(
                                egui::TextEdit::singleline(&mut self.export_dest)
                                    .desired_width(440.0),
                            );
                            ui.horizontal(|ui| {
                                let keep_name = |dest: &str, dir: String| -> String {
                                    let name = std::path::Path::new(dest)
                                        .file_name()
                                        .map(|n| n.to_string_lossy().to_string())
                                        .unwrap_or_else(|| "書き出し.mp4".into());
                                    format!("{dir}\\{name}")
                                };
                                if ui.small_button("ビデオ").clicked() {
                                    if let Ok(u) = std::env::var("USERPROFILE") {
                                        self.export_dest = keep_name(&self.export_dest, format!("{u}\\Videos"));
                                    }
                                }
                                if ui.small_button("デスクトップ").clicked() {
                                    if let Ok(u) = std::env::var("USERPROFILE") {
                                        self.export_dest = keep_name(&self.export_dest, format!("{u}\\Desktop"));
                                    }
                                }
                                if ui.small_button("ダウンロード").clicked() {
                                    if let Ok(u) = std::env::var("USERPROFILE") {
                                        self.export_dest = keep_name(&self.export_dest, format!("{u}\\Downloads"));
                                    }
                                }
                            });
                            let dest_ok = self.export_dest.trim().to_ascii_lowercase().ends_with(".mp4")
                                && std::path::Path::new(self.export_dest.trim())
                                    .parent()
                                    .map(|p| !p.as_os_str().is_empty())
                                    .unwrap_or(false);
                            if !dest_ok {
                                ui.label(
                                    egui::RichText::new("保存先は .mp4 で終わるフルパスにしてください")
                                        .color(egui::Color32::from_rgb(230, 120, 120))
                                        .small(),
                                );
                            }
                            ui.add_space(8.0);
                            ui.horizontal(|ui| {
                                if ui
                                    .add_enabled(dest_ok, egui::Button::new("▶ 書き出し開始"))
                                    .clicked()
                                {
                                    if let Some(parent) = std::path::Path::new(self.export_dest.trim()).parent() {
                                        let _ = std::fs::write(
                                            format!("{}/.export_dir.txt", self.doc.asset_dir),
                                            parent.to_string_lossy().as_bytes(),
                                        );
                                    }
                                    self.export_dialog_open = false;
                                    self.start_export();
                                }
                                if ui.button("キャンセル").clicked() {
                                    self.export_dialog_open = false;
                                }
                            });
                        });
                    if !keep_open {
                        self.export_dialog_open = false;
                    }
                }
                if let Some((ra, rb)) = (!self.on_sub_tab()).then_some(self.export_range).flatten() {
                    ui.label(
                        egui::RichText::new(format!(
                            "範囲 {:02}:{:02}–{:02}:{:02}",
                            ra as i64 / 60, ra as i64 % 60, rb as i64 / 60, rb as i64 % 60
                        ))
                        .color(egui::Color32::from_rgb(110, 190, 255))
                        .small(),
                    )
                    .on_hover_text("この範囲だけ書き出します（I/Oキーで変更・ルーラー上の旗をドラッグ）");
                    if ui.small_button("✕").on_hover_text("範囲を解除して全体を書き出す").clicked() {
                        self.export_range = None;
                    }
                }
                if exporting {
                    if let Some(frac) = self.export_progress {
                        ui.add(
                            egui::ProgressBar::new(frac)
                                .desired_width(150.0)
                                .text(format!("{:.0}%", frac * 100.0)),
                        );
                    } else {
                        ui.spinner();
                    }
                }
                if let Some(st) = &self.export_status {
                    ui.label(st.clone());
                }
                if !exporting {
                    if let Some(done) = self.export_done_path.clone() {
                        if ui.small_button("📂 保存先を開く").on_hover_text(done.clone()).clicked() {
                            let _ = std::process::Command::new("explorer.exe")
                                .arg(format!("/select,{}", done.replace('/', "\\")))
                                .spawn();
                        }
                        if ui.small_button("✕").on_hover_text("この表示を消す").clicked() {
                            self.export_done_path = None;
                            self.export_status = None;
                        }
                    }
                }
                // volume for the selected clip (linked audio / audio clip)
                let selv: Option<model::Clip> = if self.selected.len() == 1 {
                    self.doc
                        .seq
                        .tracks
                        .iter()
                        .flat_map(|tr| tr.clips.iter())
                        .find(|c| c.id == self.selected[0] && (c.link_id.is_some() || c.asset_id.is_some()))
                        .cloned()
                } else {
                    None
                };
                if let Some(c) = selv {
                    ui.separator();
                    ui.label("音量");
                    let mut vol = c.volume as f32;
                    let sl = ui.add(egui::Slider::new(&mut vol, 0.0..=2.0).show_value(true).fixed_decimals(2));
                    if sl.drag_started() {
                        self.pending_undo = Some(self.doc.raw.clone());
                    }
                    if sl.changed() {
                        let ids = edits::expand_links(&self.doc.raw, &[c.id.clone()]);
                        let v = vol as f64;
                        self.apply_edit(false, move |raw| edits::set_volume(raw, &ids, v));
                    }
                }
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    ui.label(egui::RichText::new("F1: ショートカット一覧 | クリップ選択=右に調整パネル | 番号ヘッダをドラッグ=レーン並べ替え").weak().small());
                });
                });
            });
            egui::TopBottomPanel::bottom("timeline")
                .resizable(true)
                .default_height(260.0)
                .height_range(140.0..=700.0)
                .show(ctx, |ui| {
                    self.timeline_toolbar(ui);
                    ui.add_space(2.0);
                    self.timeline_ui(ui);
                });
            egui::TopBottomPanel::bottom("transport")
                .exact_height(44.0)
                .show(ctx, |ui| self.transport_ui(ui));
            self.inspector_ui(ctx);
        }
        self.assistant_ui(ctx, frame);
        egui::CentralPanel::default()
            .frame(egui::Frame::none().fill(egui::Color32::from_gray(10)))
            .show(ctx, |ui| {
                let avail = ui.available_size();
                let gpu_frame = self.display_tex.clone();
                if gpu_frame.is_some() || self.tex.is_some() {
                    // 枠の形は「今表示しているフレーム自身の寸法」から決める。形式切替の
                    // 直後は新寸法のフレームが届くまで旧フレームを旧比率のまま見せ、
                    // 届いた瞬間に枠ごと切り替える（一瞬の潰れ・黒抜けの根絶）。
                    let (cw, ch) = if let Some(g) = &gpu_frame {
                        (g.w as f32, g.h as f32)
                    } else if let Some(t) = &self.tex {
                        let s = t.size();
                        (s[0] as f32, s[1] as f32)
                    } else {
                        (canvas_w() as f32, canvas_h() as f32)
                    };
                    let scale = (avail.x / cw).min(avail.y / ch);
                    let size = egui::vec2(cw * scale, ch * scale);
                    ui.centered_and_justified(|ui| {
                        // isolation probe: produce GPU frames but never draw them
                        let nodraw = std::env::var("NATIVE_GPU_NODRAW").map(|v| !v.is_empty()).unwrap_or(false);
                        let resp = if let Some(gtex) = gpu_frame.filter(|_| !nodraw) {
                            // GPU-direct: the composed D3D11 texture is drawn straight
                            // into eframe's swapchain by the interop callback — same
                            // allocation call as egui::Image, so the geometry (and all
                            // overlay/caption math below) is unchanged.
                            let (_, resp) = ui.allocate_exact_size(size, egui::Sense::click_and_drag());
                            let vid = egui::Rect::from_center_size(resp.rect.center(), size);
                            let glv = self.gl_video.clone();
                            let shared = self.shared.clone();
                            ui.painter().add(egui::PaintCallback {
                                rect: vid,
                                callback: Arc::new(eframe::egui_glow::CallbackFn::new(
                                    move |_info, painter| {
                                        let pool = shared.gpu_pool.lock().unwrap().clone();
                                        let ok = pool
                                            .map(|p| glv.draw(painter.gl(), &p, &gtex))
                                            .unwrap_or(false);
                                        if !ok {
                                            shared.gpu_disabled.store(true, Ordering::Relaxed);
                                        }
                                    },
                                )),
                            });
                            resp
                        } else if let Some(tex) = self.tex.clone() {
                            ui.add(egui::Image::new((tex.id(), size)))
                                .interact(egui::Sense::click_and_drag())
                        } else {
                            ui.allocate_exact_size(size, egui::Sense::click_and_drag()).1
                        };
                        // The preview owns pointer gestures, never text entry. End any
                        // numeric/text focus explicitly so shortcuts resume in this same
                        // interaction instead of waiting for a later panel click.
                        if resp.clicked() || resp.drag_started() {
                            if let Some(id) = ui.memory(|mem| mem.focused()) {
                                ui.memory_mut(|mem| mem.surrender_focus(id));
                            }
                        }
                        // プレビュー上のクリックで素材を選択（タイムラインを触らずに選べる）。
                        // clicked はドラッグ無しの離しでだけ真なので、範囲指定・移動ドラッグとは干渉しない。
                        // 上のレーンから順に、クリック点を実効箱に含む一番手前のクリップを選ぶ。
                        if resp.clicked() && !self.revise_pick && !self.blur_mode && !self.assistant.pick {
                            if let Some(p) = resp.interact_pointer_pos() {
                                let vid = egui::Rect::from_center_size(resp.rect.center(), size);
                                let fx = ((p.x - vid.left()) / vid.width()).clamp(0.0, 1.0) as f64;
                                let fy = ((p.y - vid.top()) / vid.height()).clamp(0.0, 1.0) as f64;
                                let t_disp = self.displayed_grid_t();
                                let mut hit: Option<String> = None;
                                'pick: for tr in self.doc.seq.tracks.iter().rev() {
                                    if tr.hidden
                                        || matches!(tr.kind.as_str(), "audio" | "caption" | "effect")
                                    {
                                        continue;
                                    }
                                    for c in tr.clips.iter().rev() {
                                        if c.asset_id.is_none()
                                            || t_disp < c.timeline_start
                                            || t_disp >= c.timeline_end
                                            || c.video_enabled == Some(false)
                                        {
                                            continue;
                                        }
                                        let b = effective_box(&self.doc, c, t_disp);
                                        if fx >= b.x
                                            && fx <= b.x + b.width
                                            && fy >= b.y
                                            && fy <= b.y + b.height
                                        {
                                            hit = Some(c.id.clone());
                                            break 'pick;
                                        }
                                    }
                                }
                                match hit {
                                    Some(id) => {
                                        if !(self.selected.len() == 1 && self.selected[0] == id) {
                                            self.selected = vec![id];
                                        }
                                    }
                                    None => self.selected.clear(),
                                }
                            }
                        }
                        let vid = egui::Rect::from_center_size(resp.rect.center(), size);
                        self.sync_caption_web(frame, vid, true);
                        if self.revise_pick {
                            // ダンに指示の◱: 囲んだ場所+今のフレーム時刻が指示に添付される
                            let pp = ui.painter_at(vid);
                            let col = egui::Color32::from_rgb(120, 170, 255);
                            pp.rect_stroke(vid, 0.0, egui::Stroke::new(1.0, col));
                            pp.text(
                                egui::pos2(vid.center().x, vid.top() + 14.0),
                                egui::Align2::CENTER_CENTER,
                                "ダンに見せたい場所をドラッグで囲んでください",
                                egui::FontId::proportional(13.0),
                                col,
                            );
                            if resp.drag_started() {
                                self.blur_drag = resp.interact_pointer_pos();
                            }
                            if let (Some(a), Some(p)) = (self.blur_drag, resp.interact_pointer_pos()) {
                                let r = egui::Rect::from_two_pos(a, p);
                                pp.rect_filled(r, 0.0, egui::Color32::from_rgba_unmultiplied(120, 170, 255, 40));
                                pp.rect_stroke(r, 0.0, egui::Stroke::new(1.5, col));
                            }
                            if resp.drag_stopped() {
                                if let (Some(a), Some(p)) = (self.blur_drag.take(), resp.interact_pointer_pos()) {
                                    let rr = egui::Rect::from_two_pos(a, p);
                                    if rr.width() > 8.0 && rr.height() > 8.0 {
                                        self.pause_at_displayed();
                                        let fx = ((rr.left() - vid.left()) / vid.width()).clamp(0.0, 1.0) as f64;
                                        let fy = ((rr.top() - vid.top()) / vid.height()).clamp(0.0, 1.0) as f64;
                                        let fw = (rr.width() / vid.width()).min(1.0) as f64;
                                        let fh = (rr.height() / vid.height()).min(1.0) as f64;
                                        self.assistant.selection = Some(serde_json::json!({"rect":[fx,fy,fw,fh],"t":self.displayed_grid_t()}));
                                        self.assistant.focus = Some(serde_json::json!({"rect":[fx,fy,fw,fh],"label":"選択した範囲"}));
                                        self.revise_pick = false;
                                        self.assistant.open = true;
                                        self.assistant.pick = true;
                                        self.toast("ダンに指示する範囲を選べます");
                                    }
                                }
                            }
                        } else if self.blur_mode {
                            let vid = egui::Rect::from_center_size(resp.rect.center(), size);
                            let pp = ui.painter_at(vid);
                            pp.rect_stroke(vid, 0.0, egui::Stroke::new(1.0, UI_ACCENT));
                            pp.text(
                                egui::pos2(vid.center().x, vid.top() + 14.0),
                                egui::Align2::CENTER_CENTER,
                                "ぼかす範囲をドラッグで指定",
                                egui::FontId::proportional(13.0),
                                UI_ACCENT,
                            );
                            if resp.drag_started() {
                                self.blur_drag = resp.interact_pointer_pos();
                            }
                            if let (Some(a), Some(p)) = (self.blur_drag, resp.interact_pointer_pos()) {
                                let r = egui::Rect::from_two_pos(a, p);
                                pp.rect_filled(r, 0.0, egui::Color32::from_rgba_unmultiplied(0, 190, 150, 40));
                                pp.rect_stroke(r, 0.0, egui::Stroke::new(1.5, UI_ACCENT));
                            }
                            if resp.drag_stopped() {
                                if let (Some(a), Some(p)) = (self.blur_drag.take(), resp.interact_pointer_pos()) {
                                    let rr = egui::Rect::from_two_pos(a, p);
                                    if rr.width() > 8.0 && rr.height() > 8.0 {
                                        let fx = ((rr.left() - vid.left()) / vid.width()).clamp(0.0, 1.0) as f64;
                                        let fy = ((rr.top() - vid.top()) / vid.height()).clamp(0.0, 1.0) as f64;
                                        let fw = (rr.width() / vid.width()).min(1.0) as f64;
                                        let fh = (rr.height() / vid.height()).min(1.0) as f64;
                                        // belt & braces: land exactly on the frame being
                                        // shown, and pin the preview clock to it too
                                        self.pause_at_displayed();
                                        let t = self.displayed_t();
                                        self.t = t;
                                        {
                                            let f = self.shared.frame.lock().unwrap();
                                            eprintln!(
                                                "BLURDROP self.t={t:.3} shown_t={:.3} q={} playing={}",
                                                f.t, f.quality, self.playing
                                            );
                                            self.blur_debug_last_t = f.t;
                                        }
                                        self.blur_debug_until =
                                            Some(Instant::now() + std::time::Duration::from_secs(2));
                                        let salt = self.salt;
                                        self.salt += 1;
                                        self.apply_edit(true, move |raw| {
                                            edits::add_effect_clip(raw, t, 3.0, (fx, fy, fw, fh), "gaussian", salt)
                                        });
                                        self.push_req(false);
                                        self.blur_mode = false;
                                        self.toast("ぼかしを追加しました（右パネルで追従ベイク・種類・時間を調整）");
                                    }
                                }
                            }
                        } else {
                            self.preview_inspector(ui, &resp);
                        }
                        // NATIVE_GEOM_PROBE: dump every rect in the outline<->image mapping
                        // chain once per second — the ground truth for "is the FRAME or the
                        // BLUR that drifts with position"
                        if std::env::var("NATIVE_GEOM_PROBE").map(|v| !v.is_empty()).unwrap_or(false) {
                            let vid_img = egui::Rect::from_center_size(resp.rect.center(), size);
                            let insp = {
                                let img = resp.rect;
                                let (cw, ch) = (canvas_w() as f32, canvas_h() as f32);
                                let scale = (img.width() / cw).min(img.height() / ch);
                                egui::Rect::from_center_size(img.center(), egui::vec2(cw * scale, ch * scale))
                            };
                            fz_log(&format!(
                                "GEOM avail={avail:?} size={size:?} resp={:?} img_rect={vid_img:?} insp_vid={insp:?} ppp={}",
                                resp.rect,
                                ui.ctx().pixels_per_point()
                            ));
                        }
                        // captions: active caption clips drawn over the frame (white bold with
                        // dark outline, bottom-centre — the export bakes the full styling
                        // server-side; this is the live view)
                        // Captions are part of the composed video frame now, not a UI overlay.
                    });
                }
            });
        if let Ok(t) = std::env::var("NATIVE_REVISE_RUN") {
            if !t.is_empty() && !self.lib.started {
                self.revise_open = true;
                if self.lib.assets.is_empty() {
                    // wait for the asset list; retry the refresh on the shared 2s timer
                    if self.lib_poll.elapsed().as_millis() > 2000 {
                        self.lib_poll = Instant::now();
                        self.lib_refresh();
                    }
                } else {
                    std::env::set_var("NATIVE_REVISE_RUN", "");
                    self.revise_text = t;
                    self.start_revision();
                    self.revise_text.clear();
                }
            }
        }
        if self.revise_open {
            self.assistant.open = true;
            self.revise_open = false;
        }
        if std::env::var("NATIVE_RECUT_OPEN").map(|v| !v.is_empty()).unwrap_or(false) {
            std::env::set_var("NATIVE_RECUT_OPEN", "");
            self.recut_open = true;
        }
        if !self.recut_busy
            && std::env::var("NATIVE_RECUT_RUN").map(|v| !v.is_empty()).unwrap_or(false)
        {
            std::env::set_var("NATIVE_RECUT_RUN", "");
            self.recut_open = true;
            self.recut_busy = true;
            let room = self.room_id();
            let cid = self.content_id();
            let body = serde_json::json!({
                "silence_threshold": self.recut_thresh,
                "lead": self.recut_lead,
                "tail": self.recut_tail,
            });
            self.lib_post(
                "recut",
                format!("/api/v1/production-assets/contents/{cid}/recut?room_id={room}"),
                body,
            );
        }
        if self.recut_open {
            let mut open = self.recut_open;
            egui::Window::new("カット再調整")
                .open(&mut open)
                .resizable(false)
                .default_width(300.0)
                .show(ctx, |ui| {
                    ui.label(format!("無音とみなす長さ {:.2}秒", self.recut_thresh));
                    ui.add(egui::Slider::new(&mut self.recut_thresh, 0.20..=1.20).show_value(false));
                    ui.label(format!("カット前の余白 {:.2}秒", self.recut_lead));
                    ui.add(egui::Slider::new(&mut self.recut_lead, 0.0..=0.40).show_value(false));
                    ui.label(format!("カット後の余白 {:.2}秒", self.recut_tail));
                    ui.add(egui::Slider::new(&mut self.recut_tail, 0.0..=0.60).show_value(false));
                    ui.add_space(6.0);
                    let btxt = if self.recut_busy { "再カット中…" } else { "この設定で再カット" };
                    if ui
                        .add_enabled(!self.recut_busy, egui::Button::new(btxt).min_size(egui::vec2(280.0, 28.0)))
                        .clicked()
                    {
                        self.recut_busy = true;
                        self.playing = false;
                        self.push_req(false);
                        let room = self.room_id();
                        let cid = self.content_id();
                        let body = serde_json::json!({
                            "silence_threshold": self.recut_thresh,
                            "lead": self.recut_lead,
                            "tail": self.recut_tail,
                        });
                        self.lib_post(
                            "recut",
                            format!("/api/v1/production-assets/contents/{cid}/recut?room_id={room}"),
                            body,
                        );
                    }
                    if self.recut_busy {
                        ui.horizontal(|ui| {
                            ui.spinner();
                            ui.label("組み直しています…");
                        });
                    }
                    ui.label(
                        egui::RichText::new(
                            "※ダンの自動カットを組み直します。手動のクリップ編集はリセットされます",
                        )
                        .small()
                        .weak(),
                    );
                });
            self.recut_open = open;
        }
        if let Some((msg, at)) = self.toast.clone() {
            if at.elapsed().as_secs_f32() < 3.0 {
                egui::Area::new(egui::Id::new("toast"))
                    .anchor(egui::Align2::CENTER_BOTTOM, egui::vec2(0.0, -260.0))
                    .show(ctx, |ui| {
                        egui::Frame::popup(ui.style()).show(ui, |ui| ui.label(msg));
                    });
            } else {
                self.toast = None;
            }
        }
        if let Some((cid, mut buf, original)) = self.caption_edit.clone() {
            let mut save = false;
            let mut cancel = false;
            let mut text_changed = false;
            egui::Window::new("テロップ編集")
                .collapsible(false)
                .anchor(egui::Align2::CENTER_CENTER, egui::vec2(0.0, 0.0))
                .show(ctx, |ui| {
                    let text_resp =
                        ui.add(egui::TextEdit::multiline(&mut buf).desired_width(360.0).desired_rows(3));
                    self.text_focus_ids.push(text_resp.id);
                    text_changed = text_resp.changed();
                    ui.horizontal(|ui| {
                        if ui.button("保存 (Ctrl+Enter)").clicked() {
                            save = true;
                        }
                        if ui.button("キャンセル (Esc)").clicked() {
                            cancel = true;
                        }
                    });
                });
            if ctx.input(|i| i.modifiers.ctrl && i.key_pressed(egui::Key::Enter)) {
                save = true;
            }
            if ctx.input(|i| i.key_pressed(egui::Key::Escape)) {
                cancel = true;
            }
            if text_changed {
                let text = buf.clone();
                self.stage_caption_text(&cid, text);
                ctx.request_repaint_after(std::time::Duration::from_millis(16));
            }
            if save {
                self.commit_caption_drafts(Some(&cid));
                self.caption_edit = None;
            } else if cancel {
                self.pending_undo = None;
                self.caption_drafts.remove(&cid);
                self.restore(original);
                caption_live::activate(&cid);
                self.bump_caption_epoch();
                self.caption_edit = None;
            } else {
                self.caption_edit = Some((cid, buf, original));
            }
        }
        if self.show_help {
            egui::Window::new("ショートカット (F1で閉じる)")
                .collapsible(false)
                .resizable(false)
                .anchor(egui::Align2::RIGHT_TOP, egui::vec2(-12.0, 12.0))
                .show(ctx, |ui| {
                    for (k, d) in [
                        ("Space", "再生 / 一時停止"),
                        ("← →", "1フレーム移動"),
                        ("Home / End", "先頭 / 末尾へ"),
                        ("+ / -", "ズーム"),
                        ("S", "分割"),
                        ("E", "飛び出し 適用/解除"),
                        ("F", "フリーズフレーム挿入（2秒）"),
                        ("Del", "削除（メインレーンは左詰め+付随クリップも削除）"),
                        ("Shift+Del", "削除して左詰め（全レーン強制）"),
                        ("ヘッダアイコン", "🔒ロック / 👁表示 / 🔇ミュート / Sソロ / 磁マグネット"),
                        ("Ctrl+Z / Y", "元に戻す / やり直し"),
                        ("Ctrl+D", "選択クリップを複製（直後に）"),
                        ("Ctrl+C / V", "コピー / 再生位置に貼り付け"),
                        ("Ctrl+S", "保存"),
                        ("Ctrl+Shift+Z", "やり直し"),
                        ("Ctrl+A", "全クリップ選択"),
                        ("Ctrl+クリック", "複数選択"),
                        ("空白ドラッグ", "矩形で複数選択（マーキー）"),
                        ("ドラッグ端", "トリム / 中央: 移動"),
                        ("Ctrl+ホイール", "ズーム / ホイール: 横スクロール"),
                    ] {
                        ui.horizontal(|ui| {
                            ui.monospace(format!("{k:<14}"));
                            ui.label(d);
                        });
                    }
                });
        }
        // Idle drafts are the only caption edits that take the expensive document,
        // media-cache and PNG-cache paths. This runs after all text widgets have seen
        // this frame's IME events, never in the keystroke handler itself.
        self.commit_caption_drafts(None);
        // Mouse-operated buttons/sliders must not keep Space/Enter activation.
        // Actual text and numeric editors advertise an IME output and keep focus.
        if ctx.input(|i| i.pointer.any_released()) && ctx.output(|o| o.ime.is_none()) {
            if let Some(id) = ctx.memory(|m| m.focused()) {
                if !self.text_focus_ids.contains(&id) {
                    ctx.memory_mut(|m| m.surrender_focus(id));
                }
            }
        }
        // 再描画ポリシー: かつては無条件 request_repaint() で常時約100fps＝停止中でも
        // 1コアを食い続けていた（実測83%CPU）。操作・再生・ドラッグ中だけ全速、
        // アイドルは10fpsに落とす。ポーラー類(保存デバウンス/ベイク回収/HTTP結果)は
        // 100msティックで十分回り、入力イベントが来れば即座にフレームが走る。
        let busy = self.playing
            || !matches!(self.drag, Drag::None)
            || self.resume_pending.is_some()
            || self.resume_on_release
            || self.toast.is_some()
            || self.eyedrop.is_some()
            || self.lane_reorder.is_some()
            || self.range_drag.is_some()
            || ctx.input(|i| {
                i.pointer.any_down() || !i.raw.hovered_files.is_empty() || !i.raw.events.is_empty()
            });
        if busy {
            ctx.request_repaint();
        } else {
            ctx.request_repaint_after(std::time::Duration::from_millis(100));
        }
    }

    fn on_exit(&mut self, _gl: Option<&eframe::glow::Context>) {
        // A close can happen before the idle debounce expires. Persist the completed
        // input transaction rather than silently discarding the final IME text.
        self.flush_caption_drafts();
        if let Err(e) = self.save_document() {
            eprintln!("save on exit: {e:#}");
        }
    }
}


/// Positional CLI args (contents.json path, asset dir) end at the first `--flag`;
/// everything after belongs to flags and their values. A done:// deep link is a flag-like
/// launch too, not a path.
/// Windows IFileOpenDialog（複数選択）。必ず背景スレッドから呼ぶこと —
/// COM のモーダルダイアログなので UI スレッドで呼ぶと描画が止まる。
fn pick_media_files() -> Vec<std::path::PathBuf> {
    use windows::core::w;
    use windows::Win32::System::Com::{
        CoCreateInstance, CoInitializeEx, CoTaskMemFree, CLSCTX_INPROC_SERVER,
        COINIT_APARTMENTTHREADED,
    };
    use windows::Win32::UI::Shell::{
        FileOpenDialog, IFileOpenDialog, FOS_ALLOWMULTISELECT, FOS_FORCEFILESYSTEM,
        SIGDN_FILESYSPATH,
    };
    use windows::Win32::UI::Shell::Common::COMDLG_FILTERSPEC;
    let mut out = Vec::new();
    unsafe {
        let _ = CoInitializeEx(None, COINIT_APARTMENTTHREADED);
        let Ok(dlg): windows::core::Result<IFileOpenDialog> =
            CoCreateInstance(&FileOpenDialog, None, CLSCTX_INPROC_SERVER)
        else {
            return out;
        };
        let filters = [
            COMDLG_FILTERSPEC {
                pszName: w!("動画・画像"),
                pszSpec: w!("*.mp4;*.mov;*.m4v;*.webm;*.mkv;*.avi;*.png;*.jpg;*.jpeg;*.webp"),
            },
            COMDLG_FILTERSPEC { pszName: w!("すべてのファイル"), pszSpec: w!("*.*") },
        ];
        let _ = dlg.SetFileTypes(&filters);
        if let Ok(opts) = dlg.GetOptions() {
            let _ = dlg.SetOptions(opts | FOS_ALLOWMULTISELECT | FOS_FORCEFILESYSTEM);
        }
        if dlg.Show(None).is_err() {
            return out; // cancelled
        }
        let Ok(items) = dlg.GetResults() else { return out };
        let n = items.GetCount().unwrap_or(0);
        for i in 0..n {
            if let Ok(item) = items.GetItemAt(i) {
                if let Ok(pw) = item.GetDisplayName(SIGDN_FILESYSPATH) {
                    if let Ok(s) = pw.to_string() {
                        out.push(std::path::PathBuf::from(s));
                    }
                    CoTaskMemFree(Some(pw.as_ptr() as _));
                }
            }
        }
    }
    out
}

fn positional_args(args: &[String]) -> Vec<String> {
    args.iter()
        .skip(1)
        .take_while(|a| !a.starts_with("--") && !a.starts_with("done://"))
        .take(2)
        .cloned()
        .collect()
}

fn main() -> eframe::Result<()> {
    // launched without a console (.lnk / double-click): tee diagnostics to a log file so
    // real-user sessions stay diagnosable
    unsafe {
        use windows::Win32::System::Console::{GetStdHandle, SetStdHandle, STD_ERROR_HANDLE};
        let bad = GetStdHandle(STD_ERROR_HANDLE)
            .map(|h: windows::Win32::Foundation::HANDLE| h.is_invalid())
            .unwrap_or(true);
        if bad {
            let path = format!("{}/native_ui.log", std::env::temp_dir().to_string_lossy());
            if let Ok(f) = std::fs::OpenOptions::new().create(true).append(true).open(&path) {
                use std::os::windows::io::IntoRawHandle;
                let h = windows::Win32::Foundation::HANDLE(f.into_raw_handle());
                let _ = SetStdHandle(STD_ERROR_HANDLE, h);
                eprintln!("=== native_ui start {} ===", std::process::id());
            }
        }
    }
    let args: Vec<String> = std::env::args().collect();
    load_api_token(&args);
    // --repair-linked-audio: normalize saved A/V link pairs in-place. This repairs
    // projects saved before the editor enforced linked audio as derived-from-video.
    if args.iter().any(|a| a == "--repair-linked-audio") {
        let contents = positional_args(&args).first().cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let r = (|| -> anyhow::Result<bool> {
            let mut raw: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&contents)?)?;
            let before = serde_json::to_string(&raw)?;
            edits::normalize_linked_audio(&mut raw);
            edits::remove_orphan_linked_audio(&mut raw);
            let changed = serde_json::to_string(&raw)? != before;
            if changed {
                edits::save(&raw, &contents)?;
            }
            Ok(changed)
        })();
        match r {
            Ok(true) => println!("REPAIR linked-audio updated {contents}"),
            Ok(false) => println!("REPAIR linked-audio no changes {contents}"),
            Err(e) => println!("REPAIR ERR {e:#}"),
        }
        std::process::exit(0);
    }
    // --dump-frame <t[,t2,t3...]> <out.ppm|png>: headless compose of timeline frames —
    // deterministic A/B verification with no window and no user input. Multiple
    // comma-separated times share ONE engine setup (doc/D3D/decoders), so a batch of
    // N frames costs far less than N separate spawns; outputs get ".{k}" before the
    // extension when more than one time is given.
    // --probe-timeline-audio <start> <end>: headless, deterministic check of every
    // audible timeline clip in a range. It follows playback's decoder and source-time
    // mapping, rather than trusting container metadata.
    if let Some(i) = args.iter().position(|a| a == "--probe-timeline-audio") {
        unsafe {
            let _ = windows::Win32::System::Com::CoInitializeEx(
                None,
                windows::Win32::System::Com::COINIT_MULTITHREADED,
            );
            let _ = windows::Win32::Media::MediaFoundation::MFStartup(
                windows::Win32::Media::MediaFoundation::MF_VERSION,
                windows::Win32::Media::MediaFoundation::MFSTARTUP_FULL,
            );
        }
        let contents = positional_args(&args).first().cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = positional_args(&args).get(1).cloned().unwrap_or_else(|| ROOM.to_string());
        let t0: f64 = args.get(i + 1).and_then(|v| v.parse().ok()).unwrap_or(0.0);
        let t1: f64 = args.get(i + 2).and_then(|v| v.parse().ok()).unwrap_or(t0 + 1.0);
        let doc = model::Doc::load(&contents, &dir).expect("doc load");
        set_canvas_from_content(&doc.raw);
        let any_solo = doc.seq.tracks.iter().any(|tr| tr.solo);
        let mut checked = 0usize;
        let mut audible = 0usize;
        for (own, c) in doc.active_audio_span(t0, t1) {
            let gov = doc.audio_gov_track(c, own);
            let tr = &doc.seq.tracks[gov];
            let ct0 = c.timeline_start.max(t0);
            let ct1 = c.timeline_end.min(t1);
            let src_t = c.src_at(ct0);
            let dur = (ct1 - ct0).min(0.5);
            checked += 1;
            if tr.muted || (any_solo && !tr.solo) || c.volume <= 0.001 {
                println!("AUDIO_PROBE clip={} SKIP muted={} solo_gate={} volume={:.3}", c.id, tr.muted, any_solo && !tr.solo, c.volume);
                continue;
            }
            let path = doc.asset_path(c.asset_id.as_deref().unwrap());
            match media::probe_audio_samples(&path, src_t, dur) {
                Ok((samples, peak, rms)) => {
                    let ok = peak > 0.0005;
                    audible += ok as usize;
                    println!("AUDIO_PROBE clip={} source={src_t:.3} samples={samples} peak={peak:.6} rms={rms:.6} {}", c.id, if ok { "AUDIBLE" } else { "SILENT" });
                }
                Err(e) => println!("AUDIO_PROBE clip={} ERROR {e:#}", c.id),
            }
        }
        println!("AUDIO_PROBE_SUMMARY checked={checked} audible={audible} range={t0:.3}-{t1:.3}");
        std::process::exit(if checked > 0 && audible > 0 { 0 } else { 1 });
    }
    if args.iter().any(|a| a == "--print-capkeys") {
        // diagnostic: the Rust-side render key for every designed caption + whether its
        // cache PNG exists — for A/B against the Python key (json.dumps parity check)
        let contents = positional_args(&args).first().cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = positional_args(&args).get(1).cloned().unwrap_or_else(|| ROOM.to_string());
        let doc = model::Doc::load(&contents, &dir).expect("doc load");
        set_canvas_from_content(&doc.raw);
        for tr in &doc.seq.tracks {
            for c in &tr.clips {
                if c.text.is_none() || c.asset_id.is_some() || c.region.is_some() {
                    continue;
                }
                let text = c.text.clone().unwrap_or_default();
                if text.trim().is_empty() {
                    continue;
                }
                let style = c.style.clone().unwrap_or_else(|| serde_json::json!({}));
                let key = caption_cache_key(c, &text, &style);
                let png = std::path::Path::new(&doc.asset_dir)
                    .join("caption-cache")
                    .join(format!("{key}.png"));
                println!("CAPKEY {} {} png={}", c.id, key, png.exists());
            }
        }
        return Ok(());
    }
    // --export-preview-video <out.mp4> [start] [end]: render frames through the
    // same native compositor the editor preview uses, then hand only compression to
    // ffmpeg.  No FFmpeg recreation of captions, masks, popouts, or blur is involved.
    if let Some(i) = args.iter().position(|a| a == "--export-preview-video") {
        unsafe {
            let _ = windows::Win32::System::Com::CoInitializeEx(
                None,
                windows::Win32::System::Com::COINIT_MULTITHREADED,
            );
            let _ = windows::Win32::Media::MediaFoundation::MFStartup(
                windows::Win32::Media::MediaFoundation::MF_VERSION,
                windows::Win32::Media::MediaFoundation::MFSTARTUP_FULL,
            );
        }
        let out = args.get(i + 1).cloned().unwrap_or_else(|| "preview-export.mp4".into());
        let start: f64 = args.get(i + 2).and_then(|v| v.parse().ok()).unwrap_or(0.0);
        let contents = positional_args(&args).first().cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = positional_args(&args).get(1).cloned().unwrap_or_else(|| ROOM.to_string());
        // Headless: every designed caption must come out of the GPU compositor — there
        // is no WebView overlay to carry the top-most ones.
        EXPORT_ALL_CAPTIONS.store(true, Ordering::Relaxed);
        let r = (|| -> anyhow::Result<()> {
            use anyhow::Context;
            use std::io::Write;
            let doc = model::Doc::load(&contents, &dir).context("doc load")?;
            set_canvas_from_content(&doc.raw);
            // Default end = where CONTENT ends (max clip end), NOT doc.duration():
            // seq.duration is a sticky ruler-length field that never shrinks after a
            // clip is dragged shorter — exporting it appended 36s of black+silence.
            let content_end = doc
                .seq
                .tracks
                .iter()
                .flat_map(|t| t.clips.iter())
                .map(|c| c.timeline_end)
                .fold(0.0f64, f64::max);
            let end: f64 = args
                .get(i + 3)
                .and_then(|v| v.parse().ok())
                .unwrap_or(if content_end > 0.0 { content_end } else { doc.duration() });
            let fps = doc.seq.frame_rate.unwrap_or(30.0).clamp(1.0, 60.0);
            // Pre-flight: every caption must have its cache PNG (the exact bitmap the
            // preview shows). A missing one would silently disappear from the file, so
            // it is a hard error — the backend renders the PNGs first and can retry.
            let mut missing = Vec::new();
            for tr in doc.seq.tracks.iter().filter(|tr| tr.kind != "audio" && !tr.hidden) {
                for c in &tr.clips {
                    if c.asset_id.is_some() || c.region.is_some() {
                        continue;
                    }
                    let text = c.text.clone().unwrap_or_default();
                    if text.trim().is_empty() {
                        continue;
                    }
                    let style = c.style.clone().unwrap_or_else(|| serde_json::json!({}));
                    let key = caption_cache_key(c, &text, &style);
                    let png = std::path::Path::new(&doc.asset_dir)
                        .join("caption-cache")
                        .join(format!("{key}.png"));
                    if !std::fs::metadata(&png).map(|m| m.len() > 0).unwrap_or(false) {
                        missing.push((key, c.id.clone(), text.chars().take(24).collect::<String>()));
                    }
                }
            }
            if !missing.is_empty() {
                for (key, id, text) in &missing {
                    println!("EXPORT_MISSING_CAPTION key={key} clip={id} text={text}");
                }
                anyhow::bail!("{} caption PNG(s) missing from caption-cache", missing.len());
            }
            let d3d = media::D3d::new().context("d3d")?;
            let mut pool = media::VideoPool::new();
            let mut comp = compositor::Compositor::new(&d3d, canvas_w(), canvas_h()).context("compositor")?;
            let mut masks: MaskMap = Default::default();
            while mask_build_pass(&doc, &d3d, &mut masks, None) {}
            let mut pts_maps: PtsMap = Default::default();
            while pts_load_pass(&doc, &mut pts_maps) {}
            let end = end.max(start);
            // --export-ranges "a-b,c-d,...": タイムラインの飛び飛びの区間だけを順に
            // 繋げて1本に書き出す（選択クリップ書き出し）。開始順ソート＋重なりマージ。
            // 映像・音声とも同じフレーム格子（ceil(t*fps)）に量子化するので、区間毎の
            // AVズレが累積しない。指定なし＝従来どおり [start, end) の単一区間。
            let ranges: Vec<(f64, f64)> = if let Some(spec) = args
                .iter()
                .position(|a| a == "--export-ranges")
                .and_then(|k| args.get(k + 1))
            {
                let mut v: Vec<(f64, f64)> = spec
                    .split(',')
                    .filter_map(|s| {
                        let (a, b) = s.split_once('-')?;
                        let (a, b): (f64, f64) = (a.trim().parse().ok()?, b.trim().parse().ok()?);
                        (b > a && a >= 0.0).then_some((a, b))
                    })
                    .collect();
                v.sort_by(|x, y| x.0.total_cmp(&y.0));
                let mut m: Vec<(f64, f64)> = Vec::new();
                for r in v {
                    if let Some(last) = m.last_mut() {
                        if r.0 <= last.1 + 1e-6 {
                            last.1 = last.1.max(r.1);
                            continue;
                        }
                    }
                    m.push(r);
                }
                anyhow::ensure!(!m.is_empty(), "--export-ranges: 有効な区間がありません");
                m
            } else {
                vec![(start, end)]
            };
            let fr = |t: f64| (t * fps).ceil() as u64;
            let franges: Vec<(u64, u64)> = ranges
                .iter()
                .map(|&(s, e)| (fr(s), fr(e)))
                .filter(|(a, b)| b > a)
                .collect();
            anyhow::ensure!(!franges.is_empty(), "書き出し区間が空です");
            // Audio first: the SAME timeline through the playback mixer's rules, into a
            // raw PCM sidecar that ffmpeg only compresses. 区間ごとにミックスして
            // 連結（f32le 生PCMなので単純結合で継ぎ目なし）。
            let (arate, ach) = (48_000u32, 2usize);
            let pcm = format!("{out}.pcm");
            {
                let mut pcm_out = std::fs::File::create(&pcm).context("create pcm")?;
                for (k, &(fa, fb)) in franges.iter().enumerate() {
                    let seg = format!("{out}.seg{k}.pcm");
                    media::mix_timeline_audio(&doc, fa as f64 / fps, fb as f64 / fps, arate, ach, &seg)
                        .context("mix audio")?;
                    let mut f = std::fs::File::open(&seg).context("open pcm seg")?;
                    std::io::copy(&mut f, &mut pcm_out).context("concat pcm seg")?;
                    drop(f);
                    let _ = std::fs::remove_file(&seg);
                }
            }
            println!("EXPORT_AUDIO pcm={pcm} rate={arate} ch={ach} ranges={}", franges.len());
            let ffmpeg = std::env::var("FFMPEG").unwrap_or_else(|_| "C:/Users/Owner/ffmpeg/bin/ffmpeg.exe".into());
            // ffmpeg's stderr goes to a sidecar log, NOT null: an encoder that dies
            // mid-stream otherwise fails as an unexplained "パイプは終了しました" with
            // its actual reason discarded (exactly what happened once in production).
            // Deleted on success; kept and quoted in the error on failure.
            let fflog_path = format!("{out}.ffmpeg.log");
            let fflog = std::fs::File::create(&fflog_path).context("create ffmpeg log")?;
            use std::os::windows::process::CommandExt;
            let mut child = std::process::Command::new(ffmpeg)
                .args([
                    "-y",
                    "-f", "rawvideo", "-pix_fmt", "rgba",
                    "-s", &format!("{}x{}", canvas_w(), canvas_h()),
                    "-r", &format!("{fps}"), "-i", "-",
                    "-f", "f32le", "-ar", &format!("{arate}"), "-ac", &format!("{ach}"), "-i", &pcm,
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart", &out,
                ])
                .stdin(std::process::Stdio::piped())
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::from(fflog))
                // 窓を出さない: 見えたコンソールをユーザーが閉じる=エンコーダ即死
                // (原因不明だった「パイプは終了しました」失敗の正体)
                .creation_flags(0x0800_0000) // CREATE_NO_WINDOW
                .spawn()
                .context("start ffmpeg")?;
            let stdin = child.stdin.as_mut().context("ffmpeg stdin")?;
            let total: u64 = franges.iter().map(|(a, b)| b - a).sum();
            let t_render = Instant::now();
            // PROXY quality, exactly like the interactive preview (original=false).
            // The user aligns blur keys against the PREVIEW picture; VFR sources
            // (screen recordings) land DIFFERENT frames at the same timeline time when
            // decoded from the original vs the CFR proxy — exporting the original made
            // fast-motion moments show the blur visibly off the object (measured
            // 19dB vs 45dB at t=108.0 on the real room). The proxy is near-full-res
            // for the 1080x1920 canvas, so parity costs no visible quality.
            // NATIVE_EXPORT_ORIGINAL=1 restores original-decode for A/B debugging.
            let use_original = std::env::var("NATIVE_EXPORT_ORIGINAL")
                .map(|v| !v.is_empty())
                .unwrap_or(false);
            let mut done: u64 = 0;
            for &(fa, fb) in &franges {
                for n in fa..fb {
                    let t = n as f64 / fps;
                    compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, t, use_original, false, Rb::Sync)
                        .context("compose export frame")?;
                    if let Err(e) = stdin.write_all(&comp.rgba) {
                        // ffmpeg died mid-stream — surface ITS last words, not just EPIPE
                        let tail = std::fs::read_to_string(&fflog_path)
                            .map(|s| s.chars().rev().take(400).collect::<String>().chars().rev().collect::<String>())
                            .unwrap_or_default();
                        anyhow::bail!("write export frame at t={t:.2}: {e} | ffmpeg says: {tail}");
                    }
                    done += 1;
                    if done % 150 == 0 || done == total {
                        let el = t_render.elapsed().as_secs_f64().max(0.001);
                        println!(
                            "EXPORT_PROGRESS frame={done}/{total} t={t:.2} render_fps={:.1}",
                            done as f64 / el
                        );
                        let _ = std::io::stdout().flush(); // backend tails this pipe live
                    }
                }
            }
            drop(child.stdin.take());
            let status = child.wait().context("wait ffmpeg")?;
            let _ = std::fs::remove_file(&pcm);
            if !status.success() {
                let tail = std::fs::read_to_string(&fflog_path)
                    .map(|s| s.chars().rev().take(400).collect::<String>().chars().rev().collect::<String>())
                    .unwrap_or_default();
                anyhow::bail!("ffmpeg encode failed: {status} | ffmpeg says: {tail}");
            }
            let _ = std::fs::remove_file(&fflog_path);
            println!("PREVIEW_EXPORT out={out} start={start:.3} end={end:.3} fps={fps}");
            Ok(())
        })();
        if let Err(e) = r { eprintln!("PREVIEW_EXPORT ERR {e:#}"); std::process::exit(1); }
        std::process::exit(0);
    }
    if let Some(i) = args.iter().position(|a| a == "--dump-frame") {
        // NATIVE_DUMP_ALL_CAPTIONS=1: compose WebView-plane captions natively too —
        // frames then show the FULL preview (what the user sees), for export A/B checks.
        if std::env::var("NATIVE_DUMP_ALL_CAPTIONS").map(|v| !v.is_empty()).unwrap_or(false) {
            EXPORT_ALL_CAPTIONS.store(true, Ordering::Relaxed);
        }
        let tspec = args.get(i + 1).cloned().unwrap_or_else(|| "0".into());
        let ts: Vec<f64> = tspec.split(',').filter_map(|v| v.trim().parse().ok()).collect();
        let out = args.get(i + 2).cloned().unwrap_or_else(|| "frame.ppm".into());
        let contents = positional_args(&args).first().cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = positional_args(&args).get(1).cloned().unwrap_or_else(|| ROOM.to_string());
        let r = (|| -> anyhow::Result<()> {
            use anyhow::Context;
            let doc = model::Doc::load(&contents, &dir).context("doc load")?;
            set_canvas_from_content(&doc.raw);
            let d3d = media::D3d::new().context("d3d")?;
            let mut pool = media::VideoPool::new();
            let mut comp = compositor::Compositor::new(&d3d, canvas_w(), canvas_h()).context("compositor")?;
            let mut masks: MaskMap = Default::default();
            while mask_build_pass(&doc, &d3d, &mut masks, None) {}
            let mut pts_maps: PtsMap = Default::default();
            while pts_load_pass(&doc, &mut pts_maps) {}
            let orig_q = std::env::var("NATIVE_DUMP_PROXY").map(|v| v.is_empty()).unwrap_or(true);
            for (k, &t) in ts.iter().enumerate() {
                compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, t, orig_q, false, Rb::Sync)
                    .context("compose")?;
                let path = if ts.len() == 1 {
                    out.clone()
                } else {
                    match out.rfind('.') {
                        Some(dot) => format!("{}.{}{}", &out[..dot], k, &out[dot..]),
                        None => format!("{out}.{k}"),
                    }
                };
                if path.to_lowercase().ends_with(".png") {
                    // PNG for consumers that read images (the agent's eyes)
                    image::save_buffer(&path, &comp.rgba, canvas_w(), canvas_h(), image::ColorType::Rgba8)?;
                } else {
                    let mut ppm = format!("P6\n{} {}\n255\n", canvas_w(), canvas_h()).into_bytes();
                    for px in comp.rgba.chunks(4) {
                        ppm.extend_from_slice(&px[..3]);
                    }
                    std::fs::write(&path, ppm)?;
                }
                println!("dumped t={t} -> {path}");
            }
            Ok(())
        })();
        if let Err(e) = r {
            println!("DUMP ERR {e:#}");
        }
        std::process::exit(0);
    }
    // --probe-pair <path>: open BOTH video streams of one file simultaneously and
    // alternate reads (reproduces the in-app matte-twin pattern)
    if let Some(i) = args.iter().position(|a| a == "--probe-pair") {
        let path = args.get(i + 1).cloned().unwrap_or_default();
        match media::D3d::new() {
            Ok(d3d) => {
                let mut a = media::VideoStream::open(&d3d, &path, 0, true).unwrap();
                let mut b = media::VideoStream::open(&d3d, &path, 1, true).unwrap();
                let _ = a.ensure_frame(&d3d, 1.0);
                let _ = b.ensure_frame(&d3d, 1.0);
                let t0 = std::time::Instant::now();
                for i in 1..=60 {
                    let t = 1.0 + i as f64 / 30.0;
                    let _ = a.ensure_frame(&d3d, t);
                    let _ = b.ensure_frame(&d3d, t);
                }
                let ms = t0.elapsed().as_secs_f64() * 1000.0;
                println!("PAIR seq60x2={ms:.0}ms ({:.1}ms/frame-pair)", ms / 60.0);
                // and the scrub pattern: 0.33s jumps with budget
                let t1 = std::time::Instant::now();
                let mut t = 3.0;
                for _ in 0..12 {
                    t += 0.33;
                    let _ = a.ensure_frame_scrub(&d3d, t, 14.0);
                    let _ = b.ensure_frame_scrub(&d3d, t, 14.0);
                }
                let ms = t1.elapsed().as_secs_f64() * 1000.0;
                println!("PAIR scrub12x2={ms:.0}ms ({:.1}ms/tick)", ms / 12.0);
                // now under decoder-session load: open N extra readers and repeat
                if let Some(extra) = args.get(i + 2).and_then(|v| v.parse::<usize>().ok()) {
                    let epath = args.get(i + 3).cloned().unwrap_or_else(|| path.clone());
                    let mut held = Vec::new();
                    for k in 0..extra {
                        match media::VideoStream::open(&d3d, &epath, 0, false) {
                            Ok(mut v) => {
                                let _ = v.ensure_frame(&d3d, 1.0 + k as f64);
                                held.push(v);
                            }
                            Err(e) => {
                                println!("extra open {k} failed: {e:#}");
                                break;
                            }
                        }
                    }
                    println!("held {} extra decoders", held.len());
                    let t2 = std::time::Instant::now();
                    let mut t = 8.0;
                    for _ in 0..12 {
                        t += 0.33;
                        let _ = a.ensure_frame_scrub(&d3d, t, 14.0);
                        let _ = b.ensure_frame_scrub(&d3d, t, 14.0);
                    }
                    let ms = t2.elapsed().as_secs_f64() * 1000.0;
                    println!("PAIR loaded scrub12x2={ms:.0}ms ({:.1}ms/tick)", ms / 12.0);
                }
            }
            Err(e) => println!("D3D ERR {e:#}"),
        }
        std::process::exit(0);
    }
    // --probe-многo <dir> <n>: open n mt PAIRS from popout-cache (different files) plus
    // scrub the LAST pair — reproduces the in-app many-readers state
    if let Some(i) = args.iter().position(|a| a == "--probe-many") {
        let dir = args.get(i + 1).cloned().unwrap_or_default();
        let n: usize = args.get(i + 2).and_then(|v| v.parse().ok()).unwrap_or(8);
        let d3d = media::D3d::new().unwrap();
        let mut mts: Vec<String> = std::fs::read_dir(&dir)
            .unwrap()
            .filter_map(|e| e.ok())
            .map(|e| e.path().to_string_lossy().replace(char::from(92), "/"))
            .filter(|p| p.ends_with(".mt.mp4"))
            .collect();
        mts.sort();
        mts.truncate(n);
        let mut held = Vec::new();
        for p in &mts {
            for st in [0u32, 1u32] {
                if let Ok(mut v) = media::VideoStream::open(&d3d, p, st, true) {
                    let _ = v.ensure_frame(&d3d, 1.0);
                    held.push(v);
                }
            }
        }
        println!("held {} readers over {} mt files", held.len(), mts.len());
        let last = held.len() - 2;
        let (h0, h1) = held.split_at_mut(last + 1);
        let a = &mut h0[last];
        let b = &mut h1[0];
        let t0 = std::time::Instant::now();
        let mut t = 2.0;
        for _ in 0..12 {
            t += 0.33;
            let _ = a.ensure_frame_scrub(&d3d, t, 14.0);
            let _ = b.ensure_frame_scrub(&d3d, t, 14.0);
        }
        println!("MANY scrub12x2={:.1}ms/tick", t0.elapsed().as_secs_f64() * 1000.0 / 12.0);
        // interleave with an ACTIVE 4K read each tick (the in-app compose pattern)
        if let Some(fourk) = args.get(i + 3) {
            let mut o = media::VideoStream::open(&d3d, fourk, 0, false).unwrap();
            let _ = o.ensure_frame(&d3d, 30.0);
            let (h0, h1) = held.split_at_mut(last + 1);
            let a = &mut h0[last];
            let b = &mut h1[0];
            let t1 = std::time::Instant::now();
            let mut t = 6.0;
            for k in 0..12 {
                t += 0.33;
                let _ = o.ensure_frame_scrub(&d3d, 30.0 + (k as f64) * 0.33, 12.0);
                let _ = a.ensure_frame_scrub(&d3d, t, 14.0);
                let _ = b.ensure_frame_scrub(&d3d, t, 14.0);
            }
            println!("MANY+4K scrub12x3={:.1}ms/tick", t1.elapsed().as_secs_f64() * 1000.0 / 12.0);
        }
        std::process::exit(0);
    }
    // --bench-scrub <t0>: headless scrub over the real timeline (full compose path, no UI)
    if let Some(i) = args.iter().position(|a| a == "--bench-scrub") {
        let t0v: f64 = args.get(i + 1).and_then(|v| v.parse().ok()).unwrap_or(40.0);
        let contents = positional_args(&args).first().cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = positional_args(&args).get(1).cloned().unwrap_or_else(|| ROOM.to_string());
        let doc = model::Doc::load(&contents, &dir).unwrap();
        set_canvas_from_content(&doc.raw);
        let d3d = media::D3d::new().unwrap();
        let mut pool = media::VideoPool::new();
        let mut comp = compositor::Compositor::new(&d3d, canvas_w(), canvas_h()).unwrap();
        let mut masks: MaskMap = Default::default();
        while mask_build_pass(&doc, &d3d, &mut masks, None) {}
        let mut pts_maps: PtsMap = Default::default();
        while pts_load_pass(&doc, &mut pts_maps) {}
        let mut t = t0v;
        let _ = compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, t, false, true, Rb::Sync);
        let b0 = Instant::now();
        let mut worst = 0f64;
        for _ in 0..60 {
            t += 0.33;
            let c0 = Instant::now();
            let _ = compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, t, false, true, Rb::Sync);
            worst = worst.max(c0.elapsed().as_secs_f64() * 1000.0);
        }
        let ms = b0.elapsed().as_secs_f64() * 1000.0;
        println!("BENCH scrub60={:.1}ms/tick worst={worst:.0}ms", ms / 60.0);
        std::process::exit(0);
    }
    // --selftest-apply: headless E-apply flow — strip a clip's popout, re-apply, follow
    // the bake to finalized params (uses the real local server; cached keys finish instantly)
    if args.iter().any(|a| a == "--selftest-apply") {
        let contents = positional_args(&args).first().cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = positional_args(&args).get(1).cloned().unwrap_or_else(|| ROOM.to_string());
        let mut app = App::new(&contents, &dir).expect("app");
        let target = app
            .doc
            .seq
            .tracks
            .iter()
            .filter(|tr| tr.kind == "overlay")
            .flat_map(|tr| tr.clips.iter())
            .find(|c| c.popout_params().is_some())
            .map(|c| c.id.clone())
            .expect("no popout clip to test with");
        println!("target clip: {target}");
        app.selected = vec![target.clone()];
        app.toggle_popout(); // remove
        let has = |app: &App| {
            app.doc
                .seq
                .tracks
                .iter()
                .flat_map(|tr| tr.clips.iter())
                .find(|c| c.id == target)
                .and_then(|c| c.popout_params().cloned())
        };
        assert!(has(&app).is_none(), "remove failed");
        println!("removed OK");
        app.toggle_popout(); // apply -> POST -> poll
        let t0 = std::time::Instant::now();
        loop {
            app.poll_popout_bakes();
            let p = has(&app);
            let st = app.selected.get(0).and_then(|_| app.pop_states.get(&target)).copied();
            if let Some(p) = &p {
                if p.get("overlay_key").is_some() && p.get("margins").is_some() {
                    println!(
                        "APPLY PASS key={} margins={} state={:?} ({}ms)",
                        p["overlay_key"], p["margins"],
                        match st { Some(PopState::Ready) => "Ready", Some(PopState::Baking(_)) => "Baking", Some(PopState::Failed) => "Failed", None => "None" },
                        t0.elapsed().as_millis()
                    );
                    break;
                }
            }
            if let Some(PopState::Failed) = st {
                println!("APPLY FAIL (bake failed)");
                break;
            }
            if t0.elapsed().as_secs() > 240 {
                println!("APPLY TIMEOUT state={:?}", st.map(|x| match x { PopState::Ready => "R", PopState::Baking(_) => "B", PopState::Failed => "F" }));
                break;
            }
            if let Some(PopState::Baking(pct)) = st {
                if pct > 0 && t0.elapsed().as_millis() % 3000 < 300 {
                    println!("baking {pct}%");
                }
            }
            std::thread::sleep(std::time::Duration::from_millis(250));
        }
        std::process::exit(0);
    }
    // --selftest-invariants: run EVERY edit op on a clone of the open doc and machine-
    // check the "any normal NLE behaves like this" invariants: an op introduces no new
    // same-track overlap (where structural), linked A/V pairs stay at 0ms offset, and no
    // clip goes negative. This is the regression net for the implicit-spec bugs
    // (single-voice audio, duplicate-overlap, ...) — run it after touching edits.rs.
    // --validate-contents <contents.json> <asset_dir>: headless structural check of an
    // arbitrary (draft) timeline — the editor's OWN invariants as a single source of
    // truth for the agent pipeline. Prints one JSON line: {"ok":bool,"problems":[..]}
    if args.iter().any(|a| a == "--validate-contents") {
        let contents = positional_args(&args).first().cloned().unwrap_or_default();
        let dir = positional_args(&args).get(1).cloned().unwrap_or_else(|| ROOM.to_string());
        let mut problems: Vec<String> = Vec::new();
        match model::Doc::load(&contents, &dir) {
            Err(e) => problems.push(format!("doc parse: {e:#}")),
            Ok(doc) => {
                for (ti, tr) in doc.seq.tracks.iter().enumerate() {
                    for (i, a) in tr.clips.iter().enumerate() {
                        if a.timeline_start < -1e-6 {
                            problems.push(format!("{}: negative start {:.3}", a.id, a.timeline_start));
                        }
                        if a.timeline_end - a.timeline_start < 0.045 {
                            problems.push(format!("{}: zero/negative length", a.id));
                        }
                        for b in tr.clips.iter().skip(i + 1) {
                            if a.timeline_start < b.timeline_end - 0.002
                                && b.timeline_start < a.timeline_end - 0.002
                            {
                                problems.push(format!(
                                    "lane{ti} ({}): overlap {} x {}",
                                    tr.kind, a.id, b.id
                                ));
                            }
                        }
                    }
                }
                let vids: Vec<&model::Clip> = doc
                    .seq
                    .tracks
                    .iter()
                    .filter(|t| t.kind != "audio")
                    .flat_map(|t| t.clips.iter())
                    .filter(|c| c.link_id.is_some() && c.asset_id.is_some())
                    .collect();
                for a in doc
                    .seq
                    .tracks
                    .iter()
                    .filter(|t| t.kind == "audio")
                    .flat_map(|t| t.clips.iter())
                    .filter(|c| c.link_id.is_some())
                {
                    if let Some(v) = vids.iter().find(|v| v.link_id == a.link_id) {
                        let off = (v.source_start - v.timeline_start) - (a.source_start - a.timeline_start);
                        if off.abs() > 0.002 {
                            problems.push(format!("link {:?}: A/V offset {:.3}s", a.link_id, off));
                        }
                    }
                }
            }
        }
        let esc = |s: &str| s.replace('\\', "\\\\").replace('"', "\\\"");
        let list = problems.iter().map(|p| format!("\"{}\"", esc(p))).collect::<Vec<_>>().join(",");
        println!("{{\"ok\":{},\"problems\":[{}]}}", problems.is_empty(), list);
        std::process::exit(0);
    }
    if args.iter().any(|a| a == "--selftest-invariants") {
        let contents = positional_args(&args).first().cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = positional_args(&args).get(1).cloned().unwrap_or_else(|| ROOM.to_string());
        let doc = model::Doc::load(&contents, &dir).expect("doc");
        set_canvas_from_content(&doc.raw);
        let overlaps = |d: &model::Doc| -> i64 {
            let mut n = 0i64;
            for tr in &d.seq.tracks {
                for (i, a) in tr.clips.iter().enumerate() {
                    for b in tr.clips.iter().skip(i + 1) {
                        if a.timeline_start < b.timeline_end - 0.002
                            && b.timeline_start < a.timeline_end - 0.002
                        {
                            if std::env::var("INV_DEBUG").is_ok() {
                                eprintln!(
                                    "OVL {} {} [{:.3},{:.3}] x {} [{:.3},{:.3}]",
                                    tr.kind, a.id, a.timeline_start, a.timeline_end, b.id, b.timeline_start, b.timeline_end
                                );
                            }
                            n += 1;
                        }
                    }
                }
            }
            n
        };
        let av_bad = |d: &model::Doc| -> i64 {
            let mut n = 0i64;
            let vids: Vec<&model::Clip> = d
                .seq
                .tracks
                .iter()
                .filter(|t| t.kind != "audio")
                .flat_map(|t| t.clips.iter())
                .filter(|c| c.link_id.is_some() && c.asset_id.is_some())
                .collect();
            for a in d
                .seq
                .tracks
                .iter()
                .filter(|t| t.kind == "audio")
                .flat_map(|t| t.clips.iter())
                .filter(|c| c.link_id.is_some())
            {
                if let Some(v) = vids.iter().find(|v| v.link_id == a.link_id) {
                    let off = (v.source_start - v.timeline_start) - (a.source_start - a.timeline_start);
                    if off.abs() > 0.002 {
                        n += 1;
                    }
                }
            }
            n
        };
        let neg = |d: &model::Doc| -> i64 {
            d.seq
                .tracks
                .iter()
                .flat_map(|t| t.clips.iter())
                .filter(|c| c.timeline_start < -0.001 || c.timeline_end < c.timeline_start - 0.001)
                .count() as i64
        };
        let (ov0, av0, ng0) = (overlaps(&doc), av_bad(&doc), neg(&doc));
        let vid = doc
            .seq
            .tracks
            .iter()
            .filter(|t| t.kind != "audio")
            .flat_map(|t| t.clips.iter())
            .filter(|c| c.asset_id.is_some() && c.dur() > 1.0)
            .nth(2)
            .map(|c| c.id.clone())
            .expect("clip");
        let ids = edits::expand_links(&doc.raw, &[vid.clone()]);
        let mid = doc
            .seq
            .tracks
            .iter()
            .flat_map(|t| t.clips.iter())
            .find(|c| c.id == vid)
            .map(|c| (c.timeline_start + c.timeline_end) / 2.0)
            .unwrap();
        type Op = (&'static str, bool, Box<dyn Fn(&mut serde_json::Value)>);
        let ids2 = ids.clone();
        let ids3 = ids.clone();
        let ids4 = ids.clone();
        let ids5 = ids.clone();
        let ids6 = ids.clone();
        let ids7 = ids.clone();
        let ops: Vec<Op> = vec![
            ("split", true, Box::new(move |r| edits::split_clips(r, &ids2, mid, 99))),
            ("ripple_delete", true, Box::new(move |r| edits::ripple_delete(r, &ids3))),
            ("duplicate", true, Box::new(move |r| edits::duplicate_clips(r, &ids4, 99))),
            // free move may overlap by USER intent — overlap delta not checked
            ("move+0.5", false, Box::new(move |r| edits::move_clips(r, &ids5, 0.5))),
            ("move-9999", false, Box::new(move |r| edits::move_clips(r, &ids6, -9999.0))),
            ("volume0.5", true, Box::new(move |r| edits::set_volume(r, &ids7, 0.5))),
        ];
        let mut fail = 0;
        for (name, check_ov, op) in ops {
            let mut raw = doc.raw.clone();
            op(&mut raw);
            edits::normalize_linked_audio(&mut raw);
            edits::remove_orphan_linked_audio(&mut raw);
            match model::Doc::from_raw(raw, &doc.contents_path, &doc.asset_dir) {
                Ok(nd) => {
                    let dov = overlaps(&nd) - ov0;
                    let dav = av_bad(&nd) - av0;
                    let dng = neg(&nd) - ng0;
                    let ok = (!check_ov || dov <= 0) && dav <= 0 && dng <= 0;
                    if !ok {
                        fail += 1;
                        // name the NEW pairs (id-keyed, coordinate independent)
                        let pairs = |d: &model::Doc| -> std::collections::HashSet<(String, String)> {
                            let mut out = std::collections::HashSet::new();
                            for tr in &d.seq.tracks {
                                for (i, a) in tr.clips.iter().enumerate() {
                                    for b in tr.clips.iter().skip(i + 1) {
                                        if a.timeline_start < b.timeline_end - 0.002
                                            && b.timeline_start < a.timeline_end - 0.002
                                        {
                                            out.insert((a.id.clone(), b.id.clone()));
                                        }
                                    }
                                }
                            }
                            out
                        };
                        let before = pairs(&doc);
                        for p in pairs(&nd).difference(&before) {
                            println!("  NEWPAIR {} x {}", p.0, p.1);
                        }
                    }
                    println!(
                        "INV {name:<14} {} new_overlaps={dov} av_broken={dav} negative={dng}",
                        if ok { "PASS" } else { "FAIL" }
                    );
                }
                Err(e) => {
                    fail += 1;
                    println!("INV {name:<14} FAIL reparse: {e:#}");
                }
            }
        }
        println!("INVARIANTS {}", if fail == 0 { "ALL PASS" } else { "FAILURES" });
        std::process::exit(if fail == 0 { 0 } else { 1 });
    }
    // --selftest-magnet: main-lane delete closes the gap AND takes attached clips
    // (head-under rule) with it, without touching BGM-style standalone audio
    if args.iter().any(|a| a == "--selftest-magnet") {
        let contents = positional_args(&args).first().cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = positional_args(&args).get(1).cloned().unwrap_or_else(|| ROOM.to_string());
        let doc = model::Doc::load(&contents, &dir).expect("doc");
        set_canvas_from_content(&doc.raw);
        // pick a main-lane clip that has at least one caption whose HEAD sits inside it
        let main_ti = doc.seq.tracks.iter().position(|t| t.kind == "video").expect("video lane");
        let caps: Vec<(String, f64)> = doc
            .seq
            .tracks
            .iter()
            .filter(|t| t.kind == "caption")
            .flat_map(|t| t.clips.iter())
            .map(|c| (c.id.clone(), c.timeline_start))
            .collect();
        let target = doc.seq.tracks[main_ti]
            .clips
            .iter()
            .find(|v| {
                v.asset_id.is_some()
                    && caps.iter().any(|(_, h)| *h >= v.timeline_start && *h < v.timeline_end - 0.01)
            })
            .expect("clip with attached caption");
        let (vid, ts, te) = (target.id.clone(), target.timeline_start, target.timeline_end);
        let attached: Vec<String> = caps
            .iter()
            .filter(|(_, h)| *h >= ts && *h < te - 0.01)
            .map(|(id, _)| id.clone())
            .collect();
        let ids = edits::expand_links(&doc.raw, &[vid.clone()]);
        let mut raw = doc.raw.clone();
        // same sequence the Del key runs: generic attached pass, then magnet ripple
        let attached = edits::attached_to(&raw, &ids);
        if !attached.is_empty() {
            let att = edits::expand_links(&raw, &attached);
            edits::delete_clips(&mut raw, &att);
        }
        edits::magnet_delete(&mut raw, &ids);
        let nd = model::Doc::from_raw(raw, &doc.contents_path, &doc.asset_dir).expect("redoc");
        let alive: std::collections::HashSet<&str> = nd
            .seq
            .tracks
            .iter()
            .flat_map(|t| t.clips.iter())
            .map(|c| c.id.as_str())
            .collect();
        let attached_gone = attached.iter().all(|id| !alive.contains(id.as_str()));
        let main_gone = !alive.contains(vid.as_str());
        // gap closed: the clip after `te` moved left by (te - ts)
        let d = te - ts;
        let next_before = doc.seq.tracks[main_ti]
            .clips
            .iter()
            .filter(|c| c.timeline_start >= te - 1e-6)
            .min_by(|a, b| a.timeline_start.partial_cmp(&b.timeline_start).unwrap())
            .map(|c| (c.id.clone(), c.timeline_start));
        let gap_closed = next_before
            .as_ref()
            .map(|(id, old_ts)| {
                nd.seq.tracks[main_ti]
                    .clips
                    .iter()
                    .find(|c| &c.id == id)
                    .map(|c| (c.timeline_start - (old_ts - d)).abs() < 0.002)
                    .unwrap_or(false)
            })
            .unwrap_or(true);
        let synthetic = serde_json::json!([{
            "timeline": {"sequence": {"tracks": [
                {"id":"v0","type":"video","clips":[
                    {"id":"main","asset_id":"m","timeline_start":0.0,"timeline_end":10.0,"source_start":0.0,"source_end":10.0}
                ]},
                {"id":"ov1","type":"overlay","clips":[
                    {"id":"mid","asset_id":"x","timeline_start":2.0,"timeline_end":6.0,"source_start":0.0,"source_end":4.0}
                ]},
                {"id":"ov2","type":"overlay","clips":[
                    {"id":"top","asset_id":"y","timeline_start":3.0,"timeline_end":5.0,"source_start":0.0,"source_end":2.0}
                ]}
            ]}}
        }]);
        let main_attach_ok = edits::attached_to(&synthetic, &["main".to_string()]) == vec!["mid".to_string(), "top".to_string()];
        let non_main_attach_ok = edits::attached_to(&synthetic, &["mid".to_string()]).is_empty();
        let ok = attached_gone && main_gone && gap_closed && main_attach_ok && non_main_attach_ok;
        println!(
            "MAGNET {} main_gone={main_gone} attached={}/{} gone gap_closed={gap_closed} main_attach_ok={main_attach_ok} non_main_attach_ok={non_main_attach_ok}",
            if ok { "PASS" } else { "FAIL" },
            attached.iter().filter(|id| !alive.contains(id.as_str())).count(),
            attached.len()
        );
        std::process::exit(if ok { 0 } else { 1 });
    }
    // --selftest-fzins: freeze-frame + asset insert on a doc clone — machine checks
    if args.iter().any(|a| a == "--selftest-fzins") {
        let contents = positional_args(&args).first().cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = positional_args(&args).get(1).cloned().unwrap_or_else(|| ROOM.to_string());
        let doc = model::Doc::load(&contents, &dir).expect("doc");
        set_canvas_from_content(&doc.raw);
        let v = doc
            .seq
            .tracks
            .iter()
            .filter(|t| t.kind == "video")
            .flat_map(|t| t.clips.iter())
            .find(|c| c.asset_id.is_some() && c.dur() > 2.0)
            .expect("clip");
        let (vid, ts, te) = (v.id.clone(), v.timeline_start, v.timeline_end);
        let t = (ts + te) / 2.0;
        let before: usize = doc.seq.tracks.iter().map(|t| t.clips.len()).sum();
        // freeze
        let mut raw = doc.raw.clone();
        edits::freeze_frame(&mut raw, &vid, t, 2.0, 42);
        let nd = model::Doc::from_raw(raw, &doc.contents_path, &doc.asset_dir).expect("redoc");
        let fz = nd
            .seq
            .tracks
            .iter()
            .flat_map(|tr| tr.clips.iter())
            .find(|c| c.id.starts_with("fz_42"))
            .expect("freeze clip");
        let fz_ok = fz.is_freeze()
            && (fz.timeline_start - t).abs() < 0.01
            && (fz.dur() - 2.0).abs() < 0.01;
        // the clip after the original end must have shifted +2.0
        let shifted_ok = {
            let old_next = doc
                .seq
                .tracks
                .iter()
                .flat_map(|tr| tr.clips.iter())
                .filter(|c| c.timeline_start >= te - 1e-6 && c.id != vid)
                .min_by(|a, b| a.timeline_start.partial_cmp(&b.timeline_start).unwrap());
            old_next
                .map(|c| {
                    nd.seq
                        .tracks
                        .iter()
                        .flat_map(|tr| tr.clips.iter())
                        .find(|n| n.id == c.id)
                        .map(|n| (n.timeline_start - (c.timeline_start + 2.0)).abs() < 0.01)
                        .unwrap_or(false)
                })
                .unwrap_or(true)
        };
        // insert
        let aid = doc.asset_names.keys().next().cloned().unwrap_or_default();
        let mut raw2 = doc.raw.clone();
        edits::insert_asset(&mut raw2, t, 3.0, &aid, true, 43);
        let nd2 = model::Doc::from_raw(raw2, &doc.contents_path, &doc.asset_dir).expect("redoc2");
        let after2: usize = nd2.seq.tracks.iter().map(|t| t.clips.len()).sum();
        let ins = nd2
            .seq
            .tracks
            .iter()
            .flat_map(|tr| tr.clips.iter())
            .find(|c| c.id == "ins_v_43")
            .expect("inserted");
        let ins_ok = after2 == before + 2 && (ins.timeline_start - t).abs() < 0.01 && ins.link_id.is_some();
        let ok = fz_ok && shifted_ok && ins_ok;
        println!(
            "FZINS {} freeze_ok={fz_ok} shift_ok={shifted_ok} insert_ok={ins_ok}",
            if ok { "PASS" } else { "FAIL" }
        );
        std::process::exit(if ok { 0 } else { 1 });
    }
    // --selftest-trim: trim handles keep same-lane clips usable: selected right-trim
    // pushes neighbours on growth, magnetic lanes close gaps on both edge shrinks,
    // non-magnetic lanes keep shrink gaps.
    if args.iter().any(|a| a == "--selftest-trim") {
        let base = serde_json::json!([{
            "timeline": {"sequence": {"tracks": [
                {"id":"v0","type":"video","clips":[
                    {"id":"a","asset_id":"aa","link_id":"la","timeline_start":0.0,"timeline_end":4.0,"source_start":0.0,"source_end":4.0},
                    {"id":"b","asset_id":"bb","link_id":"lb","timeline_start":4.0,"timeline_end":8.0,"source_start":0.0,"source_end":4.0},
                    {"id":"e","asset_id":"ee","link_id":"le","timeline_start":8.0,"timeline_end":10.0,"source_start":0.0,"source_end":2.0}
                ]},
                {"id":"ov0","type":"overlay","magnet":false,"clips":[
                    {"id":"c","asset_id":"cc","timeline_start":0.0,"timeline_end":4.0,"source_start":0.0,"source_end":4.0},
                    {"id":"d","asset_id":"dd","timeline_start":4.0,"timeline_end":5.0,"source_start":0.0,"source_end":1.0},
                    {"id":"g","asset_id":"gg","timeline_start":8.2,"timeline_end":9.0,"source_start":0.0,"source_end":0.8}
                ]},
                {"id":"au0","type":"audio","clips":[
                    {"id":"aaud","asset_id":"aa","link_id":"la","timeline_start":0.0,"timeline_end":4.0,"source_start":0.0,"source_end":4.0},
                    {"id":"baud","asset_id":"bb","link_id":"lb","timeline_start":4.0,"timeline_end":8.0,"source_start":0.0,"source_end":4.0},
                    {"id":"eaud","asset_id":"ee","link_id":"le","timeline_start":8.0,"timeline_end":10.0,"source_start":0.0,"source_end":2.0}
                ]}
            ]}}
        }]);
        let clip = |raw: &serde_json::Value, id: &str, key: &str| -> f64 {
            raw.get(0)
                .and_then(|r| r.get("timeline"))
                .and_then(|t| t.get("sequence"))
                .and_then(|s| s.get("tracks"))
                .and_then(|t| t.as_array())
                .into_iter()
                .flatten()
                .flat_map(|tr| tr.get("clips").and_then(|c| c.as_array()).into_iter().flatten())
                .find(|c| c.get("id").and_then(|v| v.as_str()) == Some(id))
                .and_then(|c| c.get(key))
                .and_then(|v| v.as_f64())
                .unwrap_or(-999.0)
        };
        let exists = |raw: &serde_json::Value, id: &str| -> bool {
            raw.get(0)
                .and_then(|r| r.get("timeline"))
                .and_then(|t| t.get("sequence"))
                .and_then(|s| s.get("tracks"))
                .and_then(|t| t.as_array())
                .into_iter()
                .flatten()
                .flat_map(|tr| tr.get("clips").and_then(|c| c.as_array()).into_iter().flatten())
                .any(|c| c.get("id").and_then(|v| v.as_str()) == Some(id))
        };

        let mut right_shrink = base.clone();
        edits::trim_clip(&mut right_shrink, &["a".to_string()], false, 3.0);
        let ok_right_shrink_gap = (clip(&right_shrink, "a", "timeline_end") - 3.0).abs() < 0.001
            && (clip(&right_shrink, "b", "timeline_start") - 3.0).abs() < 0.001
            && (clip(&right_shrink, "b", "timeline_end") - 7.0).abs() < 0.001
            && (clip(&right_shrink, "e", "timeline_start") - 7.0).abs() < 0.001
            && (clip(&right_shrink, "aaud", "timeline_end") - 3.0).abs() < 0.001
            && (clip(&right_shrink, "baud", "timeline_start") - 3.0).abs() < 0.001
            && (clip(&right_shrink, "baud", "timeline_end") - 7.0).abs() < 0.001
            && (clip(&right_shrink, "d", "timeline_start") - 4.0).abs() < 0.001;

        let mut live_left_drag = base.clone();
        edits::trim_clip_live_from(&mut live_left_drag, &["b".to_string()], true, 4.0, 5.0, &[]);
        let ok_live_left_drag = (clip(&live_left_drag, "a", "timeline_start") - 0.0).abs() < 0.001
            && (clip(&live_left_drag, "a", "timeline_end") - 4.0).abs() < 0.001
            && (clip(&live_left_drag, "b", "timeline_start") - 4.0).abs() < 0.001
            && (clip(&live_left_drag, "b", "timeline_end") - 7.0).abs() < 0.001
            && (clip(&live_left_drag, "e", "timeline_start") - 7.0).abs() < 0.001
            && (clip(&live_left_drag, "b", "source_start") - 1.0).abs() < 0.001;

        edits::trim_clip_live_from(&mut live_left_drag, &["b".to_string()], true, 5.0, 4.0, &[]);
        let ok_live_left_grow = (clip(&live_left_drag, "a", "timeline_start") - 0.0).abs() < 0.001
            && (clip(&live_left_drag, "a", "timeline_end") - 4.0).abs() < 0.001
            && (clip(&live_left_drag, "b", "timeline_start") - 4.0).abs() < 0.001
            && (clip(&live_left_drag, "b", "timeline_end") - 8.0).abs() < 0.001
            && (clip(&live_left_drag, "e", "timeline_start") - 8.0).abs() < 0.001
            && (clip(&live_left_drag, "b", "source_start") - 0.0).abs() < 0.001;

        let mut live_left_grow_from_handle = base.clone();
        live_left_grow_from_handle[0]["timeline"]["sequence"]["tracks"][0]["clips"][1]["source_start"] = serde_json::Value::from(1.0);
        live_left_grow_from_handle[0]["timeline"]["sequence"]["tracks"][0]["clips"][1]["source_end"] = serde_json::Value::from(5.0);
        live_left_grow_from_handle[0]["timeline"]["sequence"]["tracks"][2]["clips"][1]["source_start"] = serde_json::Value::from(1.0);
        live_left_grow_from_handle[0]["timeline"]["sequence"]["tracks"][2]["clips"][1]["source_end"] = serde_json::Value::from(5.0);
        edits::trim_clip_live_from(&mut live_left_grow_from_handle, &["b".to_string()], true, 4.0, 3.0, &[]);
        let ok_live_left_grow_keeps_overlap = (clip(&live_left_grow_from_handle, "a", "timeline_start") - 0.0).abs() < 0.001
            && (clip(&live_left_grow_from_handle, "a", "timeline_end") - 4.0).abs() < 0.001
            && (clip(&live_left_grow_from_handle, "b", "timeline_start") - 4.0).abs() < 0.001
            && (clip(&live_left_grow_from_handle, "b", "timeline_end") - 9.0).abs() < 0.001
            && (clip(&live_left_grow_from_handle, "e", "timeline_start") - 9.0).abs() < 0.001
            && (clip(&live_left_grow_from_handle, "b", "source_start") - 0.0).abs() < 0.001;
        edits::settle_overlaps(&mut live_left_grow_from_handle, &["b".to_string()]);
        let ok_left_grow_settle_erases_overlap = (clip(&live_left_grow_from_handle, "a", "timeline_end") - 4.0).abs() < 0.001
            && (clip(&live_left_grow_from_handle, "b", "timeline_start") - 4.0).abs() < 0.001
            && (clip(&live_left_grow_from_handle, "b", "timeline_end") - 9.0).abs() < 0.001
            && (clip(&live_left_grow_from_handle, "e", "timeline_start") - 9.0).abs() < 0.001;

        let mut magnetic_left_shrink = base.clone();
        edits::trim_clip_live_from(&mut magnetic_left_shrink, &["b".to_string()], true, 4.0, 5.0, &[]);
        edits::settle_left_trim(&mut magnetic_left_shrink, &["b".to_string()]);
        let ok_mag_left_shrink = (clip(&magnetic_left_shrink, "a", "timeline_start") - 0.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "a", "timeline_end") - 4.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "b", "timeline_start") - 4.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "b", "timeline_end") - 7.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "b", "source_start") - 1.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "e", "timeline_start") - 7.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "g", "timeline_start") - 8.2).abs() < 0.001
            && (clip(&magnetic_left_shrink, "aaud", "timeline_start") - 0.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "aaud", "timeline_end") - 4.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "baud", "timeline_start") - 4.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "baud", "timeline_end") - 7.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "baud", "source_start") - 1.0).abs() < 0.001;

        edits::trim_clip_live_from(&mut magnetic_left_shrink, &["b".to_string()], true, 5.0, 4.0, &[]);
        edits::settle_left_trim(&mut magnetic_left_shrink, &["b".to_string()]);
        let ok_mag_left_restore = (clip(&magnetic_left_shrink, "a", "timeline_start") - 0.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "a", "timeline_end") - 4.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "b", "timeline_start") - 4.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "b", "timeline_end") - 8.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "e", "timeline_start") - 8.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "b", "source_start") - 0.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "aaud", "timeline_end") - 4.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "baud", "timeline_start") - 4.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "baud", "timeline_end") - 8.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "baud", "source_start") - 0.0).abs() < 0.001;

        let mut main_magnet_off = base.clone();
        main_magnet_off[0]["timeline"]["sequence"]["tracks"][0]["magnet"] = serde_json::Value::Bool(false);
        edits::trim_clip_live_from(&mut main_magnet_off, &["b".to_string()], true, 4.0, 5.0, &[]);
        let ok_main_off_left_shrink_gap = (clip(&main_magnet_off, "a", "timeline_end") - 4.0).abs() < 0.001
            && (clip(&main_magnet_off, "b", "timeline_start") - 5.0).abs() < 0.001
            && (clip(&main_magnet_off, "b", "timeline_end") - 8.0).abs() < 0.001
            && (clip(&main_magnet_off, "e", "timeline_start") - 8.0).abs() < 0.001
            && (clip(&main_magnet_off, "b", "source_start") - 1.0).abs() < 0.001;

        let mut main_off_left_grow = base.clone();
        main_off_left_grow[0]["timeline"]["sequence"]["tracks"][0]["magnet"] = serde_json::Value::Bool(false);
        main_off_left_grow[0]["timeline"]["sequence"]["tracks"][0]["clips"][1]["source_start"] = serde_json::Value::from(1.0);
        main_off_left_grow[0]["timeline"]["sequence"]["tracks"][0]["clips"][1]["source_end"] = serde_json::Value::from(5.0);
        main_off_left_grow[0]["timeline"]["sequence"]["tracks"][2]["clips"][1]["source_start"] = serde_json::Value::from(1.0);
        main_off_left_grow[0]["timeline"]["sequence"]["tracks"][2]["clips"][1]["source_end"] = serde_json::Value::from(5.0);
        edits::trim_clip_live_from(&mut main_off_left_grow, &["b".to_string()], true, 4.0, 3.0, &[]);
        let ok_main_off_left_grow_keeps_overlap = (clip(&main_off_left_grow, "a", "timeline_end") - 4.0).abs() < 0.001
            && (clip(&main_off_left_grow, "b", "timeline_start") - 4.0).abs() < 0.001
            && (clip(&main_off_left_grow, "b", "timeline_end") - 9.0).abs() < 0.001
            && (clip(&main_off_left_grow, "e", "timeline_start") - 9.0).abs() < 0.001
            && (clip(&main_off_left_grow, "b", "source_start") - 0.0).abs() < 0.001;
        edits::settle_overlaps(&mut main_off_left_grow, &["b".to_string()]);
        let ok_main_off_left_grow_settle_erases_overlap = (clip(&main_off_left_grow, "a", "timeline_end") - 4.0).abs() < 0.001
            && (clip(&main_off_left_grow, "b", "timeline_start") - 4.0).abs() < 0.001
            && (clip(&main_off_left_grow, "b", "timeline_end") - 9.0).abs() < 0.001
            && (clip(&main_off_left_grow, "e", "timeline_start") - 9.0).abs() < 0.001;

        let mut free_shrink = base.clone();
        edits::trim_clip(&mut free_shrink, &["c".to_string()], false, 3.0);
        let ok_free_shrink = (clip(&free_shrink, "c", "timeline_end") - 3.0).abs() < 0.001
            && (clip(&free_shrink, "d", "timeline_start") - 4.0).abs() < 0.001;

        let mut free_grow = base.clone();
        edits::trim_clip(&mut free_grow, &["c".to_string()], false, 5.0);
        let ok_free_grow = (clip(&free_grow, "c", "timeline_end") - 5.0).abs() < 0.001
            && !exists(&free_grow, "d");

        let ok = ok_right_shrink_gap
            && ok_live_left_drag
            && ok_live_left_grow
            && ok_live_left_grow_keeps_overlap
            && ok_left_grow_settle_erases_overlap
            && ok_mag_left_shrink
            && ok_mag_left_restore
            && ok_main_off_left_shrink_gap
            && ok_main_off_left_grow_keeps_overlap
            && ok_main_off_left_grow_settle_erases_overlap
            && ok_free_shrink
            && ok_free_grow;
        println!(
            "TRIM {} right_shrink_gap={ok_right_shrink_gap} live_left_drag={ok_live_left_drag} live_left_grow={ok_live_left_grow} live_left_grow_keeps_overlap={ok_live_left_grow_keeps_overlap} left_grow_settle_erases_overlap={ok_left_grow_settle_erases_overlap} magnetic_left_shrink={ok_mag_left_shrink} magnetic_left_restore={ok_mag_left_restore} main_off_left_shrink_gap={ok_main_off_left_shrink_gap} main_off_left_grow_keeps_overlap={ok_main_off_left_grow_keeps_overlap} main_off_left_grow_settle_erases_overlap={ok_main_off_left_grow_settle_erases_overlap} free_shrink={ok_free_shrink} free_grow={ok_free_grow}",
            if ok { "PASS" } else { "FAIL" }
        );
        std::process::exit(if ok { 0 } else { 1 });
    }
    // --selftest-fzops: freeze clips must SURVIVE every edit op, and video clips must
    // never silently BECOME freezes (the trim-crossing bug class)
    if args.iter().any(|a| a == "--selftest-fzops") {
        let contents = positional_args(&args).first().cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = positional_args(&args).get(1).cloned().unwrap_or_else(|| ROOM.to_string());
        let doc = model::Doc::load(&contents, &dir).expect("doc");
        set_canvas_from_content(&doc.raw);
        let count_fz = |d: &model::Doc| -> usize {
            d.seq.tracks.iter().flat_map(|t| t.clips.iter()).filter(|c| c.is_freeze()).count()
        };
        let fz = doc
            .seq
            .tracks
            .iter()
            .flat_map(|t| t.clips.iter())
            .find(|c| c.is_freeze())
            .expect("freeze clip in doc");
        let vid = doc
            .seq
            .tracks
            .iter()
            .filter(|t| t.kind == "video")
            .flat_map(|t| t.clips.iter())
            .find(|c| c.asset_id.is_some() && !c.is_freeze() && c.dur() > 1.0)
            .expect("video clip");
        let base_fz = count_fz(&doc);
        let mut fails = 0;
        let mut check = |name: &str, raw: serde_json::Value, want_fz: usize| {
            let nd = model::Doc::from_raw(raw, &doc.contents_path, &doc.asset_dir).expect("redoc");
            let n = count_fz(&nd);
            let ok = n == want_fz;
            if !ok {
                fails += 1;
            }
            println!("FZOPS {name:<22} {} freezes={n} want={want_fz}", if ok { "PASS" } else { "FAIL" });
        };
        // freeze extend right (+2s): stays a freeze
        let mut r1 = doc.raw.clone();
        edits::trim_clip(&mut r1, &[fz.id.clone()], false, fz.timeline_end + 2.0);
        check("fz-extend-right", r1, base_fz);
        // freeze shrink left: stays a freeze
        let mut r2 = doc.raw.clone();
        edits::trim_clip(&mut r2, &[fz.id.clone()], true, fz.timeline_start + 0.5);
        check("fz-shrink-left", r2, base_fz);
        // video right-trim WAY past its source span: must NOT become a freeze
        let mut r3 = doc.raw.clone();
        edits::trim_clip(&mut r3, &[vid.id.clone()], false, vid.timeline_start + 0.06);
        check("vid-hard-shrink", r3, base_fz);
        // video left-trim past its out-point: must NOT become a freeze
        let mut r4 = doc.raw.clone();
        edits::trim_clip(&mut r4, &[vid.id.clone()], true, vid.timeline_end - 0.06);
        check("vid-hard-lefttrim", r4, base_fz);
        // split a freeze: BOTH halves stay freezes
        let mut r5 = doc.raw.clone();
        edits::split_clips(&mut r5, &[fz.id.clone()], (fz.timeline_start + fz.timeline_end) / 2.0, 77);
        check("fz-split", r5, base_fz + 1);
        // duplicate a freeze: the copy is a freeze
        let mut r6 = doc.raw.clone();
        edits::duplicate_clips(&mut r6, &[fz.id.clone()], 78);
        check("fz-duplicate", r6, base_fz + 1);
        println!("FZOPS {}", if fails == 0 { "ALL PASS" } else { "FAILURES" });
        std::process::exit(if fails == 0 { 0 } else { 1 });
    }
    // --selftest-step: frame stepping must visit EVERY source frame exactly once, and
    // stepping out of a freeze must land on the SAME frame the still holds
    if args.iter().any(|a| a == "--selftest-step") {
        let contents = positional_args(&args).first().cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = positional_args(&args).get(1).cloned().unwrap_or_else(|| ROOM.to_string());
        let doc = model::Doc::load(&contents, &dir).expect("doc");
        set_canvas_from_content(&doc.raw);
        let mut cache: PtsCache = Default::default();
        let mut fails = 0;
        let mut check = |name: &str, ok: bool, detail: String| {
            if !ok {
                fails += 1;
            }
            println!("STEP {name:<18} {} {detail}", if ok { "PASS" } else { "FAIL" });
        };
        // pick a freeze that has a non-freeze video clip right after it on the same
        // lane — preferring a NEW-CONTRACT freeze (right piece rewound onto the still's
        // frame, PR#491); legacy freezes keep the old +1 semantics in their data
        let pairs: Vec<_> = doc
            .seq
            .tracks
            .iter()
            .flat_map(|tr| {
                tr.clips.iter().filter_map(move |fz| {
                    if !fz.is_freeze() {
                        return None;
                    }
                    let nx = tr.clips.iter().find(|n| {
                        !n.is_freeze()
                            && n.asset_id.is_some()
                            && (n.timeline_start - fz.timeline_end).abs() < 0.02
                            && n.dur() > 1.0
                    })?;
                    Some((fz.clone(), nx.clone()))
                })
            })
            .collect();
        // new-contract discriminator: the left neighbour's out-point sits one frame
        // PAST the still's source (split at frame end); legacy has them equal
        let left_of = |fz: &model::Clip| {
            doc.seq
                .tracks
                .iter()
                .flat_map(|tr| tr.clips.iter())
                .find(|c| {
                    !c.is_freeze()
                        && c.asset_id == fz.asset_id
                        && (c.timeline_end - fz.timeline_start).abs() < 0.02
                })
                .cloned()
        };
        let is_new = |fz: &model::Clip| {
            left_of(fz)
                .and_then(|lc| lc.source_end)
                .map(|se| se - fz.source_start > 0.005)
                .unwrap_or(false)
        };
        let pick = pairs
            .iter()
            .find(|(fz, _)| is_new(fz))
            .or_else(|| pairs.first())
            .cloned();
        if let Some((fz, nx)) = pick {
            let new_contract = is_new(&fz);
            println!("STEP pair fz={} new_contract={new_contract}", fz.id);
            let aid = nx.asset_id.clone().unwrap();
            let pts = cached_pts(&doc, &mut cache, &aid).expect("pts sidecar");
            // 1) step right out of the freeze: must land on the freeze's OWN frame
            //    (the still) as shown by the right clip = nearest frame of fz.source_start
            let mut t = fz.timeline_end - 0.02;
            t = step_target(&doc, &mut cache, t, 1.0).expect("step out");
            let src = nx.source_start + (t - nx.timeline_start);
            let got = nearest_idx(&pts, src);
            // landing correctness: the right clip's FIRST whole frame, always
            let first = edge_frame(&pts, nx.source_start, 1.0);
            check(
                "fz-exit-first-frame",
                t > fz.timeline_end && got == first,
                format!("t={t:.4} frame={got} want={first}"),
            );
            // same-frame contract: on new freezes that first frame IS the still's frame
            let want = nearest_idx(&pts, fz.source_start + 1e-4);
            if new_contract {
                check(
                    "fz-exit-same-frame",
                    got == want,
                    format!("frame={got} still={want}"),
                );
            } else {
                println!("STEP fz-exit-same-frame SKIP (legacy freeze in doc)");
            }
            // 2) 30 more right steps: every step advances by EXACTLY one frame
            let mut prev = got;
            let mut ok = true;
            let mut detail = String::new();
            for i in 0..30 {
                t = step_target(&doc, &mut cache, t, 1.0).expect("step");
                if t >= nx.timeline_end {
                    break;
                }
                let k = nearest_idx(&pts, nx.source_start + (t - nx.timeline_start));
                if k != prev + 1 {
                    ok = false;
                    detail = format!("step{i}: {prev} -> {k}");
                    break;
                }
                prev = k;
            }
            check("fwd-one-by-one", ok, detail);
            // 3) same walk backwards
            let mut ok = true;
            let mut detail = String::new();
            for i in 0..25 {
                t = step_target(&doc, &mut cache, t, -1.0).expect("back");
                if t <= nx.timeline_start {
                    break;
                }
                let k = nearest_idx(&pts, nx.source_start + (t - nx.timeline_start));
                if k != prev - 1 {
                    ok = false;
                    detail = format!("step{i}: {prev} -> {k}");
                    break;
                }
                prev = k;
            }
            check("back-one-by-one", ok, detail);
            // 4) stepping LEFT into the clip before the freeze lands on ITS last frame,
            //    which by the same-frame contract is ALSO the still's frame
            if let Some(lc) = left_of(&fz) {
                let t2 = step_target(&doc, &mut cache, fz.timeline_start + 0.01, -1.0)
                    .expect("step left out");
                let k = nearest_idx(&pts, lc.source_start + (t2 - lc.timeline_start));
                // the left clip's LAST whole frame; on new freezes == the still's frame
                let se = lc.source_end.unwrap_or(lc.source_start + lc.dur());
                let last = edge_frame(&pts, se, -1.0);
                check(
                    "fz-left-last-frame",
                    t2 < fz.timeline_start && k == last && (!new_contract || k == want),
                    format!("t={t2:.4} frame={k} last={last} still={want}"),
                );
            }
        } else {
            println!("STEP no freeze+next pair in doc — skipped boundary checks");
        }
        println!("STEP {}", if fails == 0 { "ALL PASS" } else { "FAILURES" });
        std::process::exit(if fails == 0 { 0 } else { 1 });
    }
    // --selftest-dup: headless duplicate — both placement branches on a doc CLONE:
    //   A) LAST clip (space after) -> contiguous copy right after, nothing else moves
    //   B) MIDDLE clip (packed)    -> copy at the SAME time on another lane, nothing moves
    if args.iter().any(|a| a == "--selftest-dup") {
        let contents = positional_args(&args).first().cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = positional_args(&args).get(1).cloned().unwrap_or_else(|| ROOM.to_string());
        let doc = model::Doc::load(&contents, &dir).expect("doc");
        set_canvas_from_content(&doc.raw);
        let count_overlaps = |d: &model::Doc| -> i64 {
            let mut n = 0i64;
            for tr in &d.seq.tracks {
                for (i, a) in tr.clips.iter().enumerate() {
                    for b in tr.clips.iter().skip(i + 1) {
                        if a.timeline_start < b.timeline_end - 0.002
                            && b.timeline_start < a.timeline_end - 0.002
                        {
                            n += 1;
                        }
                    }
                }
            }
            n
        };
        let run = |name: &str, pick_last: bool| {
            let vids: Vec<&model::Clip> = doc
                .seq
                .tracks
                .iter()
                .filter(|t| t.kind != "audio")
                .flat_map(|t| t.clips.iter())
                .filter(|c| c.asset_id.is_some() && c.dur() > 1.0)
                .collect();
            let target = if pick_last {
                vids.iter().max_by(|a, b| a.timeline_end.partial_cmp(&b.timeline_end).unwrap()).unwrap()
            } else {
                &vids[2]
            };
            let vid = target.id.clone();
            let (ots, ote) = (target.timeline_start, target.timeline_end);
            let ids = edits::expand_links(&doc.raw, &[vid.clone()]);
            let mut raw = doc.raw.clone();
            edits::duplicate_clips(&mut raw, &ids, 7);
            let nd = model::Doc::from_raw(raw, &doc.contents_path, &doc.asset_dir).expect("redoc");
            let copy = nd
                .seq
                .tracks
                .iter()
                .flat_map(|t| t.clips.iter())
                .find(|c| c.id.starts_with(&vid) && c.id.contains("__dup_"))
                .expect("copy");
            // nothing else may move — every original clip keeps identical times
            let before: std::collections::HashMap<&str, (f64, f64)> = doc
                .seq
                .tracks
                .iter()
                .flat_map(|t| t.clips.iter())
                .map(|c| (c.id.as_str(), (c.timeline_start, c.timeline_end)))
                .collect();
            let mut moved = 0usize;
            for tr in &nd.seq.tracks {
                for c in &tr.clips {
                    if c.id.contains("__dup_") {
                        continue;
                    }
                    if let Some(&(ts, te)) = before.get(c.id.as_str()) {
                        if (ts - c.timeline_start).abs() > 0.002 || (te - c.timeline_end).abs() > 0.002 {
                            moved += 1;
                        }
                    }
                }
            }
            let new_ov = count_overlaps(&nd) - count_overlaps(&doc);
            let placement = if (copy.timeline_start - ote).abs() < 0.01 {
                "after"
            } else if (copy.timeline_start - ots).abs() < 0.01 {
                "other-lane"
            } else {
                "???"
            };
            let ok = moved == 0 && new_ov <= 0 && placement != "???";
            println!(
                "DUP[{name}] {} placement={placement} moved={moved} new_overlaps={new_ov} copy=[{:.2},{:.2}] orig=[{:.2},{:.2}]",
                if ok { "PASS" } else { "FAIL" },
                copy.timeline_start, copy.timeline_end, ots, ote
            );
            ok
        };
        let a = run("last", true);
        let b = run("middle", false);
        std::process::exit(if a && b { 0 } else { 1 });
    }
    // --selftest-layer-order: asset-backed clips on any non-audio lane render by stack order.
    if args.iter().any(|a| a == "--selftest-layer-order") {
        let raw = serde_json::json!([{
            "timeline": {
                "sequence": {
                    "tracks": [
                        {"type": "video", "clips": [
                            {"id": "base", "asset_id": "a", "timeline_start": 0.0, "timeline_end": 5.0, "source_start": 0.0}
                        ]},
                        {"type": "caption", "clips": [
                            {"id": "top", "asset_id": "b", "timeline_start": 0.0, "timeline_end": 5.0, "source_start": 0.0}
                        ]},
                        {"type": "audio", "clips": [
                            {"id": "aud", "asset_id": "c", "timeline_start": 0.0, "timeline_end": 5.0, "source_start": 0.0}
                        ]}
                    ]
                }
            }
        }]);
        let doc = model::Doc::from_raw(raw, "", "").expect("doc");
        let (base, overlays) = doc.active_video(1.0);
        let ok = base.map(|c| c.id.as_str()) == Some("base")
            && overlays.iter().map(|c| c.id.as_str()).collect::<Vec<_>>() == vec!["top"];
        println!("LAYER_ORDER {}", if ok { "PASS" } else { "FAIL" });
        std::process::exit(if ok { 0 } else { 1 });
    }
    // --selftest-move: headless lane-move — move an overlay clip to the video track
    if args.iter().any(|a| a == "--selftest-move") {
        let contents = positional_args(&args).first().cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = positional_args(&args).get(1).cloned().unwrap_or_else(|| ROOM.to_string());
        let mut app = App::new(&contents, &dir).expect("app");
        let (src_ti, cid) = app
            .doc
            .seq
            .tracks
            .iter()
            .enumerate()
            .filter(|(_, tr)| tr.kind == "overlay")
            .flat_map(|(ti, tr)| tr.clips.iter().map(move |c| (ti, c.id.clone())))
            .next()
            .expect("no overlay clip");
        let target = app
            .doc
            .seq
            .tracks
            .iter()
            .position(|tr| tr.kind == "video")
            .expect("no video track");
        println!("moving {cid} from track {src_ti} to {target}");
        app.drop_move_to_lane(&[cid.clone()], target);
        let now_in = app
            .doc
            .seq
            .tracks
            .iter()
            .position(|tr| tr.clips.iter().any(|c| c.id == cid));
        println!(
            "MOVE {} (now in track {:?})",
            if now_in == Some(target) { "PASS" } else { "FAIL" },
            now_in
        );
        std::process::exit(0);
    }
    // --selftest-newlane: headless "drag above the top lane" — new provisional lane is
    // created (even from the front lane), repeat is idempotent, moving back dissolves it
    // --selftest-kf: position-keyframe engine — set/replace/remove/clear, linear
    // interpolation, and trim keeping keys pinned to absolute timeline moments
    if args.iter().any(|a| a == "--selftest-kf") {
        use serde_json::json;
        let mut raw = json!([{ "timeline": { "sequence": { "tracks": [
            { "type": "effect", "clips": [
                { "id": "fx1", "region": {"x": 0.1, "y": 0.3, "width": 0.2, "height": 0.1},
                  "style": "gaussian", "timeline_start": 10.0, "timeline_end": 14.0 }
            ]}
        ]}}}]);
        let clip_of = |raw: &serde_json::Value| -> model::Clip {
            serde_json::from_value(raw[0]["timeline"]["sequence"]["tracks"][0]["clips"][0].clone())
                .expect("clip parse")
        };
        edits::set_region_key(&mut raw, "fx1", 0.0, 0.1, 0.3, 0.2, 0.1);
        edits::set_region_key(&mut raw, "fx1", 4.0, 0.6, 0.3, 0.2, 0.1);
        let c = clip_of(&raw);
        let x_at = |c: &model::Clip, t: f64| c.region_at(t).unwrap().0;
        let ok1 = (x_at(&c, 11.0) - 0.225).abs() < 1e-6
            && (x_at(&c, 13.0) - 0.475).abs() < 1e-6
            && (x_at(&c, 9.0) - 0.1).abs() < 1e-6
            && (x_at(&c, 15.0) - 0.6).abs() < 1e-6;
        println!("KF interp     {}", if ok1 { "PASS" } else { "FAIL" });
        edits::set_region_key(&mut raw, "fx1", 0.003, 0.2, 0.35, 0.2, 0.1);
        let c = clip_of(&raw);
        let ok2 = c.region_key_times().len() == 2 && (x_at(&c, 10.0) - 0.2).abs() < 1e-6;
        println!("KF replace    {} (keys={})", if ok2 { "PASS" } else { "FAIL" }, c.region_key_times().len());
        // 60fps VFR: keys one real frame apart (~16ms) must ALL survive — the old
        // 1/60s replace window silently deleted the previous frame's key
        edits::set_region_key(&mut raw, "fx1", 0.016, 0.25, 0.35, 0.2, 0.1);
        edits::set_region_key(&mut raw, "fx1", 0.033, 0.3, 0.35, 0.2, 0.1);
        edits::set_region_key(&mut raw, "fx1", 0.049, 0.35, 0.35, 0.2, 0.1);
        let c = clip_of(&raw);
        let ok2b = c.region_key_times().len() == 5;
        println!("KF 60fps-adj  {} (keys={} want 5)", if ok2b { "PASS" } else { "FAIL" }, c.region_key_times().len());
        // deleting the middle key must not swallow its 16ms neighbours
        edits::remove_region_key(&mut raw, "fx1", 0.033);
        let c = clip_of(&raw);
        let ok3a = c.region_key_times().len() == 4 && !c.region_key_times().contains(&0.033);
        println!("KF del-narrow {} (keys={})", if ok3a { "PASS" } else { "FAIL" }, c.region_key_times().len());
        for t in [0.003, 0.016, 0.049] {
            edits::remove_region_key(&mut raw, "fx1", t);
        }
        let c = clip_of(&raw);
        let ok3 = c.region_key_times() == vec![4.0];
        println!("KF remove-one {}", if ok3 { "PASS" } else { "FAIL" });
        let ok2 = ok2 && ok2b && ok3a;
        edits::set_region_key(&mut raw, "fx1", 0.0, 0.1, 0.3, 0.2, 0.1);
        let before_x = x_at(&clip_of(&raw), 12.0);
        let ids: Vec<String> = vec!["fx1".into()];
        edits::trim_clip_live_from(&mut raw, &ids, true, 10.0, 11.0, &[]);
        let c = clip_of(&raw);
        let ok4 = (c.timeline_start - 11.0).abs() < 1e-6 && (x_at(&c, 12.0) - before_x).abs() < 1e-3;
        println!("KF trim-pin   {} (ts={} x@12={:.4} want {:.4})",
                 if ok4 { "PASS" } else { "FAIL" }, c.timeline_start, x_at(&c, 12.0), before_x);
        edits::trim_clip_live_from(&mut raw, &ids, true, 11.0, 9.0, &[]);
        let c = clip_of(&raw);
        let ok5 = (c.timeline_start - 9.0).abs() < 1e-6 && (x_at(&c, 12.0) - before_x).abs() < 1e-3;
        println!("KF extend-pin {} (ts={} x@12={:.4})", if ok5 { "PASS" } else { "FAIL" }, c.timeline_start, x_at(&c, 12.0));
        edits::clear_region_keys(&mut raw, "fx1");
        let ok6 = clip_of(&raw).region_key_times().is_empty();
        println!("KF clear      {}", if ok6 { "PASS" } else { "FAIL" });
        // key edits must invalidate the composed-frame cache: dirty_from has to see
        // region_keys (it didn't — stale cached frames served the OLD blur position)
        let d_before = model::Doc::from_raw(raw.clone(), "", "").expect("doc a");
        edits::set_region_key(&mut raw, "fx1", 1.0, 0.5, 0.5, 0.2, 0.1);
        let d_after = model::Doc::from_raw(raw.clone(), "", "").expect("doc b");
        let df = App::dirty_from(&d_before, &d_after);
        let ok7 = df.is_finite() && (df - d_after.seq.tracks[0].clips[0].timeline_start).abs() < 1e-6;
        println!("KF cache-inval {} (dirty_from={df})", if ok7 { "PASS" } else { "FAIL" });
        // split: keys partition at the cut, right half re-bases, both sides pin the
        // cut-moment position — a verbatim clone replayed the left motion after the cut
        edits::clear_region_keys(&mut raw, "fx1");
        edits::set_region_key(&mut raw, "fx1", 0.0, 0.1, 0.3, 0.2, 0.1);
        edits::set_region_key(&mut raw, "fx1", 4.0, 0.6, 0.3, 0.2, 0.1);
        edits::split_clips(&mut raw, &ids, 11.0, 42);
        let clips = raw[0]["timeline"]["sequence"]["tracks"][0]["clips"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        let lh: model::Clip = serde_json::from_value(clips[0].clone()).expect("left");
        let rh: model::Clip = serde_json::from_value(clips[1].clone()).expect("right");
        let ok8 = clips.len() == 2
            && (x_at(&lh, 10.0) - 0.225).abs() < 1e-3   // 前半: 元の補間そのまま
            && (x_at(&lh, 10.99) - 0.35).abs() < 5e-3   // 前半: カット際=カット時位置
            && (x_at(&rh, 11.0) - 0.35).abs() < 1e-3    // 後半: カット時位置から開始（クローン再生しない）
            && (x_at(&rh, 12.0) - 0.475).abs() < 1e-3   // 後半: 元の補間と連続
            && (x_at(&rh, 13.0) - 0.6).abs() < 1e-3
            && lh.region_key_times().len() == 2
            && rh.region_key_times().len() == 2;
        println!(
            "KF split      {} (L={:?} R={:?})",
            if ok8 { "PASS" } else { "FAIL" },
            lh.region_key_times(),
            rh.region_key_times()
        );
        // cut BEYOND all keys: no phantom key at the cut — the keyless right half
        // holds the position via its base rect instead
        edits::clear_region_keys(&mut raw, "fx1");
        edits::set_region_key(&mut raw, "fx1", 0.2, 0.2, 0.3, 0.2, 0.1);
        edits::set_region_key(&mut raw, "fx1", 0.5, 0.3, 0.3, 0.2, 0.1);
        edits::split_clips(&mut raw, &ids, 10.5, 43);
        let clips = raw[0]["timeline"]["sequence"]["tracks"][0]["clips"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        let l2: model::Clip = serde_json::from_value(clips[0].clone()).expect("left2");
        let r2: model::Clip = serde_json::from_value(clips[1].clone()).expect("right2");
        let ok9 = l2.region_key_times().len() == 2
            && r2.region_key_times().is_empty()
            && (r2.region_xywh().map(|r| r.0).unwrap_or(0.0) - 0.3).abs() < 1e-3
            && (x_at(&r2, 10.7) - 0.3).abs() < 1e-3;
        println!(
            "KF split-tail {} (L={:?} Rkeys={} Rx={:.3})",
            if ok9 { "PASS" } else { "FAIL" },
            l2.region_key_times(),
            r2.region_key_times().len(),
            r2.region_xywh().map(|r| r.0).unwrap_or(-1.0)
        );
        // off-screen rects survive: negative x kept (min 5% visible), keys too,
        // region_at no longer clamps back inside
        edits::clear_region_keys(&mut raw, "fx1");
        edits::set_region(&mut raw, "fx1", -0.1, 0.3, 0.2, 0.1);
        let c = clip_of(&raw);
        let okx = c.region_xywh().map(|r| (r.0 + 0.1).abs() < 1e-6).unwrap_or(false);
        edits::set_region_key(&mut raw, "fx1", 0.1, -0.08, 0.3, 0.2, 0.1);
        let c = clip_of(&raw);
        let ok10 = okx && (x_at(&c, 9.1) + 0.08).abs() < 1e-6;
        println!("KF offscreen  {} (base_x={:?} key_x={:.3})",
                 if ok10 { "PASS" } else { "FAIL" },
                 c.region_xywh().map(|r| r.0), x_at(&c, 9.1));
        // SIZE keyframes: w/h interpolate; legacy keys without w/h read the base size
        edits::clear_region_keys(&mut raw, "fx1");
        edits::set_region(&mut raw, "fx1", 0.1, 0.3, 0.1, 0.05);
        edits::set_region_key(&mut raw, "fx1", 0.0, 0.1, 0.3, 0.1, 0.05);
        edits::set_region_key(&mut raw, "fx1", 1.0, 0.1, 0.3, 0.3, 0.15);
        let c = clip_of(&raw);
        let sz = |t: f64| c.region_at(t).map(|r| (r.2, r.3)).unwrap_or((0.0, 0.0));
        let ok11a = (sz(9.5).0 - 0.2).abs() < 1e-6 && (sz(9.5).1 - 0.1).abs() < 1e-6
            && (sz(9.0).0 - 0.1).abs() < 1e-6 && (sz(10.5).0 - 0.3).abs() < 1e-6;
        // legacy position-only key mixed in → base size at that key
        if let Some(keys) = raw[0]["timeline"]["sequence"]["tracks"][0]["clips"][0]["region_keys"].as_array_mut() {
            keys.push(serde_json::json!({"t": 2.0, "x": 0.5, "y": 0.3}));
        }
        let c2 = clip_of(&raw);
        let legacy_w = c2.region_at(11.0).map(|r| r.2).unwrap_or(0.0);
        let ok11b = (legacy_w - 0.1).abs() < 1e-6; // rel=2 → legacy key → base w=0.1
        let ok11 = ok11a && ok11b;
        println!("KF size       {} (w@9.5={:.3} legacy_w@11={legacy_w:.3})",
                 if ok11 { "PASS" } else { "FAIL" }, sz(9.5).0);
        // OFF-mode drag = rigid trajectory move: every key shifts by the same delta,
        // count unchanged, motion SHAPE identical (no new key ever)
        edits::clear_region_keys(&mut raw, "fx1");
        edits::set_region(&mut raw, "fx1", 0.1, 0.3, 0.2, 0.1);
        edits::set_region_key(&mut raw, "fx1", 0.0, 0.1, 0.3, 0.2, 0.1);
        edits::set_region_key(&mut raw, "fx1", 1.0, 0.4, 0.3, 0.2, 0.1);
        let snapshot = clip_of(&raw).region_keys.clone().unwrap();
        edits::offset_region_keys(&mut raw, "fx1", &snapshot, 0.05, 0.1, 0.1, 0.05);
        let c = clip_of(&raw);
        let ok12 = c.region_key_times().len() == 2
            && (x_at(&c, 9.0) - 0.15).abs() < 1e-6
            && (x_at(&c, 10.0) - 0.45).abs() < 1e-6
            && (c.region_at(9.5).unwrap().1 - 0.4).abs() < 1e-6
            && (c.region_at(9.5).unwrap().2 - 0.3).abs() < 1e-6;
        println!("KF offset-all {} (keys={} x@9={:.3} x@10={:.3} w@9.5={:.3})",
                 if ok12 { "PASS" } else { "FAIL" },
                 c.region_key_times().len(), x_at(&c, 9.0), x_at(&c, 10.0),
                 c.region_at(9.5).unwrap().2);
        let all = ok1 && ok2 && ok3 && ok4 && ok5 && ok6 && ok7 && ok8 && ok9 && ok10 && ok11 && ok12;
        println!("KF ALL {}", if all { "PASS" } else { "FAIL" });
        std::process::exit(if all { 0 } else { 1 });
    }
    // --selftest-tkf: MEDIA-clip transform keyframes (display box + crop) —
    // interpolation, replace window, crop carry-over, remove/clear, trim pinning,
    // split partitioning, rigid trajectory offset, w/h & crop base fallbacks
    if args.iter().any(|a| a == "--selftest-tkf") {
        use serde_json::json;
        // vc1 lives on the SECOND video lane — the plain trim path with absolute-moment
        // pinning (the main magnet lane's ripple path gets its own check below)
        let mut raw = json!([{ "timeline": { "sequence": { "tracks": [
            { "type": "video", "clips": [
                { "id": "base1", "asset_id": "a0", "source_start": 0.0, "source_end": 99.0,
                  "timeline_start": 0.0, "timeline_end": 20.0 }
            ]},
            { "type": "video", "clips": [
                { "id": "vc1", "asset_id": "a1", "source_start": 0.0, "source_end": 99.0,
                  "timeline_start": 10.0, "timeline_end": 14.0,
                  "position": {"x": 0.1, "y": 0.2, "width": 0.4, "height": 0.3},
                  "crop": {"left": 0.1} }
            ]}
        ]}}}]);
        let clip_of = |raw: &serde_json::Value| -> model::Clip {
            serde_json::from_value(raw[0]["timeline"]["sequence"]["tracks"][1]["clips"][0].clone())
                .expect("clip parse")
        };
        let bx = |c: &model::Clip, t: f64| c.display_box_at(t);
        let cl_at = |c: &model::Clip, t: f64| c.crop_ltrb_at(t).map(|c| c.0).unwrap_or(0.0);
        // interp: box AND crop animate linearly, ends clamp
        edits::set_transform_key(&mut raw, "vc1", 0.0, 0.1, 0.2, 0.4, 0.3, Some((0.1, 0.0, 0.0, 0.0)));
        edits::set_transform_key(&mut raw, "vc1", 4.0, 0.5, 0.2, 0.2, 0.15, Some((0.3, 0.0, 0.0, 0.0)));
        let c = clip_of(&raw);
        let m = bx(&c, 12.0);
        let ok1 = (m.x - 0.3).abs() < 1e-6
            && (m.width - 0.3).abs() < 1e-6
            && (m.height - 0.225).abs() < 1e-6
            && (bx(&c, 9.0).x - 0.1).abs() < 1e-6
            && (bx(&c, 15.0).x - 0.5).abs() < 1e-6
            && (cl_at(&c, 12.0) - 0.2).abs() < 1e-6;
        println!("TKF interp    {}", if ok1 { "PASS" } else { "FAIL" });
        // replace window + crop carry-over: re-writing the key WITHOUT crop keeps it
        edits::set_transform_key(&mut raw, "vc1", 0.003, 0.15, 0.25, 0.4, 0.3, None);
        let c = clip_of(&raw);
        let ok2 = c.transform_key_times().len() == 2
            && (bx(&c, 10.0).x - 0.15).abs() < 1e-6
            && (cl_at(&c, 10.0) - 0.1).abs() < 1e-6;
        println!("TKF carry     {} (keys={} crop_l@10={:.3})",
                 if ok2 { "PASS" } else { "FAIL" }, c.transform_key_times().len(), cl_at(&c, 10.0));
        // key WITHOUT w/h and WITHOUT crop reads the base box size / base crop
        if let Some(keys) = raw[0]["timeline"]["sequence"]["tracks"][1]["clips"][0]["transform_keys"].as_array_mut() {
            keys.push(json!({"t": 2.0, "x": 0.3, "y": 0.2}));
        }
        let c = clip_of(&raw);
        let ok3 = (bx(&c, 12.0).width - 0.4).abs() < 1e-6 && (cl_at(&c, 12.0) - 0.1).abs() < 1e-6;
        println!("TKF fallback  {} (w@12={:.3} crop_l@12={:.3})",
                 if ok3 { "PASS" } else { "FAIL" }, bx(&c, 12.0).width, cl_at(&c, 12.0));
        // remove one / clear all
        edits::remove_transform_key(&mut raw, "vc1", 2.0);
        let ok4a = clip_of(&raw).transform_key_times().len() == 2;
        edits::clear_transform_keys(&mut raw, "vc1");
        let ok4 = ok4a && clip_of(&raw).transform_key_times().is_empty();
        println!("TKF del/clear {}", if ok4 { "PASS" } else { "FAIL" });
        // trim: keys stay pinned to the same ABSOLUTE timeline moment
        edits::set_transform_key(&mut raw, "vc1", 0.0, 0.1, 0.2, 0.4, 0.3, None);
        edits::set_transform_key(&mut raw, "vc1", 4.0, 0.5, 0.2, 0.4, 0.3, None);
        let before_x = bx(&clip_of(&raw), 12.0).x;
        let ids: Vec<String> = vec!["vc1".into()];
        edits::trim_clip_live_from(&mut raw, &ids, true, 10.0, 11.0, &[]);
        let c = clip_of(&raw);
        let ok5 = (c.timeline_start - 11.0).abs() < 1e-6 && (bx(&c, 12.0).x - before_x).abs() < 1e-3;
        println!("TKF trim-pin  {} (ts={} x@12={:.4} want {:.4})",
                 if ok5 { "PASS" } else { "FAIL" }, c.timeline_start, bx(&c, 12.0).x, before_x);
        edits::trim_clip_live_from(&mut raw, &ids, true, 11.0, 10.0, &[]);
        // main magnet lane: ripple trim goes through trim_main_lane_live — keys must
        // stay glued to the same SOURCE frame (the lane also pins itself to t=0)
        let mut rawm = json!([{ "timeline": { "sequence": { "tracks": [
            { "type": "video", "clips": [
                { "id": "vm1", "asset_id": "a1", "source_start": 0.0, "source_end": 99.0,
                  "timeline_start": 10.0, "timeline_end": 14.0,
                  "position": {"x": 0.1, "y": 0.2, "width": 0.4, "height": 0.3} }
            ]}
        ]}}}]);
        edits::set_transform_key(&mut rawm, "vm1", 0.0, 0.1, 0.2, 0.4, 0.3, None);
        edits::set_transform_key(&mut rawm, "vm1", 4.0, 0.5, 0.2, 0.4, 0.3, None);
        let idsm: Vec<String> = vec!["vm1".into()];
        edits::trim_clip_live_from(&mut rawm, &idsm, true, 10.0, 11.0, &[]);
        let cm: model::Clip =
            serde_json::from_value(rawm[0]["timeline"]["sequence"]["tracks"][0]["clips"][0].clone())
                .expect("vm1 parse");
        // ts pinned to 0 by the magnet; source frame 2.0 (was t=12, x=0.3) now at rel 1.0
        let ok5b = (cm.timeline_start - 0.0).abs() < 1e-6
            && (cm.source_start - 1.0).abs() < 1e-6
            && (bx(&cm, 1.0).x - 0.3).abs() < 1e-3;
        println!("TKF trim-main {} (ts={} ss={} x@1={:.4})",
                 if ok5b { "PASS" } else { "FAIL" }, cm.timeline_start, cm.source_start, bx(&cm, 1.0).x);
        let ok5 = ok5 && ok5b;
        // split: keys partition at the cut, both sides continuous, no clone replay
        edits::split_clips(&mut raw, &ids, 12.0, 42);
        let clips = raw[0]["timeline"]["sequence"]["tracks"][1]["clips"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        let lh: model::Clip = serde_json::from_value(clips[0].clone()).expect("left");
        let rh: model::Clip = serde_json::from_value(clips[1].clone()).expect("right");
        let ok6 = clips.len() == 2
            && (bx(&lh, 11.0).x - 0.2).abs() < 1e-3
            && (bx(&lh, 11.99).x - 0.3).abs() < 5e-3
            && (bx(&rh, 12.0).x - 0.3).abs() < 1e-3
            && (bx(&rh, 13.0).x - 0.4).abs() < 1e-3
            && lh.transform_key_times().len() == 2
            && rh.transform_key_times().len() == 2;
        println!(
            "TKF split     {} (L={:?} R={:?})",
            if ok6 { "PASS" } else { "FAIL" },
            lh.transform_key_times(),
            rh.transform_key_times()
        );
        // split BEYOND all keys: keyless side holds the look via base position, no
        // phantom key (rebuild the doc: single clip, keys only in the first second)
        let mut raw2 = json!([{ "timeline": { "sequence": { "tracks": [
            { "type": "video", "clips": [
                { "id": "vc2", "asset_id": "a1", "source_start": 0.0, "source_end": 99.0,
                  "timeline_start": 10.0, "timeline_end": 14.0,
                  "position": {"x": 0.1, "y": 0.2, "width": 0.4, "height": 0.3} }
            ]}
        ]}}}]);
        edits::set_transform_key(&mut raw2, "vc2", 0.2, 0.2, 0.2, 0.4, 0.3, Some((0.2, 0.0, 0.0, 0.0)));
        edits::set_transform_key(&mut raw2, "vc2", 0.5, 0.3, 0.2, 0.4, 0.3, Some((0.2, 0.0, 0.0, 0.0)));
        let ids2: Vec<String> = vec!["vc2".into()];
        edits::split_clips(&mut raw2, &ids2, 12.0, 43);
        let clips2 = raw2[0]["timeline"]["sequence"]["tracks"][0]["clips"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        let r2: model::Clip = serde_json::from_value(clips2[1].clone()).expect("right2");
        let ok7 = r2.transform_key_times().is_empty()
            && (r2.display_box().x - 0.3).abs() < 1e-3
            && (r2.crop_ltrb().map(|c| c.0).unwrap_or(0.0) - 0.2).abs() < 1e-3;
        println!(
            "TKF split-tail {} (Rkeys={} Rx={:.3} Rcrop={:.3})",
            if ok7 { "PASS" } else { "FAIL" },
            r2.transform_key_times().len(),
            r2.display_box().x,
            r2.crop_ltrb().map(|c| c.0).unwrap_or(-1.0)
        );
        // OFF-mode drag = rigid trajectory shift: same key count, same motion shape,
        // crops ride along untouched
        let mut raw3 = json!([{ "timeline": { "sequence": { "tracks": [
            { "type": "video", "clips": [
                { "id": "vc3", "asset_id": "a1", "source_start": 0.0, "source_end": 99.0,
                  "timeline_start": 10.0, "timeline_end": 14.0,
                  "position": {"x": 0.1, "y": 0.2, "width": 0.4, "height": 0.3} }
            ]}
        ]}}}]);
        let clip3 = |raw: &serde_json::Value| -> model::Clip {
            serde_json::from_value(raw[0]["timeline"]["sequence"]["tracks"][0]["clips"][0].clone())
                .expect("clip3 parse")
        };
        edits::set_transform_key(&mut raw3, "vc3", 0.0, 0.1, 0.2, 0.4, 0.3, Some((0.15, 0.0, 0.0, 0.0)));
        edits::set_transform_key(&mut raw3, "vc3", 1.0, 0.4, 0.2, 0.4, 0.3, None);
        let snapshot = clip3(&raw3).transform_keys.clone().unwrap();
        edits::offset_transform_keys(&mut raw3, "vc3", &snapshot, 0.05, 0.1, 0.1, 0.05);
        let c = clip3(&raw3);
        let ok8 = c.transform_key_times().len() == 2
            && (bx(&c, 10.0).x - 0.15).abs() < 1e-6
            && (bx(&c, 11.0).x - 0.45).abs() < 1e-6
            && (bx(&c, 10.5).y - 0.3).abs() < 1e-6
            && (bx(&c, 10.5).width - 0.5).abs() < 1e-6
            && (cl_at(&c, 10.0) - 0.15).abs() < 1e-6;
        println!("TKF offset    {} (x@10={:.3} x@11={:.3} w={:.3} crop_l={:.3})",
                 if ok8 { "PASS" } else { "FAIL" },
                 bx(&c, 10.0).x, bx(&c, 11.0).x, bx(&c, 10.5).width, cl_at(&c, 10.0));
        let all = ok1 && ok2 && ok3 && ok4 && ok5 && ok6 && ok7 && ok8;
        println!("TKF ALL {}", if all { "PASS" } else { "FAIL" });
        std::process::exit(if all { 0 } else { 1 });
    }
    if args.iter().any(|a| a == "--selftest-trimseq") {
        // 右→左トリムのUI相当シーケンス検証（Drag::Trimアームと同じ last_t 簿記）
        let mk = || -> serde_json::Value {
            serde_json::json!([{ "timeline": { "sequence": { "duration": 10.0, "frame_rate": 30, "tracks": [
                { "id": "v0", "type": "video", "clips": [
                    { "id": "V", "asset_id": "img", "track": "video",
                      "source_start": 0.0, "source_end": 2.0, "timeline_start": 0.0, "timeline_end": 2.0 },
                    { "id": "W", "asset_id": "vid", "track": "video",
                      "source_start": 0.0, "source_end": 2.0, "timeline_start": 2.0, "timeline_end": 4.0 }]},
                { "id": "a0", "type": "audio", "clips": [] }
            ]}}}])
        };
        let get = |raw: &serde_json::Value, id: &str, key: &str| -> f64 {
            raw[0]["timeline"]["sequence"]["tracks"]
                .as_array().unwrap().iter()
                .flat_map(|t| t["clips"].as_array().unwrap().iter())
                .find(|c| c["id"] == id)
                .and_then(|c| c[key].as_f64())
                .unwrap_or(-1.0)
        };
        let ids = vec!["W".to_string()];
        let mut ok = true;
        let mut check = |name: &str, got: f64, want: f64| {
            let pass = (got - want).abs() <= 0.02;
            println!("TRIMSEQ {name:<32} {} got={got:.3} want={want:.3}", if pass { "PASS" } else { "FAIL" });
            if !pass { ok = false; }
        };
        // A) 単一ドラッグ: 右0.5 → 左0.8 (マウス 2.0→2.5→1.7)
        let mut raw = mk();
        let mut last_t = 2.0;
        let mut mouse = 2.0;
        for _ in 0..5 { mouse += 0.1; last_t += edits::trim_clip_live_from(&mut raw, &ids, true, last_t, mouse, &[]); }
        for _ in 0..8 { mouse -= 0.1; last_t += edits::trim_clip_live_from(&mut raw, &ids, true, last_t, mouse, &[]); }
        edits::settle_overlaps(&mut raw, &ids);
        // 縮小0.5で頭ソース0.5sが余白化 → 反転0.8のうち0.5が消化されて停止
        check("A: single r->l W.ts", get(&raw, "W", "timeline_start"), 1.5);
        check("A: single r->l W.src", get(&raw, "W", "source_start"), 0.0);
        // B) 2ドラッグ: 縮小0.5+settle → 新規ドラッグで左0.8
        let mut raw = mk();
        let mut last_t = 2.0;
        let mut mouse = 2.0;
        for _ in 0..5 { mouse += 0.1; last_t += edits::trim_clip_live_from(&mut raw, &ids, true, last_t, mouse, &[]); }
        edits::settle_overlaps(&mut raw, &ids);
        println!("TRIMSEQ B mid: W {}-{} src {}", get(&raw,"W","timeline_start"), get(&raw,"W","timeline_end"), get(&raw,"W","source_start"));
        let mut last_t = 2.0; // 新規ドラッグ: エッジ(2.0)から
        let mut mouse = 2.0;
        for _ in 0..8 { mouse -= 0.1; last_t += edits::trim_clip_live_from(&mut raw, &ids, true, last_t, mouse, &[]); }
        edits::settle_overlaps(&mut raw, &ids);
        // 縮小で頭0.5sを捨てた後の再拡大: 余白0.5sぶん左へ戻れる
        check("B: 2nd drag W.ts", get(&raw, "W", "timeline_start"), 1.5);
        check("B: 2nd drag W.src", get(&raw, "W", "source_start"), 0.0);
        check("B: V tail eaten", get(&raw, "V", "timeline_end"), 1.5);
        // C) 非メインレーン(オーバーレイ)のクリップ: 縮小0.5 → 新規ドラッグで左0.8
        let mkc = || -> serde_json::Value {
            serde_json::json!([{ "timeline": { "sequence": { "duration": 10.0, "frame_rate": 30, "tracks": [
                { "id": "v0", "type": "video", "clips": [
                    { "id": "base", "asset_id": "vid", "track": "video",
                      "source_start": 0.0, "source_end": 8.0, "timeline_start": 0.0, "timeline_end": 8.0 }]},
                { "id": "ov", "type": "video", "clips": [
                    { "id": "P", "asset_id": "vid", "track": "video",
                      "source_start": 0.0, "source_end": 2.0, "timeline_start": 2.0, "timeline_end": 4.0 }]},
                { "id": "a0", "type": "audio", "clips": [] }
            ]}}}])
        };
        let idsp = vec!["P".to_string()];
        let mut raw = mkc();
        let mut last_t = 2.0;
        let mut mouse = 2.0;
        for _ in 0..5 { mouse += 0.1; last_t += edits::trim_clip_live_from(&mut raw, &idsp, true, last_t, mouse, &[]); }
        edits::settle_overlaps(&mut raw, &idsp);
        println!("TRIMSEQ C mid: P {}-{} src {}", get(&raw,"P","timeline_start"), get(&raw,"P","timeline_end"), get(&raw,"P","source_start"));
        check("C: shrink advanced src", get(&raw, "P", "source_start"), 0.5);
        let mut last_t = get(&raw, "P", "timeline_start");
        let mut mouse = last_t;
        for _ in 0..8 { mouse -= 0.1; last_t += edits::trim_clip_live_from(&mut raw, &idsp, true, last_t, mouse, &[]); }
        edits::settle_overlaps(&mut raw, &idsp);
        check("C: 2nd drag P.ts", get(&raw, "P", "timeline_start"), 2.0);
        check("C: 2nd drag P.src", get(&raw, "P", "source_start"), 0.0);
        println!("TRIMSEQ ALL {}", if ok { "PASS" } else { "FAIL" });
        std::process::exit(if ok { 0 } else { 1 });
    }
    if args.iter().any(|a| a == "--selftest-speed") {
        // クリップ速度写像の数値検証: 等速・ランプ積分・単調性・カーブ幅
        let mut ok = true;
        let mut check = |name: &str, got: f64, want: f64, tol: f64| {
            let pass = (got - want).abs() <= tol;
            println!(
                "SPD {name:<24} {} got={got:.4} want={want:.4}",
                if pass { "PASS" } else { "FAIL" }
            );
            if !pass {
                ok = false;
            }
            pass
        };
        let c: model::Clip = serde_json::from_value(serde_json::json!({
            "id": "s1", "asset_id": "a", "source_start": 10.0, "source_end": 18.0,
            "timeline_start": 5.0, "timeline_end": 9.0, "speed": 2.0
        }))
        .expect("clip");
        check("const2x t=7 -> src14", c.src_at(7.0), 14.0, 1e-9);
        check("const2x rate", c.rate_at(6.0), 2.0, 1e-9);
        check("const2x inverse", c.t_at_src(14.0), 7.0, 1e-9);
        let mut r: model::Clip = serde_json::from_value(serde_json::json!({
            "id": "s2", "asset_id": "a", "source_start": 0.0, "source_end": 10.0,
            "timeline_start": 0.0, "timeline_end": 7.0,
            "speed_keys": [{"u": 0.0, "v": 1.0}, {"u": 4.0, "v": 2.0, "ease": 0.0}]
        }))
        .expect("ramp clip");
        r.ramp = model::build_ramp(&r.speed_keys, 0.0, 10.0).map(std::sync::Arc::new);
        let total = r.ramp.as_ref().map(|l| l.total_t).unwrap_or(0.0);
        check("ramp total 1x4s+2x3s", total, 7.0, 0.03);
        check("ramp t=2 -> src2", r.src_at(2.0), 2.0, 0.03);
        check("ramp t=6 -> src8", r.src_at(6.0), 8.0, 0.06);
        check("ramp rate head 1x", r.rate_at(1.0), 1.0, 0.05);
        check("ramp rate tail 2x", r.rate_at(6.0), 2.0, 0.1);
        check("ramp inverse src8->t6", r.t_at_src(8.0), 6.0, 0.05);
        check("roundtrip t=3.3", r.t_at_src(r.src_at(3.3)), 3.3, 0.02);
        let mut sm: model::Clip = serde_json::from_value(serde_json::json!({
            "id": "s3", "asset_id": "a", "source_start": 0.0, "source_end": 10.0,
            "timeline_start": 0.0, "timeline_end": 7.0,
            "speed_keys": [{"u": 0.0, "v": 1.0}, {"u": 5.0, "v": 2.0, "ease": 1.0}]
        }))
        .expect("smooth clip");
        sm.ramp = model::build_ramp(&sm.speed_keys, 0.0, 10.0).map(std::sync::Arc::new);
        let tt = sm.ramp.as_ref().map(|l| l.total_t).unwrap_or(0.0);
        let in_range = tt > 6.5 && tt < 8.0;
        println!("SPD ease1 total in range   {} got={tt:.3}", if in_range { "PASS" } else { "FAIL" });
        ok &= in_range;
        let mut mono = true;
        let mut prevv = -1.0;
        for i in 0..=720 {
            let s = sm.src_at(i as f64 * 0.01);
            if s < prevv - 1e-9 {
                mono = false;
            }
            prevv = s;
        }
        println!("SPD ramp monotonic         {}", if mono { "PASS" } else { "FAIL" });
        ok &= mono;
        // カーブ度合い: ease=1 は ease=0 より遷移が広い（t=3.5 時点の速度で判定）
        let v_sharp = r.rate_at(3.2);
        let v_smooth = sm.rate_at(3.2);
        let spread = v_smooth > v_sharp + 0.05;
        println!(
            "SPD ease widens transition {} sharp={v_sharp:.3} smooth={v_smooth:.3}",
            if spread { "PASS" } else { "FAIL" }
        );
        ok &= spread;
        println!("SPD ALL {}", if ok { "PASS" } else { "FAIL" });
        std::process::exit(if ok { 0 } else { 1 });
    }
    if args.iter().any(|a| a == "--selftest-newlane") {
        let contents = positional_args(&args).first().cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = positional_args(&args).get(1).cloned().unwrap_or_else(|| ROOM.to_string());
        let mut app = App::new(&contents, &dir).expect("app");
        // normalize first: a pre-existing empty unnamed lane in the room would be swept
        // by the dissolve-side prune and skew the track-count assertions
        app.apply_edit(false, |raw| edits::prune_empty_unnamed_tracks(raw));
        let n0 = app.doc.seq.tracks.len();
        // front-most non-audio lane with >= 2 clips exercises the old blanket early-return
        let (src_ti, cid) = app
            .doc
            .seq
            .tracks
            .iter()
            .enumerate()
            .rev()
            .filter(|(_, tr)| tr.kind != "audio" && tr.clips.len() >= 2)
            .flat_map(|(ti, tr)| tr.clips.iter().map(move |c| (ti, c.id.clone())))
            .next()
            .expect("no multi-clip visual lane");
        let ids = vec![cid.clone()];
        let ids2 = ids.clone();
        app.apply_edit(true, move |raw| edits::move_to_new_top_track(raw, &ids2));
        let n1 = app.doc.seq.tracks.len();
        let front = app.doc.seq.tracks.iter().rposition(|tr| tr.kind != "audio").unwrap();
        let on_front = app.doc.seq.tracks[front].clips.iter().any(|c| c.id == cid);
        let alone = app.doc.seq.tracks[front].clips.len() == 1;
        println!("NEWLANE create {} (tracks {n0}->{n1}, on_front={on_front}, alone={alone})",
                 if n1 == n0 + 1 && on_front && alone { "PASS" } else { "FAIL" });
        let ids3 = ids.clone();
        app.apply_edit(false, move |raw| edits::move_to_new_top_track(raw, &ids3));
        let n2 = app.doc.seq.tracks.len();
        println!("NEWLANE idempotent {} (tracks {n2})", if n2 == n1 { "PASS" } else { "FAIL" });
        let ids4 = ids.clone();
        app.apply_edit(false, move |raw| edits::move_to_track(raw, &ids4, src_ti));
        let n3 = app.doc.seq.tracks.len();
        let back = app.doc.seq.tracks[src_ti].clips.iter().any(|c| c.id == cid);
        println!("NEWLANE dissolve {} (tracks {n3}, back_on_src={back})",
                 if n3 == n0 && back { "PASS" } else { "FAIL" });
        std::process::exit(0);
    }
    // --selftest-backseek <path>: prefetch forward then request an EARLIER frame — the
    // decoder must land back-near it, not hold the future frame (the ◱ preview-jump bug)
    if let Some(i) = args.iter().position(|a| a == "--selftest-backseek") {
        let path = args.get(i + 1).cloned().unwrap_or_default();
        let d3d = media::D3d::new().expect("d3d");
        let mut vs = media::VideoStream::open(&d3d, &path, 0, false).expect("open");
        vs.ensure_frame(&d3d, 464.436).expect("seed");
        let seeded = vs.shown_pts();
        // simulate the prefetch walk that advanced the decoder ~0.35s ahead
        let mut t = 464.436;
        while t < 464.80 {
            t += 0.0333;
            let _ = vs.ensure_frame(&d3d, t);
        }
        let advanced = vs.shown_pts();
        vs.ensure_frame(&d3d, 464.436).expect("backseek");
        let landed = vs.shown_pts();
        let ok = (landed - 464.436).abs() < 0.05;
        println!(
            "BACKSEEK {} seeded={seeded:.3} advanced={advanced:.3} re-request=464.436 landed={landed:.3}",
            if ok { "PASS" } else { "FAIL" }
        );
        std::process::exit(if ok { 0 } else { 1 });
    }
    // --selftest-freeze-resume <path> <source-in> [resume-duration]: model the
    // decoder hand-off at a static freeze. The still itself does not touch the
    // decoder; the continuation must nevertheless advance from the held source PTS.
    if let Some(i) = args.iter().position(|a| a == "--selftest-freeze-resume") {
        let path = args.get(i + 1).cloned().unwrap_or_default();
        let source_in: f64 = args.get(i + 2).and_then(|v| v.parse().ok()).unwrap_or(0.0);
        let duration: f64 = args.get(i + 3).and_then(|v| v.parse().ok()).unwrap_or(1.0);
        let end = source_in + duration.max(0.1);
        let d3d = media::D3d::new().expect("d3d");
        let mut vs = media::VideoStream::open(&d3d, &path, 0, false).expect("open");
        vs.ensure_frame(&d3d, source_in).expect("freeze in-point");
        let held = vs.shown_pts();
        // The freeze PNG is displayed here; deliberately make no decoder calls.
        let mut t = source_in;
        while t <= end {
            vs.ensure_frame(&d3d, t).expect("freeze continuation");
            t += 1.0 / 30.0;
        }
        let landed = vs.shown_pts();
        let ok = landed >= end - 0.10 && landed >= held - 0.001;
        println!(
            "FREEZE_RESUME {} held={held:.3} requested_end={end:.3} landed={landed:.3}",
            if ok { "PASS" } else { "FAIL" }
        );
        std::process::exit(if ok { 0 } else { 1 });
    }
    // --probe-open <path> <stream> [full_range]: open one decoder standalone and report
    if let Some(i) = args.iter().position(|a| a == "--probe-open") {
        let path = args.get(i + 1).cloned().unwrap_or_default();
        let stream: u32 = args.get(i + 2).and_then(|v| v.parse().ok()).unwrap_or(0);
        let fr = args.get(i + 3).map(|v| v == "1").unwrap_or(true);
        match media::D3d::new() {
            Ok(d3d) => match media::VideoStream::open(&d3d, &path, stream, fr) {
                Ok(mut vs) => {
                    let r = vs.ensure_frame(&d3d, 1.0);
                    let t0 = std::time::Instant::now();
                    let mut n = 0;
                    for i in 1..=60 {
                        if vs.ensure_frame(&d3d, 1.0 + i as f64 / 30.0).is_ok() {
                            n += 1;
                        }
                    }
                    let ms = t0.elapsed().as_secs_f64() * 1000.0;
                    println!(
                        "OK {}x{} ensure={:?} seq60={:.0}ms ({:.1}ms/frame, n={n})",
                        vs.width, vs.height, r.map(|_| ()), ms, ms / 60.0
                    );
                }
                Err(e) => println!("ERR {e:#}"),
            },
            Err(e) => println!("D3D ERR {e:#}"),
        }
        std::process::exit(0);
    }
    // done://production?room_id=X&token=Y — the chat 制作タブ deep link. Room resolves to
    // its uploads dir; a fresh token is persisted so later bare launches stay signed in.
    let mut deep_room: Option<String> = None;
    if let Some(url) = args.iter().find(|a| a.starts_with("done://")) {
        if let Some(q) = url.split('?').nth(1) {
            for kv in q.split('&') {
                let mut it = kv.splitn(2, '=');
                match (it.next(), it.next()) {
                    (Some("room_id"), Some(v)) if !v.is_empty() => deep_room = Some(v.to_string()),
                    (Some("token"), Some(v)) if !v.is_empty() => {
                        // already applied by load_api_token (deep token wins); persist for
                        // later bare launches
                        let p = format!(
                            "{}/.done",
                            std::env::var("USERPROFILE").unwrap_or_default().replace(char::from(92), "/")
                        );
                        let _ = std::fs::create_dir_all(&p);
                        let _ = std::fs::write(format!("{p}/native_token.txt"), v);
                    }
                    _ => {}
                }
            }
        }
    }
    let room_dir = deep_room
        .as_ref()
        .map(|r| format!("D:/done/uploads/production-assets/{r}"))
        .unwrap_or_else(|| ROOM.to_string());
    let positional = positional_args(&args);
    let contents = positional
        .first()
        .cloned()
        .unwrap_or_else(|| format!("{room_dir}/contents.json"));
    let dir = positional.get(1).cloned().unwrap_or(room_dir);
    // First open of a room (a chat room that never produced anything yet) has no
    // uploads dir at all. Seed an empty contents.json so the app opens into the
    // room's empty library instead of dying in App::new before any window exists.
    // Explicit positional contents paths are exempt: a typo there should fail, not
    // silently create a bogus document.
    if positional.is_empty() && !std::path::Path::new(&contents).exists() {
        let _ = std::fs::create_dir_all(&dir);
        let _ = std::fs::write(&contents, "[]");
    }
    let opts = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1280.0, 940.0])
            // Build tag in the title: the ONE glanceable answer to 「その修正、
            // 今動いてるアプリに入ってる？」(git hash, + = uncommitted, build time)
            .with_title(format!("done Studio  [{}]", env!("NATIVE_BUILD_TAG"))),
        ..Default::default()
    };
    eframe::run_native(
        "done-native",
        opts,
        Box::new(move |cc| {
            // Japanese glyphs: egui's built-in font has none — pull a system font in
            let mut fonts = egui::FontDefinitions::default();
            for cand in ["C:/Windows/Fonts/meiryo.ttc", "C:/Windows/Fonts/YuGothM.ttc", "C:/Windows/Fonts/msgothic.ttc"] {
                if let Ok(bytes) = std::fs::read(cand) {
                    fonts
                        .font_data
                        .insert("jp".into(), egui::FontData::from_owned(bytes));
                    for fam in [egui::FontFamily::Proportional, egui::FontFamily::Monospace] {
                        fonts.families.get_mut(&fam).unwrap().push("jp".into());
                    }
                    break;
                }
            }
            cc.egui_ctx.set_fonts(fonts);
            // pro-NLE dark theme: flat near-black panels, rounded widgets, teal accent.
            // Pin dark FIRST — egui 0.29 follows the OS (light) theme per frame otherwise
            // and silently discards set_visuals.
            cc.egui_ctx.set_theme(egui::Theme::Dark);
            let mut vis = egui::Visuals::dark();
            vis.panel_fill = UI_PANEL;
            vis.window_fill = egui::Color32::from_rgb(30, 30, 34);
            vis.extreme_bg_color = egui::Color32::from_rgb(14, 14, 16);
            vis.faint_bg_color = egui::Color32::from_rgb(32, 32, 36);
            vis.widgets.noninteractive.bg_fill = UI_PANEL;
            vis.widgets.inactive.bg_fill = egui::Color32::from_rgb(40, 40, 45);
            vis.widgets.inactive.weak_bg_fill = egui::Color32::from_rgb(40, 40, 45);
            vis.widgets.hovered.bg_fill = egui::Color32::from_rgb(56, 56, 62);
            vis.widgets.hovered.weak_bg_fill = egui::Color32::from_rgb(56, 56, 62);
            vis.widgets.active.bg_fill = egui::Color32::from_rgb(57, 72, 102);
            vis.widgets.active.weak_bg_fill = egui::Color32::from_rgb(57, 72, 102);
            vis.selection.bg_fill = egui::Color32::from_rgb(57, 72, 102);
            vis.selection.stroke = egui::Stroke::new(1.0, UI_ACCENT);
            for w in [
                &mut vis.widgets.noninteractive,
                &mut vis.widgets.inactive,
                &mut vis.widgets.hovered,
                &mut vis.widgets.active,
                &mut vis.widgets.open,
            ] {
                w.rounding = egui::Rounding::same(6.0);
            }
            cc.egui_ctx.set_visuals(vis);
            cc.egui_ctx.style_mut(|st| {
                st.spacing.button_padding = egui::vec2(12.0, 8.0);
                st.spacing.item_spacing = egui::vec2(8.0, 8.0);
            });
            let mut app = App::new(&contents, &dir)
                .map_err(|e| -> Box<dyn std::error::Error + Send + Sync> { format!("{e:#}").into() })?;
            // bare launch (no explicit contents arg): open the LIBRARY (assets ->
            // generation -> open), the full production entry point
            let all: Vec<String> = std::env::args().collect();
            let explicit = !positional_args(&all).is_empty();
            if std::env::var("DONE_EDITOR_VOICE").as_deref()==Ok("1") { app.assistant.open=true; app.assistant.immersive=true; }
            if !explicit || all.iter().any(|a| a=="--library") {
                app.screen = Screen::Library;
                app.lib_refresh();
            }
            // --import <file>: same first-import setup as drag&drop (also our self-test hook)
            let args: Vec<String> = std::env::args().collect();
            if let Some(i) = args.iter().position(|a| a == "--import") {
                if let Some(f) = args.get(i + 1) {
                    let path = std::path::PathBuf::from(f);
                    if !app.has_timeline_media() && app.doc.seq.frame_rate.is_none() {
                        app.pending_initial_fps = probe_frame_rate(&path.to_string_lossy()).into_iter().collect();
                        app.pending_initial_imports.push(path);
                    } else if let Err(e) = app.import_file(&path) {
                        eprintln!("import: {e:#}");
                    }
                }
            }
            // --seek <t>: open with the playhead at t (targeted repro runs)
            if let Some(i) = args.iter().position(|a| a == "--seek") {
                if let Some(t) = args.get(i + 1).and_then(|v| v.parse::<f64>().ok()) {
                    app.t = t.min(app.dur);
                    app.push_req(false);
                }
            }
            // --selftest: drive the ENGINE directly (no OS input — immune to a human
            // moving the real mouse): play -> fwd jump -> back jump -> 30Hz scrub -> stop
            // --play-probe <t>: start playback at t after warmup and run ~12s — headless
            // boundary/dup debugging with full engine logs, no synthetic input needed
            if let Some(i) = args.iter().position(|a| a == "--play-probe") {
                let t0: f64 = args.get(i + 1).and_then(|v| v.parse().ok()).unwrap_or(0.0);
                let delay: u64 = std::env::var("NATIVE_PROBE_DELAY")
                    .ok()
                    .and_then(|v| v.parse().ok())
                    .unwrap_or(4000);
                // NATIVE_PLAY_SPEED: probe fast playback (the L key path) headlessly
                let speed: f64 = std::env::var("NATIVE_PLAY_SPEED")
                    .ok()
                    .and_then(|v| v.parse().ok())
                    .unwrap_or(1.0);
                let sh = app.shared.clone();
                std::thread::spawn(move || {
                    std::thread::sleep(std::time::Duration::from_millis(delay));
                    eprintln!("PLAYPROBE start t={t0} speed={speed}");
                    {
                        let mut r = sh.req.lock().unwrap();
                        r.t = t0;
                        r.playing = true;
                        r.scrubbing = false;
                        r.speed = speed;
                        r.gen += 1;
                    }
                    std::thread::sleep(std::time::Duration::from_millis(12000));
                    eprintln!("PLAYPROBE end clock={:.3}", f64::from_bits(sh.clock_bits.load(Ordering::Relaxed)));
                    std::process::exit(0);
                });
            }
            if args.iter().any(|a| a == "--selftest") {
                let sh = app.shared.clone();
                std::thread::spawn(move || {
                    let bump = |t: f64, playing: bool, scrubbing: bool| {
                        let mut r = sh.req.lock().unwrap();
                        r.t = t;
                        r.playing = playing;
                        r.scrubbing = scrubbing;
                        r.gen += 1;
                    };
                    let s = |ms: u64| std::thread::sleep(std::time::Duration::from_millis(ms));
                    s(4000);
                    eprintln!("SELFTEST play@5");
                    bump(5.0, true, false);
                    s(8000);
                    eprintln!("SELFTEST fwd-jump@90");
                    bump(90.0, true, false);
                    s(8000);
                    eprintln!("SELFTEST back-jump@30");
                    bump(30.0, true, false);
                    s(8000);
                    eprintln!("SELFTEST pause+scrub");
                    bump(38.0, false, false);
                    s(600);
                    // 30Hz drag: 40 -> 80 -> 60, then rest (refine-to-exact)
                    let mut t = 40.0f64;
                    for leg in [(80.0f64, 120u64), (60.0f64, 60u64)] {
                        let step = (leg.0 - t) / leg.1 as f64;
                        for _ in 0..leg.1 {
                            t += step;
                            bump(t, false, true);
                            s(33);
                        }
                    }
                    s(1200);
                    bump(60.0, false, false);
                    // let the background frame cache fill around t=60, then re-scrub the
                    // same span: cached scrub should be ~5ms/frame at ORIGINAL quality
                    s(20000);
                    eprintln!("SELFTEST cached-scrub");
                    let mut t = 55.0f64;
                    for _ in 0..120 {
                        t += 0.083;
                        bump(t, false, true);
                        s(33);
                    }
                    s(600);
                    bump(60.0, false, false);
                    eprintln!("SELFTEST done");
                });
            }
            Ok(Box::new(app))
        }),
    )
}
