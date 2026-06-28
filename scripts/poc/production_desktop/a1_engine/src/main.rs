//! A1 parity harness.
//!
//! Drives the Rust `Engine` through the same scenario the Python oracle measures:
//!   load (build + preroll) → scrub (random flushing seeks) → play (rendered/dropped) →
//!   edits (trim/move/split/delete/pip_move via the engine API) → get_state → memory.
//! Emits one JSON report whose fields line up with poc1.py / poc3.py so the two can be
//! compared apples-to-apples (the parity check the A1 plan asks for).
//!
//! Usage:
//!   a1_harness <contents.json> <asset_dir> [--seeks N] [--play-secs S] [--edits N]

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

use a1_engine::{EditOp, Engine};
use gstreamer as gst;
use serde_json::json;

// ---- tiny deterministic RNG (xorshift64*) so we don't pull in a crate ----
struct Rng(u64);
impl Rng {
    fn new(seed: u64) -> Self {
        Rng(seed | 1)
    }
    fn next_u64(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(0x2545F4914F6CDD1D)
    }
    /// uniform f64 in [lo, hi)
    fn uniform(&mut self, lo: f64, hi: f64) -> f64 {
        let f = (self.next_u64() >> 11) as f64 / (1u64 << 53) as f64;
        lo + f * (hi - lo)
    }
    fn range(&mut self, lo: i64, hi: i64) -> i64 {
        if hi <= lo {
            return lo;
        }
        lo + (self.next_u64() % ((hi - lo) as u64)) as i64
    }
    fn pick<'a, T>(&mut self, xs: &'a [T]) -> Option<&'a T> {
        if xs.is_empty() {
            None
        } else {
            Some(&xs[(self.next_u64() as usize) % xs.len()])
        }
    }
}

fn stats(mut xs: Vec<f64>) -> serde_json::Value {
    if xs.is_empty() {
        return serde_json::Value::Null;
    }
    xs.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let n = xs.len();
    let pct = |p: f64| {
        let k = (((p / 100.0) * n as f64).ceil() as usize).max(1) - 1;
        (xs[k.min(n - 1)] * 10.0).round() / 10.0
    };
    let r1 = |v: f64| (v * 10.0).round() / 10.0;
    json!({
        "n": n,
        "ms_min": r1(xs[0]),
        "ms_median": pct(50.0),
        "ms_p90": pct(90.0),
        "ms_p95": pct(95.0),
        "ms_max": r1(xs[n - 1]),
        "ms_mean": r1(xs.iter().sum::<f64>() / n as f64),
    })
}

