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
    quality: &'static str,
}

struct Shared {
    req: Mutex<Req>,
    frame: Mutex<FrameOut>,
    clock_bits: AtomicU64,
    doc: Mutex<Arc<model::Doc>>,
}

#[derive(Clone, PartialEq)]
enum Drag {
    None,
    Scrub,
    Move { ids: Vec<String>, grab: f64, orig: f64, applied: f64 },
    Trim { ids: Vec<String>, left: bool },
}

fn compose(
    doc: &model::Doc,
    d3d: &media::D3d,
    pool: &mut media::VideoPool,
    comp: &mut compositor::Compositor,
    t: f64,
    original: bool,
) -> anyhow::Result<Vec<String>> {
    let mut used = Vec::new();
    let (base, overlays) = {
        let (b, o) = doc.active_video(t);
        (b.cloned(), o.into_iter().cloned().collect::<Vec<_>>())
    };
    comp.begin(d3d);
    if let Some(c) = base {
        let path = doc.asset_path_q(c.asset_id.as_deref().unwrap(), original);
        let src_t = c.source_start + (t - c.timeline_start);
        let vs = pool.get(d3d, &path, 0, false)?;
        vs.ensure_frame(d3d, src_t)?;
        let b = c.display_box();
        let (tex, wh) = (vs.bgra.clone(), (vs.width, vs.height));
        comp.draw(d3d, &tex, wh, (b.x, b.y, b.width, b.height), true, None)?;
        used.push(path);
    }
    for c in &overlays {
        let b = c.display_box();
        if let Some((rel, off)) = c.popout() {
            let path = doc.rel_path(&rel);
            if !std::path::Path::new(&path).exists() {
                continue;
            }
            let src_t = off + (t - c.timeline_start);
            const COLOR: u32 = 1; // MF enumerates this pv's 2 video tracks in reverse mux order
            const MATTE: u32 = 0;
            {
                let s = pool.get(d3d, &path, COLOR, false)?;
                s.ensure_frame(d3d, src_t)?;
            }
            {
                let s = pool.get(d3d, &path, MATTE, true)?;
                s.ensure_frame(d3d, src_t)?;
            }
            let (ctex, cwh) = {
                let s = pool.get(d3d, &path, COLOR, false)?;
                (s.bgra.clone(), (s.width, s.height))
            };
            let mtex = pool.get(d3d, &path, MATTE, true)?.bgra.clone();
            comp.draw(d3d, &ctex, cwh, (b.x, b.y, b.width, b.height), false, Some(&mtex))?;
            used.push(path);
        } else if let Some(aid) = c.asset_id.as_deref() {
            let path = doc.asset_path_q(aid, original);
            let src_t = c.source_start + (t - c.timeline_start);
            let vs = pool.get(d3d, &path, 0, false)?;
            vs.ensure_frame(d3d, src_t)?;
            let (tex, wh) = (vs.bgra.clone(), (vs.width, vs.height));
            comp.draw(d3d, &tex, wh, (b.x, b.y, b.width, b.height), true, None)?;
            used.push(path);
        }
    }
    comp.readback(d3d)?;
    Ok(used)
}

/// Pre-seek decoders for clips starting soon so entering them costs nothing.
fn prime_upcoming(
    doc: &model::Doc,
    d3d: &media::D3d,
    pool: &mut media::VideoPool,
    t: f64,
    original: bool,
    used: &[String],
) {
    for tr in &doc.seq.tracks {
        if tr.kind != "video" && tr.kind != "overlay" {
            continue;
        }
        for c in &tr.clips {
            if c.timeline_start <= t || c.timeline_start > t + 0.8 {
                continue;
            }
            let (path, src_in) = if let Some((rel, off)) = c.popout() {
                (doc.rel_path(&rel), off)
            } else if let Some(aid) = c.asset_id.as_deref() {
                (doc.asset_path_q(aid, original), c.source_start)
            } else {
                continue;
            };
            if used.iter().any(|u| *u == path) {
                continue; // never disturb a stream that is on screen right now
            }
            if let Ok(vs) = pool.get(d3d, &path, 0, false) {
                let _ = vs.prime(d3d, src_in);
            }
        }
    }
}

