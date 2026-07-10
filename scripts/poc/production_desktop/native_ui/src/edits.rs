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
fn is_freeze_v(v: &Value) -> bool {
    if let Some(f) = v.get("freeze").and_then(|x| x.as_bool()) {
        return f;
    }
    match (v.get("source_start").and_then(|x| x.as_f64()), v.get("source_end").and_then(|x| x.as_f64())) {
        (Some(ss), Some(se)) => se <= ss + 1e-6,
        _ => false,
    }
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
    if let Some(tracks) = tracks_mut(root) {
        for tr in tracks {
            let Some(clips) = tr.get_mut("clips").and_then(|c| c.as_array_mut()) else {
                continue;
            };
            for c in clips.iter_mut() {
                if !ids.contains(&sid(c)) {
                    continue;
                }
                let (ts, te) = (f(c, "timeline_start"), f(c, "timeline_end"));
                let dt = dt.max(-ts); // never before 0
                setf(c, "timeline_start", ts + dt);
                setf(c, "timeline_end", te + dt);
            }
        }
    }
    normalize_linked_audio(root);
    remove_orphan_linked_audio(root);
}

/// Trim one edge. left=true drags timeline_start (source in-point follows);
/// else the end. Same-lane overlap is resolved with the edited clip winning.
pub fn trim_clip(root: &mut Value, ids: &[String], left: bool, new_t: f64) {
    trim_clip_live(root, ids, left, new_t);
    settle_overlaps(root, ids);
}

pub fn trim_clip_live_from(root: &mut Value, ids: &[String], left: bool, from_t: f64, new_t: f64) {
    trim_clip_live_impl(root, ids, left, Some(from_t), new_t);
}

/// Live trim during a mouse drag. Only the selected clip changes shape; overlap
/// erasure is settled on mouse release so covered clips do not disappear mid-drag.
pub fn trim_clip_live(root: &mut Value, ids: &[String], left: bool, new_t: f64) {
    trim_clip_live_impl(root, ids, left, None, new_t);
}

fn trim_clip_live_impl(root: &mut Value, ids: &[String], left: bool, from_t: Option<f64>, new_t: f64) {
    if trim_main_lane_live(root, ids, left, from_t, new_t) {
        normalize_linked_audio(root);
        remove_orphan_linked_audio(root);
        return;
    }
    {
        let Some(tracks) = tracks_mut(root) else { return };
        for tr in tracks.iter_mut() {
            let Some(clips) = tr.get_mut("clips").and_then(|c| c.as_array_mut()) else {
                continue;
            };

            if from_t.is_some() && left {
                let min_source_room = clips
                    .iter()
                    .filter(|c| ids.contains(&sid(c)))
                    .map(|c| f(c, "source_start"))
                    .fold(f64::MAX, f64::min);
                let min_duration = clips
                    .iter()
                    .filter(|c| ids.contains(&sid(c)))
                    .map(|c| f(c, "timeline_end") - f(c, "timeline_start"))
                    .fold(f64::MAX, f64::min);
                if min_source_room == f64::MAX || min_duration == f64::MAX {
                    continue;
                }
                let mut d = new_t - from_t.unwrap();
                d = d.max(-min_source_room);
                d = d.min(min_duration - 0.05);
                if d.abs() > 1e-6 {
                    for c in clips.iter_mut() {
                        if !ids.contains(&sid(c)) {
                            continue;
                        }
                        trim_one_clip(c, left, f(c, "timeline_start") + d);
                    }
                }
                continue;
            }

            let has_selected = clips.iter().any(|c| ids.contains(&sid(c)));
            if !has_selected {
                continue;
            }

            for c in clips.iter_mut() {
                if !ids.contains(&sid(c)) {
                    continue;
                }
                trim_one_clip(c, left, new_t);
            }
        }
    }
    normalize_linked_audio(root);
    remove_orphan_linked_audio(root);
}

fn main_video_track(root: &Value) -> Option<usize> {
    tracks_ref(root)?
        .iter()
        .position(|tr| tr.get("type").and_then(|v| v.as_str()) == Some("video"))
}

fn track_magnet(root: &Value, ti: usize) -> bool {
    let Some(tracks) = tracks_ref(root) else { return false };
    let Some(tr) = tracks.get(ti) else { return false };
    if let Some(m) = tr.get("magnet").and_then(|v| v.as_bool()) {
        return m;
    }
    tr.get("type").and_then(|v| v.as_str()) == Some("video") && main_video_track(root) == Some(ti)
}

