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
    /// PiP fill mode for overlay clips: "cover" (default — keep the source's aspect ratio, crop
    /// overflow) or "stretch" (free-deform — scale to the box's width AND height, the legacy
    /// distorting behavior). Lets a per-wipe side-panel toggle opt back into manual deform.
    #[serde(default)]
    pub fit: Option<String>,
    /// Manual per-edge crop (fractions 0..1 of the PiP box) the user drags in the side panel: it
    /// trims that fraction off each edge of the wipe, and cover re-fits the source into what's
    /// left (undistorted). Lets the framing be hand-tuned without a deform toggle.
    #[serde(default)]
    pub crop: Option<Crop>,
    /// Caption text (caption clips only) — rendered as a GES text overlay.
    #[serde(default)]
    pub text: Option<String>,
    /// Opt-in per-clip effects (e.g. pop-out). Read generically so unknown effects don't break parsing.
    #[serde(default)]
    pub effects: Vec<Effect>,
    /// Optional explicit source path RELATIVE to the asset dir, overriding the normal
    /// asset_id → "{asset_id}_proxy.mp4" resolution. Used for generated pop-out clips whose source
    /// is an alpha ProRes .mov under `popout-cache/` — so a pop-out is just an ordinary (alpha)
    /// overlay clip that moves/scales/crops/trims/splits like any other, and the layer beneath shows
    /// through its transparent areas. None = resolve from asset_id as usual.
    #[serde(default)]
    pub src: Option<String>,
}

/// A per-clip effect. `params` carries effect-specific knobs; for pop-out the web side stores the
/// generated overlay file's cache key under `params.overlay_key` so the native engine can find it.
#[derive(Debug, Clone, Deserialize)]
pub struct Effect {
    #[serde(rename = "type", default)]
    pub kind: String,
    #[serde(default)]
    pub params: serde_json::Value,
}

impl Clip {
    /// If this clip has a prepared pop-out effect, the cache key of its overlay .webm (so the engine
    /// can composite that alpha layer full-frame instead of the plain wipe). None otherwise.
    pub fn popout_overlay_key(&self) -> Option<String> {
        let e = self.effects.iter().find(|e| e.kind == "popout")?;
        e.params.get("overlay_key")?.as_str().map(|s| s.to_string())
    }

    /// The pop-out bake window start (params.bake_start) when this clip carries a v4 pop-out:
    /// the bake covers a PADDED source range, so the file-relative inpoint is
    /// `source_start - bake_start`. None = legacy .mov bake (exact range, no offset).
    fn popout_bake_start(&self) -> Option<f64> {
        let e = self.effects.iter().find(|e| e.kind == "popout")?;
        e.params.get("bake_start")?.as_f64()
    }

    /// Source path (relative to the asset dir) this clip actually renders from: an explicit `src`
    /// wins; otherwise a clip carrying a prepared pop-out effect renders from its generated bake —
    /// v4 = `{key}.pv.mp4` (two-track color+alpha, HW-decodable via danpv://), legacy = the old
    /// ProRes `{key}.mov`. None → resolve from asset_id the normal way. This lets a pop-out render
    /// correctly straight from `contents.json` at load (which carries the effect, not a src), as
    /// well as from the editor's live wire (which sends `src`).
    pub fn effective_src(&self) -> Option<String> {
        if let Some(s) = &self.src {
            if !s.is_empty() {
                return Some(s.clone());
            }
        }
        let k = self.popout_overlay_key()?;
        let ext = if self.popout_bake_start().is_some() { ".pv.mp4" } else { ".mov" };
        Some(format!("popout-cache/{k}{ext}"))
    }

    /// The inpoint to use for this clip's actual source file. The editor's live wire sends `src`
    /// with an ALREADY file-relative source_start; the contents.json load path carries the raw
    /// asset-relative source_start + the pop-out effect, so a v4 pop-out shifts by bake_start.
    pub fn effective_source_start(&self) -> f64 {
        if self.src.as_deref().map(|s| !s.is_empty()).unwrap_or(false) {
            return self.source_start;
        }
        match (self.popout_overlay_key(), self.popout_bake_start()) {
            (Some(_), Some(bs)) => (self.source_start - bs).max(0.0),
            _ => self.source_start,
        }
    }

    /// Timeline duration in seconds (`timeline_end - timeline_start`); matches poc1.
    pub fn duration_s(&self) -> f64 {
        self.timeline_end - self.timeline_start
    }

    /// The box to feed the geometry chain: an explicit position wins; a clip that only has a
    /// CROP (e.g. a fullscreen clip the user trimmed edges off) uses the full frame so the
    /// crop still applies. None → no transform work at all.
    pub fn effective_position(&self) -> Option<Position> {
        if self.position.is_some() {
            return self.position;
        }
        if self.crop.is_some() {
            return Some(Position { x: 0.0, y: 0.0, width: 1.0, height: 1.0 });
        }
        None
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

/// Per-edge crop of the PiP box, each a fraction 0..1 of the box (top+bottom < 1, left+right < 1).
#[derive(Debug, Clone, Copy, Deserialize)]
pub struct Crop {
    #[serde(default)]
    pub top: f64,
    #[serde(default)]
    pub bottom: f64,
    #[serde(default)]
    pub left: f64,
    #[serde(default)]
    pub right: f64,
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