fn media_thread(shared: Arc<Shared>) {
    let run = || -> anyhow::Result<()> {
        let d3d = media::D3d::new()?;
        let mut pool = media::VideoPool::new();
        let mut comp = compositor::Compositor::new(&d3d, CANVAS_W, CANVAS_H)?;
        let mut audio = media::AudioOut::new().ok();
        let mut was_playing = false;
        let mut last_gen = u64::MAX;
        let mut last_t = -1.0f64;
        let mut seq = 0u64;
        loop {
            let doc: Arc<model::Doc> = shared.doc.lock().unwrap().clone();
            let dur = doc.duration();
            let r = shared.req.lock().unwrap().clone();
            if r.playing != was_playing {
                if let Some(a) = audio.as_mut() {
                    if r.playing {
                        let _ = a.start_at(r.t);
                    } else {
                        a.stop();
                    }
                }
                was_playing = r.playing;
            }
            let t = if r.playing {
                if let Some(a) = audio.as_mut() {
                    let _ = a.fill(&doc);
                    let c = a.clock().min(dur);
                    shared.clock_bits.store(c.to_bits(), Ordering::Relaxed);
                    c
                } else {
                    r.t
                }
            } else {
                r.t
            };
            let dirty = r.playing || r.gen != last_gen || (t - last_t).abs() > 1e-6;
            if dirty {
                let original = !r.scrubbing; // full quality unless mid-drag
                let t0 = Instant::now();
                match compose(&doc, &d3d, &mut pool, &mut comp, t, original) {
                    Ok(used) => {
                        seq += 1;
                        {
                            let mut f = shared.frame.lock().unwrap();
                            f.rgba.clear();
                            f.rgba.extend_from_slice(&comp.rgba);
                            f.seq = seq;
                            f.comp_ms = t0.elapsed().as_secs_f32() * 1000.0;
                            f.quality = if original { "original" } else { "proxy" };
                        }
                        if r.playing {
                            prime_upcoming(&doc, &d3d, &mut pool, t, original, &used);
                        }
                    }
                    Err(e) => eprintln!("compose: {e:#}"),
                }
                last_gen = r.gen;
                last_t = t;
            } else {
                std::thread::sleep(std::time::Duration::from_millis(3));
            }
        }
    };
    if let Err(e) = run() {
        eprintln!("media thread died: {e:#}");
    }
}