fn trim_main_lane_live(root: &mut Value, ids: &[String], left: bool, from_t: Option<f64>, new_t: f64) -> bool {
    let Some(main_ti) = main_video_track(root) else { return false };
    let magnet = track_magnet(root, main_ti);
    let Some(tracks) = tracks_mut(root) else { return false };
    let Some(clips) = tracks
        .get_mut(main_ti)
        .and_then(|tr| tr.get_mut("clips"))
        .and_then(|c| c.as_array_mut())
    else {
        return false;
    };
    let selected: Vec<usize> = clips
        .iter()
        .enumerate()
        .filter(|(_, c)| ids.contains(&sid(c)) && c.get("asset_id").is_some() && !is_freeze_v(c))
        .map(|(i, _)| i)
        .collect();
    if selected.len() != 1 {
        return false;
    }
    let idx = selected[0];
    let ts = f(&clips[idx], "timeline_start");
    let te = f(&clips[idx], "timeline_end");
    let ss = f(&clips[idx], "source_start");
    let has_se = clips[idx].get("source_end").map(|v| v.is_number()).unwrap_or(false);
    let se = f(&clips[idx], "source_end");
    let old_edge = if left { from_t.unwrap_or(ts) } else { from_t.unwrap_or(te) };
    let mut d = new_t - old_edge;
    if d.abs() < 1e-6 {
        return true;
    }

    let shift_block = |clips: &mut Vec<Value>, side_left: bool, pivot: f64, delta: f64, skip: usize| {
        if delta.abs() < 1e-6 {
            return;
        }
        for (i, c) in clips.iter_mut().enumerate() {
            if i == skip {
                continue;
            }
            let cs = f(c, "timeline_start");
            let ce = f(c, "timeline_end");
            let belongs = if side_left {
                ce <= pivot + 0.002
            } else {
                cs >= pivot - 0.002
            };
            if belongs {
                setf(c, "timeline_start", cs + delta);
                setf(c, "timeline_end", ce + delta);
            }
        }
    };
    let pin_start_to_zero = |clips: &mut Vec<Value>| {
        let min_start = clips
            .iter()
            .map(|c| f(c, "timeline_start"))
            .fold(f64::MAX, f64::min);
        if min_start.is_finite() && min_start > 1e-6 {
            for c in clips.iter_mut() {
                let cs = f(c, "timeline_start");
                let ce = f(c, "timeline_end");
                setf(c, "timeline_start", cs - min_start);
                setf(c, "timeline_end", ce - min_start);
            }
        }
    };

    if !left {
        d = d.max(-(te - ts - 0.05));
        if has_se {
            d = d.max(ss + 0.05 - se);
        }
        if d.abs() < 1e-6 {
            return true;
        }
        setf(&mut clips[idx], "timeline_end", te + d);
        if has_se {
            setf(&mut clips[idx], "source_end", se + d);
        }
        if d > 0.0 || magnet {
            shift_block(clips, false, te, d, idx);
        }
        return true;
    }

    if d > 0.0 {
        d = d.min(te - ts - 0.05);
        if has_se {
            d = d.min(se - ss - 0.05);
        }
        if d.abs() < 1e-6 {
            return true;
        }
        if magnet {
            shift_block(clips, true, ts, d, idx);
        }
        setf(&mut clips[idx], "timeline_start", ts + d);
        setf(&mut clips[idx], "source_start", ss + d);
        if magnet {
            pin_start_to_zero(clips);
        }
        return true;
    }

    let mut grow = (-d).min(ss);
    if grow <= 1e-6 {
        return true;
    }
    if magnet {
        let left_min_start = clips
            .iter()
            .enumerate()
            .filter(|(i, c)| *i != idx && f(c, "timeline_end") <= ts + 0.002)
            .map(|(_, c)| f(c, "timeline_start"))
            .fold(f64::MAX, f64::min);
        let restore = if left_min_start.is_finite() { grow.min(left_min_start) } else { 0.0 };
        if restore > 1e-6 {
            shift_block(clips, true, ts, -restore, idx);
            setf(&mut clips[idx], "timeline_start", ts - restore);
            setf(&mut clips[idx], "source_start", ss - restore);
            grow -= restore;
        }
    }
    if grow > 1e-6 {
        let cur_end = f(&clips[idx], "timeline_end");
        let cur_ss = f(&clips[idx], "source_start");
        setf(&mut clips[idx], "source_start", (cur_ss - grow).max(0.0));
        setf(&mut clips[idx], "timeline_end", cur_end + grow);
        shift_block(clips, false, cur_end, grow, idx);
    }
    true
}

pub fn settle_overlaps(root: &mut Value, ids: &[String]) {
    {
        let Some(tracks) = tracks_mut(root) else { return };
        for tr in tracks.iter_mut() {
            let Some(clips) = tr.get_mut("clips").and_then(|c| c.as_array_mut()) else {
                continue;
            };
            erase_same_lane_overlaps_by_ids(clips, ids);
        }
    }
    normalize_linked_audio(root);
    remove_orphan_linked_audio(root);
}

pub fn settle_left_trim(root: &mut Value, ids: &[String]) {
    settle_overlaps(root, ids);
}

pub fn normalize_linked_audio(root: &mut Value) {
    use std::collections::HashMap;
    let mut visual: HashMap<String, (f64, f64, f64, Option<f64>, String)> = HashMap::new();
    let mut audio_links: Vec<String> = Vec::new();
    let mut audio_assets: Vec<String> = Vec::new();
    let mut used_ids: Vec<String> = Vec::new();
    if let Some(tracks) = tracks_ref(root) {
        for tr in tracks {
            if tr.get("type").and_then(|v| v.as_str()) == Some("audio") {
                for c in tr.get("clips").and_then(|c| c.as_array()).unwrap_or(&vec![]) {
                    if let Some(l) = link(c) {
                        if !audio_links.contains(&l) {
                            audio_links.push(l);
                        }
                    }
                    if let Some(aid) = c.get("asset_id").and_then(|v| v.as_str()) {
                        let aid = aid.to_string();
                        if !audio_assets.contains(&aid) {
                            audio_assets.push(aid);
                        }
                    }
                    let id = sid(c);
                    if !id.is_empty() && !used_ids.contains(&id) {
                        used_ids.push(id);
                    }
                }
                continue;
            }
            for c in tr.get("clips").and_then(|c| c.as_array()).unwrap_or(&vec![]) {
                let id = sid(c);
                if !id.is_empty() && !used_ids.contains(&id) {
                    used_ids.push(id);
                }
                if let Some(l) = link(c) {
                    if let Some(aid) = c.get("asset_id").and_then(|v| v.as_str()) {
                        if is_freeze_v(c) {
                            continue;
                        }
                        visual.insert(
                            l,
                            (
                                f(c, "timeline_start"),
                                f(c, "timeline_end"),
                                f(c, "source_start"),
                                c.get("source_end").and_then(|v| v.as_f64()),
                                aid.to_string(),
                            ),
                        );
                    }
                }
            }
        }
    }
    let Some(tracks) = tracks_mut(root) else { return };
    let mut missing = Vec::new();
    for (l, (ts, te, ss, se, aid)) in &visual {
        if audio_links.contains(l) || !audio_assets.contains(aid) {
            continue;
        }
        let mut id = format!("clip_a_{}", l);
        let mut n = 1usize;
        while used_ids.contains(&id) {
            id = format!("clip_a_{}_{}", l, n);
            n += 1;
        }
        used_ids.push(id.clone());
        missing.push(serde_json::json!({
            "id": id,
            "track": "audio",
            "asset_id": aid,
            "link_id": l,
            "timeline_start": ts,
            "timeline_end": te,
            "source_start": ss,
            "source_end": se.unwrap_or(*ss + (*te - *ts))
        }));
    }
    if !missing.is_empty() {
        let ai = tracks.iter().position(|tr| tr.get("type").and_then(|v| v.as_str()) == Some("audio"));
        match ai {
            Some(i) => {
                if let Some(clips) = tracks[i].get_mut("clips").and_then(|c| c.as_array_mut()) {
                    clips.extend(missing);
                    clips.sort_by(|a, b| f(a, "timeline_start").total_cmp(&f(b, "timeline_start")));
                }
            }
            None => tracks.push(serde_json::json!({"id": "audio_repair", "type": "audio", "clips": missing})),
        }
    }
    for tr in tracks {
        if tr.get("type").and_then(|v| v.as_str()) != Some("audio") {
            continue;
        }
        let Some(clips) = tr.get_mut("clips").and_then(|c| c.as_array_mut()) else {
            continue;
        };
        for c in clips {
            let Some(l) = link(c) else { continue };
            let Some((ts, te, ss, se, _)) = visual.get(&l) else { continue };
            setf(c, "timeline_start", *ts);
            setf(c, "timeline_end", *te);
            setf(c, "source_start", *ss);
            if let Some(se) = *se {
                setf(c, "source_end", se);
            }
        }
    }
}