fn main() -> anyhow::Result<()> {
    let mut args = std::env::args().skip(1);
    let contents = args.next().expect("usage: a1_harness <contents.json> <asset_dir> [flags]");
    let asset_dir = args.next().expect("usage: a1_harness <contents.json> <asset_dir> [flags]");
    let mut seeks = 40usize;
    let mut play_secs = 20.0f64;
    let mut edits = 80usize;
    let rest: Vec<String> = args.collect();
    let mut i = 0;
    while i < rest.len() {
        match rest[i].as_str() {
            "--seeks" => { seeks = rest[i + 1].parse().unwrap(); i += 2; }
            "--play-secs" => { play_secs = rest[i + 1].parse().unwrap(); i += 2; }
            "--edits" => { edits = rest[i + 1].parse().unwrap(); i += 2; }
            other => { eprintln!("ignoring arg: {other}"); i += 1; }
        }
    }

    Engine::init()?;

    // ---- memory sampler (peak physical RSS) ----
    let peak = Arc::new(AtomicU64::new(0));
    let stop = Arc::new(AtomicBool::new(false));
    let sampler = {
        let peak = peak.clone();
        let stop = stop.clone();
        thread::spawn(move || {
            while !stop.load(Ordering::Relaxed) {
                if let Some(m) = memory_stats::memory_stats() {
                    let cur = m.physical_mem as u64;
                    peak.fetch_max(cur, Ordering::Relaxed);
                }
                thread::sleep(Duration::from_millis(50));
            }
        })
    };

    let mut rng = Rng::new(1234);
    let mut engine = Engine::new(1080, 1920, 30)?;

    // ---- LOAD ----
    let load = engine.load(&contents, &asset_dir)?;
    let dur_s = load.timeline_duration_s;
    let decoders = engine.decoder_factories();

    if !load.preroll_ok {
        let report = json!({
            "engine": "a1_rust_ges",
            "load": {
                "build_s": load.build_s, "preroll_s": load.preroll_s,
                "preroll_ok": load.preroll_ok,
            },
            "fatal": "preroll did not reach PAUSED",
        });
        println!("{}", serde_json::to_string_pretty(&report)?);
        stop.store(true, Ordering::Relaxed);
        let _ = sampler.join();
        engine.set_null();
        return Ok(());
    }

    // ---- SCRUB: random flushing accurate seeks ----
    let mut scrub = Vec::new();
    let mut scrub_fail = 0;
    for _ in 0..seeks {
        let pos = rng.uniform(0.0, (dur_s - 0.2).max(0.1));
        let r = engine.seek(pos);
        if r.ok {
            scrub.push(r.ms);
        } else {
            scrub_fail += 1;
        }
    }

    // ---- PLAY: realtime stability ----
    engine.seek(0.0);
    let (r0, d0) = engine.fps_counters();
    let play_start = Instant::now();
    engine.play()?;
    let mut play_err: Option<String> = None;
    while play_start.elapsed().as_secs_f64() < play_secs {
        if let Some(msg) = engine.bus().timed_pop_filtered(
            gst::ClockTime::from_mseconds(200),
            &[gst::MessageType::Error, gst::MessageType::Eos],
        ) {
            use gst::MessageView;
            match msg.view() {
                MessageView::Error(e) => { play_err = Some(format!("{}", e.error())); break; }
                MessageView::Eos(_) => break,
                _ => {}
            }
        }
    }
    let wall = play_start.elapsed().as_secs_f64();
    let (r1, d1) = engine.fps_counters();
    engine.pause()?;
    let rendered = r1.saturating_sub(r0);
    let dropped = d1 - d0;

    // ---- EDITS: exercise the engine API by clip id (parity with poc3) ----
    engine.seek(0.0);
    let ops = ["trim", "move", "split", "delete", "pip_move"];
    let mut commit_ms = Vec::new();
    let mut reflect: std::collections::HashMap<&str, Vec<f64>> = std::collections::HashMap::new();
    let mut edit_errors = 0;
    for k in 0..edits {
        let op = ops[k % ops.len()];
        let vids = engine.video_clip_ids();
        let oids = engine.overlay_clip_ids();
        let res = match op {
            "pip_move" => {
                let Some(id) = rng.pick(&oids).cloned() else { continue };
                let posx = rng.range(0, 1080 - 200) as i32;
                let posy = rng.range(0, 1920 - 300) as i32;
                engine.apply_edit(EditOp::PipMove { clip_id: id, posx, posy })
            }
            "trim" => {
                let Some(id) = rng.pick(&vids).cloned() else { continue };
                let d = engine.clip_duration_s(&id).unwrap_or(1.0);
                let newd = (d * rng.uniform(0.4, 0.9)).max(0.4);
                engine.apply_edit(EditOp::Trim { clip_id: id, new_duration_s: newd })
            }
            "move" => {
                let Some(id) = rng.pick(&vids).cloned() else { continue };
                let s = engine.clip_start_s(&id).unwrap_or(0.0);
                let newstart = (s + rng.uniform(-1.5, 1.5)).max(0.0);
                engine.apply_edit(EditOp::Move { clip_id: id, new_start_s: newstart })
            }
            "split" => {
                let Some(id) = rng.pick(&vids).cloned() else { continue };
                let s = engine.clip_start_s(&id).unwrap_or(0.0);
                let d = engine.clip_duration_s(&id).unwrap_or(0.0);
                if d < 0.6 { continue; }
                engine.apply_edit(EditOp::Split { clip_id: id, at_s: s + d / 2.0 })
            }
            "delete" => {
                let Some(id) = rng.pick(&vids).cloned() else { continue };
                engine.apply_edit(EditOp::Delete { clip_id: id })
            }
            _ => continue,
        };
        if !res.ok {
            edit_errors += 1;
            continue;
        }
        commit_ms.push(res.commit_ms);
        let sk = engine.seek(res.verify_pos_s);
        if sk.ok {
            reflect.entry(op).or_default().push(sk.ms);
        } else {
            edit_errors += 1;
        }
    }

    let reflect_all: Vec<f64> = reflect.values().flatten().cloned().collect();
    let reflect_by_op: serde_json::Map<String, serde_json::Value> = reflect
        .iter()
        .map(|(k, v)| (k.to_string(), stats(v.clone())))
        .collect();

    // ---- live edit during PLAYING: move PiP repeatedly, watch for stalls ----
    engine.seek(0.0);
    let (lr0, ld0) = engine.fps_counters();
    engine.play()?;
    let live_start = Instant::now();
    let mut live_edits = 0;
    let mut live_err: Option<String> = None;
    while live_start.elapsed().as_secs_f64() < 10.0 {
        let oids = engine.overlay_clip_ids();
        if let Some(id) = rng.pick(&oids).cloned() {
            let posx = rng.range(0, 1080 - 200) as i32;
            // async commit during playback (parity with poc3's live-edit loop)
            if engine.pip_move_async(&id, posx, 100) {
                live_edits += 1;
            }
        }
        if let Some(msg) = engine.bus().timed_pop_filtered(
            gst::ClockTime::from_mseconds(150),
            &[gst::MessageType::Error],
        ) {
            if let gst::MessageView::Error(e) = msg.view() {
                live_err = Some(format!("{}", e.error()));
                break;
            }
        }
    }
    let live_wall = live_start.elapsed().as_secs_f64();
    let (lr1, ld1) = engine.fps_counters();
    engine.pause()?;

    // ---- STATE snapshot ----
    let st = engine.get_state();

    engine.set_null();
    thread::sleep(Duration::from_millis(200));
    stop.store(true, Ordering::Relaxed);
    let _ = sampler.join();
    let peak_rss_mb = (peak.load(Ordering::Relaxed) as f64 / 1024.0 / 1024.0 * 10.0).round() / 10.0;

    let report = json!({
        "engine": "a1_rust_ges",
        "timeline_duration_s": (dur_s * 1000.0).round() / 1000.0,
        "load": {
            "build_s": (load.build_s * 1000.0).round() / 1000.0,
            "preroll_s": (load.preroll_s * 1000.0).round() / 1000.0,
            "preroll_ok": load.preroll_ok,
            "video_clips": load.video_clips,
            "overlay_clips": load.overlay_clips,
            "audio_clips": load.audio_clips,
            "skipped": load.skipped,
            "assets": load.assets,
        },
        "video_decoders": decoders,
        "scrub": {
            "seeks": seeks, "ok": scrub.len(), "failed": scrub_fail,
            "stats": stats(scrub),
        },
        "play": {
            "wall_s": (wall * 100.0).round() / 100.0,
            "frames_rendered": rendered,
            "frames_dropped": dropped,
            "avg_fps": if wall > 0.0 { (rendered as f64 / wall * 10.0).round() / 10.0 } else { 0.0 },
            "target_fps": 30,
            "error": play_err,
        },
        "edits": {
            "requested": edits,
            "errors": edit_errors,
            "commit_ms": stats(commit_ms),
            "reflect_ms_all": stats(reflect_all),
            "reflect_ms_by_op": reflect_by_op,
        },
        "live_edit_during_play": {
            "wall_s": (live_wall * 100.0).round() / 100.0,
            "edits_applied": live_edits,
            "frames_rendered": lr1.saturating_sub(lr0),
            "frames_dropped": ld1 - ld0,
            "avg_fps": if live_wall > 0.0 { ((lr1.saturating_sub(lr0)) as f64 / live_wall * 10.0).round() / 10.0 } else { 0.0 },
            "error": live_err,
        },
        "state_after": {
            "position_s": (st.position_s * 1000.0).round() / 1000.0,
            "duration_s": (st.duration_s * 1000.0).round() / 1000.0,
            "playing": st.playing,
            "state": st.state,
            "video_clips": st.video_clips,
            "overlay_clips": st.overlay_clips,
            "audio_clips": st.audio_clips,
        },
        "mem": { "peak_rss_mb": peak_rss_mb },
    });

    println!("{}", serde_json::to_string_pretty(&report)?);
    Ok(())
}
