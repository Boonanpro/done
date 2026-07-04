//! M3 — edit operations applied to the RAW contents.json value (the single source of
//! truth Dan/web/export all read). Editing raw JSON — not our typed subset — means every
//! field we don't model (captions' style, crop, volume, effects params, words, …) survives
//! a save byte-for-byte. The typed Doc is re-derived after each edit.

use serde_json::Value;

fn clips_iter_mut(root: &mut Value) -> Vec<&mut Value> {
    let mut out = Vec::new();
    let Some(seq) = root
        .get_mut(0)
        .and_then(|r| r.get_mut("timeline"))
        .and_then(|t| t.get_mut("sequence"))
    else {
        return out;
    };
    if let Some(tracks) = seq.get_mut("tracks").and_then(|t| t.as_array_mut()) {
        for tr in tracks {
            if let Some(cs) = tr.get_mut("clips").and_then(|c| c.as_array_mut()) {
                for c in cs {
                    out.push(c);
                }
            }
        }
    }
    out
}

fn f(v: &Value, k: &str) -> f64 {
    v.get(k).and_then(|x| x.as_f64()).unwrap_or(0.0)
}
fn setf(v: &mut Value, k: &str, val: f64) {
    v[k] = Value::from((val * 1000.0).round() / 1000.0);
}
fn sid(v: &Value) -> String {
    v.get("id").and_then(|x| x.as_str()).unwrap_or("").to_string()
}
fn link(v: &Value) -> Option<String> {
    v.get("link_id").and_then(|x| x.as_str()).map(|s| s.to_string())
}

/// ids sharing a link with any of `ids` (A/V linked move/trim/delete like the web editor).
pub fn expand_links(root: &Value, ids: &[String]) -> Vec<String> {
    let mut links = Vec::new();
    let mut out: Vec<String> = ids.to_vec();
    if let Some(seq) = root.get(0).and_then(|r| r.get("timeline")).and_then(|t| t.get("sequence")) {
        let all: Vec<&Value> = seq
            .get("tracks")
            .and_then(|t| t.as_array())
            .map(|ts| ts.iter().flat_map(|tr| tr.get("clips").and_then(|c| c.as_array()).into_iter().flatten()).collect())
            .unwrap_or_default();
        for c in &all {
            if ids.contains(&sid(c)) {
                if let Some(l) = link(c) {
                    links.push(l);
                }
            }
        }
        for c in &all {
            if let Some(l) = link(c) {
                if links.contains(&l) && !out.contains(&sid(c)) {
                    out.push(sid(c));
                }
            }
        }
    }
    out
}

pub fn move_clips(root: &mut Value, ids: &[String], dt: f64) {
    for c in clips_iter_mut(root) {
        if !ids.contains(&sid(c)) {
            continue;
        }
        let (ts, te) = (f(c, "timeline_start"), f(c, "timeline_end"));
        let dt = dt.max(-ts); // never before 0
        setf(c, "timeline_start", ts + dt);
        setf(c, "timeline_end", te + dt);
    }
}

/// Trim one edge. left=true drags timeline_start (source in-point follows); else the end.
pub fn trim_clip(root: &mut Value, ids: &[String], left: bool, new_t: f64) {
    for c in clips_iter_mut(root) {
        if !ids.contains(&sid(c)) {
            continue;
        }
        let (ts, te) = (f(c, "timeline_start"), f(c, "timeline_end"));
        let ss = f(c, "source_start");
        let has_se = c.get("source_end").map(|v| v.is_number()).unwrap_or(false);
        if left {
            let nt = new_t.clamp(0.0, te - 0.05);
            let d = nt - ts;
            setf(c, "timeline_start", nt);
            setf(c, "source_start", (ss + d).max(0.0));
        } else {
            let nt = new_t.max(ts + 0.05);
            setf(c, "timeline_end", nt);
            if has_se {
                let se = f(c, "source_end");
                setf(c, "source_end", se + (nt - te));
            }
        }
    }
}

