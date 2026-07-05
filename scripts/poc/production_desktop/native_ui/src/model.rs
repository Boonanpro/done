//! Timeline document — the SAME contents.json Dan generates and the server exports.
//! (Business requirement: Dan must be able to read/write what the human edits.)

use serde::Deserialize;

#[derive(Debug, Deserialize)]
pub struct Root {
    pub timeline: TimelineWrap,
}
#[derive(Debug, Deserialize)]
pub struct TimelineWrap {
    pub sequence: Sequence,
}
#[derive(Debug, Default, Deserialize)]
pub struct Sequence {
    #[serde(default)]
    pub duration: f64,
    #[serde(default)]
    pub tracks: Vec<Track>,
}
#[derive(Debug, Deserialize)]
pub struct Track {
    #[serde(rename = "type", default)]
    pub kind: String,
    #[serde(default)]
    pub clips: Vec<Clip>,
    // lane controls (standard NLE header toggles)
    #[serde(default)]
    pub locked: bool,
    #[serde(default)]
    pub hidden: bool,
    #[serde(default)]
    pub muted: bool,
    #[serde(default)]
    pub solo: bool,
    // magnet (auto close gaps on delete): None = default (ON for the main video lane)
    #[serde(default)]
    pub magnet: Option<bool>,
}
#[derive(Debug, Clone, Deserialize)]
pub struct Clip {
    #[serde(default)]
    pub crop: Option<serde_json::Value>,
    #[serde(default)]
    pub region: Option<serde_json::Value>,
    // freeze-frame: room-relative path of the materialized PNG (Filmora-style: the still
    // IS an image file — no decoder is ever consulted, so it cannot wander)
    #[serde(default)]
    pub freeze_still: Option<String>,
    #[serde(default)]
    pub style: Option<serde_json::Value>,
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub asset_id: Option<String>,
    #[serde(default)]
    pub source_start: f64,
    #[serde(default)]
    pub source_end: Option<f64>,
    #[serde(default)]
    pub timeline_start: f64,
    #[serde(default)]
    pub timeline_end: f64,
    #[serde(default)]
    pub position: Option<Pos>,
    #[serde(default)]
    pub transform: Option<Tf>,
    #[serde(default)]
    pub effects: Vec<Effect>,
    #[serde(default)]
    pub text: Option<String>,
    #[serde(default)]
    pub link_id: Option<String>,
    #[serde(default = "one")]
    pub volume: f64,
}
#[derive(Debug, Clone, Copy, Deserialize)]
pub struct Pos {
    #[serde(default)]
    pub x: f64,
    #[serde(default)]
    pub y: f64,
    #[serde(default = "one")]
    pub width: f64,
    #[serde(default = "one")]
    pub height: f64,
}
#[derive(Debug, Clone, Copy, Deserialize)]
pub struct Tf {
    #[serde(default = "one")]
    pub scale: f64,
    #[serde(default)]
    pub x: f64,
    #[serde(default)]
    pub y: f64,
}
fn one() -> f64 {
    1.0
}
#[derive(Debug, Clone, Deserialize)]
pub struct Effect {
    #[serde(rename = "type", default)]
    pub kind: String,
    #[serde(default)]
    pub params: serde_json::Value,
}

/// Bake metadata ({key}.json, v7+) — everything the live matte compositor needs to place
/// the ORIGINAL frame into the bake's canvas space and rebuild the static card masks.
#[derive(Debug, Clone, Deserialize)]
pub struct PopMeta {
    pub canvas: [u32; 2],
    pub src_x: i32,
    pub src_y: i32,
    pub sw: u32,
    pub sh: u32,
    #[serde(rename = "box")]
    pub bbox: [i32; 4], // px, py, ow, oh (canvas coords)
    pub radius: i32,
    #[serde(default)]
    pub v: i32,
}

impl PopMeta {
    pub fn load(path: &str) -> Option<Self> {
        let txt = std::fs::read_to_string(path).ok()?;
        let m: PopMeta = serde_json::from_str(&txt).ok()?;
        (m.v >= 7 && m.canvas[0] > 0 && m.canvas[1] > 0 && m.sw > 0 && m.sh > 0).then_some(m)
    }
}

