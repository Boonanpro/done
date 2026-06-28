//! A1 in-process media engine for the production-desktop MVP.
//!
//! `Engine` builds a GES timeline from the `/production-assets` timeline JSON and exposes
//! the engine API (`load/seek/play/pause/apply_edit/get_state`). The Python harnesses
//! (poc1.py / poc3.py) stay as the parity oracle.

pub mod engine;
pub mod timeline_model;

pub use engine::{EditOp, EditResult, Engine, EngineState, LoadReport, SeekResult};