pub fn delete_clips(root: &mut Value, ids: &[String]) {
    let Some(seq) = root
        .get_mut(0)
        .and_then(|r| r.get_mut("timeline"))
        .and_then(|t| t.get_mut("sequence"))
    else {
        return;
    };
    if let Some(tracks) = seq.get_mut("tracks").and_then(|t| t.as_array_mut()) {
        for tr in tracks {
            if let Some(cs) = tr.get_mut("clips").and_then(|c| c.as_array_mut()) {
                cs.retain(|c| !ids.contains(&sid(c)));
            }
        }
    }
}

/// Split every listed clip that straddles `t` (same math as the web editor: right half gets
/// a fresh id and shifted source_start; linked pairs get a shared new link id).
pub fn split_clips(root: &mut Value, ids: &[String], t: f64, salt: u64) {
    let mut n = 0u64;
    let mut right_links: std::collections::HashMap<String, String> = Default::default();
    let Some(seq) = root
        .get_mut(0)
        .and_then(|r| r.get_mut("timeline"))
        .and_then(|t| t.get_mut("sequence"))
    else {
        return;
    };
    if let Some(tracks) = seq.get_mut("tracks").and_then(|t| t.as_array_mut()) {
        for tr in tracks {
            if let Some(cs) = tr.get_mut("clips").and_then(|c| c.as_array_mut()) {
                let mut out: Vec<Value> = Vec::with_capacity(cs.len());
                for c in cs.drain(..) {
                    let (ts, te) = (f(&c, "timeline_start"), f(&c, "timeline_end"));
                    let inside = t > ts + 0.05 && t < te - 0.05;
                    if !(ids.contains(&sid(&c)) && inside) {
                        out.push(c);
                        continue;
                    }
                    let d = t - ts;
                    let has_se = c.get("source_end").map(|v| v.is_number()).unwrap_or(false);
                    let mut leftv = c.clone();
                    setf(&mut leftv, "timeline_end", t);
                    if has_se {
                        let ss = f(&c, "source_start");
                        setf(&mut leftv, "source_end", ss + d);
                    }
                    let mut rightv = c.clone();
                    n += 1;
                    rightv["id"] = Value::from(format!("{}__ns_{}_{}", sid(&c), salt, n));
                    setf(&mut rightv, "timeline_start", t);
                    if has_se {
                        let ss = f(&c, "source_start");
                        setf(&mut rightv, "source_start", ss + d);
                    }
                    if let Some(l) = link(&c) {
                        let nl = right_links
                            .entry(l)
                            .or_insert_with(|| format!("lk_ns_{}_{}", salt, n))
                            .clone();
                        rightv["link_id"] = Value::from(nl);
                    }
                    out.push(leftv);
                    out.push(rightv);
                }
                *cs = out;
            }
        }
    }
}