impl Clip {
    /// Effect-clip region (x, y, w, h canvas fractions), when this is a region effect.
    pub fn region_xywh(&self) -> Option<(f64, f64, f64, f64)> {
        let r = self.region.as_ref()?;
        let g = |k: &str| r.get(k).and_then(|v| v.as_f64()).unwrap_or(0.0);
        let (w, h) = (g("width"), g("height"));
        if w > 1e-3 && h > 1e-3 {
            Some((g("x").clamp(0.0, 1.0), g("y").clamp(0.0, 1.0), w.min(1.0), h.min(1.0)))
        } else {
            None
        }
    }
    /// Freeze-frame clip? (exporter convention: source_start >= source_end)
    pub fn is_freeze(&self) -> bool {
        self.source_end.map(|se| se <= self.source_start + 1e-6).unwrap_or(false)
    }
    /// Source time shown at timeline time t — a freeze clip holds its one frame.
    pub fn src_at(&self, t: f64) -> f64 {
        if self.is_freeze() {
            self.source_start
        } else {
            self.source_start + (t - self.timeline_start)
        }
    }
    /// Per-edge crop fractions (left, top, right, bottom), clamped like the exporter.
    pub fn crop_ltrb(&self) -> Option<(f64, f64, f64, f64)> {
        let c = self.crop.as_ref()?;
        let g = |k: &str| c.get(k).and_then(|v| v.as_f64()).unwrap_or(0.0).clamp(0.0, 0.9);
        let (l, t, r, b) = (g("left"), g("top"), g("right"), g("bottom"));
        if l + t + r + b > 1e-4 {
            Some((l, t, r, b))
        } else {
            None
        }
    }
    pub fn dur(&self) -> f64 {
        self.timeline_end - self.timeline_start
    }
    /// Pop-out v4+: (pv relative path, source offset = source_start - bake_start).
    pub fn popout(&self) -> Option<(String, f64)> {
        let (key, off) = self.popout_key()?;
        Some((format!("popout-cache/{key}.pv.mp4"), off))
    }
    /// The popout effect's params object, if this clip has one.
    pub fn popout_params(&self) -> Option<&serde_json::Value> {
        self.effects
            .iter()
            .find(|e| e.kind == "popout")
            .map(|e| &e.params)
    }
    /// The CARD box the popout was applied with (params.box, canvas fractions).
    pub fn popout_card_box(&self) -> Option<Pos> {
        let b = self.popout_params()?.get("box")?;
        Some(Pos {
            x: b.get("x")?.as_f64()?,
            y: b.get("y")?.as_f64()?,
            width: b.get("width")?.as_f64()?,
            height: b.get("height")?.as_f64()?,
        })
    }
    /// (overlay cache key, source offset into the baked files)
    pub fn popout_key(&self) -> Option<(String, f64)> {
        let e = self.effects.iter().find(|e| e.kind == "popout")?;
        let key = e.params.get("overlay_key")?.as_str()?;
        let bs = e.params.get("bake_start")?.as_f64()?;
        Some((key.to_string(), (self.source_start - bs).max(0.0)))
    }
    /// Display box in canvas fractions (position wins; else transform scale/pan; else full).
    pub fn display_box(&self) -> Pos {
        if let Some(p) = self.position {
            return p;
        }
        if let Some(t) = self.transform {
            let (s, tx, ty) = (t.scale, t.x, t.y);
            if (s - 1.0).abs() > 1e-4 || tx.abs() > 1e-4 || ty.abs() > 1e-4 {
                return Pos { x: (1.0 - s) / 2.0 + tx, y: (1.0 - s) / 2.0 + ty, width: s, height: s };
            }
        }
        Pos { x: 0.0, y: 0.0, width: 1.0, height: 1.0 }
    }
}

pub struct Doc {
    pub raw: serde_json::Value,
    pub contents_path: String,
    pub seq: Sequence,
    pub asset_dir: String,
    /// asset_id -> ORIGINAL file path (from assets.json local_path), when it exists on disk.
    pub originals: std::collections::HashMap<String, String>,
    pub asset_names: std::collections::HashMap<String, String>,
}

impl Doc {
    pub fn load(contents_path: &str, asset_dir: &str) -> anyhow::Result<Self> {
        let text = std::fs::read_to_string(contents_path)?;
        let raw: serde_json::Value = serde_json::from_str(&text)?;
        Self::from_raw(raw, contents_path, asset_dir)
    }

