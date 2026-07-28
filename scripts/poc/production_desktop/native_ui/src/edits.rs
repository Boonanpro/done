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
    v[k] = Value::from((val * 1_000_000_000.0).round() / 1_000_000_000.0);
}

/// Canonical timeline clock: every visual/image/caption boundary is an integer
/// sequence-frame index. Linked audio follows its visual partner; independent audio may
/// retain sample/sub-frame precision. This removes the impossible state where an arrow
/// key can never land on a clip edge between two output frames.
pub fn quantize_timeline_frames(root: &mut Value) {
    let Some(seq) = root
        .get_mut(0)
        .and_then(|r| r.get_mut("timeline"))
        .and_then(|t| t.get_mut("sequence"))
    else {
        return;
    };
    let fps = seq
        .get("frame_rate")
        .and_then(|v| v.as_f64())
        .filter(|v| v.is_finite() && *v > 1.0)
        .unwrap_or(30.0);
    let q = |t: f64| ((t.max(0.0) * fps).round() / fps * 1_000_000_000.0).round()
        / 1_000_000_000.0;
    let q_end = |t: f64| ((t.max(0.0) * fps).ceil() / fps * 1_000_000_000.0).round()
        / 1_000_000_000.0;
    let step = 1.0 / fps;
    let Some(tracks) = seq.get_mut("tracks").and_then(|v| v.as_array_mut()) else {
        return;
    };
    let mut max_end = 0.0f64;
    for tr in tracks {
        let audio = tr.get("type").and_then(|v| v.as_str()) == Some("audio");
        let Some(clips) = tr.get_mut("clips").and_then(|v| v.as_array_mut()) else {
            continue;
        };
        for clip in clips {
            if audio && clip.get("link_id").and_then(|v| v.as_str()).is_none() {
                max_end = max_end.max(f(clip, "timeline_end"));
                continue;
            }
            let start = q(f(clip, "timeline_start"));
            let mut end = q(f(clip, "timeline_end"));
            if end <= start {
                end = q(start + step);
            }
            setf(clip, "timeline_start", start);
            setf(clip, "timeline_end", end);
            max_end = max_end.max(end);
        }
    }
    let old_duration = seq.get("duration").and_then(|v| v.as_f64()).unwrap_or(0.0);
    // The container duration must never round down across independent sub-frame audio.
    seq["duration"] = Value::from(q_end(old_duration.max(max_end)));
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
    // Clamp once for the whole selection. Clamping per clip made a multi-selection
    // compress/collapse at t=0 because each member received a different delta.
    let min_start = clips_iter_mut(root)
        .into_iter()
        .filter(|c| ids.contains(&sid(c)))
        .map(|c| f(c, "timeline_start"))
        .fold(f64::MAX, f64::min);
    let group_dt = if min_start.is_finite() { dt.max(-min_start) } else { dt };
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
                setf(c, "timeline_start", ts + group_dt);
                setf(c, "timeline_end", te + group_dt);
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
                if !clips.iter().any(|c| ids.contains(&sid(c))) {
                    continue;
                }
                // source-less clips (region effects) have no in-point: no left-extension limit
                let min_source_room = clips
                    .iter()
                    .filter(|c| ids.contains(&sid(c)))
                    .map(|c| {
                        if c.get("source_start").map(|v| v.is_number()).unwrap_or(false) {
                            f(c, "source_start")
                        } else {
                            f64::INFINITY
                        }
                    })
                    .fold(f64::INFINITY, f64::min);
                let min_duration = clips
                    .iter()
                    .filter(|c| ids.contains(&sid(c)))
                    .map(|c| f(c, "timeline_end") - f(c, "timeline_start"))
                    .fold(f64::INFINITY, f64::min);
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
        // keyframes are clip-relative and glued to SOURCE frames: the in-point moved
        // by d, so every key slides back by d (same rule as trim_one_clip)
        shift_region_keys(&mut clips[idx], -d);
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
            shift_region_keys(&mut clips[idx], restore);
            grow -= restore;
        }
    }
    if grow > 1e-6 {
        let cur_end = f(&clips[idx], "timeline_end");
        let cur_ss = f(&clips[idx], "source_start");
        setf(&mut clips[idx], "source_start", (cur_ss - grow).max(0.0));
        setf(&mut clips[idx], "timeline_end", cur_end + grow);
        // in-point moved earlier by grow while timeline_start stayed: the same source
        // frame now sits grow seconds LATER in clip-relative time
        shift_region_keys(&mut clips[idx], grow);
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
    let has_ss = c.get("source_start").map(|v| v.is_number()).unwrap_or(false);
    let has_se = c.get("source_end").map(|v| v.is_number()).unwrap_or(false);
    if is_freeze_v(c) {
        // a freeze's length is TIMELINE-only: never touch its source fields.
        // (the old video math turned an extended freeze back into moving video)
        if left {
            let nts = new_t.clamp(0.0, te - 0.05);
            setf(c, "timeline_start", nts);
            shift_region_keys(c, ts - nts);
        } else {
            setf(c, "timeline_end", new_t.max(ts + 0.05));
        }
        return;
    }
    if left {
        let nt = new_t.clamp(0.0, te - 0.05);
        let mut d = nt - ts;
        if has_ss {
            // real media: can't extend before the source's first frame. Source-less
            // clips (region effects) have no such limit — they extend freely.
            d = d.max(-ss);
        }
        if has_se {
            // never push the in-point past the out-point (that flipped the clip
            // into an accidental freeze by the implicit se<=ss convention)
            let se = f(c, "source_end");
            d = d.min(se - ss - 0.05);
        }
        let nts = (ts + d).max(0.0);
        setf(c, "timeline_start", nts);
        if has_ss {
            setf(c, "source_start", (ss + d).max(0.0));
        }
        // position keyframes are clip-relative: keep each pinned to the same
        // TIMELINE moment when the clip's left edge moves
        shift_region_keys(c, ts - nts);
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

/// Shift every keyframe (region AND transform) by dt seconds (used when the clip's
/// left edge moves: rel times must keep pointing at the same absolute timeline moment).
fn shift_region_keys(c: &mut Value, dt: f64) {
    if dt.abs() < 1e-9 {
        return;
    }
    for field in ["region_keys", "transform_keys"] {
        let Some(keys) = c.get_mut(field).and_then(|v| v.as_array_mut()) else {
            continue;
        };
        for k in keys.iter_mut() {
            if let Some(t) = k.get("t").and_then(|v| v.as_f64()) {
                if let Some(o) = k.as_object_mut() {
                    o.insert("t".into(), serde_json::json!(((t + dt) * 1000.0).round() / 1000.0));
                }
            }
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
                    // position keyframes are clip-relative: partition them at the cut and
                    // re-base the right half, pinning the cut-moment position on both
                    // sides — a verbatim clone REPLAYED the left half's motion after the
                    // cut (「前半のキーが後半にクローンされる」)
                    split_region_keys(&c, d, &mut leftv, &mut rightv);
                    split_transform_keys(&c, d, &mut leftv, &mut rightv);
                    out.push(leftv);
                    out.push(rightv);
                }
                *cs = out;
            }
        }
    }
}

/// Linear interpolation of a region_keys array at clip-relative time `rel`
/// (same math as model::Clip::region_at — ends clamp to the first/last key).
fn region_keys_pos_at(keys: &[Value], rel: f64, bw: f64, bh: f64) -> Option<(f64, f64, f64, f64)> {
    let mut ks: Vec<(f64, f64, f64, f64, f64)> = keys
        .iter()
        .filter_map(|k| {
            Some((
                k.get("t")?.as_f64()?,
                k.get("x")?.as_f64()?,
                k.get("y")?.as_f64()?,
                k.get("w").and_then(|v| v.as_f64()).unwrap_or(bw),
                k.get("h").and_then(|v| v.as_f64()).unwrap_or(bh),
            ))
        })
        .collect();
    if ks.is_empty() {
        return None;
    }
    ks.sort_by(|a, b| a.0.total_cmp(&b.0));
    if rel <= ks[0].0 {
        let f = &ks[0];
        return Some((f.1, f.2, f.3, f.4));
    }
    if rel >= ks[ks.len() - 1].0 {
        let l = &ks[ks.len() - 1];
        return Some((l.1, l.2, l.3, l.4));
    }
    let i = ks.iter().position(|k| k.0 > rel).unwrap();
    let (a, b) = (&ks[i - 1], &ks[i]);
    let fr = ((rel - a.0) / (b.0 - a.0).max(1e-9)).clamp(0.0, 1.0);
    Some((
        a.1 + (b.1 - a.1) * fr,
        a.2 + (b.2 - a.2) * fr,
        a.3 + (b.3 - a.3) * fr,
        a.4 + (b.4 - a.4) * fr,
    ))
}