/// Duplicate the selection as a BLOCK with a ripple INSERT (Filmora/CapCut semantics):
/// copies land right after the selection keeping their relative layout, and everything
/// that starts at/after the selection's end — on ALL tracks — shifts right to make room.
/// Without the ripple, a copy dropped onto a gap-free timeline overlaps the next clip:
/// two videos stack and both audios play at once (the "duplicate is broken" report).
/// Linked A/V pairs get a fresh shared link_id so copies link to each other, not the originals.
pub fn duplicate_clips(root: &mut Value, ids: &[String], salt: u64) {
    // selection block bounds
    let mut bs = f64::MAX;
    let mut be = f64::MIN;
    if let Some(seq) = root.get(0).and_then(|r| r.get("timeline")).and_then(|t| t.get("sequence")) {
        if let Some(tracks) = seq.get("tracks").and_then(|t| t.as_array()) {
            for tr in tracks {
                for c in tr.get("clips").and_then(|c| c.as_array()).unwrap_or(&vec![]) {
                    if ids.contains(&sid(c)) {
                        bs = bs.min(f(c, "timeline_start"));
                        be = be.max(f(c, "timeline_end"));
                    }
                }
            }
        }
    }
    if !(be > bs) {
        return;
    }
    let d = be - bs;
    // 1) ripple: make room AFTER the block (all tracks, same rule as ripple_delete inverted)
    for_each_clip(root, |c| {
        if ids.contains(&sid(c)) {
            return;
        }
        let cs = f(c, "timeline_start");
        if cs >= be - 1e-6 {
            let ce = f(c, "timeline_end");
            setf(c, "timeline_start", cs + d);
            setf(c, "timeline_end", ce + d);
        }
    });
    // 2) copies at original position + block length (relative layout preserved)
    let mut n = 0u64;
    let mut new_links: std::collections::HashMap<String, String> = Default::default();
    let Some(seq) = root
        .get_mut(0)
        .and_then(|r| r.get_mut("timeline"))
        .and_then(|t| t.get_mut("sequence"))
    else {
        return;
    };
    if let Some(tracks) = seq.get_mut("tracks").and_then(|t| t.as_array_mut()) {
        for tr in tracks {
            if let Some(cs) = tr.get_mut("clips").and_then(|c| c.as_array_mut()) {
                let mut out: Vec<Value> = Vec::with_capacity(cs.len());
                for c in cs.drain(..) {
                    if !ids.contains(&sid(&c)) {
                        out.push(c);
                        continue;
                    }
                    let (ts, te) = (f(&c, "timeline_start"), f(&c, "timeline_end"));
                    let mut copy = c.clone();
                    n += 1;
                    copy["id"] = Value::from(format!("{}__dup_{}_{}", sid(&c), salt, n));
                    setf(&mut copy, "timeline_start", ts + d);
                    setf(&mut copy, "timeline_end", te + d);
                    if let Some(l) = link(&c) {
                        let nl = new_links
                            .entry(l)
                            .or_insert_with(|| format!("lk_dup_{}_{}", salt, n))
                            .clone();
                        copy["link_id"] = Value::from(nl);
                    }
                    out.push(c);
                    out.push(copy);
                }
                *cs = out;
            }
        }
    }
}

/// Atomic write-back of the WHOLE document (tmp + rename) — the same file the web editor,
/// Dan and the server exporter read.
pub fn save(root: &Value, contents_path: &str) -> anyhow::Result<()> {
    let tmp = format!("{contents_path}.native.tmp");
    std::fs::write(&tmp, serde_json::to_string(root)?)?;
    std::fs::rename(&tmp, contents_path)?;
    Ok(())
}

/// Add/replace or remove the popout effect on the given clips.
pub fn set_popout(raw: &mut serde_json::Value, ids: &[String], params: Option<serde_json::Value>) {
    for_each_clip(raw, |c| {
        let id = c.get("id").and_then(|v| v.as_str()).unwrap_or("");
        if !ids.iter().any(|i| i == id) {
            return;
        }
        let effects = c
            .as_object_mut()
            .unwrap()
            .entry("effects")
            .or_insert_with(|| serde_json::Value::Array(vec![]));
        // removing: restore the display position the clip had BEFORE the effect was
        // applied (recorded as params.orig_position at apply)
        let mut restore: Option<Option<serde_json::Value>> = None;
        if params.is_none() {
            if let Some(arr) = effects.as_array() {
                if let Some(p) = arr
                    .iter()
                    .find(|e| e.get("type").and_then(|t| t.as_str()) == Some("popout"))
                    .and_then(|e| e.get("params"))
                {
                    restore = Some(match p.get("orig_position") {
                        Some(serde_json::Value::Null) | None => p.get("box").cloned(),
                        Some(v) => Some(v.clone()),
                    });
                }
            }
        }
        if let Some(arr) = effects.as_array_mut() {
            arr.retain(|e| e.get("type").and_then(|t| t.as_str()) != Some("popout"));
            if let Some(p) = &params {
                arr.push(serde_json::json!({"type": "popout", "params": p}));
            }
        }
        if let Some(r) = restore {
            match r {
                Some(b) => {
                    c.as_object_mut().unwrap().insert("position".into(), b);
                }
                None => {
                    c.as_object_mut().unwrap().remove("position");
                }
            }
        }
    });
}