    /// Re-derive the typed view from a (possibly edited) raw document.
    pub fn from_raw(raw: serde_json::Value, contents_path: &str, asset_dir: &str) -> anyhow::Result<Self> {
        let roots: Vec<Root> = serde_json::from_value(raw.clone())?;
        let seq = roots
            .into_iter()
            .next()
            .map(|r| r.timeline.sequence)
            .unwrap_or_default();
        let dir = asset_dir.replace(char::from(92), "/");
        // originals from assets.json: preview decodes the SOURCE file (no proxy softness),
        // falling back to the proxy when the original is missing
        let mut originals = std::collections::HashMap::new();
        let mut asset_names = std::collections::HashMap::new();
        if let Ok(txt) = std::fs::read_to_string(format!("{dir}/assets.json")) {
            if let Ok(v) = serde_json::from_str::<serde_json::Value>(&txt) {
                for a in v.as_array().cloned().unwrap_or_default() {
                    let id = a.get("id").and_then(|x| x.as_str());
                    if let (Some(id), Some(name)) = (
                        id,
                        a.get("filename").or_else(|| a.get("name")).and_then(|x| x.as_str()),
                    ) {
                        asset_names.insert(id.to_string(), name.to_string());
                    }
                    let lp = a.get("local_path").and_then(|x| x.as_str());
                    if let (Some(id), Some(lp)) = (id, lp) {
                        if std::path::Path::new(lp).exists() {
                            originals.insert(id.to_string(), lp.replace(char::from(92), "/"));
                        }
                    }
                }
            }
        }
        Ok(Self { raw, contents_path: contents_path.to_string(), seq, asset_dir: dir, originals, asset_names })
    }

    /// Best source for QUALITY (original when available) vs SPEED (proxy: small, short GOP).
    pub fn asset_path_q(&self, asset_id: &str, original: bool) -> String {
        if original {
            if let Some(p) = self.originals.get(asset_id) {
                return p.clone();
            }
        }
        self.asset_path(asset_id)
    }
    pub fn asset_path(&self, asset_id: &str) -> String {
        format!("{}/{}_proxy.mp4", self.asset_dir, asset_id)
    }
    pub fn rel_path(&self, rel: &str) -> String {
        format!("{}/{}", self.asset_dir, rel)
    }
    pub fn duration(&self) -> f64 {
        let d = self
            .seq
            .tracks
            .iter()
            .flat_map(|t| t.clips.iter())
            .map(|c| c.timeline_end)
            .fold(0.0f64, f64::max);
        d.max(self.seq.duration)
    }
    /// Active visual clips at t, in STACKING ORDER (track array index = back-to-front).
    /// The first entry paints the background; later entries layer on top. No kind
    /// special-casing — a clip renders in front simply because its track is higher.
    pub fn active_video(&self, t: f64) -> (Option<&Clip>, Vec<&Clip>) {
        let mut layers: Vec<&Clip> = Vec::new();
        for tr in &self.seq.tracks {
            if tr.kind == "audio" || tr.hidden {
                continue; // audio lanes & hidden lanes don't paint — no role rules otherwise
            }
            for c in &tr.clips {
                if c.asset_id.is_none() || t < c.timeline_start || t >= c.timeline_end {
                    continue;
                }
                layers.push(c);
            }
        }
        let mut it = layers.into_iter();
        let base = it.next();
        (base, it.collect())
    }
    /// Is lane `ti` magnetic (delete = close the gap)? Explicit flag wins; the default is
    /// ON only for the MAIN video lane (the first video track = the storyline spine).
    pub fn is_magnet(&self, ti: usize) -> bool {
        let Some(tr) = self.seq.tracks.get(ti) else { return false };
        if let Some(m) = tr.magnet {
            return m;
        }
        tr.kind == "video"
            && self.seq.tracks.iter().position(|t| t.kind == "video") == Some(ti)
    }
    /// The lane whose 🔊/S flags govern an audio clip: its linked visual clip's lane when
    /// linked (unified A/V), else its own audio lane.
    pub fn audio_gov_track(&self, clip: &Clip, own: usize) -> usize {
        if let Some(l) = &clip.link_id {
            for (i, tr) in self.seq.tracks.iter().enumerate() {
                if tr.kind != "audio" && tr.clips.iter().any(|v| v.link_id.as_ref() == Some(l)) {
                    return i;
                }
            }
        }
        own
    }
    /// ALL audio-lane clips overlapping [t0, t1) — the mixer plays every one of them.
    pub fn active_audio_span(&self, t0: f64, t1: f64) -> Vec<(usize, &Clip)> {
        self.seq
            .tracks
            .iter()
            .enumerate()
            .filter(|(_, tr)| tr.kind == "audio")
            .flat_map(|(i, tr)| tr.clips.iter().map(move |c| (i, c)))
            .filter(|(_, c)| c.asset_id.is_some() && c.timeline_end > t0 && c.timeline_start < t1)
            .collect()
    }
    /// Active audio clip at t (first match).
    pub fn active_audio(&self, t: f64) -> Option<&Clip> {
        self.seq
            .tracks
            .iter()
            .filter(|tr| tr.kind == "audio")
            .flat_map(|tr| tr.clips.iter())
            .find(|c| c.asset_id.is_some() && t >= c.timeline_start && t < c.timeline_end)
    }
}
