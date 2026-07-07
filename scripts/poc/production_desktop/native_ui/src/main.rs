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
mod edits;
mod media;
mod model;

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use eframe::egui;

const ROOM: &str = "D:/done/uploads/production-assets/bd05fcc0-c143-4d1c-828e-7624e087b6c1";
// design tokens (Filmora-reference dark theme: near-black stage, teal accent, pink playhead)
const UI_ACCENT: egui::Color32 = egui::Color32::from_rgb(0, 190, 150);
const UI_PLAYHEAD: egui::Color32 = egui::Color32::from_rgb(255, 74, 85);
const UI_PANEL: egui::Color32 = egui::Color32::from_rgb(24, 24, 27);
const UI_STAGE: egui::Color32 = egui::Color32::from_rgb(12, 12, 14);

const CANVAS_W: u32 = 1080;
const CANVAS_H: u32 = 1920;

#[derive(Clone)]
struct Req {
    t: f64,
    playing: bool,
    scrubbing: bool,
    speed: f64,
    gen: u64,
}

struct FrameOut {
    rgba: Vec<u8>,
    seq: u64,
    comp_ms: f32,
    comp_max: f32,  // worst compose over the last second
    gap_max: f32,   // worst wall-clock gap between published frames (what the eye sees)
    quality: &'static str,
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
    req: Mutex<Req>,
    frame: Mutex<FrameOut>,
    clock_bits: AtomicU64,
    underruns: AtomicU64,
    ring_level: std::sync::atomic::AtomicUsize,
    ring: Mutex<std::collections::VecDeque<(f64, Vec<u8>)>>,
    ring_gen: AtomicU64,
    // timeline position the ring is being built FOR (f64 bits). On a mid-play seek this
    // moves to the new playhead BEFORE the clock does — audio waits on it (JUMPGATE) and
    // the presenter goes hands-off so it can't eat the rebuilt ring as "stale".
    ring_target_bits: AtomicU64,
    doc: Mutex<Arc<model::Doc>>,
    aux_req: Mutex<Vec<AuxJob>>,
    aux: Mutex<AuxOut>,
}

