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
        // removing: restore the display position to the CARD box the effect was applied
        // with (apply had swapped position to the margins-composed full frame)
        let mut restore: Option<serde_json::Value> = None;
        if params.is_none() {
            if let Some(arr) = effects.as_array() {
                restore = arr
                    .iter()
                    .find(|e| e.get("type").and_then(|t| t.as_str()) == Some("popout"))
                    .and_then(|e| e.get("params"))
                    .and_then(|p| p.get("box"))
                    .cloned();
            }
        }
        if let Some(arr) = effects.as_array_mut() {
            arr.retain(|e| e.get("type").and_then(|t| t.as_str()) != Some("popout"));
            if let Some(p) = &params {
                arr.push(serde_json::json!({"type": "popout", "params": p}));
            }
        }
        if let Some(b) = restore {
            c.as_object_mut().unwrap().insert("position".into(), b);
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