struct App {
    doc: Arc<model::Doc>,
    shared: Arc<Shared>,
    selected: Vec<String>,
    drag: Drag,
    undo: Vec<serde_json::Value>,
    redo: Vec<serde_json::Value>,
    save_at: Option<Instant>,
    salt: u64,
    tex: Option<egui::TextureHandle>,
    last_seq: u64,
    playing: bool,
    t: f64,
    dur: f64,
    pps: f32,
    scroll_x: f32,
    ui_fps: f32,
    last_frames: Vec<Instant>,
    comp_ms: f32,
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
                quality: "proxy",
            }),
            clock_bits: AtomicU64::new(0f64.to_bits()),
            doc: Mutex::new(doc.clone()),
        });
        {
            let shared = shared.clone();
            std::thread::Builder::new()
                .name("media".into())
                .spawn(move || media_thread(shared))?;
        }
        Ok(Self {
            doc,
            shared,
            selected: Vec::new(),
            drag: Drag::None,
            undo: Vec::new(),
            redo: Vec::new(),
            save_at: None,
            salt: std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0),
            tex: None,
            last_seq: 0,
            playing: false,
            t: 0.0,
            dur,
            pps: 8.0,
            scroll_x: 0.0,
            ui_fps: 0.0,
            last_frames: Vec::new(),
            comp_ms: 0.0,
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
        if let Ok(nd) = model::Doc::from_raw(raw, &self.doc.contents_path, &self.doc.asset_dir) {
            let nd = Arc::new(nd);
            self.doc = nd.clone();
            *self.shared.doc.lock().unwrap() = nd;
            self.dur = self.doc.duration();
            self.save_at = Some(Instant::now() + std::time::Duration::from_millis(1200));
            self.push_req(false);
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

    fn push_req(&mut self, scrubbing: bool) {
        let mut r = self.shared.req.lock().unwrap();
        self.gen += 1;
        *r = Req { t: self.t, playing: self.playing, scrubbing, gen: self.gen };
    }

    fn timeline_ui(&mut self, ui: &mut egui::Ui) {
        let h = ui.available_height();
        let w = ui.available_width();
        let (rect, resp) = ui.allocate_exact_size(egui::vec2(w, h), egui::Sense::click_and_drag());
        let p = ui.painter_at(rect);
        p.rect_filled(rect, 0.0, egui::Color32::from_gray(18));

        let (scroll, zoom_mod, pointer) =
            ui.input(|i| (i.raw_scroll_delta, i.modifiers.ctrl, i.pointer.hover_pos()));
        if rect.contains(pointer.unwrap_or_default()) {
            if zoom_mod && scroll.y != 0.0 {
                let px = pointer.unwrap().x - rect.left();
                let t_at = (self.scroll_x + px) / self.pps;
                self.pps = (self.pps * (1.0 + scroll.y.signum() * 0.15)).clamp(1.0, 400.0);
                self.scroll_x = (t_at * self.pps - px).max(0.0);
            } else if scroll.x != 0.0 || scroll.y != 0.0 {
                self.scroll_x = (self.scroll_x - scroll.x - scroll.y).max(0.0);
            }
        }

        let ruler_h = 18.0;
        let step_s = (60.0 / self.pps).ceil().max(1.0);
        let mut s = (self.scroll_x / self.pps / step_s).floor() * step_s;
        while s * self.pps - self.scroll_x < w {
            let x = rect.left() + s * self.pps - self.scroll_x;
            p.line_segment(
                [egui::pos2(x, rect.top()), egui::pos2(x, rect.top() + ruler_h)],
                egui::Stroke::new(1.0, egui::Color32::from_gray(90)),
            );
            p.text(
                egui::pos2(x + 3.0, rect.top() + 2.0),
                egui::Align2::LEFT_TOP,
                format!("{:02}:{:02}", (s as i64) / 60, (s as i64) % 60),
                egui::FontId::proportional(10.0),
                egui::Color32::from_gray(150),
            );
            s += step_s;
        }

        let lane_h =
            ((h - ruler_h - 4.0) / (self.doc.seq.tracks.len().max(1) as f32)).clamp(16.0, 42.0);
        let mut clips_drawn = 0usize;
        let mut hits: Vec<(egui::Rect, String)> = Vec::new();
        for (li, tr) in self.doc.seq.tracks.iter().enumerate() {
            let y0 = rect.top() + ruler_h + 2.0 + li as f32 * lane_h;
            let color = match tr.kind.as_str() {
                "video" => egui::Color32::from_rgb(70, 110, 190),
                "overlay" => egui::Color32::from_rgb(150, 90, 200),
                "audio" => egui::Color32::from_rgb(70, 160, 90),
                "caption" => egui::Color32::from_rgb(190, 150, 60),
                _ => egui::Color32::from_gray(90),
            };
            for c in &tr.clips {
                let x0 = rect.left() + (c.timeline_start as f32) * self.pps - self.scroll_x;
                let x1 = rect.left() + (c.timeline_end as f32) * self.pps - self.scroll_x;
                if x1 < rect.left() || x0 > rect.right() {
                    continue;
                }
                let r = egui::Rect::from_min_max(
                    egui::pos2(x0.max(rect.left()), y0),
                    egui::pos2(x1.min(rect.right()), y0 + lane_h - 3.0),
                );
                let is_pop = c.effects.iter().any(|e| e.kind == "popout");
                p.rect_filled(
                    r,
                    3.0,
                    if is_pop { egui::Color32::from_rgb(220, 120, 60) } else { color },
                );
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
                hits.push((r, c.id.clone()));
                clips_drawn += 1;
            }
        }

        let hx = rect.left() + (self.t as f32) * self.pps - self.scroll_x;
        if hx >= rect.left() && hx <= rect.right() {
            p.line_segment(
                [egui::pos2(hx, rect.top()), egui::pos2(hx, rect.bottom())],
                egui::Stroke::new(1.5, egui::Color32::from_rgb(240, 60, 60)),
            );
        }

        // ---- interactions: trim edges > move body > scrub empty space ----
        let to_t = |scroll_x: f32, pps: f32, x: f32| ((scroll_x + (x - rect.left())) / pps).max(0.0) as f64;
        if resp.drag_started() || (resp.clicked() && self.drag == Drag::None) {
            if let Some(pos) = resp.interact_pointer_pos() {
                let hit = hits.iter().find(|(r, _)| r.expand2(egui::vec2(4.0, 0.0)).contains(pos));
                match hit {
                    Some((r, id)) => {
                        if !self.selected.contains(id) {
                            if ui.input(|i| i.modifiers.ctrl) {
                                self.selected.push(id.clone());
                            } else {
                                self.selected = vec![id.clone()];
                            }
                        }
                        let ids = edits::expand_links(&self.doc.raw, &self.selected);
                        if resp.drag_started() {
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
                        if resp.clicked() {
                            self.selected.clear();
                        }
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
                        let want =
                            self.snap(orig + (to_t(self.scroll_x, self.pps, pos.x) - grab), &ids);
                        let dt = want - orig - applied;
                        if dt.abs() > 1e-4 {
                            self.apply_edit(false, |raw| edits::move_clips(raw, &ids, dt));
                            if let Drag::Move { applied, .. } = &mut self.drag {
                                *applied += dt;
                            }
                        }
                    }
                    Drag::Trim { ids, left } => {
                        let nt = self.snap(to_t(self.scroll_x, self.pps, pos.x), &ids);
                        self.apply_edit(false, |raw| edits::trim_clip(raw, &ids, left, nt));
                    }
                    Drag::None => {}
                }
            }
        }
        if resp.drag_stopped() {
            self.drag = Drag::None;
            self.push_req(false); // settle on full quality
        }

        p.text(
            rect.left_top() + egui::vec2(6.0, h - 16.0),
            egui::Align2::LEFT_TOP,
            format!(
                "{} clips | comp {:.1}ms | ui {:.0}fps | {} | {}",
                clips_drawn,
                self.comp_ms,
                self.ui_fps,
                self.quality,
                if self.playing { "PLAYING" } else { "PAUSED" }
            ),
            egui::FontId::proportional(11.0),
            egui::Color32::from_gray(200),
        );
    }
}

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
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
        if ctx.input(|i| i.key_pressed(egui::Key::Delete) || i.key_pressed(egui::Key::Backspace)) {
            if !self.selected.is_empty() {
                let ids = edits::expand_links(&self.doc.raw, &self.selected);
                self.selected.clear();
                self.apply_edit(true, |raw| edits::delete_clips(raw, &ids));
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
            self.push_req(false);
        }
        if self.playing {
            self.t = f64::from_bits(self.shared.clock_bits.load(Ordering::Relaxed));
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

        egui::TopBottomPanel::bottom("timeline")
            .exact_height(240.0)
            .show(ctx, |ui| self.timeline_ui(ui));
        egui::CentralPanel::default()
            .frame(egui::Frame::none().fill(egui::Color32::from_gray(10)))
            .show(ctx, |ui| {
                let avail = ui.available_size();
                if let Some(tex) = &self.tex {
                    let (cw, ch) = (CANVAS_W as f32, CANVAS_H as f32);
                    let scale = (avail.x / cw).min(avail.y / ch);
                    let size = egui::vec2(cw * scale, ch * scale);
                    ui.centered_and_justified(|ui| {
                        ui.add(egui::Image::new((tex.id(), size)));
                    });
                }
            });
        ctx.request_repaint();
    }
}

fn main() -> eframe::Result<()> {
    let args: Vec<String> = std::env::args().collect();
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
        Box::new(move |_cc| {
            let app = App::new(&contents, &dir)
                .map_err(|e| -> Box<dyn std::error::Error + Send + Sync> { format!("{e:#}").into() })?;
            Ok(Box::new(app))
        }),
    )
}
