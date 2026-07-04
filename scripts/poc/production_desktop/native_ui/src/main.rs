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
const CANVAS_W: u32 = 1080;
const CANVAS_H: u32 = 1920;

#[derive(Clone)]
struct Req {
    t: f64,
    playing: bool,
    scrubbing: bool,
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
    loop {
        let (playing, t_req, gen) = {
            let r = shared.req.lock().unwrap();
            (r.playing, r.t, r.gen)
        };
        let doc: Arc<model::Doc> = shared.doc.lock().unwrap().clone();
        if playing != was_playing {
            if playing {
                let t0 = std::time::Instant::now();
                while shared.ring_level.load(Ordering::Relaxed) < 4
                    && t0.elapsed().as_millis() < 400
                {
                    std::thread::sleep(std::time::Duration::from_millis(5));
                }
                let _ = audio.start_at(t_req);
                shared.clock_bits.store(t_req.to_bits(), Ordering::Relaxed);
            } else {
                audio.stop();
            }
            was_playing = playing;
            last_gen = gen;
        } else if playing && gen != last_gen {
            last_gen = gen;
            let cur = f64::from_bits(shared.clock_bits.load(Ordering::Relaxed));
            if (t_req - cur).abs() > 0.3 {
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
                    let _ = audio.start_at(t_req);
                    shared.clock_bits.store(t_req.to_bits(), Ordering::Relaxed);
                    eprintln!(
                        "JUMPGATE {:.0}ms ring={}",
                        t0.elapsed().as_secs_f32() * 1000.0,
                        shared.ring_level.load(Ordering::Relaxed)
                    );
                }
            }
        }
        if playing {
            let _ = audio.fill(&doc);
            let c = audio.clock();
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
    Trim { ids: Vec<String>, left: bool },
}

/// Olive-style composed-frame cache: finished timeline frames (ORIGINAL quality, 30fps
/// grid) LZ4-compressed in RAM. Scrub/jump/playback over cached spans just decompress
/// (~3-6ms) instead of composing (30-100ms+). Conservative correctness: ANY document edit
/// clears the whole cache — a stale frame is structurally impossible. Filled during
/// paused idle (playhead outward) and opportunistically from playback production.
struct FrameCache {
    frames: std::collections::HashMap<i64, Vec<u8>>,
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
    fn get(&mut self, t: f64, out: &mut Vec<u8>) -> bool {
        if let Some(z) = self.frames.get(&Self::idx(t)) {
            if let Ok(raw) = lz4_flex::decompress_size_prepended(z) {
                out.clear();
                out.extend_from_slice(&raw);
                self.hits += 1;
                return true;
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
        self.frames.insert(key, z);
        // over budget: evict farthest-from-playhead first
        while self.bytes > self.budget {
            let ph = Self::idx(playhead);
            let Some((&far, _)) = self.frames.iter().max_by_key(|(k, _)| (**k - ph).abs()) else {
                break;
            };
            if let Some(z) = self.frames.remove(&far) {
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
        if tr.kind != "video" && tr.kind != "overlay" {
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
        if tr.kind != "video" && tr.kind != "overlay" {
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
    let src_t = c.source_start + (t - c.timeline_start);
    let vs = pool.get(d3d, &p2, 0, false, src_t)?;
    if fast {
        let _ = vs.ensure_frame_scrub(d3d, src_t, 12.0)?;
    } else {
        vs.ensure_frame(d3d, src_t)
            .map_err(|e| e.context(format!("plain-pip {} src_t={src_t:.2}", vs.name)))?;
    }
    let (tex, wh) = (vs.bgra.clone(), (vs.width, vs.height));
    comp.draw(d3d, &tex, wh, (bb.x, bb.y, bb.width, bb.height), true, None)?;
    Ok(Some(p2))
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
                let src_t = c.source_start + (t - c.timeline_start);
                let mt_path = doc.rel_path(&format!("popout-cache/{key}.mt.mp4"));
                let mt_t = off + (t - c.timeline_start);
                // ONE pool.get per stream: a second get in the same compose sees the
                // instance as busy-this-frame and OPENS A SPARE (~50ms + an empty texture)
                // — that was 110ms/frame of the pop-out scrub cost
                let otex = {
                    let s = pool.get(d3d, &opath, 0, false, src_t)?;
                    if fast {
                        if Instant::now() < f_deadline {
                            exact &= s.ensure_frame_scrub(d3d, src_t, 12.0)?;
                        } else {
                            exact = false; // out of budget — stale person, refined at rest
                        }
                    } else {
                        s.ensure_frame(d3d, src_t)
                            .map_err(|e| e.context(format!("live-orig {} src_t={src_t:.2}", s.name)))?;
                    }
                    s.bgra.clone()
                };
                let mut mt_tex = Vec::with_capacity(2);
                for stream in [MT_PERSON, MT_SHADOW] {
                    let s = pool.get(d3d, &mt_path, stream, true, mt_t)?;
                    if fast {
                        if Instant::now() < f_deadline {
                            exact &= s.ensure_frame_scrub(d3d, mt_t, 8.0)?;
                        } else {
                            exact = false;
                        }
                    } else {
                        s.ensure_frame(d3d, mt_t)
                            .map_err(|e| e.context(format!("live-mt {} src_t={mt_t:.2}", s.name)))?;
                    }
                    mt_tex.push(s.bgra.clone());
                }
                let stex = mt_tex.pop().unwrap();
                let ptex = mt_tex.pop().unwrap();
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
                let src_t = off + (t - c.timeline_start);
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
            let mut src_t = c.source_start + (t - c.timeline_start);
            if !fast && original {
                src_t = snap_src_t(pts_maps, aid, src_t);
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
            comp.draw(d3d, &tex, wh, (b.x, b.y, b.width, b.height), true, None)?;
            used.push(path);
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
        if tr.kind != "video" && tr.kind != "overlay" {
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
        let worked = if let Some((key, off)) = c.popout_key() {
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
        };
        if worked {
            return; // one slice per loop — the ring keeps breathing
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
        if tr.kind != "video" && tr.kind != "overlay" {
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
        if tr.kind != "video" && tr.kind != "overlay" {
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
    let tok = args
        .iter()
        .position(|a| a == "--token")
        .and_then(|i| args.get(i + 1).cloned())
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
        if tr.kind != "video" && tr.kind != "overlay" {
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
        if tr.kind != "video" && tr.kind != "overlay" {
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
            f.quality = "original";
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
        let mut scrub_win: Vec<f32> = Vec::new();
        let mut scrub_t0 = Instant::now();
        let mut scrub_exact = true; // last scrub compose reached the exact frame
        let mut masks: MaskMap = Default::default();
        let mut pts_maps: PtsMap = Default::default();
        let mut fcache = FrameCache::new();
        let mut prev_was_compose = false;
        // Look-ahead ring: timeline frames composed AHEAD of the playhead on a fixed 30fps
        // grid. Presentation picks from the ring and NEVER waits for a decode — GOP walks
        // and source switches are paid in the ring's future (the Filmora mechanism).
        const STEP: f64 = 1.0 / 30.0;
        const RING_DEPTH: usize = 12; // ~400ms of slack
        loop {
            let hb0 = Instant::now();
            let doc: Arc<model::Doc> = shared.doc.lock().unwrap().clone();
            let ptr = Arc::as_ptr(&doc) as usize;
            if ptr != last_doc_ptr {
                last_doc_ptr = ptr;
                warm_done = false;
                fcache.clear(); // edited: NEVER show a stale composed frame
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
                        if let Ok(_snap) = compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, r.t, true, true, true) {
                            seq += 1;
                            let mut f = shared.frame.lock().unwrap();
                            f.rgba.clear();
                            f.rgba.extend_from_slice(&comp.rgba);
                            f.seq = seq;
                            f.quality = "original";
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
                if len < RING_DEPTH && next_t <= dur {
                    let t0 = Instant::now();
                    // cache hit = decompress instead of compose (jump refills become ~instant)
                    let mut cached_buf: Vec<u8> = Vec::new();
                    let from_cache = fcache.get(next_t, &mut cached_buf);
                    let res = if from_cache {
                        Ok((Vec::new(), true))
                    } else {
                        compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, next_t, true, false, false)
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
                                fcache.insert(next_t - STEP, &comp.rgba, t);
                            }
                            prev_was_compose = !from_cache;
                            ms_push = p0.elapsed().as_secs_f32() * 1000.0;
                            if len >= 8 {
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
                if fcache.get(t, &mut buf) {
                    seq += 1;
                    let mut f = shared.frame.lock().unwrap();
                    f.rgba = buf;
                    f.seq = seq;
                    f.comp_ms = 0.0;
                    f.quality = "original";
                    scrub_exact = true;
                    last_gen = r.gen;
                    last_t = t;
                    false // handled — skip the compose branch
                } else {
                    true
                }
            } {
                // Scrub decodes the HIGH-QUALITY proxy (long side 1920, CRF19, GOP15 —
                // indistinguishable from the original at pane size, seeks in ~20ms so the
                // preview stays glued to the finger); the settle/refine pass and playback
                // use the original. This is Filmora's actual mechanism — its 4K scrubbing
                // runs on auto-proxies too, ours were just 406x720 CRF28 mush before.
                let original = !r.scrubbing;
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
                            f.quality = "original";
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
                    if fcache.get(t, &mut buf) {
                        seq += 1;
                        let mut f = shared.frame.lock().unwrap();
                        f.rgba = buf;
                        f.seq = seq;
                        f.quality = "original";
                        scrub_exact = true;
                        std::thread::sleep(std::time::Duration::from_millis(2));
                        continue;
                    }
                    // finger resting mid-drag on a long-GOP spot: keep refining toward the
                    // exact frame, one budget slice per pass (converges like Filmora's
                    // "stop and the picture sharpens to the real frame")
                    if let Ok((_, ex)) = compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, t, true, true, true) {
                        scrub_exact = ex;
                        seq += 1;
                        let mut f = shared.frame.lock().unwrap();
                        f.rgba.clear();
                        f.rgba.extend_from_slice(&comp.rgba);
                        f.seq = seq;
                        f.quality = "original";
                    } else {
                        scrub_exact = true; // failed — stop hammering
                    }
                } else {
                    // interaction in flight: keep this thread FREE so the next scrub frame
                    // starts the instant it arrives
                    std::thread::sleep(std::time::Duration::from_millis(2));
                }
            } else if shared.ring.lock().unwrap().len() < RING_DEPTH {
                // FIRST: pre-build the ring ahead of the frozen playhead so pressing play
                // is instant — compose opens the decoders it needs on demand, so this must
                // not wait behind the full warm pass (59 files ≈ tens of seconds)
                let next_t = {
                    let rg = shared.ring.lock().unwrap();
                    rg.back().map(|(ft, _)| ft + STEP).unwrap_or_else(|| (t / STEP).floor() * STEP)
                };
                if next_t <= dur {
                    if let Ok(u2) = compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, next_t, true, false, false) {
                        let mut rg = shared.ring.lock().unwrap();
                        rg.push_back((next_t, comp.rgba.clone()));
                        shared.ring_level.store(rg.len(), Ordering::Relaxed);
                        let _ = u2;
                    }
                } else {
                    std::thread::sleep(std::time::Duration::from_millis(2));
                }
            } else if mask_build_pass(&doc, &d3d, &mut masks) {
                // pop-out card masks for the live matte path — one σ26 blur per slice.
                // BEFORE the warm pass: few and quick, and without them pop-outs render
                // from the stale pv twin
            } else if pts_load_pass(&doc, &mut pts_maps) {
                // frame-pts tables for exact proxy<->original settling
            } else if !warm_done {
                // THEN: open every decoder the rest of the timeline needs (a cold open
                // mid-play is a 100-200ms media-thread stall = visible gap)
                warm_done = warm_open_pass(&doc, &d3d, &mut pool, &masks);
            } else if shared.aux_req.lock().unwrap().is_empty() && {
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
                    if let Ok(_) = compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, ft, true, false, true) {
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
    recut_open: bool,
    recut_thresh: f32,
    recut_lead: f32,
    recut_tail: f32,
    recut_busy: bool,
    doc: Arc<model::Doc>,
    shared: Arc<Shared>,
    selected: Vec<String>,
    drag: Drag,
    undo: Vec<serde_json::Value>,
    redo: Vec<serde_json::Value>,
    save_at: Option<Instant>,
    salt: u64,
    thumbs: std::collections::HashMap<(String, i64), egui::TextureHandle>,
    peaks: std::collections::HashMap<String, (f64, Vec<f32>)>,
    aux_ver: u64,
    tex: Option<egui::TextureHandle>,
    last_seq: u64,
    playing: bool,
    show_help: bool,
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
        let doc = Arc::new(model::Doc::load(contents, dir)?);
        let dur = doc.duration();
        let shared = Arc::new(Shared {
            req: Mutex::new(Req { t: 0.0, playing: false, scrubbing: false, gen: 0 }),
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
                .name("presenter".into())
                .spawn(move || presenter_thread(shared))?;
        }
        Ok(Self {
            screen: Screen::Editor,
            lib: Library { format: "9:16".into(), ..Default::default() },
            lib_poll: Instant::now(),
            lib_sink: Default::default(),
            lib_gen_stash: None,
            recut_open: false,
            recut_thresh: 0.45,
            recut_lead: 0.06,
            recut_tail: 0.10,
            recut_busy: false,
            doc,
            shared,
            selected: Vec::new(),
            drag: Drag::None,
            undo: Vec::new(),
            redo: Vec::new(),
            save_at: None,
            thumbs: Default::default(),
            peaks: Default::default(),
            aux_ver: 0,
            salt: std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0),
            tex: None,
            last_seq: 0,
            playing: false,
            show_help: false,
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
    fn apply_edit(&mut self, snapshot: bool, f: impl FnOnce(&mut serde_json::Value)) {
        if snapshot {
            self.undo.push(self.doc.raw.clone());
            if self.undo.len() > 60 {
                self.undo.remove(0);
            }
            self.redo.clear();
        }
        let mut raw = self.doc.raw.clone();
        f(&mut raw);
        match model::Doc::from_raw(raw, &self.doc.contents_path, &self.doc.asset_dir) {
            Ok(nd) => {
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
        }
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
                    self.undo.push(self.doc.raw.clone());
                    self.redo.clear();
                    self.inspect_drag = Some((c.id.clone(), ci as u8 + 1, pt, b));
                } else if bx.contains(pt) {
                    self.undo.push(self.doc.raw.clone());
                    self.redo.clear();
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
        *r = Req { t: self.t, playing: self.playing, scrubbing, gen: self.gen };
    }

    fn timeline_ui(&mut self, ui: &mut egui::Ui) {
        const GUTTER: f32 = 64.0; // lane headers
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

        let ruler_h = 18.0;
        p.rect_filled(
            egui::Rect::from_min_max(body.min, egui::pos2(body.right(), body.top() + ruler_h)),
            0.0,
            egui::Color32::from_gray(26),
        );
        let step_s = (60.0 / self.pps).ceil().max(1.0);
        let mut s = (self.scroll_x / self.pps / step_s).floor() * step_s;
        while s * self.pps - self.scroll_x < w {
            let x = body.left() + s * self.pps - self.scroll_x;
            if x >= body.left() {
                p.line_segment(
                    [egui::pos2(x, body.top()), egui::pos2(x, body.top() + ruler_h)],
                    egui::Stroke::new(1.0, egui::Color32::from_gray(90)),
                );
                p.text(
                    egui::pos2(x + 3.0, body.top() + 2.0),
                    egui::Align2::LEFT_TOP,
                    format!("{:02}:{:02}", (s as i64) / 60, (s as i64) % 60),
                    egui::FontId::proportional(10.0),
                    egui::Color32::from_gray(150),
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
                self.undo.push(self.doc.raw.clone());
                self.redo.clear();
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
            // lane header: just a layer number — lanes have no fixed roles, upper = front
            p.text(
                egui::pos2(rect.left() + 6.0, y0 + lane_h * 0.5),
                egui::Align2::LEFT_CENTER,
                if tr.kind == "audio" {
                    format!("A{}", ti + 1)
                } else {
                    format!("{}", ti + 1)
                },
                egui::FontId::proportional(11.0),
                egui::Color32::from_gray(140),
            );
            p.line_segment(
                [egui::pos2(rect.left(), y0 + lane_h + 1.5), egui::pos2(rect.right(), y0 + lane_h + 1.5)],
                egui::Stroke::new(1.0, egui::Color32::from_gray(28)),
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
                p.rect_filled(r, 3.0, color);
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
                    _ => {
                        if is_pop && r.width() > 56.0 {
                            p.text(
                                egui::pos2(r.left() + 4.0, r.top() + 6.0),
                                egui::Align2::LEFT_TOP,
                                "飛び出し",
                                egui::FontId::proportional(9.0),
                                egui::Color32::from_white_alpha(230),
                            );
                        }
                    }
                }
                if tr.kind != "audio" {
                    if let Some(aid) = c.asset_id.as_ref() {
                        // FILMSTRIP: each tile shows the actual source frame at its position
                        let tile_w = (r.height() * 16.0 / 9.0).max(8.0);
                        let mut x = x0.max(rect.left()); // start at the clip's true left edge
                        while x < r.right() {
                            let tt = c.source_start
                                + (((x - x0) / self.pps) as f64).max(0.0);
                            let b = (tt / THUMB_BUCKET_S) as i64;
                            let th = self
                                .thumbs
                                .get(&(aid.clone(), b))
                                .or_else(|| self.thumbs.get(&(aid.clone(), 0)));
                            if let Some(th) = th {
                                let tr2 = egui::Rect::from_min_max(
                                    egui::pos2(x, r.top()),
                                    egui::pos2((x + tile_w).min(r.right()), r.bottom()),
                                );
                                let frac = tr2.width() / tile_w;
                                p.image(
                                    th.id(),
                                    tr2,
                                    egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(frac, 1.0)),
                                    egui::Color32::from_white_alpha(210),
                                );
                            }
                            x += tile_w;
                        }
                    }
                }
                if tr.kind != "audio" && c.link_id.is_some() {
                    // unified A/V: waveform ribbon along the clip's bottom quarter
                    if let Some((spb, pk)) = c.asset_id.as_ref().and_then(|a| self.peaks.get(a)) {
                        let base_y = r.bottom() - 1.0;
                        let amp = (r.height() * 0.28).min(12.0);
                        let n = (r.width() as usize).max(1);
                        let mut pts: Vec<egui::Pos2> = Vec::with_capacity(n);
                        for i in 0..n {
                            let tt = c.source_start
                                + ((i as f32 / n as f32) * (c.timeline_end - c.timeline_start) as f32) as f64;
                            let idx = (tt / spb) as usize;
                            let v = pk.get(idx).copied().unwrap_or(0.0).min(1.0);
                            pts.push(egui::pos2(r.left() + i as f32, base_y - v * amp));
                        }
                        p.add(egui::Shape::line(
                            pts,
                            egui::Stroke::new(1.0, egui::Color32::from_rgba_unmultiplied(190, 255, 205, 170)),
                        ));
                    }
                }
                if tr.kind == "audio" {
                    if let Some((spb, pk)) = c.asset_id.as_ref().and_then(|a| self.peaks.get(a)) {
                        let mid = r.center().y;
                        let half = r.height() * 0.48;
                        let n = (r.width() as usize).max(1);
                        let mut pts: Vec<egui::Pos2> = Vec::with_capacity(n);
                        for i in 0..n {
                            let tt = c.source_start
                                + ((i as f32 / n as f32) * (c.timeline_end - c.timeline_start) as f32) as f64;
                            let idx = (tt / spb) as usize;
                            let v = pk.get(idx).copied().unwrap_or(0.0).min(1.0);
                            pts.push(egui::pos2(r.left() + i as f32, mid - v * half));
                        }
                        p.add(egui::Shape::line(pts, egui::Stroke::new(1.0, egui::Color32::from_rgb(20, 90, 40))));
                    }
                }
                let sel = self.selected.contains(&c.id);
                p.rect_stroke(
                    r,
                    3.0,
                    if sel {
                        egui::Stroke::new(2.0, egui::Color32::WHITE)
                    } else {
                        egui::Stroke::new(1.0, egui::Color32::from_gray(25))
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
                    if r.expand2(egui::vec2(5.0, 0.0)).contains(pt)
                        && ((pt.x - r.left()).abs() < 6.0 || (pt.x - r.right()).abs() < 6.0)
                    {
                        ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeHorizontal);
                    }
                }
                hits.push((r, c.id.clone()));
                clips_drawn += 1;
            }
        }

        let hx = body.left() + (self.t as f32) * self.pps - self.scroll_x;
        if hx >= body.left() && hx <= body.right() {
            p.line_segment(
                [egui::pos2(hx, body.top()), egui::pos2(hx, rect.bottom())],
                egui::Stroke::new(1.5, egui::Color32::from_rgb(240, 60, 60)),
            );
            // grab handle on the ruler
            p.add(egui::Shape::convex_polygon(
                vec![
                    egui::pos2(hx - 6.0, body.top()),
                    egui::pos2(hx + 6.0, body.top()),
                    egui::pos2(hx, body.top() + 11.0),
                ],
                egui::Color32::from_rgb(240, 60, 60),
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
                let hit = hits.iter().find(|(r, _)| r.expand2(egui::vec2(4.0, 0.0)).contains(pos));
                match hit {
                    Some((r, id)) => {
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
                        if !self.selected.contains(id) {
                            if ui.input(|i| i.modifiers.ctrl) {
                                self.selected.push(id.clone());
                            } else {
                                self.selected = vec![id.clone()];
                            }
                        }
                        let ids = edits::expand_links(&self.doc.raw, &self.selected);
                        if self.drag == Drag::None {
                            self.undo.push(self.doc.raw.clone());
                            self.redo.clear();
                            if (pos.x - r.left()).abs() < 6.0 {
                                self.drag = Drag::Trim { ids, left: true };
                            } else if (pos.x - r.right()).abs() < 6.0 {
                                self.drag = Drag::Trim { ids, left: false };
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
                        self.selected.clear();
                        self.drag = Drag::Scrub;
                        self.t = to_t(self.scroll_x, self.pps, pos.x).min(self.dur);
                        self.push_req(false);
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
                    Drag::Trim { ids, left } => {
                        let raw_t = to_t(self.scroll_x, self.pps, pos.x);
                        let nt = self.snap(raw_t, &ids);
                        self.snap_line = ((nt - raw_t).abs() > 1e-9).then_some(nt);
                        self.apply_edit(false, |raw| edits::trim_clip(raw, &ids, left, nt));
                    }
                    Drag::None => {}
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
        if resp.drag_stopped() {
            let prev = std::mem::replace(&mut self.drag, Drag::None);
            eprintln!(
                "DRAGSTOP prev={} hover={:?}",
                match &prev {
                    Drag::None => "none",
                    Drag::Scrub => "scrub",
                    Drag::Move { .. } => "move",
                    Drag::Trim { .. } => "trim",
                },
                self.hover_lane
            );
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

        // ---- bottom bar: zoom slider / fit / horizontal scrollbar ----
        ui.horizontal(|ui| {
            ui.add_space(4.0);
            if ui.small_button("全体").clicked() {
                self.pps = ((ui.available_width() - GUTTER - 40.0) / (self.dur.max(1.0) as f32)).clamp(1.0, 400.0);
                self.scroll_x = 0.0;
            }
            let mut z = self.pps.ln();
            let resp = ui.add(
                egui::Slider::new(&mut z, 1.0f32.ln()..=400.0f32.ln())
                    .show_value(false)
                    .text("ズーム"),
            );
            if resp.changed() {
                // zoom around the playhead
                let anchor = (self.t as f32) * self.pps - self.scroll_x;
                self.pps = z.exp().clamp(1.0, 400.0);
                self.scroll_x = ((self.t as f32) * self.pps - anchor).max(0.0);
            }
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
        // claim any leftover space: under-reporting our size made the resizable panel
        // shrink back a few px every frame (the "drifts back after release" bug)
        ui.allocate_space(ui.available_size());
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
        // thumbnails from the room dir ({id}_thumb.jpg) — decoded once, cached
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
                    let ff = ["ffmpeg", "C:/Users/Owner/ffmpeg/bin/ffmpeg.exe", "C:/ffmpeg/bin/ffmpeg.exe"]
                        .into_iter()
                        .find(|f| *f == "ffmpeg" || std::path::Path::new(f).exists())
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
        egui::SidePanel::right("gen_panel").exact_width(340.0).show(ctx, |ui| {
            ui.add_space(8.0);
            ui.heading("新しく作る");
            ui.add_space(6.0);
            let presets = [
                "映像→UGC (9:16)",
                "映像→ストーリー (9:16)",
                "映像→映画風 (16:9)",
                "画像→広告画像 (4:5)",
                "自由制作 (9:16)",
            ];
            for (i, p) in presets.iter().enumerate() {
                if ui.selectable_label(self.lib.preset == i, *p).clicked() {
                    self.lib.preset = i;
                    self.lib.format = ["9:16", "9:16", "16:9", "4:5", "9:16"][i].into();
                }
            }
            ui.add_space(6.0);
            ui.label("タイトル");
            ui.text_edit_singleline(&mut self.lib.title);
            ui.label("何を作るか（ブリーフ）");
            ui.add(
                egui::TextEdit::multiline(&mut self.lib.brief)
                    .desired_rows(4)
                    .desired_width(f32::INFINITY),
            );
            ui.horizontal(|ui| {
                ui.label("形式");
                for f in ["9:16", "16:9", "1:1", "4:5"] {
                    if ui.selectable_label(self.lib.format == f, f).clicked() {
                        self.lib.format = f.into();
                    }
                }
            });
            ui.add_space(8.0);
            let n = self.lib.selected_assets.len();
            let can = n > 0 && !self.lib.started;
            let btxt = format!("▶ ダンに作らせる（素材{n}件）");
            if ui
                .add_enabled(can, egui::Button::new(btxt).min_size(egui::vec2(300.0, 34.0)))
                .clicked()
            {
                self.start_generation();
            }
            if self.lib.started {
                ui.add_space(6.0);
                ui.horizontal(|ui| {
                    ui.spinner();
                    ui.label("ダンが制作中…（数分かかります）");
                });
                for ev in &self.lib.events {
                    ui.label(egui::RichText::new(ev).small().weak());
                }
            }
            if let Some(e) = &self.lib.error {
                ui.colored_label(egui::Color32::from_rgb(255, 120, 120), e);
            }
            ui.separator();
            ui.label("素材をパスで登録（PC内のファイル）");
            ui.text_edit_singleline(&mut self.lib.register_path);
            if ui.button("登録").clicked() && !self.lib.register_path.trim().is_empty() {
                let body = serde_json::json!({
                    "room_id": self.room_id(),
                    "uri": self.lib.register_path.trim(),
                    "source_type": "local_path",
                    "make_proxy": true,
                });
                self.lib.register_path.clear();
                self.lib_post("act", "/api/v1/production-assets/register".into(), body);
            }
            ui.label(
                egui::RichText::new("ヒント: 動画ファイルをこのウィンドウにドロップしても登録できます")
                    .small()
                    .weak(),
            );
        });
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.horizontal(|ui| {
                ui.heading("制作ライブラリ");
                if ui.small_button("🔄 更新").clicked() {
                    self.lib_refresh();
                }
            });
            egui::ScrollArea::vertical().show(ui, |ui| {
                ui.add_space(4.0);
                ui.label(egui::RichText::new("コンテンツ（クリックで開く）").strong());
                ui.horizontal_wrapped(|ui| {
                    let contents = self.lib.contents.clone();
                    for c in &contents {
                        let title = c.get("title").and_then(|v| v.as_str()).unwrap_or("(無題)");
                        let cid = c.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                        let nclips = c
                            .get("timeline")
                            .and_then(|t| t.get("sequence"))
                            .and_then(|sq| sq.get("tracks"))
                            .and_then(|t| t.as_array())
                            .map(|t| {
                                t.iter()
                                    .map(|tr| tr.get("clips").and_then(|c| c.as_array()).map(|c| c.len()).unwrap_or(0))
                                    .sum::<usize>()
                            })
                            .unwrap_or(0);
                        let label = format!("🎬 {title}\n{nclips} clips");
                        if ui.add_sized(egui::vec2(160.0, 56.0), egui::Button::new(label)).clicked()
                            && !cid.is_empty()
                        {
                            self.open_content(&cid);
                        }
                    }
                });
                ui.add_space(10.0);
                ui.label(egui::RichText::new("素材（クリックで選択 → 右の「ダンに作らせる」）").strong());
                ui.horizontal_wrapped(|ui| {
                    let assets = self.lib.assets.clone();
                    for a in &assets {
                        let id = a.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                        let name = a
                            .get("filename")
                            .or_else(|| a.get("name"))
                            .and_then(|v| v.as_str())
                            .unwrap_or("(無名)")
                            .to_string();
                        let status = a.get("status").and_then(|v| v.as_str()).unwrap_or("");
                        let selected = self.lib.selected_assets.iter().any(|s| *s == id);
                        let (rect, resp) =
                            ui.allocate_exact_size(egui::vec2(150.0, 110.0), egui::Sense::click());
                        let p = ui.painter_at(rect);
                        p.rect_filled(rect, 6.0, egui::Color32::from_gray(28));
                        if let Some(t) = self.lib.thumbs.get(&id) {
                            let img_r = egui::Rect::from_min_max(
                                rect.min + egui::vec2(4.0, 4.0),
                                egui::pos2(rect.right() - 4.0, rect.bottom() - 26.0),
                            );
                            p.image(
                                t.id(),
                                img_r,
                                egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0)),
                                egui::Color32::WHITE,
                            );
                        }
                        let badge = if status == "proxy_ready" {
                            "OK"
                        } else if status == "processing" {
                            "..."
                        } else {
                            "-"
                        };
                        let short: String = name.chars().take(16).collect();
                        p.text(
                            egui::pos2(rect.left() + 6.0, rect.bottom() - 12.0),
                            egui::Align2::LEFT_CENTER,
                            format!("[{badge}] {short}"),
                            egui::FontId::proportional(10.0),
                            egui::Color32::from_gray(200),
                        );
                        p.rect_stroke(
                            rect,
                            6.0,
                            if selected {
                                egui::Stroke::new(2.5, egui::Color32::from_rgb(90, 170, 255))
                            } else {
                                egui::Stroke::new(1.0, egui::Color32::from_gray(45))
                            },
                        );
                        if resp.clicked() && !id.is_empty() {
                            if selected {
                                self.lib.selected_assets.retain(|s| *s != id);
                            } else {
                                self.lib.selected_assets.push(id.clone());
                            }
                        }
                    }
                });
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
        let now = Instant::now();
        self.last_frames.push(now);
        self.last_frames.retain(|t| now.duration_since(*t).as_secs_f32() < 1.0);
        self.ui_fps = self.last_frames.len() as f32;

        // edit keys: S=split, Del=delete, Ctrl+Z/Y=undo/redo
        if ctx.input(|i| i.key_pressed(egui::Key::S) && !i.modifiers.ctrl) {
            let t = self.t;
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
        if ctx.input(|i| i.key_pressed(egui::Key::E) && !i.modifiers.ctrl) {
            self.toggle_popout();
        }
        self.poll_popout_bakes();
        if ctx.input(|i| i.key_pressed(egui::Key::Delete) || i.key_pressed(egui::Key::Backspace)) {
            if !self.selected.is_empty() {
                let ids = edits::expand_links(&self.doc.raw, &self.selected);
                let ripple = ctx.input(|i| i.modifiers.shift);
                self.selected.clear();
                if ripple {
                    // Shift+Del: delete AND close the gap (ripple / 左詰め)
                    self.apply_edit(true, |raw| edits::ripple_delete(raw, &ids));
                } else {
                    self.apply_edit(true, |raw| edits::delete_clips(raw, &ids));
                }
            }
        }
        if ctx.input(|i| i.modifiers.ctrl && i.key_pressed(egui::Key::Z)) {
            if let Some(prev) = self.undo.pop() {
                self.redo.push(self.doc.raw.clone());
                self.restore(prev);
            }
        }
        if ctx.input(|i| i.modifiers.ctrl && i.key_pressed(egui::Key::Y)) {
            if let Some(next) = self.redo.pop() {
                self.undo.push(self.doc.raw.clone());
                self.restore(next);
            }
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
            if self.playing {
                // freeze the playhead where the audible clock actually was
                self.t = f64::from_bits(self.shared.clock_bits.load(Ordering::Relaxed));
            }
            self.playing = !self.playing;
            self.resume_pending = None; // explicit toggle overrides any pending auto-resume
            self.push_req(false);
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
        // frame step while paused (Filmora parity: arrow keys = +-1 frame)
        if !self.playing {
            const FSTEP: f64 = 1.0 / 30.0;
            if ctx.input(|i| i.key_pressed(egui::Key::ArrowRight)) {
                self.t = ((self.t / FSTEP).round() * FSTEP + FSTEP).min(self.dur);
                self.push_req(false);
            }
            if ctx.input(|i| i.key_pressed(egui::Key::ArrowLeft)) {
                self.t = ((self.t / FSTEP).round() * FSTEP - FSTEP).max(0.0);
                self.push_req(false);
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
            if req.len() < 4 {
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
                for j in want {
                    if !req.contains(&j) && req.len() < 4 {
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
        egui::TopBottomPanel::top("toolbar").exact_height(30.0).show(ctx, |ui| {
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
                        self.undo.push(self.doc.raw.clone());
                        self.redo.clear();
                    }
                    if sl.changed() {
                        let ids = edits::expand_links(&self.doc.raw, &[c.id.clone()]);
                        let v = vol as f64;
                        self.apply_edit(false, move |raw| edits::set_volume(raw, &ids, v));
                    }
                }
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    ui.label(egui::RichText::new("F1: ショートカット一覧 | クリップをダブルクリック=テロップ編集 | 番号ヘッダをドラッグ=レーン並べ替え").weak().small());
                });
            });
        });
        egui::TopBottomPanel::bottom("timeline")
            .resizable(true)
            .default_height(260.0)
            .height_range(140.0..=700.0)
            .show(ctx, |ui| self.timeline_ui(ui));
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
                        self.preview_inspector(ui, &resp);
                        // captions: active caption clips drawn over the frame (white bold with
                        // dark outline, bottom-centre — the export bakes the full styling
                        // server-side; this is the live view)
                        let t = self.t;
                        let texts: Vec<String> = self
                            .doc
                            .seq
                            .tracks
                            .iter()
                            .filter(|tr| tr.kind == "caption")
                            .flat_map(|tr| tr.clips.iter())
                            .filter(|c| t >= c.timeline_start && t < c.timeline_end)
                            .filter_map(|c| c.text.clone())
                            .collect();
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
                        ("Del", "削除"),
                        ("Shift+Del", "削除して左詰め"),
                        ("Ctrl+Z / Y", "元に戻す / やり直し"),
                        ("Ctrl+クリック", "複数選択"),
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
    // --dump-frame <t> <out.ppm>: headless compose of one timeline frame — deterministic
    // A/B verification (live matte path vs pv fallback) with no window and no user input
    if let Some(i) = args.iter().position(|a| a == "--dump-frame") {
        let t: f64 = args.get(i + 1).and_then(|v| v.parse().ok()).unwrap_or(0.0);
        let out = args.get(i + 2).cloned().unwrap_or_else(|| "frame.ppm".into());
        let contents = args.get(1).cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = args.get(2).cloned().unwrap_or_else(|| ROOM.to_string());
        let r = (|| -> anyhow::Result<()> {
            let doc = model::Doc::load(&contents, &dir)?;
            let d3d = media::D3d::new()?;
            let mut pool = media::VideoPool::new();
            let mut comp = compositor::Compositor::new(&d3d, CANVAS_W, CANVAS_H)?;
            let mut masks: MaskMap = Default::default();
            while mask_build_pass(&doc, &d3d, &mut masks) {}
            let mut pts_maps: PtsMap = Default::default();
            while pts_load_pass(&doc, &mut pts_maps) {}
            compose(&doc, &d3d, &mut pool, &mut comp, &masks, &pts_maps, t, true, false, true)?;
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
        let contents = args.get(1).cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = args.get(2).cloned().unwrap_or_else(|| ROOM.to_string());
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
        let contents = args.get(1).cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = args.get(2).cloned().unwrap_or_else(|| ROOM.to_string());
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
    // --selftest-move: headless lane-move — move an overlay clip to the video track
    if args.iter().any(|a| a == "--selftest-move") {
        let contents = args.get(1).cloned().unwrap_or_else(|| format!("{ROOM}/contents.json"));
        let dir = args.get(2).cloned().unwrap_or_else(|| ROOM.to_string());
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
    let contents = args
        .get(1)
        .cloned()
        .unwrap_or_else(|| format!("{ROOM}/contents.json"));
    let dir = args.get(2).cloned().unwrap_or_else(|| ROOM.to_string());
    let opts = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1280.0, 940.0])
            .with_title("done native editor (M2)"),
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
            let mut app = App::new(&contents, &dir)
                .map_err(|e| -> Box<dyn std::error::Error + Send + Sync> { format!("{e:#}").into() })?;
            // bare launch (no explicit contents arg): open the LIBRARY (assets ->
            // generation -> open), the full production entry point
            let explicit = std::env::args().nth(1).map(|a| !a.starts_with("--")).unwrap_or(false);
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