/// Bake finished: record margins on the effect and re-express the display position as the
/// margins-composed full frame (the bake canvas extends beyond the frame).
pub fn finalize_popout(raw: &mut serde_json::Value, id: &str, margins: &serde_json::Value) {
    let (l, t, r, b) = (
        margins.get("l").and_then(|v| v.as_f64()).unwrap_or(0.0),
        margins.get("t").and_then(|v| v.as_f64()).unwrap_or(0.0),
        margins.get("r").and_then(|v| v.as_f64()).unwrap_or(0.0),
        margins.get("b").and_then(|v| v.as_f64()).unwrap_or(0.0),
    );
    for_each_clip(raw, |c| {
        if c.get("id").and_then(|v| v.as_str()) != Some(id) {
            return;
        }
        if let Some(arr) = c.get_mut("effects").and_then(|e| e.as_array_mut()) {
            for e in arr.iter_mut() {
                if e.get("type").and_then(|t| t.as_str()) == Some("popout") {
                    if let Some(p) = e.get_mut("params").and_then(|p| p.as_object_mut()) {
                        p.insert("margins".into(), margins.clone());
                    }
                }
            }
        }
        let o = c.as_object_mut().unwrap();
        o.insert(
            "position".into(),
            serde_json::json!({
                "x": (0.0 - l * 10000.0).round() / 10000.0,
                "y": (0.0 - t * 10000.0).round() / 10000.0,
                "width": ((1.0 + l + r) * 10000.0).round() / 10000.0,
                "height": ((1.0 + t + b) * 10000.0).round() / 10000.0,
            }),
        );
        o.insert("crop".into(), serde_json::Value::Null);
        o.insert("muted".into(), serde_json::Value::Bool(true));
    });
}

fn for_each_clip(raw: &mut serde_json::Value, mut f: impl FnMut(&mut serde_json::Value)) {
    if let Some(tracks) = raw
        .get_mut(0)
        .and_then(|r| r.get_mut("timeline"))
        .and_then(|x| x.get_mut("sequence"))
        .and_then(|x| x.get_mut("tracks"))
        .and_then(|x| x.as_array_mut())
    {
        for tr in tracks {
            if let Some(clips) = tr.get_mut("clips").and_then(|c| c.as_array_mut()) {
                for c in clips {
                    f(c);
                }
            }
        }
    }
}

/// Ripple delete: remove the clips AND close the gaps they leave — everything after each
/// removed span shifts left, across ALL tracks (Filmora's magnetic delete).
pub fn ripple_delete(raw: &mut serde_json::Value, ids: &[String]) {
    // collect spans first
    let mut spans: Vec<(f64, f64)> = Vec::new();
    if let Some(tracks) = raw
        .get(0)
        .and_then(|r| r.get("timeline"))
        .and_then(|x| x.get("sequence"))
        .and_then(|x| x.get("tracks"))
        .and_then(|x| x.as_array())
    {
        for tr in tracks {
            for c in tr.get("clips").and_then(|c| c.as_array()).unwrap_or(&vec![]) {
                let id = c.get("id").and_then(|v| v.as_str()).unwrap_or("");
                if ids.iter().any(|i| i == id) {
                    let ts = c.get("timeline_start").and_then(|v| v.as_f64()).unwrap_or(0.0);
                    let te = c.get("timeline_end").and_then(|v| v.as_f64()).unwrap_or(ts);
                    spans.push((ts, te));
                }
            }
        }
    }
    delete_clips(raw, ids);
    // merge overlapping spans, then shift right-to-left so offsets stay valid
    spans.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
    let mut merged: Vec<(f64, f64)> = Vec::new();
    for sp in spans {
        if let Some(last) = merged.last_mut() {
            if sp.0 <= last.1 + 1e-6 {
                last.1 = last.1.max(sp.1);
                continue;
            }
        }
        merged.push(sp);
    }
    for (ts, te) in merged.into_iter().rev() {
        let d = te - ts;
        for_each_clip(raw, |c| {
            let cs = c.get("timeline_start").and_then(|v| v.as_f64()).unwrap_or(0.0);
            if cs >= te - 1e-6 {
                let ce = c.get("timeline_end").and_then(|v| v.as_f64()).unwrap_or(cs);
                let o = c.as_object_mut().unwrap();
                o.insert("timeline_start".into(), serde_json::json!(((cs - d) * 1000.0).round() / 1000.0));
                o.insert("timeline_end".into(), serde_json::json!(((ce - d) * 1000.0).round() / 1000.0));
            }
        });
    }
}