/// Partition a split clip's position keyframes at cut offset `d`: the left half keeps
/// keys up to the cut, the right half gets keys after the cut RE-BASED to its new
/// start, and both sides get a boundary key with the interpolated cut-moment position
/// so neither half moves at the instant of the cut.
fn split_region_keys(orig: &Value, d: f64, leftv: &mut Value, rightv: &mut Value) {
    let Some(keys) = orig.get("region_keys").and_then(|v| v.as_array()).cloned() else {
        return;
    };
    if keys.is_empty() {
        return;
    }
    let q3 = |v: f64| (v * 1000.0).round() / 1000.0;
    let q4 = |v: f64| (v * 10000.0).round() / 10000.0;
    let kt_of = |k: &Value| k.get("t").and_then(|v| v.as_f64());
    let had_before = keys.iter().any(|k| kt_of(k).map(|kt| kt < d - KEY_REPLACE_EPS).unwrap_or(false));
    let had_after = keys.iter().any(|k| kt_of(k).map(|kt| kt > d + KEY_REPLACE_EPS).unwrap_or(false));
    let (bw, bh) = orig
        .get("region")
        .map(|r| {
            (
                r.get("width").and_then(|v| v.as_f64()).unwrap_or(0.1),
                r.get("height").and_then(|v| v.as_f64()).unwrap_or(0.1),
            )
        })
        .unwrap_or((0.1, 0.1));
    let cut_pos = region_keys_pos_at(&keys, d, bw, bh);
    let mut lk: Vec<Value> = keys
        .iter()
        .filter(|k| kt_of(k).map(|kt| kt <= d + KEY_REPLACE_EPS).unwrap_or(false))
        .cloned()
        .collect();
    let mut rk: Vec<Value> = keys
        .iter()
        .filter_map(|k| {
            let kt = kt_of(k)?;
            if kt < d - KEY_REPLACE_EPS {
                return None;
            }
            let mut k2 = k.clone();
            k2["t"] = serde_json::json!(q3((kt - d).max(0.0)));
            Some(k2)
        })
        .collect();
    if let Some((px, py, pw, ph)) = cut_pos {
        // boundary keys ONLY where motion actually crosses the cut (keys on BOTH
        // sides): a cut beyond all keys must not sprinkle a visible key at the cut —
        // the keyless side gets the position written into its BASE rect instead
        if !lk.is_empty()
            && had_after
            && !lk.iter().any(|k| kt_of(k).map(|kt| (kt - d).abs() <= KEY_REPLACE_EPS).unwrap_or(false))
        {
            lk.push(serde_json::json!({"t": q3(d), "x": q4(px), "y": q4(py), "w": q4(pw), "h": q4(ph)}));
        }
        if !rk.is_empty()
            && had_before
            && !rk.iter().any(|k| kt_of(k).map(|kt| kt.abs() <= KEY_REPLACE_EPS).unwrap_or(false))
        {
            rk.push(serde_json::json!({"t": 0.0, "x": q4(px), "y": q4(py), "w": q4(pw), "h": q4(ph)}));
        }
    }
    let sort = |v: &mut Vec<Value>| {
        v.sort_by(|a, b| {
            let ta = a.get("t").and_then(|x| x.as_f64()).unwrap_or(0.0);
            let tb = b.get("t").and_then(|x| x.as_f64()).unwrap_or(0.0);
            ta.total_cmp(&tb)
        })
    };
    sort(&mut lk);
    sort(&mut rk);
    for (side, ks) in [(&mut *leftv, lk), (&mut *rightv, rk)] {
        if let Some(o) = side.as_object_mut() {
            if ks.is_empty() {
                o.remove("region_keys");
                // keyless side: hold the cut-moment position AND size via the base rect
                // (same picture, no keyframe diamond appearing out of nowhere)
                if let (Some((px, py, pw, ph)), Some(rg)) =
                    (cut_pos, o.get_mut("region").and_then(|v| v.as_object_mut()))
                {
                    rg.insert("x".into(), serde_json::json!(q4(px.clamp(0.05 - pw, 0.95))));
                    rg.insert("y".into(), serde_json::json!(q4(py.clamp(0.05 - ph, 0.95))));
                    rg.insert("width".into(), serde_json::json!(q4(pw.clamp(0.01, 1.0))));
                    rg.insert("height".into(), serde_json::json!(q4(ph.clamp(0.01, 1.0))));
                }
            } else {
                o.insert("region_keys".into(), Value::Array(ks));
            }
        }
    }
}

/// Base display box of a RAW clip (position wins; else transform scale/pan; else full)
/// — JSON mirror of model::Clip::display_box for split-time interpolation.
fn raw_display_box(c: &Value) -> (f64, f64, f64, f64) {
    if let Some(p) = c.get("position").filter(|p| p.is_object()) {
        let g = |k: &str, d: f64| p.get(k).and_then(|v| v.as_f64()).unwrap_or(d);
        return (g("x", 0.0), g("y", 0.0), g("width", 1.0), g("height", 1.0));
    }
    if let Some(t) = c.get("transform").filter(|t| t.is_object()) {
        let g = |k: &str, d: f64| t.get(k).and_then(|v| v.as_f64()).unwrap_or(d);
        let (s, tx, ty) = (g("scale", 1.0), g("x", 0.0), g("y", 0.0));
        if (s - 1.0).abs() > 1e-4 || tx.abs() > 1e-4 || ty.abs() > 1e-4 {
            return ((1.0 - s) / 2.0 + tx, (1.0 - s) / 2.0 + ty, s, s);
        }
    }
    (0.0, 0.0, 1.0, 1.0)
}

/// Base per-edge crop of a RAW clip as [l, t, r, b] (zeros when none).
fn raw_crop_ltrb(c: &Value) -> [f64; 4] {
    let Some(cr) = c.get("crop").filter(|v| v.is_object()) else {
        return [0.0; 4];
    };
    let g = |k: &str| cr.get(k).and_then(|v| v.as_f64()).unwrap_or(0.0).clamp(0.0, 0.9);
    [g("left"), g("top"), g("right"), g("bottom")]
}

/// Linear interpolation of a transform_keys array at clip-relative time `rel`
/// (same math as model::Clip::transform_at — ends clamp to the first/last key).
fn transform_keys_at(
    keys: &[Value],
    rel: f64,
    base: (f64, f64, f64, f64),
    base_crop: [f64; 4],
) -> Option<(f64, f64, f64, f64, [f64; 4])> {
    let mut ks: Vec<(f64, f64, f64, f64, f64, [f64; 4])> = keys
        .iter()
        .filter_map(|k| {
            let crop = k.get("crop").map(|c| {
                let g = |n: &str| c.get(n).and_then(|v| v.as_f64()).unwrap_or(0.0).clamp(0.0, 0.9);
                [g("left"), g("top"), g("right"), g("bottom")]
            });
            Some((
                k.get("t")?.as_f64()?,
                k.get("x")?.as_f64()?,
                k.get("y")?.as_f64()?,
                k.get("w").and_then(|v| v.as_f64()).unwrap_or(base.2),
                k.get("h").and_then(|v| v.as_f64()).unwrap_or(base.3),
                crop.unwrap_or(base_crop),
            ))
        })
        .collect();
    if ks.is_empty() {
        return None;
    }
    ks.sort_by(|a, b| a.0.total_cmp(&b.0));
    let pick = |a: &(f64, f64, f64, f64, f64, [f64; 4])| (a.1, a.2, a.3, a.4, a.5);
    if rel <= ks[0].0 {
        return Some(pick(&ks[0]));
    }
    if rel >= ks[ks.len() - 1].0 {
        return Some(pick(&ks[ks.len() - 1]));
    }
    let i = ks.iter().position(|k| k.0 > rel).unwrap();
    let (a, b) = (&ks[i - 1], &ks[i]);
    let fr = ((rel - a.0) / (b.0 - a.0).max(1e-9)).clamp(0.0, 1.0);
    let l = |p: f64, q: f64| p + (q - p) * fr;
    Some((
        l(a.1, b.1),
        l(a.2, b.2),
        l(a.3, b.3),
        l(a.4, b.4),
        [
            l(a.5[0], b.5[0]),
            l(a.5[1], b.5[1]),
            l(a.5[2], b.5[2]),
            l(a.5[3], b.5[3]),
        ],
    ))
}

