//! done native editor — M1(GPU compositor) + M2(GPU-drawn timeline) in ONE process.
//! No WebView, no IPC, no GStreamer: UI calls the frame server as plain functions.
//!
//! Usage: native_ui [contents.json] [asset_dir]
//! Keys: Space=play/pause, drag timeline=scrub, wheel=pan, Ctrl+wheel=zoom.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod compositor;
mod media;
mod model;

use std::time::Instant;

use eframe::egui;

const ROOM: &str = "D:/done/uploads/production-assets/bd05fcc0-c143-4d1c-828e-7624e087b6c1";

struct App {
    doc: model::Doc,
    d3d: media::D3d,
    pool: media::VideoPool,
    comp: compositor::Compositor,
    audio: Option<media::AudioOut>,
    tex: Option<egui::TextureHandle>,
    playing: bool,
    t: f64,
    dur: f64,
    pps: f32,      // timeline pixels per second
    scroll_x: f32, // timeline horizontal scroll (px)
    frame_no: u64,
    comp_ms: f32,
    ui_fps: f32,
    last_frames: Vec<Instant>,
    err: Option<String>,
}

impl App {
    fn new(contents: &str, dir: &str) -> anyhow::Result<Self> {
        let doc = model::Doc::load(contents, dir)?;
        let d3d = media::D3d::new()?;
        let comp = compositor::Compositor::new(&d3d, 720, 1280)?;
        let audio = media::AudioOut::new().ok();
        let dur = doc.duration();
        Ok(Self {
            doc,
            d3d,
            pool: media::VideoPool::new(),
            comp,
            audio,
            tex: None,
            playing: false,
            t: 0.0,
            dur,
            pps: 8.0,
            scroll_x: 0.0,
            frame_no: 0,
            comp_ms: 0.0,
            ui_fps: 0.0,
            last_frames: Vec::new(),
            err: None,
        })
    }

    fn set_playing(&mut self, on: bool) {
        if on == self.playing {
            return;
        }
        self.playing = on;
        if let Some(a) = self.audio.as_mut() {
            if on {
                let _ = a.start_at(self.t);
            } else {
                a.stop();
            }
        }
    }

    fn compose(&mut self) -> anyhow::Result<()> {
        let t0 = Instant::now();
        let t = self.t;
        let (base, overlays) = {
            let (b, o) = self.doc.active_video(t);
            (b.cloned(), o.into_iter().cloned().collect::<Vec<_>>())
        };
        self.comp.begin(&self.d3d);
        if let Some(c) = base {
            let path = self.doc.asset_path(c.asset_id.as_deref().unwrap());
            let src_t = c.source_start + (t - c.timeline_start);
            let vs = self.pool.get(&self.d3d, &path, 0, false)?;
            vs.ensure_frame(&self.d3d, src_t)?;
            let b = c.display_box();
            let (tex, wh) = (vs.bgra.clone(), (vs.width, vs.height));
            self.comp
                .draw(&self.d3d, &tex, wh, (b.x, b.y, b.width, b.height), true, None)?;
        }
        for c in &overlays {
            let b = c.display_box();
            if let Some((rel, off)) = c.popout() {
                let path = self.doc.rel_path(&rel);
                if !std::path::Path::new(&path).exists() {
                    continue;
                }
                let src_t = off + (t - c.timeline_start);
                const COLOR: u32 = 1; // MF enumerates this pv's video tracks in reverse mux order
                const MATTE: u32 = 0;
                {
                    let color = self.pool.get(&self.d3d, &path, COLOR, false)?;
                    color.ensure_frame(&self.d3d, src_t)?;
                }
                {
                    let matte = self.pool.get(&self.d3d, &path, MATTE, true)?;
                    matte.ensure_frame(&self.d3d, src_t)?;
                }
                let (ctex, cwh) = {
                    let s = self.pool.get(&self.d3d, &path, COLOR, false)?;
                    (s.bgra.clone(), (s.width, s.height))
                };
                let mtex = self.pool.get(&self.d3d, &path, MATTE, true)?.bgra.clone();
                self.comp.draw(
                    &self.d3d,
                    &ctex,
                    cwh,
                    (b.x, b.y, b.width, b.height),
                    false,
                    Some(&mtex),
                )?;
            } else if let Some(aid) = c.asset_id.as_deref() {
                let path = self.doc.asset_path(aid);
                let src_t = c.source_start + (t - c.timeline_start);
                let vs = self.pool.get(&self.d3d, &path, 0, false)?;
                vs.ensure_frame(&self.d3d, src_t)?;
                let (tex, wh) = (vs.bgra.clone(), (vs.width, vs.height));
                self.comp
                    .draw(&self.d3d, &tex, wh, (b.x, b.y, b.width, b.height), true, None)?;
            }
        }
        self.comp.readback(&self.d3d)?;
        self.comp_ms = t0.elapsed().as_secs_f32() * 1000.0;
        Ok(())
    }