/// Move clips to another track (drag between lanes). The clip renders in front/behind
/// simply by which track it lands on; its "track" kind field follows the target.
pub fn move_to_track(raw: &mut serde_json::Value, ids: &[String], target: usize) {
    let Some(tracks) = raw
        .get_mut(0)
        .and_then(|r| r.get_mut("timeline"))
        .and_then(|x| x.get_mut("sequence"))
        .and_then(|x| x.get_mut("tracks"))
        .and_then(|x| x.as_array_mut())
    else {
        return;
    };
    if target >= tracks.len() {
        return;
    }
    let tkind = tracks[target].get("type").and_then(|v| v.as_str()).unwrap_or("").to_string();
    if tkind == "audio" {
        return; // visual clips can live on any non-audio lane
    }
    let mut moved: Vec<serde_json::Value> = Vec::new();
    for tr in tracks.iter_mut() {
        if let Some(clips) = tr.get_mut("clips").and_then(|c| c.as_array_mut()) {
            let mut i = 0;
            while i < clips.len() {
                let id = clips[i].get("id").and_then(|v| v.as_str()).unwrap_or("");
                if ids.iter().any(|x| x == id) {
                    moved.push(clips.remove(i));
                } else {
                    i += 1;
                }
            }
        }
    }
    for mut c in moved {
        if let Some(o) = c.as_object_mut() {
            o.insert("track".into(), serde_json::json!(tkind));
        }
        tracks[target]
            .get_mut("clips")
            .and_then(|c| c.as_array_mut())
            .map(|arr| arr.push(c));
    }
}

/// Set a clip's display position (canvas fractions) — the preview inspector drag.
pub fn set_position(raw: &mut serde_json::Value, id: &str, x: f64, y: f64, w: f64, h: f64) {
    for_each_clip(raw, |c| {
        if c.get("id").and_then(|v| v.as_str()) != Some(id) {
            return;
        }
        c.as_object_mut().unwrap().insert(
            "position".into(),
            serde_json::json!({
                "x": (x * 10000.0).round() / 10000.0,
                "y": (y * 10000.0).round() / 10000.0,
                "width": (w * 10000.0).round() / 10000.0,
                "height": (h * 10000.0).round() / 10000.0,
            }),
        );
    });
}

/// Set a caption clip's text.
pub fn set_text(raw: &mut serde_json::Value, id: &str, text: &str) {
    for_each_clip(raw, |c| {
        if c.get("id").and_then(|v| v.as_str()) == Some(id) {
            c.as_object_mut().unwrap().insert("text".into(), serde_json::json!(text));
        }
    });
}

/// Set a clip's volume (applies to its linked audio at playback and export).
pub fn set_volume(raw: &mut serde_json::Value, ids: &[String], vol: f64) {
    for_each_clip(raw, |c| {
        let id = c.get("id").and_then(|v| v.as_str()).unwrap_or("");
        if ids.iter().any(|i| i == id) {
            c.as_object_mut().unwrap().insert(
                "volume".into(),
                serde_json::json!((vol * 1000.0).round() / 1000.0),
            );
        }
    });
}

/// Reorder tracks (lane header drag): array order IS the stacking order.
pub fn reorder_tracks(raw: &mut serde_json::Value, from: usize, to: usize) {
    if let Some(tracks) = raw
        .get_mut(0)
        .and_then(|r| r.get_mut("timeline"))
        .and_then(|x| x.get_mut("sequence"))
        .and_then(|x| x.get_mut("tracks"))
        .and_then(|x| x.as_array_mut())
    {
        if from < tracks.len() && to < tracks.len() && from != to {
            let tr = tracks.remove(from);
            tracks.insert(to, tr);
        }
    }
}