/// Partition a split clip's transform keyframes at cut offset `d` — same contract as
/// split_region_keys: each side keeps its keys (right side re-based), motion crossing
/// the cut gets pinned with boundary keys, and a keyless side holds the cut-moment
/// look via its base position/crop instead of a key out of nowhere.
fn split_transform_keys(orig: &Value, d: f64, leftv: &mut Value, rightv: &mut Value) {
    let Some(keys) = orig.get("transform_keys").and_then(|v| v.as_array()).cloned() else {
        return;
    };
    if keys.is_empty() {
        return;
    }
    let q3 = |v: f64| (v * 1000.0).round() / 1000.0;
    let q4 = |v: f64| (v * 10000.0).round() / 10000.0;
    let kt_of = |k: &Value| k.get("t").and_then(|v| v.as_f64());
    let had_before = keys.iter().any(|k| kt_of(k).map(|kt| kt < d - KEY_REPLACE_EPS).unwrap_or(false));
    let had_after = keys.iter().any(|k| kt_of(k).map(|kt| kt > d + KEY_REPLACE_EPS).unwrap_or(false));
    let cut = transform_keys_at(&keys, d, raw_display_box(orig), raw_crop_ltrb(orig));
    let key_json = |t: f64, px: f64, py: f64, pw: f64, ph: f64, pc: [f64; 4]| {
        let mut o = serde_json::Map::new();
        o.insert("t".into(), serde_json::json!(q3(t)));
        o.insert("x".into(), serde_json::json!(q4(px)));
        o.insert("y".into(), serde_json::json!(q4(py)));
        o.insert("w".into(), serde_json::json!(q4(pw)));
        o.insert("h".into(), serde_json::json!(q4(ph)));
        if pc.iter().sum::<f64>() > 1e-4 {
            o.insert(
                "crop".into(),
                serde_json::json!({"left": q4(pc[0]), "top": q4(pc[1]), "right": q4(pc[2]), "bottom": q4(pc[3])}),
            );
        }
        Value::Object(o)
    };
    let mut lk: Vec<Value> = keys
        .iter()
        .filter(|k| kt_of(k).map(|kt| kt <= d + KEY_REPLACE_EPS).unwrap_or(false))
        .cloned()
        .collect();
    let mut rk: Vec<Value> = keys
        .iter()
        .filter_map(|k| {
            let kt = kt_of(k)?;
            if kt < d - KEY_REPLACE_EPS {
                return None;
            }
            let mut k2 = k.clone();
            k2["t"] = serde_json::json!(q3((kt - d).max(0.0)));
            Some(k2)
        })
        .collect();
    if let Some((px, py, pw, ph, pc)) = cut {
        if !lk.is_empty()
            && had_after
            && !lk.iter().any(|k| kt_of(k).map(|kt| (kt - d).abs() <= KEY_REPLACE_EPS).unwrap_or(false))
        {
            lk.push(key_json(d, px, py, pw, ph, pc));
        }
        if !rk.is_empty()
            && had_before
            && !rk.iter().any(|k| kt_of(k).map(|kt| kt.abs() <= KEY_REPLACE_EPS).unwrap_or(false))
        {
            rk.push(key_json(0.0, px, py, pw, ph, pc));
        }
    }
    let sort = |v: &mut Vec<Value>| {
        v.sort_by(|a, b| {
            let ta = a.get("t").and_then(|x| x.as_f64()).unwrap_or(0.0);
            let tb = b.get("t").and_then(|x| x.as_f64()).unwrap_or(0.0);
            ta.total_cmp(&tb)
        })
    };
    sort(&mut lk);
    sort(&mut rk);
    for (side, ks) in [(&mut *leftv, lk), (&mut *rightv, rk)] {
        if let Some(o) = side.as_object_mut() {
            if ks.is_empty() {
                o.remove("transform_keys");
                // keyless side: hold the cut-moment look via the base fields
                if let Some((px, py, pw, ph, pc)) = cut {
                    o.insert(
                        "position".into(),
                        serde_json::json!({"x": q4(px), "y": q4(py), "width": q4(pw), "height": q4(ph)}),
                    );
                    if pc.iter().sum::<f64>() > 1e-4 {
                        o.insert(
                            "crop".into(),
                            serde_json::json!({"left": q4(pc[0]), "top": q4(pc[1]), "right": q4(pc[2]), "bottom": q4(pc[3])}),
                        );
                    } else {
                        o.remove("crop");
                    }
                }
            } else {
                o.insert("transform_keys".into(), Value::Array(ks));
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
    // Allocate every new id up front. This lets a copied tracked-blur binding point at
    // the copied media clip even when the effect happens to be visited first.
    let selected: Vec<Value> = tracks_ref(root)
        .map(|tracks| {
            tracks
                .iter()
                .flat_map(|tr| tr.get("clips").and_then(|c| c.as_array()).into_iter().flatten())
                .filter(|c| ids.contains(&sid(c)))
                .cloned()
                .collect()
        })
        .unwrap_or_default();
    let id_map: std::collections::HashMap<String, String> = selected
        .iter()
        .enumerate()
        .map(|(i, c)| (sid(c), format!("{}__dup_{}_{}", sid(c), salt, i + 1)))
        .collect();
    // Old blur bindings predate target_clip_id. When the selected block contains a
    // matching media clip, infer that relationship once so the copies become explicit.
    let mut legacy_targets: std::collections::HashMap<String, String> = Default::default();
    for fx in &selected {
        let Some(bt) = fx.get("blur_track").and_then(|v| v.as_object()) else { continue };
        if bt.get("target_clip_id").and_then(|v| v.as_str()).is_some() {
            continue;
        }
        let aid = bt.get("asset_id").and_then(|v| v.as_str()).unwrap_or("");
        let best = selected
            .iter()
            .filter(|m| m.get("asset_id").and_then(|v| v.as_str()) == Some(aid))
            .filter_map(|m| {
                let overlap = (f(fx, "timeline_end").min(f(m, "timeline_end"))
                    - f(fx, "timeline_start").max(f(m, "timeline_start")))
                    .max(0.0);
                (overlap > 0.0).then_some((overlap, sid(m)))
            })
            .max_by(|a, b| a.0.total_cmp(&b.0));
        if let Some((_, target)) = best {
            legacy_targets.insert(sid(fx), target);
        }
    }
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
    let mut new_links: std::collections::HashMap<String, String> = Default::default();
    let mut link_n = 0u64;
    let mut mk_copy = |c: &Value, shift: f64| -> Value {
        let mut copy = c.clone();
        let old_id = sid(c);
        copy["id"] = Value::from(id_map.get(&old_id).cloned().unwrap_or_else(|| format!("{old_id}__dup_{salt}")));
        setf(&mut copy, "timeline_start", f(c, "timeline_start") + shift);
        setf(&mut copy, "timeline_end", f(c, "timeline_end") + shift);
        if let Some(l) = link(c) {
            if !new_links.contains_key(&l) {
                link_n += 1;
                new_links.insert(l.clone(), format!("lk_dup_{}_{}", salt, link_n));
            }
            let nl = new_links.get(&l).cloned().unwrap();
            copy["link_id"] = Value::from(nl);
        }
        if let Some(bt) = copy.get_mut("blur_track").and_then(|v| v.as_object_mut()) {
            let old_target = bt
                .get("target_clip_id")
                .and_then(|v| v.as_str())
                .map(str::to_string)
                .or_else(|| legacy_targets.get(&old_id).cloned());
            if let Some(new_target) = old_target.as_ref().and_then(|id| id_map.get(id)) {
                bt.insert("target_clip_id".into(), Value::from(new_target.clone()));
            }
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

/// Toggle picture visibility on selected video clips without changing their linked audio.
pub fn set_video_enabled(raw: &mut Value, ids: &[String], enabled: bool) {
    for clip in clips_iter_mut(raw) {
        if ids.contains(&sid(clip)) && clip.get("asset_id").is_some() {
            clip["video_enabled"] = Value::from(enabled);
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
    let is_main_lane = tracks_ref(raw)
        .and_then(|tracks| tracks.iter().position(|tr| tr.get("type").and_then(|v| v.as_str()) != Some("audio")))
        == track_idx;
    let ids = if is_main_lane {
        // The main storyline owns the global timeline clock: preserve its ripple
        // behaviour, including splitting clips which straddle the inserted still.
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
        expand_links(raw, &straddlers)
    } else {
        // A PiP/overlay freeze is local: split only this clip and its linked audio.
        expand_links(raw, &[id.to_string()])
    };
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
    let mut freeze_track_idx = track_idx;
    if is_main_lane {
        ripple_open(raw, t, dur);
    } else {
        let right_prefixes: Vec<String> = ids.iter().map(|cid| format!("{cid}__ns_{salt}_")).collect();
        // Shift only this clip's continuation (and its linked audio), never the main
        // lane or unrelated overlays. If that would collide, use an empty lane above.
        let has_room = match (tracks_ref(raw), track_idx) {
            (Some(tracks), Some(ti)) => tracks[ti]
                .get("clips")
                .and_then(|v| v.as_array())
                .map(|clips| {
                    let moved: Vec<&Value> = clips
                        .iter()
                        .filter(|c| right_prefixes.iter().any(|p| sid(c).starts_with(p)))
                        .collect();
                    !clips.iter().any(|other| {
                        if right_prefixes.iter().any(|p| sid(other).starts_with(p)) {
                            return false;
                        }
                        moved.iter().any(|moved| {
                            f(other, "timeline_start") < f(moved, "timeline_end") + dur - 1e-6
                                && f(other, "timeline_end") > f(moved, "timeline_start") + dur + 1e-6
                        })
                    })
                })
                .unwrap_or(false),
            _ => false,
        };
        if has_room {
            for c in clips_iter_mut(raw) {
                let cid = sid(c);
                if right_prefixes.iter().any(|p| cid.starts_with(p)) {
                    setf(c, "timeline_start", f(c, "timeline_start") + dur);
                    setf(c, "timeline_end", f(c, "timeline_end") + dur);
                }
            }
        } else if let (Some(tracks), Some(ti)) = (tracks_mut(raw), track_idx) {
            let clear = (ti + 1..tracks.len()).find(|&i| {
                tracks[i].get("type").and_then(|v| v.as_str()) != Some("audio")
                    && !tracks[i].get("locked").and_then(|v| v.as_bool()).unwrap_or(false)
                    && !tracks[i]
                        .get("clips")
                        .and_then(|v| v.as_array())
                        .map(|clips| clips.iter().any(|c| f(c, "timeline_start") < t + dur - 1e-6 && f(c, "timeline_end") > t + 1e-6))
                        .unwrap_or(false)
            });
            freeze_track_idx = Some(clear.unwrap_or_else(|| {
                let at = ti + 1;
                tracks.insert(at, serde_json::json!({
                    "id": format!("freeze_overlay_{salt}"), "type": "overlay",
                    "label": "Freeze frame", "clips": []
                }));
                at
            }));
        }
    }
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
    if let (Some(tracks), Some(ti)) = (tracks_mut(raw), freeze_track_idx) {
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

/// Set a clip's style string (effect clips: gaussian / mosaic / solid).
pub fn set_style(raw: &mut Value, id: &str, style: &str) {
    for_each_clip(raw, |c| {
        if c.get("id").and_then(|v| v.as_str()) == Some(id) {
            c["style"] = Value::from(style);
        }
    });
}

/// Update optional region-effect controls. `None` removes a field so legacy defaults
/// remain stable in saved documents.
pub fn set_effect_options(
    raw: &mut Value, id: &str, strength: Option<f64>, color: Option<String>, opacity: Option<f64>,
) {
    for_each_clip(raw, |c| {
        if c.get("id").and_then(|v| v.as_str()) != Some(id) { return; }
        let set = |obj: &mut Value, key: &str, value: Option<Value>| {
            if let Some(map) = obj.as_object_mut() {
                match value { Some(v) => { map.insert(key.into(), v); }, None => { map.remove(key); } }
            }
        };
        set(c, "effect_strength", strength.map(Value::from));
        set(c, "effect_color", color.clone().map(Value::from));
        set(c, "effect_opacity", opacity.map(Value::from));
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
    // dragging back DOWN dissolves the provisional lane the same gesture created above
    // (pruning only empty id-less lanes, which nothing else produces). Runs after the
    // move so `target` (resolved against pre-edit lanes) stayed valid.
    prune_empty_unnamed_tracks_impl(tracks);
}

/// Place an existing asset at an exact timeline time/lane without rippling or overwriting.
/// If the requested visual lane is occupied, create a lane immediately in front of it so
/// every existing clip survives. Video audio is linked on the first audio lane; still images
/// are silent and use the same visual-clip contract as the native compositor/exporter.
pub fn place_asset(
    raw: &mut Value,
    target: usize,
    t: f64,
    dur: f64,
    asset_id: &str,
    has_audio: bool,
    is_image: bool,
    salt: u64,
) -> Vec<String> {
    let t = (t.max(0.0) * 1000.0).round() / 1000.0;
    let dur = dur.max(0.1);
    let end = ((t + dur) * 1000.0).round() / 1000.0;
    let link = format!("lk_drop_{salt}");
    let vid_id = format!("drop_v_{salt}");
    let aud_id = format!("drop_a_{salt}");
    let Some(tracks) = tracks_mut(raw) else { return Vec::new() };
    if target >= tracks.len()
        || tracks[target].get("type").and_then(|v| v.as_str()) == Some("audio")
        || tracks[target].get("locked").and_then(|v| v.as_bool()).unwrap_or(false)
    {
        return Vec::new();
    }

    let occupied = tracks[target]
        .get("clips")
        .and_then(|c| c.as_array())
        .map(|clips| clips.iter().any(|c| {
            f(c, "timeline_start") < end - 1e-6 && f(c, "timeline_end") > t + 1e-6
        }))
        .unwrap_or(false);
    let visual_target = if occupied {
        let insert_at = target + 1;
        tracks.insert(
            insert_at,
            serde_json::json!({
                "id": format!("overlay_drop_{salt}"),
                "type": "overlay",
                "label": "Dropped media",
                "clips": []
            }),
        );
        insert_at
    } else {
        target
    };
    let target_kind = tracks[visual_target]
        .get("type")
        .and_then(|v| v.as_str())
        .unwrap_or("overlay")
        .to_string();
    let mut vclip = serde_json::json!({
        "id": vid_id.clone(),
        "asset_id": asset_id,
        "track": target_kind,
        "fit": "contain",
        "source_start": 0.0,
        "source_end": dur,
        "timeline_start": t,
        "timeline_end": end
    });
    if has_audio && !is_image {
        vclip["link_id"] = serde_json::json!(link.clone());
    }
    tracks[visual_target]
        .get_mut("clips")
        .and_then(|c| c.as_array_mut())
        .map(|clips| clips.push(vclip));

    let mut inserted = vec![vid_id];
    if has_audio && !is_image {
        let aclip = serde_json::json!({
            "id": aud_id.clone(),
            "asset_id": asset_id,
            "track": "audio",
            "source_start": 0.0,
            "source_end": dur,
            "timeline_start": t,
            "timeline_end": end,
            "link_id": link
        });
        if let Some(ai) = tracks
            .iter()
            .position(|tr| tr.get("type").and_then(|v| v.as_str()) == Some("audio"))
        {
            tracks[ai]
                .get_mut("clips")
                .and_then(|c| c.as_array_mut())
                .map(|clips| clips.push(aclip));
        } else {
            tracks.push(serde_json::json!({
                "id": format!("audio_drop_{salt}"), "type": "audio", "clips": [aclip]
            }));
        }
        inserted.push(aud_id);
    }
    inserted
}

/// Place a PURE AUDIO asset (BGM / SE / narration file) on the audio lane at `t` —
/// a standalone audio clip with no linked visual. Creates the audio lane when the
/// sequence has none yet.
pub fn place_audio_asset(
    raw: &mut Value,
    t: f64,
    dur: f64,
    asset_id: &str,
    salt: u64,
) -> Vec<String> {
    let t = (t.max(0.0) * 1000.0).round() / 1000.0;
    let dur = dur.max(0.1);
    let end = ((t + dur) * 1000.0).round() / 1000.0;
    let aud_id = format!("drop_a_{salt}");
    let Some(tracks) = tracks_mut(raw) else { return Vec::new() };
    let aclip = serde_json::json!({
        "id": aud_id.clone(),
        "asset_id": asset_id,
        "track": "audio",
        "source_start": 0.0,
        "source_end": dur,
        "timeline_start": t,
        "timeline_end": end
    });
    // One lane, no overlaps — the NLE invariant every edit op assumes. The first
    // audio lane usually carries the linked A/V clips, so a BGM spanning minutes
    // would overlap them there: pick the first audio lane whose span is FREE,
    // else append a fresh audio lane.
    let span_free = |tr: &Value| {
        tr.get("clips")
            .and_then(|c| c.as_array())
            .map(|clips| {
                clips.iter().all(|c| {
                    f(c, "timeline_start") >= end - 1e-6 || f(c, "timeline_end") <= t + 1e-6
                })
            })
            .unwrap_or(true)
    };
    if let Some(ai) = tracks
        .iter()
        .position(|tr| tr.get("type").and_then(|v| v.as_str()) == Some("audio") && span_free(tr))
    {
        tracks[ai]
            .get_mut("clips")
            .and_then(|c| c.as_array_mut())
            .map(|clips| clips.push(aclip));
    } else {
        tracks.push(serde_json::json!({
            "id": format!("audio_drop_{salt}"), "type": "audio", "clips": [aclip]
        }));
    }
    vec![aud_id]
}

/// Move a visual multi-selection between lanes as one rigid group. `anchor_id` is the clip
/// actually held by the pointer; it lands on `target`, while clips selected on neighbouring
/// lanes keep the same vertical offsets. The delta is clamped as a group at the first/last
/// visual lane, so clips can never collapse into one lane or disappear at a boundary.
pub fn move_group_to_track(
    raw: &mut serde_json::Value,
    ids: &[String],
    anchor_id: &str,
    target: usize,
) {
    let Some(tracks) = raw
        .get_mut(0)
        .and_then(|r| r.get_mut("timeline"))
        .and_then(|x| x.get_mut("sequence"))
        .and_then(|x| x.get_mut("tracks"))
        .and_then(|x| x.as_array_mut())
    else {
        return;
    };
    if target >= tracks.len()
        || tracks[target].get("type").and_then(|v| v.as_str()) == Some("audio")
    {
        return;
    }

    let visual_tracks: Vec<usize> = tracks
        .iter()
        .enumerate()
        .filter(|(_, tr)| tr.get("type").and_then(|v| v.as_str()) != Some("audio"))
        .map(|(i, _)| i)
        .collect();
    let Some(target_ord) = visual_tracks.iter().position(|&i| i == target) else { return };

    let mut selected_ords: Vec<usize> = Vec::new();
    let mut anchor_ord: Option<usize> = None;
    for (ord, &ti) in visual_tracks.iter().enumerate() {
        let Some(clips) = tracks[ti].get("clips").and_then(|c| c.as_array()) else { continue };
        for c in clips {
            let id = sid(c);
            if ids.contains(&id) {
                selected_ords.push(ord);
                if id == anchor_id {
                    anchor_ord = Some(ord);
                }
            }
        }
    }
    let Some(anchor_ord) = anchor_ord.or_else(|| selected_ords.first().copied()) else { return };
    let min_ord = *selected_ords.iter().min().unwrap_or(&anchor_ord);
    let max_ord = *selected_ords.iter().max().unwrap_or(&anchor_ord);
    let wanted = target_ord as isize - anchor_ord as isize;
    let delta = wanted.clamp(
        -(min_ord as isize),
        visual_tracks.len() as isize - 1 - max_ord as isize,
    );
    if delta == 0 {
        return;
    }

    let mut moved: Vec<(usize, Value)> = Vec::new();
    for (ord, &ti) in visual_tracks.iter().enumerate() {
        if let Some(clips) = tracks[ti].get_mut("clips").and_then(|c| c.as_array_mut()) {
            let mut i = 0;
            while i < clips.len() {
                if ids.contains(&sid(&clips[i])) {
                    moved.push((ord, clips.remove(i)));
                } else {
                    i += 1;
                }
            }
        }
    }
    for (src_ord, mut clip) in moved {
        let dst_ord = (src_ord as isize + delta) as usize;
        let dst_ti = visual_tracks[dst_ord];
        let kind = tracks[dst_ti]
            .get("type")
            .and_then(|v| v.as_str())
            .unwrap_or("overlay")
            .to_string();
        if let Some(o) = clip.as_object_mut() {
            o.insert("track".into(), serde_json::json!(kind));
        }
        if let Some(arr) = tracks[dst_ti].get_mut("clips").and_then(|c| c.as_array_mut()) {
            arr.push(clip);
            arr.sort_by(|a, b| f(a, "timeline_start").total_cmp(&f(b, "timeline_start")));
        }
    }
    prune_empty_unnamed_tracks_impl(tracks);
}

/// The above-the-top drop zone gets a fresh lane, then uses the same rigid group move. Once
/// the selection already occupies an otherwise-empty provisional top lane, repeated drag
/// frames are idempotent instead of continuously creating lanes.
pub fn move_group_to_new_top_track(raw: &mut Value, ids: &[String], anchor_id: &str) {
    let Some(tracks) = raw
        .get_mut(0)
        .and_then(|r| r.get_mut("timeline"))
        .and_then(|x| x.get_mut("sequence"))
        .and_then(|x| x.get_mut("tracks"))
        .and_then(|x| x.as_array_mut())
    else { return };
    let Some(front) = tracks
        .iter()
        .enumerate()
        .filter(|(_, tr)| tr.get("type").and_then(|v| v.as_str()) != Some("audio"))
        .map(|(i, _)| i)
        .max()
    else { return };
    let front_clips = tracks[front].get("clips").and_then(|c| c.as_array());
    let already_provisional = tracks[front].get("id").and_then(|v| v.as_str()).is_none()
        && front_clips
            .map(|cs| !cs.is_empty() && cs.iter().all(|c| ids.contains(&sid(c))))
            .unwrap_or(false);
    if already_provisional {
        return;
    }
    let kind = tracks
        .iter()
        .find_map(|tr| {
            let has = tr
                .get("clips")
                .and_then(|c| c.as_array())
                .map(|cs| cs.iter().any(|c| ids.contains(&sid(c))))
                .unwrap_or(false);
            has.then(|| tr.get("type").and_then(|v| v.as_str()).unwrap_or("overlay").to_string())
        })
        .unwrap_or_else(|| "overlay".to_string());
    tracks.insert(front + 1, serde_json::json!({"type": kind, "clips": []}));
    let target = front + 1;
    // Release the mutable borrow before calling the general mover.
    let _ = tracks;
    move_group_to_track(raw, ids, anchor_id, target);
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
    // Already ALONE on the front lane -> that lane IS the (provisional) new lane; adding
    // another would stack empties. But a clip dragged up FROM a front lane that still
    // holds other clips must get its own new lane — the old blanket "src == front"
    // early-return silently ate exactly that case (発火するのにレーンが増えない).
    if src_track == front {
        let front_empty = front
            .and_then(|i| tracks[i].get("clips").and_then(|c| c.as_array()))
            .map(|cs| cs.is_empty())
            .unwrap_or(false);
        if front_empty {
            if let Some(ti) = src_track {
                if let Some(arr) = tracks[ti].get_mut("clips").and_then(|c| c.as_array_mut()) {
                    arr.extend(moved);
                }
            }
            return;
        }
    }
    let tkind = lane_kind.unwrap_or_else(|| "overlay".to_string());
    for c in &mut moved {
        if let Some(o) = c.as_object_mut() {
            o.insert("track".into(), serde_json::json!(tkind));
        }
    }
    let insert_at = front.map(|i| i + 1).unwrap_or(tracks.len());
    tracks.insert(insert_at, serde_json::json!({"type": tkind, "clips": moved}));
    prune_empty_unnamed_tracks_impl(tracks);
}

/// Remove PROVISIONAL lanes that ended up empty: tracks created by drag-to-new-lane carry
/// no "id" (every persisted lane has one), so an empty id-less lane is a leftover of the
/// current gesture — e.g. the user dragged into the new-lane zone and then back down.
fn prune_empty_unnamed_tracks_impl(tracks: &mut Vec<serde_json::Value>) {
    tracks.retain(|tr| {
        let unnamed = tr.get("id").and_then(|v| v.as_str()).map(str::is_empty).unwrap_or(true);
        let audio = tr.get("type").and_then(|v| v.as_str()) == Some("audio");
        let empty = tr
            .get("clips")
            .and_then(|c| c.as_array())
            .map(|cs| cs.is_empty())
            .unwrap_or(true);
        !(unnamed && empty && !audio)
    });
}

pub fn prune_empty_unnamed_tracks(raw: &mut serde_json::Value) {
    if let Some(tracks) = tracks_mut(raw) {
        prune_empty_unnamed_tracks_impl(tracks);
    }
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

/// Select whether the source keeps its aspect ratio inside the position box. This is
/// deliberately separate from `position`: moving or uniformly resizing a clip must not
/// silently change a stretch chosen by the user.
pub fn set_fit_many(raw: &mut serde_json::Value, ids: &[String], stretch: bool) {
    for_each_clip(raw, |c| {
        let id = c.get("id").and_then(|v| v.as_str()).unwrap_or("");
        if !ids.iter().any(|i| i == id) {
            return;
        }
        let o = c.as_object_mut().unwrap();
        if stretch {
            o.insert("fit".into(), serde_json::json!("stretch"));
        } else {
            // `cover` is the persisted default. Omitting it keeps old documents compact.
            o.remove("fit");
        }
    });
}

pub fn set_opacity_many(raw: &mut serde_json::Value, ids: &[String], opacity: f64) {
    let opacity = opacity.clamp(0.0, 1.0);
    for_each_clip(raw, |c| {
        let id = c.get("id").and_then(|v| v.as_str()).unwrap_or("");
        if !ids.iter().any(|i| i == id) {
            return;
        }
        let o = c.as_object_mut().unwrap();
        if opacity >= 0.9999 {
            o.remove("opacity");
        } else {
            o.insert("opacity".into(), serde_json::json!((opacity * 1000.0).round() / 1000.0));
        }
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

/// Move/resize a region-effect clip's rectangle (canvas fractions).
pub fn set_region(raw: &mut serde_json::Value, id: &str, x: f64, y: f64, w: f64, h: f64) {
    for_each_clip(raw, |c| {
        if c.get("id").and_then(|v| v.as_str()) == Some(id) {
            let q = |v: f64| (v * 10000.0).round() / 10000.0;
            let (w, h) = (w.clamp(0.01, 1.0), h.clamp(0.01, 1.0));
            // may hang partly OFF-SCREEN (covering objects at the very edge needs the
            // rect past the border); at least 5% stays visible so it can be grabbed
            c.as_object_mut().unwrap().insert(
                "region".into(),
                serde_json::json!({"x": q(x.clamp(0.05 - w, 0.95)), "y": q(y.clamp(0.05 - h, 0.95)),
                                    "width": q(w), "height": q(h)}),
            );
        }
    });
}

/// Same-key window for insert/replace: must be SMALLER than any real frame interval
/// (60fps VFR sources have ~16ms gaps — the old 1/60s window silently ate the
/// previous frame's key on every step-and-drag) yet larger than the 1ms storage
/// rounding. The UI's "on this key" paint uses the same value.
pub const KEY_REPLACE_EPS: f64 = 0.004;

/// Insert/replace a keyframe on a region clip (t = clip-relative seconds; only a key
/// at the SAME frame instant — within KEY_REPLACE_EPS — is replaced; a key on the
/// neighbouring frame is always kept as its own key). Keys carry position AND size;
/// legacy position-only keys read back with the base rect's size.
pub fn set_region_key(raw: &mut serde_json::Value, id: &str, t: f64, x: f64, y: f64, w: f64, h: f64) {
    for_each_clip(raw, |c| {
        if c.get("id").and_then(|v| v.as_str()) != Some(id) {
            return;
        }
        let o = c.as_object_mut().unwrap();
        let arr = o
            .entry("region_keys")
            .or_insert_with(|| serde_json::Value::Array(vec![]));
        let Some(keys) = arr.as_array_mut() else { return };
        let q = |v: f64| (v * 10000.0).round() / 10000.0;
        keys.retain(|k| {
            k.get("t")
                .and_then(|v| v.as_f64())
                .map(|kt| (kt - t).abs() > KEY_REPLACE_EPS)
                .unwrap_or(false)
        });
        let (w, h) = (w.clamp(0.01, 1.0), h.clamp(0.01, 1.0));
        keys.push(serde_json::json!({"t": (t * 1000.0).round() / 1000.0,
                                      "x": q(x.clamp(0.05 - w, 0.95)), "y": q(y.clamp(0.05 - h, 0.95)),
                                      "w": q(w), "h": q(h)}));
        keys.sort_by(|a, b| {
            let ta = a.get("t").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let tb = b.get("t").and_then(|v| v.as_f64()).unwrap_or(0.0);
            ta.total_cmp(&tb)
        });
    });
}

/// Replace a clip's keys with `orig_keys` shifted by (dx,dy) and resized by (dw,dh) —
/// the WHOLE trajectory moves rigidly; no key is created or destroyed. This is what a
/// drag does when キー打ちモード is OFF: a static adjustment must never grow motion.
/// Idempotent per drag frame (always recomputed from the drag-start snapshot).
pub fn offset_region_keys(
    raw: &mut serde_json::Value,
    id: &str,
    orig_keys: &serde_json::Value,
    dx: f64,
    dy: f64,
    dw: f64,
    dh: f64,
) {
    let Some(orig) = orig_keys.as_array() else { return };
    let q = |v: f64| (v * 10000.0).round() / 10000.0;
    let shifted: Vec<Value> = orig
        .iter()
        .filter_map(|k| {
            let t = k.get("t")?.as_f64()?;
            let x = k.get("x")?.as_f64()?;
            let y = k.get("y")?.as_f64()?;
            let kw = k.get("w").and_then(|v| v.as_f64());
            let kh = k.get("h").and_then(|v| v.as_f64());
            let nw = kw.map(|w| (w + dw).clamp(0.01, 1.0));
            let nh = kh.map(|h| (h + dh).clamp(0.01, 1.0));
            let cw = nw.unwrap_or(0.1);
            let ch = nh.unwrap_or(0.1);
            let mut o = serde_json::Map::new();
            o.insert("t".into(), serde_json::json!(t));
            o.insert("x".into(), serde_json::json!(q((x + dx).clamp(0.05 - cw, 0.95))));
            o.insert("y".into(), serde_json::json!(q((y + dy).clamp(0.05 - ch, 0.95))));
            if let Some(w) = nw {
                o.insert("w".into(), serde_json::json!(q(w)));
            }
            if let Some(h) = nh {
                o.insert("h".into(), serde_json::json!(q(h)));
            }
            Some(Value::Object(o))
        })
        .collect();
    for_each_clip(raw, |c| {
        if c.get("id").and_then(|v| v.as_str()) == Some(id) {
            if let Some(o) = c.as_object_mut() {
                o.insert("region_keys".into(), Value::Array(shifted.clone()));
            }
        }
    });
}

/// Remove the position keyframe at clip-relative time t. Window = twice the
/// replace epsilon — still far below a 60fps frame gap, so deleting one key can
/// never swallow the NEIGHBOURING frame's key with it.
pub fn remove_region_key(raw: &mut serde_json::Value, id: &str, t: f64) {
    for_each_clip(raw, |c| {
        if c.get("id").and_then(|v| v.as_str()) != Some(id) {
            return;
        }
        let o = c.as_object_mut().unwrap();
        let Some(keys) = o.get_mut("region_keys").and_then(|v| v.as_array_mut()) else {
            return;
        };
        keys.retain(|k| {
            k.get("t")
                .and_then(|v| v.as_f64())
                .map(|kt| (kt - t).abs() > KEY_REPLACE_EPS * 2.0)
                .unwrap_or(false)
        });
        if keys.is_empty() {
            o.remove("region_keys");
        }
    });
}

/// Remove all position keyframes from a region clip.
pub fn clear_region_keys(raw: &mut serde_json::Value, id: &str) {
    for_each_clip(raw, |c| {
        if c.get("id").and_then(|v| v.as_str()) == Some(id) {
            c.as_object_mut().unwrap().remove("region_keys");
        }
    });
}

/// Insert/replace a MEDIA-clip transform keyframe (display box + optional crop) at
/// clip-relative time t. Same replace window / quantization as set_region_key. x/y are
/// not clamped here — like set_position, the caller enforces the on-screen minimum.
pub fn set_transform_key(
    raw: &mut serde_json::Value,
    id: &str,
    t: f64,
    x: f64,
    y: f64,
    w: f64,
    h: f64,
    crop: Option<(f64, f64, f64, f64)>,
) {
    for_each_clip(raw, |c| {
        if c.get("id").and_then(|v| v.as_str()) != Some(id) {
            return;
        }
        let o = c.as_object_mut().unwrap();
        let arr = o
            .entry("transform_keys")
            .or_insert_with(|| serde_json::Value::Array(vec![]));
        let Some(keys) = arr.as_array_mut() else { return };
        let q = |v: f64| (v * 10000.0).round() / 10000.0;
        // crop=None means "don't touch the crop": a position drag re-writing THIS key
        // must not silently strip the crop the key carried — carry it over instead
        let mut carry_crop: Option<Value> = None;
        keys.retain(|k| {
            let same = k
                .get("t")
                .and_then(|v| v.as_f64())
                .map(|kt| (kt - t).abs() <= KEY_REPLACE_EPS)
                .unwrap_or(true);
            if same && carry_crop.is_none() {
                carry_crop = k.get("crop").cloned();
            }
            !same
        });
        let mut key = serde_json::Map::new();
        key.insert("t".into(), serde_json::json!((t * 1000.0).round() / 1000.0));
        key.insert("x".into(), serde_json::json!(q(x)));
        key.insert("y".into(), serde_json::json!(q(y)));
        key.insert("w".into(), serde_json::json!(q(w.clamp(0.01, 4.0))));
        key.insert("h".into(), serde_json::json!(q(h.clamp(0.01, 4.0))));
        if let Some((cl, ct, cr, cb)) = crop {
            let qc = |v: f64| q(v.clamp(0.0, 0.9));
            key.insert(
                "crop".into(),
                serde_json::json!({"left": qc(cl), "top": qc(ct), "right": qc(cr), "bottom": qc(cb)}),
            );
        } else if let Some(cc) = carry_crop {
            key.insert("crop".into(), cc);
        }
        keys.push(Value::Object(key));
        keys.sort_by(|a, b| {
            let ta = a.get("t").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let tb = b.get("t").and_then(|v| v.as_f64()).unwrap_or(0.0);
            ta.total_cmp(&tb)
        });
    });
}

/// Shift a media clip's WHOLE transform trajectory rigidly by (dx,dy) and resize by
/// (dw,dh) — the OFF-mode drag of a keyframed clip (no key is created or destroyed).
/// Idempotent per drag frame (recomputed from the drag-start snapshot). Crops ride
/// along untouched.
pub fn offset_transform_keys(
    raw: &mut serde_json::Value,
    id: &str,
    orig_keys: &serde_json::Value,
    dx: f64,
    dy: f64,
    dw: f64,
    dh: f64,
) {
    let Some(orig) = orig_keys.as_array() else { return };
    let q = |v: f64| (v * 10000.0).round() / 10000.0;
    let shifted: Vec<Value> = orig
        .iter()
        .filter_map(|k| {
            let mut k2 = k.clone();
            let o = k2.as_object_mut()?;
            let x = o.get("x")?.as_f64()?;
            let y = o.get("y")?.as_f64()?;
            o.insert("x".into(), serde_json::json!(q(x + dx)));
            o.insert("y".into(), serde_json::json!(q(y + dy)));
            if let Some(w) = o.get("w").and_then(|v| v.as_f64()) {
                o.insert("w".into(), serde_json::json!(q((w + dw).clamp(0.01, 4.0))));
            }
            if let Some(h) = o.get("h").and_then(|v| v.as_f64()) {
                o.insert("h".into(), serde_json::json!(q((h + dh).clamp(0.01, 4.0))));
            }
            Some(k2)
        })
        .collect();
    for_each_clip(raw, |c| {
        if c.get("id").and_then(|v| v.as_str()) == Some(id) {
            if let Some(o) = c.as_object_mut() {
                o.insert("transform_keys".into(), Value::Array(shifted.clone()));
            }
        }
    });
}

/// Remove the transform keyframe at clip-relative time t (same window as region).
pub fn remove_transform_key(raw: &mut serde_json::Value, id: &str, t: f64) {
    for_each_clip(raw, |c| {
        if c.get("id").and_then(|v| v.as_str()) != Some(id) {
            return;
        }
        let o = c.as_object_mut().unwrap();
        let Some(keys) = o.get_mut("transform_keys").and_then(|v| v.as_array_mut()) else {
            return;
        };
        keys.retain(|k| {
            k.get("t")
                .and_then(|v| v.as_f64())
                .map(|kt| (kt - t).abs() > KEY_REPLACE_EPS * 2.0)
                .unwrap_or(false)
        });
        if keys.is_empty() {
            o.remove("transform_keys");
        }
    });
}

/// Remove all transform keyframes from a media clip.
pub fn clear_transform_keys(raw: &mut serde_json::Value, id: &str) {
    for_each_clip(raw, |c| {
        if c.get("id").and_then(|v| v.as_str()) == Some(id) {
            c.as_object_mut().unwrap().remove("transform_keys");
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn timeline_visual_boundaries_are_frame_quantized_and_idempotent() {
        let mut raw = serde_json::json!([{
            "timeline": {"sequence": {
                "duration": 1.019,
                "frame_rate": 30.0,
                "tracks": [
                    {"type":"video", "clips":[{
                        "id":"v", "link_id":"av", "timeline_start":0.010,
                        "timeline_end":1.019
                    }]},
                    {"type":"caption", "clips":[{
                        "id":"c", "timeline_start":0.049, "timeline_end":0.051
                    }]},
                    {"type":"audio", "clips":[
                        {"id":"linked", "link_id":"av", "timeline_start":0.010,
                         "timeline_end":1.019},
                        {"id":"music", "timeline_start":0.0123, "timeline_end":0.9987}
                    ]}
                ]
            }}
        }]);

        quantize_timeline_frames(&mut raw);
        let once = raw.clone();
        let tracks = raw[0]["timeline"]["sequence"]["tracks"].as_array().unwrap();
        for (track_i, clip_i) in [(0usize, 0usize), (1, 0), (2, 0)] {
            let clip = &tracks[track_i]["clips"][clip_i];
            for key in ["timeline_start", "timeline_end"] {
                let frames = clip[key].as_f64().unwrap() * 30.0;
                assert!((frames - frames.round()).abs() < 1e-7, "{track_i}/{clip_i}/{key}");
            }
            assert!(clip["timeline_end"].as_f64().unwrap() > clip["timeline_start"].as_f64().unwrap());
        }
        assert_eq!(tracks[2]["clips"][1]["timeline_start"].as_f64(), Some(0.0123));
        assert_eq!(tracks[2]["clips"][1]["timeline_end"].as_f64(), Some(0.9987));

        quantize_timeline_frames(&mut raw);
        assert_eq!(raw, once);
    }

    fn lane_ids(raw: &Value, lane: usize) -> Vec<String> {
        raw[0]["timeline"]["sequence"]["tracks"][lane]["clips"]
            .as_array()
            .unwrap()
            .iter()
            .map(sid)
            .collect()
    }

    #[test]
    fn duplicate_remaps_tracked_blur_to_copied_media() {
        let mut raw = serde_json::json!([{
            "timeline": {"sequence": {"tracks": [
                {"type":"video", "clips":[{
                    "id":"media", "asset_id":"asset-a",
                    "timeline_start":1.0, "timeline_end":3.0,
                    "source_start":10.0, "source_end":12.0
                }]},
                {"type":"effect", "clips":[{
                    "id":"blur", "timeline_start":1.0, "timeline_end":3.0,
                    "region":{"x":0.1,"y":0.1,"width":0.2,"height":0.2},
                    "blur_track":{"asset_id":"asset-a","key":"abc","bake_start":9.0,"target_clip_id":"media"}
                }]}
            ]}}
        }]);
        duplicate_clips(&mut raw, &["media".into(), "blur".into()], 42);
        let clips: Vec<&Value> = raw[0]["timeline"]["sequence"]["tracks"]
            .as_array().unwrap().iter()
            .flat_map(|tr| tr["clips"].as_array().unwrap().iter())
            .collect();
        let media_copy = clips.iter().find(|c| sid(c).starts_with("media__dup_42_")).unwrap();
        let blur_copy = clips.iter().find(|c| sid(c).starts_with("blur__dup_42_")).unwrap();
        assert_eq!(
            blur_copy["blur_track"]["target_clip_id"].as_str(),
            media_copy["id"].as_str()
        );
    }

    #[test]
    fn duplicate_upgrades_legacy_tracked_blur_binding() {
        let mut raw = serde_json::json!([{
            "timeline": {"sequence": {"tracks": [
                {"type":"caption", "clips":[{
                    "id":"media", "asset_id":"asset-a",
                    "timeline_start":1.0, "timeline_end":3.0,
                    "source_start":10.0, "source_end":12.0
                }]},
                {"type":"overlay", "clips":[{
                    "id":"blur", "timeline_start":1.0, "timeline_end":3.0,
                    "region":{"x":0.1,"y":0.1,"width":0.2,"height":0.2},
                    "blur_track":{"asset_id":"asset-a","key":"abc","bake_start":9.0}
                }]}
            ]}}
        }]);
        duplicate_clips(&mut raw, &["media".into(), "blur".into()], 43);
        let clips: Vec<&Value> = raw[0]["timeline"]["sequence"]["tracks"]
            .as_array().unwrap().iter()
            .flat_map(|tr| tr["clips"].as_array().unwrap().iter())
            .collect();
        let media_copy = clips.iter().find(|c| sid(c).starts_with("media__dup_43_")).unwrap();
        let blur_copy = clips.iter().find(|c| sid(c).starts_with("blur__dup_43_")).unwrap();
        assert_eq!(
            blur_copy["blur_track"]["target_clip_id"].as_str(),
            media_copy["id"].as_str()
        );
    }

    #[test]
    fn multi_lane_move_keeps_relative_lanes_and_existing_clips() {
        let mut raw = serde_json::json!([{
            "timeline": {"sequence": {"tracks": [
                {"id":"v1", "type":"video", "clips":[
                    {"id":"a", "track":"video", "timeline_start":0.0, "timeline_end":2.0},
                    {"id":"keep0", "track":"video", "timeline_start":4.0, "timeline_end":6.0}
                ]},
                {"id":"v2", "type":"overlay", "clips":[
                    {"id":"b", "track":"overlay", "timeline_start":0.0, "timeline_end":2.0},
                    {"id":"keep1", "track":"overlay", "timeline_start":0.0, "timeline_end":2.0}
                ]},
                {"id":"v3", "type":"overlay", "clips":[
                    {"id":"keep2", "track":"overlay", "timeline_start":0.0, "timeline_end":2.0}
                ]},
                {"id":"a1", "type":"audio", "clips":[]}
            ]}}
        }]);
        let ids = vec!["a".to_string(), "b".to_string()];

        move_group_to_track(&mut raw, &ids, "a", 1);

        assert_eq!(lane_ids(&raw, 0), vec!["keep0"]);
        let lane1 = lane_ids(&raw, 1);
        let lane2 = lane_ids(&raw, 2);
        assert!(lane1.contains(&"a".to_string()) && lane1.contains(&"keep1".to_string()));
        assert!(lane2.contains(&"b".to_string()) && lane2.contains(&"keep2".to_string()));
        let all: Vec<String> = (0..4).flat_map(|lane| lane_ids(&raw, lane)).collect();
        for id in ["a", "b", "keep0", "keep1", "keep2"] {
            assert!(all.contains(&id.to_string()), "{id} disappeared");
        }
    }

    #[test]
    fn horizontal_group_move_clamps_rigidly_at_zero() {
        let mut raw = serde_json::json!([{
            "timeline": {"sequence": {"tracks": [
                {"id":"v1", "type":"video", "clips":[
                    {"id":"a", "timeline_start":1.0, "timeline_end":2.0},
                    {"id":"b", "timeline_start":3.0, "timeline_end":4.0}
                ]}
            ]}}
        }]);
        move_clips(&mut raw, &["a".into(), "b".into()], -10.0);
        let clips = raw[0]["timeline"]["sequence"]["tracks"][0]["clips"].as_array().unwrap();
        assert_eq!(f(&clips[0], "timeline_start"), 0.0);
        assert_eq!(f(&clips[1], "timeline_start"), 2.0);
    }

    #[test]
    fn dropped_video_on_occupied_lane_preserves_both_and_adds_linked_audio() {
        let mut raw = serde_json::json!([{
            "timeline": {"sequence": {"tracks": [
                {"id":"v1", "type":"video", "clips":[
                    {"id":"existing", "timeline_start":1.0, "timeline_end":8.0}
                ]},
                {"id":"a1", "type":"audio", "clips":[]}
            ]}}
        }]);

        let inserted = place_asset(&mut raw, 0, 3.0, 2.0, "asset-1", true, false, 42);
        let tracks = raw[0]["timeline"]["sequence"]["tracks"].as_array().unwrap();

        assert_eq!(inserted, vec!["drop_v_42", "drop_a_42"]);
        assert_eq!(tracks.len(), 3);
        assert_eq!(lane_ids(&raw, 0), vec!["existing"]);
        assert_eq!(lane_ids(&raw, 1), vec!["drop_v_42"]);
        assert_eq!(lane_ids(&raw, 2), vec!["drop_a_42"]);
        assert_eq!(tracks[1]["clips"][0]["timeline_start"], serde_json::json!(3.0));
        assert_eq!(tracks[1]["clips"][0]["link_id"], tracks[2]["clips"][0]["link_id"]);
    }

    #[test]
    fn dropped_image_uses_requested_empty_lane_and_stays_silent() {
        let mut raw = serde_json::json!([{
            "timeline": {"sequence": {"tracks": [
                {"id":"v1", "type":"video", "clips":[]},
                {"id":"a1", "type":"audio", "clips":[]}
            ]}}
        }]);

        let inserted = place_asset(&mut raw, 0, 4.5, 5.0, "still-1", false, true, 7);

        assert_eq!(inserted, vec!["drop_v_7"]);
        assert_eq!(lane_ids(&raw, 0), vec!["drop_v_7"]);
        assert!(lane_ids(&raw, 1).is_empty());
        assert_eq!(raw[0]["timeline"]["sequence"]["tracks"][0]["clips"][0]["timeline_end"], serde_json::json!(9.5));
    }

    #[test]
    fn fit_mode_is_explicit_and_survives_position_edits() {
        let mut raw = serde_json::json!([{
            "timeline": {"sequence": {"tracks": [{
                "id":"v1", "type":"overlay", "clips":[{"id":"logo"}]
            }]}}
        }]);
        let ids = vec!["logo".to_string()];

        set_fit_many(&mut raw, &ids, true);
        set_position_many(&mut raw, &ids, 0.1, 0.2, 0.3, 0.4);
        let clip = &raw[0]["timeline"]["sequence"]["tracks"][0]["clips"][0];
        assert_eq!(clip["fit"], "stretch");
        assert_eq!(clip["position"]["width"], 0.3);

        set_fit_many(&mut raw, &ids, false);
        let clip = &raw[0]["timeline"]["sequence"]["tracks"][0]["clips"][0];
        assert!(clip.get("fit").is_none());

        set_opacity_many(&mut raw, &ids, 0.375);
        let clip = &raw[0]["timeline"]["sequence"]["tracks"][0]["clips"][0];
        assert_eq!(clip["opacity"], 0.375);
        set_opacity_many(&mut raw, &ids, 1.0);
        let clip = &raw[0]["timeline"]["sequence"]["tracks"][0]["clips"][0];
        assert!(clip.get("opacity").is_none());
    }
}

/// 素材ドロップの「最上段より上」ゾーン: 最前面に空のビジュアルトラックを挿入する。
/// クリップMoveの move_group_to_new_top_track と同じ位置規則（front+1）。
pub fn insert_top_visual_track(raw: &mut Value) {
    let Some(tracks) = tracks_mut(raw) else { return };
    let at = tracks
        .iter()
        .enumerate()
        .filter(|(_, tr)| tr.get("type").and_then(|v| v.as_str()) != Some("audio"))
        .map(|(i, _)| i)
        .max()
        .map(|f| f + 1)
        .unwrap_or(0);
    tracks.insert(at, serde_json::json!({"type": "overlay", "clips": []}));
}
