//! Serde model for the `/production-assets` timeline JSON (`contents.json`).
//!
//! This is the **single source of truth** for editing (MVP decision #2): Web, Desktop,
//! DAN, and export all read the same JSON. We deserialize the subset the engine needs and
//! tolerate unknown/extra fields. `schema_version` is surfaced for the future-migration
//! guard the plan calls for.

use serde::Deserialize;

/// Top of `contents.json` is a list; element 0 carries the timeline.
#[derive(Debug, Deserialize)]
pub struct Root {
    pub timeline: TimelineWrap,
}

#[derive(Debug, Deserialize)]
pub struct TimelineWrap {
    pub sequence: Sequence,
}

#[derive(Debug, Deserialize)]
pub struct Sequence {
    /// Schema/version marker (the plan: "schema version フィールドを入れる"). Present as
    /// `version` today; kept optional so older/newer payloads still parse.
    #[serde(default)]
    pub version: Option<serde_json::Value>,
    #[serde(default)]
    pub duration: f64,
    #[serde(default)]
    pub tracks: Vec<Track>,
}

#[derive(Debug, Deserialize)]
pub struct Track {
    /// "video" | "overlay" | "audio" | "caption" | "effect"
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
    /// PiP rectangle (overlay clips only), normalized 0..1 of the output frame.
    #[serde(default)]
    pub position: Option<Position>,
}

impl Clip {
    /// Timeline duration in seconds (`timeline_end - timeline_start`); matches poc1.
    pub fn duration_s(&self) -> f64 {
        self.timeline_end - self.timeline_start
    }
}

#[derive(Debug, Clone, Copy, Deserialize)]
pub struct Position {
    #[serde(default)]
    pub x: f64,
    #[serde(default)]
    pub y: f64,
    #[serde(default = "one")]
    pub width: f64,
    #[serde(default = "one")]
    pub height: f64,
}

fn one() -> f64 {
    1.0
}

/// Parse `contents.json` into the timeline `Sequence`. Mirrors `poc1.load_clips`:
/// element 0 → `timeline.sequence`.
pub fn parse_contents(path: &str) -> anyhow::Result<Sequence> {
    let text = std::fs::read_to_string(path)
        .map_err(|e| anyhow::anyhow!("read {path}: {e}"))?;
    let roots: Vec<Root> = serde_json::from_str(&text)
        .map_err(|e| anyhow::anyhow!("parse {path}: {e}"))?;
    let root = roots
        .into_iter()
        .next()
        .ok_or_else(|| anyhow::anyhow!("contents.json is an empty list"))?;
    Ok(root.timeline.sequence)
}