    fn timeline_ui(&mut self, ui: &mut egui::Ui) {
        let h = ui.available_height();
        let w = ui.available_width();
        let (rect, resp) = ui.allocate_exact_size(egui::vec2(w, h), egui::Sense::click_and_drag());
        let p = ui.painter_at(rect);
        p.rect_filled(rect, 0.0, egui::Color32::from_gray(18));

        // zoom / pan
        let (scroll, zoom_mod, pointer) = ui.input(|i| {
            (
                i.raw_scroll_delta,
                i.modifiers.ctrl,
                i.pointer.hover_pos(),
            )
        });
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

        // ruler
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

        // lanes
        let lane_h = ((h - ruler_h - 4.0) / (self.doc.seq.tracks.len().max(1) as f32)).clamp(16.0, 42.0);
        let mut clips_drawn = 0usize;
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
                p.rect_filled(r, 3.0, if is_pop { egui::Color32::from_rgb(220, 120, 60) } else { color });
                p.rect_stroke(r, 3.0, egui::Stroke::new(1.0, egui::Color32::from_gray(25)));
                clips_drawn += 1;
            }
        }

        // playhead
        let hx = rect.left() + (self.t as f32) * self.pps - self.scroll_x;
        if hx >= rect.left() && hx <= rect.right() {
            p.line_segment(
                [egui::pos2(hx, rect.top()), egui::pos2(hx, rect.bottom())],
                egui::Stroke::new(1.5, egui::Color32::from_rgb(240, 60, 60)),
            );
        }

        // scrub
        if resp.dragged() || resp.clicked() {
            if let Some(pos) = resp.interact_pointer_pos() {
                let nt = ((self.scroll_x + (pos.x - rect.left())) / self.pps).clamp(0.0, self.dur as f32);
                self.t = nt as f64;
                if self.playing {
                    if let Some(a) = self.audio.as_mut() {
                        let _ = a.start_at(self.t);
                    }
                }
            }
        }
        p.text(
            rect.left_top() + egui::vec2(6.0, h - 16.0),
            egui::Align2::LEFT_TOP,
            format!(
                "{} clips drawn | comp {:.1}ms | ui {:.0}fps | {}",
                clips_drawn,
                self.comp_ms,
                self.ui_fps,
                if self.playing { "PLAYING" } else { "PAUSED" }
            ),
            egui::FontId::proportional(11.0),
            egui::Color32::from_gray(200),
        );
    }
}

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        // fps meter
        let now = Instant::now();
        self.last_frames.push(now);
        self.last_frames.retain(|t| now.duration_since(*t).as_secs_f32() < 1.0);
        self.ui_fps = self.last_frames.len() as f32;
        self.frame_no += 1;

        if ctx.input(|i| i.key_pressed(egui::Key::Space)) {
            let on = !self.playing;
            self.set_playing(on);
        }
        if self.playing {
            if let Some(a) = self.audio.as_mut() {
                let _ = a.fill(&self.doc);
                self.t = a.clock().min(self.dur);
                if self.t >= self.dur {
                    self.set_playing(false);
                }
            } else {
                self.t = (self.t + ctx.input(|i| i.stable_dt) as f64).min(self.dur);
            }
        }

        if let Err(e) = self.compose() {
            if self.err.as_deref() != Some(&e.to_string()[..]) {
                eprintln!("compose error: {e:#}");
            }
            self.err = Some(e.to_string());
        }
        let img = egui::ColorImage::from_rgba_unmultiplied(
            [self.comp.width as usize, self.comp.height as usize],
            &self.comp.rgba,
        );
        match &mut self.tex {
            Some(t) => t.set(img, egui::TextureOptions::LINEAR),
            None => self.tex = Some(ctx.load_texture("preview", img, egui::TextureOptions::LINEAR)),
        }

        egui::TopBottomPanel::bottom("timeline")
            .exact_height(240.0)
            .show(ctx, |ui| self.timeline_ui(ui));
        egui::CentralPanel::default()
            .frame(egui::Frame::none().fill(egui::Color32::from_gray(10)))
            .show(ctx, |ui| {
                let avail = ui.available_size();
                if let Some(tex) = &self.tex {
                    let (cw, ch) = (self.comp.width as f32, self.comp.height as f32);
                    let scale = (avail.x / cw).min(avail.y / ch);
                    let size = egui::vec2(cw * scale, ch * scale);
                    ui.centered_and_justified(|ui| {
                        ui.add(egui::Image::new((tex.id(), size)));
                    });
                }
                if let Some(e) = &self.err {
                    ui.colored_label(egui::Color32::RED, e);
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
            let app = App::new(&contents, &dir).map_err(|e| -> Box<dyn std::error::Error + Send + Sync> {
                format!("{e:#}").into()
            })?;
            Ok(Box::new(app))
        }),
    )
}