fn trim_one_clip(c: &mut Value, left: bool, new_t: f64) {
    let (ts, te) = (f(c, "timeline_start"), f(c, "timeline_end"));
    let ss = f(c, "source_start");
    let has_se = c.get("source_end").map(|v| v.is_number()).unwrap_or(false);
    if is_freeze_v(c) {
        // a freeze's length is TIMELINE-only: never touch its source fields.
        // (the old video math turned an extended freeze back into moving video)
        if left {
            setf(c, "timeline_start", new_t.clamp(0.0, te - 0.05));
        } else {
            setf(c, "timeline_end", new_t.max(ts + 0.05));
        }
        return;
    }
    if left {
        let nt = new_t.clamp(0.0, te - 0.05);
        let mut d = nt - ts;
        d = d.max(-ss);
        if has_se {
            // never push the in-point past the out-point (that flipped the clip
            // into an accidental freeze by the implicit se<=ss convention)
            let se = f(c, "source_end");
            d = d.min(se - ss - 0.05);
        }
        setf(c, "timeline_start", (ts + d).max(0.0));
        setf(c, "source_start", (ss + d).max(0.0));
    } else {
        let nt = new_t.max(ts + 0.05);
        setf(c, "timeline_end", nt);
        if has_se {
            let se = f(c, "source_end");
            // clamp: the out-point stays after the in-point
            setf(c, "source_end", (se + (nt - te)).max(ss + 0.05));
        }
    }
}

pub fn remove_orphan_linked_audio(root: &mut Value) {
    let mut visual_links: Vec<String> = Vec::new();
    if let Some(tracks) = tracks_ref(root) {
        for tr in tracks {
            if tr.get("type").and_then(|v| v.as_str()) == Some("audio") {
                continue;
            }
            for c in tr.get("clips").and_then(|c| c.as_array()).unwrap_or(&vec![]) {
                if let Some(l) = link(c) {
                    if !visual_links.contains(&l) {
                        visual_links.push(l);
                    }
                }
            }
        }
    }
    let Some(tracks) = tracks_mut(root) else { return };
    for tr in tracks {
        if tr.get("type").and_then(|v| v.as_str()) != Some("audio") {
            continue;
        }
        let Some(clips) = tr.get_mut("clips").and_then(|c| c.as_array_mut()) else {
            continue;
        };
        clips.retain(|c| link(c).map(|l| visual_links.contains(&l)).unwrap_or(true));
    }
}

fn apply_visible_segment(c: &mut Value, new_start: f64, new_end: f64) -> bool {
    let old_start = f(c, "timeline_start");
    let old_end = f(c, "timeline_end");
    if new_end - new_start < 0.05 {
        return false;
    }
    if !is_freeze_v(c) {
        if c.get("source_start").map(|v| v.is_number()).unwrap_or(false) {
            setf(c, "source_start", (f(c, "source_start") + (new_start - old_start)).max(0.0));
        }
        if c.get("source_end").map(|v| v.is_number()).unwrap_or(false) {
            let ss = f(c, "source_start");
            setf(c, "source_end", (f(c, "source_end") + (new_end - old_end)).max(ss + 0.05));
        }
    }
    setf(c, "timeline_start", new_start);
    setf(c, "timeline_end", new_end);
    true
}

