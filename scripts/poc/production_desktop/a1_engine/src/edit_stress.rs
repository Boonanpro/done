//! Reproduce the "edits freeze the app when pop-out clips are on the timeline" report:
//! load the REAL contents.json, seek INTO a pop-out clip (danpv source active), then hammer
//! the same edits the UI sends — 25Hz crop-drag rebuilds (in-place + async commit) and a
//! size change (structural re-add + commit_sync). A watchdog aborts with a diagnosis if any
//! step stalls. Usage:
//!   edit_stress <contents.json> <asset_dir> <seek_s> <clip_id> [--play]

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Instant;

use a1_engine::{timeline_model, Engine};

fn clips_from(contents: &str) -> Vec<(String, timeline_model::Clip)> {
    let seq = timeline_model::parse_contents(contents).expect("parse contents");
    let mut v = Vec::new();
    for tr in seq.tracks {
        let lane = tr.kind.clone();
        if lane != "video" && lane != "overlay" && lane != "audio" {
            continue;
        }
        for c in tr.clips {
            v.push((lane.clone(), c));
        }
    }
    v
}

fn main() -> anyhow::Result<()> {
    let a: Vec<String> = std::env::args().collect();
    let (contents, dir, seek_s, target) = (&a[1], &a[2], a[3].parse::<f64>()?, a[4].clone());
    let play = a.iter().any(|s| s == "--play");

    Engine::init()?;
    let mut e = Engine::new(720, 1280, 30)?;
    let rep = e.load(contents, dir)?;
    println!("loaded v={} o={} a={} preroll_ok={}", rep.video_clips, rep.overlay_clips, rep.audio_clips, rep.preroll_ok);
    let r = e.seek(seek_s);
    println!("seek {seek_s}s ok={} {:.0}ms", r.ok, r.ms);
    if play {
        e.play()?;
        std::thread::sleep(std::time::Duration::from_millis(500));
    }

    // watchdog: if a step takes >8s, report and hard-exit so we still get output
    let step = Arc::new(AtomicU64::new(0));
    {
        let step = step.clone();
        std::thread::spawn(move || {
            let mut last = 0u64;
            let mut same_since = Instant::now();
            loop {
                std::thread::sleep(std::time::Duration::from_millis(250));
                let s = step.load(Ordering::SeqCst);
                if s == u64::MAX {
                    return;
                }
                if s != last {
                    last = s;
                    same_since = Instant::now();
                } else if same_since.elapsed().as_secs_f64() > 8.0 {
                    eprintln!("!!! HANG detected at step {s} (no progress for 8s)");
                    std::process::exit(42);
                }
            }
        });
    }

    let base = clips_from(contents);

    // --- phase 1: crop-drag storm (what the UI's sendLiveCrop does at ~25Hz) ---
    let mut worst = 0.0f64;
    for i in 0..40u32 {
        step.store(1000 + i as u64, Ordering::SeqCst);
        let mut cs = base.clone();
        let frac = 0.01 * ((i % 10) as f64);
        for (_l, c) in cs.iter_mut() {
            if c.id == target {
                c.crop = Some(timeline_model::Crop { top: 0.0, bottom: frac, left: 0.0, right: 0.0 });
            }
        }
        let t = Instant::now();
        e.rebuild(cs)?;
        let ms = t.elapsed().as_secs_f64() * 1000.0;
        worst = worst.max(ms);
        if i % 10 == 0 {
            println!("crop rebuild {i}: {ms:.0}ms");
        }
        std::thread::sleep(std::time::Duration::from_millis(40));
    }
    println!("crop storm done, worst={worst:.0}ms");

    // --- phase 2: crop back to zero (the "戻しても戻らない" report) ---
    step.store(2000, Ordering::SeqCst);
    let t = Instant::now();
    e.rebuild(base.clone())?;
    println!("crop reset rebuild: {:.0}ms", t.elapsed().as_secs_f64() * 1000.0);

    // --- phase 3: size change (structural re-add + commit_sync) then back ---
    for (tag, wmul) in [("shrink", 0.8f64), ("restore", 1.0f64)] {
        step.store(3000, Ordering::SeqCst);
        let mut cs = base.clone();
        for (_l, c) in cs.iter_mut() {
            if c.id == target {
                if let Some(p) = c.position.as_mut() {
                    p.width *= wmul;
                    p.height *= wmul;
                }
            }
        }
        let t = Instant::now();
        e.rebuild(cs)?;
        println!("size {tag} rebuild: {:.0}ms", t.elapsed().as_secs_f64() * 1000.0);
    }

    // --- phase 4: sanity — pipeline still alive? (seek + state query) ---
    step.store(4000, Ordering::SeqCst);
    let r2 = e.seek(seek_s + 0.5);
    println!("post-edit seek ok={} {:.0}ms", r2.ok, r2.ms);
    step.store(u64::MAX, Ordering::SeqCst);
    println!("EDIT STRESS OK");
    Ok(())
}
