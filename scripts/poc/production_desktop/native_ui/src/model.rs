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
}
#[derive(Debug, Clone, Deserialize)]
pub struct Clip {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub asset_id: Option<String>,
    #[serde(default)]
    pub source_start: f64,
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

impl Clip {
    pub fn dur(&self) -> f64 {
        self.timeline_end - self.timeline_start
    }
    /// Pop-out v4+: (pv relative path, source offset = source_start - bake_start).
    pub fn popout(&self) -> Option<(String, f64)> {
        let e = self.effects.iter().find(|e| e.kind == "popout")?;
        let key = e.params.get("overlay_key")?.as_str()?;
        let bs = e.params.get("bake_start")?.as_f64()?;
        Some((format!("popout-cache/{key}.pv.mp4"), (self.source_start - bs).max(0.0)))
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
    pub seq: Sequence,
    pub asset_dir: String,
}

impl Doc {
    pub fn load(contents_path: &str, asset_dir: &str) -> anyhow::Result<Self> {
        let text = std::fs::read_to_string(contents_path)?;
        let roots: Vec<Root> = serde_json::from_str(&text)?;
        let seq = roots
            .into_iter()
            .next()
            .map(|r| r.timeline.sequence)
            .unwrap_or_default();
        Ok(Self { seq, asset_dir: asset_dir.replace('\\', "/") })
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
    /// Active video-lane clip (base, bottom) and overlay clips (top) at time t.
    pub fn active_video(&self, t: f64) -> (Option<&Clip>, Vec<&Clip>) {
        let mut base = None;
        let mut overlays = Vec::new();
        for tr in &self.seq.tracks {
            if tr.kind != "video" && tr.kind != "overlay" {
                continue;
            }
            for c in &tr.clips {
                if c.asset_id.is_none() || t < c.timeline_start || t >= c.timeline_end {
                    continue;
                }
                if tr.kind == "video" {
                    base = Some(c);
                } else {
                    overlays.push(c);
                }
            }
        }
        (base, overlays)
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