/// Audio on its own thread: the WASAPI buffer is refilled no matter what the video side is
/// doing, so an expensive video seek can never make sound stutter again. Also owns the
/// master clock and restarts the stream when the playhead jumps (scrub while playing).
fn audio_thread(shared: Arc<Shared>) {
    let Ok(mut audio) = media::AudioOut::new() else { return };
    let mut was_playing = false;
    let mut last_gen = u64::MAX;
    let mut last_tick = Instant::now();
    let mut last_speed = 1.0f64;
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
                    if ((rt - t_req).abs() < 0.5 && lvl >= 4) || t0.elapsed().as_millis() > 900 {
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
                    if ((rt - t_req).abs() < 0.5 && lvl >= 4) || t0.elapsed().as_millis() > 600 {
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
            let _ = audio.fill(&doc, speed);
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

#[derive(Clone, PartialEq)]
enum Drag {
    None,
    Scrub,
    Move { ids: Vec<String>, grab: f64, orig: f64, applied: f64 },
    Trim { ids: Vec<String>, left: bool, last_t: f64 },
    Marquee { anchor: egui::Pos2 },
    Volume { ids: Vec<String>, start_y: f32, start_vol: f64 },
}

/// Olive-style composed-frame cache: finished timeline frames (ORIGINAL quality, 30fps
/// grid) LZ4-compressed in RAM. Scrub/jump/playback over cached spans just decompress
/// (~3-6ms) instead of composing (30-100ms+). Conservative correctness: ANY document edit
/// clears the whole cache — a stale frame is structurally impossible. Filled during
/// paused idle (playhead outward) and opportunistically from playback production.
struct FrameCache {
    // key: 1/30 bucket; value: (EXACT compose time, lz4 pixels). The exact time is the
    // honesty check: a bucket spans 33ms — up to two different source frames — and
    // serving "whatever the bucket holds" showed the NEIGHBOUR frame when a paused
    // inspection landed 12ms away from the cached compose (the freeze-boundary bug the
    // dump-frame verification missed because it bypasses this cache).
    frames: std::collections::HashMap<i64, (f64, Vec<u8>)>,
    bytes: usize,
    budget: usize,
    hits: u64,
    misses: u64,
}

impl FrameCache {
    fn new() -> Self {
        Self {
            frames: Default::default(),
            bytes: 0,
            budget: 2_500_000_000, // ~2.5GB ≈ 30-40s of 1080x1920 frames
            hits: 0,
            misses: 0,
        }
    }
    fn idx(t: f64) -> i64 {
        (t * 30.0).round() as i64
    }
    fn clear(&mut self) {
        self.frames.clear();
        self.bytes = 0;
    }
    /// Drop only frames at/after `t` — an edit at 60s must not throw away the first
    /// minute of finished frames (the whole-cache clear was the post-edit heaviness).
    fn invalidate_from(&mut self, t: f64) {
        let cut = Self::idx(t) - 1;
        let dead: Vec<i64> = self.frames.keys().copied().filter(|k| *k >= cut).collect();
        for k in dead {
            if let Some((_, z)) = self.frames.remove(&k) {
                self.bytes -= z.len();
            }
        }
    }
    /// Serve only when the cached pixels were composed within `tol` seconds of `t`.
    /// Playback reuse passes a whole tick (~17ms); paused/scrub inspection passes 5ms
    /// so a neighbouring source frame can never impersonate the requested one.
    fn get(&mut self, t: f64, tol: f64, out: &mut Vec<u8>) -> bool {
        if let Some((ct, z)) = self.frames.get(&Self::idx(t)) {
            if (ct - t).abs() <= tol {
                if let Ok(raw) = lz4_flex::decompress_size_prepended(z) {
                    out.clear();
                    out.extend_from_slice(&raw);
                    self.hits += 1;
                    return true;
                }
            }
        }
        self.misses += 1;
        false
    }
    fn contains(&self, t: f64) -> bool {
        self.frames.contains_key(&Self::idx(t))
    }
    fn insert(&mut self, t: f64, rgba: &[u8], playhead: f64) {
        let key = Self::idx(t);
        if self.frames.contains_key(&key) {
            return;
        }
        let z = lz4_flex::compress_prepend_size(rgba);
        self.bytes += z.len();
        self.frames.insert(key, (t, z));
        // over budget: evict farthest-from-playhead first
        while self.bytes > self.budget {
            let ph = Self::idx(playhead);
            let Some((&far, _)) = self.frames.iter().max_by_key(|(k, _)| (**k - ph).abs()) else {
                break;
            };
            if let Some((_, z)) = self.frames.remove(&far) {
                self.bytes -= z.len();
            }
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
fn mask_build_pass(doc: &model::Doc, d3d: &media::D3d, masks: &mut MaskMap) -> bool {
    for tr in &doc.seq.tracks {
        if tr.kind == "audio" {
            continue;
        }
        for c in &tr.clips {
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
        comp.draw_cropped(d3d, &tex, wh, (bb.x, bb.y, bb.width, bb.height), true, None, c.crop_ltrb())?;
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
    comp.draw_cropped(d3d, &tex, wh, (bb.x, bb.y, bb.width, bb.height), true, None, c.crop_ltrb())?;
    Ok(Some(p2))
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
    let src_edge = c.source_start + (edge.clamp(c.timeline_start, c.timeline_end) - c.timeline_start);
    let k = edge_frame(&pts, src_edge, dir);
    let nt = c.timeline_start + (frame_mid(&pts, k)? - c.source_start);
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
    let src = c.source_start + (t - c.timeline_start);
    let k2 = nearest_idx(&pts, src) as i64 + dir as i64;
    if k2 < 0 {
        return step_enter(doc, cache, c.timeline_start, -1.0);
    }
    let nt = c.timeline_start + (frame_mid(&pts, k2 as usize)? - c.source_start);
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
    exact_rb: bool, // interactive one-shot: synchronous readback (THIS frame's pixels)
) -> anyhow::Result<(Vec<String>, bool)> {
    pool.frame_no += 1;
    let mut used = Vec::new();
    let mut exact = true; // false while any budgeted scrub seek stopped short of t
    let layers: Vec<model::Clip> = {
        let (b, o) = doc.active_video(t);
        b.into_iter().chain(o).cloned().collect()
    };
    let _t_begin = Instant::now();
    comp.begin(d3d);
    let _ms_base = 0f64;
    let mut _ms_ov = 0f64;
    // scrub deadline: the FULLSCREEN base updates every tick (that's what the eye tracks
    // while whipping); decorations (pop-out person / mattes) update only while the tick
    // budget lasts and land exactly at rest via the refine loop — original pixels always,
    // never a proxy
    let f_deadline = Instant::now() + std::time::Duration::from_millis(30);
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
    for c in &layers {
        let b = c.display_box();
        if let Some((key, off)) = c.popout_key() {
            // LIVE matte path: color sampled from the ORIGINAL frame — the same file and
            // the same src_t the AUDIO plays, so lips can't drift. The baked pv (30fps
            // re-encode, ~17ms staler) remains the fallback while no matte twin exists.
            let live = masks.get(&key).and_then(|o| o.clone());
            if let (Some((meta, mask)), Some(aid)) = (live, c.asset_id.as_deref()) {
                let opath = doc.asset_path_q(aid, original);
                let src_t = c.src_at(t);
                let mt_path = doc.rel_path(&format!("popout-cache/{key}.mt.mp4"));
                let mt_t = if c.is_freeze() { off } else { off + (t - c.timeline_start) };
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
                comp.draw_popout_live(d3d, &otex, &ptex, &stex, &mask, (b.x, b.y, b.width, b.height), aff)?;
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
                let src_t = if c.is_freeze() { off } else { off + (t - c.timeline_start) };
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
                comp.draw(d3d, &ctex, cwh, (b.x, b.y, b.width, b.height), false, Some(&mtex))?;
                used.push(path.clone());
                Ok(())
            })(pool, comp, &mut used);
            if let Err(e) = pv_draw {
                eprintln!("pv fallback {key}: {e:#}");
                if let Some(p2) = draw_plain_pip(doc, d3d, pool, comp, c, b, t, original, fast)? {
                    used.push(p2);
                }
            }
        } else if let Some(aid) = c.asset_id.as_deref() {
            let path = doc.asset_path_q(aid, original);
            let mut src_t = c.src_at(t);
            if !fast && original {
                src_t = snap_src_t(pts_maps, aid, src_t);
            }
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
                let b = c.display_box();
                if near_fz {
                    eprintln!(
                        "FZ_SEAM t={t:.3} clip={} q={} tex={}x{} box={:.4},{:.4},{:.4},{:.4}",
                        c.id,
                        if got_was_still { "png" } else if original { "orig-dec" } else { "proxy-dec" },
                        wh.0, wh.1, b.x, b.y, b.width, b.height
                    );
                }
                comp.draw_cropped(d3d, &tex, wh, (b.x, b.y, b.width, b.height), true, None, c.crop_ltrb())?;
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
            let (tex, wh) = (vs.bgra.clone(), (vs.width, vs.height));
            if near_fz {
                eprintln!(
                    "FZ_SEAM t={t:.3} clip={} q={} tex={}x{} box={:.4},{:.4},{:.4},{:.4}",
                    c.id,
                    if original { "orig-dec" } else { "proxy-dec" },
                    wh.0, wh.1, b.x, b.y, b.width, b.height
                );
            }
            comp.draw_cropped(d3d, &tex, wh, (b.x, b.y, b.width, b.height), true, None, c.crop_ltrb())?;
            used.push(path);
        }
    }
    // region effects (blur/mosaic clips on effect lanes): live mosaic stand-in — the
    // export runs the real gaussian/mosaic chain over the same regions
    for tr in doc.seq.tracks.iter().filter(|tr| tr.kind == "effect" && !tr.hidden) {
        for c in &tr.clips {
            if t < c.timeline_start || t >= c.timeline_end {
                continue;
            }
            if let Some(rg) = c.region_xywh() {
                let style = c.style.as_ref().and_then(|v| v.as_str()).unwrap_or("");
                let cell = if style.contains("mosaic") { 14.0 } else { 9.0 };
                let _ = comp.apply_mosaic(d3d, rg, cell);
            }
        }
    }
    _ms_ov = _t.elapsed().as_secs_f64() * 1000.0;
    let _t = Instant::now();
    if exact_rb {
        comp.readback_sync(d3d)?;
    } else {
        comp.readback(d3d)?;
    }
    let _ms_rb = _t.elapsed().as_secs_f64() * 1000.0;
    let total = _t_begin.elapsed().as_secs_f64() * 1000.0;
    if total > 40.0 {
        eprintln!("slow compose t={t:.2}: base={_ms_base:.0} ov={_ms_ov:.0} rb={_ms_rb:.0} total={total:.0}");
    }
    Ok((used, exact))
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
static API_TOKEN: std::sync::OnceLock<Option<String>> = std::sync::OnceLock::new();

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
    let _ = API_TOKEN.set(tok);
}

fn http_local(method: &str, path: &str, json_body: Option<&str>) -> anyhow::Result<String> {
    use std::io::{Read, Write};
    let mut st = std::net::TcpStream::connect(("127.0.0.1", 8000))?;
    st.set_read_timeout(Some(std::time::Duration::from_secs(20)))?;
    let body = json_body.unwrap_or("");
    let auth = API_TOKEN
        .get()
        .and_then(|t| t.as_ref())
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
) -> bool {
    const INSTANCE_CAP: usize = 40;
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
        let mut grabbed: Option<(f64, Vec<u8>)> = None;
        {
            let mut ring = shared.ring.lock().unwrap();
            while ring.front().map(|(ft, _)| *ft < t - 1.0 / 30.0).unwrap_or(false) {
                ring.pop_front();
            }
            if let Some((ft, _)) = ring.iter().rev().find(|(ft, _)| *ft <= t) {
                let ft = *ft;
                if ft > published_t {
                    if let Some((_, rgba)) = ring.iter().find(|(x, _)| *x == ft) {
                        grabbed = Some((ft, rgba.clone()));
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
                        (rg.front().map(|(f2, _)| *f2), rg.back().map(|(b2, _)| *b2), rg.len())
                    };
                    eprintln!("PRES-IDLE {idle:.0}ms t={t:.2} pub={published_t:.2} ring={ln} front={fr:?} back={ba:?}");
                }
            }
        }
        if let Some((ft, rgba)) = grabbed {
            let now = Instant::now();
            seq_hi += 1;
            let mut f = shared.frame.lock().unwrap();
            f.rgba = rgba;
            f.seq = seq_hi;
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

fn media_thread(shared: Arc<Shared>) {
    let run = || -> anyhow::Result<()> {
        let d3d = media::D3d::new()?;
        let mut pool = media::VideoPool::new();
        let mut comp = compositor::Compositor::new(&d3d, CANVAS_W, CANVAS_H)?;
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
        let mut settle = Instant::now(); // last user interaction (scrub/edit/seek)
        let mut edit_cooldown_until = Instant::now();
        let mut scrub_win: Vec<f32> = Vec::new();
        let mut scrub_t0 = Instant::now();
        let mut scrub_exact = true; // last scrub compose reached the exact frame
        let mut masks: MaskMap = Default::default();
        let mut pts_maps: PtsMap = Default::default();
        let mut fcache = FrameCache::new();
        let mut prev_was_compose = false;
        let mut prev_compose_t = f64::NAN;
        let mut prev_playing = false;
        let mut play_started: Option<Instant> = None;
        // Look-ahead ring: timeline frames composed AHEAD of the playhead on a fixed 30fps
        // grid. Presentation picks from the ring and NEVER waits for a decode — GOP walks
        // and source switches are paid in the ring's future (the Filmora mechanism).
        const STEP: f64 = 1.0 / 30.0;
        const RING_DEPTH: usize = 12; // ~400ms of slack
        // Speculative paused-idle cache fill is too expensive for structural edits:
        // it composes arbitrary surrounding frames even when the user only needs the
        // current preview and a short play-ahead ring. Keep the cache as an
        // opportunistic playback/scrub accelerator, but do not let it compete with
        // interactive work in the background.
        const IDLE_FRAME_CACHE_FILL: bool = false;
        loop {
            let hb0 = Instant::now();
            let doc: Arc<model::Doc> = shared.doc.lock().unwrap().clone();
            let ptr = Arc::as_ptr(&doc) as usize;
            if ptr != last_doc_ptr {
                last_doc_ptr = ptr;
                warm_done = false;
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
                    fcache.invalidate_from(cut);
                } else {
                    eprintln!("CACHE_CLEAR full");
                    fcache.clear(); // unknown provenance (open/undo/redo): full reset
                }
                // the RING holds composed frames too: time-aligned entries survived the
                // doc swap and briefly played PRE-EDIT content after every edit
                {
                    let mut rg = shared.ring.lock().unwrap();
                    let before = rg.len();
                    rg.retain(|(ft, _)| *ft < cut);
                    if rg.len() != before {
                        shared.ring_gen.fetch_add(1, Ordering::Relaxed);
                    }
                    shared.ring_level.store(rg.len(), Ordering::Relaxed);
                }
            }
            let dur = doc.duration();
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
                            .map(|(ft, _)| (*ft - target).abs() < 2.0 / 30.0 || (*ft < target && rg.back().map(|(bt, _)| *bt >= target).unwrap_or(false)))
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
                        if let Ok(_snap) = compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, r.t, false, true, true) {
                            seq += 1;
                            let mut f = shared.frame.lock().unwrap();
                            f.rgba.clear();
                            f.rgba.extend_from_slice(&comp.rgba);
                            f.seq = seq;
                            f.quality = "proxy";
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
                        rg.back().map(|(ft, _)| ft + STEP).unwrap_or_else(|| (t_build / STEP).floor() * STEP),
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
                    let from_cache = fcache.get(next_t, 0.017, &mut cached_buf);
                    let res = if from_cache {
                        Ok((Vec::new(), true))
                    } else {
                        compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, next_t, false, false, false)
                    };
                    ms_comp = t0.elapsed().as_secs_f32() * 1000.0;
                    match res {
                        Ok((used, _)) => {
                            if ms_comp > 60.0 {
                                eprintln!("SLOWPROD t={next_t:.2}: {ms_comp:.0}ms");
                            }
                            let p0 = Instant::now();
                            let frame_ref: &Vec<u8> = if from_cache { &cached_buf } else { &comp.rgba };
                            {
                                let mut rg = shared.ring.lock().unwrap();
                                rg.push_back((next_t, frame_ref.clone()));
                                // never trim against the OLD clock while a jump is pending —
                                // a backward seek's fresh frames all look "stale" to it
                                if jump_to.is_none() {
                                    while rg.front().map(|(ft, _)| *ft < t - 2.0 * STEP).unwrap_or(false) {
                                        rg.pop_front();
                                    }
                                }
                                shared.ring_level.store(rg.len(), Ordering::Relaxed);
                            }
                            if !from_cache && prev_was_compose && len >= 6 && ms_comp < 25.0 {
                                // cheap frames get cached opportunistically (lz4 ~5ms).
                                // ASYNC readback returns the PREVIOUS compose's pixels, so
                                // the content belongs to next_t - STEP — keying it at
                                // next_t poisoned the cache with shifted frames (the
                                // "ちらちら" flicker on jumps into cached spans)
                                // PROVENANCE CHECK: the compensation assumes the previous
                                // compose was exactly one STEP earlier — log when it wasn't
                                // (jump seams would cache WRONG-time pixels)
                                if (prev_compose_t - (next_t - STEP)).abs() > 1e-4 {
                                    eprintln!(
                                        "CACHE_PUT_WRONG key={:.3} pixels_from={prev_compose_t:.3}",
                                        next_t - STEP
                                    );
                                } else if near_freeze(&doc, next_t) {
                                    eprintln!("CACHE_PUT key={:.3} ok", next_t - STEP);
                                }
                                fcache.insert(next_t - STEP, &comp.rgba, t);
                            }
                            prev_was_compose = !from_cache;
                            prev_compose_t = next_t;
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
                shared.ring.lock().unwrap().clear();
                shared.ring_gen.fetch_add(1, Ordering::Relaxed);
            }
            let settled = !r.scrubbing && settle.elapsed().as_secs_f32() > 0.2;
            let dirty = r.gen != last_gen || (t - last_t).abs() > 1e-6;
            if dirty && {
                // composed-frame cache first: scrub/settle over a cached span shows the
                // ORIGINAL-quality frame in ~5ms without touching a decoder
                let mut buf = Vec::new();
                if fcache.get(t, 0.005, &mut buf) {
                    if near_freeze(&doc, t) {
                        eprintln!("SERVE t={t:.3} src=cache");
                    }
                    seq += 1;
                    let mut f = shared.frame.lock().unwrap();
                    f.rgba = buf;
                    f.seq = seq;
                    f.comp_ms = 0.0;
                    f.quality = "proxy";
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
                match compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, t, original, r.scrubbing, true) {
                    Ok((used, exact)) => {
                        scrub_exact = !r.scrubbing || exact;
                        seq += 1;
                        {
                            let mut f = shared.frame.lock().unwrap();
                            f.rgba.clear();
                            f.rgba.extend_from_slice(&comp.rgba);
                            f.seq = seq;
                            f.comp_ms = t0.elapsed().as_secs_f32() * 1000.0;
                            let now = Instant::now();
                            comp_hist.push((now, f.comp_ms));
                            comp_hist.retain(|(t2, _)| now.duration_since(*t2).as_secs_f32() < 1.0);
                            f.comp_max = comp_hist.iter().map(|(_, v)| *v).fold(0.0, f32::max);
                            last_pub = Some(now);
                            f.quality = "proxy";
                        }
                        let _ = used;
                    }
                    Err(e) => eprintln!("compose: {e:#}"),
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
                last_gen = r.gen;
                last_t = t;
            } else if !settled {
                // refine only once the pointer actually RESTS — refining between drag
                // ticks kept compose+readback running back-to-back, saturating the GPU
                // queue and stalling every decoder ReadSample behind it (~50ms/sample)
                let resting = settle.elapsed().as_secs_f32() > 0.12;
                if r.scrubbing && !scrub_exact && resting {
                    let mut buf = Vec::new();
                    if fcache.get(t, 0.005, &mut buf) {
                        if near_freeze(&doc, t) {
                            eprintln!("SERVE t={t:.3} src=cache-rest");
                        }
                        seq += 1;
                        let mut f = shared.frame.lock().unwrap();
                        f.rgba = buf;
                        f.seq = seq;
                        f.quality = "proxy";
                        scrub_exact = true;
                        std::thread::sleep(std::time::Duration::from_millis(2));
                        continue;
                    }
                    // finger resting mid-drag on a long-GOP spot: keep refining toward the
                    // exact frame, one budget slice per pass (converges like Filmora's
                    // "stop and the picture sharpens to the real frame")
                    if let Ok((_, ex)) = compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, t, false, true, true) {
                        scrub_exact = ex;
                        seq += 1;
                        let mut f = shared.frame.lock().unwrap();
                        f.rgba.clear();
                        f.rgba.extend_from_slice(&comp.rgba);
                        f.seq = seq;
                        f.quality = "proxy";
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
                    rg.back().map(|(ft, _)| ft + STEP).unwrap_or_else(|| (t / STEP).floor() * STEP)
                };
                if next_t <= dur {
                    if let Ok(u2) = compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, next_t, false, false, false) {
                        let mut rg = shared.ring.lock().unwrap();
                        rg.push_back((next_t, comp.rgba.clone()));
                        shared.ring_level.store(rg.len(), Ordering::Relaxed);
                        let _ = u2;
                    }
                } else {
                    std::thread::sleep(std::time::Duration::from_millis(2));
                }
            } else if {
                let p0 = Instant::now();
                let r2 = mask_build_pass(&doc, &d3d, &mut masks);
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
                warm_done = warm_open_pass(&doc, &d3d, &mut pool, &masks);
                if p0.elapsed().as_millis() > 80 {
                    eprintln!("PASS warm {}ms", p0.elapsed().as_millis());
                }
            } else if IDLE_FRAME_CACHE_FILL && shared.aux_req.lock().unwrap().is_empty() && {
                // Olive-style background fill: compose ORIGINAL-quality frames outward
                // from the playhead into the frame cache (one per idle slice). AFTER
                // thumbnails/waveforms (visible UI beats invisible cache warmth).
                let mut target = None;
                'fill: for step in 0..(45.0 * 30.0) as i64 {
                    for dir in [1i64, -1i64] {
                        let idx = FrameCache::idx(t) + dir * step;
                        if idx < 0 {
                            continue;
                        }
                        let ft = idx as f64 / 30.0;
                        if ft > dur {
                            continue;
                        }
                        if !fcache.contains(ft) {
                            target = Some(ft);
                            break 'fill;
                        }
                    }
                }
                if let Some(ft) = target {
                    if let Ok(_) = compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, ft, false, false, true) {
                        fcache.insert(ft, &comp.rgba, t);
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
            } else {
                // idle: chew on one aux job slice (thumbnails / waveform peaks)
                let job = { shared.aux_req.lock().unwrap().first().cloned() };
                match job {
                    Some(AuxJob::Thumb { asset_id, path, bucket }) => {
                        let tt = bucket as f64 * THUMB_BUCKET_S + THUMB_BUCKET_S * 0.5;
                        let got = media::thumbnail(&d3d, &path, tt, 96).ok();
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
        let d3d = media::D3d::new()?;
        let mut peak_scan: Option<(String, media::PeakScan)> = None;
        loop {
            let job = { shared.aux_req.lock().unwrap().first().cloned() };
            match job {
                Some(AuxJob::Thumb { asset_id, path, bucket }) => {
                    let tt = bucket as f64 * THUMB_BUCKET_S + THUMB_BUCKET_S * 0.5;
                    let got = media::thumbnail(&d3d, &path, tt, 96).ok();
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
    assets: Vec<serde_json::Value>,
    contents: Vec<serde_json::Value>,
    selected_assets: Vec<String>,
    thumbs: std::collections::HashMap<String, egui::TextureHandle>,
    brief: String,
    title: String,
    format: String,
    preset: usize,
    register_path: String,
    thumb_tried: std::collections::HashSet<String>,
    gen_content: Option<String>,
    gen_job: Option<String>,
    events: Vec<String>,
    error: Option<String>,
    started: bool,
}

struct App {
    screen: Screen,
    lib: Library,
    lib_poll: Instant,
    lib_sink: std::sync::Arc<Mutex<Vec<(String, Result<serde_json::Value, String>)>>>,
    lib_gen_stash: Option<serde_json::Value>,
    marquee: Option<egui::Rect>,
    insp_text: String,
    blur_mode: bool,
    blur_drag: Option<egui::Pos2>,
    insp_for: String,
    cap_keys: std::collections::HashMap<String, String>, // caption clip id -> render key
    cap_tex: std::collections::HashMap<String, egui::TextureHandle>, // key -> texture
    cap_probe: std::collections::HashMap<String, Instant>, // key -> last disk check
    cap_sig: u64,
    cap_req_ids: Vec<String>,
    recut_open: bool,
    recut_thresh: f32,
    recut_lead: f32,
    recut_tail: f32,
    recut_busy: bool,
    revise_open: bool,
    revise_text: String,
    doc: Arc<model::Doc>,
    shared: Arc<Shared>,
    selected: Vec<String>,
    drag: Drag,
    undo: Vec<serde_json::Value>,
    // armed at gesture start (press/drag), committed to `undo` by the FIRST real edit.
    // Pushing at press time polluted the stack with no-op snapshots (a plain click piled
    // identical states, so Ctrl+Z seemed to only ever go one step back).
    pending_undo: Option<serde_json::Value>,
    redo: Vec<serde_json::Value>,
    save_at: Option<Instant>,
    salt: u64,
    thumbs: std::collections::HashMap<(String, i64), egui::TextureHandle>,
    peaks: std::collections::HashMap<String, (f64, Vec<f32>)>,
    aux_ver: u64,
    tex: Option<egui::TextureHandle>,
    last_seq: u64,
    playing: bool,
    playback_speed: f64,
    preview_fullscreen: bool,
    show_help: bool,
    // pts sidecars cached for frame-accurate stepping (None = sidecar missing)
    step_pts: PtsCache,
    // NATIVE_STEP_PROBE state machine: (phase, phase entry time)
    step_probe: Option<(u8, Instant)>,
    toast: Option<(String, Instant)>,
    snap_line: Option<f64>,
    hover_lane: Option<usize>,
    /// preview inspector: (clip id, drag kind, pointer at start, box at start)
    inspect_drag: Option<(String, u8, egui::Pos2, model::Pos)>,
    caption_edit: Option<(String, String)>,
    lane_reorder: Option<usize>,
    export_result: std::sync::Arc<Mutex<Option<Result<serde_json::Value, String>>>>,
    export_job: Option<String>,
    export_status: Option<String>,
    export_poll: Instant,
    /// clip_id -> popout bake display state (polled from the cache dir, not the server)
    pop_states: std::collections::HashMap<String, PopState>,
    bake_results: std::sync::Arc<Mutex<Vec<(String, Result<serde_json::Value, String>)>>>,
    last_pop_poll: Instant,
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
        let before_norm = serde_json::to_string(&raw).unwrap_or_default();
        edits::normalize_linked_audio(&mut raw);
        edits::remove_orphan_linked_audio(&mut raw);
        let normalized_on_load = serde_json::to_string(&raw).unwrap_or_default() != before_norm;
        let doc = Arc::new(model::Doc::from_raw(raw, contents, dir)?);
        let dur = doc.duration();
        let shared = Arc::new(Shared {
            req: Mutex::new(Req { t: 0.0, playing: false, scrubbing: false, speed: 1.0, gen: 0 }),
            frame: Mutex::new(FrameOut {
                rgba: vec![0; (CANVAS_W * CANVAS_H * 4) as usize],
                seq: 0,
                comp_ms: 0.0,
                comp_max: 0.0,
                gap_max: 0.0,
                quality: "proxy",
            }),
            clock_bits: AtomicU64::new(0f64.to_bits()),
            underruns: AtomicU64::new(0),
            dirty_from_bits: AtomicU64::new(f64::INFINITY.to_bits()),
            ring_level: std::sync::atomic::AtomicUsize::new(0),
            ring: Mutex::new(Default::default()),
            ring_gen: AtomicU64::new(0),
            ring_target_bits: AtomicU64::new(0f64.to_bits()),
            doc: Mutex::new(doc.clone()),
            aux_req: Mutex::new(Vec::new()),
            aux: Mutex::new(AuxOut::default()),
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
            lib: Library { format: "9:16".into(), ..Default::default() },
            lib_poll: Instant::now(),
            lib_sink: Default::default(),
            lib_gen_stash: None,
            marquee: None,
            insp_text: String::new(),
            blur_mode: false,
            blur_drag: None,
            insp_for: String::new(),
            cap_keys: Default::default(),
            cap_tex: Default::default(),
            cap_probe: Default::default(),
            cap_sig: 0,
            cap_req_ids: Vec::new(),
            recut_open: false,
            recut_thresh: 0.45,
            recut_lead: 0.06,
            recut_tail: 0.10,
            recut_busy: false,
            revise_open: false,
            revise_text: String::new(),
            doc,
            shared,
            selected: Vec::new(),
            drag: Drag::None,
            undo: Vec::new(),
            pending_undo: None,
            redo: Vec::new(),
            save_at: normalized_on_load.then(|| Instant::now() + std::time::Duration::from_millis(1200)),
            thumbs: Default::default(),
            peaks: Default::default(),
            aux_ver: 0,
            salt: std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0),
            tex: None,
            last_seq: 0,
            playing: false,
            playback_speed: 1.0,
            preview_fullscreen: false,
            show_help: false,
            step_pts: Default::default(),
            step_probe: None,
            toast: None,
            snap_line: None,
            hover_lane: None,
            inspect_drag: None,
            caption_edit: None,
            lane_reorder: None,
            export_result: Default::default(),
            export_job: None,
            export_status: None,
            export_poll: Instant::now(),
            pop_states: Default::default(),
            bake_results: Default::default(),
            last_pop_poll: Instant::now(),
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
                    let sig = format!(
                        "{ti}|{:.3}|{:.3}|{:.3}|{:?}|{:?}|{:?}|{:?}|{:?}|{:.3}|{}|{}|{}|{}",
                        c.timeline_start,
                        c.timeline_end,
                        c.source_start,
                        c.source_end,
                        c.position,
                        c.crop,
                        c.region,
                        c.text,
                        c.volume,
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
        if snapshot {
            self.pending_undo = None;
            self.undo.push(self.doc.raw.clone());
            if self.undo.len() > 60 {
                self.undo.remove(0);
            }
            self.redo.clear();
        } else if let Some(prev) = self.pending_undo.take() {
            // first real edit of the armed gesture — commit the pre-gesture state
            self.undo.push(prev);
            if self.undo.len() > 60 {
                self.undo.remove(0);
            }
            self.redo.clear();
        }
        let mut raw = self.doc.raw.clone();
        f(&mut raw);
        edits::normalize_linked_audio(&mut raw);
        edits::remove_orphan_linked_audio(&mut raw);
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
        if let Ok(nd) = model::Doc::from_raw(raw, &self.doc.contents_path, &self.doc.asset_dir) {
            let nd = Arc::new(nd);
            self.doc = nd.clone();
            *self.shared.doc.lock().unwrap() = nd;
            self.dur = self.doc.duration();
            self.save_at = Some(Instant::now() + std::time::Duration::from_millis(1200));
            self.push_req(false);
        }
    }

    /// Snap t to nearby clip edges / the playhead (8px feel like Filmora's magnet).
    fn snap(&self, t: f64, ignore: &[String]) -> f64 {
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
        best
    }

    /// Register a dropped file as an asset (assets.json) and insert a linked A/V clip pair
    /// at the playhead on the first video/audio tracks.
    fn import_file(&mut self, p: &std::path::Path) -> anyhow::Result<()> {
        let path = p.to_string_lossy().replace(char::from(92), "/");
        self.salt += 1;
        let id = format!("nat{}_{}", self.salt, std::process::id());
        // asset duration via a throwaway probe on the media thread would be cleaner; a direct
        // MF probe from this thread works because MF objects are free-threaded (COM init is
        // best-effort here).
        let dur = probe_duration(&path).unwrap_or(5.0);
        // assets.json append
        let aj = format!("{}/assets.json", self.doc.asset_dir);
        let mut arr: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(&aj).unwrap_or_else(|_| "[]".into()))
                .unwrap_or_else(|_| serde_json::Value::Array(vec![]));
        if let Some(a) = arr.as_array_mut() {
            a.push(serde_json::json!({
                "id": id,
                "kind": "video",
                "name": p.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default(),
                "local_path": path,
                "status": "ready",
                "imported_by": "native"
            }));
        }
        std::fs::write(&aj, serde_json::to_string(&arr)?)?;
        // insert clips at playhead
        let t = self.t;
        let link = format!("lk_{id}");
        let vid = serde_json::json!({
            "id": format!("{id}_v"), "asset_id": id, "track": "video",
            "source_start": 0.0, "source_end": dur,
            "timeline_start": t, "timeline_end": t + dur, "link_id": link
        });
        let aud = serde_json::json!({
            "id": format!("{id}_a"), "asset_id": id, "track": "audio",
            "source_start": 0.0, "source_end": dur,
            "timeline_start": t, "timeline_end": t + dur, "link_id": link
        });
        self.apply_edit(true, move |raw| {
            if let Some(seq) = raw
                .get_mut(0)
                .and_then(|r| r.get_mut("timeline"))
                .and_then(|x| x.get_mut("sequence"))
            {
                if let Some(tracks) = seq.get_mut("tracks").and_then(|x| x.as_array_mut()) {
                    let mut vdone = false;
                    for tr in tracks.iter_mut() {
                        let kind = tr.get("type").and_then(|k| k.as_str()).unwrap_or("");
                        if kind == "video" && !vdone {
                            if let Some(cs) = tr.get_mut("clips").and_then(|c| c.as_array_mut()) {
                                cs.push(vid.clone());
                                vdone = true;
                            }
                        }
                    }
                    for tr in tracks.iter_mut() {
                        let kind = tr.get("type").and_then(|k| k.as_str()).unwrap_or("");
                        if kind == "audio" {
                            if let Some(cs) = tr.get_mut("clips").and_then(|c| c.as_array_mut()) {
                                cs.push(aud.clone());
                            }
                            break;
                        }
                    }
                }
            }
        });
        Ok(())
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
                "source_end": c.source_start + (c.timeline_end - c.timeline_start),
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

    /// Designed captions: when the caption set changes, ask the server for the SAME
    /// /caption-frame PNGs the export burns in (cached server-side); the preview then
    /// shows the real design instead of plain text.
    fn caption_cache_pass(&mut self) {
        use std::hash::{Hash, Hasher};
        let mut specs: Vec<(String, serde_json::Value)> = Vec::new();
        let tracks = self.doc.raw.get(0).and_then(|c| c.get("timeline")).and_then(|t| t.get("sequence")).and_then(|sq| sq.get("tracks")).and_then(|t| t.as_array());
        if let Some(tracks) = tracks {
            for tr in tracks {
                for cl in tr.get("clips").and_then(|c| c.as_array()).map(|a| a.as_slice()).unwrap_or(&[]) {
                    let text = cl.get("text").and_then(|t| t.as_str()).unwrap_or("");
                    if text.trim().is_empty() {
                        continue;
                    }
                    let id = cl.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                    let spec = serde_json::json!({
                        "text": text,
                        "design": cl.get("style").cloned().unwrap_or(serde_json::json!({})),
                        "words": cl.get("words").cloned().unwrap_or(serde_json::json!([])),
                    });
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
        if sig == self.cap_sig || specs.is_empty() {
            return;
        }
        self.cap_sig = sig;
        self.cap_req_ids = specs.iter().map(|(id, _)| id.clone()).collect();
        let items: Vec<serde_json::Value> = specs.into_iter().map(|(_, sp)| sp).collect();
        let body = serde_json::json!({
            "room_id": self.room_id(),
            "outW": CANVAS_W,
            "outH": CANVAS_H,
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

    /// One arrow-key frame step (exactly what the key handler runs).
    fn step_once(&mut self, dir: f64) {
        const FSTEP: f64 = 1.0 / 30.0;
        let grid = (self.t / FSTEP).round() * FSTEP + dir * FSTEP;
        let nt = step_target(&self.doc, &mut self.step_pts, self.t, dir).unwrap_or(grid);
        self.t = nt.clamp(0.0, self.dur);
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
            if f.rgba.len() == (CANVAS_W * CANVAS_H * 4) as usize {
                let p = format!("{out_dir}/{name}.png");
                let _ = std::fs::create_dir_all(&out_dir);
                let _ = image::save_buffer(&p, &f.rgba, CANVAS_W, CANVAS_H, image::ColorType::Rgba8);
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
            self.apply_edit(true, |raw| edits::split_clips(raw, &ids, t, salt));
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
            self.redo.push(self.doc.raw.clone());
            self.restore(prev);
        }
    }

    fn do_redo(&mut self) {
        if let Some(next) = self.redo.pop() {
            self.undo.push(self.doc.raw.clone());
            self.restore(next);
        }
    }

    fn zoom_fit(&mut self, width: f32) {
        self.pps = ((width - 112.0 - 40.0) / (self.dur.max(1.0) as f32)).clamp(1.0, 400.0);
        self.scroll_x = 0.0;
    }

    /// transport bar under the preview: jump/step/play buttons + seek bar + timecode
    fn transport_ui(&mut self, ui: &mut egui::Ui) {
        let fmt_tc = |t: f64| {
            let fr = ((t * 30.0).round() as i64).max(0);
            format!("{:02}:{:02}:{:02}", fr / 1800, (fr / 30) % 60, fr % 30)
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
                self.t = (self.t - 1.0 / 30.0).max(0.0);
                self.push_req(false);
            }
            let glyph = if self.playing { "⏸" } else { "▶" };
            if ui
                .add(
                    egui::Button::new(egui::RichText::new(glyph).size(21.0).color(egui::Color32::WHITE))
                        .min_size(egui::vec2(44.0, 32.0))
                        .rounding(16.0)
                        .fill(if self.playing {
                            egui::Color32::from_rgb(60, 60, 66)
                        } else {
                            UI_ACCENT
                        }),
                )
                .on_hover_text("再生 / 一時停止 (Space)")
                .clicked()
            {
                self.toggle_play();
            }
            if tbtn(ui, "⏩", "1フレーム進む (→)") {
                self.playing = false;
                self.t = (self.t + 1.0 / 30.0).min(self.dur);
                self.push_req(false);
            }
            if tbtn(ui, "⏭", "末尾へ (End)") {
                self.playing = false;
                self.t = self.dur;
                self.push_req(false);
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

    /// icon strip above the ruler: undo/redo, split, delete, zoom (Filmora layout)
    fn timeline_toolbar(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            ui.add_space(6.0);
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
        if hov {
            ui.ctx().set_cursor_icon(egui::CursorIcon::PointingHand);
        }
        if resp.clicked() && !id.is_empty() {
            if selected {
                self.lib.selected_assets.retain(|s| *s != id);
            } else {
                self.lib.selected_assets.push(id.clone());
            }
        }
    }

    /// Inspector: properties panel for the selected clip (single selection). Numeric
    /// position/size, volume, per-edge crop, popout toggle; captions edit in place.
    fn inspector_ui(&mut self, ctx: &egui::Context) {
        if self.selected.len() != 1 {
            return;
        }
        let id = self.selected[0].clone();
        let Some((clip, kind)) = self
            .doc
            .seq
            .tracks
            .iter()
            .flat_map(|tr| tr.clips.iter().map(move |c| (c, tr.kind.clone())))
            .find(|(c, _)| c.id == id)
            .map(|(c, k)| (c.clone(), k))
        else {
            return;
        };
        egui::SidePanel::right("inspector").exact_width(250.0).show(ctx, |ui| {
            egui::ScrollArea::vertical().show(ui, |ui| {
                ui.add_space(8.0);
                let title = if clip.text.is_some() && clip.asset_id.is_none() {
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
                // ---- region effect (blur/mosaic) ----
                if clip.region.is_some() && clip.asset_id.is_none() {
                    ui.label(egui::RichText::new("種類").strong());
                    let cur = clip.style.as_ref().and_then(|v| v.as_str()).unwrap_or("mosaic").to_string();
                    ui.horizontal(|ui| {
                        for (label, val) in [("モザイク", "mosaic"), ("ぼかし", "gaussian")] {
                            if ui.selectable_label(cur.contains(val), label).clicked() {
                                let cid = id.clone();
                                self.apply_edit(true, move |raw| edits::set_style(raw, &cid, val));
                                self.push_req(false);
                            }
                        }
                    });
                    ui.label(egui::RichText::new("※プレビューはモザイク表示。書き出しで指定の種類が適用されます").small().weak());
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
                    if self.insp_for != id {
                        self.insp_for = id.clone();
                        self.insp_text = clip.text.clone().unwrap_or_default();
                    }
                    ui.label(egui::RichText::new("本文").strong());
                    let r = ui.add(
                        egui::TextEdit::multiline(&mut self.insp_text)
                            .desired_rows(4)
                            .desired_width(f32::INFINITY),
                    );
                    if r.gained_focus() {
                        self.pending_undo = Some(self.doc.raw.clone());
                    }
                    if r.changed() {
                        let txt = self.insp_text.clone();
                        let cid = id.clone();
                        self.apply_edit(false, move |raw| edits::set_text(raw, &cid, &txt));
                        self.push_req(false);
                    }
                    return;
                }
                if clip.asset_id.is_none() {
                    return;
                }
                // ---- position & size (canvas %) ----
                ui.label(egui::RichText::new("位置とサイズ（%）").strong());
                let b = clip.display_box();
                let mut vals = [b.x * 100.0, b.y * 100.0, b.width * 100.0, b.height * 100.0];
                let mut changed = false;
                for (row, pair) in [("X / Y", [0usize, 1]), ("幅 / 高さ", [2, 3])] {
                    ui.horizontal(|ui| {
                        ui.label(egui::RichText::new(row).weak().small());
                        for &i in &pair {
                            let rng = if i < 2 { -50.0..=100.0 } else { 1.0..=100.0 };
                            let r = ui.add(
                                egui::DragValue::new(&mut vals[i]).speed(0.5).range(rng).suffix("%"),
                            );
                            if r.drag_started() || r.gained_focus() {
                                self.pending_undo = Some(self.doc.raw.clone());
                            }
                            changed |= r.changed();
                        }
                    });
                }
                if changed {
                    let cid = id.clone();
                    let (x, y, w, h) =
                        (vals[0] / 100.0, vals[1] / 100.0, vals[2] / 100.0, vals[3] / 100.0);
                    self.apply_edit(false, move |raw| edits::set_position(raw, &cid, x, y, w, h));
                    self.push_req(false);
                }
                if ui.small_button("全画面に戻す").clicked() {
                    let cid = id.clone();
                    self.apply_edit(true, move |raw| edits::set_position(raw, &cid, 0.0, 0.0, 1.0, 1.0));
                    self.push_req(false);
                }
                ui.add_space(6.0);
                // ---- volume ----
                if clip.link_id.is_some() {
                    ui.label(egui::RichText::new("音量").strong());
                    let mut vol = (clip.volume * 100.0) as f32;
                    let r = ui.add(egui::Slider::new(&mut vol, 0.0..=200.0).suffix("%"));
                    if r.drag_started() {
                        self.pending_undo = Some(self.doc.raw.clone());
                    }
                    if r.changed() {
                        let ids = edits::expand_links(&self.doc.raw, &[id.clone()]);
                        let v = (vol / 100.0) as f64;
                        self.apply_edit(false, move |raw| edits::set_volume(raw, &ids, v));
                    }
                    ui.add_space(6.0);
                }
                // ---- crop ----
                ui.label(egui::RichText::new("クロップ（端を切る %）").strong());
                let (l, t, r_, bm) = clip.crop_ltrb().unwrap_or((0.0, 0.0, 0.0, 0.0));
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
                    let cid = id.clone();
                    let (cl, ct, crr, cb) =
                        (cr[0] / 100.0, cr[1] / 100.0, cr[2] / 100.0, cr[3] / 100.0);
                    self.apply_edit(false, move |raw| edits::set_crop(raw, &cid, cl, ct, crr, cb));
                    self.push_req(false);
                }
                if clip.crop_ltrb().is_some() && ui.small_button("クロップ解除").clicked() {
                    let cid = id.clone();
                    self.apply_edit(true, move |raw| edits::set_crop(raw, &cid, 0.0, 0.0, 0.0, 0.0));
                    self.push_req(false);
                }
                ui.add_space(6.0);
                // ---- popout ----
                if kind != "audio" {
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
                let src = c.source_start + (t - c.timeline_start);
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
                let tn = (t + (chosen + fd + 0.0002 - src)).min(c.timeline_end - 0.05);
                let new_src = c.source_start + (tn - c.timeline_start);
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
                let src = (c.source_start + (t - c.timeline_start) - frame_back).max(0.0);
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
                    let (w, h) = (CANVAS_W, CANVAS_H);
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

    fn lib_refresh(&mut self) {
        let room = self.room_id();
        self.lib_get("assets", format!("/api/v1/production-assets?room_id={room}"));
        self.lib_get("contents", format!("/api/v1/production-assets/contents?room_id={room}"));
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

    fn open_content(&mut self, content_id: &str) {
        let path = format!("{}/contents.json", self.doc.asset_dir);
        let Ok(txt) = std::fs::read_to_string(&path) else { return };
        let Ok(mut raw) = serde_json::from_str::<serde_json::Value>(&txt) else { return };
        if let Some(arr) = raw.as_array_mut() {
            if let Some(idx) = arr.iter().position(|c| c.get("id").and_then(|v| v.as_str()) == Some(content_id)) {
                let c = arr.remove(idx);
                arr.insert(0, c);
            }
        }
        if let Ok(nd) = model::Doc::from_raw(raw, &self.doc.contents_path, &self.doc.asset_dir) {
            let nd = Arc::new(nd);
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
            self.push_req(false);
            self.migrate_legacy_freezes();
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
                "revision_regions": [],
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
    }

    fn start_generation(&mut self) {
        let room = self.room_id();
        let presets: [(&str, &str, &str); 5] = [
            ("映像→UGC", "9:16", "UGC風の縦型ショート動画にしてください。テンポ良く、無音や間はカットしてください。"),
            ("映像→ストーリー", "9:16", "ストーリー性のある縦型動画に編集してください。"),
            ("映像→映画風", "16:9", "映画の予告編のような雰囲気の横型動画にしてください。"),
            ("画像→広告画像", "4:5", "商品広告向けの画像コンテンツを作ってください。"),
            ("自由制作", "9:16", ""),
        ];
        let (pname, _, pbrief) = presets[self.lib.preset.min(4)];
        let brief = if self.lib.brief.trim().is_empty() { pbrief.to_string() } else { self.lib.brief.clone() };
        let title = if self.lib.title.trim().is_empty() {
            format!("{pname} {}", self.lib.contents.len() + 1)
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

    fn content_id(&self) -> String {
        self.doc
            .raw
            .get(0)
            .and_then(|r| r.get("id"))
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .to_string()
    }

    fn start_export(&mut self) {
        // mode "export" renders the CURRENT timeline server-side (the sequence rides in
        // the instruction — what you see is exactly what gets rendered)
        let timeline = self
            .doc
            .raw
            .get(0)
            .and_then(|r| r.get("timeline"))
            .cloned()
            .unwrap_or(serde_json::json!({}));
        let payload = serde_json::json!({
            "room_id": self.room_id(),
            "content_id": self.content_id(),
            "instruction": {"mode": "export", "timeline": timeline},
        })
        .to_string();
        self.export_status = Some("書き出しを開始しています…".into());
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
                    self.export_status = Some(format!("書き出しエラー: {e}"));
                    self.export_job = None;
                    eprintln!("export failed: {e}");
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
        let sink = self.export_result.clone();
        std::thread::spawn(move || {
            let res = http_local("GET", &path, None)
                .and_then(|t| Ok(serde_json::from_str::<serde_json::Value>(&t)?))
                .map(|list| serde_json::json!({"poll": list, "job": job_id}))
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
                let out = job
                    .get("result")
                    .and_then(|r| r.get("output_path"))
                    .and_then(|p| p.as_str())
                    .unwrap_or("")
                    .to_string();
                self.export_job = None;
                self.export_status = Some(format!("書き出し完了: {out}"));
                self.toast(&format!("書き出し完了 → {out}"));
            }
            "failed" => {
                let err = job.get("error").and_then(|e| e.as_str()).unwrap_or("不明なエラー");
                self.export_job = None;
                self.export_status = Some(format!("書き出し失敗: {err}"));
            }
            st => {
                self.export_status = Some(format!("書き出し{}…", if st == "queued" { "待機中" } else { "中" }));
            }
        }
        true
    }

    /// Preview inspector: the selected clip's display box is drawn over the preview and
    /// can be MOVED (drag inside) or RESIZED (corner handles, aspect kept) directly.
    fn preview_inspector(&mut self, ui: &mut egui::Ui, resp: &egui::Response) {
        let img = resp.rect;
        // exactly one selected visual clip
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
        if sel.len() != 1 {
            return;
        }
        let c = &sel[0];
        // only meaningful while the clip is on screen
        if self.t < c.timeline_start || self.t >= c.timeline_end {
            return;
        }
        let b = c.display_box();
        let bx = egui::Rect::from_min_size(
            egui::pos2(
                img.left() + (b.x as f32) * img.width(),
                img.top() + (b.y as f32) * img.height(),
            ),
            egui::vec2((b.width as f32) * img.width(), (b.height as f32) * img.height()),
        );
        let p = ui.painter_at(img);
        p.rect_stroke(bx, 2.0, egui::Stroke::new(1.5, egui::Color32::from_rgb(90, 170, 255)));
        let corners = [bx.min, egui::pos2(bx.max.x, bx.min.y), egui::pos2(bx.min.x, bx.max.y), bx.max];
        for cp in corners {
            p.rect_filled(egui::Rect::from_center_size(cp, egui::vec2(9.0, 9.0)), 2.0, egui::Color32::from_rgb(90, 170, 255));
        }
        let pointer = resp.interact_pointer_pos().or(resp.hover_pos());
        // cursor feedback
        if let Some(pt) = pointer {
            if corners.iter().any(|cp| cp.distance(pt) < 10.0) {
                ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeNwSe);
            } else if bx.contains(pt) {
                ui.ctx().set_cursor_icon(egui::CursorIcon::Grab);
            }
        }
        if resp.drag_started() {
            if let Some(pt) = resp.interact_pointer_pos() {
                let corner = corners.iter().position(|cp| cp.distance(pt) < 10.0);
                if let Some(ci) = corner {
                    self.pending_undo = Some(self.doc.raw.clone());
                    self.inspect_drag = Some((c.id.clone(), ci as u8 + 1, pt, b));
                } else if bx.contains(pt) {
                    self.pending_undo = Some(self.doc.raw.clone());
                    self.inspect_drag = Some((c.id.clone(), 0, pt, b));
                }
            }
        }
        if resp.dragged() {
            if let (Some((id, mode, start, ob)), Some(pt)) = (self.inspect_drag.clone(), resp.interact_pointer_pos()) {
                let dx = ((pt.x - start.x) / img.width()) as f64;
                let dy = ((pt.y - start.y) / img.height()) as f64;
                let (nx, ny, nw, nh) = if mode == 0 {
                    (ob.x + dx, ob.y + dy, ob.width, ob.height)
                } else {
                    // corner resize, aspect kept, anchored at the OPPOSITE corner
                    let (ax, ay, sxs, sys) = match mode {
                        1 => (ob.x + ob.width, ob.y + ob.height, -1.0, -1.0),
                        2 => (ob.x, ob.y + ob.height, 1.0, -1.0),
                        3 => (ob.x + ob.width, ob.y, -1.0, 1.0),
                        _ => (ob.x, ob.y, 1.0, 1.0),
                    };
                    let scale_w = (ob.width + dx * sxs).max(0.03) / ob.width;
                    let scale_h = (ob.height + dy * sys).max(0.03) / ob.height;
                    let sc = scale_w.max(scale_h);
                    let (nw, nh) = (ob.width * sc, ob.height * sc);
                    let nx = if sxs < 0.0 { ax - nw } else { ax };
                    let ny = if sys < 0.0 { ay - nh } else { ay };
                    (nx, ny, nw, nh)
                };
                self.apply_edit(false, move |raw| edits::set_position(raw, &id, nx, ny, nw, nh));
            }
        }
        if resp.drag_stopped() {
            self.inspect_drag = None;
            self.push_req(false); // settle full quality after the adjustment
        }
    }

    fn push_req(&mut self, scrubbing: bool) {
        let mut r = self.shared.req.lock().unwrap();
        self.gen += 1;
        self.last_push = Instant::now();
        *r = Req { t: self.t, playing: self.playing, scrubbing, speed: self.playback_speed, gen: self.gen };
    }

    fn timeline_ui(&mut self, ui: &mut egui::Ui) {
        const GUTTER: f32 = 112.0; // lane headers (number + lock/eye/mute/solo/magnet icons)
        const BOTTOM: f32 = 24.0; // zoom slider + scrollbar
        let h = ui.available_height() - BOTTOM;
        let w = ui.available_width();
        let (rect, resp) = ui.allocate_exact_size(egui::vec2(w, h), egui::Sense::click_and_drag());
        let body = egui::Rect::from_min_max(egui::pos2(rect.left() + GUTTER, rect.top()), rect.max);
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

        // Layered-track model (Filmora/Olive): the tracks array IS the stacking order,
        // index 0 = back. Display shows visual tracks top=front (reverse array order);
        // audio tracks sit below the visual stack (universal NLE convention). No
        // kind-based pinning — reorder/move clips and the render follows.
        let visual: Vec<usize> = (0..self.doc.seq.tracks.len())
            .rev()
            .filter(|&i| self.doc.seq.tracks[i].kind != "audio")
            .collect();
        let audio: Vec<usize> = (0..self.doc.seq.tracks.len())
            .filter(|&i| self.doc.seq.tracks[i].kind == "audio")
            .collect();
        let order: Vec<usize> = visual.into_iter().chain(audio).collect();
        let kind_h = |kind: &str| match kind {
            "video" => 54.0f32,
            "overlay" => 46.0,
            "audio" => 30.0,
            "caption" => 22.0,
            _ => 20.0,
        };
        let total_h: f32 = order.iter().map(|&i| kind_h(&self.doc.seq.tracks[i].kind) + 3.0).sum();
        let avail = h - ruler_h - 6.0;
        let squeeze = (avail / total_h).min(1.0);
        let mut lane_tops: Vec<(usize, f32, f32)> = Vec::new(); // (track idx, y0, height)
        {
            let mut y = rect.top() + ruler_h + 3.0;
            for &i in &order {
                let lh = kind_h(&self.doc.seq.tracks[i].kind) * squeeze;
                lane_tops.push((i, y, lh));
                y += lh + 3.0 * squeeze;
            }
        }
        let mut clips_drawn = 0usize;
        let mut hits: Vec<(egui::Rect, String)> = Vec::new();
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
        for &(ti, y0, lane_h) in &lane_tops {
            let tr = &self.doc.seq.tracks[ti];
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
            // lane header: layer number + standard NLE toggles (lock / eye / mute / solo,
            // magnet on the main video lane). Lanes still have no fixed roles.
            p.text(
                egui::pos2(rect.left() + 4.0, y0 + lane_h * 0.5),
                egui::Align2::LEFT_CENTER,
                if tr.kind == "audio" {
                    format!("A{}", ti + 1)
                } else {
                    format!("{}", ti + 1)
                },
                egui::FontId::proportional(11.0),
                egui::Color32::from_gray(140),
            );
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
                let mut x = rect.left() + 24.0;
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
            let color = match tr.kind.as_str() {
                "video" => egui::Color32::from_rgb(70, 110, 190),
                "overlay" => egui::Color32::from_rgb(150, 90, 200),
                "audio" => egui::Color32::from_rgb(70, 160, 90),
                "caption" => egui::Color32::from_rgb(190, 150, 60),
                _ => egui::Color32::from_gray(90),
            };
            for c in &tr.clips {
                if tr.kind == "audio" && linked_av.contains(&c.id) {
                    continue; // drawn as part of its video clip
                }
                let x0 = body.left() + (c.timeline_start as f32) * self.pps - self.scroll_x;
                let x1 = body.left() + (c.timeline_end as f32) * self.pps - self.scroll_x;
                if x1 < body.left() || x0 > body.right() {
                    continue;
                }
                let r = egui::Rect::from_min_max(
                    egui::pos2(x0.max(body.left()), y0),
                    egui::pos2(x1.min(body.right()), y0 + lane_h),
                );
                let is_pop = c.effects.iter().any(|e| e.kind == "popout");
                let pop_state = if is_pop { self.pop_states.get(&c.id).copied() } else { None };
                let is_caption = c.text.is_some() && c.asset_id.is_none();
                if is_caption {
                    // caption clip: dark slate body + mustard accent edge + the TEXT itself
                    p.rect_filled(r, 4.0, egui::Color32::from_rgb(46, 42, 30));
                    p.rect_filled(
                        egui::Rect::from_min_max(r.min, egui::pos2(r.left() + 3.0, r.bottom())),
                        2.0,
                        color,
                    );
                    if r.width() > 22.0 {
                        let txt = c.text.clone().unwrap_or_default().replace(chr_nl(), " ");
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
                    p.rect_filled(r, 4.0, color.gamma_multiply(0.55));
                    if c.region.is_some() && r.width() > 26.0 {
                        let style = c.style.as_ref().and_then(|v| v.as_str()).unwrap_or("");
                        p.text(
                            egui::pos2(r.left() + 6.0, r.center().y),
                            egui::Align2::LEFT_CENTER,
                            if style.contains("mosaic") { "モザイク" } else { "ぼかし" },
                            egui::FontId::proportional(10.0),
                            egui::Color32::from_gray(220),
                        );
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
                            format!("飛び出し生成中 {pct}%")
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
                }
                if tr.kind != "audio" && c.link_id.is_some() {
                    // unified A/V: waveform ribbon along the clip's bottom quarter
                    if let Some((spb, pk)) = c.asset_id.as_ref().and_then(|a| self.peaks.get(a)) {
                        let base_y = r.bottom() - 1.0;
                        let amp = (r.height() * 0.26).min(12.0);
                        let n = ((r.width() / 2.0) as usize).max(1);
                        for i in 0..n {
                            let x = r.left() + (i as f32) * 2.0;
                            let tt = c.source_start
                                + ((i as f32 / n as f32) * (c.timeline_end - c.timeline_start) as f32) as f64;
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
                            let tt = c.source_start
                                + ((i as f32 / n as f32) * (c.timeline_end - c.timeline_start) as f32) as f64;
                            let idx = (tt / spb) as usize;
                            let v = pk.get(idx).copied().unwrap_or(0.0).min(1.0).max(0.04);
                            p.line_segment(
                                [egui::pos2(x, mid + v * half), egui::pos2(x, mid - v * half)],
                                egui::Stroke::new(1.4, egui::Color32::from_rgb(45, 190, 155)),
                            );
                        }
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
                    let edge_hit = if sel { 14.0 } else { 10.0 };
                    if r.expand2(egui::vec2(edge_hit, 0.0)).contains(pt)
                        && ((pt.x - r.left()).abs() <= edge_hit || (pt.x - r.right()).abs() <= edge_hit)
                    {
                        ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeHorizontal);
                    } else if r.contains(pt)
                        && pt.y > r.bottom() - 14.0
                        && r.height() >= 40.0
                        && c.link_id.is_some()
                        && c.asset_id.is_some()
                    {
                        // waveform ribbon = volume zone
                        ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeVertical);
                    }
                }
                if !tr.locked {
                    hits.push((r, c.id.clone()));
                }
                clips_drawn += 1;
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
        // ---- interactions: trim edges > move body > scrub empty space ----
        let to_t = |scroll_x: f32, pps: f32, x: f32| ((scroll_x + (x - body.left())) / pps).max(0.0) as f64;
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
                let edge_hit = hits
                    .iter()
                    .filter_map(|(r, id)| {
                        let selected = self.selected.contains(id);
                        let edge_px = if selected { 14.0 } else { 10.0 };
                        if !r.expand2(egui::vec2(edge_px, 0.0)).contains(pos) {
                            return None;
                        }
                        let dl = (pos.x - r.left()).abs();
                        let dr = (pos.x - r.right()).abs();
                        let dist = dl.min(dr);
                        if dist <= edge_px {
                            Some((if selected { 0 } else { 1 }, dist, *r, id.clone(), dl <= dr))
                        } else {
                            None
                        }
                    })
                    .min_by(|a, b| a.0.cmp(&b.0).then_with(|| a.1.total_cmp(&b.1)))
                    .map(|(_, _, r, id, left)| (r, id, Some(left)));
                let body_hit = edge_hit.clone().or_else(|| {
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
                                    self.caption_edit = Some((c.id.clone(), txt.clone()));
                                }
                            }
                        }
                        if !self.selected.contains(&id) {
                            if ui.input(|i| i.modifiers.ctrl) {
                                self.selected.push(id.clone());
                            } else {
                                self.selected = vec![id.clone()];
                            }
                        }
                        let ids = edits::expand_links(&self.doc.raw, &self.selected);
                        if self.drag == Drag::None {
                            self.pending_undo = Some(self.doc.raw.clone());
                            let vol_zone = pos.y > r.bottom() - 14.0
                                && r.height() >= 40.0
                                && edge.is_none()
                                && (pos.x - r.left()).abs() >= 10.0
                                && (pos.x - r.right()).abs() >= 10.0
                                && self
                                    .doc
                                    .seq
                                    .tracks
                                    .iter()
                                    .flat_map(|tr| tr.clips.iter())
                                    .find(|c| c.id == *id)
                                    .map(|c| c.link_id.is_some() && c.asset_id.is_some())
                                    .unwrap_or(false);
                            if vol_zone {
                                let v0 = self
                                    .doc
                                    .seq
                                    .tracks
                                    .iter()
                                    .flat_map(|tr| tr.clips.iter())
                                    .find(|c| c.id == *id)
                                    .map(|c| c.volume)
                                    .unwrap_or(1.0);
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
                                self.drag = Drag::Move {
                                    ids,
                                    grab: to_t(self.scroll_x, self.pps, pos.x),
                                    orig: ts,
                                    applied: 0.0,
                                };
                            }
                        }
                    }
                    None => {
                        // ruler strip keeps the press-scrub feel; empty LANE space arms a
                        // marquee (drag = box-select, a tiny click still seeks on release)
                        if pos.y <= body.top() + 18.0 {
                            self.selected.clear();
                            self.drag = Drag::Scrub;
                            self.t = to_t(self.scroll_x, self.pps, pos.x).min(self.dur);
                            self.push_req(false);
                        } else {
                            if !ui.input(|i| i.modifiers.ctrl) {
                                self.selected.clear();
                            }
                            self.drag = Drag::Marquee { anchor: pos };
                        }
                    }
                }
            }
        }
        if resp.dragged() {
            if let Some(pos) = resp.interact_pointer_pos() {
                match self.drag.clone() {
                    Drag::Scrub => {
                        self.t = to_t(self.scroll_x, self.pps, pos.x).min(self.dur);
                        self.push_req(true);
                    }
                    Drag::Move { ids, grab, orig, applied } => {
                        // vertical: the clip FOLLOWS the pointer's lane live (not on release)
                        self.hover_lane = lane_tops
                            .iter()
                            .find(|&&(_, y0, lh)| pos.y >= y0 && pos.y <= y0 + lh)
                            .map(|&(ti, _, _)| ti);
                        if let Some(target) = self.hover_lane {
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
                                    self.apply_edit(false, move |raw| edits::move_to_track(raw, &vids, target));
                                }
                            }
                        }
                        let raw_t = orig + (to_t(self.scroll_x, self.pps, pos.x) - grab);
                        let want = self.snap(raw_t, &ids);
                        self.snap_line = ((want - raw_t).abs() > 1e-9).then_some(want);
                        let dt = want - orig - applied;
                        if dt.abs() > 1e-4 {
                            self.apply_edit(false, |raw| edits::move_clips(raw, &ids, dt));
                            if let Drag::Move { applied, .. } = &mut self.drag {
                                *applied += dt;
                            }
                        }
                    }
                    Drag::Trim { ids, left, last_t } => {
                        let raw_t = to_t(self.scroll_x, self.pps, pos.x);
                        let nt = self.snap(raw_t, &ids);
                        self.snap_line = ((nt - raw_t).abs() > 1e-9).then_some(nt);
                        self.apply_edit(false, |raw| edits::trim_clip_live_from(raw, &ids, left, last_t, nt));
                        if let Drag::Trim { last_t, .. } = &mut self.drag {
                            *last_t = nt;
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
                    Drag::Marquee { anchor } => {
                        let r = egui::Rect::from_two_pos(anchor, pos);
                        self.marquee = Some(r);
                        self.selected = hits
                            .iter()
                            .filter(|(cr, _)| cr.intersects(r))
                            .map(|(_, id)| id.clone())
                            .collect();
                    }
                    Drag::None => {}
                }
            }
        }
        // marquee rectangle overlay
        if let Some(r) = self.marquee {
            p.rect_filled(r, 0.0, egui::Color32::from_rgba_unmultiplied(90, 160, 255, 24));
            p.rect_stroke(r, 0.0, egui::Stroke::new(1.0, egui::Color32::from_rgb(120, 180, 255)));
        }
        // edge auto-scroll: ONLY while the playhead is actively held (Scrub drag with the
        // button down) — clip drags and a merely-hovering mouse never move the view
        if matches!(self.drag, Drag::Scrub) && ui.input(|i| i.pointer.primary_down()) {
            if let Some(pt) = ui.input(|i| i.pointer.interact_pos()) {
                const EDGE: f32 = 26.0;
                let speed = |d: f32| ((EDGE - d) / EDGE * 14.0).clamp(2.0, 14.0);
                if pt.x < body.left() + EDGE {
                    self.scroll_x = (self.scroll_x - speed(pt.x - body.left())).max(0.0);
                } else if pt.x > body.right() - EDGE {
                    let max_sx = ((self.dur as f32) * self.pps - body.width()).max(0.0);
                    self.scroll_x = (self.scroll_x + speed(body.right() - pt.x)).min(max_sx);
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
        if resp.drag_stopped() || (released_now && self.drag != Drag::None) {
            let prev = std::mem::replace(&mut self.drag, Drag::None);
            if let Drag::Marquee { anchor } = &prev {
                let moved = self
                    .marquee
                    .map(|r| r.width().max(r.height()) > 4.0)
                    .unwrap_or(false);
                if !moved {
                    self.t = to_t(self.scroll_x, self.pps, anchor.x).min(self.dur);
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
            if let Drag::Trim { ids, left: true, .. } = &prev {
                self.apply_edit(false, |raw| edits::settle_left_trim(raw, ids));
            }
            let _ = &prev; // lane moves happen LIVE during the drag now
            self.hover_lane = None;
            self.snap_line = None;
            if self.resume_on_release {
                self.resume_on_release = false;
                self.resume_pending = Some(Instant::now());
            }
            self.push_req(false); // settle on full quality
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
    }
}

impl App {
    fn absorb_lib(&mut self) {
        let taken: Vec<(String, Result<serde_json::Value, String>)> =
            std::mem::take(&mut *self.lib_sink.lock().unwrap());
        for (tag, res) in taken {
            match (tag.as_str(), res) {
                ("assets", Ok(v)) => {
                    self.lib.assets = v.as_array().cloned().unwrap_or_default();
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
                    let body = serde_json::json!({
                        "room_id": self.room_id(),
                        "content_id": cid,
                        "instruction": {
                            "mode": "dan_plan",
                            "content_id": cid,
                            "content_title": st.get("title").cloned().unwrap_or_default(),
                            "asset_ids": st.get("asset_ids").cloned().unwrap_or_default(),
                            "source_assets": st.get("source_assets").cloned().unwrap_or_default(),
                            "brief": st.get("brief").cloned().unwrap_or_default(),
                            "workflow_preset": st.get("workflow_preset").cloned().unwrap_or_default(),
                            "timeline": st.get("timeline").cloned().unwrap_or_default(),
                        },
                    });
                    self.lib_post("gen_job", "/api/v1/production-assets/jobs".into(), body);
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
                            self.open_content(&cid);
                        }
                        "failed" => {
                            self.lib.error = Some(
                                job.get("error").and_then(|e| e.as_str()).unwrap_or("失敗").to_string(),
                            );
                            self.lib.started = false;
                            self.lib.gen_job = None;
                        }
                        _ => {}
                    }
                }
                ("events_poll", Ok(v)) => {
                    if let Some(arr) = v.as_array() {
                        let msgs: Vec<String> = arr
                            .iter()
                            .rev()
                            .take(8)
                            .rev()
                            .filter_map(|e| e.get("text").and_then(|t| t.as_str()).map(|s| s.to_string()))
                            .collect();
                        if !msgs.is_empty() {
                            self.lib.events = msgs;
                        }
                    }
                }
                ("act", Ok(_)) => {
                    self.lib_refresh();
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
        egui::SidePanel::right("gen_panel").exact_width(360.0).show(ctx, |ui| {
            egui::ScrollArea::vertical().show(ui, |ui| {
                ui.add_space(10.0);
                ui.heading("新しく作る");
                ui.add_space(2.0);
                ui.label(egui::RichText::new("素材を選んでダンに丸ごと編集させます").weak().small());
                ui.add_space(10.0);
                ui.label(egui::RichText::new("1. 作りたいもの").strong());
                let presets = [
                    ("映像→UGC", "9:16", "テンポ良く無音をカットした縦型ショート"),
                    ("映像→ストーリー", "9:16", "ストーリー仕立ての縦型動画"),
                    ("映像→映画風", "16:9", "予告編のような横型動画"),
                    ("画像→広告画像", "4:5", "商品広告向けの画像"),
                    ("自由制作", "9:16", "ブリーフの指示だけで自由に"),
                ];
                for (i, (name, fmt, desc)) in presets.iter().enumerate() {
                    let on = self.lib.preset == i;
                    let fill = if on { egui::Color32::from_rgb(0, 84, 66) } else { egui::Color32::from_rgb(34, 34, 39) };
                    let resp = ui.add(
                        egui::Button::new(
                            egui::RichText::new(format!("{name}  {fmt}\n{desc}")).size(11.5),
                        )
                        .min_size(egui::vec2(330.0, 40.0))
                        .fill(fill)
                        .stroke(if on {
                            egui::Stroke::new(1.5, UI_ACCENT)
                        } else {
                            egui::Stroke::new(1.0, egui::Color32::from_gray(50))
                        }),
                    );
                    if resp.clicked() {
                        self.lib.preset = i;
                        self.lib.format = fmt.to_string();
                    }
                }
                ui.add_space(10.0);
                ui.label(egui::RichText::new("2. 内容（任意）").strong());
                ui.add(egui::TextEdit::singleline(&mut self.lib.title).hint_text("タイトル（空なら自動）").desired_width(f32::INFINITY));
                ui.add(
                    egui::TextEdit::multiline(&mut self.lib.brief)
                        .desired_rows(3)
                        .desired_width(f32::INFINITY)
                        .hint_text("どう作ってほしいか（例: 冒頭3秒で結論、テロップ大きめ）"),
                );
                ui.horizontal(|ui| {
                    ui.label(egui::RichText::new("形式").weak());
                    for f in ["9:16", "16:9", "1:1", "4:5"] {
                        if ui.selectable_label(self.lib.format == f, f).clicked() {
                            self.lib.format = f.into();
                        }
                    }
                });
                ui.add_space(12.0);
                let n = self.lib.selected_assets.len();
                let can = n > 0 && !self.lib.started;
                if ui
                    .add_enabled(
                        can,
                        egui::Button::new(
                            egui::RichText::new(format!("▶  ダンに作らせる（素材{n}件）"))
                                .size(14.0)
                                .color(egui::Color32::WHITE),
                        )
                        .min_size(egui::vec2(330.0, 40.0))
                        .rounding(8.0)
                        .fill(if can { UI_ACCENT } else { egui::Color32::from_gray(45) }),
                    )
                    .clicked()
                {
                    self.start_generation();
                }
                if n == 0 && !self.lib.started {
                    ui.label(
                        egui::RichText::new("← 左の素材をクリックして選んでください")
                            .small()
                            .color(egui::Color32::from_rgb(240, 190, 80)),
                    );
                }
                if self.lib.started {
                    ui.add_space(6.0);
                    ui.horizontal(|ui| {
                        ui.spinner();
                        ui.label("ダンが制作中…（数分。完成すると自動で開きます）");
                    });
                    for ev in &self.lib.events {
                        ui.label(egui::RichText::new(ev).small().weak());
                    }
                }
                if let Some(e) = &self.lib.error {
                    ui.colored_label(egui::Color32::from_rgb(255, 120, 120), e);
                }
                ui.add_space(14.0);
                ui.separator();
                ui.label(egui::RichText::new("素材を追加").strong());
                ui.label(
                    egui::RichText::new("動画ファイルをこのウィンドウにドラッグ&ドロップ")
                        .small()
                        .weak(),
                );
                ui.horizontal(|ui| {
                    ui.add(
                        egui::TextEdit::singleline(&mut self.lib.register_path)
                            .hint_text("またはPC内のパスを貼り付け")
                            .desired_width(250.0),
                    );
                    if ui.button("追加").clicked() && !self.lib.register_path.trim().is_empty() {
                        let body = serde_json::json!({
                            "room_id": self.room_id(),
                            "uri": self.lib.register_path.trim(),
                            "source_type": "local_path",
                            "make_proxy": true,
                        });
                        self.lib.register_path.clear();
                        self.lib_post("act", "/api/v1/production-assets/register".into(), body);
                    }
                });
            });
        });
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.add_space(6.0);
            ui.horizontal(|ui| {
                ui.heading("制作ライブラリ");
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
                        let (rect, resp) = ui.allocate_exact_size(egui::vec2(200.0, 62.0), egui::Sense::click());
                        let pp = ui.painter_at(rect);
                        let hov = resp.hovered();
                        pp.rect_filled(rect, 8.0, if hov { egui::Color32::from_rgb(42, 42, 48) } else { egui::Color32::from_rgb(32, 32, 37) });
                        pp.rect_stroke(rect, 8.0, egui::Stroke::new(1.0, if hov { UI_ACCENT } else { egui::Color32::from_gray(50) }));
                        let tshort: String = title.chars().take(14).collect();
                        pp.text(egui::pos2(rect.left() + 10.0, rect.top() + 14.0), egui::Align2::LEFT_CENTER,
                                format!("🎬 {tshort}"), egui::FontId::proportional(12.5), egui::Color32::from_gray(230));
                        pp.text(egui::pos2(rect.left() + 10.0, rect.bottom() - 15.0), egui::Align2::LEFT_CENTER,
                                format!("{nclips}クリップ・{:.0}:{:02}", dur as i64 / 60, dur as i64 % 60),
                                egui::FontId::proportional(10.0), egui::Color32::from_gray(140));
                        if hov {
                            pp.text(egui::pos2(rect.right() - 10.0, rect.center().y), egui::Align2::RIGHT_CENTER,
                                    "開く ▶", egui::FontId::proportional(11.0), UI_ACCENT);
                            ui.ctx().set_cursor_icon(egui::CursorIcon::PointingHand);
                        }
                        if resp.clicked() && !cid.is_empty() {
                            self.open_content(&cid);
                        }
                    }
                    if contents.is_empty() {
                        ui.label(egui::RichText::new("まだありません。素材を選んで右の「ダンに作らせる」から").weak());
                    }
                });
                // ---- user assets ----
                ui.add_space(12.0);
                let assets = self.lib.assets.clone();
                let (mine, generated): (Vec<_>, Vec<_>) = assets
                    .iter()
                    .partition(|a| a.get("source_type").and_then(|v| v.as_str()) != Some("generated"));
                ui.label(egui::RichText::new("あなたの素材").strong().size(13.0));
                ui.label(egui::RichText::new("クリックで選択 → 右の「ダンに作らせる」").weak().small());
                ui.add_space(2.0);
                ui.horizontal_wrapped(|ui| {
                    for a in &mine {
                        self.asset_card(ui, a);
                    }
                    if mine.is_empty() {
                        ui.label(egui::RichText::new("動画ファイルをこのウィンドウにドロップして追加").weak());
                    }
                });
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
        // drag & drop: local files register by path (no upload roundtrip needed)
        let dropped: Vec<std::path::PathBuf> =
            ctx.input(|i| i.raw.dropped_files.iter().filter_map(|f| f.path.clone()).collect());
        for pth in dropped {
            let body = serde_json::json!({
                "room_id": self.room_id(),
                "uri": pth.to_string_lossy().replace(char::from(92), "/"),
                "source_type": "local_path",
                "make_proxy": true,
            });
            self.lib_post("act", "/api/v1/production-assets/register".into(), body);
        }
        ctx.request_repaint_after(std::time::Duration::from_millis(300));
    }
}

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.absorb_lib();
        if self.screen == Screen::Library {
            self.library_ui(ctx);
            return;
        }
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

        // edit keys: S=split, Del=delete, Ctrl+Z/Y=undo/redo
        if ctx.input(|i| i.key_pressed(egui::Key::S) && !i.modifiers.ctrl) {
            self.split_at_playhead();
        }
        if ctx.input(|i| i.key_pressed(egui::Key::F) && !i.modifiers.ctrl) {
            self.freeze_at_playhead();
        }
        if ctx.input(|i| i.key_pressed(egui::Key::E) && !i.modifiers.ctrl) {
            self.toggle_popout();
        }
        if ctx.input(|i| i.key_pressed(egui::Key::P) && !i.modifiers.ctrl) && !ctx.wants_keyboard_input() {
            self.preview_fullscreen = !self.preview_fullscreen;
            ctx.send_viewport_cmd(egui::ViewportCommand::Fullscreen(self.preview_fullscreen));
            self.push_req(false);
        }
        if ctx.input(|i| i.key_pressed(egui::Key::L) && !i.modifiers.ctrl) && !ctx.wants_keyboard_input() {
            self.cycle_playback_speed();
        }
        self.poll_popout_bakes();
        if ctx.input(|i| i.key_pressed(egui::Key::Delete) || i.key_pressed(egui::Key::Backspace)) {
            let force_ripple = ctx.input(|i| i.modifiers.shift);
            self.delete_selected(force_ripple);
        }
        if ctx.input(|i| i.modifiers.ctrl && i.key_pressed(egui::Key::D)) && !self.selected.is_empty()
        {
            let ids = edits::expand_links(&self.doc.raw, &self.selected);
            let salt = std::process::id() as u64 ^ (self.t * 1000.0) as u64;
            self.apply_edit(true, move |raw| edits::duplicate_clips(raw, &ids, salt));
            self.toast("複製しました（右に空きが無い場合は別レーンの同じ時刻）");
        }
        if ctx.input(|i| i.modifiers.ctrl && i.key_pressed(egui::Key::A)) {
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
        if ctx.input(|i| i.modifiers.ctrl && i.key_pressed(egui::Key::Z)) {
            self.do_undo();
        }
        if ctx.input(|i| i.modifiers.ctrl && i.key_pressed(egui::Key::Y)) {
            self.do_redo();
        }
        if let Some(at) = self.save_at {
            if Instant::now() >= at {
                self.save_at = None;
                if let Err(e) = edits::save(&self.doc.raw, &self.doc.contents_path) {
                    eprintln!("save: {e:#}");
                }
            }
        }

        if ctx.input(|i| i.key_pressed(egui::Key::Space)) {
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
                if lvl >= 4 || t0.elapsed().as_millis() > 700 {
                    self.resume_pending = None;
                    self.playing = true;
                    self.push_req(false);
                }
            }
        }
        // Home/End = timeline start/end, +/- = zoom around the playhead
        if ctx.input(|i| i.key_pressed(egui::Key::Home)) {
            self.t = 0.0;
            self.playing = false;
            self.resume_pending = None;
            self.push_req(false);
        }
        if ctx.input(|i| i.key_pressed(egui::Key::End)) {
            self.t = self.dur;
            self.playing = false;
            self.resume_pending = None;
            self.push_req(false);
        }
        for (key, dir) in [(egui::Key::Plus, 1.0f32), (egui::Key::Equals, 1.0), (egui::Key::Minus, -1.0)] {
            if ctx.input(|i| i.key_pressed(key)) {
                let old_pps = self.pps;
                self.pps = (self.pps * (1.0 + dir * 0.25)).clamp(1.0, 400.0);
                // keep the playhead visually anchored while zooming
                self.scroll_x = ((self.t as f32) * self.pps
                    - ((self.t as f32) * old_pps - self.scroll_x))
                    .max(0.0);
            }
        }
        if ctx.input(|i| i.key_pressed(egui::Key::F1) || i.key_pressed(egui::Key::Questionmark)) {
            self.show_help = !self.show_help;
        }
        // frame step while paused (Filmora parity: arrow keys = +-1 SOURCE frame of the
        // clip under the playhead; global-grid fallback when no clip/sidecar)
        if !self.playing {
            if ctx.input(|i| i.key_pressed(egui::Key::ArrowRight)) {
                self.step_once(1.0);
            }
            if ctx.input(|i| i.key_pressed(egui::Key::ArrowLeft)) {
                self.step_once(-1.0);
            }
        }
        self.underruns = self.shared.underruns.load(Ordering::Relaxed);
        if self.playing {
            let c = f64::from_bits(self.shared.clock_bits.load(Ordering::Relaxed));
            // the audio clock re-anchors a beat after a seek/play request — until it does,
            // showing it would flash the playhead bar back to the OLD position
            if (c - self.t).abs() < 0.3 || self.last_push.elapsed().as_secs_f32() > 1.2 {
                self.t = c;
            }
            if self.t >= self.dur - 0.05 {
                self.playing = false;
                self.push_req(false);
            }
        }

        // upload the newest published frame (the media thread never blocks on us)
        {
            let f = self.shared.frame.lock().unwrap();
            if f.seq != self.last_seq && f.rgba.len() == (CANVAS_W * CANVAS_H * 4) as usize {
                self.last_seq = f.seq;
                self.comp_ms = f.comp_ms;
                self.comp_max = f.comp_max;
                self.gap_max = f.gap_max;
                self.quality = f.quality;
                let img = egui::ColorImage::from_rgba_unmultiplied(
                    [CANVAS_W as usize, CANVAS_H as usize],
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
                            let s1 = c.source_start + (c.timeline_end - c.timeline_start);
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
        // drag&drop import: dropped video files become assets + a linked A/V clip pair at
        // the playhead (registered in assets.json so Dan/web/export see the same material)
        let dropped: Vec<std::path::PathBuf> = ctx.input(|i| {
            i.raw.dropped_files.iter().filter_map(|f| f.path.clone()).collect()
        });
        if !dropped.is_empty() {
            for p in dropped {
                let ext = p.extension().and_then(|e| e.to_str()).unwrap_or("").to_lowercase();
                if !["mp4", "mov", "mkv", "webm", "m4v"].contains(&ext.as_str()) {
                    continue;
                }
                if let Err(e) = self.import_file(&p) {
                    eprintln!("import: {e:#}");
                }
            }
        }

        self.poll_export();
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
                    .selectable_label(self.blur_mode, "◱ ぼかし")
                    .on_hover_text("プレビュー上をドラッグしてぼかし/モザイクの範囲を指定")
                    .clicked()
                {
                    self.blur_mode = !self.blur_mode;
                    self.blur_drag = None;
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
                            let (rect, resp) =
                                ui.allocate_exact_size(egui::vec2(250.0, 60.0), egui::Sense::click());
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
                            ui.add_space(3.0);
                        }
                    });
                });
                if ui
                    .selectable_label(self.revise_open, "🤖 ダンに指示")
                    .on_hover_text("この動画への修正指示を言葉で送る（例: 冒頭をもっとテンポ良く）")
                    .clicked()
                {
                    self.revise_open = !self.revise_open;
                    if self.revise_open && self.lib.assets.is_empty() {
                        self.lib_refresh();
                    }
                }
                let exporting = self.export_job.is_some();
                if ui
                    .add_enabled(!exporting, egui::Button::new("📤 書き出し"))
                    .clicked()
                {
                    self.start_export();
                }
                if exporting {
                    ui.spinner();
                }
                if let Some(st) = &self.export_status {
                    ui.label(st.clone());
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
        egui::CentralPanel::default()
            .frame(egui::Frame::none().fill(egui::Color32::from_gray(10)))
            .show(ctx, |ui| {
                let avail = ui.available_size();
                if let Some(tex) = self.tex.clone() {
                    let (cw, ch) = (CANVAS_W as f32, CANVAS_H as f32);
                    let scale = (avail.x / cw).min(avail.y / ch);
                    let size = egui::vec2(cw * scale, ch * scale);
                    ui.centered_and_justified(|ui| {
                        let resp = ui
                            .add(egui::Image::new((tex.id(), size)))
                            .interact(egui::Sense::click_and_drag());
                        if self.blur_mode {
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
                                        let t = self.displayed_t();
                                        let salt = self.salt;
                                        self.salt += 1;
                                        self.apply_edit(true, move |raw| {
                                            edits::add_effect_clip(raw, t, 3.0, (fx, fy, fw, fh), "mosaic", salt)
                                        });
                                        self.push_req(false);
                                        self.blur_mode = false;
                                        self.toast("モザイクを追加しました（右パネルで種類・時間を調整）");
                                    }
                                }
                            }
                        } else {
                            self.preview_inspector(ui, &resp);
                        }
                        // captions: active caption clips drawn over the frame (white bold with
                        // dark outline, bottom-centre — the export bakes the full styling
                        // server-side; this is the live view)
                        let t = self.t;
                        let active: Vec<(String, String)> = self
                            .doc
                            .seq
                            .tracks
                            .iter()
                            .filter(|tr| tr.kind == "caption" && !tr.hidden)
                            .flat_map(|tr| tr.clips.iter())
                            .filter(|c| t >= c.timeline_start && t < c.timeline_end)
                            .filter_map(|c| c.text.clone().map(|txt| (c.id.clone(), txt)))
                            .collect();
                        // designed captions: draw the server-rendered PNG (export parity);
                        // fall back to plain outlined text until it lands on disk
                        let mut texts: Vec<String> = Vec::new();
                        for (cid, txt) in &active {
                            let Some(key) = self.cap_keys.get(cid).cloned() else {
                                texts.push(txt.clone());
                                continue;
                            };
                            if !self.cap_tex.contains_key(&key) {
                                let due = self
                                    .cap_probe
                                    .get(&key)
                                    .map(|at| at.elapsed().as_millis() > 1000)
                                    .unwrap_or(true);
                                if due {
                                    self.cap_probe.insert(key.clone(), Instant::now());
                                    let p = format!("{}/caption-cache/{key}.png", self.doc.asset_dir);
                                    if let Ok(bytes) = std::fs::read(&p) {
                                        if let Ok(img) = image::load_from_memory(&bytes) {
                                            let rgba = img.to_rgba8();
                                            let (w, h) = (rgba.width() as usize, rgba.height() as usize);
                                            let tex = ui.ctx().load_texture(
                                                format!("cap_{key}"),
                                                egui::ColorImage::from_rgba_unmultiplied([w, h], &rgba),
                                                egui::TextureOptions::LINEAR,
                                            );
                                            self.cap_tex.insert(key.clone(), tex);
                                        }
                                    }
                                }
                            }
                            match self.cap_tex.get(&key) {
                                Some(tex) => {
                                    // the PNG is canvas-sized: map it onto the letterboxed
                                    // VIDEO rect, not the whole panel
                                    let vid = egui::Rect::from_center_size(resp.rect.center(), size);
                                    let p = ui.painter_at(vid);
                                    p.image(
                                        tex.id(),
                                        vid,
                                        egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0)),
                                        egui::Color32::WHITE,
                                    );
                                }
                                None => texts.push(txt.clone()),
                            }
                        }
                        if !texts.is_empty() {
                            let p = ui.painter_at(resp.rect);
                            let fsz = (size.y * 0.032).max(12.0);
                            let pos = egui::pos2(
                                resp.rect.center().x,
                                resp.rect.bottom() - size.y * 0.10,
                            );
                            let text = texts.join(chr_nl());
                            let font = egui::FontId::proportional(fsz);
                            for (dx, dy) in [(-1.5, 0.0), (1.5, 0.0), (0.0, -1.5), (0.0, 1.5)] {
                                p.text(
                                    pos + egui::vec2(dx, dy),
                                    egui::Align2::CENTER_BOTTOM,
                                    &text,
                                    font.clone(),
                                    egui::Color32::BLACK,
                                );
                            }
                            p.text(pos, egui::Align2::CENTER_BOTTOM, &text, font, egui::Color32::WHITE);
                        }
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
            let mut open = self.revise_open;
            let mut sent = false;
            egui::Window::new("ダンに指示")
                .open(&mut open)
                .resizable(false)
                .default_width(340.0)
                .show(ctx, |ui| {
                    ui.label("この動画をどう直してほしいか、言葉で指示してください");
                    ui.add(
                        egui::TextEdit::multiline(&mut self.revise_text)
                            .desired_rows(4)
                            .desired_width(f32::INFINITY)
                            .hint_text("例: 冒頭の自己紹介を短くして、テロップを大きめに"),
                    );
                    ui.add_space(4.0);
                    let can = !self.revise_text.trim().is_empty() && !self.lib.started;
                    if ui
                        .add_enabled(can, egui::Button::new("▶ ダンに修正させる").min_size(egui::vec2(320.0, 28.0)))
                        .clicked()
                    {
                        sent = true;
                    }
                    if self.lib.started {
                        ui.horizontal(|ui| {
                            ui.spinner();
                            ui.label("ダンが修正中…（完成すると自動で反映されます）");
                        });
                        for ev in &self.lib.events {
                            ui.label(egui::RichText::new(ev).small().weak());
                        }
                    }
                    if let Some(e) = &self.lib.error {
                        ui.colored_label(egui::Color32::from_rgb(255, 120, 120), e);
                    }
                });
            self.revise_open = open;
            if sent {
                self.playing = false;
                self.push_req(false);
                self.start_revision();
                self.revise_text.clear();
            }
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
        if let Some((cid, mut buf)) = self.caption_edit.clone() {
            let mut save = false;
            let mut cancel = false;
            egui::Window::new("テロップ編集")
                .collapsible(false)
                .anchor(egui::Align2::CENTER_CENTER, egui::vec2(0.0, 0.0))
                .show(ctx, |ui| {
                    ui.add(egui::TextEdit::multiline(&mut buf).desired_width(360.0).desired_rows(3));
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
            if save {
                let text = buf.clone();
                let id2 = cid.clone();
                self.apply_edit(true, move |raw| edits::set_text(raw, &id2, &text));
                self.caption_edit = None;
            } else if cancel {
                self.caption_edit = None;
            } else {
                self.caption_edit = Some((cid, buf));
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
        ctx.request_repaint();
    }
}


/// Positional CLI args (contents.json path, asset dir) end at the first `--flag`;
/// everything after belongs to flags and their values. A done:// deep link is a flag-like
/// launch too, not a path.
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
    // --dump-frame <t> <out.ppm>: headless compose of one timeline frame — deterministic
    // A/B verification (live matte path vs pv fallback) with no window and no user input
    if let Some(i) = args.iter().position(|a| a == "--dump-frame") {
        let t: f64 = args.get(i + 1).and_then(|v| v.parse().ok()).unwrap_or(0.0);
        let out = args.get(i + 2).cloned().unwrap_or_else(|| "frame.ppm".into());
        let contents = positional_args(&args).first().cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = positional_args(&args).get(1).cloned().unwrap_or_else(|| ROOM.to_string());
        let r = (|| -> anyhow::Result<()> {
            use anyhow::Context;
            let doc = model::Doc::load(&contents, &dir).context("doc load")?;
            let d3d = media::D3d::new().context("d3d")?;
            let mut pool = media::VideoPool::new();
            let mut comp = compositor::Compositor::new(&d3d, CANVAS_W, CANVAS_H).context("compositor")?;
            let mut masks: MaskMap = Default::default();
            while mask_build_pass(&doc, &d3d, &mut masks) {}
            let mut pts_maps: PtsMap = Default::default();
            while pts_load_pass(&doc, &mut pts_maps) {}
            let orig_q = std::env::var("NATIVE_DUMP_PROXY").map(|v| v.is_empty()).unwrap_or(true);
            compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, t, orig_q, false, true)
                .context("compose")?;
            let mut ppm = format!("P6\n{CANVAS_W} {CANVAS_H}\n255\n").into_bytes();
            for px in comp.rgba.chunks(4) {
                ppm.extend_from_slice(&px[..3]);
            }
            std::fs::write(&out, ppm)?;
            println!("dumped t={t} -> {out}");
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
        let d3d = media::D3d::new().unwrap();
        let mut pool = media::VideoPool::new();
        let mut comp = compositor::Compositor::new(&d3d, CANVAS_W, CANVAS_H).unwrap();
        let mut masks: MaskMap = Default::default();
        while mask_build_pass(&doc, &d3d, &mut masks) {}
        let mut pts_maps: PtsMap = Default::default();
        while pts_load_pass(&doc, &mut pts_maps) {}
        let mut t = t0v;
        let _ = compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, t, false, true, true);
        let b0 = Instant::now();
        let mut worst = 0f64;
        for _ in 0..60 {
            t += 0.33;
            let c0 = Instant::now();
            let _ = compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, t, false, true, true);
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
    if args.iter().any(|a| a == "--selftest-invariants") {
        let contents = positional_args(&args).first().cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = positional_args(&args).get(1).cloned().unwrap_or_else(|| ROOM.to_string());
        let doc = model::Doc::load(&contents, &dir).expect("doc");
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
            && (clip(&right_shrink, "b", "timeline_start") - 4.0).abs() < 0.001
            && (clip(&right_shrink, "aaud", "timeline_end") - 3.0).abs() < 0.001
            && (clip(&right_shrink, "baud", "timeline_start") - 4.0).abs() < 0.001
            && (clip(&right_shrink, "d", "timeline_start") - 4.0).abs() < 0.001;

        let mut live_left_drag = base.clone();
        edits::trim_clip_live_from(&mut live_left_drag, &["b".to_string()], true, 4.0, 5.0);
        let ok_live_left_drag = (clip(&live_left_drag, "a", "timeline_end") - 4.0).abs() < 0.001
            && (clip(&live_left_drag, "b", "timeline_start") - 5.0).abs() < 0.001
            && (clip(&live_left_drag, "b", "timeline_end") - 8.0).abs() < 0.001
            && (clip(&live_left_drag, "e", "timeline_start") - 8.0).abs() < 0.001
            && (clip(&live_left_drag, "b", "source_start") - 1.0).abs() < 0.001;

        edits::trim_clip_live_from(&mut live_left_drag, &["b".to_string()], true, 5.0, 4.0);
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
        edits::trim_clip_live_from(&mut live_left_grow_from_handle, &["b".to_string()], true, 4.0, 3.0);
        let ok_live_left_grow_erases_overlap = (clip(&live_left_grow_from_handle, "a", "timeline_start") - 0.0).abs() < 0.001
            && (clip(&live_left_grow_from_handle, "a", "timeline_end") - 3.0).abs() < 0.001
            && (clip(&live_left_grow_from_handle, "b", "timeline_start") - 3.0).abs() < 0.001
            && (clip(&live_left_grow_from_handle, "b", "timeline_end") - 8.0).abs() < 0.001
            && (clip(&live_left_grow_from_handle, "e", "timeline_start") - 8.0).abs() < 0.001
            && (clip(&live_left_grow_from_handle, "b", "source_start") - 0.0).abs() < 0.001;

        let mut magnetic_left_shrink = base.clone();
        edits::trim_clip_live_from(&mut magnetic_left_shrink, &["b".to_string()], true, 4.0, 5.0);
        edits::settle_left_trim(&mut magnetic_left_shrink, &["b".to_string()]);
        let ok_mag_left_shrink = (clip(&magnetic_left_shrink, "a", "timeline_end") - 4.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "b", "timeline_start") - 5.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "b", "timeline_end") - 8.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "b", "source_start") - 1.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "e", "timeline_start") - 8.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "g", "timeline_start") - 8.2).abs() < 0.001
            && (clip(&magnetic_left_shrink, "aaud", "timeline_end") - 4.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "baud", "timeline_start") - 5.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "baud", "timeline_end") - 8.0).abs() < 0.001
            && (clip(&magnetic_left_shrink, "baud", "source_start") - 1.0).abs() < 0.001;

        edits::trim_clip_live_from(&mut magnetic_left_shrink, &["b".to_string()], true, 5.0, 4.0);
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
        edits::trim_clip_live_from(&mut main_magnet_off, &["b".to_string()], true, 4.0, 5.0);
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
        edits::trim_clip_live_from(&mut main_off_left_grow, &["b".to_string()], true, 4.0, 3.0);
        let ok_main_off_left_grow_erases_overlap = (clip(&main_off_left_grow, "a", "timeline_end") - 3.0).abs() < 0.001
            && (clip(&main_off_left_grow, "b", "timeline_start") - 3.0).abs() < 0.001
            && (clip(&main_off_left_grow, "b", "timeline_end") - 8.0).abs() < 0.001
            && (clip(&main_off_left_grow, "e", "timeline_start") - 8.0).abs() < 0.001
            && (clip(&main_off_left_grow, "b", "source_start") - 0.0).abs() < 0.001;

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
            && ok_live_left_grow_erases_overlap
            && ok_mag_left_shrink
            && ok_mag_left_restore
            && ok_main_off_left_shrink_gap
            && ok_main_off_left_grow_erases_overlap
            && ok_free_shrink
            && ok_free_grow;
        println!(
            "TRIM {} right_shrink_gap={ok_right_shrink_gap} live_left_drag={ok_live_left_drag} live_left_grow={ok_live_left_grow} live_left_grow_erases_overlap={ok_live_left_grow_erases_overlap} magnetic_left_shrink={ok_mag_left_shrink} magnetic_left_restore={ok_mag_left_restore} main_off_left_shrink_gap={ok_main_off_left_shrink_gap} main_off_left_grow_erases_overlap={ok_main_off_left_grow_erases_overlap} free_shrink={ok_free_shrink} free_grow={ok_free_grow}",
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
    let opts = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1280.0, 940.0])
            .with_title("done Studio"),
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
            vis.widgets.active.bg_fill = egui::Color32::from_rgb(0, 120, 96);
            vis.widgets.active.weak_bg_fill = egui::Color32::from_rgb(0, 120, 96);
            vis.selection.bg_fill = egui::Color32::from_rgb(0, 122, 98);
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
                st.spacing.button_padding = egui::vec2(10.0, 5.0);
                st.spacing.item_spacing = egui::vec2(7.0, 6.0);
            });
            let mut app = App::new(&contents, &dir)
                .map_err(|e| -> Box<dyn std::error::Error + Send + Sync> { format!("{e:#}").into() })?;
            // bare launch (no explicit contents arg): open the LIBRARY (assets ->
            // generation -> open), the full production entry point
            let all: Vec<String> = std::env::args().collect();
            let explicit = !positional_args(&all).is_empty();
            if !explicit {
                app.screen = Screen::Library;
                app.lib_refresh();
            }
            // --import <file>: same code path as drag&drop (also our self-test hook)
            let args: Vec<String> = std::env::args().collect();
            if let Some(i) = args.iter().position(|a| a == "--import") {
                if let Some(f) = args.get(i + 1) {
                    if let Err(e) = app.import_file(std::path::Path::new(f)) {
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