fn erase_same_lane_overlaps_by_ids(clips: &mut Vec<Value>, ids: &[String]) {
    let cutters: Vec<(f64, f64)> = clips
        .iter()
        .filter(|c| ids.contains(&sid(c)))
        .map(|c| (f(c, "timeline_start"), f(c, "timeline_end")))
        .filter(|(s, e)| e - s >= 0.05)
        .collect();
    if cutters.is_empty() {
        return;
    }

    for c in clips.iter_mut() {
        if ids.contains(&sid(c)) {
            continue;
        }
        let mut keep_start = f(c, "timeline_start");
        let mut keep_end = f(c, "timeline_end");
        let mut drop = false;

        for &(cut_start, cut_end) in &cutters {
            if cut_end <= keep_start + 1e-6 || cut_start >= keep_end - 1e-6 {
                continue;
            }

            let left = (keep_start, cut_start.min(keep_end));
            let right = (cut_end.max(keep_start), keep_end);
            let left_len = left.1 - left.0;
            let right_len = right.1 - right.0;

            if left_len < 0.05 && right_len < 0.05 {
                drop = true;
                break;
            } else if right_len > left_len {
                keep_start = right.0;
                keep_end = right.1;
            } else {
                keep_start = left.0;
                keep_end = left.1;
            }
        }

        if drop || !apply_visible_segment(c, keep_start, keep_end) {
            c["__native_drop"] = Value::from(true);
        }
    }

    clips.retain(|c| !c.get("__native_drop").and_then(|v| v.as_bool()).unwrap_or(false));
    for c in clips.iter_mut() {
        if let Some(o) = c.as_object_mut() {
            o.remove("__native_drop");
        }
    }
    clips.sort_by(|a, b| {
        f(a, "timeline_start")
            .partial_cmp(&f(b, "timeline_start"))
            .unwrap_or(std::cmp::Ordering::Equal)
    });
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
                    let fz = is_freeze_v(&c);
                    let has_se = c.get("source_end").map(|v| v.is_number()).unwrap_or(false);
                    let mut leftv = c.clone();
                    setf(&mut leftv, "timeline_end", t);
                    if has_se && !fz {
                        let ss = f(&c, "source_start");
                        setf(&mut leftv, "source_end", ss + d);
                    }
                    let mut rightv = c.clone();
                    n += 1;
                    rightv["id"] = Value::from(format!("{}__ns_{}_{}", sid(&c), salt, n));
                    setf(&mut rightv, "timeline_start", t);
                    if has_se && !fz {
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

/// Duplicate the selection: NOTHING else on the timeline ever moves (no ripple — a
/// global shift bred unintended gaps). Placement:
///   1. right after the block on the SAME lanes, if that span is free on every lane, else
///   2. at the ORIGINAL time on another lane with space (per source lane; a new lane is
///      appended when none fits) — the red-flagged invisible-overlap case can't happen.
/// Linked A/V copies get a fresh shared link_id so they link to each other, not the originals.
pub fn duplicate_clips(root: &mut Value, ids: &[String], salt: u64) {
    // block bounds
    let mut bs = f64::MAX;
    let mut be = f64::MIN;
    if let Some(tracks) = tracks_ref(root) {
        for tr in tracks {
            for c in tr.get("clips").and_then(|c| c.as_array()).unwrap_or(&vec![]) {
                if ids.contains(&sid(c)) {
                    bs = bs.min(f(c, "timeline_start"));
                    be = be.max(f(c, "timeline_end"));
                }
            }
        }
    }
    if !(be > bs) {
        return;
    }
    let d = be - bs;
    // can every copy land at +d on its own lane without touching a non-selected clip?
    let mut fits_after = true;
    if let Some(tracks) = tracks_ref(root) {
        'outer: for tr in tracks {
            let clips = tr.get("clips").and_then(|c| c.as_array()).cloned().unwrap_or_default();
            for c in &clips {
                if !ids.contains(&sid(c)) {
                    continue;
                }
                let (nts, nte) = (f(c, "timeline_start") + d, f(c, "timeline_end") + d);
                for o in &clips {
                    if ids.contains(&sid(o)) {
                        continue;
                    }
                    if f(o, "timeline_start") < nte - 0.002 && nts < f(o, "timeline_end") - 0.002 {
                        fits_after = false;
                        break 'outer;
                    }
                }
            }
        }
    }
    let mut n = 0u64;
    let mut new_links: std::collections::HashMap<String, String> = Default::default();
    let mut mk_copy = |c: &Value, shift: f64| -> Value {
        let mut copy = c.clone();
        n += 1;
        copy["id"] = Value::from(format!("{}__dup_{}_{}", sid(c), salt, n));
        setf(&mut copy, "timeline_start", f(c, "timeline_start") + shift);
        setf(&mut copy, "timeline_end", f(c, "timeline_end") + shift);
        if let Some(l) = link(c) {
            let nl = new_links
                .entry(l)
                .or_insert_with(|| format!("lk_dup_{}_{}", salt, n))
                .clone();
            copy["link_id"] = Value::from(nl);
        }
        copy
    };
    if fits_after {
        // contiguous on the same lanes
        let Some(tracks) = tracks_mut(root) else { return };
        for tr in tracks {
            let Some(cs) = tr.get_mut("clips").and_then(|c| c.as_array_mut()) else { continue };
            let copies: Vec<Value> = cs
                .iter()
                .filter(|c| ids.contains(&sid(c)))
                .map(|c| mk_copy(c, d))
                .collect();
            cs.extend(copies);
        }
        return;
    }
    // per source lane: copies keep their ORIGINAL times on another lane with space
    let n_tracks = tracks_ref(root).map(|t| t.len()).unwrap_or(0);
    for si in 0..n_tracks {
        let (copies, kind): (Vec<Value>, String) = {
            let Some(tracks) = tracks_ref(root) else { return };
            let tr = &tracks[si];
            let kind = tr.get("type").and_then(|v| v.as_str()).unwrap_or("").to_string();
            let copies = tr
                .get("clips")
                .and_then(|c| c.as_array())
                .map(|cs| {
                    cs.iter()
                        .filter(|c| ids.contains(&sid(c)))
                        .map(|c| mk_copy(c, 0.0))
                        .collect()
                })
                .unwrap_or_default();
            (copies, kind)
        };
        if copies.is_empty() {
            continue;
        }
        let want_audio = kind == "audio";
        // first other lane of the same category where every copy fits
        let target: Option<usize> = {
            let tracks = tracks_ref(root).unwrap();
            (0..tracks.len()).find(|&ti| {
                if ti == si {
                    return false;
                }
                let tk = tracks[ti].get("type").and_then(|v| v.as_str()).unwrap_or("");
                if (tk == "audio") != want_audio {
                    return false;
                }
                let empty = vec![];
                let cs = tracks[ti].get("clips").and_then(|c| c.as_array()).unwrap_or(&empty);
                copies.iter().all(|cp| {
                    cs.iter().all(|o| {
                        !(f(o, "timeline_start") < f(cp, "timeline_end") - 0.002
                            && f(cp, "timeline_start") < f(o, "timeline_end") - 0.002)
                    })
                })
            })
        };
        let Some(tracks) = tracks_mut(root) else { return };
        match target {
            Some(ti) => {
                if let Some(cs) = tracks[ti].get_mut("clips").and_then(|c| c.as_array_mut()) {
                    cs.extend(copies);
                }
            }
            None => {
                let lane_kind = if want_audio { "audio" } else { "overlay" };
                tracks.push(serde_json::json!({
                    "id": format!("{lane_kind}_dup_{salt}_{si}"),
                    "type": lane_kind,
                    "clips": copies,
                }));
            }
        }
    }
}

/// Toggle a lane header flag (locked / hidden / muted / solo / magnet) on track `ti`.
pub fn set_track_flag(raw: &mut Value, ti: usize, key: &str, val: bool) {
    if let Some(tracks) = tracks_mut(raw) {
        if let Some(tr) = tracks.get_mut(ti) {
            tr[key] = Value::from(val);
        }
    }
}

/// Clips ATTACHED to the given (about to be deleted) clips: a clip is attached when its
/// HEAD sits over a deleted clip's span on a lane IN FRONT of it (higher stack index) —
/// captions/effects riding a video, per Filmora/DaVinci. Locked lanes are left alone.
/// Audio lanes are excluded (linked audio follows via expand_links; BGM is independent).
pub fn attached_to(raw: &Value, ids: &[String]) -> Vec<String> {
    let main_video = tracks_ref(raw).and_then(|tracks| {
        tracks
            .iter()
            .position(|tr| tr.get("type").and_then(|v| v.as_str()) == Some("video"))
    });
    let mut spans: Vec<(usize, f64, f64)> = Vec::new(); // (lane, ts, te)
    if let Some(tracks) = tracks_ref(raw) {
        for (ti, tr) in tracks.iter().enumerate() {
            if Some(ti) != main_video {
                continue;
            }
            for c in tr.get("clips").and_then(|c| c.as_array()).unwrap_or(&vec![]) {
                if ids.contains(&sid(c)) {
                    spans.push((ti, f(c, "timeline_start"), f(c, "timeline_end")));
                }
            }
        }
    }
    let mut out: Vec<String> = Vec::new();
    if let Some(tracks) = tracks_ref(raw) {
        for (ti, tr) in tracks.iter().enumerate() {
            let kind = tr.get("type").and_then(|v| v.as_str()).unwrap_or("");
            if kind == "audio" || tr.get("locked").and_then(|v| v.as_bool()).unwrap_or(false) {
                continue;
            }
            for c in tr.get("clips").and_then(|c| c.as_array()).unwrap_or(&vec![]) {
                let id = sid(c);
                if ids.contains(&id) || out.contains(&id) {
                    continue;
                }
                let head = f(c, "timeline_start");
                if spans
                    .iter()
                    .any(|&(si, ts, te)| ti > si && head >= ts - 1e-6 && head < te - 1e-6)
                {
                    out.push(id);
                }
            }
        }
    }
    out
}

/// Magnet-lane delete: remove the clips, remove clips ATTACHED to them (a clip is attached
/// to whichever deleted clip its HEAD sits on — Filmora/DaVinci rule; audio lanes excluded,
/// BGM is independent), then close the gaps (ripple). `ids` should already be link-expanded.
pub fn magnet_delete(raw: &mut Value, ids: &[String]) {
    // spans of the deleted clips
    let mut spans: Vec<(f64, f64)> = Vec::new();
    let mut src_tracks: Vec<usize> = Vec::new();
    if let Some(tracks) = tracks_ref(raw) {
        for (ti, tr) in tracks.iter().enumerate() {
            for c in tr.get("clips").and_then(|c| c.as_array()).unwrap_or(&vec![]) {
                if ids.contains(&sid(c)) {
                    spans.push((f(c, "timeline_start"), f(c, "timeline_end")));
                    if !src_tracks.contains(&ti) {
                        src_tracks.push(ti);
                    }
                }
            }
        }
    }
    // attached clips are handled generically by the caller (attached_to) for every
    // deletion; here we only close the gap
    let _ = src_tracks;
    ripple_delete(raw, ids);
}

/// Ripple-shift every clip starting at/after `t` right by `d` (all lanes).
fn ripple_open(raw: &mut Value, t: f64, d: f64) {
    for_each_clip(raw, |c| {
        let cs = f(c, "timeline_start");
        if cs >= t - 1e-6 {
            let ce = f(c, "timeline_end");
            setf(c, "timeline_start", cs + d);
            setf(c, "timeline_end", ce + d);
        }
    });
}

/// Freeze-frame: split `id` at `t`, open a `dur`-second hole, and drop in a clip that
/// holds the frame (exporter convention: source_start >= source_end = freeze).
pub fn freeze_frame(raw: &mut Value, id: &str, t: f64, dur: f64, salt: u64) {
    freeze_frame_with_still(raw, id, t, dur, salt, None, 0.0)
}

/// `back` = one source-frame duration (seconds). The split lands at the END of the
/// displayed frame, so `back` rewinds the freeze still AND the right-hand pieces of the
/// frozen clip's link group by exactly one frame. Net user-visible contract:
/// left clip's LAST frame == the still == right clip's FIRST frame == what was on screen.
pub fn freeze_frame_with_still(
    raw: &mut Value,
    id: &str,
    t: f64,
    dur: f64,
    salt: u64,
    still_rel: Option<String>,
    back: f64,
) {
    // Round ONCE to the same 3dp grid setf writes: the snap offset (+0.0002) put the
    // ripple threshold 0.2ms ABOVE the rounded split point, so the right piece of the
    // split escaped the shift and kept playing under the freeze.
    let t = (t * 1000.0).round() / 1000.0;
    // capture BEFORE splitting: the source time under the playhead + the track/asset
    let mut info: Option<(String, f64)> = None; // (asset_id, src_at)
    let mut track_idx: Option<usize> = None;
    if let Some(tracks) = tracks_ref(raw) {
        for (ti, tr) in tracks.iter().enumerate() {
            for c in tr.get("clips").and_then(|c| c.as_array()).unwrap_or(&vec![]) {
                if sid(c) == id {
                    let src = f(c, "source_start") + (t - f(c, "timeline_start"));
                    if let Some(aid) = c.get("asset_id").and_then(|v| v.as_str()) {
                        info = Some((aid.to_string(), src));
                        track_idx = Some(ti);
                    }
                }
            }
        }
    }
    let Some((aid, src)) = info else { return };
    // FULL CLONE of the source clip: position / size / pop-out effect / crop / volume /
    // style all survive the freeze — only the identity and the time fields change
    // (a bare {asset,time} clip snapped pop-outs back to full frame: the reported bug)
    let mut template: Option<Value> = None;
    if let Some(tracks) = tracks_ref(raw) {
        for tr in tracks {
            for c in tr.get("clips").and_then(|c| c.as_array()).unwrap_or(&vec![]) {
                if sid(c) == id {
                    template = Some(c.clone());
                }
            }
        }
    }
    // split EVERY clip straddling t (all lanes): a straddler that merely shifted kept
    // playing UNDER the frozen span (video + still at once). Strict 映像→静止画→映像.
    let mut straddlers: Vec<String> = Vec::new();
    if let Some(tracks) = tracks_ref(raw) {
        for tr in tracks {
            for c in tr.get("clips").and_then(|c| c.as_array()).unwrap_or(&vec![]) {
                let (ts, te) = (f(c, "timeline_start"), f(c, "timeline_end"));
                if t > ts + 0.05 && t < te - 0.05 {
                    straddlers.push(sid(c));
                }
            }
        }
    }
    let ids = expand_links(raw, &straddlers);
    split_clips(raw, &ids, t, salt);
    if back > 1e-6 {
        let group = expand_links(raw, &[id.to_string()]);
        for c in clips_iter_mut(raw) {
            let cid = sid(c);
            let is_right_piece = group
                .iter()
                .any(|g| cid.starts_with(&format!("{g}__ns_{salt}_")));
            if is_right_piece && !is_freeze_v(c) {
                let ss = f(c, "source_start");
                setf(c, "source_start", (ss - back).max(0.0));
            }
        }
    }
    ripple_open(raw, t, dur);
    let mut clip = template.unwrap_or_else(|| serde_json::json!({"asset_id": aid}));
    clip["id"] = Value::from(format!("fz_{salt}_{}", &aid[..8.min(aid.len())]));
    setf(&mut clip, "timeline_start", t);
    setf(&mut clip, "timeline_end", t + dur);
    let fsrc = (src - back).max(0.0);
    setf(&mut clip, "source_start", fsrc);
    setf(&mut clip, "source_end", fsrc);
    if let Some(o) = clip.as_object_mut() {
        o.remove("link_id"); // no linked audio: a freeze is silent
        o.insert("freeze".into(), Value::from(true));
        if let Some(p) = still_rel {
            o.insert("freeze_still".into(), Value::from(p));
        }
    }
    if let (Some(tracks), Some(ti)) = (tracks_mut(raw), track_idx) {
        if let Some(cs) = tracks[ti].get_mut("clips").and_then(|c| c.as_array_mut()) {
            cs.push(clip);
        }
    }
}

/// Insert a library asset at `t` on the main video lane (ripple insert on all lanes),
/// with a linked audio clip when the asset has sound.
pub fn insert_asset(raw: &mut Value, t: f64, dur: f64, asset_id: &str, has_audio: bool, salt: u64) {
    ripple_open(raw, t, dur);
    let link = format!("lk_ins_{salt}");
    let vclip = serde_json::json!({
        "id": format!("ins_v_{salt}"),
        "asset_id": asset_id,
        "timeline_start": (t * 1000.0).round() / 1000.0,
        "timeline_end": ((t + dur) * 1000.0).round() / 1000.0,
        "source_start": 0.0,
        "source_end": (dur * 1000.0).round() / 1000.0,
        "link_id": link,
    });
    let Some(tracks) = tracks_mut(raw) else { return };
    let vt = tracks
        .iter()
        .position(|tr| tr.get("type").and_then(|v| v.as_str()) == Some("video"));
    match vt {
        Some(ti) => {
            if let Some(cs) = tracks[ti].get_mut("clips").and_then(|c| c.as_array_mut()) {
                cs.push(vclip);
            }
        }
        None => tracks.push(serde_json::json!({"id": "video_ins", "type": "video", "clips": [vclip]})),
    }
    if has_audio {
        let aclip = serde_json::json!({
            "id": format!("ins_a_{salt}"),
            "asset_id": asset_id,
            "timeline_start": (t * 1000.0).round() / 1000.0,
            "timeline_end": ((t + dur) * 1000.0).round() / 1000.0,
            "source_start": 0.0,
            "source_end": (dur * 1000.0).round() / 1000.0,
            "link_id": link,
        });
        let at = tracks
            .iter()
            .position(|tr| tr.get("type").and_then(|v| v.as_str()) == Some("audio"));
        match at {
            Some(ti) => {
                if let Some(cs) = tracks[ti].get_mut("clips").and_then(|c| c.as_array_mut()) {
                    cs.push(aclip);
                }
            }
            None => tracks.push(serde_json::json!({"id": "audio_ins", "type": "audio", "clips": [aclip]})),
        }
    }
}

/// Add a region effect clip (blur/mosaic) on the effect lane (created when missing).
pub fn add_effect_clip(
    raw: &mut Value,
    t: f64,
    dur: f64,
    region: (f64, f64, f64, f64),
    style: &str,
    salt: u64,
) {
    let clip = serde_json::json!({
        "id": format!("fx_{salt}"),
        "timeline_start": (t * 1000.0).round() / 1000.0,
        "timeline_end": ((t + dur) * 1000.0).round() / 1000.0,
        "style": style,
        "region": {
            "x": (region.0 * 10000.0).round() / 10000.0,
            "y": (region.1 * 10000.0).round() / 10000.0,
            "width": (region.2 * 10000.0).round() / 10000.0,
            "height": (region.3 * 10000.0).round() / 10000.0,
        },
    });
    let Some(tracks) = tracks_mut(raw) else { return };
    // Place on the FRONT-most (display top) non-audio lane whose [t, t+dur) span is
    // free — never on top of existing clips. Lanes are just layers (no effect-lane
    // special casing); when every lane is occupied, open a new top lane.
    let (t0, t1) = (t, t + dur);
    let free_lane = (0..tracks.len()).rev().find(|&ti| {
        let tr = &tracks[ti];
        let kind = tr.get("type").and_then(|v| v.as_str()).unwrap_or("");
        if kind == "audio"
            || tr.get("locked").and_then(|v| v.as_bool()).unwrap_or(false)
            || tr.get("hidden").and_then(|v| v.as_bool()).unwrap_or(false)
        {
            return false;
        }
        tr.get("clips")
            .and_then(|c| c.as_array())
            .map(|cs| {
                cs.iter().all(|c| {
                    let cs_ = c.get("timeline_start").and_then(|v| v.as_f64()).unwrap_or(0.0);
                    let ce = c.get("timeline_end").and_then(|v| v.as_f64()).unwrap_or(0.0);
                    ce <= t0 + 0.001 || cs_ >= t1 - 0.001
                })
            })
            .unwrap_or(true)
    });
    match free_lane {
        Some(ti) => {
            if let Some(cs) = tracks[ti].get_mut("clips").and_then(|c| c.as_array_mut()) {
                cs.push(clip);
            }
        }
        None => {
            let front = tracks
                .iter()
                .enumerate()
                .filter(|(_, tr)| tr.get("type").and_then(|v| v.as_str()) != Some("audio"))
                .map(|(i, _)| i)
                .max();
            let insert_at = front.map(|i| i + 1).unwrap_or(tracks.len());
            tracks.insert(insert_at, serde_json::json!({"type": "overlay", "clips": [clip]}));
        }
    }
}

/// Record a freeze clip's materialized still path.
pub fn set_freeze_still(raw: &mut Value, id: &str, rel: &str) {
    for_each_clip(raw, |c| {
        if c.get("id").and_then(|v| v.as_str()) == Some(id) {
            c["freeze_still"] = Value::from(rel);
        }
    });
}

/// Set a clip's style string (effect clips: gaussian / mosaic).
pub fn set_style(raw: &mut Value, id: &str, style: &str) {
    for_each_clip(raw, |c| {
        if c.get("id").and_then(|v| v.as_str()) == Some(id) {
            c["style"] = Value::from(style);
        }
    });
}

fn merge_object(dst: &mut Value, patch: &Value) {
    let Some(src) = patch.as_object() else { return };
    if !dst.is_object() {
        *dst = serde_json::json!({});
    }
    let Some(out) = dst.as_object_mut() else { return };
    for (k, v) in src {
        if v.is_null() {
            out.remove(k);
        } else {
            out.insert(k.clone(), v.clone());
        }
    }
}

/// Merge a designed-caption style object into selected caption clips.
pub fn patch_caption_style(raw: &mut Value, ids: &[String], patch: Value) {
    for_each_clip(raw, |c| {
        let id = c.get("id").and_then(|v| v.as_str()).unwrap_or("");
        if !ids.iter().any(|want| want == id) {
            return;
        }
        let o = c.as_object_mut().unwrap();
        let style = o.entry("style").or_insert_with(|| serde_json::json!({}));
        merge_object(style, &patch);
    });
}

/// Merge a designed-caption style object into every caption clip.
pub fn patch_all_caption_style(raw: &mut Value, patch: Value) {
    for_each_clip(raw, |c| {
        let is_caption = c.get("track").and_then(|v| v.as_str()) == Some("caption")
            || c.get("text").and_then(|v| v.as_str()).is_some();
        if !is_caption {
            return;
        }
        let o = c.as_object_mut().unwrap();
        let style = o.entry("style").or_insert_with(|| serde_json::json!({}));
        merge_object(style, &patch);
    });
}

/// Set a clip's timeline span directly (inspector numeric edit).
pub fn set_span(raw: &mut Value, id: &str, ts: f64, te: f64) {
    for_each_clip(raw, |c| {
        if c.get("id").and_then(|v| v.as_str()) == Some(id) {
            setf(c, "timeline_start", ts.max(0.0));
            setf(c, "timeline_end", te.max(ts + 0.1));
        }
    });
}

fn tracks_ref(root: &Value) -> Option<&Vec<Value>> {
    root.get(0)?
        .get("timeline")?
        .get("sequence")?
        .get("tracks")?
        .as_array()
}

fn tracks_mut(root: &mut Value) -> Option<&mut Vec<Value>> {
    root.get_mut(0)?
        .get_mut("timeline")?
        .get_mut("sequence")?
        .get_mut("tracks")?
        .as_array_mut()
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
    // Closing the gap = REMOVING the time interval [ts,te) from the whole timeline.
    // Just shifting clips that start after te (the old code) smashed shifted clips into
    // clips STRADDLING the span (a caption running across the cut kept its full length
    // while everything behind it moved left -> same-track overlap). Correct mapping:
    // map(t) = t < ts ? t : max(ts, t - d) applied to both edges; a clip that collapses
    // lived inside the span and is dropped; source in/out points follow the cut edges.
    for (ts, te) in merged.into_iter().rev() {
        let d = te - ts;
        let mut dead: Vec<String> = Vec::new();
        for_each_clip(raw, |c| {
            let cs = f(c, "timeline_start");
            let ce = f(c, "timeline_end");
            if ce <= ts + 1e-6 {
                return; // fully before the removed span
            }
            let map = |t: f64| if t <= ts { t } else { (t - d).max(ts) };
            let (ncs, nce) = (map(cs), map(ce));
            if nce - ncs < 0.05 {
                dead.push(sid(c));
                return;
            }
            let has_src = c.get("source_start").map(|v| v.is_number()).unwrap_or(false);
            if has_src {
                // head of the clip removed (clip starts inside the span): in-point advances
                if cs > ts - 1e-6 && cs < te {
                    let head_cut = (te.min(ce) - cs).max(0.0);
                    setf(c, "source_start", f(c, "source_start") + head_cut);
                }
                // tail / middle removed: out-point retreats by the rest of the cut
                let removed = (ce.min(te) - cs.max(ts)).max(0.0);
                let head_cut = if cs > ts - 1e-6 && cs < te { (te.min(ce) - cs).max(0.0) } else { 0.0 };
                let tail_cut = (removed - head_cut).max(0.0);
                if tail_cut > 1e-6 && c.get("source_end").map(|v| v.is_number()).unwrap_or(false) {
                    setf(c, "source_end", f(c, "source_end") - tail_cut);
                }
            }
            setf(c, "timeline_start", ncs);
            setf(c, "timeline_end", nce);
        });
        if !dead.is_empty() {
            delete_clips(raw, &dead);
        }
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
pub fn move_to_new_top_track(raw: &mut serde_json::Value, ids: &[String]) {
    let Some(tracks) = raw
        .get_mut(0)
        .and_then(|r| r.get_mut("timeline"))
        .and_then(|x| x.get_mut("sequence"))
        .and_then(|x| x.get_mut("tracks"))
        .and_then(|x| x.as_array_mut())
    else {
        return;
    };
    let mut moved: Vec<serde_json::Value> = Vec::new();
    let mut lane_kind: Option<String> = None;
    let mut src_track: Option<usize> = None;
    for (ti, tr) in tracks.iter_mut().enumerate() {
        let tkind = tr.get("type").and_then(|v| v.as_str()).unwrap_or("").to_string();
        if tkind == "audio" {
            continue;
        }
        if let Some(clips) = tr.get_mut("clips").and_then(|c| c.as_array_mut()) {
            let mut i = 0;
            while i < clips.len() {
                let id = clips[i].get("id").and_then(|v| v.as_str()).unwrap_or("");
                if ids.iter().any(|x| x == id) {
                    if lane_kind.is_none() {
                        lane_kind = Some(tkind.clone());
                        src_track = Some(ti);
                    }
                    moved.push(clips.remove(i));
                } else {
                    i += 1;
                }
            }
        }
    }
    if moved.is_empty() {
        return;
    }
    let front = tracks
        .iter()
        .enumerate()
        .filter(|(_, tr)| tr.get("type").and_then(|v| v.as_str()) != Some("audio"))
        .map(|(i, _)| i)
        .max();
    if src_track == front {
        if let Some(ti) = src_track {
            if let Some(arr) = tracks[ti].get_mut("clips").and_then(|c| c.as_array_mut()) {
                arr.extend(moved);
            }
        }
        return;
    }
    let tkind = lane_kind.unwrap_or_else(|| "overlay".to_string());
    for c in &mut moved {
        if let Some(o) = c.as_object_mut() {
            o.insert("track".into(), serde_json::json!(tkind));
        }
    }
    let insert_at = front.map(|i| i + 1).unwrap_or(tracks.len());
    tracks.insert(insert_at, serde_json::json!({"type": tkind, "clips": moved}));
}

pub fn set_position(raw: &mut serde_json::Value, id: &str, x: f64, y: f64, w: f64, h: f64) {
    set_position_many(raw, &[id.to_string()], x, y, w, h);
}

pub fn set_position_many(raw: &mut serde_json::Value, ids: &[String], x: f64, y: f64, w: f64, h: f64) {
    for_each_clip(raw, |c| {
        let id = c.get("id").and_then(|v| v.as_str()).unwrap_or("");
        if !ids.iter().any(|i| i == id) {
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

/// Per-edge crop (fractions 0..0.9). All-zero removes the crop entirely.
pub fn set_crop_many(raw: &mut serde_json::Value, ids: &[String], l: f64, t: f64, r: f64, b: f64) {
    for_each_clip(raw, |c| {
        let id = c.get("id").and_then(|v| v.as_str()).unwrap_or("");
        if !ids.iter().any(|i| i == id) {
            return;
        }
        let o = c.as_object_mut().unwrap();
        if l + t + r + b < 1e-4 {
            o.insert("crop".into(), serde_json::Value::Null);
        } else {
            let cl = |v: f64| ((v.clamp(0.0, 0.9)) * 1000.0).round() / 1000.0;
            o.insert(
                "crop".into(),
                serde_json::json!({"left": cl(l), "top": cl(t), "right": cl(r), "bottom": cl(b)}),
            );
        }
    });
}

/// Attach / update / remove the SAM tracked-blur binding on a region-effect clip.
pub fn set_blur_track(raw: &mut serde_json::Value, id: &str, value: Option<serde_json::Value>) {
    for_each_clip(raw, |c| {
        if c.get("id").and_then(|v| v.as_str()) == Some(id) {
            let o = c.as_object_mut().unwrap();
            match &value {
                Some(v) => {
                    o.insert("blur_track".into(), v.clone());
                }
                None => {
                    o.remove("blur_track");
                }
            }
        }
    });
}

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
